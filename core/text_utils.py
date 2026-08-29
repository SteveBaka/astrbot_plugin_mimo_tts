# -*- coding: utf-8 -*-
"""Text processing utilities for MiMO TTS plugin."""

from __future__ import annotations

import logging
import re

try:
    from astrbot.api import logger
    from astrbot.api.message_components import Plain, Record
except ImportError:  # 独立导入（纯逻辑单测）时无 AstrBot 运行时，仅保证可导入
    logger = logging.getLogger("astrbot")
    Plain = type("Plain", (), {"__init__": lambda self, text="": setattr(self, "text", text)})
    Record = type("Record", (), {})


def should_skip(text: str, min_length: int, max_length: int, skip_patterns: list[str]) -> bool:
    """Check if text should be skipped for TTS."""
    if not text or not text.strip():
        return True
    t = text.strip()
    if len(t) < min_length:
        return True
    if len(t) > max_length:
        return True
    for pat in skip_patterns:
        if re.search(pat, t):
            return True
    return False


def split_text(text: str, pattern: str, patterns: dict[str, str], max_count: int) -> list[str]:
    """Split text into segments using the configured regex pattern."""
    regex = patterns.get(pattern, patterns["sentence"])
    segments = re.split(regex, text)
    result = [s.strip() for s in segments if s.strip()]

    if max_count > 0 and len(result) > max_count:
        merged = result[:max_count - 1]
        merged.append("".join(result[max_count - 1:]))
        result = merged

    return result


def strip_audio_tags(text: str) -> str:
    """Remove MiMO audio tags for display: (风格) and [标签]."""
    s = re.sub(r"[（\(][^）\)]{1,10}[）\)]", "", text)
    s = re.sub(r"[\[【][^\]】]{1,20}[\]】]", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


_MD_SYMBOLS_RE = re.compile(r"\*+|`+|~~|__")
_MD_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")


def strip_markdown_symbols(text: str) -> str:
    """去除 Markdown 格式符号，避免被 TTS 朗读。

    清洗对象：**加粗**、*斜体*、`代码`、~~删除线~~、__下划线__、行首 # 标题。
    只删符号、保留文字内容，不触碰 MiMo 官方标签（开头 (风格) 与 [音频标签]）；
    保留原有换行与空格结构（唱歌歌词链路不经过本函数，由调用方豁免）。
    """
    if not text:
        return text
    s = _MD_SYMBOLS_RE.sub("", str(text))
    return _MD_HEADING_RE.sub("", s).strip()


_TTS_STYLE_LEADING_RE = re.compile(r"^(?:\s*[（(][^）)]{1,12}[）)])+")
_TTS_AUDIO_TAG_RE = re.compile(r"[\[【][^\]】]{1,20}[\]】]")


def strip_tts_tags(text: str) -> str:
    """去除 TTS 专用标签，用于用户侧展示文本（标签只应到 TTS 服务端与日志）。

    清洗对象：开头的 (风格) 标签（如 ``(活泼)``，可多个连续）与正文中的
    [音频标签]/【音频标签】（如 ``[叹气]``）。保留正文与普通括号内容
    （如 ``(约380元)`` 这类正文括号不做剥离）。
    """
    if not text:
        return text
    s = _TTS_AUDIO_TAG_RE.sub("", str(text).lstrip())
    s = _TTS_STYLE_LEADING_RE.sub("", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


_SINGING_TAG_RE = re.compile(
    # 以唱歌关键词开头的括号（含 "(唱歌 温柔)" 组合写法）
    r"^([\(\[（])\s*(?:唱歌|sing|singing)((?:[\s,，、][^\)\]）]*)?)[\)\]）]",
    re.IGNORECASE,
)
# 开头短风格括号：内容 1~16 字；配合逐词长度与句读守卫，避免误吞歌词
_STYLE_BRACKET_RE = re.compile(r"^[\(\[（]\s*([^\)\]）]{1,16}?)\s*[\)\]）]\s*")
_SENTENCE_BREAK_RE = re.compile(r"[。！？!?；;]")


def _split_styles(raw: str) -> list[str]:
    return [s.strip() for s in re.split(r"[\s,，、]+", raw or "") if s.strip()]


def extract_leading_styles(text: str) -> tuple[str, list[str]]:
    """提取文本开头的风格括号（唱歌标签/纯风格括号），返回 (无括号正文, 风格词列表)。

    不添加 "(唱歌)" 前缀；守卫同 apply_singing_tag（无句读、每词 ≤8 字）。
    """
    stripped = text.lstrip()
    extras: list[str] = []
    while True:
        m = _SINGING_TAG_RE.match(stripped)
        if m:
            extras += _split_styles(m.group(2))
            stripped = stripped[m.end():].lstrip()
            continue
        s = _STYLE_BRACKET_RE.match(stripped)
        if s:
            words = _split_styles(s.group(1))
            if words and not _SENTENCE_BREAK_RE.search(s.group(1)) and all(
                len(w) <= 8 for w in words
            ):
                extras += words
                stripped = stripped[s.end():].lstrip()
                continue
        break
    return stripped, extras


def apply_singing_tag(text: str) -> tuple[str, list[str]]:
    """归一化开头的唱歌/风格标签，返回 (最终文本, 附加风格词列表)。

    assistant 文本只保留精确 "(唱歌)" 标签；用户在歌词开头写的风格括号
    —— "(温柔)歌词"、"(唱歌 温柔)歌词"、"(唱歌)(温柔)歌词" —— 统一拆出
    风格词，由调用方移入 user 角色控制指令（官方风格控制通道）。
    """
    stripped = text.lstrip()
    if not stripped:
        return text, []
    body, extras = extract_leading_styles(stripped)
    return f"(唱歌){body}", extras


def sanitize_polished_text(original: str, polished: str, max_ratio: float = 3.0) -> str:
    """润色输出卫生（sing-mode-feature.md §2.5）：剥代码围栏/包裹引号 + 长度健全性校验。

    越界改写（超原文 max_ratio 倍）视为不可信，返回空串由调用方回退原文。
    """
    s = str(polished or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'“”‘’":
        s = s[1:-1].strip()
    if not s:
        return ""
    if len(s) > len(str(original or "")) * max_ratio + 10:
        return ""
    return s


def extract_auto_tts_text(chain) -> str:
    """Extract the first continuous plain text segment from the message chain."""
    chunks: list[str] = []
    started = False

    for comp in chain:
        if isinstance(comp, Record):
            break
        if isinstance(comp, Plain) and comp.text:
            chunks.append(comp.text)
            started = True
            continue
        if started:
            break

    return "".join(chunks).strip()


def build_audio_only_chain(chain, text: str, audio_component) -> list:
    """Build a chain containing only the audio component, removing the original text."""
    new_chain: list = []
    consumed = False

    for comp in chain:
        if isinstance(comp, Record):
            continue
        if not consumed and isinstance(comp, Plain) and comp.text:
            comp_text = str(comp.text)
            if text and text in comp_text:
                remainder = (comp_text.replace(text, "", 1)).strip()
                if remainder:
                    new_chain.append(Plain(remainder))
                consumed = True
                continue
        new_chain.append(comp)

    new_chain.append(audio_component)
    return new_chain


def log_tts_text(uid: str, mode: str, sing: bool, text: str) -> None:
    """Log TTS input parameters."""
    logger.info(
        "[MiMO TTS] synthesize text uid=%s mode=%s sing=%s text=%r",
        uid,
        mode,
        sing,
        text,
    )


def looks_like_hidden_prompt_or_reasoning(text: str) -> bool:
    """Detect persona/skill internal prompts or reasoning text to avoid TTS reading.

    Returns True if the text looks like a leaked system prompt or chain-of-thought.
    """
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return False

    head = normalized[:240].lower()
    suspicious_prefixes = (
        "**considering ",
        "considering ",
        "analysis:",
        "chain of thought",
        "thought:",
        "reasoning:",
        "internal monologue:",
        "system prompt",
        "developer prompt",
        "assistant persona",
        "skill:",
        "persona:",
        "你是谁",
        "你是一个",
        "系统提示",
        "开发者提示",
        "角色设定",
        "response style",
        "i need to ",
        "i should ",
        "let me ",
        "the user wants",
    )
    if head.startswith(suspicious_prefixes):
        return True

    suspicious_phrases = (
        "considering a response style",
        "need to provide a short answer",
        "keeping it formal",
        "using commas instead of periods",
        "without punctuation",
        "i need to provide",
        "i should provide",
        "system prompt",
        "developer message",
        "assistant persona",
        "chain-of-thought",
        "internal reasoning",
        "不要向用户展示",
        "以下是你的设定",
        "技能描述",
        "人格设定",
    )
    matched = sum(1 for phrase in suspicious_phrases if phrase in head)
    if matched >= 3:
        return True

    suspicious_patterns = (
        r"^(?:#|##|###)\s*(?:system|developer|persona|skill|thought|reasoning)",
        r"^[\[【](?:system|developer|persona|skill|内部|推理|思考)[\]】]",
        r"(?:请扮演|你的任务是|你的人设是|必须遵循以下规则)",
        r"(?:do not reveal|hidden prompt|internal use only)",
    )
    return any(
        re.search(pattern, head, re.IGNORECASE) for pattern in suspicious_patterns
    )
