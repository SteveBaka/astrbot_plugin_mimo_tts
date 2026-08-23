# -*- coding: utf-8 -*-
"""Voice management handlers: /voice, /voices, /ttsswitch, /voiceclone, /voicegen."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.constants import (
    AUDIO_MIN_VALID_SIZE,
    AUDIO_VALID_EXTENSIONS,
    MIMO_VOICE_LIST,
)
from ..core.style_lib import match_style_entry_by_name


async def handle_voice(plugin, event: AstrMessageEvent):
    """/voice [音色名]"""
    arg = plugin._parse_cmd(event, "/voice")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        lines = [f"当前音色: {uset['voice']}", "", "内置音色:"]
        for v in MIMO_VOICE_LIST:
            lines.append(
                f"  {v['id']:10s} {v['name']}  ({v['gender']}声 {v['style']})"
            )
        lines.append("")
        lines.append("用法: /voice <音色ID>")
        yield MessageEventResult().message("\n".join(lines))
        return

    resolved = plugin._resolve_voice(arg)
    plugin._get_user_settings(uid)["voice"] = resolved
    plugin._persist_current_state()
    yield MessageEventResult().message(f"[✓] 音色已切换为: {resolved}")


async def handle_voices(plugin, event: AstrMessageEvent):
    """List all built-in voices."""
    lines = ["MiMO 内置音色:", ""]
    for v in MIMO_VOICE_LIST:
        lines.append(
            f"  {v['id']:10s} {v['name']}  ({v['gender']}声 · {v['style']})"
        )
    lines.append(f"\n共 {len(MIMO_VOICE_LIST)} 种  |  用法: /voice <音色ID>")
    yield MessageEventResult().message("\n".join(lines))


async def handle_ttsswitch(plugin, event: AstrMessageEvent):
    """/ttsswitch [default|design|clone] — 切换 TTS 输出来源模式"""
    arg = plugin._parse_cmd(event, "/ttsswitch")
    uid, uset = plugin._get_event_settings(event)

    if not arg:
        mode = plugin._resolve_tts_mode(uid)
        lines = [
            f"当前输出模式: {plugin._tts_mode_label(mode)} ({mode})",
            f"配置默认模式: {plugin._tts_mode_label(plugin._normalize_tts_mode(plugin.config.tts_output_mode))}",
            f"默认音色: {plugin.config.default_voice}",
            f"设计音色ID: {plugin.config.design_voice_id or '(未配置)'}",
            f"克隆音色ID: {plugin.config.clone_voice_id or '(未配置)'}",
            "",
            "用法: /ttsswitch <default|design|clone>",
            "也支持中文: /ttsswitch 默认 /设计 /克隆",
        ]
        yield MessageEventResult().message("\n".join(lines))
        return

    mode = plugin._normalize_tts_mode(arg)
    uset["tts_mode"] = mode
    plugin._persist_current_state()
    yield MessageEventResult().message(
        f"[✓] TTS 输出模式已切换为: {plugin._tts_mode_label(mode)} ({mode})"
    )


async def handle_mimo_register_clone_tool(
    plugin,
    event: AstrMessageEvent,
    voice_id: str,
    audio_path: str,
    replace_existing: bool = False,
    style_prompt: str = "",
    audio_tags: str = "",
) -> str:
    """Register a local processed audio file as a named clone voice."""
    if not isinstance(replace_existing, bool):
        return "参数错误: replace_existing 必须是 JSON boolean true/false。"
    voice_id = str(voice_id or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_\-\u4e00-\u9fff]{1,50}", voice_id):
        return "参数错误: voice_id 只能包含中文、字母、数字、下划线或连字符，长度 1~50。"
    if any(item["id"] == voice_id for item in MIMO_VOICE_LIST):
        return "参数错误: voice_id 与内置音色 ID 冲突，请换一个克隆音色 ID。"

    existing = plugin._voice_manager.get_voice(voice_id)
    if existing and not replace_existing:
        return "参数错误: voice_id 已存在；需要更新时显式传 replace_existing=true。"
    if existing and str(existing.get("model", "")).lower() != "voiceclone":
        return "参数错误: voice_id 已被设计音色占用，请换一个 ID。"

    audio_path = str(audio_path or "").strip().strip('"').strip("'")
    if not audio_path:
        return "参数错误: audio_path 必须填写克隆目录中的本地音频路径。"
    try:
        source = plugin._resolve_clone_audio_path(audio_path)
    except Exception as clone_path_exc:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

            candidate = Path(audio_path).expanduser().resolve()
            temp_root = Path(get_astrbot_temp_path()).resolve()
            if not candidate.is_relative_to(temp_root):
                raise PermissionError(str(clone_path_exc))
            source = candidate
        except Exception as exc:
            return f"参数错误: audio_path 只能指向克隆目录或 AstrBot 临时附件目录中的现有文件。{exc}"
    if not source.is_file():
        return "参数错误: audio_path 不是有效文件。"
    if source.suffix.lower() not in AUDIO_VALID_EXTENSIONS:
        return "参数错误: 只接受 .mp3、.wav、.ogg、.opus、.pcm 音频文件；禁止传视频、压缩包、URL 或 Base64。"
    try:
        if source.stat().st_size < AUDIO_MIN_VALID_SIZE:
            return f"参数错误: 音频文件至少需要 {AUDIO_MIN_VALID_SIZE} 字节。"
    except OSError as exc:
        return f"参数错误: 读取音频文件大小失败: {exc}"

    style_prompt = str(style_prompt or "").strip()
    audio_tags = str(audio_tags or "").strip()
    if len(style_prompt) > 500 or len(audio_tags) > 500:
        return "参数错误: style_prompt 和 audio_tags 各最多 500 个字符。"

    clone_dir = plugin._data_dir / "clone"
    clone_dir.mkdir(parents=True, exist_ok=True)
    destination = clone_dir / f"{voice_id}{source.suffix.lower()}"
    try:
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    except OSError as exc:
        return f"克隆音频写入失败: {exc}"

    provider = plugin._ensure_provider()
    if not provider:
        return "API Key 未配置。"
    if not await provider.register_voice(voice_id, str(destination)):
        return f"克隆音色登记失败: {provider.last_error or '参考音频校验失败。'}"

    plugin._voice_manager.register_voice(
        voice_id,
        name=voice_id,
        model="voiceclone",
        audio_path=str(destination),
    )
    if style_prompt or audio_tags:
        plugin.config.upsert_clone_pool_entry(voice_id, style_prompt, audio_tags)
    plugin.config.set("clone_enabled", True)
    plugin.config.set("clone_voice_id", voice_id)
    uid, _ = plugin._get_event_settings(event)
    uset = plugin._get_user_settings(uid)
    uset["voice"] = voice_id
    uset["tts_mode"] = "clone"
    plugin._persist_current_state()
    action = "更新" if existing else "创建"
    return f"已{action}克隆音色 {voice_id}，参考音频已写入 {destination.name}，后续调用 mimo_clone_speak 时传 voice={voice_id}。"


async def handle_voiceclone(plugin, event: AstrMessageEvent):
    """/voiceclone <ID> <参考音频路径> — 克隆参考音频的声音"""
    try:
        arg = plugin._parse_cmd(event, "/voiceclone")
        if not arg:
            voices = [
                v
                for v in plugin._voice_manager.list_voices()
                if v.get("model") == "voiceclone"
            ]
            lines = [
                "用法:",
                "  /voiceclone <ID> <参考音频路径>  — 注册新克隆音色",
                "  /voiceclone <音色名>              — 切换到已注册的克隆音色",
                "  /voiceclone cancel <音色名>       — 取消注册某个克隆音色",
            ]
            if voices:
                lines.append("\n已注册的克隆音色:")
                for v in voices:
                    lines.append(f"  {v['voice_id']}")
            lines.append(f"\n说明: 推荐将参考音频放到 {plugin._data_dir / 'clone'}")
            yield MessageEventResult().message("\n".join(lines))
            return

        if arg.lower().startswith("cancel "):
            vid = arg[7:].strip()
            if not vid:
                yield MessageEventResult().message("用法: /voiceclone cancel <音色名>")
                return
            info = plugin._voice_manager.get_voice(vid)
            if not info or info.get("model") != "voiceclone":
                yield MessageEventResult().message(f"[X] 未找到已注册的克隆音色: {vid}")
                return
            plugin._voice_manager.remove_voice(vid)
            if str(plugin.config.clone_voice_id or "").strip() == vid:
                plugin.config.set("clone_voice_id", "")
            uid, _ = plugin._get_event_settings(event)
            us = plugin._get_user_settings(uid)
            if us.get("voice") == vid:
                us["voice"] = plugin.config.default_voice or "mimo_default"
                us["tts_mode"] = "default"
                plugin._persist_current_state()
                yield MessageEventResult().message(
                    f"[✓] 已取消注册克隆音色: {vid}\n"
                    f"  当前音色已自动回退为: {us['voice']}，输出模式已切回「默认」"
                )
            else:
                yield MessageEventResult().message(f"[✓] 已取消注册克隆音色: {vid}")
            return

        parts = arg.split(maxsplit=1)
        if len(parts) == 1:
            vid = parts[0]
            info = plugin._voice_manager.get_voice(vid)
            if not info or info.get("model") != "voiceclone":
                yield MessageEventResult().message(
                    f"[X] 未找到已注册的克隆音色: {vid}\n"
                    "请先使用 /voiceclone <ID> <参考音频路径> 注册"
                )
                return
            uid, _ = plugin._get_event_settings(event)
            uset = plugin._get_user_settings(uid)
            uset["voice"] = vid
            uset["tts_mode"] = "clone"
            plugin._persist_current_state()
            yield MessageEventResult().message(
                f"[✓] 已切换当前音色为: {vid}\n  输出模式已自动切换为「克隆」，可直接使用 TTS"
            )
            return

        vid, audio_path = parts[0], parts[1]
        audio_file = plugin._resolve_clone_audio_path(audio_path)

        if not audio_file.exists():
            plugin_audio_dir = plugin._data_dir / "clone"
            yield MessageEventResult().message(
                f"[X] 音频文件不存在: {audio_path}\n"
                f"可将参考音频放到 AstrBot 数据目录下: {plugin_audio_dir}\n"
                f"然后使用: /voiceclone {vid} clone/文件名"
            )
            return

        if not audio_file.is_file():
            yield MessageEventResult().message(f"[X] 不是有效文件: {audio_path}")
            return

        if audio_file.suffix.lower() not in AUDIO_VALID_EXTENSIONS:
            yield MessageEventResult().message(
                f"[X] 不支持的音频格式: {audio_file.suffix or '(无后缀)'}\n"
                f"支持: {', '.join(AUDIO_VALID_EXTENSIONS)}"
            )
            return

        if audio_file.stat().st_size < AUDIO_MIN_VALID_SIZE:
            yield MessageEventResult().message(
                f"[X] 音频文件过小，无法用于克隆（至少 {AUDIO_MIN_VALID_SIZE} 字节）"
            )
            return

        provider = plugin._ensure_provider()
        if not provider:
            yield MessageEventResult().message("API Key 未配置。")
            return

        yield MessageEventResult().message("⏳ 正在登记克隆参考音频…")

        ok = await provider.register_voice(vid, str(audio_file))
        if ok:
            plugin._voice_manager.register_voice(
                vid, name=vid, model="voiceclone", audio_path=str(audio_file)
            )
            plugin.config.set("clone_enabled", True)
            plugin.config.set("clone_voice_id", vid)
            uid, _ = plugin._get_event_settings(event)
            plugin._get_user_settings(uid)["voice"] = vid
            plugin._persist_current_state()
            yield MessageEventResult().message(
                f"[✓] 已登记克隆音色: {vid}\n"
                f"  参考音频: {audio_file}\n"
                f"  已自动切换当前音色为: {vid}\n"
                f"  可用 /ttsswitch clone 切到克隆输出模式"
            )
        else:
            yield MessageEventResult().message(
                f"[X] 克隆参考音频登记失败：{provider.last_error or '请查看日志。'}"
            )
    except Exception as e:
        yield MessageEventResult().message(f"! {e}")


async def handle_voicegen(plugin, event: AstrMessageEvent):
    """/voicegen <ID> <描述文本> — 用文字描述生成全新音色"""
    arg = plugin._parse_cmd(event, "/voicegen")
    if not arg:
        voices = [
            v
            for v in plugin._voice_manager.list_voices()
            if v.get("model") == "voicedesign"
        ]
        lines = [
            "用法:",
            "  /voicegen <ID> <音色描述>  — 注册新设计音色（描述填示例池分类名如「温柔甜美」"
            "自动启用完整词表提示+画面感例句）",
            "  /voicegen <分类名>         — 示例池分类名一键注册并切换设计音色（如 /voicegen 温柔甜美）",
            "  /voicegen <音色名>         — 切换到已注册的设计音色",
            "  /voicegen cancel <音色名>  — 取消注册某个设计音色",
        ]
        if voices:
            lines.append("\n已注册的设计音色:")
            for v in voices:
                lines.append(f"  {v['voice_id']}")
        yield MessageEventResult().message("\n".join(lines))
        return

    parts = arg.split(maxsplit=1)

    # /voicegen cancel <音色名> — 取消注册设计音色（当前音色自动回退）
    if arg.lower().startswith("cancel "):
        vid = arg[7:].strip()
        if not vid:
            yield MessageEventResult().message("用法: /voicegen cancel <音色名>")
            return
        info = plugin._voice_manager.get_voice(vid)
        if not info or info.get("model") != "voicedesign":
            yield MessageEventResult().message(f"[X] 未找到已注册的设计音色: {vid}")
            return
        plugin._voice_manager.remove_voice(vid)
        if str(plugin.config.design_voice_id or "").strip() == vid:
            plugin.config.design_voice_id = ""
        uid, _ = plugin._get_event_settings(event)
        us = plugin._get_user_settings(uid)
        if us.get("voice") == vid:
            us["voice"] = plugin.config.default_voice or "mimo_default"
            us["tts_mode"] = "default"
            plugin._persist_current_state()
            yield MessageEventResult().message(
                f"[✓] 已取消注册设计音色: {vid}\n"
                f"  当前音色已自动回退为: {us['voice']}，输出模式已切回「默认」"
            )
        else:
            yield MessageEventResult().message(f"[✓] 已取消注册设计音色: {vid}")
        return

    # /voicegen <音色名> — 切换到已注册的设计音色；
    # 未注册但命中示例池分类名时一键注册并切换（§14.5 方案 A）
    if len(parts) == 1:
        vid = parts[0]
        info = plugin._voice_manager.get_voice(vid)
        if not info or info.get("model") != "voicedesign":
            entry = match_style_entry_by_name(vid, plugin.config.style_examples)
            if not entry:
                yield MessageEventResult().message(
                    f"[X] 未找到已注册的设计音色: {vid}\n"
                    "请先使用 /voicegen <ID> <音色描述> 注册，"
                    "或直接填 style_examples 分类名（如 温柔甜美）一键注册"
                )
                return
            provider = plugin._ensure_provider()
            if not provider:
                yield MessageEventResult().message("API Key 未配置。")
                return
            ok = await provider.design_voice(vid, vid, model=plugin.config.design_model)
            if not ok:
                yield MessageEventResult().message(
                    f"[X] 设计音色登记失败：{provider.last_error or '请查看日志。'}"
                )
                return
            plugin._voice_manager.register_voice(
                vid, name=vid, model="voicedesign", description=vid
            )
            # v2.2.9：写入配置「设计音色风格控制池」（与配置面板联动权威数据源）
            plugin.config.upsert_design_pool_entry(vid, vid)
            plugin.config.set("design_enabled", True)
            plugin.config.design_voice_id = vid
            plugin.config.set("design_voice_description", vid)
            uid, _ = plugin._get_event_settings(event)
            uset = plugin._get_user_settings(uid)
            uset["voice"] = vid
            uset["tts_mode"] = "design"
            plugin._persist_current_state()
            yield MessageEventResult().message(
                f"[✓] 已一键注册设计音色: {vid}（示例池分类名 · 方案 A）\n"
                f"  已切换当前音色为: {vid}，输出模式「设计」\n"
                "  完整词表提示与画面感例句将随示例池条目自动生效"
            )
            return
        uid, _ = plugin._get_event_settings(event)
        uset = plugin._get_user_settings(uid)
        uset["voice"] = vid
        uset["tts_mode"] = "design"
        plugin._persist_current_state()
        yield MessageEventResult().message(
            f"[✓] 已切换当前音色为: {vid}\n  输出模式已自动切换为「设计」，可直接使用 TTS"
        )
        return

    # /voicegen <ID> <描述文本> — 注册新设计音色
    vid, desc = parts[0], parts[1]

    provider = plugin._ensure_provider()
    if not provider:
        yield MessageEventResult().message("API Key 未配置。")
        return

    yield MessageEventResult().message("⏳ 正在登记设计音色描述…")

    ok = await provider.design_voice(vid, desc, model=plugin.config.design_model)
    if ok:
        plugin._voice_manager.register_voice(
            vid, name=vid, model="voicedesign", description=desc
        )
        # v2.2.9：写入配置「设计音色风格控制池」（与配置面板联动权威数据源）
        plugin.config.upsert_design_pool_entry(vid, desc)
        plugin.config.set("design_enabled", True)
        plugin.config.design_voice_id = vid
        plugin.config.set("design_voice_description", desc)
        uid, _ = plugin._get_event_settings(event)
        uset = plugin._get_user_settings(uid)
        uset["voice"] = vid
        uset["tts_mode"] = "design"
        plugin._persist_current_state()
        hint = ""
        if match_style_entry_by_name(desc, plugin.config.style_examples):
            hint = (
                "\n  已识别示例池分类名（方案 A）：完整词表提示与"
                "画面感例句将随示例池条目自动生效"
            )
        yield MessageEventResult().message(
            f"[✓] 已登记设计音色: {vid}\n"
            f"  输出模式已自动切换为「设计」，可直接使用 TTS\n"
            f"  配置面板已同步更新描述信息{hint}"
        )
    else:
        yield MessageEventResult().message(
            f"[X] 设计音色登记失败：{provider.last_error or '请查看日志。'}"
        )
