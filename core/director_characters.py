# -*- coding: utf-8 -*-
"""导演角色库（P5-M1）：配置 JSON 权威（与风格示例池同构）+ 文件兜底。

权威数据源 = 配置 ``director_characters``（Dashboard JSON 编辑器，保存即生效）。
plugin_data ``director/characters.json`` 仅作兼容/迁移兜底；user_state 只存 id 引用。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger

from .director_assets import list_builtin_scene_names
from .director_package import ScenePackage, sanitize_package

_CHAR_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_STRUCTURED_HINT = ("角色：", "场景：", "指导：", "Role:", "Scene:", "Guidance:")

# 配置面板默认示例（与 schema default 同步；可删）
SAMPLE_CHARACTERS_JSON = """[
  {
    "id": "xiaoyin",
    "name": "小茵",
    "character": "二十岁出头的邻家学姐，说话轻、尾音软，偶尔带一点鼻音。",
    "baseline_guidance": "整体偏温柔、语速稍慢；句尾自然收，不夸张。",
    "scene": "",
    "voice": "茉莉",
    "style_words": ["温柔"],
    "enabled": true,
    "note": "示例角色，可删"
  }
]"""


def looks_like_character_name(text: str) -> bool:
    """短名且无三维标签时才查角色库，避免整段散文被当名字。"""
    raw = str(text or "").strip().lstrip("@").strip()
    if not raw or len(raw) > 20:
        return False
    if any(h in raw for h in _STRUCTURED_HINT):
        return False
    if "\n" in raw:
        return False
    return True


def _clean_text(value: Any, limit: int) -> str:
    from .director_package import _strip_forbidden

    return _strip_forbidden(str(value or ""))[:limit]


def sanitize_character(data: Any) -> Optional[dict]:
    """清洗一条角色记录；非法返回 None。"""
    if not isinstance(data, dict):
        return None
    cid = str(data.get("id") or "").strip().lower()
    name = str(data.get("name") or "").strip()[:16]
    character = _clean_text(data.get("character"), 200)
    if not cid or not _CHAR_ID_RE.match(cid):
        return None
    if not name or not character:
        return None

    guidance = _clean_text(data.get("baseline_guidance"), 400)
    scene = _clean_text(data.get("scene"), 200)
    voice = str(data.get("voice") or "").strip()[:64]
    words_raw = data.get("style_words") or []
    if isinstance(words_raw, str):
        words = [w.strip() for w in re.split(r"[\s,，、/]+", words_raw) if w.strip()]
    elif isinstance(words_raw, (list, tuple)):
        words = [str(w).strip() for w in words_raw if str(w or "").strip()]
    else:
        words = []
    return {
        "id": cid,
        "name": name,
        "character": character,
        "baseline_guidance": guidance,
        "scene": scene,
        "voice": voice,
        "style_words": words[:8],
        "enabled": bool(data.get("enabled", True)),
        "note": str(data.get("note") or "").strip()[:80],
    }


def parse_characters_payload(raw: Any) -> list[dict]:
    """解析配置 JSON / 列表 / 文件 characters 字段 → 清洗后的条目列表。"""
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        # 兼容文件包装 {"characters": [...]}
        items = raw.get("characters")
        if not isinstance(items, list):
            items = [raw]
    elif isinstance(raw, str):
        text = str(raw or "").strip()
        if not text:
            return []
        from .config import _loads_lenient

        parsed = _loads_lenient(text)
        if parsed is None:
            try:
                parsed = json.loads(text)
            except Exception:
                return []
        if isinstance(parsed, dict):
            items = parsed.get("characters")
            if not isinstance(items, list):
                items = [parsed]
        elif isinstance(parsed, list):
            items = parsed
        else:
            return []
    else:
        return []

    entries: list[dict] = []
    for item in items:
        entry = sanitize_character(item)
        if entry:
            entries.append(entry)
    return entries


def character_to_package(entry: dict) -> Optional[ScenePackage]:
    """角色条目 → ScenePackage（带 character_id，guidance 可空）。"""
    if not entry:
        return None
    return sanitize_package(
        {
            "scene_name": str(entry.get("name") or ""),
            "character_id": str(entry.get("id") or ""),
            "character": entry.get("character") or "",
            "scene": entry.get("scene") or "",
            "guidance": entry.get("baseline_guidance") or "",
            "style_words": entry.get("style_words") or [],
            "guidance_source": "builtin",
        }
    )


class CharacterStore:
    """角色库：配置 JSON 权威；保存配置即刷新，无需 /char reload。"""

    def __init__(self, config=None, data_dir: Path | None = None):
        self._config = config
        self._data_dir = Path(data_dir) if data_dir else None
        self._path = (
            (self._data_dir / "director" / "characters.json")
            if self._data_dir
            else None
        )
        self._entries: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._source = ""
        self._fingerprint: Optional[int] = None

    @property
    def source(self) -> str:
        return self._source or "empty"

    def load(self) -> int:
        """从配置读取；配置为空且存在旧文件时迁移兜底。返回条目数。"""
        items: list[dict] = []
        source = "config"
        raw_cfg = None
        if self._config is not None:
            try:
                raw_cfg = self._config.get("director_characters")
            except Exception:
                raw_cfg = None
            items = parse_characters_payload(raw_cfg)
            if not items and raw_cfg not in (None, "", "[]"):
                # 配置有内容但全非法 → 不静默回退文件，避免改坏后“幽灵角色”
                source = "config-invalid"
        if not items and source == "config" and self._path and self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                items = parse_characters_payload(data)
                if items:
                    source = "file"
                    logger.info(
                        "MiMO TTS: characters migrated from file n=%d "
                        "(建议保存到配置「角色库」后以配置为准)",
                        len(items),
                    )
            except Exception as e:
                logger.warning(
                    "MiMO TTS: failed to read character file %s: %s", self._path, e
                )

        self._rebuild(items)
        self._source = source
        self._fingerprint = self._config_fingerprint()
        logger.info(
            "MiMO TTS: characters loaded n=%d source=%s",
            len(self._entries),
            source,
        )
        return len(self._entries)

    def _config_fingerprint(self) -> Optional[int]:
        if self._config is None:
            return None
        try:
            raw = self._config.get("director_characters")
        except Exception:
            return None
        return hash(str(raw or ""))

    def refresh_if_changed(self) -> None:
        """配置保存后下次查询自动生效（等同原 /char reload）。"""
        fp = self._config_fingerprint()
        if fp != self._fingerprint:
            self.load()

    def _rebuild(self, items: list[dict]) -> None:
        entries: list[dict] = []
        by_id: dict[str, dict] = {}
        by_name: dict[str, dict] = {}
        scene_names = set(list_builtin_scene_names())
        for entry in items:
            if entry["id"] in by_id or entry["name"] in by_name:
                logger.warning(
                    "MiMO TTS: skip duplicate character id=%s name=%s",
                    entry["id"],
                    entry["name"],
                )
                continue
            if entry["name"] in scene_names:
                logger.warning(
                    "MiMO TTS: character name conflicts builtin scene: %s",
                    entry["name"],
                )
            entries.append(entry)
            by_id[entry["id"]] = entry
            by_name[entry["name"]] = entry
        self._entries = entries
        self._by_id = by_id
        self._by_name = by_name

    def list_enabled(self) -> list[dict]:
        self.refresh_if_changed()
        return [e for e in self._entries if e.get("enabled", True)]

    def list_all(self) -> list[dict]:
        self.refresh_if_changed()
        return list(self._entries)

    def get(self, name_or_id: str) -> Optional[dict]:
        self.refresh_if_changed()
        key = str(name_or_id or "").strip().lstrip("@").strip()
        if not key:
            return None
        low = key.lower()
        if low in self._by_id:
            return self._by_id[low]
        if key in self._by_name:
            return self._by_name[key]
        return None

    def match_name(self, text: str) -> Optional[dict]:
        """短名精确匹配（name 或 id）；不启用/过长返回 None。"""
        if not looks_like_character_name(text):
            return None
        entry = self.get(text)
        if not entry or not entry.get("enabled", True):
            return None
        return entry

    def summary_line(self, entry: dict) -> str:
        voice = entry.get("voice") or "—"
        return f"{entry.get('name')}（{entry.get('id')}，音色 {voice}）"
