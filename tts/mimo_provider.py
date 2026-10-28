# -*- coding: utf-8 -*-
"""MiMO TTS API Provider."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from mimetypes import guess_type
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from astrbot.api import logger

DEFAULT_PCM_SAMPLE_RATE = 24000
DEFAULT_PCM_CHANNELS = 1
DEFAULT_PCM_SAMPLE_WIDTH = 2


class MiMOProvider:
    """Async client for MiMO-V2.5-TTS API.

    Follows official docs: https://platform.xiaomimimo.com/docs/usage-guide/speech-synthesis-v2.5
    Auth strategy (dual headers for maximum compatibility):
      - api-key: <key>        — MiMO 原生平台认证
      - Authorization: Bearer — NewAPI / OpenAI 兼容代理认证
    Key differences from OpenAI format:
      - Text content goes in assistant role, control prompt in user role
      - Response: choices[0].message.audio.data (base64)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "mimo-v2.5-tts",
        voice: str = "mimo_default",
        audio_format: str = "wav",
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
        """尽量将接口返回的音频整理为 AstrBot 可稳定发送的格式。

        当请求 wav 但 API 返回 mp3 时，自动将实际格式记录为 mp3 并发出警告，
        由调用方决定后续处理方式（当前 _do_tts 会用 actual_fmt 命名文件）。
        """
        if audio_bytes.startswith(b"RIFF"):
            return audio_bytes, "wav"
        if audio_bytes.startswith(b"OggS"):
            return audio_bytes, "ogg"
        if self._looks_like_mp3(audio_bytes):
            if requested_format.lower().strip() in {"wav", "pcm"}:
                logger.warning(
                    "MiMO TTS: requested wav but API returned mp3; "
                    "keeping actual format to avoid playback failure"
                )
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
        # audio_b64 is纯 ASCII 字符串，其 len() 就等于 UTF-8 字节数，
        # 无需再 encode("utf-8") 造成大量临时内存分配。
        if len(audio_b64) > 10 * 1024 * 1024:
            raise ValueError("参考音频 Base64 编码后超过 10MB，无法用于 VoiceClone")
        return f"data:{mime_type};base64,{audio_b64}"

    @staticmethod
    def _extract_stream_audio_b64(obj: dict) -> Optional[str]:
        """从流式 chunk 中提取 base64 音频（兼容多种 delta 形态）。"""
        if not isinstance(obj, dict):
            return None
        try:
            choice0 = (obj.get("choices") or [{}])[0]
            delta = choice0.get("delta") or choice0.get("message") or {}
            audio = delta.get("audio") if isinstance(delta, dict) else None
            if isinstance(audio, dict):
                data = audio.get("data") or audio.get("b64")
                if data:
                    return str(data)
            if isinstance(audio, str) and audio:
                return audio
        except (IndexError, TypeError, AttributeError):
            pass
        audio_root = obj.get("audio")
        if isinstance(audio_root, dict):
            data = audio_root.get("data") or audio_root.get("b64")
            if data:
                return str(data)
        if isinstance(audio_root, str) and audio_root:
            return audio_root
        return None

    @staticmethod
    def _wav_pcm_payload(wav_bytes: bytes) -> Optional[bytes]:
        """从完整 WAV 中剥离 RIFF 头，只取 PCM data；失败返回 None。"""
        if not wav_bytes.startswith(b"RIFF") or len(wav_bytes) < 44:
            return None
        try:
            # RIFF: 0-3 RIFF, 4-7 size, 8-11 WAVE, then chunks
            offset = 12
            while offset + 8 <= len(wav_bytes):
                cid = wav_bytes[offset : offset + 4]
                size = int.from_bytes(wav_bytes[offset + 4 : offset + 8], "little")
                data_off = offset + 8
                if cid == b"data":
                    end = min(len(wav_bytes), data_off + max(size, 0))
                    payload = wav_bytes[data_off:end]
                    if payload:
                        return payload
                    return None
                # odd-sized chunk padding
                offset = data_off + size + (size & 1)
            return None
        except Exception:
            return None

    def _join_stream_chunks(
        self, decoded: list[bytes], requested_format: str
    ) -> tuple[bytes, str]:
        """拼接流式分片。

        实测部分兼容网关会把「完整 WAV/容器」逐分片下发；直接 b"".join 会得到
        多 RIFF 头的坏文件（ffmpeg 时长可只有几十毫秒）。策略：
        - 全是 RIFF → 各取 PCM data 再统一包一层 WAV
        - 单个完整容器（mp3/ogg/wav）→ 直接用
        - 多个完整容器 → 优先最后一片（通常是最新的完整帧），失败再试拼 PCM
        - 否则当 raw PCM 拼接后 normalize
        """
        decoded = [c for c in decoded if c]
        if not decoded:
            raise RuntimeError("stream 音频拼接后为空")

        if all(c.startswith(b"RIFF") for c in decoded):
            pcm = b""
            for c in decoded:
                part = self._wav_pcm_payload(c)
                pcm += part if part is not None else b""
            if pcm:
                return self._wrap_pcm_as_wav(pcm), "wav"
            # 退化：只用最后一片完整 WAV
            last = decoded[-1]
            return self._normalize_audio_bytes(last, requested_format)

        if len(decoded) > 1:
            complete = [
                c
                for c in decoded
                if c.startswith(b"RIFF")
                or c.startswith(b"OggS")
                or self._looks_like_mp3(c)
            ]
            if len(complete) == len(decoded):
                # 多份完整容器：取最大者（通常信息量最全）
                best = max(complete, key=len)
                logger.warning(
                    "MiMO TTS: stream returned %d complete containers; using largest (%d bytes)",
                    len(complete),
                    len(best),
                )
                return self._normalize_audio_bytes(best, requested_format)

        joined = b"".join(decoded)
        return self._normalize_audio_bytes(joined, requested_format)

    async def _post_stream_once(
        self,
        url: str,
        headers: dict,
        payload: dict,
        requested_format: str,
        stream_timeout: int,
    ) -> Optional[tuple[bytes, str]]:
        """SSE 流式拉取音频片段并拼接；失败抛异常由上层降级非流式。"""
        timeout = aiohttp.ClientTimeout(total=max(5, int(stream_timeout or 60)))
        session = aiohttp.ClientSession(timeout=timeout)
        chunks_b64: list[str] = []
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                if not (200 <= resp.status < 300):
                    body = await resp.text()
                    raise RuntimeError(f"stream HTTP {resp.status}: {body[:200]}")
                content_type = (resp.headers.get("Content-Type") or "").lower()
                if "text/event-stream" not in content_type and "json" in content_type:
                    data = await resp.json()
                    b64 = self._extract_stream_audio_b64(data)
                    if not b64:
                        raise RuntimeError("stream JSON 无音频字段")
                    chunks_b64.append(b64)
                else:
                    async for raw_line in resp.content:
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.startswith(b"data:"):
                            line = line[5:].strip()
                        if not line or line == b"[DONE]":
                            if line == b"[DONE]":
                                break
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        b64 = self._extract_stream_audio_b64(obj)
                        if b64:
                            chunks_b64.append(b64)
        finally:
            await session.close()

        if not chunks_b64:
            raise RuntimeError("stream 未收到任何音频分片")
        decoded = [base64.b64decode(c) for c in chunks_b64]
        logger.info(
            "MiMO TTS: stream received %d audio chunks total_decoded=%d first_head=%s",
            len(decoded),
            sum(len(c) for c in decoded),
            decoded[0][:4] if decoded else b"",
        )
        return self._join_stream_chunks(decoded, requested_format)

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        control_prompt: Optional[str] = None,
        audio_format: Optional[str] = None,
        model: Optional[str] = None,
        clone_audio_path: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        optimize_text_preview: bool = False,
        use_stream: bool = False,
        stream_timeout: int = 60,
    ) -> Optional[bytes]:
        """Synthesize text to audio bytes.

        Follows official MiMO-V2.5-TTS API spec:
          - Auth: dual headers (api-key + Authorization: Bearer)
          - Text to speak goes in assistant role
          - Control instructions go in user role

        Args:
            text: The text to synthesize.
            voice: Voice ID override (uses self._voice if None).
            control_prompt: Control instructions for emotion/style (user role).
            audio_format: Override audio format (mp3/wav/ogg/pcm).
            model: Override synthesis model.
            optimize_text_preview: 官方 voicedesign 智能润色参数（仅设计模型生效）。
            use_stream: 仅 default 模型可请求 API stream=true；clone/design 忽略。
            stream_timeout: 流式合成总超时（秒）；失败自动降级非流式。

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

        # Dual auth headers:
        #   - api-key: MiMO 原生平台认证
        #   - Authorization: Bearer: NewAPI / OpenAI 兼容代理认证
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
        }

        # MiMO message format:
        #   assistant role = text to speak
        #   user role = control instructions (emotion, speed, etc.)
        # 官方示例中 user 在前、assistant 在后，这里按文档顺序构造。
        messages = []
        if control_prompt:
            messages.append({"role": "user", "content": control_prompt})
        messages.append({"role": "assistant", "content": text})

        model_name = model or self._model
        is_clone = self._is_voice_clone_model(model_name)
        is_design = self._is_voice_design_model(model_name)
        audio: dict = {"format": fmt}
        if is_clone:
            try:
                audio["voice"] = self._build_voice_clone_data_url(
                    clone_audio_path or ""
                )
            except Exception as e:
                self._set_last_error(str(e))
                logger.error("MiMO TTS voiceclone payload build failed: %s", e)
                return None
        elif not is_design:
            audio["voice"] = voice_id
        elif optimize_text_preview:
            # 官方参数：仅 voicedesign 支持，控制服务端对播报文本智能润色
            audio["optimize_text_preview"] = True

        # P3 流式合成：仅 default 模型；clone/design 恒 stream=false
        allow_stream = bool(use_stream) and not is_clone and not is_design
        payload: dict = {
            "model": model_name,
            "messages": messages,
            "audio": audio,
            "stream": allow_stream,
        }

        # Model hyperparameters (temperature/top_p)
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p

        backoff = 1.0
        self._set_last_error("")
        logger.info(
            "MiMO TTS request prepared: url=%s model=%s clone=%s design=%s "
            "format=%s voice=%s has_user_prompt=%s tts_api_stream=%s",
            url,
            model_name,
            is_clone,
            is_design,
            fmt,
            "<data-url>" if is_clone else (voice_id or ""),
            bool(control_prompt),
            allow_stream,
        )

        if allow_stream:
            try:
                logger.info(
                    "MiMO TTS: streaming synthesis start chars=%d timeout=%ss",
                    len(text),
                    stream_timeout,
                )
                result = await self._post_stream_once(
                    url, headers, payload, fmt, stream_timeout
                )
                if result:
                    normalized_bytes, actual_format = result
                    self._last_output_format = actual_format
                    logger.info(
                        "MiMO TTS: streaming synthesized %d chars -> %d bytes "
                        "(requested=%s, actual=%s, tts_api_stream=true)",
                        len(text),
                        len(normalized_bytes),
                        fmt,
                        actual_format,
                    )
                    return normalized_bytes
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "MiMO TTS: stream synthesis failed (%s); fallback to non-stream",
                    e,
                )
                payload["stream"] = False

        total_attempts = self.max_retries + 1
        for attempt in range(1, total_attempts + 1):
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
                                "MiMO TTS: no audio in response. Keys: %s",
                                list(data.keys()),
                            )
                            return None
                        audio_bytes = base64.b64decode(audio_b64)
                        normalized_bytes, actual_format = self._normalize_audio_bytes(
                            audio_bytes, fmt
                        )
                        self._last_output_format = actual_format
                        logger.info(
                            "MiMO TTS: synthesized %d chars -> %d bytes "
                            "(requested=%s, actual=%s, tts_api_stream=false)",
                            len(text),
                            len(normalized_bytes),
                            fmt,
                            actual_format,
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
                        # 认证错误和客户端参数错误不重试
                        if resp.status in (401, 403, 400):
                            logger.error(
                                "MiMO TTS: non-retryable HTTP %s, aborting",
                                resp.status,
                            )
                            return None
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

            if attempt < total_attempts:
                await asyncio.sleep(min(backoff, 10))
                backoff *= 2

        if not self.last_error:
            self._set_last_error(f"请求失败，已重试 {total_attempts} 次")
        logger.error("MiMO TTS: all %d attempts failed", total_attempts)
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
