# -*- coding: utf-8 -*-
"""MiMO TTS Prompt Builder - constructs user-role prompts for emotion/control.

MiMO-V2.5-TTS uses a unique message format:
  - assistant role: the text to speak
  - user role: control instructions (emotion, speed, prosody, etc.)

This module builds the user-role control prompt.
"""

from __future__ import annotations

from typing import Optional

from ..emotion.emotion_detector import (
    detect_emotion,  # noqa: F401  (re-export for backward compatibility)
)

# ── Emotion descriptions ─────────────────────────────────────

EMOTION_DESCRIPTIONS: dict[str, str] = {
    "happy": "开心愉悦的语气，带有微笑的感觉",
    "sad": "难过悲伤的语气，低沉缓慢",
    "angry": "生气愤怒的语气，有力且急促",
    "neutral": "平静自然的语气",
    "whisper": "轻声细语，像在说悄悄话",
    "surprised": "惊讶意外的语气，语调上扬",
    "excited": "激动兴奋的语气，充满活力",
    "gentle": "温柔轻柔的语气，像在哄人",
    "serious": "严肃认真的语气，沉稳有力",
    "romantic": "浪漫深情的语气，温柔缠绵",
    "fearful": "害怕恐惧的语气，带着颤抖",
    "disgusted": "厌恶嫌弃的语气",
    "sarcastic": "讽刺挖苦的语气，阴阳怪气",
    "nostalgic": "怀念感慨的语气，带着追忆",
    "playful": "俏皮活泼的语气，带着玩味",
    "calm": "淡定从容的语气，波澜不惊",
    "anxious": "焦虑紧张的语气，带着不安",
    "proud": "骄傲自豪的语气，昂扬自信",
    "tender": "体贴关怀的语气，暖心温柔",
    "lazy": "慵懒随意的语气，漫不经心",
}


# ── Speed descriptions ───────────────────────────────────────


def _speed_description(speed: float) -> str:
    """Convert speed value to natural language description."""
    if speed <= 0.5:
        return "语速极慢，每个字都拖得很长"
    elif speed < 0.7:
        return "语速很慢，字斟句酌"
    elif speed < 0.9:
        return "语速稍慢，从容不迫"
    elif speed <= 1.1:
        return ""  # Normal speed, no description needed
    elif speed <= 1.3:
        return "语速稍快"
    elif speed <= 1.5:
        return "语速较快"
    elif speed <= 1.8:
        return "语速很快，连珠炮一般"
    else:
        return "语速极快，机关枪一样"


# ── Pitch descriptions ───────────────────────────────────────


def _pitch_description(pitch: int) -> str:
    """Convert pitch offset to natural language description."""
    if pitch >= 6:
        return "音调非常高，尖锐明亮"
    elif pitch >= 3:
        return "音调偏高，清亮"
    elif pitch <= -6:
        return "音调非常低，低沉浑厚"
    elif pitch <= -3:
        return "音调偏低"
    else:
        return ""


def build_system_prompt(
    emotion: Optional[str] = None,
    speed: float = 1.0,
    pitch: int = 0,
    breath: bool = False,
    sing: bool = False,
    stress: bool = False,
    style_prompt: str = "",
    style_hint: Optional[str] = None,
    voice_desc: str = "",
    laughter: bool = False,
    pause: bool = False,
    dialect: str = "",
    volume: str = "",
) -> str:
    """Build the user-role control prompt for MiMO TTS API.

    This prompt goes in the user role message and controls how the
    assistant-role text should be spoken.

    Args:
        emotion: Emotion name (happy/sad/angry/etc.)
        speed: Speed multiplier (0.5~2.0)
        pitch: Pitch offset (-12 to +12)
        breath: Add natural breathing sounds
        sing: Enable singing mode
        stress: Enable emphasis/stress mode
        style_prompt: Custom style instruction
        voice_desc: Voice character description
        laughter: Allow natural laughter in speech
        pause: Add more pauses between sentences
        dialect: Dialect hint (e.g., "四川话", "粤语", "东北话")
        volume: Volume hint ("轻声", "正常", "大声")

    Returns:
        Control prompt string for user role.
    """
    parts: list[str] = []

    # Emotion
    if emotion and emotion != "neutral":
        desc = EMOTION_DESCRIPTIONS.get(emotion, f"用{emotion}的语气")
        parts.append(desc)

    # Custom style (style_hint is an alias for style_prompt)
    style_text = style_prompt or (style_hint or "")
    if style_text:
        parts.append(style_text.strip().rstrip("。"))

    # Voice character description
    if voice_desc:
        parts.append(voice_desc.strip())

    # Speed
    speed_desc = _speed_description(speed)
    if speed_desc:
        parts.append(speed_desc)

    # Pitch
    pitch_desc = _pitch_description(pitch)
    if pitch_desc:
        parts.append(pitch_desc)

    # Breath
    if breath:
        parts.append("说话时偶尔有轻微的呼吸换气声，语速保持自然流畅")

    # Sing
    if sing:
        parts.append("请用唱歌的方式演绎这段文字，注意旋律起伏和节奏感，像在唱歌一样")

    # Stress/Emphasis
    if stress:
        parts.append("重点词句加重语气，有节奏感和力度变化")

    # Laughter
    if laughter:
        parts.append("可以自然地加入笑声，更生动")

    # Pauses
    if pause:
        parts.append("句与句之间多停顿，给人思考的空间")

    # Dialect
    if dialect:
        parts.append(f"用{dialect}口音来说")

    # Volume
    if volume and volume != "正常":
        parts.append(volume)

    return "，".join(parts) if parts else ""


# detect_emotion re-exported at module level via top-level import.
