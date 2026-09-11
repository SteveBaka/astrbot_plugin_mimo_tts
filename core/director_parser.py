# -*- coding: utf-8 -*-
"""导演模式解析：词表快路径 + 三维标签切分（本切片零 LLM）。

LLM 自由描述解析属后续（director_parse_llm），此处不引入。
"""

from __future__ import annotations

import re
from typing import Optional

from .director_assets import get_builtin_scene
from .director_package import ScenePackage, sanitize_package

_LABEL_LINE = re.compile(
    r"^[ \t]*(角色|场景|指导|Role|Character|CHARACTER|Scene|SCENE|"
    r"Guidance|GUIDANCE|Direction|DIRECTION)[ \t]*[:：][ \t]*",
    re.IGNORECASE,
)


def _normalize_label(label: str) -> Optional[str]:
    low = label.strip().lower()
    if low in ("角色", "role", "character"):
        return "character"
    if low in ("场景", "scene"):
        return "scene"
    if low in ("指导", "guidance", "direction"):
        return "guidance"
    return None


def try_parse_structured(text: str) -> Optional[ScenePackage]:
    """切分「角色：/场景：/指导：」或英文等价标签；无结构返回 None。"""
    raw = str(text or "").strip()
    if not raw:
        return None

    fields: dict[str, list[str]] = {"character": [], "scene": [], "guidance": []}
    current: Optional[str] = None
    saw_label = False

    for line in raw.splitlines():
        m = _LABEL_LINE.match(line)
        if m:
            key = _normalize_label(m.group(1))
            if key is None:
                continue
            saw_label = True
            current = key
            rest = line[m.end() :].strip()
            if rest:
                fields[key].append(rest)
            continue
        if current:
            fields[current].append(line.strip())

    if not saw_label:
        return None

    pkg = sanitize_package(
        {
            "character": "\n".join(x for x in fields["character"] if x),
            "scene": "\n".join(x for x in fields["scene"] if x),
            "guidance": "\n".join(x for x in fields["guidance"] if x),
            "guidance_source": "manual",
        }
    )
    return pkg


def match_builtin_scene(text: str) -> Optional[ScenePackage]:
    """内置场景名 / 关键词精确命中 → 零 LLM 场景包。"""
    raw = str(text or "").strip()
    if not raw or len(raw) > 40:
        return None
    item = get_builtin_scene(raw)
    if not item:
        return None
    return sanitize_package(
        {
            "scene_name": item["name"],
            "character": item["character"],
            "scene": item["scene"],
            "guidance": item["guidance"],
            "guidance_source": "builtin",
        }
    )


def parse_director_input(text: str) -> Optional[ScenePackage]:
    """解析入口：三维标签优先，其次内置场景名。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    pkg = try_parse_structured(raw)
    if pkg:
        return pkg
    return match_builtin_scene(raw)
