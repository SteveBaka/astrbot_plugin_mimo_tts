# -*- coding: utf-8 -*-
"""Shared helpers for handlers."""

from __future__ import annotations

import re
from typing import Iterable

from ..emotion.emotion_detector import detect_emotion

_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def parse_value_flags(
    text: str,
    value_flags: Iterable[str],
    bare_until_content: bool = False,
) -> tuple[str, dict[str, str], list[str]]:
    """统一命令 flag 解析：`-flag 值` 形式，顺序无关，值支持引号跨空格。

    Args:
        value_flags: 需要取值的 flag 名集合（不含 '-'，如 {"p", "s"}）。
        bare_until_content: True 时，正文出现前的未知 -token 记为裸 flag
            （/sing 的 `-冰糖` 用法）；False 时未知 -token 留在正文
            （/mimo_say 语义，与旧 _parse_opt 行为一致）。

    Returns:
        (剩余正文, {flag名: 值}, 裸 flag token 列表)
    """
    tokens = _TOKEN_RE.findall(str(text or ""))
    known = {str(f).lstrip("-") for f in value_flags}
    remaining: list[str] = []
    opts: dict[str, str] = {}
    bare: list[str] = []
    seen_content = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        name = tok.lstrip("-")
        if tok.startswith("-") and len(tok) > 1 and name in known:
            value = _unquote(tokens[i + 1]) if i + 1 < len(tokens) else ""
            opts[name] = value
            i += 2
            continue
        if (
            tok.startswith("-")
            and len(tok) > 1
            and not seen_content
            and bare_until_content
        ):
            bare.append(tok)
            i += 1
            continue
        seen_content = True
        remaining.append(tok)
        i += 1
    return " ".join(remaining).strip(), opts, bare


def parse_mimo_say_options(plugin, text: str, uid: str, uset: dict):
    """Parse inline options from /mimo_say command text.

    Returns: (remaining_text, settings_override_dict, emotion_override)
    """
    from typing import Optional

    text, opts, _ = parse_value_flags(
        text,
        {"emotion", "speed", "pitch", "voice", "breath", "stress", "dialect", "volume"},
    )
    overrides: dict = {}
    emo_override: Optional[str] = None

    emo = opts.get("emotion", "")
    spd = opts.get("speed", "")
    ptc = opts.get("pitch", "")
    voi = opts.get("voice", "")
    brt = opts.get("breath", "")
    sts = opts.get("stress", "")
    dia = opts.get("dialect", "")
    vol = opts.get("volume", "")

    if emo:
        if emo == "auto":
            detected = detect_emotion(text)
            emo_override = detected or None
        elif emo == "off":
            overrides["emotion"] = ""
        else:
            overrides["emotion"] = emo
    if spd:
        overrides["speed"] = max(0.5, min(2.0, float(spd)))
    if ptc:
        overrides["pitch"] = max(-12, min(12, int(ptc)))
    if voi:
        overrides["voice"] = plugin._resolve_voice(voi)
    if brt:
        overrides["breath"] = brt == "on"
    if sts:
        overrides["stress"] = sts == "on"
    if dia:
        overrides["dialect"] = "" if dia == "off" else dia
    if vol:
        overrides["volume"] = "" if vol == "off" else vol

    return text, overrides, emo_override
