# -*- coding: utf-8 -*-
"""分段回复规划层：纯逻辑，不依赖 AstrBot，可脱离运行环境单测。

开关职责单一原则（每开关只回答一个问题）：
- ``segment_voice_probability`` 只管掷骰（哪些段想出语音）
- ``text_async`` 只管文字与语音的时序（文字先发、语音后补）
- ``segment_text_fallback`` 只管「最终没有语音」的段落是否用纯文本兜底

投递动作是分段行为的唯一决策出口，全部 if/else 矩阵集中在
:func:`resolve_delivery`；执行层（handlers/segmenting.py）只分发、不做判断。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable

# 纯分隔线/装饰段（如 markdown 的 "---"、"***"）：无信息量，整段丢弃，
# 不作为文字气泡发出（qq_official 等平台会把它们残缺地渲染出来）
_BLANK_SEG_RE = re.compile(r"^(?:[-=*_~—·.>\s]|#)+$")

# ── 投递动作 ──
BUNDLED = "bundled"              # 文字+语音捆绑一条消息
TEXT_FIRST = "text_first"        # 文字立即发，语音后台串行补发
VOICE_ONLY = "voice_only"        # 仅语音
TEXT_FALLBACK = "text_fallback"  # 无语音段：纯文字兜底
DROP = "drop"                    # 无语音段且兜底关闭：丢弃（仅记录日志）


@dataclass
class SegmentPlan:
    """单个分段的掷骰结果。"""

    text: str
    short: bool        # 过短段：策略性纯文字（不值得单独合成），不掷骰
    want_voice: bool   # 掷骰命中；实际能否出语音由执行层合成结果决定
    blank: bool = False  # 纯分隔线/空段：整段丢弃（不受兜底开关约束）


def plan_segments(
    segments: list[str],
    *,
    min_length: int,
    probability: float,
    rng: Callable[[], float] = random.random,
) -> list[SegmentPlan]:
    """对切分结果逐段掷骰，产出规划列表（保持原顺序）。

    rng 作为参数注入：生产传 random.random，测试传确定性序列。
    """
    plans: list[SegmentPlan] = []
    for seg in segments:
        if not seg or _BLANK_SEG_RE.match(seg):
            plans.append(SegmentPlan(text=seg, short=False, want_voice=False, blank=True))
        elif len(seg) < min_length:
            plans.append(SegmentPlan(text=seg, short=True, want_voice=False))
        else:
            plans.append(SegmentPlan(text=seg, short=False, want_voice=rng() < probability))
    return plans


def resolve_delivery(
    *,
    short: bool,
    want_voice: bool,
    text_enabled: bool,
    text_async: bool,
    fallback_enabled: bool,
    blank: bool = False,
) -> str:
    """决策表：根据规划结果与两个文字开关返回投递动作。

    短段无条件纯文字是固定策略（「太短不值得合成」），不受
    fallback 开关约束，故同样落到 TEXT_FALLBACK。
    纯分隔线段（blank）固定 DROP：无信息量内容不投递。
    合成失败不在本表内：由执行层把 BUNDLED/VOICE_ONLY 降级为
    「fallback_enabled ? TEXT_FALLBACK : 丢弃」（见 segmenting.py）。
    """
    if blank:
        return DROP
    if short:
        return TEXT_FALLBACK
    if not want_voice:
        return TEXT_FALLBACK if fallback_enabled else DROP
    if not text_enabled:
        return VOICE_ONLY
    return TEXT_FIRST if text_async else BUNDLED
