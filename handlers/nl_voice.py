# -*- coding: utf-8 -*-
"""自然语言语音朗读：「用语音说/朗读/念…」正则白名单。

与 NL 唱歌同级、互相独立；命中即 stop_event + 直接合成发送，
不进入 LLM 管线，也不走 auto_tts / llm_response 自动钩子。
等同 ``/mimo_say <content>``（无额外参数），不注入唱歌 override。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Record

from ..core.adaptive_tts import match_nl_voice_command, nl_voice_enabled


async def handle_nl_voice(plugin, event: AstrMessageEvent) -> None:
    """唤醒消息匹配 NL 语音朗读句式时直接合成并发送。"""
    if not nl_voice_enabled(plugin):
        return
    if not getattr(event, "is_wake", False):
        return

    text = str(event.message_str or "").strip()
    content = match_nl_voice_command(text)
    if not content:
        return

    uid, _ = plugin._get_event_settings(event)
    event.stop_event()
    logger.info(
        "MiMO TTS: nl_voice matched uid=%s chars=%d text=%r",
        uid,
        len(content),
        content[:40],
    )
    plugin.plog.info("NL Voice", f"语音朗读触发 uid={uid} len={len(content)}")

    try:
        audio_path = await plugin._do_tts(content, uid)
        if audio_path:
            chain = MessageChain()
            chain.chain.append(Record.fromFileSystem(str(audio_path)))
            await event.send(chain)
            logger.info(
                "MiMO TTS: nl_voice voice sent uid=%s chars=%d path=%s",
                uid,
                len(content),
                getattr(audio_path, "name", audio_path),
            )
        else:
            await event.send(MessageChain().message("语音合成失败。"))
    except Exception as e:
        logger.warning("MiMO TTS: nl_voice TTS failed: %s", e)
        await event.send(MessageChain().message(f"! {e}"))
