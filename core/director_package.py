# -*- coding: utf-8 -*-
"""导演模式场景包：通道无关中间表示与序列化。

字段按维拆分（§17.5 钩子），供 P5 角色库 / 自动 guidance 复用。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .director_assets import (
    CUE_FORBIDDEN,
    DIRECTOR_PAYLOAD_HARD_MAX,
    DIRECTOR_USER_TEXT_HARD_MAX,
)

_GUIDANCE_SOURCES = frozenset({"manual", "builtin", "auto"})


@dataclass
class ScenePackage:
    """与通道无关的导演场景包。"""

    scene_name: str = ""
    character_id: str = ""
    character: str = ""
    scene: str = ""
    guidance: str = ""
    style_words: list[str] = field(default_factory=list)
    guidance_source: str = "builtin"

    def is_empty(self) -> bool:
        return not (self.character or self.scene or self.guidance or self.style_words)

    def summary(self, limit: int = 40) -> str:
        parts = []
        if self.scene_name:
            parts.append(self.scene_name)
        if self.character:
            parts.append(self.character[:limit])
        elif self.guidance:
            parts.append(self.guidance[:limit])
        elif self.scene:
            parts.append(self.scene[:limit])
        return " / ".join(parts) if parts else "（空）"


def _strip_forbidden(text: str) -> str:
    cleaned = str(text or "")
    for word in CUE_FORBIDDEN:
        if word.lower() in cleaned.lower():
            cleaned = re.sub(re.escape(word), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\[\]（）()]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > DIRECTOR_USER_TEXT_HARD_MAX:
        cleaned = cleaned[:DIRECTOR_USER_TEXT_HARD_MAX].rstrip()
    return cleaned


def sanitize_package(data: Any) -> Optional[ScenePackage]:
    """清洗任意输入为合法 ScenePackage；无法识别则返回 None。"""
    if isinstance(data, ScenePackage):
        raw = asdict(data)
    elif isinstance(data, dict):
        raw = data
    else:
        return None

    source = str(raw.get("guidance_source") or "builtin").strip().lower()
    if source not in _GUIDANCE_SOURCES:
        source = "manual"

    words_raw = raw.get("style_words") or []
    if isinstance(words_raw, str):
        words = [w.strip() for w in re.split(r"[\s,，、/]+", words_raw) if w.strip()]
    elif isinstance(words_raw, (list, tuple)):
        words = [str(w).strip() for w in words_raw if str(w or "").strip()]
    else:
        words = []
    words = words[:8]

    pkg = ScenePackage(
        scene_name=str(raw.get("scene_name") or "").strip()[:40],
        character_id=str(raw.get("character_id") or "").strip()[:40],
        character=_strip_forbidden(raw.get("character") or "")[:200],
        scene=_strip_forbidden(raw.get("scene") or "")[:200],
        guidance=_strip_forbidden(raw.get("guidance") or "")[:400],
        style_words=words,
        guidance_source=source,
    )
    if pkg.is_empty():
        return None
    return pkg


def dumps_package(pkg: ScenePackage) -> str:
    """序列化为 user_state 可存的 JSON 字符串；超长返回空串表示拒绝。"""
    payload = json.dumps(asdict(pkg), ensure_ascii=False, separators=(",", ":"))
    if len(payload) > DIRECTOR_PAYLOAD_HARD_MAX:
        return ""
    return payload


def loads_package(raw: Any) -> Optional[ScenePackage]:
    """从 user_state 字符串还原场景包；失败返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return sanitize_package(data)
