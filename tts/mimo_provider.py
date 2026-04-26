# -*- coding: utf-8 -*-
"""MiMO TTS API Provider."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import wave
from mimetypes import guess_type
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


DEFAULT_PCM_SAMPLE_RATE = 24000
DEFAULT_PCM_CHANNELS = 1
DEFAULT_PCM_SAMPLE_WIDTH = 2


class MiMOProvider:
    """Async client for MiMO-V2.5-TTS API.

    Follows official docs: https://platform.xiaomimimo.com/docs/usage-guide/speech-synthesis-v2.5
    Key differences from OpenAI format:
      - Auth header: api-key: <key>  (NOT Authorization: Bearer)
      - Text content goes in assistant role, control prompt in user role
      - Response: choices[0].message.audio.data (base64)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "mimo-v2.5-tts",
        voice: str = "mimo_default",
        audio_format: str = "mp3",
        timeout: int = 60,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.base_url = self._normalize_base_url(base_url)
        self._model = model
        self._voice = voice
        self._audio_format = audio_format
        self.timeout = timeout
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_error: str = ""
        self._last_output_format: str = audio_format

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_output_format(self) -> str:
        return self._last_output_format

    def _set_last_error(self, message: str) -> None:
        self._last_error = str(message or "").strip()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """Normalize configured API base URL for MiMO chat completions.

        Supports the following user inputs:
        - https://api.xiaomimimo.com/v1
        - https://api.xiaomimimo.com
        - https://api.xiaomimimo.com/v1/chat/completions
        """
        text = str(base_url or "").strip().rstrip("/")
        if not text:
            return ""

        if text.endswith("/chat/completions"):
            text = text[: -len("/chat/completions")].rstrip("/")

        parsed = urlparse(text)
        host = (parsed.netloc or "").lower().strip()
        path = (parsed.path or "").rstrip("/")
        if host == "api.xiaomimimo.com" and path == "":
            return f"{text}/v1"
        return text

    def _build_chat_completions_url(self) -> str:
        normalized = self._normalize_base_url(self.base_url)
        return f"{normalized}/chat/completions"

    @staticmethod
    def _looks_like_mp3(data: bytes) -> bool:
        return data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        )

    @staticmethod
    def _wrap_pcm_as_wav(audio_bytes: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(DEFAULT_PCM_CHANNELS)
            wav_file.setsampwidth(DEFAULT_PCM_SAMPLE_WIDTH)
            wav_file.setframerate(DEFAULT_PCM_SAMPLE_RATE)
            wav_file.writeframes(audio_bytes)
        return buf.getvalue()

    def _normalize_audio_bytes(
        self, audio_bytes: bytes, requested_format: str
    ) -> tuple[bytes, str]:
        """尽量将接口返回的音频整理为 AstrBot 可稳定发送的格式。"""
        if audio_bytes.startswith(b"RIFF"):
            return audio_bytes, "wav"
        if audio_bytes.startswith(b"OggS"):
            return audio_bytes, "ogg"
        if self._looks_like_mp3(audio_bytes):
            return audio_bytes, "mp3"

        normalized = requested_format.lower().strip()
        if normalized in {"wav", "pcm"}:
            logger.info("MiMO TTS: received raw PCM bytes, wrapping into WAV container")
            return self._wrap_pcm_as_wav(audio_bytes), "wav"

        logger.warning(
            "MiMO TTS: requested format '%s' but response header is unknown; wrapping as WAV for compatibility",
            normalized,
        )
        return self._wrap_pcm_as_wav(audio_bytes), "wav"

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    @staticmethod
    def _is_voice_design_model(model_name: Optional[str]) -> bool:
        return str(model_name or "").strip().lower() == "mimo-v2.5-tts-voicedesign"

    @staticmethod
    def _is_voice_clone_model(model_name: Optional[str]) -> bool:
        return str(model_name or "").strip().lower() == "mimo-v2.5-tts-voiceclone"

    @staticmethod
    def _normalize_reference_audio_mime(audio_file: Path) -> str:
        guessed = (guess_type(audio_file.name)[0] or "").lower().strip()
        if guessed in {"audio/mpeg", "audio/mp3"}:
            return "audio/mpeg"
        if guessed in {"audio/wav", "audio/x-wav", "audio/wave"}:
            return "audio/wav"

        suffix = audio_file.suffix.lower()
        if suffix == ".mp3":
            return "audio/mpeg"
        if suffix == ".wav":
            return "audio/wav"
        raise ValueError("VoiceClone 参考音频仅支持 mp3 或 wav 格式")

    def _build_voice_clone_data_url(self, audio_path: str) -> str:
        audio_file = Path(audio_path)
        if not audio_file.exists() or not audio_file.is_file():
            raise ValueError(f"参考音频不存在: {audio_path}")

        mime_type = self._normalize_reference_audio_mime(audio_file)
        audio_bytes = audio_file.read_bytes()
        if not audio_bytes:
            raise ValueError(f"参考音频为空文件: {audio_path}")

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        if len(audio_b64.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("参考音频 Base64 编码后超过 10MB，无法用于 VoiceClone")
        return f"data:{mime_type};base64,{audio_b64}"

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        system_prompt: Optional[str] = None,
        audio_format: Optional[str] = None,
        model: Optional[str] = None,
        clone_audio_path: Optional[str] = None,
    ) -> Optional[bytes]:
        """Synthesize text to audio bytes.

        Follows official MiMO-V2.5-TTS API spec:
          - Auth: api-key header (NOT Authorization: Bearer)
          - Text to speak goes in assistant role
          - Control instructions go in user role

        Args:
            text: The text to synthesize.
            voice: Voice ID override (uses self._voice if None).
            system_prompt: Control instructions for emotion/style.
            audio_format: Override audio format (mp3/wav/ogg/pcm).
            model: Override synthesis model.

        Returns:
            Audio bytes, or None on failure.
        """
        if not self.api_key:
            self._set_last_error("缺少 API Key 配置")
            logger.error("MiMO TTS: missing api_key")
            return None

        voice_id = voice or self._voice
        fmt = audio_format or self._audio_format
        url = self._build_chat_completions_url()

        # Official MiMO auth header format
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        # MiMO message format:
        #   assistant role = text to speak
        #   user role = control instructions (emotion, speed, etc.)
        # 官方示例中 user 在前、assistant 在后，这里按文档顺序构造。
        messages = []
        if system_prompt:
            messages.append({"role": "user", "content": system_prompt})
        messages.append({"role": "assistant", "content": text})

        model_name = model or self._model
        payload = {
            "model": model_name,
            "messages": messages,
            "audio": {
                "format": fmt,
            },
            "stream": False,
        }
        if self._is_voice_clone_model(model_name):
            try:
                payload["audio"]["voice"] = self._build_voice_clone_data_url(
                    clone_audio_path or ""
                )
            except Exception as e:
                self._set_last_error(str(e))
                logger.error("MiMO TTS voiceclone payload build failed: %s", e)
                return None
        elif not self._is_voice_design_model(model_name):
            payload["audio"]["voice"] = voice_id

        backoff = 1.0
        self._set_last_error("")
        logger.info(
            "MiMO TTS request prepared: url=%s model=%s clone=%s design=%s format=%s voice=%s has_user_prompt=%s",
            url,
            model_name,
            self._is_voice_clone_model(model_name),
            self._is_voice_design_model(model_name),
            fmt,
            "<data-url>"
            if self._is_voice_clone_model(model_name)
            else (voice_id or ""),
            bool(system_prompt),
        )

        for attempt in range(1, self.max_retries + 2):
            try:
                session = self._get_session()
                async with session.post(url, headers=headers, json=payload) as resp:
                    if 200 <= resp.status < 300:
                        data = await resp.json()
                        # Official response: choices[0].message.audio.data
                        try:
                            audio_b64 = data["choices"][0]["message"]["audio"]["data"]
                        except (KeyError, IndexError, TypeError):
                            # Fallback: try alternate structures
                            audio_b64 = (
                                data.get("audio", {}).get("data")
                                if isinstance(data.get("audio"), dict)
                                else data.get("audio")
                            )
                        if not audio_b64:
                            self._set_last_error(
                                f"接口返回中未找到音频数据，响应键：{list(data.keys())}"
                            )
                            logger.error(
                                f"MiMO TTS: no audio in response. Keys: {list(data.keys())}"
                            )
                            return None
                        audio_bytes = base64.b64decode(audio_b64)
                        normalized_bytes, actual_format = self._normalize_audio_bytes(
                            audio_bytes, fmt
                        )
                        self._last_output_format = actual_format
                        logger.info(
                            f"MiMO TTS: synthesized {len(text)} chars -> {len(normalized_bytes)} bytes "
                            f"(requested={fmt}, actual={actual_format})"
                        )
                        return normalized_bytes
                    else:
                        body = await resp.text()
                        self._set_last_error(
                            f"HTTP {resp.status} @ {url} [model={model_name}]: {body[:300]}"
                        )
                        logger.warning(
                            "MiMO TTS HTTP %s @ %s [model=%s]: %s",
                            resp.status,
                            url,
                            model_name,
                            body[:300],
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._set_last_error(f"请求异常 @ {url} [model={model_name}]: {e}")
                logger.warning(
                    "MiMO TTS attempt %s failed @ %s [model=%s]: %s",
                    attempt,
                    url,
                    model_name,
                    e,
                )

            if attempt <= self.max_retries:
                await asyncio.sleep(min(backoff, 10))
                backoff *= 2

        if not self.last_error:
            self._set_last_error(f"请求失败，已重试 {self.max_retries + 1} 次")
        logger.error(f"MiMO TTS: all {self.max_retries + 1} attempts failed")
        return None

    async def register_voice(self, voice_id: str, audio_path: str) -> bool:
        """Validate a local voice clone reference audio.

        Args:
            voice_id: The voice ID to validate.
            audio_path: Path to the reference audio file.

        Returns:
            True if the local reference audio can be used for VoiceClone.
        """
        try:
            self._set_last_error("")
            _ = self._build_voice_clone_data_url(audio_path)
            logger.info("Voice clone reference validated: %s", voice_id)
            return True
        except Exception as e:
            self._set_last_error(f"参考音频不可用: {e}")
            logger.error("Voice clone validation error: %s", e)
            return False

    async def design_voice(
        self, voice_id: str, description: str, model: str = "mimo-v2.5-tts-voicedesign"
    ) -> bool:
        """Validate a local voice design profile.

        Args:
            voice_id: The voice ID to store.
            description: Text description of the desired voice.
            model: Voice design model name.

        Returns:
            True if the profile can be used during synthesis.
        """
        try:
            self._set_last_error("")
            if not str(voice_id or "").strip():
                raise ValueError("缺少 design 音色 ID")
            if not str(description or "").strip():
                raise ValueError("缺少 design 音色描述")
            if not self._is_voice_design_model(model):
                raise ValueError(f"不支持的 design 模型: {model}")
            logger.info("Voice design profile validated: %s", voice_id)
            return True
        except Exception as e:
            self._set_last_error(f"设计音色配置无效: {e}")
            logger.error("Voice design validation error: %s", e)
            return False
