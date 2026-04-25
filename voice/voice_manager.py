# -*- coding: utf-8 -*-
"""Voice Manager - manages voice clones and generated voices."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class VoiceManager:
    """Manages voice clones and voice design samples."""

    def __init__(
        self,
        voice_cache_dir: Path = Path("voice"),
        audio_samples_dir: Path = Path("audio_samples"),
    ):
        self.voice_cache_dir = voice_cache_dir
        self.audio_samples_dir = audio_samples_dir
        self.voice_cache_dir.mkdir(parents=True, exist_ok=True)
        self.audio_samples_dir.mkdir(parents=True, exist_ok=True)

        # Registry file for clones
        self.registry_file = self.voice_cache_dir / "voice_registry.json"
        self._voices: dict[str, dict] = self._load_registry()

    def _load_registry(self) -> dict:
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_registry(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(self._voices, f, ensure_ascii=False, indent=2)

    def register_voice(self, voice_id: str, name: str = "", model: str = "voiceclone", **kwargs) -> None:
        """Register a voice (clone or generated) in the local registry."""
        self._voices[voice_id] = {
            "voice_id": voice_id,
            "name": name or voice_id,
            "model": model,
            **kwargs,
        }
        self._save_registry()
        logger.info(f"Voice registered: {voice_id} (model={model})")

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