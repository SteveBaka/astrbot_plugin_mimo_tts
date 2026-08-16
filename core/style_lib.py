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
    "你是一个语气风格标签筛选专家。请从【风格描述】中挑选 2-4 个最贴合的官方风格标签词，"
    "用于插件的唱歌风格标签收集。\n\n"
    "官方风格词表：\n"
    "整体语调：温柔/高冷/活泼/严肃/慵懒/俏皮/深沉/干练/凌厉\n"
    "音色定位：磁性/醇厚/清亮/空灵/稚嫩/苍老/甜美/沙哑/醇雅\n"
    "基础情绪：开心/悲伤/愤怒/恐惧/惊讶/兴奋/委屈/平静/冷漠\n"
    "复合情绪：怅然/欣慰/无奈/愧疚/释然/嫉妒/厌倦/忐忑/动情\n"
    "人设腔调：夹子音/御姐音/正太音/大叔音/台湾腔\n"
    "角色扮演：孙悟空/林黛玉\n\n"
    "规则：\n"
    "1. 只能输出上表中的词，空格分隔，2-4 个；无合适词只输出\"无\"\n"
    "2. 优先选整体语调与音色定位词，各不超过 2 个（最能决定听感）\n"
    "3. 词须与风格描述含义一致，不要强行凑数\n"
    "4. 不要输出任何解释、标点或思考过程，第一行即结果\n\n"
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


def extract_style_words(text: Optional[str]) -> list[str]:
    """从任意文本提取官方风格词（按词表稳定序，去重）。

    供 design/clone 通道复用：用户描述（如"温柔甜美的少女音"）中的
    官方词被自动识别，交给 style_words_to_hint 生成结构化提示，
    让服务端以词表语言理解风格（v2.2.0 起唱歌/设计/克隆共用词表）。
    """
    seen: list[str] = []
    for tag in FLAT_OFFICIAL_TAGS:
        if tag in str(text or "") and tag not in seen:
            seen.append(tag)
    return seen


def style_words_to_hint(words: Optional[list]) -> str:
    """官方风格词 → 结构化提示（按分类分组，供 design/clone 注入 user 通道）。

    例：["温柔", "甜美", "清亮"] → "整体语调温柔、甜美，音色定位清亮"。
    空词返回 ""（调用方不注入）。
    """
    grouped: dict[str, list[str]] = {}
    for tag in words or []:
        tag = str(tag or "").strip()
        if not tag:
            continue
        for category, tags in OFFICIAL_STYLE_TAGS.items():
            if tag in tags:
                grouped.setdefault(category, []).append(tag)
                break
    parts = [
        f"{category}{'、'.join(grouped[category])}"
        for category in OFFICIAL_STYLE_TAGS
        if grouped.get(category)
    ]
    return "，".join(parts)


def match_style_entry_by_name(
    text: Optional[str], examples: Optional[list] = None
):
    """精确匹配示例池条目名 → 返回该条目 dict；否则 None。

    方案 A（§14.5）：design_voice_description 可直接填示例池分类名
    （如"温柔甜美"）引用整条——调用方用该条目全部 words 生成词表提示、
    全部例句注入，修复 name 简写（"磁性低沉"→低沉非官方词）导致的
    词表提示缺词；自由描述文本不精确匹配时走 extract+match 链路。
    """
    name = str(text or "").strip()
    if not name or not examples:
        return None
    for entry in examples or []:
        if (
            isinstance(entry, dict)
            and str(entry.get("name", "") or "").strip() == name
        ):
            return entry
    return None


def match_style_examples(
    text: Optional[str],
    examples: Optional[list] = None,
    max_examples: int = 2,
) -> list[str]:
    """从文本匹配风格示例池，返回命中条目中 ≤max_examples 条例句（零 LLM）。

    §14.3 匹配引擎：文本 → extract_style_words（官方词）→ 与每条目的
    words 求交集 → 命中条目取 examples（按池序、去重、截断）。
    无命中返回 []（调用方零注入）。examples 为归一化后的
    list[{name, words, examples}]（来自 config.style_examples）。
    """
    words = set(extract_style_words(text))
    if not words or not examples:
        return []
    picked: list[str] = []
    for entry in examples or []:
        if len(picked) >= max_examples:
            break
        if not isinstance(entry, dict):
            continue
        entry_words = {
            str(w).strip() for w in (entry.get("words") or []) if str(w or "").strip()
        }
        if not entry_words or not (words & entry_words):
            continue
        for ex in entry.get("examples") or []:
            ex = str(ex or "").strip()
            if ex and ex not in picked:
                picked.append(ex)
                if len(picked) >= max_examples:
                    break
    return picked


def build_singing_prefix(tags: Optional[list] = None) -> str:
    """构建 assistant 开头标签：有词 → `(唱歌 词1 词2)`；无词 → `(唱歌)`。

    注：v2.2.0 实测矩阵证明唱歌模式不识别多风格括号（朗读/杂音），
    真实唱歌链路不再调用本函数；保留供未来 /singdebug 重建或非唱歌
    场景（普通播报风格标签）复用。
    """
    words = [str(t).strip() for t in (tags or []) if str(t or "").strip()]
    if not words:
        return "(唱歌)"
    return "(唱歌 " + " ".join(words) + ")"
