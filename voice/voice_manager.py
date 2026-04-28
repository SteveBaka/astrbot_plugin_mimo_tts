# -*- coding: utf-8 -*-
"""Voice Manager - manages voice clones and generated voices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from astrbot.api import logger


class VoiceManager:
    """Manages voice clones and voice design samples."""

    def __init__(
        self,
        data_dir: Path | None = None,
        voice_cache_dir: Path | None = None,
        clone_audio_dir: Path | None = None,
    ):
        self.plugin_dir = Path(__file__).resolve().parent.parent

        # data_dir 由 main.py 通过 StarTools.get_data_dir() 获取后传入；
        # 这里仅在未传入时回退到插件目录下的 data 子目录，避免在子模块中
        # 直接调用 StarTools 导致无法解析模块元数据的问题。
        default_data_dir = self.plugin_dir / "data"
        self.data_dir = Path(data_dir) if data_dir else default_data_dir
        self.voice_cache_dir = (
            Path(voice_cache_dir) if voice_cache_dir else (self.data_dir / "voice")
        )
        self.clone_audio_dir = (
            Path(clone_audio_dir) if clone_audio_dir else (self.data_dir / "clone")
        )
        self.voice_cache_dir.mkdir(parents=True, exist_ok=True)
        self.clone_audio_dir.mkdir(parents=True, exist_ok=True)

        # Registry file for clones
        self.registry_file = self.voice_cache_dir / "voice_registry.json"
        self.legacy_registry_file = Path("voice") / "voice_registry.json"
        self.legacy_plugin_registry_file = (
            self.plugin_dir / "voice" / "voice_registry.json"
        )
        self.legacy_plugin_clone_dir = self.plugin_dir / "clone"
        self._voices: dict[str, dict] = self._load_registry()

    def _load_registry(self) -> dict:
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}

        if self.legacy_registry_file.exists():
            try:
                with open(self.legacy_registry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(
                    "Loaded legacy voice registry from: %s", self.legacy_registry_file
                )
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        if self.legacy_plugin_registry_file.exists():
            try:
                with open(self.legacy_plugin_registry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(
                    "Loaded legacy plugin voice registry from: %s",
                    self.legacy_plugin_registry_file,
                )
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def _save_registry(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(self._voices, f, ensure_ascii=False, indent=2)

    def register_voice(
        self, voice_id: str, name: str = "", model: str = "voiceclone", **kwargs
    ) -> None:
        """Register a voice (clone or generated) in the local registry."""
        normalized_kwargs = dict(kwargs)
        audio_path = normalized_kwargs.get("audio_path")
        if audio_path:
            try:
                path_obj = Path(audio_path)
                if not path_obj.is_absolute():
                    candidate = self.plugin_dir / path_obj
                    if candidate.exists():
                        path_obj = candidate
                    else:
                        clone_candidate = self.clone_audio_dir / path_obj.name
                        if clone_candidate.exists():
                            path_obj = clone_candidate
                        else:
                            legacy_clone_candidate = (
                                self.legacy_plugin_clone_dir / path_obj.name
                            )
                            if legacy_clone_candidate.exists():
                                path_obj = legacy_clone_candidate
                normalized_kwargs["audio_path"] = str(path_obj.resolve())
            except Exception:
                normalized_kwargs["audio_path"] = str(audio_path)

        self._voices[voice_id] = {
            "voice_id": voice_id,
            "name": name or voice_id,
            "model": model,
            **normalized_kwargs,
        }
        self._save_registry()
        logger.info(f"Voice registered: {voice_id} (model={model})")

    def get_clone_audio_path(self, voice_id: str) -> str:
        """Get local reference audio path for a clone voice."""
        info = self.get_voice(voice_id) or {}
        raw_path = str(info.get("audio_path", "") or "").strip()
        if not raw_path:
            return ""

        path_obj = Path(raw_path)
        if path_obj.exists():
            return str(path_obj)

        fallback = self.clone_audio_dir / path_obj.name
        if fallback.exists():
            logger.warning(
                "Clone audio path migrated by fallback: voice_id=%s old=%s new=%s",
                voice_id,
                raw_path,
                fallback,
            )
            info["audio_path"] = str(fallback.resolve())
            self._voices[voice_id] = info
            self._save_registry()
            return str(fallback.resolve())

        legacy_fallback = self.legacy_plugin_clone_dir / path_obj.name
        if legacy_fallback.exists():
            logger.warning(
                "Clone audio path using legacy plugin clone dir: voice_id=%s old=%s new=%s",
                voice_id,
                raw_path,
                legacy_fallback,
            )
            info["audio_path"] = str(legacy_fallback.resolve())
            self._voices[voice_id] = info
            self._save_registry()
            return str(legacy_fallback.resolve())

        return ""

    def get_voice(self, voice_id: str) -> Optional[dict]:
        """Get voice info by ID."""
        return self._voices.get(voice_id)

    def list_voices(self) -> list[dict]:
        """List all registered voices."""
        return list(self._voices.values())

    def remove_voice(self, voice_id: str) -> bool:
        """Remove a registered voice."""
        if voice_id in self._voices:
            del self._voices[voice_id]
            self._save_registry()
            logger.info(f"Voice removed: {voice_id}")
            return True
        return False
