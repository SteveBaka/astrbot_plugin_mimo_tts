# -*- coding: utf-8 -*-
"""Voice management handlers: /voice, /voices, /ttsswitch, /voiceclone, /voicegen."""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.constants import (
    AUDIO_MIN_VALID_SIZE,
    AUDIO_VALID_EXTENSIONS,
    MIMO_VOICE_LIST,
)


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
        yield MessageEventResult().message(
            "用法: /voicegen <ID> <音色描述>\n"
            '示例: /voicegen my_voice "温柔甜美的年轻女声，语速适中"'
        )
        return

    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        yield MessageEventResult().message("用法: /voicegen <ID> <音色描述>")
        return

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
        plugin.config.set("design_enabled", True)
        plugin.config.design_voice_id = vid
        plugin.config.set("design_voice_description", desc)
        uid, _ = plugin._get_event_settings(event)
        plugin._get_user_settings(uid)["voice"] = vid
        plugin._persist_current_state()
        yield MessageEventResult().message(
            f"[✓] 已登记设计音色: {vid}\n"
            f"  可用 /ttsswitch design 切换到设计模式\n"
            f"  也可用 /voice {vid} 将这条描述设为当前设计音色\n"
            f"  配置面板已同步更新描述信息"
        )
    else:
        yield MessageEventResult().message(
            f"[X] 设计音色登记失败：{provider.last_error or '请查看日志。'}"
        )
