# -*- coding: utf-8 -*-
"""User state management for MiMO TTS plugin.

Handles per-user settings persistence, LRU eviction, and format overrides.
"""

from __future__ import annotations

import json
import threading
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
        "dialect": "",
        "volume": "",
        "tts_mode": "default",
        "tts_enabled": True,
        "text_enabled": None,
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
    cleaned["tts_mode"] = str(cleaned.get("tts_mode", "default") or "default")
    cleaned["tts_enabled"] = bool(cleaned.get("tts_enabled", True))
    text_enabled = cleaned.get("text_enabled", None)
    cleaned["text_enabled"] = None if text_enabled is None else bool(text_enabled)
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
    _CLEANUP_MAX_TOTAL_BYTES = 500 * 1024 * 1024

    def __init__(self, data_dir: Path, config):
        self._data_dir = data_dir
        self._state_file = data_dir / "user_state.json"
        self._config = config
        self._user_settings: dict[str, dict] = {}
        self._user_format: dict[str, str] = {}
        self._user_umo: dict[str, str] = {}
        self._recent_files: list[tuple[float, Path]] = []
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
        self.persist()

    def reset_all(self) -> None:
        """Clear all user state and remove the state file."""
        self._user_settings.clear()
        self._user_format.clear()
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
                "dialect": "",
                "volume": "",
                "tts_mode": normalize_tts_mode(cfg.tts_output_mode),
                "tts_enabled": True,
                "text_enabled": None,
            }
        self.touch_user(uid)
        return self._user_settings[uid]

    def should_send_text_with_tts(self, uid: str, normalize_tts_mode) -> bool:
        """Check if text should be sent alongside TTS audio."""
        text_enabled = self.get_settings(uid, normalize_tts_mode).get("text_enabled", None)
        if text_enabled is None:
            return self._config.send_text_with_tts
        return bool(text_enabled)

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
        return evicted

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
