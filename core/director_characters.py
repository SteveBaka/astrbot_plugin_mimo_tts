# -*- coding: utf-8 -*-
"""导演角色库（P5-M1）：plugin_data 文件权威存储 + 内存索引。

资产落在 ``data/plugin_data/<plugin>/director/characters.json``，
user_state 只存 ``character_id`` 引用，避免会话状态膨胀。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger

from .director_assets import list_builtin_scene_names
from .director_package import ScenePackage, sanitize_package

CHARACTER_FILE_VERSION = 1
_CHAR_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_STRUCTURED_HINT = ("角色：", "场景：", "指导：", "Role:", "Scene:", "Guidance:")

# 首次创建时写入的示例角色（可删）
_SAMPLE_CHARACTERS: list[dict] = [
    {
        "id": "xiaoyin",
        "name": "小茵",
        "character": "二十岁出头的邻家学姐，说话轻、尾音软，偶尔带一点鼻音。",
        "baseline_guidance": "整体偏温柔、语速稍慢；句尾自然收，不夸张。",
        "scene": "",
        "voice": "茉莉",
        "style_words": ["温柔"],
        "enabled": True,
        "note": "示例角色，可删",
    },
]


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
    """角色库：加载 / 校验 / 精确匹配 / 原子写。"""

    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._path = self._data_dir / "director" / "characters.json"
        self._entries: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> int:
        """读文件建索引；不存在则写入示例角色。返回条目数。"""
        try:
            if not self._path.exists():
                self._write_raw({"version": CHARACTER_FILE_VERSION, "characters": list(_SAMPLE_CHARACTERS)})
                logger.info(
                    "MiMO TTS: character store created with samples path=%s",
                    self._path,
                )
            raw_text = self._path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as e:
            logger.warning("MiMO TTS: failed to load character store %s: %s", self._path, e)
            self._entries = []
            self._by_id = {}
            self._by_name = {}
            return 0

        items = data.get("characters") if isinstance(data, dict) else None
        if not isinstance(items, list):
            items = []
        self._rebuild(items)
        logger.info(
            "MiMO TTS: characters loaded n=%d path=%s",
            len(self._entries),
            self._path,
        )
        return len(self._entries)

    def reload(self) -> int:
        return self.load()

    def _rebuild(self, items: list) -> None:
        entries: list[dict] = []
        by_id: dict[str, dict] = {}
        by_name: dict[str, dict] = {}
        scene_names = set(list_builtin_scene_names())
        for item in items:
            entry = sanitize_character(item)
            if not entry:
                continue
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

    def _write_raw(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=".characters.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def save_all(self) -> None:
        self._write_raw(
            {
                "version": CHARACTER_FILE_VERSION,
                "characters": self._entries,
            }
        )

    def list_enabled(self) -> list[dict]:
        return [e for e in self._entries if e.get("enabled", True)]

    def list_all(self) -> list[dict]:
        return list(self._entries)

    def get(self, name_or_id: str) -> Optional[dict]:
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
