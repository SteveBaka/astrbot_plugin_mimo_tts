# -*- coding: utf-8 -*-
"""
Configuration manager for astrbot_plugin_mimo_tts.
Reads _conf_schema.json and manages plugin settings.

Supports nested schema (type: "object" with items) by flattening
into a internal dict for backward-compatible property access.
"""

from __future__ import annotations

from typing import Any


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
        "tts_output_mode": "default",
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
        "audio_format": "wav",
        "min_text_length": 5,
        "max_text_length": 500,
        # Segmentation
        "enable_segmentation": False,
        "segment_pattern": "sentence",
        "segment_max_count": 10,
        "segment_voice_probability": 1.0,
        # Voice polish (LLM)
        "enable_voice_polish": False,
        "polish_llm_provider": "",
        "polish_prompt": "",
        # Clone settings
        "clone_enabled": True,
        "clone_model": "mimo-v2.5-tts-voiceclone",
        "clone_voice_id": "",
        "clone_style_prompt": "",
        "clone_audio_tags": "",
        # Design settings
        "design_enabled": True,
        "design_model": "mimo-v2.5-tts-voicedesign",
        "design_voice_description": "",
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
    def design_enabled(self) -> bool:
        return bool(self._flat.get("design_enabled", True))

    @property
    def design_model(self) -> str:
        return str(self._flat.get("design_model", "mimo-v2.5-tts-voicedesign"))

    @property
    def tts_output_mode(self) -> str:
        return str(self._flat.get("tts_output_mode", "default"))

    @property
    def design_voice_description(self) -> str:
        return str(self._flat.get("design_voice_description", ""))

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

    # ── Voice polish (LLM) ──

    @property
    def enable_voice_polish(self) -> bool:
        return bool(self._flat.get("enable_voice_polish", False))

    @property
    def polish_llm_provider(self) -> str:
        return str(self._flat.get("polish_llm_provider", "") or "")

    @property
    def polish_prompt(self) -> str:
        return str(self._flat.get("polish_prompt", "") or "")

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
