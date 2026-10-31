# -*- coding: utf-8 -*-
"""自适应自动 TTS 决策（Issue #11）。

优先级（高 → 低）：
1. ``/sing`` · NL 唱歌（各自钩子 stop_event，不进本决策）
2. NL 语音朗读（``adaptive_triggers`` 含 ``nl_voice``，不进自动钩子）
3. 智能模式 adaptive 触发（``smart_auto_tts_mode`` + ``voice_input``）
4. 经典概率掷骰（``smart_auto_tts_mode=false`` 时）

判定必须同时覆盖 decorate 与 llm_response 两入口：
- 非流式：``handle_auto_tts`` → ``plugin._should_auto_tts(event, uid)``
- 流式：``resolve_tts_active`` → 同一函数（事件级缓存一次）
"""

from __future__ import annotations

import random
import re
from typing import Any, Iterable

# 统一「智能触发条件」多选项（Dashboard checkbox）
ADAPTIVE_TRIGGER_CHOICES = ("voice_input", "nl_voice")
# 配置存储：list[str]（兼容旧逗号分隔字符串）
_ADAPTIVE_SPLIT_RE = re.compile(r"[\s,，、]+")

# NL 语音朗读白名单（严格句首匹配，避免「我想念你」类误触）
NL_VOICE_COMMAND_RE = re.compile(
    r"^(?:请|麻烦|帮忙)?"
    r"(?:"
    r"用语音(?:来)?(?:说|朗读|念)(?:一下)?|"
    r"语音(?:说|朗读|念)(?:一下)?|"
    r"用声音(?:说|朗读|念)(?:一下)?|"
    r"朗读(?:一下)?|"
    r"念一下"
    r")"
    r"(?P<content>.+)$",
    re.IGNORECASE,
)
_NL_CONTENT_MAX = 500
_NL_CONTENT_MIN = 2


def parse_adaptive_triggers(raw: Any) -> frozenset[str]:
    """归一化 adaptive_triggers → 仅含合法触发词的 frozenset。"""
    if raw is None:
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        items: Iterable[Any] = raw
    else:
        items = _ADAPTIVE_SPLIT_RE.split(str(raw))
    allowed = set(ADAPTIVE_TRIGGER_CHOICES)
    out: set[str] = set()
    for item in items:
        token = str(item or "").strip().lower()
        if token and token in allowed:
            out.add(token)
    return frozenset(out)


def message_has_record(segments: Any) -> bool:
    """顶层消息链是否含语音段（Record）。"""
    if not segments:
        return False
    for seg in segments:
        if seg is None:
            continue
        # 优先精确类型（运行时真 Record）
        try:
            from astrbot.api.message_components import Record

            if isinstance(seg, Record):
                return True
        except Exception:
            pass
        type_name = type(seg).__name__.lower()
        if type_name == "record":
            return True
        # enum / 字符串 type 字段兜底（单测桩、跨版本）
        t = getattr(seg, "type", None)
        if t is not None:
            name = getattr(t, "name", None)
            text = str(name if name is not None else t).lower()
            if "record" in text:
                return True
    return False


def is_voice_input(event: Any) -> bool:
    """用户消息是否为语音输入（含顶层 Record）。"""
    if event is None:
        return False
    msg = getattr(event, "message_obj", None)
    if msg is None:
        return False
    return message_has_record(getattr(msg, "message", None))


def match_nl_voice_command(text: Any) -> str | None:
    """命中 NL 语音朗读白名单时返回待朗读正文，否则 None。"""
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return None
    m = NL_VOICE_COMMAND_RE.match(raw)
    if not m:
        return None
    content = m.group("content").strip().strip("\"'“”‘’ 　")
    if len(content) < _NL_CONTENT_MIN:
        return None
    return content[:_NL_CONTENT_MAX]


def _session_gates_ok(plugin, uid: str) -> bool:
    """全局 auto_tts + 会话 tts_enabled（与经典路径一致）。"""
    if not plugin.config.get("auto_tts", True):
        return False
    settings = plugin._get_user_settings(uid)
    if not settings.get("tts_enabled", True):
        return False
    return True


def nl_voice_enabled(plugin) -> bool:
    """自然语言朗读是否启用（adaptive_triggers 含 nl_voice）。

    与 smart_auto_tts_mode 正交：勾了就生效，不必先开智能模式。
    """
    return "nl_voice" in parse_adaptive_triggers(
        getattr(plugin.config, "adaptive_triggers", None)
    )


def is_adaptive_voice_force(plugin, event: Any) -> bool:
    """智能模式 + voice_input 勾选 + 本条为语音输入（强制出音，绕过概率/分段掷骰）。"""
    if not bool(plugin.config.smart_auto_tts_mode):
        return False
    if "voice_input" not in parse_adaptive_triggers(
        getattr(plugin.config, "adaptive_triggers", None)
    ):
        return False
    return is_voice_input(event)


def should_auto_tts(plugin, event: Any, uid: str) -> bool:
    """统一自动 TTS 决策：decorate / llm_response 共用。"""
    if not _session_gates_ok(plugin, uid):
        return False

    smart = bool(plugin.config.smart_auto_tts_mode)
    if smart:
        triggers = parse_adaptive_triggers(plugin.config.adaptive_triggers)
        # 仅 voice_input 影响自动出音；nl_voice 走独立监听器
        if "voice_input" in triggers:
            return is_voice_input(event)
        # 只勾了 nl_voice 或全不勾：自动钩子不出音（不掷骰）
        return False

    # 经典路径：概率掷骰
    probability = plugin.config.probability
    if probability <= 0:
        return False
    if probability >= 1:
        return True
    return random.random() < probability
