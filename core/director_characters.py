# -*- coding: utf-8 -*-
"""导演角色库（P5-M1）：配置 JSON 权威（与风格示例池同构）+ 文件兜底。

权威数据源 = 配置 ``director_characters``（Dashboard JSON 编辑器，保存即生效）。
plugin_data ``director/characters.json`` 仅作兼容/迁移兜底；user_state 只存 id 引用。
"""

from __future__ import annotations

import json
import re
import time
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
    enabled = bool(data.get("enabled", True))
    tts_mode = str(data.get("tts_mode") or "").strip().lower()
    if tts_mode not in ("", "default", "clone", "design"):
        tts_mode = ""
    return {
        "id": cid,
        "name": name,
        "character": character,
        "baseline_guidance": guidance,
        "scene": scene,
        "voice": voice,
        "style_words": words[:8],
        "enabled": enabled,
        "tts_mode": tts_mode,
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
    """角色条目 → ScenePackage（带 character_id；source=character 便于日志对账）。"""
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
            "guidance_source": "character",
        }
    )


_CHAR_FIELD_KEYS = (
    "id",
    "name",
    "voice",
    "character",
    "guidance",
    "baseline_guidance",
    "scene",
    "enabled",
)


def parse_char_fields(text: str) -> dict:
    """解析 /char add|set 的 key=value（值可含空格，以下一个 key= 为界）。"""
    fields: dict = {}
    raw = str(text or "").strip()
    if not raw:
        return fields
    pattern = re.compile(
        r"(" + "|".join(_CHAR_FIELD_KEYS) + r")\s*=\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(raw))
    if not matches:
        return fields
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        value = raw[start:end].strip().strip('"').strip("「」")
        if key == "baseline_guidance":
            key = "guidance"
        if key == "enabled":
            fields[key] = value.lower() not in ("false", "0", "off", "no")
        else:
            fields[key] = value
    return fields


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

    def persist_entries(self) -> bool:
        """把内存条目写回配置 director_characters（2 空格缩进）。"""
        if self._config is None:
            return False
        try:
            payload = json.dumps(self._entries, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return False
        try:
            self._config.set("director_characters", payload)
        except Exception:
            logger.exception("MiMO TTS: failed to persist director_characters")
            return False
        self._fingerprint = self._config_fingerprint()
        return True

    def upsert_entry(self, data: dict) -> tuple[Optional[dict], str]:
        """新增或按 id 更新角色；返回 (entry, err)。"""
        payload = dict(data or {})
        if payload.get("guidance") and not payload.get("baseline_guidance"):
            payload["baseline_guidance"] = payload["guidance"]
        entry = sanitize_character(payload)
        if not entry:
            return None, "条目不合法：需 id/name/character，且 id 为小写字母数字_-"
        self.refresh_if_changed()
        existing = self.get(entry["id"])
        name_hit = self.get(entry["name"])
        if name_hit and name_hit.get("id") != entry["id"]:
            return None, f"名称已被占用: {entry['name']}"
        if existing:
            self._entries = [
                entry if e["id"] == entry["id"] else e for e in self._entries
            ]
            mode = "updated"
        else:
            self._entries.append(entry)
            mode = "added"
        self._rebuild(self._entries)
        if not self.persist_entries():
            return None, "写入配置失败"
        return entry, mode

    def delete_entry(self, name_or_id: str) -> tuple[Optional[dict], str]:
        """删除角色；返回 (entry, err)。"""
        self.refresh_if_changed()
        entry = self.get(name_or_id)
        if not entry:
            return None, f"未找到角色: {name_or_id}"
        self._entries = [e for e in self._entries if e["id"] != entry["id"]]
        self._rebuild(self._entries)
        if not self.persist_entries():
            return None, "写入配置失败"
        return entry, "deleted"

    def update_fields(
        self, name_or_id: str, fields: dict
    ) -> tuple[Optional[dict], str]:
        """按字段更新角色；返回 (entry, err)。"""
        self.refresh_if_changed()
        entry = self.get(name_or_id)
        if not entry:
            return None, f"未找到角色: {name_or_id}"
        merged = {**entry, **(fields or {})}
        if merged.get("guidance") and "guidance" in (fields or {}):
            merged["baseline_guidance"] = merged["guidance"]
        merged["id"] = entry["id"]  # 禁止通过 set 改 id
        updated = sanitize_character(merged)
        if not updated:
            return None, "更新后不合法：需保留 name/character"
        name_hit = self.get(updated["name"])
        if name_hit and name_hit.get("id") != updated["id"]:
            return None, f"名称已被占用: {updated['name']}"
        self._entries = [
            updated if e["id"] == updated["id"] else e for e in self._entries
        ]
        self._rebuild(self._entries)
        if not self.persist_entries():
            return None, "写入配置失败"
        return updated, "updated"

    def list_api_items(self) -> list[dict]:
        """控制台下拉用摘要（含 id/name/voice/tts_mode）。"""
        self.refresh_if_changed()
        return [
            {
                "id": e.get("id", ""),
                "name": e.get("name", ""),
                "voice": e.get("voice", ""),
                "tts_mode": e.get("tts_mode", ""),
                "summary": self.summary_line(e),
            }
            for e in self._entries
            if e.get("enabled", True)
        ]


def apply_character_binding(plugin, uset: dict, entry: dict) -> str:
    """按策略绑定角色音色/输出模式；会先写 director_snapshot 以便 /direct off 恢复。

    voice_policy: keep=仅默认音色时切换；force=总是切换
    mode_policy:  keep=不改 tts_mode；bind=角色带 tts_mode（default/clone）时切换
    返回拼接提示（可空）；不进入 format_director_applied 主文案。
    """
    notes: list[str] = []
    voice = str(entry.get("voice") or "").strip()
    mode_want = str(entry.get("tts_mode") or "").strip().lower()

    default_voice = str(
        plugin.config.get("default_voice", "") or "mimo_default"
    ).strip()
    current_voice = str(uset.get("voice") or "").strip()
    current_mode = str(uset.get("tts_mode") or "default").strip().lower()

    voice_policy = getattr(plugin.config, "character_voice_policy", "keep")
    mode_policy = getattr(plugin.config, "character_mode_policy", "keep")

    will_voice = False
    resolved_voice = current_voice
    if voice:
        if voice_policy == "force":
            will_voice = True
        elif current_voice in ("", default_voice, "mimo_default"):
            will_voice = True
        if will_voice:
            try:
                resolved_voice = (
                    plugin.synth.resolve_voice(voice) if plugin.synth else voice
                )
            except Exception:
                resolved_voice = voice
            will_voice = bool(resolved_voice) and resolved_voice != current_voice

    will_mode = False
    target_mode = current_mode
    if mode_policy == "bind" and mode_want in ("default", "clone"):
        # design 不绑定：设计通道不注入导演稿（§16.2）
        target_mode = mode_want
        will_mode = target_mode != current_mode

    if will_voice or will_mode:
        _ensure_director_snapshot(uset, current_voice, current_mode)
    if will_voice:
        uset["voice"] = resolved_voice
    if will_mode:
        uset["tts_mode"] = target_mode
        notes.append(f"输出模式 → {target_mode}")
    return "；".join(notes)


def _ensure_director_snapshot(uset: dict, voice: str, tts_mode: str) -> None:
    """仅在尚无快照时记录进入导演前的状态（不覆盖）。"""
    if uset.get("director_snapshot"):
        return
    uset["director_snapshot"] = {
        "voice": voice or "",
        "tts_mode": tts_mode or "default",
        "saved_at": int(time.time()),
    }


def restore_director_snapshot(uset: dict, *, clear_layers: bool = True) -> dict:
    """恢复快照中的 voice/tts_mode；默认同时清除快照与双层。

    ``clear_layers=False`` 时只恢复音色/模式并清空快照，保留 sticky/pending
    （供分层清除：仅当双层都清空后才恢复）。
    返回 ``{"restored": bool, "voice": str, "tts_mode": str}``。
    """
    snap = uset.get("director_snapshot") or {}
    if clear_layers:
        uset["director_sticky"] = ""
        uset["director_pending"] = ""
        uset["director_mode"] = ""
        uset["director_payload"] = ""
    if not isinstance(snap, dict) or not snap:
        uset["director_snapshot"] = None
        return {"restored": False, "voice": "", "tts_mode": ""}
    voice = str(snap.get("voice") or "")
    tts_mode = str(snap.get("tts_mode") or "default") or "default"
    if voice:
        uset["voice"] = voice
    uset["tts_mode"] = tts_mode
    uset["director_snapshot"] = None
    return {"restored": True, "voice": voice, "tts_mode": tts_mode}


def clear_director_layer(uset: dict, layer: str) -> dict:
    """按层清除导演状态；layer=all|sticky|pending。

    仅当清除后双层皆空时才恢复快照（避免还有层在用时提前回退音色）。
    返回 ``{"cleared": list[str], "restored": bool, "voice": str, "tts_mode": str}``。
    """
    layer = str(layer or "all").strip().lower()
    if layer not in ("all", "sticky", "pending"):
        layer = "all"
    cleared: list[str] = []
    if layer in ("all", "sticky"):
        uset["director_sticky"] = ""
        uset["director_mode"] = ""
        uset["director_payload"] = ""
        cleared.append("sticky")
    if layer in ("all", "pending"):
        uset["director_pending"] = ""
        cleared.append("pending")

    has_remaining = bool(
        str(uset.get("director_sticky") or "").strip()
        or str(uset.get("director_pending") or "").strip()
    )
    restored = {"restored": False, "voice": "", "tts_mode": ""}
    if not has_remaining:
        restored = restore_director_snapshot(uset, clear_layers=False)
    return {
        "cleared": cleared,
        "restored": restored.get("restored", False),
        "voice": restored.get("voice", ""),
        "tts_mode": restored.get("tts_mode", ""),
    }


# 兼容旧调用点：仅音色（无快照）。新代码用 apply_character_binding。
def apply_character_voice(plugin, uset: dict, entry: dict) -> str:
    """会话音色仍为默认时绑定角色音色；已自定义则不覆盖。返回提示文案。"""
    voice = str(entry.get("voice") or "").strip()
    if not voice:
        return ""
    current = str(uset.get("voice") or "").strip()
    default = str(plugin.config.get("default_voice", "") or "mimo_default").strip()
    if current and current != default and current != "mimo_default":
        return f"保留当前音色 {current}；角色默认为 {voice}"
    try:
        resolved = plugin.synth.resolve_voice(voice) if plugin.synth else voice
    except Exception:
        resolved = voice
    if resolved:
        uset["voice"] = resolved
        return f"已切换音色 → {resolved}"
    return ""


def voice_type_label(plugin, voice_id: str) -> str:
    """音色类型短标签：预置 / 已注册克隆 / 已注册设计 / 自定义。"""
    from .constants import MIMO_VOICE_LIST

    vid = str(voice_id or "").strip()
    if not vid:
        return ""
    info = None
    try:
        synth = getattr(plugin, "synth", None)
        vm = getattr(synth, "_voice_manager", None) if synth else None
        if vm:
            info = vm.get_voice(vid)
    except Exception:
        info = None
    if info:
        model = str(info.get("model", "") or "").lower()
        if model == "voiceclone":
            return "已注册克隆"
        if model == "voicedesign":
            return "已注册设计"
        return "自定义"
    if any(v.get("id") == vid for v in MIMO_VOICE_LIST):
        return "预置"
    return ""


def format_director_applied(
    plugin,
    pkg,
    mode: str,
    voice_id: str = "",
    voice_note: str = "",
) -> str:
    """命令与 WebUI 共用的「已应用」文案（§18 模板）。

    第一行：层 + 名称 / 音色（类型） / 角色 / 场景 / 指导
    第二行：另一层说明 + /direct off
    ``voice_note`` 保留参数兼容调用方，当前不再拼进正文（信息已在音色行）。
    """
    session = str(mode or "session").lower() != "once"
    layer = "会话常驻配置" if session else "一次性配置"
    other = "不影响已设置的一次性场景" if session else "优先于会话常驻，用尽后回落"
    name = (pkg.scene_name if pkg else "").strip() or "（自定义）"

    parts = [f"已设置本{layer}：{name}"]

    vid = str(voice_id or "").strip()
    if vid:
        vtype = voice_type_label(plugin, vid)
        voice_part = f"音色：{vid}"
        if vtype:
            voice_part += f"（{vtype}）"
        parts.append(voice_part)

    character = (pkg.character if pkg else "").strip()
    if character:
        parts.append(f"角色：{character}")

    scene = (pkg.scene if pkg else "").strip()
    if scene:
        parts.append(f"场景：{scene}")

    guidance = (pkg.guidance if pkg else "").strip()
    if guidance:
        parts.append(f"指导：{guidance}")

    line1 = " / ".join(parts)
    line2 = f"{other}；关闭和清除导演模式: /direct off"
    return f"{line1}\n{line2}"
