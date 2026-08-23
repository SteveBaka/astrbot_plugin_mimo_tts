# -*- coding: utf-8 -*-
"""TTS synthesis handlers: /mimo_say, /sing, /ttsraw."""

from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult
from astrbot.api.message_components import Record

from ..core.constants import MIMO_VOICE_LIST, SUPPORTED_AUDIO_FORMATS, SUPPORTED_EMOTIONS
from ._helpers import _unquote, parse_mimo_say_options, parse_value_flags

SING_USAGE = (
    "用法: /sing <歌词>\n"
    "     /sing -音色名 <歌词> — 指定音色唱歌，如 /sing -冰糖 小星星\n"
    "     /sing -s 风格组 <歌词> — 用风格组唱歌，如 /sing -s 小雪 晚风轻拂\n"
    "     /sing -p \"提示词\" <歌词> — 本次按提示词唱（含空格请加引号）\n"
    "     /sing (风格) <歌词> — 括号风格简写，如 /sing (温柔) 晚风轻拂\n"
    "参数可组合: /sing -s 小雪 -p 欢快地 <歌词>（提示词覆盖组内风格描述）"
)

CLONE_OUTPUT_FORMATS: tuple[str, ...] = ("mp3", "flac", "m4a", "wav", "ogg")


async def handle_mimo_speak_tool(
    plugin,
    event: AstrMessageEvent,
    text: str,
    emotion: str = "",
    voice: str = "",
    speed: float = 0,
    pitch: int = 999,
    breath: bool | None = None,
    stress: bool | None = None,
    laughter: bool | None = None,
    pause: bool | None = None,
    dialect: str = "",
    volume: str = "",
    audio_format: str = "",
    tts_mode: str = "default",
    style: str = "",
    design_description: str = "",
    clone_style_prompt: str = "",
    clone_audio_tags: str = "",
    clone_only: bool = False,
    design_only: bool = False,
    standard_only: bool = False,
) -> str:
    """Validate one-shot LLM TTS arguments and send the generated audio."""
    text = str(text or "").strip()
    if not 2 <= len(text) <= 500:
        return "参数错误: text 必须是 2~500 字的正文。"

    emotion = str(emotion or "").strip().lower()
    if emotion and emotion not in (*SUPPORTED_EMOTIONS, "auto", "off"):
        allowed = ", ".join((*SUPPORTED_EMOTIONS, "auto", "off"))
        return f"参数错误: emotion 只能是 {allowed}。"

    voice = str(voice or "").strip()
    builtin_voices = {item["id"] for item in MIMO_VOICE_LIST}
    if standard_only and not voice:
        configured_voice = str(plugin.config.default_voice or "").strip()
        voice = configured_voice if configured_voice in builtin_voices else "mimo_default"
    if design_only and not voice:
        configured_design = str(plugin.config.design_voice_id or "").strip()
        design_info = plugin._voice_manager.get_voice(configured_design) or {}
        if str(design_info.get("model", "")).lower() == "voicedesign":
            voice = configured_design
        elif not str(design_description or "").strip():
            design_description = str(plugin.config.design_voice_description or "").strip()
    if clone_only and not voice:
        return "参数错误: voice 必须填写已登记的本地克隆音色 ID。"
    if clone_only:
        clone_info = plugin._voice_manager.get_voice(voice) or {}
        if str(clone_info.get("model", "")).lower() != "voiceclone":
            return "参数错误: voice 必须是已登记的克隆音色 ID；请先调用 mimo_list_clone_voices。"
        if not plugin._voice_manager.get_clone_audio_path(voice):
            return "参数错误: voice 对应的本地参考音频不可用，请重新登记该克隆音色。"
    elif design_only and voice:
        design_info = plugin._voice_manager.get_voice(voice) or {}
        if str(design_info.get("model", "")).lower() != "voicedesign":
            return "参数错误: voice 必须是已登记的设计音色 ID。"
    elif standard_only and voice not in builtin_voices:
        return "参数错误: 普通语音工具只能使用内置音色，请调用 mimo_design_speak 或 mimo_clone_speak。"
    elif voice:
        registered_voices = {
            item.get("voice_id", "") for item in plugin._voice_manager.list_voices()
        }
        if voice not in builtin_voices and voice not in registered_voices:
            return "参数错误: voice 必须是内置音色 ID 或已注册音色 ID；禁止传 URL、本地路径、Base64 或未注册名称。"

    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        return "参数错误: speed 必须是 number；0 表示继承，实际值范围为 0.5~2.0。"
    if speed != 0 and not 0.5 <= speed <= 2.0:
        return "参数错误: speed 只能传 0（继承）或 0.5~2.0。"

    if isinstance(pitch, bool) or not isinstance(pitch, (int, float)):
        return "参数错误: pitch 必须是 number；999 表示继承，实际值为 -12~12 的整数。"
    if pitch == 999 and isinstance(pitch, int):
        pass
    elif not float(pitch).is_integer() or not -12 <= pitch <= 12:
        return "参数错误: pitch 只能传 999（继承）或 -12~12 的整数。"

    for name, value in (
        ("breath", breath),
        ("stress", stress),
        ("laughter", laughter),
        ("pause", pause),
    ):
        if value is not None and not isinstance(value, bool):
            return f"参数错误: {name} 必须是 JSON boolean true/false；禁止传 on/off、开/关或 1/0。"

    dialect = str(dialect or "").strip()
    if len(dialect) > 20:
        return "参数错误: dialect 最多 20 个字符，传 off 可关闭。"

    volume = str(volume or "").strip()
    if volume not in ("", "轻声", "正常", "大声", "off"):
        return "参数错误: volume 只能是 轻声、正常、大声、off 或空字符串。"

    audio_format = str(audio_format or "").strip().lower()
    allowed_audio_formats = CLONE_OUTPUT_FORMATS if clone_only else SUPPORTED_AUDIO_FORMATS
    if audio_format and audio_format not in allowed_audio_formats:
        return "参数错误: audio_format 只能是 " + ", ".join(allowed_audio_formats) + "。"

    tts_mode = str(tts_mode or "default").strip().lower()
    if tts_mode not in ("default", "design", "clone"):
        return "参数错误: tts_mode 只能是 default、design 或 clone。"

    for name, value, limit in (
        ("style", style, 200),
        ("design_description", design_description, 300),
        ("clone_style_prompt", clone_style_prompt, 300),
        ("clone_audio_tags", clone_audio_tags, 300),
    ):
        if len(str(value or "")) > limit:
            return f"参数错误: {name} 最多 {limit} 个字符。"

    uid, _ = plugin._get_event_settings(event)
    overrides: dict = {}
    for name, value in (
        ("breath", breath),
        ("stress", stress),
        ("laughter", laughter),
        ("pause", pause),
    ):
        if value is not None:
            overrides[name] = value
    if voice:
        overrides["voice"] = plugin._resolve_voice(voice)
    if speed:
        overrides["speed"] = float(speed)
    if pitch != 999:
        overrides["pitch"] = int(pitch)
    if dialect:
        overrides["dialect"] = "" if dialect.lower() == "off" else dialect
    if volume:
        overrides["volume"] = "" if volume.lower() == "off" else volume
    overrides["tts_mode"] = tts_mode
    if style:
        overrides["style_hint"] = str(style).strip()
    if design_description:
        overrides["design_description"] = str(design_description).strip()
    if clone_style_prompt:
        overrides["clone_style_prompt"] = str(clone_style_prompt).strip()
    if clone_audio_tags:
        overrides["clone_audio_tags"] = str(clone_audio_tags).strip()

    emotion_override = None
    if emotion == "auto":
        from ..emotion.emotion_detector import detect_emotion

        overrides["emotion"] = ""
        emotion_override = detect_emotion(text)
    elif emotion == "off":
        overrides["emotion"] = ""
    elif emotion:
        overrides["emotion"] = emotion

    async def synthesize_and_send() -> None:
        try:
            audio_path = await plugin._do_tts(
                text,
                uid,
                format_override=audio_format or None,
                emotion_override=emotion_override,
                settings_override=overrides,
            )
            if not audio_path:
                await event.send(MessageChain().message("语音合成失败: 没有生成音频文件。"))
                return
            chain = MessageChain()
            chain.chain.append(Record.fromFileSystem(str(audio_path)))
            await event.send(chain)
        except Exception as exc:
            await event.send(MessageChain().message(f"语音合成失败: {exc}"))

    asyncio.create_task(synthesize_and_send())
    return "已接受语音请求，正在后台合成并发送。"


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
