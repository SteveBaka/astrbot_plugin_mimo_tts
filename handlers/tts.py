# -*- coding: utf-8 -*-
"""TTS synthesis handlers: /mimo_say, /sing, /ttsraw."""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import Record

from ._helpers import _unquote, parse_mimo_say_options, parse_value_flags

SING_USAGE = (
    "用法: /sing <歌词>\n"
    "     /sing -音色名 <歌词> — 指定音色唱歌，如 /sing -冰糖 小星星\n"
    "     /sing -s 风格组 <歌词> — 用风格组唱歌，如 /sing -s 小雪 晚风轻拂\n"
    "     /sing -p \"提示词\" <歌词> — 本次按提示词唱（含空格请加引号）\n"
    "     /sing (风格) <歌词> — 括号风格简写，如 /sing (温柔) 晚风轻拂\n"
    "参数可组合: /sing -s 小雪 -p 欢快地 <歌词>（提示词覆盖组内风格描述）"
)


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
            r"^/?mimo_say(?:@[^\s]+)?\s*",
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
    """/sing [-音色名] [-s 风格组] [-p 提示词] <歌词>，也支持 (风格) 括号简写"""
    from astrbot.api import logger

    text = plugin._parse_cmd(event, "/sing")
    if not text:
        yield MessageEventResult().message(SING_USAGE)
        return

    uid, _ = plugin._get_event_settings(event)

    # 统一解析：-p/-s 取值 flag（顺序无关、引号跨空格）+ 正文前裸 -token（音色名）
    lyrics, opts, bare = parse_value_flags(text, {"p", "s"}, bare_until_content=True)

    overrides: dict = {"sing": True}
    sing_voice = ""
    if bare and len(bare[0]) > 1:
        sing_voice = _unquote(bare[0][1:])
        logger.debug(
            "[MimoTTSPlugin] uid=%s cmd_sing sing_voice_override=%s", uid, sing_voice
        )
    if opts.get("s"):
        overrides["sing_style_override"] = opts["s"].strip()[:20]
    if opts.get("p"):
        overrides["sing_prompt_override"] = opts["p"].strip()[:200]

    if not lyrics:
        yield MessageEventResult().message(SING_USAGE)
        return

    if sing_voice:
        overrides["sing_voice_override"] = sing_voice

    try:
        audio_path = await plugin._do_tts(lyrics, uid, settings_override=overrides)
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
