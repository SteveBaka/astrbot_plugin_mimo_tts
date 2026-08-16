# -*- coding: utf-8 -*-
"""MiMO 唱歌风格标签库：官方风格词表 + 标签收集/提取/构建。

MiMO-V2.5-TTS 官方风格标签机制（docs/sing-mode-feature.md §6 与官方
usage-guide）：
  - 风格标签写在 assistant 文本开头括号内：`(唱歌 温柔 甜美)歌词`
    （支持多风格同括号，等效取值 唱歌/sing/singing）；
  - 官方风格词按分类推荐（整体语调/音色定位/基础情绪/复合情绪/
    人设腔调/角色扮演），同时支持未在列表中的自定义风格词；
  - 音频标签 [xx] 在唱歌中会被当作歌词唱出（插件实测），不得进入
    assistant 文本——风格标签括号是官方语法、实测不会唱出。

v2.2.14 起唱歌风格改走「双通道」：
  - assistant 开头括号（标签通道）：喂服务端风格标签解析器；
  - user 控制指令（自由文本通道）：画面感描述（官方示例
    "Bright, bouncy… like you're bursting with good news…" 同构）。

标签收集优先级（collect_sing_tags）：用户括号词 > 风格组 style_tags
显式字段 > 本地词表从 style 描述提取；去重后截断至 max_tags。
"""

from __future__ import annotations

from typing import Optional

# 官方风格标签词表（分类；来源：MiMO usage-guide「风格类型/风格示例」）
OFFICIAL_STYLE_TAGS: dict[str, tuple[str, ...]] = {
    "整体语调": ("温柔", "高冷", "活泼", "严肃", "慵懒", "俏皮", "深沉", "干练", "凌厉"),
    "音色定位": ("磁性", "醇厚", "清亮", "空灵", "稚嫩", "苍老", "甜美", "沙哑", "醇雅"),
    "基础情绪": ("开心", "悲伤", "愤怒", "恐惧", "惊讶", "兴奋", "委屈", "平静", "冷漠"),
    "复合情绪": ("怅然", "欣慰", "无奈", "愧疚", "释然", "嫉妒", "厌倦", "忐忑", "动情"),
    "人设腔调": ("夹子音", "御姐音", "正太音", "大叔音", "台湾腔"),
    "角色扮演": ("孙悟空", "林黛玉"),
}

# 平铺官方词表（按分类稳定序，用于本地提取与 LLM 白名单过滤）
FLAT_OFFICIAL_TAGS: tuple[str, ...] = tuple(
    tag for tags in OFFICIAL_STYLE_TAGS.values() for tag in tags
)

# 标签注入数量上下限
SING_TAGS_MIN: int = 1
SING_TAGS_MAX: int = 4

# 唱歌关键字（等效取值）：用户括号如 (唱歌 温柔) 经 extract_leading_styles
# 拆分后会混入"唱歌"，不得作为风格标签词重复注入
SING_KEYWORDS: tuple[str, ...] = ("唱歌", "sing", "singing")

# LLM 标签筛选模板（第 3 层兜底；{style} 描述基准 + {text} 歌词占位符）。
# 输出强制经 FLAT_OFFICIAL_TAGS 白名单过滤，防幻觉词进入 assistant 括号。
SING_TAG_PROMPT = (
    "你是 MiMO 风格标签筛选器。请从【风格描述】中挑选 2-4 个最贴合的官方风格标签词，"
    "用于 (唱歌 词…) 开头风格标签。\n\n"
    "官方风格词表：\n"
    "整体语调：温柔/高冷/活泼/严肃/慵懒/俏皮/深沉/干练/凌厉\n"
    "音色定位：磁性/醇厚/清亮/空灵/稚嫩/苍老/甜美/沙哑/醇雅\n"
    "基础情绪：开心/悲伤/愤怒/恐惧/惊讶/兴奋/委屈/平静/冷漠\n"
    "复合情绪：怅然/欣慰/无奈/愧疚/释然/嫉妒/厌倦/忐忑/动情\n"
    "人设腔调：夹子音/御姐音/正太音/大叔音/台湾腔\n"
    "角色扮演：孙悟空/林黛玉\n\n"
    "规则：\n"
    "1. 只能输出上表中的词，空格分隔，2-4 个；无合适词只输出\"无\"\n"
    "2. 优先选整体语调与音色定位词，各不超过 2 个\n"
    "3. 不要输出任何解释、标点或思考过程\n\n"
    "风格描述（基准）：{style}\n歌词：{text}"
)


def collect_sing_tags(
    bracket_styles: Optional[list] = None,
    style_tags_explicit: Optional[list] = None,
    style_desc: Optional[str] = None,
    max_tags: int = SING_TAGS_MAX,
) -> list[str]:
    """按优先级收集唱歌标签词：用户括号词 > 组 style_tags 显式 > 本地提取。

    去重（保持首见顺序）；截断至 max_tags。显式词（括号/组字段）全放行
    （支持自定义词，如"可爱"）；本地提取只认官方词表。
    """
    tags: list[str] = []
    for src in (bracket_styles, style_tags_explicit):
        for raw in src or []:
            tag = str(raw or "").strip()
            if (
                tag
                and tag not in tags
                and tag.lower() not in SING_KEYWORDS
            ):
                tags.append(tag)
    for tag in FLAT_OFFICIAL_TAGS:
        if tag in str(style_desc or "") and tag not in tags:
            tags.append(tag)
    return tags[:max_tags]


def filter_official_tags(words: Optional[list]) -> list[str]:
    """LLM 输出白名单过滤：仅保留官方词表词，去重、保序。"""
    seen: list[str] = []
    for raw in words or []:
        tag = str(raw or "").strip()
        if tag in FLAT_OFFICIAL_TAGS and tag not in seen:
            seen.append(tag)
    return seen


def build_singing_prefix(tags: Optional[list] = None) -> str:
    """构建 assistant 开头标签：有词 → `(唱歌 词1 词2)`；无词 → `(唱歌)`。"""
    words = [str(t).strip() for t in (tags or []) if str(t or "").strip()]
    if not words:
        return "(唱歌)"
    return "(唱歌 " + " ".join(words) + ")"
