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

import aiohttp

logger = logging.getLogger(__name__)


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

        Returns:
            Audio bytes, or None on failure.
        """
        if not self.api_key:
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
        messages = []
        messages.append({"role": "assistant", "content": text})
        if system_prompt:
            messages.append({"role": "user", "content": system_prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "voice": voice_id,
            "audio_format": fmt,
            "stream": False,
        }

        backoff = 1.0

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
                            logger.error(f"MiMO TTS: no audio in response. Keys: {list(data.keys())}")
                            return None
                        audio_bytes = base64.b64decode(audio_b64)
                        logger.info(f"MiMO TTS: synthesized {len(text)} chars -> {len(audio_bytes)} bytes ({fmt})")
                        return audio_bytes
                    else:
                        body = await resp.text()
                        logger.warning(f"MiMO TTS HTTP {resp.status}: {body[:300]}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"MiMO TTS attempt {attempt} failed: {e}")

            if attempt <= self.max_retries:
                await asyncio.sleep(min(backoff, 10))
                backoff *= 2

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
            logger.error("MiMO TTS: missing api_key for voice registration")
            return False

        url = f"{self.base_url}/audio/voice/clone"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            # Read and encode audio file
            audio_file = Path(audio_path)
            if not audio_file.exists():
                logger.error(f"Audio file not found: {audio_path}")
                return False

            with open(audio_file, "rb") as f:
                audio_data = f.read()

            # Build multipart form data
            data = aiohttp.FormData()
            data.add_field("voice_id", voice_id)
            data.add_field(
                "file",
                audio_data,
                filename=audio_file.name,
                content_type="audio/wav",
            )

            session = self._get_session()
            async with session.post(url, headers=headers, data=data) as resp:
                if 200 <= resp.status < 300:
                    logger.info(f"Voice clone registered: {voice_id}")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Voice clone failed ({resp.status}): {body[:200]}")
                    return False
        except Exception as e:
            logger.error(f"Voice clone error: {e}")
            return False

    async def design_voice(self, voice_id: str, description: str) -> bool:
        """Generate a voice using the voice design model.

        Args:
            voice_id: The voice ID to create.
            description: Text description of the desired voice.

        Returns:
            True if successful.
        """
        if not self.api_key:
            logger.error("MiMO TTS: missing api_key for voice design")
            return False

        url = f"{self.base_url}/audio/voice/design"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "voice_id": voice_id,
            "description": description,
        }

        try:
            session = self._get_session()
            async with session.post(url, headers=headers, json=payload) as resp:
                if 200 <= resp.status < 300:
                    logger.info(f"Voice designed: {voice_id}")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Voice design failed ({resp.status}): {body[:200]}")
                    return False
        except Exception as e:
            logger.error(f"Voice design error: {e}")
            return False