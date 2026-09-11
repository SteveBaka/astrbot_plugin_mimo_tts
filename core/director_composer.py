# -*- coding: utf-8 -*-
"""导演模式组合层：覆盖合并 + 固定中文骨架渲染。

只填空档：显式速度等会过滤 guidance 中对应提示，不改用户设置本身。
"""

from __future__ import annotations

import re
from typing import Optional

from .director_assets import (
    SKELETON_CHARACTER,
    SKELETON_GUIDANCE,
    SKELETON_SCENE,
)
from .director_package import ScenePackage, loads_package

_SPEED_CUES = re.compile(
    r"(极慢|缓慢|稍慢|稍快|急促|语速偏慢|语速稍快|语速很慢|很慢)",
)


def filter_conflicts(pkg: ScenePackage, uset: Optional[dict] = None) -> ScenePackage:
    """按会话显式设置过滤 guidance 冲突提示（只读 uset，不修改 uset）。"""
    uset = uset or {}
    guidance = pkg.guidance
    if not guidance:
        return pkg

    try:
        speed = float(uset.get("speed", 1.0) or 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    if abs(speed - 1.0) > 1e-6:
        guidance = _SPEED_CUES.sub("", guidance)
        guidance = re.sub(r"\n{3,}", "\n\n", guidance).strip()

    return ScenePackage(
        scene_name=pkg.scene_name,
        character_id=pkg.character_id,
        character=pkg.character,
        scene=pkg.scene,
        guidance=guidance,
        style_words=list(pkg.style_words),
        guidance_source=pkg.guidance_source,
    )


def render_user_text(pkg: ScenePackage) -> str:
    """渲染固定中文三维骨架；空段整段省略。"""
    if pkg is None or pkg.is_empty():
        return ""
    parts: list[str] = []
    if pkg.character:
        parts.append(SKELETON_CHARACTER.format(character=pkg.character.strip()))
    if pkg.scene:
        parts.append(SKELETON_SCENE.format(scene=pkg.scene.strip()))
    guidance = (pkg.guidance or "").strip()
    if not guidance and pkg.style_words:
        guidance = "整体偏" + "、".join(pkg.style_words) + "，语气自然。"
    if guidance:
        parts.append(SKELETON_GUIDANCE.format(guidance=guidance))
    return "\n".join(parts)


def merge_director_into_prompt(base_prompt: str, director_text: str) -> str:
    """base 控制短句与导演骨架拼接；骨架含换行时独立成块。"""
    head = str(base_prompt or "").strip()
    body = str(director_text or "").strip()
    if not head:
        return body
    if not body:
        return head
    if "\n" in body:
        return f"{head}\n{body}"
    return f"{head}，{body}"


def apply_director_to_prompt(
    base_prompt: str, uset: Optional[dict] = None
) -> str:
    """从 uset 读取导演状态并合成最终 user 控制稿；无包时原样返回。

    ``base_prompt`` 已含 emotion/style_hint 等（build_control_prompt），
    此处只把导演骨架拼接在后，避免重复注入 style_hint。
    """
    uset = uset or {}
    if str(uset.get("director_mode") or "") not in ("once", "session"):
        return base_prompt
    pkg = loads_package(uset.get("director_payload"))
    if not pkg:
        return base_prompt
    pkg = filter_conflicts(pkg, uset)
    director_text = render_user_text(pkg)
    if not director_text:
        return base_prompt
    return merge_director_into_prompt(base_prompt, director_text)
