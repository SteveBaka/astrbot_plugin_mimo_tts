# -*- coding: utf-8 -*-
"""
Configuration manager for astrbot_plugin_mimo_tts.
Reads _conf_schema.json and manages plugin settings.

Supports nested schema (type: "object" with items) by flattening
into a internal dict for backward-compatible property access.
"""

from __future__ import annotations

from astrbot.api import logger

import json
import re
from typing import Any, Optional

# ── 唱歌风格库约束（sing-mode-feature.md §8.2 输入卫生） ──
SING_STYLES_MAX = 20
_SING_NAME_MAX = 20
_SING_STYLE_TEXT_MAX = 200
_SING_TAGS_MAX = 5

# ── 风格示例池约束（§14 导演模式先导，v2.2.0） ──
STYLE_EXAMPLES_MAX = 50
_EXAMPLE_WORDS_MAX = 8
_EXAMPLE_TEXT_MAX = 80


def normalize_sing_style_tags(raw: Any) -> list[str]:
    """演绎词（纯文本，多个用顿号/逗号/空格分隔，如 "轻笑、气声"）。

    v2.2.4 起仅支持字符串写法（摒弃 ["[轻笑]"] 旧数组写法）。
    """
    if not isinstance(raw, str):
        return []
    parts = [p.strip() for p in re.split(r"[\s,，、]+", raw) if p.strip()]
    return parts[:_SING_TAGS_MAX]


# 内置风格示例池（§14 导演模式先导，v2.2.0）：官方风格词 → 画面感中文例句。
# words 须为官方风格词（match 时只认词表）；例句禁用收窄词、每条 ≤40 字。
STYLE_EXAMPLES_PRESET = (
    '[\n'
    '  {\n    "name": "温柔甜美",\n    "words": "温柔 甜美",\n    "examples": ['
    '"像融化的棉花糖一样温柔，声音软糯清甜，尾音轻轻上扬，语速放缓",'
    '"像午后阳光里的一杯热牛奶，温柔绵密，每一句都带着甜甜的笑意"\n    ]\n  },\n'
    '  {\n    "name": "磁性低沉",\n    "words": "磁性 深沉",\n    "examples": ['
    '"像午夜电台的主播，磁性沙哑，句句都带停顿与余韵，语速沉缓"\n    ]\n  },\n'
    '  {\n    "name": "活泼俏皮",\n    "words": "活泼 俏皮",\n    "examples": ['
    '"像清晨的第一声鸟鸣，轻快雀跃，尾音总爱往上跳一跳，气息明快"\n    ]\n  },\n'
    '  {\n    "name": "清亮空灵",\n    "words": "清亮 空灵",\n    "examples": ['
    '"像山涧泉水一样清亮通透，尾音带一丝空灵的余韵，气声自然"\n    ]\n  },\n'
    '  {\n    "name": "御姐高冷",\n    "words": "御姐音 高冷",\n    "examples": ['
    '"像职场精英的从容开场，御姐音高冷利落，语气笃定，句尾干脆"\n    ]\n  },\n'
    '  {\n    "name": "慵懒安逸",\n    "words": "慵懒",\n    "examples": ['
    '"像午后窝在沙发里的惬意，慵懒随性，语速不紧不慢，尾音拖得舒展"\n    ]\n  }\n]'
)


def normalize_style_examples(raw: Any) -> list[dict]:
    """归一化风格示例池 → list[{name, words, examples}]。

    §14.3：words/examples 支持空格/顿号分隔字符串或数组；结构归一、
    长度截断；words 的官方词校验在 match_style_examples 时进行（单一来源）。
    容错：JSON 解析失败/非法项跳过；条目数上限 STYLE_EXAMPLES_MAX。
    """
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = [raw]
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        parsed = _loads_lenient(text)
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        entries = parsed
    else:
        return []
    items: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "") or "").strip()
        if not name:
            continue

        def _words(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(w).strip() for w in value if str(w or "").strip()]
            if isinstance(value, str):
                return [w.strip() for w in re.split(r"[\s,，、]+", value) if w.strip()]
            return []

        def _examples(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(e).strip() for e in value if str(e or "").strip()]
            if isinstance(value, str):
                return [e.strip() for e in re.split(r"[\n;；]+", value) if e.strip()]
            return []

        items.append({
            "name": name[:_SING_NAME_MAX],
            "words": _words(entry.get("words"))[:_EXAMPLE_WORDS_MAX],
            "examples": _examples(entry.get("examples"))[:_EXAMPLE_TEXT_MAX],
        })
    return items[:STYLE_EXAMPLES_MAX]


def migrate_sing_styles(cfg, astrbot_config=None) -> None:
    """sing_styles 预设迁移：空值/旧版预设升级为当前预设。

    AstrBot 只对缺失键填默认值，已保存值需自行迁移；写入后尝试持久化。
    """
    raw = str(cfg.get("sing_styles") or "").strip()
    if raw in ("", "[]") or raw in (
        _SING_STYLES_PRESET_V1.strip(),
        _SING_STYLES_PRESET_V2.strip(),
    ):
        cfg.set("sing_styles", SING_STYLES_PRESET)
        save = getattr(astrbot_config, "save_config", None)
        if callable(save):
            try:
                save()
                logger.info("MiMO TTS: sing_styles preset migrated/upgraded")
            except Exception:
                logger.warning("MiMO TTS: sing_styles preset migration not persisted")


# 内置风格库预设（换行格式化；v2.2.14 起双组 + style_tags 显式标签字段：
# 小雪演示本地词表提取路径；小花演示 style_tags 自定义词"可爱"放行路径）
SING_STYLES_PRESET = (
    '[\n  {\n    "name": "小雪",\n    "style": "声音清澈，温柔甜美",'
    '\n    "tags": "轻笑",\n    "voice": "茉莉",\n    "speed": 1.5,\n    "pitch": 1\n  },'
    '\n  {\n    "name": "小花",\n    "style": "温柔甜美的可爱风格",'
    '\n    "tags": "可爱",\n    "style_tags": "可爱",'
    '\n    "voice": "冰糖",\n    "speed": 1.1,\n    "pitch": 1\n  }\n]'
)
# v2.2.5 的预设（无 speed/pitch），用于一次性升级迁移识别
_SING_STYLES_PRESET_V1 = (
    '[\n  {\n    "name": "小雪",\n    "style": "声音清澈，温柔甜美",'
    '\n    "tags": "轻笑",\n    "voice": "茉莉"\n  }\n]'
)
# v2.2.6~v2.2.11 的预设（仅小雪，speed 1.1 / pitch 2），升级迁移识别
_SING_STYLES_PRESET_V2 = (
    '[\n  {\n    "name": "小雪",\n    "style": "声音清澈，温柔甜美",'
    '\n    "tags": "轻笑",\n    "voice": "茉莉",\n    "speed": 1.1,\n    "pitch": 2\n  }\n]'
)


def _normalize_style_entry(
    name: str, style: Any, tags: Any, voice: Any,
    speed: Any = None, pitch: Any = None, style_tags: Any = None,
) -> dict:
    try:
        speed_val = (
            max(0.5, min(2.0, float(speed))) if speed not in (None, "") else None
        )
    except (TypeError, ValueError):
        speed_val = None
    try:
        pitch_val = (
            max(-12, min(12, int(pitch))) if pitch not in (None, "") else None
        )
    except (TypeError, ValueError):
        pitch_val = None
    return {
        "name": str(name).strip()[:_SING_NAME_MAX],
        "style": str(style or "").strip()[:_SING_STYLE_TEXT_MAX],
        "tags": normalize_sing_style_tags(tags),
        # 显式风格标签词（v2.2.14）：注入 assistant 开头 (唱歌 词…) 括号，
        # 支持自定义词；与 tags（演绎词，走 user 通道）职责分离
        "style_tags": normalize_sing_style_tags(style_tags),
        "voice": str(voice or "").strip()[:_SING_NAME_MAX],
        "speed": speed_val,
        "pitch": pitch_val,
    }


def _loads_lenient(text: str):
    """容错 JSON 解析：直接解析 → 全角引号转换重试 → 裸对象序列自动补数组括号。

    覆盖两类高频手误：多个对象逗号并列但缺数组括号；粘贴带入全角引号。
    仍失败返回 None（调用方回退空库）。
    """
    try:
        return json.loads(text)
    except ValueError:
        pass
    repaired = (
        text.replace(chr(8220), chr(34)).replace(chr(8221), chr(34))
        .replace(chr(8216), chr(39)).replace(chr(8217), chr(39))
    )
    for candidate in (repaired, "[" + repaired + "]", "[" + text + "]"):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def normalize_sing_styles(raw: Any) -> list[dict]:
    """归一化唱歌风格库 → list[{name,style,tags,voice}]。

    输入为 JSON 字符串（text+editor_mode 配置，配置面板已内置换行预设示例）；
    v2.2.4 起仅支持 JSON 格式（摒弃行式与旧 tags 数组写法）。
    容错：JSON 解析失败/非法项跳过不整体报错；组数上限 SING_STYLES_MAX。
    """
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        # 单个裸对象（已解析）也视作单组库
        entries = [raw]
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        parsed = _loads_lenient(text)
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        entries = parsed
    else:
        return []
    items: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("name", "")).strip():
            continue
        items.append(_normalize_style_entry(
            entry.get("name", ""),
            entry.get("style", ""),
            entry.get("tags", ""),
            entry.get("voice", ""),
            entry.get("speed"),
            entry.get("pitch"),
            entry.get("style_tags"),
        ))
    return items[:SING_STYLES_MAX]


def find_sing_style(styles: list[dict], name: str) -> Optional[dict]:
    """在风格库中查找：精确匹配 → 包含匹配。未命中返回 None。"""
    name = str(name or "").strip()
    if not name:
        return None
    for s in styles:
        if s["name"] == name:
            return s
    for s in styles:
        if name in s["name"] or s["name"] in name:
            return s
    return None


def normalize_clone_style_pool(raw: Any) -> list[dict]:
    """归一化克隆音色风格控制池 → list[{name, style, audio_tags}]。

    输入为 JSON 字符串（text+editor_mode 配置，与 sing_styles 同格式）；
    v2.2.8 起作为 per-voice 风格/标签的**配置权威数据源**（配置面板联动）。
    name = 克隆音色 voice_id；style / audio_tags 留空 = 用全局。
    容错：JSON 解析失败/非法项跳过不整体报错。
    """
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = [raw]
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        parsed = _loads_lenient(text)
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        entries = parsed
    else:
        return []
    items: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        items.append({
            "name": name,
            "style": str(entry.get("style", "") or "").strip(),
            "audio_tags": str(entry.get("audio_tags", "") or "").strip(),
        })
    return items


def find_clone_pool_entry(pool: list[dict], voice_id: str) -> Optional[dict]:
    """在克隆音色风格控制池中按 voice_id（name 字段）精确查找。"""
    voice_id = str(voice_id or "").strip()
    if not voice_id:
        return None
    for e in pool:
        if e.get("name") == voice_id:
            return e
    return None


def normalize_design_style_pool(raw: Any) -> list[dict]:
    """归一化设计音色风格控制池 → list[{name, description}]。

    输入为 JSON 字符串（text+editor_mode 配置，与 sing_styles 同格式）；
    v2.2.9 起作为 design 音色描述的**配置权威数据源**（配置面板联动，
    与「风格示例池」同组，描述可填分类名触发方案 A，供导演模式素材复用）。
    name = 设计音色 voice_id；description 留空 = 用全局 design_voice_description。
    容错：JSON 解析失败/非法项跳过不整体报错。
    """
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = [raw]
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        parsed = _loads_lenient(text)
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        entries = parsed
    else:
        return []
    items: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        items.append({
            "name": name,
            "description": str(entry.get("description", "") or "").strip(),
        })
    return items


def find_design_pool_entry(pool: list[dict], voice_id: str) -> Optional[dict]:
    """在设计音色风格控制池中按 voice_id（name 字段）精确查找。"""
    voice_id = str(voice_id or "").strip()
    if not voice_id:
        return None
    for e in pool:
        if e.get("name") == voice_id:
            return e
    return None


def resolve_sing_style(
    styles: list[dict],
    named: str,
    prompt_override: str,
    bracket_styles: list[str],
) -> tuple[str, list[str], str, Optional[dict]]:
    """解析唱歌风格优先级链，返回 (风格文本, 静态标签, 来源, 命中的组或 None)。

    优先级（v2.2.1 起，无全局兜底——(唱歌) 标签由 /sing 自动注入）：
      1. -p 一次性提示词 / 括号风格词（同级叠加，覆盖组内 style 文本）
      2. -s 一次性组名 / 会话 sing_style（命名组）
      3. 都无 → 仅 (唱歌) 标签
    组的静态 tags 与 voice 和 style 文本正交：style 被 -p 覆盖时 tags/voice 仍生效。
    """
    named = str(named or "").strip()
    group = find_sing_style(styles, named) if named else None
    group_tags = list(group["tags"]) if group else []
    group_style = str(group["style"]).strip() if group else ""

    free_parts: list[str] = []
    po = str(prompt_override or "").strip()
    if po:
        free_parts.append(po[:_SING_STYLE_TEXT_MAX])
    free_parts.extend(w for w in bracket_styles if w)

    if free_parts:
        return "，".join(free_parts), group_tags, "free", group
    if group_style:
        return group_style, group_tags, f"group:{group['name']}", group
    return "", [], "none", group


class ConfigManager:
    """Plugin configuration manager.

    AstrBot stores plugin config as nested dicts when schema uses
    ``type: "object"``.  This class flattens the nested structure so
    that all existing property accessors (``self.config.api_key`` etc.)
    continue to work unchanged.
    """

    # ── Schema defaults (flat key → value) ──

    _SCHEMA_DEFAULTS: dict[str, Any] = {
        # API settings
        "api_key": "",
        "api_base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-tts",
        # Voice settings
        "default_voice": "mimo_default",
        "sing_voice": "",
        "sing_styles": SING_STYLES_PRESET,
        "sing_lyrics_polish": False,
        "sing_polish_llm_provider": "",
        "sing_polish_timeout": 20,
        "sing_polish_cache_ttl": 600,
        "sing_style_source": "prompt",
        "sing_tag_prompt": "",
        "sing_direct_prompt": "",
        "nl_sing_enabled": False,
        "nl_sing_cooldown": 30,
        "nl_sing_tool": False,
        "llm_tts_tool": True,
        "tts_output_mode": "default",
        "tts_example_inject": False,
        # TTS parameters
        "emotion_override": "",
        "default_speed": 1.0,
        "default_pitch": 0,
        "style_hint": "",
        "breath_enabled": False,
        "stress_enabled": False,
        "laughter_enabled": False,
        "pause_enabled": False,
        # Output settings
        "probability": 0.8,
        "auto_tts": True,
        "send_text_with_tts": True,
        "send_text_async": False,
        "audio_format": "wav",
        "min_text_length": 5,
        "max_text_length": 500,
        # Segmentation
        "enable_segmentation": False,
        "segment_pattern": "sentence",
        "segment_max_count": 10,
        "segment_voice_probability": 1.0,
        "segment_text_fallback": True,
        # Voice polish (LLM)
        "enable_voice_polish": False,
        "display_polished_text": False,
        "polish_llm_provider": "",
        "polish_prompt": "",
        "optimize_text_preview": False,
        # Clone settings
        "clone_enabled": True,
        "clone_model": "mimo-v2.5-tts-voiceclone",
        "clone_voice_id": "",
        "clone_style_prompt": "",
        "clone_audio_tags": "",
        "clone_style_pool": "[]",
        # Design settings
        "design_enabled": True,
        "design_model": "mimo-v2.5-tts-voicedesign",
        "design_voice_description": "",
        "design_style_pool": "[]",
        "style_examples": STYLE_EXAMPLES_PRESET,
        # Presets
        "preset_gentle_female": "温柔的女生音色，轻柔细腻",
        "preset_serious_male": "成熟男声，严肃有力",
        "preset_cute_girl": "年轻女孩的声音，活泼甜美",
        "preset_storyteller": "温和的讲述者声音，抑扬顿挫",
        "preset_news_anchor": "标准普通话，字正腔圆，专业权威",
        # Model hyperparameters
        "temperature": 0.6,
        "top_p": 0.95,
        # Advanced
        "timeout": 60,
        "max_retries": 2,
        # Plugin log
        "enable_plugin_log": False,
    }

    # ── Map flat keys to their nested path in the config dict ──
    # Built dynamically in __init__ from the actual nested config structure.
    # e.g. "api_key" → ("api_settings", "api_key")

    def __init__(self, config: dict):
        raw_cfg: dict = config or {}

        # Clean legacy fields
        raw_cfg.pop("singing_mode", None)
        self._design_voice_id: str = str(raw_cfg.pop("design_voice_id", "")).strip()

        # Store the raw (possibly nested) config for persistence
        self._cfg: dict = raw_cfg

        # Build path mapping and flatten nested config
        self._key_to_path: dict[str, tuple[str, ...]] = {}
        self._flat: dict[str, Any] = {}
        self._flatten(self._cfg, self._flat)

        # Ensure all schema defaults exist in the flat dict
        for key, default_val in self._SCHEMA_DEFAULTS.items():
            if key not in self._flat:
                self._flat[key] = default_val

    # ── Flatten / unflatten helpers ──

    def _flatten(self, src: dict, dst: dict, path: tuple[str, ...] = ()) -> None:
        """Recursively flatten a nested dict into *dst* and build path mapping."""
        for k, v in src.items():
            current = path + (k,)
            if isinstance(v, dict):
                self._flatten(v, dst, current)
            else:
                dst[k] = v
                if len(current) > 1:
                    self._key_to_path[k] = current

    def _set_nested(self, key: str, value: Any) -> None:
        """Write a flat key back into the nested ``_cfg`` dict."""
        path = self._key_to_path.get(key)
        if path is None:
            self._cfg[key] = value
            return
        d = self._cfg
        for segment in path[:-1]:
            if segment not in d or not isinstance(d[segment], dict):
                d[segment] = {}
            d = d[segment]
        d[path[-1]] = value

    # ── Generic accessor ──

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by flat key."""
        return self._flat.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value (updates both flat and nested dicts)."""
        self._flat[key] = value
        self._set_nested(key, value)

    # ── Typed property accessors ──

    @property
    def api_key(self) -> str:
        return str(self._flat.get("api_key", ""))

    @property
    def api_base_url(self) -> str:
        return str(self._flat.get("api_base_url", ""))

    @property
    def model(self) -> str:
        return str(self._flat.get("model", "mimo-v2.5-tts"))

    @property
    def default_voice(self) -> str:
        return str(self._flat.get("default_voice", "mimo_default"))

    @property
    def sing_voice(self) -> str:
        return str(self._flat.get("sing_voice", ""))

    @property
    def sing_styles(self) -> list[dict]:
        """归一化后的唱歌风格库（JSON 字符串/行式/list 双格式，见 normalize_sing_styles）。"""
        return normalize_sing_styles(self._flat.get("sing_styles", "[]"))

    def find_sing_style_by_name(self, name: str) -> Optional[dict]:
        return find_sing_style(self.sing_styles, name)

    @property
    def sing_lyrics_polish(self) -> bool:
        return bool(self._flat.get("sing_lyrics_polish", False))

    @property
    def sing_polish_llm_provider(self) -> str:
        """唱歌润色专用 Provider：留空回退通用润色 Provider，再留空用当前对话模型。"""
        return str(self._flat.get("sing_polish_llm_provider", "") or "")

    @property
    def sing_style_source(self) -> str:
        """唱歌风格注入源：prompt=user 自然语言描述（默认，官方唱歌风格通道，实测稳定）；
        tag=assistant 括号风格标签（实验：实测 (唱歌 词…) 多风格组合会朗读，供未来模型/格式验证）；
        off=关闭风格注入。"""
        return str(self._flat.get("sing_style_source", "prompt") or "prompt")

    @property
    def sing_polish_timeout(self) -> int:
        """润色 LLM 超时（秒，0=不限制）。"""
        try:
            value = int(self._flat.get("sing_polish_timeout", 20) or 0)
        except (ValueError, TypeError):
            value = 20
        return max(0, value)

    @property
    def sing_polish_cache_ttl(self) -> int:
        """润色结果缓存 TTL（秒，0=关闭）。"""
        try:
            value = int(self._flat.get("sing_polish_cache_ttl", 600) or 0)
        except (ValueError, TypeError):
            value = 600
        return max(0, value)

    @property
    def sing_tag_prompt(self) -> str:
        """标签筛选 LLM 模板（第 3 层兜底；留空用内置 SING_TAG_PROMPT）。"""
        return str(self._flat.get("sing_tag_prompt", "") or "")

    @property
    def sing_direct_prompt(self) -> str:
        return str(self._flat.get("sing_direct_prompt", "") or "")

    @property
    def nl_sing_enabled(self) -> bool:
        return bool(self._flat.get("nl_sing_enabled", False))

    @property
    def nl_sing_tool(self) -> bool:
        """NL 唱歌 LLM 工具兜底开关（需与 nl_sing_enabled 同时开启）。"""
        return bool(self._flat.get("nl_sing_tool", False))

    @property
    def llm_tts_tool(self) -> bool:
        """Direct LLM TTS tool switch."""
        return bool(self._flat.get("llm_tts_tool", True))

    @property
    def nl_sing_cooldown(self) -> int:
        try:
            value = int(self._flat.get("nl_sing_cooldown", 30))
        except (ValueError, TypeError):
            value = 30
        return max(0, min(3600, value))

    @property
    def probability(self) -> float:
        try:
            value = float(self._flat.get("probability", 0.8))
        except (ValueError, TypeError):
            value = 0.8
        return max(0.0, min(1.0, value))

    @property
    def default_speed(self) -> float:
        try:
            value = float(self._flat.get("default_speed", 1.0))
        except (ValueError, TypeError):
            value = 1.0
        return max(0.5, min(2.0, value))

    @property
    def send_text_with_tts(self) -> bool:
        return bool(self._flat.get("send_text_with_tts", True))

    @property
    def send_text_async(self) -> bool:
        return bool(self._flat.get("send_text_async", False))

    @property
    def default_pitch(self) -> int:
        try:
            value = int(self._flat.get("default_pitch", 0))
        except (ValueError, TypeError):
            value = 0
        return max(-12, min(12, value))

    @property
    def emotion_override(self) -> str:
        return str(self._flat.get("emotion_override", ""))

    @property
    def style_hint(self) -> str:
        return str(self._flat.get("style_hint", ""))

    @property
    def breath_enabled(self) -> bool:
        return bool(self._flat.get("breath_enabled", False))

    @property
    def stress_enabled(self) -> bool:
        return bool(self._flat.get("stress_enabled", False))

    @property
    def laughter_enabled(self) -> bool:
        return bool(self._flat.get("laughter_enabled", False))

    @property
    def pause_enabled(self) -> bool:
        return bool(self._flat.get("pause_enabled", False))

    @property
    def clone_enabled(self) -> bool:
        return bool(self._flat.get("clone_enabled", True))

    @property
    def clone_model(self) -> str:
        return str(self._flat.get("clone_model", "mimo-v2.5-tts-voiceclone"))

    @property
    def clone_voice_id(self) -> str:
        return str(self._flat.get("clone_voice_id", ""))

    @property
    def clone_style_prompt(self) -> str:
        return str(self._flat.get("clone_style_prompt", ""))

    @property
    def clone_audio_tags(self) -> str:
        return str(self._flat.get("clone_audio_tags", ""))

    @property
    def clone_style_pool(self) -> list[dict]:
        """克隆音色风格控制池（v2.2.8）：list[{name, style, audio_tags}]。

        name = 克隆音色 voice_id；作为 per-voice 风格/标签的配置权威数据源，
        与合成链路联动（resolve_clone_style_prompt / resolve_clone_audio_tags）。
        """
        return normalize_clone_style_pool(self._flat.get("clone_style_pool", "[]"))

    def get_clone_pool_entry(self, voice_id: str) -> Optional[dict]:
        """按克隆音色 voice_id 查风格控制池条目（未配置返回 None）。"""
        return find_clone_pool_entry(self.clone_style_pool, voice_id)

    def upsert_clone_pool_entry(
        self, voice_id: str, style: str = "", audio_tags: str = ""
    ) -> None:
        """新增或更新克隆音色风格控制池条目（写回配置，与面板联动）。

        条目存在则更新 style/audio_tags；不存在则追加。空值同样落库
        （= 显式清空该音色 per-voice，回退全局）。
        """
        voice_id = str(voice_id or "").strip()
        if not voice_id:
            return
        pool = self.clone_style_pool
        entry = find_clone_pool_entry(pool, voice_id)
        if entry is None:
            pool.append({
                "name": voice_id,
                "style": str(style or "").strip(),
                "audio_tags": str(audio_tags or "").strip(),
            })
        else:
            entry["style"] = str(style or "").strip()
            entry["audio_tags"] = str(audio_tags or "").strip()
        self.set(
            "clone_style_pool",
            json.dumps(pool, ensure_ascii=False, indent=2),
        )

    def remove_clone_pool_entry(self, voice_id: str) -> None:
        """删除克隆音色风格控制池条目（删除音色时联动清理）。"""
        voice_id = str(voice_id or "").strip()
        if not voice_id:
            return
        pool = self.clone_style_pool
        kept = [e for e in pool if e.get("name") != voice_id]
        if len(kept) != len(pool):
            self.set(
                "clone_style_pool",
                json.dumps(kept, ensure_ascii=False, indent=2),
            )

    @property
    def design_style_pool(self) -> list[dict]:
        """设计音色风格控制池（v2.2.9）：list[{name, description}]。

        name = 设计音色 voice_id；作为 design 音色描述的配置权威数据源，
        与合成链路联动（resolve_design_description）。描述可填
        style_examples 分类名（方案 A 精确引用），供导演模式素材复用。
        """
        return normalize_design_style_pool(
            self._flat.get("design_style_pool", "[]")
        )

    def get_design_pool_entry(self, voice_id: str) -> Optional[dict]:
        """按设计音色 voice_id 查风格控制池条目（未配置返回 None）。"""
        return find_design_pool_entry(self.design_style_pool, voice_id)

    def upsert_design_pool_entry(
        self, voice_id: str, description: str = ""
    ) -> None:
        """新增或更新设计音色风格控制池条目（写回配置，与面板联动）。

        条目存在则更新 description；不存在则追加。空值同样落库
        （= 显式清空该音色描述，回退全局 design_voice_description）。
        """
        voice_id = str(voice_id or "").strip()
        if not voice_id:
            return
        pool = self.design_style_pool
        entry = find_design_pool_entry(pool, voice_id)
        if entry is None:
            pool.append({
                "name": voice_id,
                "description": str(description or "").strip(),
            })
        else:
            entry["description"] = str(description or "").strip()
        self.set(
            "design_style_pool",
            json.dumps(pool, ensure_ascii=False, indent=2),
        )

    def remove_design_pool_entry(self, voice_id: str) -> None:
        """删除设计音色风格控制池条目（删除音色时联动清理）。"""
        voice_id = str(voice_id or "").strip()
        if not voice_id:
            return
        pool = self.design_style_pool
        kept = [e for e in pool if e.get("name") != voice_id]
        if len(kept) != len(pool):
            self.set(
                "design_style_pool",
                json.dumps(kept, ensure_ascii=False, indent=2),
            )

    @property
    def design_enabled(self) -> bool:
        return bool(self._flat.get("design_enabled", True))

    @property
    def design_model(self) -> str:
        return str(self._flat.get("design_model", "mimo-v2.5-tts-voicedesign"))

    @property
    def tts_output_mode(self) -> str:
        return str(self._flat.get("tts_output_mode", "default"))

    @property
    def tts_example_inject(self) -> bool:
        """普通 TTS 风格示例注入开关（§14.9 P2，默认关）。"""
        return bool(self._flat.get("tts_example_inject", False))

    @property
    def design_voice_description(self) -> str:
        return str(self._flat.get("design_voice_description", ""))

    @property
    def style_examples(self) -> list[dict]:
        """风格示例池（§14 导演模式先导）：list[{name, words, examples}]。"""
        return normalize_style_examples(
            self._flat.get("style_examples", STYLE_EXAMPLES_PRESET)
        )

    @property
    def design_voice_id(self) -> str:
        return self._design_voice_id

    @design_voice_id.setter
    def design_voice_id(self, value: str) -> None:
        self._design_voice_id = str(value or "").strip()

    @property
    def voice_presets(self) -> dict[str, str]:
        """Return all preset_ keys as a {name: description} dict."""
        return {
            "gentle_female": str(self._flat.get("preset_gentle_female", "")),
            "serious_male": str(self._flat.get("preset_serious_male", "")),
            "cute_girl": str(self._flat.get("preset_cute_girl", "")),
            "storyteller": str(self._flat.get("preset_storyteller", "")),
            "news_anchor": str(self._flat.get("preset_news_anchor", "")),
        }

    @property
    def audio_format(self) -> str:
        return str(self._flat.get("audio_format", "wav"))

    @property
    def timeout(self) -> int:
        try:
            value = int(self._flat.get("timeout", 60))
        except (ValueError, TypeError):
            value = 60
        return max(1, value)

    @property
    def max_retries(self) -> int:
        try:
            value = int(self._flat.get("max_retries", 2))
        except (ValueError, TypeError):
            value = 2
        return max(0, value)

    @property
    def enable_plugin_log(self) -> bool:
        return bool(self._flat.get("enable_plugin_log", False))

    # ── Segmentation ──

    @property
    def enable_segmentation(self) -> bool:
        return bool(self._flat.get("enable_segmentation", False))

    @property
    def segment_pattern(self) -> str:
        return str(self._flat.get("segment_pattern", "sentence") or "sentence")

    @property
    def segment_max_count(self) -> int:
        try:
            value = int(self._flat.get("segment_max_count", 10))
        except (ValueError, TypeError):
            value = 10
        return max(0, value)

    @property
    def segment_voice_probability(self) -> float:
        try:
            value = float(self._flat.get("segment_voice_probability", 1.0))
        except (ValueError, TypeError):
            value = 1.0
        return max(0.0, min(1.0, value))

    @property
    def segment_text_fallback(self) -> bool:
        """无语音段（掷骰未命中/合成失败）是否用纯文本兜底，防内容丢失。"""
        return bool(self._flat.get("segment_text_fallback", True))

    # ── Voice polish (LLM) ──

    @property
    def enable_voice_polish(self) -> bool:
        return bool(self._flat.get("enable_voice_polish", False))

    @property
    def display_polished_text(self) -> bool:
        """展示文字使用润色后文本，与语音内容一致（兜底小模型改写原文）。"""
        return bool(self._flat.get("display_polished_text", False))

    @property
    def polish_llm_provider(self) -> str:
        return str(self._flat.get("polish_llm_provider", "") or "")

    @property
    def polish_prompt(self) -> str:
        return str(self._flat.get("polish_prompt", "") or "")

    @property
    def optimize_text_preview(self) -> bool:
        """官方 voicedesign 智能润色参数（与服务端，与插件 LLM 润色建议二选一）。"""
        return bool(self._flat.get("optimize_text_preview", False))

    # ── Model hyperparameters ──

    @property
    def temperature(self) -> float:
        """采样温度。较高值使输出更随机，较低值使输出更确定。TTS 默认 0.6。"""
        try:
            value = float(self._flat.get("temperature", 0.6))
        except (ValueError, TypeError):
            value = 0.6
        return max(0.0, min(1.5, value))

    @property
    def top_p(self) -> float:
        """核采样概率阈值。值越高生成多样性越高。默认 0.95。"""
        try:
            value = float(self._flat.get("top_p", 0.95))
        except (ValueError, TypeError):
            value = 0.95
        return max(0.01, min(1.0, value))
