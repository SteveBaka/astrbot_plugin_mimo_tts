# -*- coding: utf-8 -*-
"""分段回复执行层：只做投递分发，不做决策（决策见 core/segmentation.py）。

时序约定：
- BUNDLED：该段文字+语音一条消息同步发出（用户等待合成完成）
- TEXT_FIRST：该段文字立即发出，语音进入队列，循环结束后由单个后台
  任务按原顺序串行合成发送——不能并行 create_task，否则语音顺序错乱
  且会瞬间并发打满 TTS 服务端
- 合成失败：文字一律不丢（兜底开关决定发不发），错误只写日志，
  不向聊天裸发错误串
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Record

from ..core.segmentation import (
    BUNDLED,
    DROP,
    TEXT_FALLBACK,
    TEXT_FIRST,
    VOICE_ONLY,
    SegmentPlan,
    plan_segments,
    resolve_delivery,
)
from ..core.text_utils import strip_markdown_symbols, strip_tts_tags


def _emotion_override(plugin, uset: dict, text: str) -> Optional[str]:
    """情感设置为空/auto 时自动检测，与全文合成路径语义一致。"""
    if uset.get("emotion") and uset.get("emotion") != "auto":
        return None
    from ..emotion.emotion_detector import detect_emotion

    return detect_emotion(text) or None


async def _polish(plugin, uid: str, text: str, polish_enabled: bool) -> str:
    """按开关执行 LLM 润色；关闭或润色失败（内部回退）均返回安全文本。"""
    if not polish_enabled:
        return text
    return await plugin._polish_text_with_llm(text, uid)


async def _synthesize(
    plugin, uid: str, uset: dict, tts_text: str, emo_base_text: str
) -> Optional[Path]:
    """TTS 合成（不含润色），失败返回 None（不抛出）。情感检测基于原文。"""
    try:
        return await plugin._do_tts(
            tts_text,
            uid,
            emotion_override=_emotion_override(plugin, uset, emo_base_text),
        )
    except Exception as e:
        logger.warning("MiMO TTS: segment TTS failed: %s", e)
        plugin.plog.error("TTS", f"分段合成失败: {e}")
        return None


async def _synthesize_and_send(
    plugin,
    event: AstrMessageEvent,
    uid: str,
    uset: dict,
    text: str,
    polish_enabled: bool,
    *,
    with_text: bool,
    fallback_enabled: bool,
    display_polished: bool,
    display_text: str,
    text_already_sent: bool = False,
) -> None:
    """合成并投递单段；失败时按兜底开关处理文字（内容永不静默丢失）。

    时序：文字始终先于语音单独发出（混合链 [文字, 语音] 在部分平台
    适配器上会被渲染成语音在前，QQ/NapCat 实测），且文字不必等待本段
    合成耗时。
    display_polished（展示文字用润色后文本）时改为先润色再发文字，
    保证展示文字与语音内容一致，代价是文字需等待一次 LLM 调用。
    display_text 为无标签展示版（TTS 标签只应到服务端与日志）；
    display_polished 时展示文本为润色输出的剥标签版。
    text_already_sent=True（流式）：不发文字、失败不兜底文字。
    """
    if text_already_sent:
        with_text = False
        fallback_enabled = False
        display_polished = False
    fast_text = with_text and not display_polished
    if fast_text:
        await event.send(MessageChain().message(display_text))
    tts_text = await _polish(plugin, uid, text, polish_enabled)
    if with_text and not fast_text:
        await event.send(MessageChain().message(strip_tts_tags(tts_text)))
    audio = await _synthesize(plugin, uid, uset, tts_text, text)
    if audio:
        chain = MessageChain()
        chain.chain.append(Record.fromFileSystem(str(audio)))
        await event.send(chain)
        logger.info(
            "MiMO TTS: segment voice sent via=event.send chars=%d polished=%s "
            "with_text=%s",
            len(tts_text or ""),
            polish_enabled,
            with_text,
        )
    elif not with_text and fallback_enabled:
        # VOICE_ONLY 合成失败：文字未发过，按兜底开关补发（与语音内容一致）
        fallback = strip_tts_tags(tts_text) if display_polished else display_text
        await event.send(MessageChain().message(fallback))
    # with_text 时文字已发出，合成失败仅记日志（_synthesize 内），不重复发送


async def _send_pending_voices(
    plugin,
    event: AstrMessageEvent,
    uid: str,
    uset: dict,
    queue: list[tuple[str, bool]],
    polish_enabled: bool,
) -> None:
    """后台任务：按原顺序串行补发 TEXT_FIRST 段的语音（仅语音）。

    queue 项为 (tts_text, polished_done)：display_polished 开启时文字
    阶段已完成润色，此处跳过重复润色直接合成。
    """
    for i, (tts_text, polished_done) in enumerate(queue):
        try:
            tts_text = await _polish(
                plugin, uid, tts_text, polish_enabled and not polished_done
            )
            audio = await _synthesize(plugin, uid, uset, tts_text, tts_text)
            if audio:
                chain = MessageChain()
                chain.chain.append(Record.fromFileSystem(str(audio)))
                await event.send(chain)
                logger.info(
                    "MiMO TTS: bg segment voice sent via=event.send "
                    "index=%d chars=%d",
                    i,
                    len(tts_text or ""),
                )
            # 失败不再兜底：文字已在 TEXT_FIRST 阶段发出，无内容丢失
        except Exception as e:
            logger.warning("MiMO TTS: background segment voice %d failed: %s", i, e)


async def execute_segmented_reply(
    plugin,
    event: AstrMessageEvent,
    uid: str,
    uset: dict,
    segments: list[str],
    *,
    text_already_sent: bool = False,
) -> None:
    """规划并投递全部分段。调用方负责随后清空 result.chain。

    text_already_sent=True（流式）：字已由 AstrBot 直播，只补语音，
    禁止再发任何文字（含 fallback / TEXT_FIRST / BUNDLED 文字）。
    """
    plans: list[SegmentPlan] = plan_segments(
        segments,
        min_length=plugin.config.get("min_text_length"),
        probability=plugin.config.segment_voice_probability,
    )
    fallback_enabled = plugin.config.segment_text_fallback
    text_enabled = plugin._should_send_text_with_tts(uid)
    text_async = plugin._should_send_text_async(uid)
    polish_enabled = plugin._voice_polish_enabled(uid)
    # 展示文字用润色后文本：文字与语音内容一致（兜底小模型改写原文）
    # 流式下字已直播，display_polished 不得再发展示文字
    display_polished = (
        polish_enabled and plugin.config.display_polished_text and not text_already_sent
    )
    if polish_enabled and plugin.config.display_polished_text and text_already_sent:
        logger.warning(
            "MiMO TTS: display_polished_text degraded under streaming; "
            "segment text not re-sent"
        )

    plugin.plog.info(
        "Segmentation",
        f"分段 uid={uid} 段数={len(plans)} "
        f"命中={sum(1 for p in plans if p.want_voice)} "
        f"prob={plugin.config.segment_voice_probability} "
        f"text={'on' if text_enabled else 'off'} async={'on' if text_async else 'off'} "
        f"fallback={'on' if fallback_enabled else 'off'} "
        f"display_polished={'on' if display_polished else 'off'} "
        f"text_already_sent={text_already_sent}",
    )

    pending_voices: list[tuple[str, bool]] = []
    immediate_voices = 0
    for i, plan in enumerate(plans):
        # 合成文本清洗 Markdown 符号（qq_official 等平台不支持 markdown
        # 渲染）；展示文本再剥离 TTS 标签（只应到服务端与日志，见 strip_tts_tags）
        seg_text = strip_markdown_symbols(plan.text) or plan.text
        seg_display = strip_tts_tags(seg_text)
        action = resolve_delivery(
            short=plan.short,
            want_voice=plan.want_voice,
            text_enabled=text_enabled,
            text_async=text_async,
            fallback_enabled=fallback_enabled,
            blank=plan.blank,
        )
        if text_already_sent:
            # 流式：只关心「是否出音」；文字动作一律压成 VOICE_ONLY / DROP
            if action in (BUNDLED, TEXT_FIRST, TEXT_FALLBACK):
                action = (
                    VOICE_ONLY
                    if plan.want_voice
                    else (TEXT_FALLBACK if plan.short else DROP)
                )
                # 短段/未命中在流式下也不重发文字
                if action == TEXT_FALLBACK:
                    logger.debug(
                        "MiMO TTS: stream skip text fallback for segment %d", i
                    )
                    action = DROP
            elif action == VOICE_ONLY:
                pass
        try:
            if action == TEXT_FIRST:
                if display_polished:
                    # 文字与语音一致：先润色再发文字，后台免重复润色
                    tts_text = await _polish(plugin, uid, seg_text, True)
                    await event.send(MessageChain().message(strip_tts_tags(tts_text)))
                    pending_voices.append((tts_text, True))
                else:
                    await event.send(MessageChain().message(seg_display))
                    pending_voices.append((seg_text, False))
            elif action == BUNDLED:
                await _synthesize_and_send(
                    plugin,
                    event,
                    uid,
                    uset,
                    seg_text,
                    polish_enabled,
                    with_text=True,
                    fallback_enabled=fallback_enabled,
                    display_polished=display_polished,
                    display_text=seg_display,
                    text_already_sent=text_already_sent,
                )
                immediate_voices += 1
            elif action == VOICE_ONLY:
                await _synthesize_and_send(
                    plugin,
                    event,
                    uid,
                    uset,
                    seg_text,
                    polish_enabled,
                    with_text=False,
                    fallback_enabled=fallback_enabled,
                    display_polished=display_polished,
                    display_text=seg_display,
                    text_already_sent=text_already_sent,
                )
                immediate_voices += 1
            elif action == TEXT_FALLBACK:
                if text_already_sent:
                    logger.debug("MiMO TTS: stream skip TEXT_FALLBACK segment %d", i)
                else:
                    await event.send(MessageChain().message(seg_display))
            elif action == DROP:
                logger.debug(
                    "MiMO TTS: segment %d dropped (%s)",
                    i,
                    "separator/blank" if plan.blank else "dice miss, fallback off",
                )
        except Exception as e:
            # 投递层异常（发送失败等）：保底补文字，避免整段静默消失
            logger.warning("MiMO TTS: segment %d delivery failed: %s", i, e)
            if not text_already_sent:
                try:
                    await event.send(MessageChain().message(seg_display))
                except Exception:
                    pass

    if pending_voices:
        logger.info(
            "MiMO TTS: segmentation queue pending_bg_voices=%d uid=%s",
            len(pending_voices),
            uid,
        )
        asyncio.create_task(
            _send_pending_voices(
                plugin, event, uid, uset, pending_voices, polish_enabled
            )
        )
    logger.info(
        "MiMO TTS: segmentation done uid=%s segments=%d immediate_voices=%d "
        "pending_bg=%d text_already_sent=%s",
        uid,
        len(plans),
        immediate_voices,
        len(pending_voices),
        text_already_sent,
    )
