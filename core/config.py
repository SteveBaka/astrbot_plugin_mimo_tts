# -*- coding: utf-8 -*-
"""
Configuration manager for MiMO TTS Plugin.
Reads _conf_schema.json and manages plugin settings.
"""

from __future__ import annotations

from typing import Any


class ConfigManager:
    """Plugin configuration manager that reads settings from _conf_schema.json.

    AstrBot stores plugin config as a flat dict keyed by schema field names.
    This class provides typed accessors and ensures all schema defaults exist.
    """

    # ── Schema defaults (inline fallback) ──

    _SCHEMA_DEFAULTS: dict[str, Any] = {
        # Basic
        "api_key": "",
        "api_base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-tts",
        "default_voice": "mimo_default",
        "probability": 0.8,
        "auto_tts": True,
        "auto_tts_in_group": True,
        "send_text_with_tts": True,
        # Emotion / prosody
        "emotion_override": "",
        "default_speed": 1.0,
        "default_pitch": 0,
        # Voice features
        "style_hint": "",
        "breath_enabled": False,
        "stress_enabled": False,
        "laughter_enabled": False,
        "pause_enabled": False,
        # Voice clone / design
        "clone_enabled": False,
        "clone_model": "mimo-v2.5-tts-voiceclone",
        "clone_voice_id": "",
        "clone_style_prompt": "",
        "clone_audio_tags": "",
        "design_enabled": False,
        "design_model": "mimo-v2.5-tts-voicedesign",
        "tts_output_mode": "default",
        "design_voice_description": "",
        # Voice presets
        "preset_gentle_female": "温柔的女生音色，轻柔细腻",
        "preset_serious_male": "成熟男声，严肃有力",
        "preset_cute_girl": "年轻女孩的声音，活泼甜美",
        "preset_storyteller": "温和的讲述者声音，抑扬顿挫",
        "preset_news_anchor": "标准普通话，字正腔圆，专业权威",
        # Output
        "audio_format": "mp3",
        "min_text_length": 5,
        "max_text_length": 500,
        "timeout": 60,
        "max_retries": 2,
    }

    def __init__(self, config: dict):
        raw_cfg = dict(config or {})
        # 清理不应继续出现在插件设置面板中的历史字段。
        raw_cfg.pop("singing_mode", None)

        # design_voice_id 仍用于运行时兼容旧配置，但不再注入插件设置面板。
        # 这里不再使用占位值，避免 design 模式把无效 voice_id 传入接口。
        self._design_voice_id: str = str(raw_cfg.pop("design_voice_id", "")).strip()

        self._cfg: dict = raw_cfg
        # Ensure all schema keys exist with their defaults
        for key, default_val in self._SCHEMA_DEFAULTS.items():
            if key not in self._cfg:
                self._cfg[key] = default_val

    # ── Generic accessor ──

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by key."""
        return self._cfg.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value."""
        self._cfg[key] = value

    # ── Typed property accessors ──

    @property
    def api_key(self) -> str:
        return str(self._cfg.get("api_key", ""))

    @property
    def api_base_url(self) -> str:
        return str(self._cfg.get("api_base_url", ""))

    @property
    def model(self) -> str:
        return str(self._cfg.get("model", "mimo-v2.5-tts"))

    @property
    def default_voice(self) -> str:
        return str(self._cfg.get("default_voice", "mimo_default"))

    @property
    def probability(self) -> float:
        try:
            value = float(self._cfg.get("probability", 0.8))
        except Exception:
            value = 0.8
        return max(0.0, min(1.0, value))

    @property
    def default_speed(self) -> float:
        return float(self._cfg.get("default_speed", 1.0))

    @property
    def send_text_with_tts(self) -> bool:
        return bool(self._cfg.get("send_text_with_tts", True))

    @property
    def default_pitch(self) -> int:
        return int(self._cfg.get("default_pitch", 0))

    @property
    def emotion_override(self) -> str:
        return str(self._cfg.get("emotion_override", ""))

    @property
    def style_hint(self) -> str:
        return str(self._cfg.get("style_hint", ""))

    @property
    def breath_enabled(self) -> bool:
        return bool(self._cfg.get("breath_enabled", False))

    @property
    def stress_enabled(self) -> bool:
        return bool(self._cfg.get("stress_enabled", False))

    @property
    def laughter_enabled(self) -> bool:
        return bool(self._cfg.get("laughter_enabled", False))

    @property
    def pause_enabled(self) -> bool:
        return bool(self._cfg.get("pause_enabled", False))

    @property
    def clone_enabled(self) -> bool:
        return bool(self._cfg.get("clone_enabled", False))

    @property
    def clone_model(self) -> str:
        return str(self._cfg.get("clone_model", "mimo-v2.5-tts-voiceclone"))

    @property
    def clone_voice_id(self) -> str:
        return str(self._cfg.get("clone_voice_id", ""))

    @property
    def clone_style_prompt(self) -> str:
        return str(self._cfg.get("clone_style_prompt", ""))

    @property
    def clone_audio_tags(self) -> str:
        return str(self._cfg.get("clone_audio_tags", ""))

    @property
    def design_enabled(self) -> bool:
        return bool(self._cfg.get("design_enabled", False))

    @property
    def design_model(self) -> str:
        return str(self._cfg.get("design_model", "mimo-v2.5-tts-voicedesign"))

    @property
    def tts_output_mode(self) -> str:
        return str(self._cfg.get("tts_output_mode", "default"))

    @property
    def design_voice_description(self) -> str:
        return str(self._cfg.get("design_voice_description", ""))

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
            "gentle_female": str(self._cfg.get("preset_gentle_female", "")),
            "serious_male": str(self._cfg.get("preset_serious_male", "")),
            "cute_girl": str(self._cfg.get("preset_cute_girl", "")),
            "storyteller": str(self._cfg.get("preset_storyteller", "")),
            "news_anchor": str(self._cfg.get("preset_news_anchor", "")),
        }

    @property
    def audio_format(self) -> str:
        return str(self._cfg.get("audio_format", "mp3"))

    @property
    def timeout(self) -> int:
        return int(self._cfg.get("timeout", 60))

    @property
    def max_retries(self) -> int:
        return int(self._cfg.get("max_retries", 2))
