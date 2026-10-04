# -*- coding: utf-8 -*-
"""流式输出兼容：结果类型判定、文本提取与短窗去重。

纯函数优先，便于脱离 AstrBot 单测。判定不依赖全局 streaming_response
配置，而以结果形态 / LLMResponse 来源为准，便于大版本最小适配。

去重说明：
- 跨钩子（decorate / on_llm_response / background）必须共享同一存储。
- 事件级 `_mimo_tts_voice_sent` 用于「本条回复只允许一次语音」的硬闸门。
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any, Optional

# 事件级：本条事件只允许发送一次自动语音
EXTRA_VOICE_SENT = "_mimo_tts_voice_sent"
EXTRA_DICE_CHECKED = "_mimo_tts_checked"
EXTRA_DICE_ACTIVE = "_mimo_tts_active"

# 进程级单例：禁止在调用点 `VoiceDedupStore()` 新建空表（曾导致双音）
_GLOBAL_DEDUP: Optional["VoiceDedupStore"] = None


def _content_type_name(result: Any) -> str:
    typ = getattr(result, "result_content_type", None)
    if typ is None:
        return ""
    name = getattr(typ, "name", None)
    if isinstance(name, str) and name:
        return name
    text = str(typ)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.upper()


def is_streaming_result(result: Any) -> bool:
    """True: STREAMING_RESULT / STREAMING_FINISH（或 content_type 名称匹配）。"""
    if result is None:
        return False
    ctype = _content_type_name(result)
    if ctype in {"STREAMING_RESULT", "STREAMING_FINISH"}:
        return True
    fn = getattr(result, "is_streaming_result", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return False


def is_non_stream_llm_result(result: Any) -> bool:
    """True: 可走非流式 decorate 自动 TTS 的 LLM 结果。"""
    if result is None:
        return False
    if is_streaming_result(result):
        return False
    fn = getattr(result, "is_llm_result", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return _content_type_name(result) == "LLM_RESULT"


def extract_text_from_chain(chain: Any) -> str:
    """从 MessageChain/列表提取连续 Plain 文本（与 auto_tts 语义一致）。"""
    try:
        from ..core.text_utils import extract_auto_tts_text

        comps = getattr(chain, "chain", chain)
        if comps is not None:
            return extract_auto_tts_text(comps)
    except Exception:
        pass
    if not chain:
        return ""
    comps = getattr(chain, "chain", chain)
    if not comps:
        return ""
    chunks: list[str] = []
    started = False
    for comp in comps:
        if hasattr(comp, "file") and not getattr(comp, "text", None):
            break
        text = getattr(comp, "text", None)
        if not text:
            if started:
                break
            continue
        type_name = str(getattr(comp, "type", "") or "").upper()
        if "RECORD" in type_name:
            break
        chunks.append(str(text))
        started = True
    return "".join(chunks).strip()


def extract_text_from_llm_response(resp: Any) -> str:
    """从 LLMResponse 提取可朗读全文。"""
    if resp is None:
        return ""
    role = str(getattr(resp, "role", "") or "").lower()
    if role in {"err", "error"}:
        return ""
    text = getattr(resp, "completion_text", None)
    if text and str(text).strip():
        return str(text).strip()
    chain = getattr(resp, "result_chain", None)
    return extract_text_from_chain(chain)


def text_hash(plain: str) -> str:
    raw = str(plain or "").strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _event_extra(event: Any, key: str) -> Any:
    if event is None:
        return None
    fn = getattr(event, "get_extra", None)
    if not callable(fn):
        return None
    try:
        return fn(key, None)
    except Exception:
        return None


def _set_event_extra(event: Any, key: str, value: Any) -> None:
    if event is None:
        return
    fn = getattr(event, "set_extra", None)
    if not callable(fn):
        return
    try:
        fn(key, value)
    except Exception:
        pass


def claim_voice_send(event: Any) -> bool:
    """原子抢占：本事件是否允许发送自动语音。

    检查与置位之间无 await，asyncio 单线程下可防止 decorate /
    on_llm_response / background 并发双发。
    """
    if bool(_event_extra(event, EXTRA_VOICE_SENT)):
        return False
    _set_event_extra(event, EXTRA_VOICE_SENT, True)
    return True


def has_voice_sent(event: Any) -> bool:
    return bool(_event_extra(event, EXTRA_VOICE_SENT))


def resolve_tts_active(plugin, event: Any, uid: str) -> bool:
    """每条回复只掷骰一次；decorate 与 llm_response 共用。"""
    checked = _event_extra(event, EXTRA_DICE_CHECKED)
    if checked is not None:
        return bool(_event_extra(event, EXTRA_DICE_ACTIVE))
    active = plugin._is_tts_active(uid)
    _set_event_extra(event, EXTRA_DICE_CHECKED, True)
    _set_event_extra(event, EXTRA_DICE_ACTIVE, active)
    return active


class VoiceDedupStore:
    """uid+text_hash 短窗去重，防止 decorate 与 on_llm_response 双发语音。"""

    def __init__(self, window_seconds: int = 45, max_size: int = 256):
        self.window_seconds = max(5, int(window_seconds))
        self.max_size = max(16, int(max_size))
        self._items: OrderedDict[tuple[str, str], float] = OrderedDict()

    def _purge(self, now: float) -> None:
        expired = [
            key for key, ts in self._items.items() if now - ts > self.window_seconds
        ]
        for key in expired:
            self._items.pop(key, None)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def seen(self, uid: str, plain: str) -> bool:
        key = (str(uid or ""), text_hash(plain))
        now = time.time()
        self._purge(now)
        ts = self._items.get(key)
        return ts is not None and (now - ts) <= self.window_seconds

    def mark(self, uid: str, plain: str) -> None:
        key = (str(uid or ""), text_hash(plain))
        now = time.time()
        self._purge(now)
        self._items[key] = now
        self._items.move_to_end(key)


def voice_dedup(plugin: Any = None) -> VoiceDedupStore:
    """返回共享去重存储。优先挂到 plugin 实例，否则用进程级单例。"""
    global _GLOBAL_DEDUP
    if plugin is not None:
        store = getattr(plugin, "_voice_dedup", None)
        if isinstance(store, VoiceDedupStore):
            return store
        if _GLOBAL_DEDUP is None:
            _GLOBAL_DEDUP = VoiceDedupStore()
        try:
            plugin._voice_dedup = _GLOBAL_DEDUP
        except Exception:
            pass
        return _GLOBAL_DEDUP
    if _GLOBAL_DEDUP is None:
        _GLOBAL_DEDUP = VoiceDedupStore()
    return _GLOBAL_DEDUP
