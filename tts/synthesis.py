# -*- coding: utf-8 -*-
"""TTS synthesis orchestration for MiMO TTS plugin.

Handles voice resolution, mode switching, prompt building, and actual synthesis.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from astrbot.api import logger

from ..core.constants import MIMO_VOICE_LIST
from ..core.text_utils import apply_singing_tag, log_tts_text
from ..tts.mimo_provider import MiMOProvider
from ..tts.prompt_builder import build_system_prompt


def normalize_tts_mode(mode: Optional[str]) -> str:
    """Normalize TTS mode string to canonical form."""
    mapping = {
        "default": "default",
        "默认": "default",
        "normal": "default",
        "design": "design",
        "设计": "design",
        "voicedesign": "design",
        "clone": "clone",
        "克隆": "clone",
        "voiceclone": "clone",
    }
    return mapping.get(str(mode or "").strip().lower(), "default")


def tts_mode_label(mode: str) -> str:
    """Return human-readable label for TTS mode."""
    return {
        "default": "默认",
        "design": "设计",
        "clone": "克隆",
    }.get(mode, "[未知]")


def merge_prompt_parts(*parts: Optional[str]) -> str:
    """Merge multiple prompt parts with Chinese comma separator."""
    merged: list[str] = []
    for part in parts:
        text = str(part or "").strip().strip("，,")
        if text:
            merged.append(text)
    return "，".join(merged)


class TTSSynthesizer:
    """Orchestrates TTS synthesis: voice resolution, mode switching, prompt building."""

    def __init__(self, config, voice_manager: "VoiceManager", data_dir: Path):
        self._config = config
        self._voice_manager = voice_manager
        self._data_dir = data_dir
        self._provider: Optional[MiMOProvider] = None

    @property
    def provider(self) -> Optional[MiMOProvider]:
        return self._provider

    def ensure_provider(self) -> Optional[MiMOProvider]:
        """Get or create the TTS provider."""
        if self._provider is not None:
            return self._provider

        api_key = self._config.get("api_key", "")
        if not api_key:
            return None

        api_base_url = self._config.get("api_base_url", "")
        if not api_base_url:
            logger.warning(
                "MiMO TTS: api_base_url not configured. "
                "Please set your API Base URL in plugin config. "
                "Different MiMO plan types use different URLs."
            )
            return None

        self._provider = MiMOProvider(
            api_key=api_key,
            base_url=api_base_url,
            model=self._config.get("model", "mimo-v2.5-tts"),
            voice=self._config.get("default_voice", "mimo_default"),
            audio_format=self._config.get("audio_format", "wav"),
            timeout=self._config.get("timeout", 60),
            max_retries=self._config.get("max_retries"),
        )
        return self._provider

    async def close_provider(self) -> None:
        """Close the TTS provider session."""
        if self._provider is not None:
            try:
                await self._provider.close()
            except Exception:
                pass
            self._provider = None

    def resolve_voice(self, voice_id: str) -> str:
        """Resolve voice ID to a valid voice."""
        info = self._voice_manager.get_voice(voice_id)
        if info:
            return voice_id
        for v in MIMO_VOICE_LIST:
            if v["id"] == voice_id:
                return voice_id
        return self._config.get("default_voice", "mimo_default")

    def resolve_design_description(self, uid: str, get_user_settings) -> str:
        """Resolve the voice design description for the given uid."""
        uset = get_user_settings(uid)
        current_voice = self.resolve_voice(uset["voice"])
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}

        if str(current_voice_info.get("model", "")).lower() == "voicedesign":
            desc = str(current_voice_info.get("description", "")).strip()
            if desc:
                return desc

        return self._config.design_voice_description.strip()

    def resolve_synthesis_target(
        self, uid: str, get_user_settings, uset: Optional[dict] = None
    ) -> tuple[str, Optional[str], str, Optional[str]]:
        """Resolve final voice, model, mode, and clone audio path."""
        if uset is None:
            uset = get_user_settings(uid)
        mode = normalize_tts_mode(uset.get("tts_mode", "default"))
        current_voice = self.resolve_voice(uset["voice"])
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}

        if mode == "clone":
            clone_voice_id = self._config.clone_voice_id.strip()
            if clone_voice_id:
                clone_audio_path = self._voice_manager.get_clone_audio_path(
                    clone_voice_id
                )
                if clone_audio_path:
                    return (
                        clone_voice_id,
                        self._config.clone_model,
                        mode,
                        clone_audio_path,
                    )
            if str(current_voice_info.get("model", "")).lower() == "voiceclone":
                clone_audio_path = self._voice_manager.get_clone_audio_path(
                    current_voice
                )
                if clone_audio_path:
                    return (
                        current_voice,
                        self._config.clone_model,
                        mode,
                        clone_audio_path,
                    )
            raise RuntimeError(
                '当前已切换到"克隆"输出，但未找到可用的本地参考音频。请先执行 /voiceclone <ID> <音频路径>。'
            )

        if mode == "design":
            description = self.resolve_design_description(uid, get_user_settings)
            if description:
                return "", self._config.design_model, mode, None
            raise RuntimeError(
                '当前已切换到"设计"输出，但未配置 design_voice_description，也未选中带描述的设计音色。'
            )

        custom_model = str(current_voice_info.get("model", "")).lower()
        if custom_model == "voiceclone":
            clone_audio_path = self._voice_manager.get_clone_audio_path(current_voice)
            if clone_audio_path:
                return (
                    current_voice,
                    self._config.clone_model,
                    "clone",
                    clone_audio_path,
                )
            raise RuntimeError(
                f"当前音色 {current_voice} 是克隆音色，但未找到可用参考音频。请重新执行 /voiceclone {current_voice} <音频路径>。"
            )

        if custom_model == "voicedesign":
            description = self.resolve_design_description(uid, get_user_settings)
            if description:
                return "", self._config.design_model, "design", None
            raise RuntimeError(
                f"当前音色 {current_voice} 是设计音色，但缺少可用描述文本。请重新执行 /voicegen {current_voice} <描述>。"
            )

        return current_voice, None, mode, None

    def build_prompt(self, uid: str, get_user_settings, emotion_override: Optional[str] = None) -> str:
        """Build the user-role control prompt."""
        uset = get_user_settings(uid)
        style = self._config.style_hint
        return build_system_prompt(
            emotion=emotion_override
            if emotion_override is not None
            else (uset["emotion"] or None),
            speed=uset["speed"],
            pitch=uset["pitch"],
            breath=uset["breath"],
            sing=False,
            stress=uset["stress"],
            laughter=uset["laughter"],
            pause=uset["pause"],
            dialect=uset["dialect"],
            volume=uset["volume"],
            style_hint=style or None,
        )

    def build_clone_prompt(self, base_prompt: str) -> str:
        """Build clone-specific prompt with style and audio tags."""
        style_prompt = self._config.clone_style_prompt.strip()
        audio_tags = self._config.clone_audio_tags.strip()

        tag_prompt = ""
        if audio_tags:
            normalized_tags = re.sub(r"[，、]+", " ", audio_tags)
            normalized_tags = re.sub(r"\s+", " ", normalized_tags).strip()
            if normalized_tags:
                tag_prompt = f"音频标签：{normalized_tags}"

        return merge_prompt_parts(base_prompt, style_prompt, tag_prompt)

    def resolve_clone_audio_path(self, raw_path: str) -> Path:
        """Resolve reference audio path with path traversal protection."""
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return Path(text)

        raw = Path(text)
        plugin_dir = Path(__file__).resolve().parent.parent
        data_clone_dir = self._data_dir / "clone"
        legacy_clone_dir = plugin_dir / "clone"

        allowed_roots: list[Path] = [
            data_clone_dir,
            legacy_clone_dir,
        ]

        candidates: list[Path] = []

        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.extend(
                [
                    data_clone_dir / raw,
                    data_clone_dir / raw.name,
                    legacy_clone_dir / raw,
                    legacy_clone_dir / raw.name,
                    raw,
                ]
            )

        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=False)
                if not resolved.exists():
                    continue
                if any(
                    resolved.is_relative_to(root.resolve())
                    for root in allowed_roots
                    if root.exists()
                ):
                    return resolved
            except Exception:
                continue

        raise PermissionError(
            f"路径 {raw_path!r} 解析后不在允许的克隆音频目录范围内。"
            f"请将参考音频放入: {data_clone_dir}"
        )

    async def do_tts(
        self,
        text: str,
        uid: str,
        get_user_settings,
        get_effective_audio_format,
        format_override: Optional[str] = None,
        emotion_override: Optional[str] = None,
        settings_override: Optional[dict] = None,
    ) -> Optional[Path]:
        """Run TTS and return the audio file path."""
        provider = self.ensure_provider()
        if not provider:
            raise RuntimeError("API Key 未配置。请在配置中设置 api_key。")

        uset = get_user_settings(uid)
        if settings_override:
            uset: dict = {**uset, **settings_override}
        prompt = self.build_prompt(uid, get_user_settings, emotion_override=emotion_override)
        requested_fmt = format_override or get_effective_audio_format(uid)
        fmt = requested_fmt

        sing_voice_override = uset.get("sing_voice_override")
        if uset["sing"] and sing_voice_override:
            current_voice = self.resolve_voice(sing_voice_override)
            uset["voice"] = current_voice
        elif uset["sing"]:
            is_custom_voice = uset["voice"] != self._config.default_voice
            if not is_custom_voice:
                sing_voice_cfg = self._config.sing_voice.strip()
                if sing_voice_cfg:
                    current_voice = self.resolve_voice(sing_voice_cfg)
                    uset["voice"] = current_voice
        final_text = apply_singing_tag(text) if uset["sing"] else text

        log_tts_text(uid, uset.get("tts_mode", "default"), uset["sing"], final_text)

        voice_id, model_override, mode, clone_audio_path = (
            self.resolve_synthesis_target(uid, get_user_settings, uset=uset)
        )
        if mode == "clone":
            prompt = self.build_clone_prompt(prompt)
        elif mode == "design":
            design_description = self.resolve_design_description(uid, get_user_settings)
            prompt = merge_prompt_parts(design_description, prompt)

        raw = await provider.synthesize(
            text=final_text,
            voice=voice_id or None,
            system_prompt=prompt if prompt else None,
            audio_format=fmt,
            model=model_override,
            clone_audio_path=clone_audio_path,
            temperature=self._config.temperature,
            top_p=self._config.top_p,
        )
        if not raw:
            raise RuntimeError(provider.last_error or "MiMO TTS 合成失败，请查看日志。")

        actual_fmt = str(provider.last_output_format or fmt or "mp3").lower()
        if requested_fmt == "wav" and actual_fmt != "wav":
            logger.warning(
                "MiMO TTS: 请求 wav 格式但接口返回了 %s，建议通过 /ttsformat 切换到 wav 或检查平台兼容性",
                actual_fmt,
            )
        elif requested_fmt != actual_fmt:
            logger.info(
                "MiMO TTS: 请求 %s 格式，实际返回 %s",
                requested_fmt,
                actual_fmt,
            )

        tmp_dir = self._data_dir / "temp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out = tmp_dir / f"mimo_{ts}.{actual_fmt}"
        out.write_bytes(raw)
        return out
