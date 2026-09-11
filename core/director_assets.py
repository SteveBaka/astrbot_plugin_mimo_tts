# -*- coding: utf-8 -*-
"""导演模式资产：内置场景包模板、骨架模板与受控词表。

纯数据模块，不依赖插件其它运行时对象，便于单测与后续配置覆盖。
"""

from __future__ import annotations

from typing import Any

# 标准 user 稿骨架（§16.3 / §16.10.2）：任一段为空则整段省略
SKELETON_CHARACTER = "角色：{character}"
SKELETON_SCENE = "场景：{scene}"
SKELETON_GUIDANCE = "指导：\n{guidance}"

# 语气/副语言界定词（快路径与清洗参考；散文允许超出白名单）
CUE_VOCAB: dict[str, tuple[str, ...]] = {
    "语速与顿挫": (
        "极慢",
        "缓慢",
        "稍慢",
        "适中",
        "稍快",
        "急促",
        "连珠",
        "字字顿挫",
        "长停顿",
        "短停顿",
    ),
    "气声与实声": ("气声", "实声", "半气声", "气音收束", "纯气声"),
    "咬字肌理": ("咬字清晰", "唇齿音轻", "圆润", "尖锐", "轻拖音"),
}

# 禁止进入导演 user 稿的模式（动作/标签/系统指令）
CUE_FORBIDDEN: tuple[str, ...] = (
    "转身",
    "挥手",
    "坐下",
    "起立",
    "忽略以上",
    "system",
    "assistant",
)

DIRECTOR_USER_TEXT_HARD_MAX = 800
DIRECTOR_PAYLOAD_HARD_MAX = 2000


def _scene(
    name: str,
    character: str,
    scene: str,
    guidance: str,
    keywords: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "character": character,
        "scene": scene,
        "guidance": guidance,
        "keywords": keywords,
    }


# 内置场景（精做不贪多；快路径零 LLM）
BUILTIN_SCENES: dict[str, dict[str, Any]] = {
    item["name"]: item
    for item in (
        _scene(
            "深夜电台",
            character="午夜电台主持人，沉稳、有故事感，像在陪伴还没睡的人。",
            scene="深夜，城市安静下来，对着麦克风与听众独处。",
            guidance=(
                "语速偏慢，句间留白；音色偏低沉磁性，气声略多但不夸张。\n"
                "- 语速与顿挫：从容，句尾可稍拖。\n"
                "- 气声与实声：以实声为主，收尾带一点气声。\n"
                "- 咬字肌理：清晰、柔和，不尖锐。"
            ),
            keywords=("深夜", "电台", "午夜", "晚安电台"),
        ),
        _scene(
            "哄睡",
            character="温柔的陪伴者，耐心、体贴，像在床边轻声说话。",
            scene="睡前，对方已经躺下，房间很暗、很安静。",
            guidance=(
                "整体极轻、极慢；多气声，少力度；避免突然抬高音量。\n"
                "- 语速与顿挫：很慢，句子之间多停顿。\n"
                "- 气声与实声：偏气声，像耳语边缘。\n"
                "- 咬字肌理：软、圆，不强调重音。"
            ),
            keywords=("哄睡", "睡前", "助眠", "晚安"),
        ),
        _scene(
            "元气早安",
            character="开朗的朋友，明亮、有活力，带着刚起床的精神。",
            scene="清晨，拉开窗帘，阳光很好，向对方打招呼。",
            guidance=(
                "语速稍快，语调上扬；声音明亮干净，情绪积极但不吵闹。\n"
                "- 语速与顿挫：轻快，节奏清楚。\n"
                "- 气声与实声：实声明亮。\n"
                "- 咬字肌理：干净利落。"
            ),
            keywords=("早安", "清晨", "元气", "早上好"),
        ),
    )
}

BUILTIN_SCENE_NAMES: tuple[str, ...] = tuple(BUILTIN_SCENES.keys())


def list_builtin_scene_names() -> list[str]:
    return list(BUILTIN_SCENE_NAMES)


def get_builtin_scene(name: str) -> dict[str, Any] | None:
    key = str(name or "").strip()
    if not key:
        return None
    if key in BUILTIN_SCENES:
        return BUILTIN_SCENES[key]
    for item in BUILTIN_SCENES.values():
        if key == item["name"] or key in item.get("keywords", ()):
            return item
    return None
