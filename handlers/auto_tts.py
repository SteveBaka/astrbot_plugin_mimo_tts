# -*- coding: utf-8 -*-
"""自动 TTS 拦截器：LLM 回复 → 语音回复（分段投递 / 全文单次合成两条路径）。"""

from __future__ import annotations

import asyncio
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain, Record

from ..core.text_utils import (
    build_audio_only_chain,
    extract_auto_tts_text,
    looks_like_hidden_prompt_or_reasoning,
    strip_tts_tags,
)
from .segmenting import execute_segmented_reply


def _detect_emotion(uset: dict, text: str) -> Optional[str]:
    """情感设置为空/auto 时自动检测，与分段路径语义一致。"""
    if uset.get("emotion") and uset.get("emotion") != "auto":
        return None
    from ..emotion.emotion_detector import detect_emotion
    return detect_emotion(text) or None


async def send_tts_audio_background(
    plugin,
    event: AstrMessageEvent,
    text: str,
    uid: str,
    polish_enabled: bool = False,
    tts_text: Optional[str] = None,
) -> None:
    """后台执行 TTS 合成并发送音频（文字先发、语音后补场景）。

    tts_text 传入时（display_polished 已在文字阶段完成润色）跳过润色
    直接合成；否则按 polish_enabled 决定是否润色。
    """
    try:
        if tts_text is None:
            tts_text = text
            if polish_enabled:
                logger.info("MiMO TTS: voice polish in background, calling LLM...")
                plugin.plog.info("Polish", f"LLM 润色触发 uid={uid}")
                tts_text = await plugin._polish_text_with_llm(text, uid)

        emo_override = _detect_emotion(plugin._get_user_settings(uid), text)
        audio_path = await plugin._do_tts(tts_text, uid, emotion_override=emo_override)
        if audio_path:
            chain_msg = MessageChain()
            chain_msg.chain.append(Record.fromFileSystem(str(audio_path)))
            await event.send(chain_msg)
    except Exception as e:
        logger.warning("MiMO TTS: background TTS failed: %s", e)
        plugin.plog.error("TTS", f"后台合成失败: {e}")


async def handle_auto_tts(plugin, event: AstrMessageEvent) -> None:
    """拦截 LLM 输出并自动生成语音回复（分段投递或全文单次合成）。"""
    uid, uset = plugin._get_event_settings(event)

    # Step 1: 概率与前置过滤（静默出口均记录原因，便于平台侧排障）
    if not plugin._is_tts_active(uid):
        logger.info(
            "MiMO TTS: auto TTS inactive, skip. (auto_tts=%s tts_enabled=%s "
            "probability=%s — may be dice miss)",
            plugin.config.get("auto_tts", True),
            plugin._get_user_settings(uid).get("tts_enabled", True),
            plugin.config.probability,
        )
        return

    result = event.get_result()
    chain = result.chain if result and result.chain else None
    if not chain:
        logger.info("MiMO TTS: empty result chain, skip auto TTS")
        return

    if hasattr(result, "is_llm_result") and callable(result.is_llm_result):
        if not result.is_llm_result():
            logger.info("MiMO TTS: non-LLM result, skip auto TTS")
            return

    if any(isinstance(comp, Record) for comp in chain):
        logger.info("MiMO TTS: chain already contains Record, skip auto TTS")
        return

    plain = extract_auto_tts_text(chain)
    if plugin._should_skip(plain):
        logger.info(
            "MiMO TTS: skip auto TTS (len=%d outside [%s, %s] or skip pattern hit), "
            "text=%r",
            len(plain),
            plugin.config.get("min_text_length"),
            plugin.config.get("max_text_length"),
            plain[:50],
        )
        return
    if looks_like_hidden_prompt_or_reasoning(plain):
        logger.warning(
            "MiMO TTS: skip auto TTS because result looks like leaked persona/skill prompt"
        )
        return

    if plain.startswith("/"):
        return

    # Step 2: 分段模式（决策表见 core/segmentation.py，投递见 handlers/segmenting.py）
    if plugin._segmentation_enabled(uid):
        segments = plugin._split_text(plain)
        if not segments:
            return
        await execute_segmented_reply(plugin, event, uid, uset, segments)
        result.chain = []
        return

    # Step 3: 全文单次合成
    polish_enabled = plugin._voice_polish_enabled(uid)
    # 展示文字用润色后文本：文字与语音内容一致（兜底小模型改写原文）
    display_polished = polish_enabled and plugin.config.display_polished_text
    tts_text = plain

    if plugin._should_send_text_with_tts(uid):
        if plugin._should_send_text_async(uid):
            if display_polished:
                tts_text = await plugin._polish_text_with_llm(plain, uid)
                plugin.plog.info("Polish", f"LLM 润色触发 uid={uid} (display_polished)")
                await event.send(MessageChain().message(strip_tts_tags(tts_text)))
                result.chain = []
                asyncio.create_task(
                    send_tts_audio_background(plugin, event, plain, uid, tts_text=tts_text)
                )
            else:
                await event.send(MessageChain().message(strip_tts_tags(plain)))
                result.chain = []
                asyncio.create_task(
                    send_tts_audio_background(plugin, event, plain, uid, polish_enabled)
                )
        else:
            if polish_enabled:
                logger.info("MiMO TTS: voice polish enabled, calling LLM...")
                plugin.plog.info("Polish", f"LLM 润色触发 uid={uid}")
                tts_text = await plugin._polish_text_with_llm(plain, uid)

            try:
                audio_path = await plugin._do_tts(
                    tts_text, uid, emotion_override=_detect_emotion(uset, plain)
                )
                if audio_path:
                    result.chain.append(Record.fromFileSystem(str(audio_path)))
            except Exception as e:
                result.chain.append(Plain(f"[TTS 合成失败: {e}]"))

            # 展示文字不外露 TTS 标签；display_polished 时替换为润色正文。
            # 仅在文字会展示的同步分支执行，不影响 build_audio_only_chain 的原文匹配
            if display_polished and tts_text != plain:
                final_display = strip_tts_tags(tts_text)
            else:
                final_display = strip_tts_tags(plain)
            if final_display != plain:
                for comp in result.chain:
                    if isinstance(comp, Plain) and comp.text == plain:
                        comp.text = final_display
    else:
        if polish_enabled:
            logger.info("MiMO TTS: voice polish enabled, calling LLM...")
            plugin.plog.info("Polish", f"LLM 润色触发 uid={uid}")
            tts_text = await plugin._polish_text_with_llm(plain, uid)

        try:
            audio_path = await plugin._do_tts(
                tts_text, uid, emotion_override=_detect_emotion(uset, plain)
            )
            if audio_path:
                audio_comp = Record.fromFileSystem(str(audio_path))
                result.chain = build_audio_only_chain(chain, plain, audio_comp)
        except Exception as e:
            result.chain.append(Plain(f"[TTS 合成失败: {e}]"))
