# -*- coding: utf-8 -*-
"""Preset handlers: /preset, /presetlist."""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.constants import TTS_PRESETS


async def handle_preset(plugin, event: AstrMessageEvent):
    """/preset [预设名] — 查看/应用预设"""
    arg = plugin._parse_cmd(event, "/preset")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        lines = ["预设列表:", ""]
        for name, p in TTS_PRESETS.items():
            lines.append(
                f"  {name:18s}  情感={p['emotion']:10s}  语速={p['speed']}  音高={p['pitch']:+d}  音色={p['voice']}"
            )
        lines.append("")
        lines.append("用法: /preset <预设名>  （如 /preset bedtime_story）")
        yield MessageEventResult().message("\n".join(lines))
        return

    if arg not in TTS_PRESETS:
        yield MessageEventResult().message(
            f"[X] 未知预设: {arg}\n用 /presetlist 查看所有预设"
        )
        return

    preset = TTS_PRESETS[arg]
    uset = plugin._get_user_settings(uid)
    uset["emotion"] = preset["emotion"]
    uset["speed"] = preset["speed"]
    uset["pitch"] = preset["pitch"]
    uset["breath"] = preset["breath"]
    uset["stress"] = preset["stress"]
    uset["voice"] = plugin._resolve_voice(preset["voice"])
    plugin._persist_current_state()

    yield MessageEventResult().message(
        f"[✓] 已应用预设: {arg}\n"
        f"  情感={preset['emotion']}  语速={preset['speed']}  音高={preset['pitch']:+d}\n"
        f"  呼吸={'开' if preset['breath'] else '关'}  重音={'开' if preset['stress'] else '关'}  音色={preset['voice']}"
    )


async def handle_presetlist(plugin, event: AstrMessageEvent):
    """List all TTS presets."""
    lines = ["所有预设:", ""]
    for name, p in TTS_PRESETS.items():
        lines.append(f"  {name}")
        lines.append(
            f"    情感={p['emotion']}  语速={p['speed']}  音高={p['pitch']:+d}  音色={p['voice']}  呼吸={'✓' if p['breath'] else '✗'}  重音={'✓' if p['stress'] else '✗'}"
        )
    lines.append("\n用法: /preset <预设名> 应用预设")
    yield MessageEventResult().message("\n".join(lines))
