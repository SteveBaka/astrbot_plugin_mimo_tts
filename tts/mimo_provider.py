# -*- coding: utf-8 -*-
"""MiMO TTS API Provider."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import struct
import wave
from pathlib import Path
from typing import Optional
from mimetypes import guess_type

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
        self.base_url = base_url.rstrip("/")
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
    def _looks_like_mp3(data: bytes) -> bool:
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)

    @staticmethod
    def _wrap_pcm_as_wav(audio_bytes: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(DEFAULT_PCM_CHANNELS)
            wav_file.setsampwidth(DEFAULT_PCM_SAMPLE_WIDTH)
            wav_file.setframerate(DEFAULT_PCM_SAMPLE_RATE)
            wav_file.writeframes(audio_bytes)
        return buf.getvalue()

    def _normalize_audio_bytes(self, audio_bytes: bytes, requested_format: str) -> tuple[bytes, str]:
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

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        system_prompt: Optional[str] = None,
        audio_format: Optional[str] = None,
        model: Optional[str] = None,
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
        url = f"{self.base_url}/chat/completions"

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

        payload = {
            "model": model or self._model,
            "messages": messages,
            "audio": {
                "voice": voice_id,
                "format": fmt,
            },
            "stream": False,
        }

        backoff = 1.0
        self._set_last_error("")

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
                            audio_b64 = data.get("audio", {}).get("data") if isinstance(data.get("audio"), dict) else data.get("audio")
                        if not audio_b64:
                            self._set_last_error(f"接口返回中未找到音频数据，响应键：{list(data.keys())}")
                            logger.error(f"MiMO TTS: no audio in response. Keys: {list(data.keys())}")
                            return None
                        audio_bytes = base64.b64decode(audio_b64)
                        normalized_bytes, actual_format = self._normalize_audio_bytes(audio_bytes, fmt)
                        self._last_output_format = actual_format
                        logger.info(
                            f"MiMO TTS: synthesized {len(text)} chars -> {len(normalized_bytes)} bytes "
                            f"(requested={fmt}, actual={actual_format})"
                        )
                        return normalized_bytes
                    else:
                        body = await resp.text()
                        self._set_last_error(f"HTTP {resp.status}: {body[:300]}")
                        logger.warning(f"MiMO TTS HTTP {resp.status}: {body[:300]}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._set_last_error(f"请求异常: {e}")
                logger.warning(f"MiMO TTS attempt {attempt} failed: {e}")

            if attempt <= self.max_retries:
                await asyncio.sleep(min(backoff, 10))
                backoff *= 2

        if not self.last_error:
            self._set_last_error(f"请求失败，已重试 {self.max_retries + 1} 次")
        logger.error(f"MiMO TTS: all {self.max_retries + 1} attempts failed")
        return None

    async def register_voice(self, voice_id: str, audio_path: str) -> bool:
        """Register a voice clone with reference audio.

        Args:
            voice_id: The voice ID to register.
            audio_path: Path to the reference audio file.

        Returns:
            True if successful.
        """
        if not self.api_key:
            self._set_last_error("缺少 API Key 配置")
            logger.error("MiMO TTS: missing api_key for voice registration")
            return False

        url = f"{self.base_url}/audio/voice/clone"
        headers = {
            "api-key": self.api_key,
        }

        try:
            self._set_last_error("")
            # Read and encode audio file
            audio_file = Path(audio_path)
            if not audio_file.exists():
                self._set_last_error(f"音频文件不存在: {audio_path}")
                logger.error(f"Audio file not found: {audio_path}")
                return False

            with open(audio_file, "rb") as f:
                audio_data = f.read()

            guessed_content_type = guess_type(audio_file.name)[0] or "application/octet-stream"

            # Build multipart form data
            data = aiohttp.FormData()
            data.add_field("voice_id", voice_id)
            data.add_field(
                "file",
                audio_data,
                filename=audio_file.name,
                content_type=guessed_content_type,
            )

            session = self._get_session()
            async with session.post(url, headers=headers, data=data) as resp:
                if 200 <= resp.status < 300:
                    logger.info(f"Voice clone registered: {voice_id}")
                    return True
                else:
                    body = await resp.text()
                    self._set_last_error(f"HTTP {resp.status}: {body[:300]}")
                    logger.error(f"Voice clone failed ({resp.status}): {body[:200]}")
                    return False
        except Exception as e:
            self._set_last_error(f"请求异常: {e}")
            logger.error(f"Voice clone error: {e}")
            return False

    async def design_voice(self, voice_id: str, description: str, model: str = "mimo-v2.5-tts-voicedesign") -> bool:
        """Generate a voice using the voice design model.

        Args:
            voice_id: The voice ID to create.
            description: Text description of the desired voice.
            model: Voice design model name.

        Returns:
            True if successful.
        """
        if not self.api_key:
            self._set_last_error("缺少 API Key 配置")
            logger.error("MiMO TTS: missing api_key for voice design")
            return False

        url = f"{self.base_url}/audio/voice/design"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": model,
            "voice_id": voice_id,
            "description": description,
        }

        try:
            self._set_last_error("")
            session = self._get_session()
            async with session.post(url, headers=headers, json=payload) as resp:
                if 200 <= resp.status < 300:
                    logger.info(f"Voice designed: {voice_id}")
                    return True
                else:
                    body = await resp.text()
                    self._set_last_error(f"HTTP {resp.status}: {body[:300]}")
                    logger.error(f"Voice design failed ({resp.status}): {body[:200]}")
                    return False
        except Exception as e:
            self._set_last_error(f"请求异常: {e}")
            logger.error(f"Voice design error: {e}")
            return False