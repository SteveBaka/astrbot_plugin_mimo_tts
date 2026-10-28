# -*- coding: utf-8 -*-
"""流式 LLM 完成后的自动 TTS：on_llm_response 入口（仅流式）。

v2.4.5 路由：
- **仅当** result 为 STREAMING_*（流式）时本钩子出声。
- **非流式**：立即 return，交回 main 的 on_decorating_result 分段/全文路径。
- 流式：claim + 短窗去重；文字由平台直播（text_already_sent 语义）。
- 流式下**忽略** enable_segmentation：强制全文一条音，避免「全字 + 零星音」
  与非流式分段特征割裂（见 docs/stream-segmented-voice.md）。
- 流式 postwork 后台化：claim 后立即返回，不阻塞流生成器收尾帧
  （QQ C2C 实测阻塞会拖迟 state=10 收尾 → 协议超时回滚 → 文字残缺）。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Record

from ..core.stream_compat import (
    claim_voice_send,
    extract_text_from_llm_response,
    has_voice_sent,
    is_streaming_result,
    resolve_tts_active,
    text_hash,
    voice_dedup,
)
from ..core.text_utils import looks_like_hidden_prompt_or_reasoning
from .auto_tts import _detect_emotion


async def _send_voice(
    plugin,
    event: AstrMessageEvent,
    uid: str,
    tts_text: str,
    uset: dict,
    polished: bool,
) -> None:
    emo_override = _detect_emotion(uset, tts_text)
    audio_path = await plugin._do_tts(tts_text, uid, emotion_override=emo_override)
    if not audio_path:
        return
    chain = MessageChain()
    chain.chain.append(Record.fromFileSystem(str(audio_path)))
    await event.send(chain)
    logger.info(
        "MiMO TTS: voice sent via=event.send llm_stream=on "
        "uid=%s chars=%d path=%s polish=%s",
        uid,
        len(tts_text or ""),
        getattr(audio_path, "name", audio_path),
        polished,
    )


async def handle_llm_response_tts(plugin, event: AstrMessageEvent, resp) -> None:
    """AstrBot on_llm_response：仅流式路径自动 TTS；非流式交给 main decorate。"""
    if not getattr(plugin.config, "stream_llm_tts_compat", True):
        return

    plain = extract_text_from_llm_response(resp)
    if not plain or plain.startswith("/"):
        return

    uid, uset = plugin._get_event_settings(event)
    result = event.get_result()

    # 非流式 / 尚未形成流式结果：保持 main 的 decorate 语义，本钩子不出声
    if result is None or not is_streaming_result(result):
        logger.info(
            "MiMO TTS: skip llm_response TTS (non-stream; decorate owns voice) uid=%s",
            uid,
        )
        return

    if not resolve_tts_active(plugin, event, uid):
        logger.info(
            "MiMO TTS: auto TTS inactive on llm_response, skip. "
            "(auto_tts=%s tts_enabled=%s smart=%s hook=llm_response)",
            plugin.config.get("auto_tts", True),
            uset.get("tts_enabled", True),
            getattr(plugin.config, "smart_auto_tts_mode", False),
        )
        return

    dedup = voice_dedup(plugin)
    if has_voice_sent(event):
        logger.info("MiMO TTS: skip llm_response TTS (voice already sent) uid=%s", uid)
        return
    if dedup.seen(uid, plain):
        logger.info(
            "MiMO TTS: skip llm_response TTS (dedup) uid=%s hash=%s",
            uid,
            text_hash(plain)[:12],
        )
        return

    chain = list(getattr(result, "chain", None) or [])
    if any(isinstance(c, Record) for c in chain):
        dedup.mark(uid, plain)
        logger.info(
            "MiMO TTS: skip llm_response TTS (chain already has Record) uid=%s",
            uid,
        )
        return

    if plugin._should_skip(plain):
        logger.info(
            "MiMO TTS: skip llm_response TTS (len/skip) chars=%d",
            len(plain),
        )
        return
    if looks_like_hidden_prompt_or_reasoning(plain):
        logger.warning("MiMO TTS: skip llm_response TTS (hidden prompt/reasoning)")
        return

    polish_enabled = plugin._voice_polish_enabled(uid)
    if plugin.config.display_polished_text and polish_enabled:
        logger.warning(
            "MiMO TTS: display_polished_text degraded under streaming; "
            "chat text stays stream original"
        )

    if not claim_voice_send(event):
        logger.info("MiMO TTS: skip llm_response TTS (claim failed) uid=%s", uid)
        return

    async def _stream_postwork() -> None:
        """流式补音后台任务：润色 + 合成 + 发送（单 task 内串行保序）。

        必须后台执行：本钩子运行期间 respond 仍在消费流生成器，内联慢操作
        会推迟平台收尾帧——QQ C2C 实测被拖 26s，触发协议超时回滚导致
        文字残缺（语音走普通消息不受影响）。串行约束保留在本 task 内部。

        分段策略：流式下平台已直播全文，分段只补部分段语音会造成
        「全字 + 零星音」割裂；故强制降级为全文一条音（见 docs/stream-segmented-voice.md）。
        """
        try:
            if plugin._segmentation_enabled(uid):
                logger.warning(
                    "MiMO TTS: segmentation degraded under streaming; "
                    "using full-text single voice (see docs/stream-segmented-voice.md) "
                    "uid=%s",
                    uid,
                )
                plugin.plog.warn(
                    "Segmentation",
                    f"流式下降级为全文单音 uid={uid}（分段仅非流式生效）",
                )

            tts_text = plain
            if polish_enabled:
                logger.info(
                    "MiMO TTS: voice polish in llm_response, calling LLM..."
                )
                plugin.plog.info("Polish", f"LLM 润色触发 uid={uid} (stream)")
                tts_text = await plugin._polish_text_with_llm(plain, uid)

            await _send_voice(
                plugin, event, uid, tts_text, uset, polished=polish_enabled
            )
            dedup.mark(uid, plain)
            if tts_text != plain:
                dedup.mark(uid, tts_text)
        except Exception as e:
            logger.warning("MiMO TTS: llm_response TTS failed: %s", e)
            plugin.plog.error("TTS", f"流式自动合成失败: {e}")

    task = asyncio.create_task(_stream_postwork())
    tasks = getattr(plugin, "_stream_postwork_tasks", None)
    if tasks is None:
        tasks = set()
        plugin._stream_postwork_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    logger.info(
        "MiMO TTS: stream postwork backgrounded uid=%s seg=%s polish=%s "
        "mode=full_text",
        uid,
        plugin._segmentation_enabled(uid),
        polish_enabled,
    )
