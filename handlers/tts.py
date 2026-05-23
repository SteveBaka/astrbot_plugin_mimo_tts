# -*- coding: utf-8 -*-
"""TTS synthesis handlers: /mimo_say, /sing, /ttsraw."""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import Record

from ._helpers import parse_mimo_say_options


async def handle_mimo_say(plugin, event: AstrMessageEvent):
    """/mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]
                    [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]
    """
    import re

    raw = str(event.message_str or "").strip()
    first, sep, remainder = raw.partition(" ")
    normalized_first = first.lstrip("/").split("@", 1)[0].strip().lower()
    if normalized_first == "mimo_say":
        text = remainder.strip()
    else:
        text = re.sub(
            rf"^/?mimo_say(?:@[^\s]+)?\s*",
            "",
            raw,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
    if not text:
        yield MessageEventResult().message(
            "用法: /mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色] "
            "[-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]"
        )
        return

    uid, uset = plugin._get_event_settings(event)
    text, overrides, emo_override = parse_mimo_say_options(plugin, text, uid, uset)

    if not text:
        yield MessageEventResult().message("文本内容不能为空。")
        return

    try:
        audio_path = await plugin._do_tts(
            text,
            uid,
            emotion_override=emo_override,
            settings_override=overrides or None,
        )
        if audio_path:
            r = MessageEventResult()
            r.chain.append(Record.fromFileSystem(str(audio_path)))
            yield r
        else:
            yield MessageEventResult().message("TTS 合成失败。")
    except Exception as e:
        yield MessageEventResult().message(f"! {e}")


async def handle_sing(plugin, event: AstrMessageEvent):
    """/sing [-音色名] <歌词>"""
    from astrbot.api import logger

    text = plugin._parse_cmd(event, "/sing")
    if not text:
        yield MessageEventResult().message(
            "用法: /sing <歌词>（单次触发，执行后自动恢复原设置）\n"
            "     /sing -冰糖 <歌词> — 使用冰糖音色唱歌"
        )
        return

    uid, _ = plugin._get_event_settings(event)

    overrides: dict = {"sing": True}
    sing_voice = ""

    if text.startswith("-") and len(text) > 1:
        parts = text[1:].split(maxsplit=1)
        candidate = parts[0].strip() if parts else ""
        if candidate:
            sing_voice = candidate
            text = parts[1].strip() if len(parts) > 1 else ""
            logger.debug(
                "[MimoTTSPlugin] uid=%s cmd_sing sing_voice_override=%s",
                uid,
                candidate,
            )

    if not text:
        yield MessageEventResult().message(
            "用法: /sing <歌词>（单次触发，执行后自动恢复原设置）\n"
            "     /sing -冰糖 <歌词> — 使用冰糖音色唱歌"
        )
        return

    if sing_voice:
        overrides["sing_voice_override"] = sing_voice

    try:
        audio_path = await plugin._do_tts(text, uid, settings_override=overrides)
        if audio_path:
            r = MessageEventResult()
            r.chain.append(Record.fromFileSystem(str(audio_path)))
            yield r
        else:
            yield MessageEventResult().message("唱歌合成失败。")
    except Exception as e:
        yield MessageEventResult().message(f"! {e}")


async def handle_ttsraw(plugin, event: AstrMessageEvent):
    """/ttsraw <文本> — 不带情感的纯文本合成"""
    text = plugin._parse_cmd(event, "/ttsraw")
    if not text:
        yield MessageEventResult().message("用法: /ttsraw <文本>")
        return
    uid, _ = plugin._get_event_settings(event)
    try:
        audio_path = await plugin._do_tts(text, uid)
        if audio_path:
            r = MessageEventResult()
            r.chain.append(Record.fromFileSystem(str(audio_path)))
            yield r
        else:
            yield MessageEventResult().message("TTS 合成失败。")
    except Exception as e:
        yield MessageEventResult().message(f"! {e}")
