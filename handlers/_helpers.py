# -*- coding: utf-8 -*-
"""Shared helpers for handlers."""

from __future__ import annotations

from typing import Optional

from ..core.constants import SUPPORTED_EMOTIONS
from ..emotion.emotion_detector import detect_emotion


def parse_mimo_say_options(plugin, text: str, uid: str, uset: dict):
    """Parse inline options from /mimo_say command text.

    Returns: (remaining_text, settings_override_dict, emotion_override)
    """
    from astrbot.api.event import filter  # avoid top-level import cycle

    overrides: dict = {}
    emo_override: Optional[str] = None

    text, emo = plugin._parse_opt(text, "-emotion")
    text, spd = plugin._parse_opt(text, "-speed")
    text, ptc = plugin._parse_opt(text, "-pitch")
    text, voi = plugin._parse_opt(text, "-voice")
    text, brt = plugin._parse_opt(text, "-breath")
    text, sts = plugin._parse_opt(text, "-stress")
    text, dia = plugin._parse_opt(text, "-dialect")
    text, vol = plugin._parse_opt(text, "-volume")
    text = text.strip()

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
