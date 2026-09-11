# -*- coding: utf-8 -*-
"""User state management for MiMO TTS plugin.

Handles per-user settings persistence, LRU eviction, and format overrides.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .constants import SUPPORTED_AUDIO_FORMATS


def sanitize_user_settings(data: dict) -> dict:
    """Sanitize and fill defaults for user settings."""
    defaults = {
        "emotion": "",
        "speed": 1.0,
        "pitch": 0,
        "voice": "mimo_default",
        "breath": False,
        "stress": False,
        "sing": False,
        "laughter": False,
        "pause": False,
        "style_hint": "",
        "sing_style": "",
        "dialect": "",
        "volume": "",
        "tts_mode": "default",
        "tts_enabled": True,
        "text_enabled": None,
        "text_async": None,
        # None = 跟随插件全局配置；True/False = WebUI 会话级显式覆盖
        "enable_segmentation": None,
        "enable_voice_polish": None,
        # 导演模式："" / "once" / "session"；payload 为 ScenePackage JSON
        "director_mode": "",
        "director_payload": "",
    }
    cleaned = dict(defaults)
    if isinstance(data, dict):
        cleaned.update({k: v for k, v in data.items() if k in defaults})
    cleaned["speed"] = max(0.5, min(2.0, float(cleaned.get("speed", 1.0) or 1.0)))
    cleaned["pitch"] = max(-12, min(12, int(cleaned.get("pitch", 0) or 0)))
    cleaned["breath"] = bool(cleaned.get("breath", False))
    cleaned["stress"] = bool(cleaned.get("stress", False))
    cleaned["sing"] = False
    cleaned["laughter"] = bool(cleaned.get("laughter", False))
    cleaned["pause"] = bool(cleaned.get("pause", False))
    cleaned["dialect"] = str(cleaned.get("dialect", "") or "")
    cleaned["volume"] = str(cleaned.get("volume", "") or "")
    cleaned["voice"] = str(cleaned.get("voice", "mimo_default") or "mimo_default")
    cleaned["emotion"] = str(cleaned.get("emotion", "") or "")
    cleaned["style_hint"] = str(cleaned.get("style_hint", "") or "")
    # 唱歌风格组："" = 继承全局（与其他会话字段惯例同构）
    cleaned["sing_style"] = str(cleaned.get("sing_style", "") or "")[:20]
    cleaned["tts_mode"] = str(cleaned.get("tts_mode", "default") or "default")
    cleaned["tts_enabled"] = bool(cleaned.get("tts_enabled", True))
    text_enabled = cleaned.get("text_enabled", None)
    cleaned["text_enabled"] = None if text_enabled is None else bool(text_enabled)
    text_async = cleaned.get("text_async", None)
    cleaned["text_async"] = None if text_async is None else bool(text_async)
    # 三态开关（None=跟随全局）：归一化防止 WebUI 传入非布尔值
    for key in ("enable_segmentation", "enable_voice_polish"):
        value = cleaned.get(key, None)
        cleaned[key] = None if value is None else bool(value)
    director_mode = str(cleaned.get("director_mode", "") or "").strip().lower()
    cleaned["director_mode"] = (
        director_mode if director_mode in ("once", "session") else ""
    )
    cleaned["director_payload"] = str(cleaned.get("director_payload", "") or "")[:2000]
    return cleaned


def safe_event_value(event, *names: str) -> str:
    """Best-effort read event identifiers across AstrBot versions."""
    for name in names:
        try:
            attr = getattr(event, name, None)
            value = attr() if callable(attr) else attr
            text = str(value or "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def get_user_scope_key(event) -> str:
    """Resolve a stable settings key shared by commands and auto-TTS callbacks."""
    session_id = safe_event_value(event, "get_session_id", "session_id")
    if session_id:
        return f"session:{session_id}"

    conversation_id = safe_event_value(event, "get_conversation_id", "conversation_id")
    if conversation_id:
        return f"conversation:{conversation_id}"

    group_id = safe_event_value(event, "get_group_id", "group_id")
    sender_id = safe_event_value(event, "get_sender_id", "sender_id")
    if group_id and sender_id:
        return f"group:{group_id}:user:{sender_id}"
    if sender_id:
        return f"user:{sender_id}"
    return "user:default"


class UserStateManager:
    """Manages per-user TTS settings with persistence and LRU eviction."""

    _MAX_IDLE_USERS = 500
    _CLEANUP_MAX_TOTAL_BYTES = 100 * 1024 * 1024
    # temp 目录孤儿文件的最小存活期：合成通常数秒完成，
    # 插件热重载瞬间旧实例可能仍在写盘，保留 1 小时缓冲避免误删在途文件
    _TEMP_ORPHAN_MIN_AGE_SECONDS = 3600

    def __init__(self, data_dir: Path, config):
        self._data_dir = data_dir
        self._state_file = data_dir / "user_state.json"
        self._config = config
        self._user_settings: dict[str, dict] = {}
        self._user_format: dict[str, str] = {}
        self._user_umo: dict[str, str] = {}
        self._recent_files: list[tuple[float, Path]] = []
        self._nl_sing_last: dict[str, float] = {}
        self._persist_lock = threading.Lock()

    @property
    def user_settings(self) -> dict[str, dict]:
        return self._user_settings

    @property
    def user_umo(self) -> dict[str, str]:
        return self._user_umo

    @property
    def user_format(self) -> dict[str, str]:
        return self._user_format

    @property
    def recent_files(self) -> list[tuple[float, Path]]:
        return self._recent_files

    @property
    def nl_sing_last(self) -> dict[str, float]:
        """自然语言唱歌的会话级冷却时间戳（内存态，随淘汰策略清理）。"""
        return self._nl_sing_last

    def load(self) -> None:
        """Load user state from disk."""
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
            user_settings = (
                payload.get("user_settings", {}) if isinstance(payload, dict) else {}
            )
            user_format = (
                payload.get("user_format", {}) if isinstance(payload, dict) else {}
            )

            if isinstance(user_settings, dict):
                self._user_settings = {
                    str(uid): sanitize_user_settings(settings)
                    for uid, settings in user_settings.items()
                    if isinstance(uid, str)
                }
            if isinstance(user_format, dict):
                self._user_format = {
                    str(uid): str(fmt).lower()
                    for uid, fmt in user_format.items()
                    if isinstance(uid, str)
                    and str(fmt).lower() in SUPPORTED_AUDIO_FORMATS
                }
            logger.info(
                "MiMO TTS: loaded persistent user state from %s", self._state_file
            )
        except Exception:
            logger.warning(
                "MiMO TTS: failed to load persistent user state from %s",
                self._state_file,
                exc_info=True,
            )

    def save(self) -> None:
        """Save user state to disk."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "user_settings": {
                    uid: sanitize_user_settings(settings)
                    for uid, settings in self._user_settings.items()
                },
                "user_format": {
                    uid: fmt
                    for uid, fmt in self._user_format.items()
                    if fmt in SUPPORTED_AUDIO_FORMATS
                },
            }
            self._state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning(
                "MiMO TTS: failed to save persistent user state to %s",
                self._state_file,
                exc_info=True,
            )

    def persist(self) -> None:
        """Persist user state to disk with lock to prevent concurrent writes."""
        with self._persist_lock:
            self._evict_stale_users()
            self.save()

    def touch_user(self, uid: str) -> None:
        """Refresh user access order for LRU eviction."""
        stores: list[dict[str, Any]] = [self._user_settings, self._user_format]
        for store in stores:
            if uid in store:
                store[uid] = store.pop(uid)

    def restore(self, uid: str) -> None:
        """Restore current session settings to plugin defaults."""
        self._user_settings.pop(uid, None)
        self._user_format.pop(uid, None)
        self._user_umo.pop(uid, None)
        self._nl_sing_last.pop(uid, None)
        self.persist()

    def reset_all(self) -> None:
        """Clear all user state and remove the state file."""
        self._user_settings.clear()
        self._user_format.clear()
        self._user_umo.clear()
        self._nl_sing_last.clear()
        try:
            if self._state_file.exists():
                self._state_file.unlink()
        except Exception:
            logger.warning(
                "MiMO TTS: failed to remove persistent state file %s",
                self._state_file,
                exc_info=True,
            )

    def get_settings(self, uid: str, normalize_tts_mode) -> dict:
        """Get or initialize user settings for the given uid."""
        if uid not in self._user_settings:
            cfg = self._config
            self._user_settings[uid] = {
                "emotion": cfg.emotion_override,
                "speed": cfg.default_speed,
                "pitch": cfg.default_pitch,
                "voice": cfg.default_voice,
                "breath": cfg.breath_enabled,
                "stress": cfg.stress_enabled,
                "sing": False,
                "laughter": cfg.laughter_enabled,
                "pause": cfg.pause_enabled,
                "style_hint": cfg.style_hint,
                "sing_style": "",
                "dialect": "",
                "volume": "",
                "tts_mode": normalize_tts_mode(cfg.tts_output_mode),
                "tts_enabled": True,
                "text_enabled": None,
                "text_async": None,
                # None = 跟随全局（每次实时读 config，改全局配置立即生效）
                "enable_segmentation": None,
                "enable_voice_polish": None,
                "director_mode": "",
                "director_payload": "",
            }
        self.touch_user(uid)
        return self._user_settings[uid]

    def should_send_text_with_tts(self, uid: str, normalize_tts_mode) -> bool:
        """Check if text should be sent alongside TTS audio."""
        text_enabled = self.get_settings(uid, normalize_tts_mode).get("text_enabled", None)
        if text_enabled is None:
            return self._config.send_text_with_tts
        return bool(text_enabled)

    def should_send_text_async(self, uid: str, normalize_tts_mode) -> bool:
        """Check if text should be sent immediately (async) before TTS completes."""
        text_async = self.get_settings(uid, normalize_tts_mode).get("text_async", None)
        if text_async is None:
            return self._config.send_text_async
        return bool(text_async)

    def segmentation_enabled(self, uid: str, normalize_tts_mode) -> bool:
        """分段开关：None=跟随全局配置，True/False=WebUI 会话级覆盖。"""
        value = self.get_settings(uid, normalize_tts_mode).get("enable_segmentation")
        return self._config.enable_segmentation if value is None else bool(value)

    def voice_polish_enabled(self, uid: str, normalize_tts_mode) -> bool:
        """润色开关：None=跟随全局配置，True/False=WebUI 会话级覆盖。"""
        value = self.get_settings(uid, normalize_tts_mode).get("enable_voice_polish")
        return self._config.enable_voice_polish if value is None else bool(value)

    def get_effective_audio_format(self, uid: str) -> str:
        """Return the effective audio format for the given uid."""
        user_fmt = str(self._user_format.get(uid, "") or "").lower()
        if user_fmt in SUPPORTED_AUDIO_FORMATS:
            return user_fmt

        config_fmt = str(self._config.audio_format or "").lower()
        if config_fmt in SUPPORTED_AUDIO_FORMATS:
            return config_fmt

        return "wav"

    def get_event_settings(self, event, normalize_tts_mode) -> tuple[str, dict]:
        """Get settings dict for current event, migrating legacy keys if needed."""
        scope_key = get_user_scope_key(event)
        legacy_sender_key = safe_event_value(event, "get_sender_id", "sender_id")

        # Store UMO for session identification
        umo = safe_event_value(event, "unified_msg_origin")
        if umo and scope_key not in self._user_umo:
            self._user_umo[scope_key] = umo

        if (
            scope_key not in self._user_settings
            and legacy_sender_key
            and legacy_sender_key in self._user_settings
        ):
            self._user_settings[scope_key] = dict(
                self._user_settings[legacy_sender_key]
            )
            self.persist()
        if (
            scope_key not in self._user_format
            and legacy_sender_key
            and legacy_sender_key in self._user_format
        ):
            self._user_format[scope_key] = self._user_format[legacy_sender_key]
            self.persist()

        return scope_key, self.get_settings(scope_key, normalize_tts_mode)

    def _evict_stale_users(self) -> bool:
        """Evict excess user entries to prevent memory growth."""
        evicted = False
        for store in (self._user_settings, self._user_format):
            if len(store) > self._MAX_IDLE_USERS:
                excess = len(store) - self._MAX_IDLE_USERS
                for uid in list(store.keys())[:excess]:
                    store.pop(uid, None)
                    evicted = True
        # 派生映射（会话标识、唱歌冷却）跟随主设置淘汰，防止无界增长
        for derived in (self._user_umo, self._nl_sing_last):
            stale = derived.keys() - self._user_settings.keys()
            if stale:
                for uid in stale:
                    derived.pop(uid, None)
                evicted = True
        return evicted

    def cleanup_temp_dir(self, temp_dir: Path | None = None) -> int:
        """Directory-level sweep of the temp audio dir.

        ``_recent_files`` is memory-only, so audio files produced before a
        process restart/crash are invisible to ``cleanup_recent_files`` —
        this scan is the only way to reclaim them. Dir convention mirrors
        tts/synthesis.py (``data_dir/temp``). Returns the number of files
        removed.
        """
        target = temp_dir or (self._data_dir / "temp")
        try:
            candidates = [p for p in target.iterdir() if p.is_file()]
        except Exception:
            return 0
        tracked = {p.resolve() for _, p in self._recent_files}
        now = time.time()
        removed = 0
        for path in candidates:
            try:
                if path.resolve() in tracked:
                    continue
                # 保留存活期内的文件：热重载瞬间旧实例可能仍在写盘
                if now - path.stat().st_mtime < self._TEMP_ORPHAN_MIN_AGE_SECONDS:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
            except Exception:
                continue
        if removed:
            logger.info(
                "MiMO TTS: startup temp sweep removed %d orphaned audio file(s) in %s",
                removed,
                target,
            )
        return removed

    def cleanup_recent_files(self) -> None:
        """Clean up stale temp audio files and enforce disk limit."""
        kept: list[tuple[float, Path]] = []
        for t, p in self._recent_files:
            try:
                if not p.exists():
                    continue
                if p.stat().st_size < 100:
                    p.unlink(missing_ok=True)
                    continue
                kept.append((t, p))
            except Exception:
                pass

        kept.sort(key=lambda item: item[0])
        total_bytes = 0
        for _, p in kept:
            try:
                total_bytes += p.stat().st_size
            except Exception:
                pass
        if total_bytes > self._CLEANUP_MAX_TOTAL_BYTES:
            final: list[tuple[float, Path]] = []
            for t, p in kept:
                try:
                    sz = p.stat().st_size
                except Exception:
                    continue
                if total_bytes > self._CLEANUP_MAX_TOTAL_BYTES:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                    total_bytes -= sz
                else:
                    final.append((t, p))
            kept = final

        self._recent_files = kept
