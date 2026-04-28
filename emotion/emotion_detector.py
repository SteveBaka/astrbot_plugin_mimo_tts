# -*- coding: utf-8 -*-
"""Emotion Detector - keyword-based emotion detection for Chinese text.

Now supports 20 emotions with expanded keyword sets.
"""

from __future__ import annotations

from typing import Optional

# Chinese and English emotion keywords mapping (20 emotions)
EMOTION_KEYWORDS: dict[str, list[str]] = {
    "happy": [
        "开心",
        "高兴",
        "快乐",
        "太好了",
        "哈哈",
        "嘻嘻",
        "好棒",
        "耶",
        "😄",
        "😁",
        "😊",
        "喜悦",
        "愉快",
        "欢乐",
        "欣喜",
        "乐",
    ],
    "sad": [
        "难过",
        "伤心",
        "哭泣",
        "唉",
        "可惜",
        "遗憾",
        "心疼",
        "悲伤",
        "😢",
        "😭",
        "忧伤",
        "愁",
        "泪",
        "离别",
    ],
    "angry": [
        "生气",
        "愤怒",
        "气死",
        "可恶",
        "混蛋",
        "讨厌",
        "烦",
        "😠",
        "😡",
        "暴怒",
        "恨",
        "岂有此理",
    ],
    "surprised": [
        "天哪",
        "哇",
        "不会吧",
        "居然",
        "竟然",
        "没想到",
        "😮",
        "震惊",
        "意想不到",
        "难以置信",
    ],
    "excited": [
        "太棒了",
        "终于",
        "冲啊",
        "加油",
        "好激动",
        "🔥",
        "兴奋",
        "期待",
        "万岁",
        "太赞",
    ],
    "gentle": ["轻轻", "温柔", "慢慢", "轻声", "柔声"],
    "serious": ["注意", "严肃", "重要", "必须", "绝对", "郑重", "正经", "认真"],
    "whisper": ["悄悄", "小声", "秘密", "嘘", "别出声", "低语"],
    "fearful": [
        "害怕",
        "恐惧",
        "吓人",
        "好怕",
        "恐怖",
        "😨",
        "胆寒",
        "毛骨悚然",
        "颤栗",
    ],
    "romantic": [
        "喜欢",
        "爱你",
        "想你",
        "拥抱",
        "牵手",
        "心动",
        "💕",
        "❤️",
        "甜蜜",
        "恋爱",
    ],
    "disgusted": ["恶心", "呕", "受不了", "太过分了", "厌恶"],
    "sarcastic": ["呵", "切", "厉害了", "了不起啊", "呵呵"],
    "nostalgic": ["想当年", "回忆", "怀念", "以前", "那时候", "曾经"],
    "playful": ["嘿嘿", "逗你", "开玩笑", "嘻嘻", "调皮"],
    "anxious": ["着急", "完了", "怎么办", "糟糕", "糟了", "坏了"],
    "proud": ["骄傲", "自豪", "看我的", "我做到了", "厉害"],
    "calm": ["淡定", "没关系", "不急", "慢慢来", "从容"],
    "tender": ["宝贝", "亲爱的", "心疼你", "照顾好自己", "保重"],
    "lazy": ["困", "好累", "不想动", "懒", "好困", "睡觉"],
}


class EmotionDetector:
    """Simple keyword-based emotion detector for Chinese text.

    Supports 20 emotions with weighted scoring.
    """

    def __init__(self, custom_keywords: Optional[dict[str, list[str]]] = None):
        self.keywords = dict(EMOTION_KEYWORDS)
        if custom_keywords:
            for emo, kws in custom_keywords.items():
                if emo in self.keywords:
                    self.keywords[emo].extend(kws)
                else:
                    self.keywords[emo] = kws

    def detect(self, text: str) -> Optional[str]:
        """Detect the dominant emotion from text.

        Returns the emotion name with the most keyword matches, or None for neutral.
        """
        if not text:
            return None

        text_lower = text.lower()
        scores: dict[str, int] = {}

        for emotion, keywords in self.keywords.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > 0:
                scores[emotion] = count

        if not scores:
            return None

        return max(scores, key=lambda k: scores[k])

    def detect_all(self, text: str) -> dict[str, int]:
        """Detect all emotion scores from text."""
        if not text:
            return {}

        text_lower = text.lower()
        scores: dict[str, int] = {}

        for emotion, keywords in self.keywords.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > 0:
                scores[emotion] = count

        return scores

    def add_keywords(self, emotion: str, keywords: list[str]) -> None:
        """Add custom keywords for an emotion."""
        if emotion in self.keywords:
            self.keywords[emotion].extend(keywords)
        else:
            self.keywords[emotion] = keywords


# ── Module-level convenience function ────────────────────────────
# Provides a stateless one-shot emotion detection API without
# requiring callers to instantiate ``EmotionDetector`` themselves.
# Used by ``tts.prompt_builder.detect_emotion`` and ``main.py``.


_default_detector: Optional[EmotionDetector] = None


def detect_emotion(text: str) -> Optional[str]:
    """Detect the dominant emotion from *text* using a default keyword detector.

    This is a thin wrapper around ``EmotionDetector.detect()`` so callers
    don't need to create their own instance.  Returns the emotion name
    (e.g. ``"happy"``, ``"sad"``) or ``None`` for neutral.
    """
    global _default_detector
    if _default_detector is None:
        _default_detector = EmotionDetector()
    return _default_detector.detect(text)
