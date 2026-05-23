# -*- coding: utf-8 -*-
"""Settings and info query handlers.

Provides commands for audio format configuration, runtime status inspection,
and plugin metadata display:
  /ttsformat  — Set audio output format (mp3/wav/ogg)
  /ttsconfig  — View current session configuration and provider status
  /ttsinfo    — Display plugin version and capability summary
"""

from __future__ import annotations

from pathlib import Path

import yaml
from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.constants import (
    MIMO_VOICE_LIST,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_EMOTIONS,
    TTS_PRESETS,
)


async def handle_ttsformat(plugin, event: AstrMessageEvent):
    """/ttsformat [mp3|wav|ogg] — 设置音频输出格式"""
    arg = plugin._parse_cmd(event, "/ttsformat")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        cur = plugin._get_effective_audio_format(uid)
        source = "当前对话" if uid in plugin._user_format else "插件全局默认"
        yield MessageEventResult().message(
            f"当前格式: {cur}\n"
            f"当前生效来源: {source}\n"
            f"支持的格式: {', '.join(SUPPORTED_AUDIO_FORMATS)}\n"
            f"用法: /ttsformat <格式>"
        )
        return

    if arg.lower() not in SUPPORTED_AUDIO_FORMATS:
        yield MessageEventResult().message(
            f"[X] 不支持的格式: {arg}\n支持: {', '.join(SUPPORTED_AUDIO_FORMATS)}"
        )
        return

    plugin._user_format[uid] = arg.lower()
    plugin._persist_current_state()
    yield MessageEventResult().message(f"[✓] 音频格式已设置为: {arg}")


async def handle_ttsconfig(plugin, event: AstrMessageEvent):
    """/ttsconfig — 查看当前会话配置"""
    arg = plugin._parse_cmd(event, "/ttsconfig")

    if arg == "reset":
        plugin._reset_persistent_state()
        yield MessageEventResult().message("[✓] 所有个人设置已重置。")
        return

    provider = plugin._ensure_provider()
    status = "[✓] 正常" if provider else "[X] 未配置"

    uid, _ = plugin._get_event_settings(event)
    uset = plugin._get_user_settings(uid)

    lines = [
        f"MiMO TTS 配置状态: {status}",
        f"模型: {plugin.config.get('model', 'mimo-v2.5-tts')}",
        f"API: {plugin.config.get('api_base_url', 'https://api.xiaomimimo.com/v1')[:80]}",
        f"持久化文件: {plugin._state_file}",
        "",
        "── 你的当前设置 ──",
        f"情感: {uset['emotion'] or '(自动)'}",
        f"语速: {uset['speed']}  音高: {uset['pitch']:+d}",
        f"呼吸: {'开' if uset['breath'] else '关'}  重音: {'开' if uset['stress'] else '关'}",
        f"方言: {uset['dialect'] or '(无)'}  音量: {uset['volume'] or '(正常)'}",
        f"笑声: {'开' if uset['laughter'] else '关'}  停顿: {'开' if uset['pause'] else '关'}",
        f"当前对话自动 TTS: {'开' if uset.get('tts_enabled', True) else '关'}",
        f"当前对话文字同步: {'开' if plugin._should_send_text_with_tts(uid) else '关'}",
        f"音色: {uset['voice']}",
        f"输出模式: {plugin._tts_mode_label(plugin._resolve_tts_mode(uid))} ({plugin._resolve_tts_mode(uid)})",
        f"格式: {plugin._get_effective_audio_format(uid)}",
        f"唱歌默认音色: {plugin.config.sing_voice or '(跟随当前音色)'}",
        "",
        "用 /sing [-音色名] <歌词> 触发唱歌",
        "用 /preset <预设名> 快速切换风格",
        "用 /tts_help 快速查看指令",
    ]
    yield MessageEventResult().message("\n".join(lines))


async def handle_ttsinfo(plugin, event: AstrMessageEvent):
    """/ttsinfo — 查看插件信息"""
    _version = "unknown"
    try:
        _meta = Path(__file__).resolve().parent.parent / "metadata.yaml"
        if _meta.exists():
            with open(_meta, "r", encoding="utf-8") as _f:
                _version = str(yaml.safe_load(_f).get("version", "")).strip() or "unknown"
    except Exception:
        pass

    lines = [
        f"astrbot_plugin_mimo_tts v{_version}",
        "",
        "基于 MiMO-V2.5-TTS 的精细化语音合成插件",
        "",
        f"支持情感: {len(SUPPORTED_EMOTIONS)} 种",
        f"内置音色: {len(MIMO_VOICE_LIST)} 种",
        f"内置预设: {len(TTS_PRESETS)} 个",
        "控制维度: 情感 语速 音高 呼吸声 重音 方言 音量 笑声 停顿（唱歌仅 /sing）",
        "",
        "主要命令:",
        "  /mimo_say <文本>  - 即时合成",
        "  /tts_off  - 关闭当前对话自动 TTS",
        "  /text on|off  - 切换当前对话文字同步",
        "  /sing <歌词>  - 唱歌模式",
        "  /preset <名>  - 应用预设",
        "  /ttsconfig  - 查看配置",
    ]
    yield MessageEventResult().message("\n".join(lines))
