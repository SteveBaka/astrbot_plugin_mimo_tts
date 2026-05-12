# -*- coding: utf-8 -*-
"""TTS parameter handlers: /emotion, /emotions, /speed, /pitch, /breath,
/stress, /dialect, /volume, /laughter, /pause.
"""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.constants import SUPPORTED_EMOTIONS


async def handle_emotion(plugin, event: AstrMessageEvent):
    """/emotion [情感名|auto|off]"""
    arg = plugin._parse_cmd(event, "/emotion")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        cur = uset["emotion"] or "(自动检测)"
        lines = [f"当前情感: {cur}", "", "支持的情感:"]
        for emo in SUPPORTED_EMOTIONS:
            lines.append(f"  {emo}")
        lines.append("")
        lines.append("用法: /emotion <情感名|auto|off>")
        yield MessageEventResult().message("\n".join(lines))
        return

    if arg == "off":
        plugin._get_user_settings(uid)["emotion"] = ""
        plugin._persist_current_state()
        yield MessageEventResult().message("[✓] 已关闭情感覆盖（自动检测）")
    elif arg == "auto":
        plugin._get_user_settings(uid)["emotion"] = "auto"
        plugin._persist_current_state()
        yield MessageEventResult().message("[✓] 已开启情感自动检测")
    elif arg in SUPPORTED_EMOTIONS:
        plugin._get_user_settings(uid)["emotion"] = arg
        plugin._persist_current_state()
        yield MessageEventResult().message(f"[✓] 情感已设置为: {arg}")
    else:
        yield MessageEventResult().message(
            f"[X] 不支持的情感: {arg}\n可用: {', '.join(SUPPORTED_EMOTIONS)}"
        )


async def handle_emotions(plugin, event: AstrMessageEvent):
    """List all supported emotions."""
    lines = ["支持的情感列表:", ""]
    for emo in SUPPORTED_EMOTIONS:
        lines.append(f"  • {emo}")
    lines.append(f"\n共 {len(SUPPORTED_EMOTIONS)} 种")
    yield MessageEventResult().message("\n".join(lines))


async def handle_speed(plugin, event: AstrMessageEvent):
    """/speed [0.5~2.0]"""
    arg = plugin._parse_cmd(event, "/speed")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        yield MessageEventResult().message(
            f"当前语速: {uset['speed']}\n用法: /speed <0.5~2.0>"
        )
        return

    try:
        val = max(0.5, min(2.0, float(arg)))
        plugin._get_user_settings(uid)["speed"] = val
        plugin._persist_current_state()
        yield MessageEventResult().message(f"[✓] 语速已设置为: {val}")
    except ValueError:
        yield MessageEventResult().message("[X] 请输入 0.5~2.0 之间的数值。")


async def handle_pitch(plugin, event: AstrMessageEvent):
    """/pitch [-12~+12]"""
    arg = plugin._parse_cmd(event, "/pitch")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        yield MessageEventResult().message(
            f"当前音高: {uset['pitch']}\n用法: /pitch <-12~+12>"
        )
        return

    try:
        val = max(-12, min(12, int(arg)))
        plugin._get_user_settings(uid)["pitch"] = val
        plugin._persist_current_state()
        yield MessageEventResult().message(f"[✓] 音高已设置为: {val}")
    except ValueError:
        yield MessageEventResult().message("[X] 请输入 -12~+12 之间的整数。")


def _toggle_on(arg: str) -> bool:
    return arg.lower() in ("on", "true", "1", "开")


async def handle_breath(plugin, event: AstrMessageEvent):
    """/breath [on|off]"""
    arg = plugin._parse_cmd(event, "/breath")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        state = "开" if uset["breath"] else "关"
        yield MessageEventResult().message(
            f"呼吸声: {state}\n用法: /breath <on|off>"
        )
        return

    val = _toggle_on(arg)
    plugin._get_user_settings(uid)["breath"] = val
    plugin._persist_current_state()
    yield MessageEventResult().message(f"[✓] 呼吸声已{'开启' if val else '关闭'}")


async def handle_stress(plugin, event: AstrMessageEvent):
    """/stress [on|off]"""
    arg = plugin._parse_cmd(event, "/stress")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        state = "开" if uset["stress"] else "关"
        yield MessageEventResult().message(
            f"重音模式: {state}\n用法: /stress <on|off>"
        )
        return

    val = _toggle_on(arg)
    plugin._get_user_settings(uid)["stress"] = val
    plugin._persist_current_state()
    yield MessageEventResult().message(f"[✓] 重音模式已{'开启' if val else '关闭'}")


async def handle_dialect(plugin, event: AstrMessageEvent):
    """/dialect [方言名|off] — 设置方言口音"""
    arg = plugin._parse_cmd(event, "/dialect")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        cur = uset["dialect"] or "(无)"
        yield MessageEventResult().message(
            f"当前方言: {cur}\n"
            "用法: /dialect <方言名|off>\n"
            "示例: /dialect 四川话、/dialect 粤语、/dialect 东北话、/dialect 台湾腔"
        )
        return

    if arg == "off":
        plugin._get_user_settings(uid)["dialect"] = ""
        plugin._persist_current_state()
        yield MessageEventResult().message("[✓] 已关闭方言口音")
    else:
        plugin._get_user_settings(uid)["dialect"] = arg
        plugin._persist_current_state()
        yield MessageEventResult().message(f"[✓] 方言已设置为: {arg}")


async def handle_volume(plugin, event: AstrMessageEvent):
    """/volume [轻声|正常|大声|off]"""
    arg = plugin._parse_cmd(event, "/volume")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        cur = uset["volume"] or "(正常)"
        yield MessageEventResult().message(
            f"当前音量: {cur}\n用法: /volume <轻声|正常|大声|off>"
        )
        return

    if arg == "off":
        plugin._get_user_settings(uid)["volume"] = ""
        plugin._persist_current_state()
        yield MessageEventResult().message("[✓] 音量已恢复为正常")
    else:
        plugin._get_user_settings(uid)["volume"] = arg
        plugin._persist_current_state()
        yield MessageEventResult().message(f"[✓] 音量已设置为: {arg}")


async def handle_laughter(plugin, event: AstrMessageEvent):
    """/laughter [on|off]"""
    arg = plugin._parse_cmd(event, "/laughter")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        state = "开" if uset["laughter"] else "关"
        yield MessageEventResult().message(
            f"笑声: {state}\n用法: /laughter <on|off>"
        )
        return

    val = _toggle_on(arg)
    plugin._get_user_settings(uid)["laughter"] = val
    plugin._persist_current_state()
    yield MessageEventResult().message(f"[✓] 笑声已{'开启' if val else '关闭'}")


async def handle_pause(plugin, event: AstrMessageEvent):
    """/pause [on|off]"""
    arg = plugin._parse_cmd(event, "/pause")
    uid, _ = plugin._get_event_settings(event)

    if not arg:
        uset = plugin._get_user_settings(uid)
        state = "开" if uset["pause"] else "关"
        yield MessageEventResult().message(
            f"停顿模式: {state}\n用法: /pause <on|off>"
        )
        return

    val = _toggle_on(arg)
    plugin._get_user_settings(uid)["pause"] = val
    plugin._persist_current_state()
    yield MessageEventResult().message(f"[✓] 停顿模式已{'开启' if val else '关闭'}")
