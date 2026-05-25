# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.message_components import Plain, Record

from .core.config import ConfigManager
from .core.constants import (
    MIMO_VOICE_LIST,
    SKIP_PATTERNS,
    SUPPORTED_AUDIO_FORMATS,
)
from .handlers.control import (
    handle_text,
    handle_tts_help,
    handle_tts_off,
    handle_tts_on,
    handle_tts_restore,
)
from .handlers.params import (
    handle_breath,
    handle_dialect,
    handle_emotion,
    handle_emotions,
    handle_laughter,
    handle_pause,
    handle_pitch,
    handle_speed,
    handle_stress,
    handle_volume,
)
from .handlers.preset import handle_preset, handle_presetlist
from .handlers.settings import handle_ttsconfig, handle_ttsformat, handle_ttsinfo
from .handlers.tts import handle_mimo_say, handle_sing, handle_ttsraw
from .handlers.voice import (
    handle_ttsswitch,
    handle_voice,
    handle_voiceclone,
    handle_voicegen,
    handle_voices,
)
from .tts.mimo_provider import MiMOProvider
from .tts.prompt_builder import build_system_prompt, detect_emotion
from .voice.voice_manager import VoiceManager


def _read_plugin_version() -> str:
    """Read version from metadata.yaml to avoid hardcoding."""
    try:
        meta_path = Path(__file__).parent / "metadata.yaml"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
            v = str(meta.get("version", "")).strip()
            if v:
                return v
    except Exception:
        pass
    return "unknown"


class MiMoTTSPlugin(Star):
    """AstrBot Plugin: MiMO TTS — fine-grained voice synthesis with emotion control."""

    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)

        self.config = ConfigManager(config or {})

        # ── TTS provider ──
        self._provider: Optional[MiMOProvider] = None

        # ── Per-user settings: {uid: {emotion, speed, pitch, voice, breath, stress, sing, dialect, volume, laughter, pause}} ──
        self._user_settings: dict[str, dict] = {}

        # ── Per-user output format override ──
        self._user_format: dict[str, str] = {}

        # ── Persistent state ──
        self._plugin_dir = Path(__file__).resolve().parent
        self._data_dir = Path(StarTools.get_data_dir())
        self._state_file = self._data_dir / "user_state.json"

        # ── Voice manager ──
        self._voice_manager = VoiceManager(data_dir=self._data_dir)

        # ── Persist lock (prevents concurrent state file writes) ──
        self._persist_lock = threading.Lock()

        # ── Audio file cleanup tracking ──
        self._recent_files: list[tuple[float, Path]] = []

        # ── Init done ──
        self._started = False

        self._load_user_state()

    # ── Helpers ────────────────────────────────────────────────

    def _ensure_provider(self) -> Optional[MiMOProvider]:
        """Get or create the TTS provider.

        api_key and api_base_url are both required.
        api_base_url must be set in plugin config according to the user's
        MiMO plan (different plan types have different base URLs).
        """
        if self._provider is not None:
            return self._provider

        api_key = self.config.get("api_key", "")
        if not api_key:
            return None

        api_base_url = self.config.get("api_base_url", "")
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
            model=self.config.get("model", "mimo-v2.5-tts"),
            voice=self.config.get("default_voice", "mimo_default"),
            audio_format=self.config.get("audio_format", "wav"),
            timeout=self.config.get("timeout", 60),
            max_retries=self.config.get("max_retries"),
        )
        return self._provider

    @staticmethod
    def _sanitize_user_settings(data: dict) -> dict:
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

    def _load_user_state(self) -> None:
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
                    str(uid): self._sanitize_user_settings(settings)
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

    def _save_user_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "user_settings": {
                    uid: self._sanitize_user_settings(settings)
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

    def _persist_current_state(self) -> None:
        """Persist user state to disk with lock to prevent concurrent writes."""
        with self._persist_lock:
            self._evict_stale_users()
            self._save_user_state()

    def _touch_user(self, uid: str) -> None:
        """刷新用户访问顺序，实现 LRU 淘汰。"""
        stores: list[dict[str, Any]] = [self._user_settings, self._user_format]
        for store in stores:
            if uid in store:
                store[uid] = store.pop(uid)

    def _restore_user_state(self, uid: str) -> None:
        """将当前会话设置恢复为插件配置默认值。"""
        self._user_settings.pop(uid, None)
        self._user_format.pop(uid, None)
        self._persist_current_state()

    def _reset_persistent_state(self) -> None:
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

    def _get_user_settings(self, uid: str) -> dict:
        if uid not in self._user_settings:
            self._user_settings[uid] = {
                "emotion": self.config.emotion_override,
                "speed": self.config.default_speed,
                "pitch": self.config.default_pitch,
                "voice": self.config.default_voice,
                "breath": self.config.breath_enabled,
                "stress": self.config.stress_enabled,
                "sing": False,
                "laughter": self.config.laughter_enabled,
                "pause": self.config.pause_enabled,
                "style_hint": self.config.style_hint,
                "dialect": "",
                "volume": "",
                "tts_mode": self._normalize_tts_mode(self.config.tts_output_mode),
                "tts_enabled": True,
                "text_enabled": None,
            }
        self._touch_user(uid)
        return self._user_settings[uid]

    def _should_send_text_with_tts(self, uid: str) -> bool:
        text_enabled = self._get_user_settings(uid).get("text_enabled", None)
        if text_enabled is None:
            return self.config.send_text_with_tts
        return bool(text_enabled)

    def _get_effective_audio_format(self, uid: str) -> str:
        """返回当前会话实际生效的音频格式：优先当前对话覆盖，否则回退插件配置。"""
        user_fmt = str(self._user_format.get(uid, "") or "").lower()
        if user_fmt in SUPPORTED_AUDIO_FORMATS:
            return user_fmt

        config_fmt = str(self.config.audio_format or "").lower()
        if config_fmt in SUPPORTED_AUDIO_FORMATS:
            return config_fmt

        return "wav"

    @staticmethod
    def _safe_event_value(event: AstrMessageEvent, *names: str) -> str:
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

    def _get_user_scope_key(self, event: AstrMessageEvent) -> str:
        """Resolve a stable settings key shared by commands and auto-TTS callbacks.

        优先使用会话/会话上下文 ID，避免某些阶段的 sender_id 不一致，
        导致 `/ttsswitch` 反馈成功但实际合成仍读取另一份默认设置。
        """
        session_id = self._safe_event_value(event, "get_session_id", "session_id")
        if session_id:
            return f"session:{session_id}"

        conversation_id = self._safe_event_value(
            event, "get_conversation_id", "conversation_id"
        )
        if conversation_id:
            return f"conversation:{conversation_id}"

        group_id = self._safe_event_value(event, "get_group_id", "group_id")
        sender_id = self._safe_event_value(event, "get_sender_id", "sender_id")
        if group_id and sender_id:
            return f"group:{group_id}:user:{sender_id}"
        if sender_id:
            return f"user:{sender_id}"
        return "user:default"

    def _get_event_settings(self, event: AstrMessageEvent) -> tuple[str, dict]:
        """Get settings dict for current event and migrate legacy sender-id keys if needed."""
        scope_key = self._get_user_scope_key(event)
        legacy_sender_key = self._safe_event_value(event, "get_sender_id", "sender_id")

        if (
            scope_key not in self._user_settings
            and legacy_sender_key
            and legacy_sender_key in self._user_settings
        ):
            self._user_settings[scope_key] = dict(
                self._user_settings[legacy_sender_key]
            )
            self._persist_current_state()
        if (
            scope_key not in self._user_format
            and legacy_sender_key
            and legacy_sender_key in self._user_format
        ):
            self._user_format[scope_key] = self._user_format[legacy_sender_key]
            self._persist_current_state()

        return scope_key, self._get_user_settings(scope_key)

    def _is_tts_active(self, uid: str) -> bool:
        if not self.config.get("auto_tts", True):
            return False

        if not self._get_user_settings(uid).get("tts_enabled", True):
            return False

        probability = self.config.probability
        if probability <= 0:
            return False
        if probability >= 1:
            return True
        return random.random() < probability

    def _should_skip(self, text: str) -> bool:
        if not text or not text.strip():
            return True
        t = text.strip()
        if len(t) < self.config.get("min_text_length"):
            return True
        if len(t) > self.config.get("max_text_length"):
            return True
        for pat in SKIP_PATTERNS:
            if re.search(pat, t):
                return True
        return False

    def _split_text(self, text: str) -> list[str]:
        """Split text into segments using the configured regex pattern."""
        from .core.constants import SEGMENT_PATTERNS

        pattern_name = self.config.segment_pattern
        regex = SEGMENT_PATTERNS.get(pattern_name, SEGMENT_PATTERNS["sentence"])
        segments = re.split(regex, text)
        result = [s.strip() for s in segments if s.strip()]

        max_count = self.config.segment_max_count
        if max_count > 0 and len(result) > max_count:
            merged = result[:max_count - 1]
            merged.append("".join(result[max_count - 1:]))
            result = merged

        return result

    @staticmethod
    def _strip_audio_tags(text: str) -> str:
        """Remove MiMO audio tags for display: (风格) and [标签]."""
        s = re.sub(r"[（\(][^）\)]{1,10}[）\)]", "", text)
        s = re.sub(r"[\[【][^\]】]{1,20}[\]】]", "", s)
        return re.sub(r"\s{2,}", " ", s).strip()

    async def _polish_text_with_llm(self, text: str, uid: str) -> str:
        """Use LLM to inject MiMO audio tags into text before TTS."""
        provider_id = self.config.polish_llm_provider
        if not provider_id:
            try:
                provider_id = await self.context.get_current_chat_provider_id(uid)
            except Exception:
                logger.warning(
                    "MiMO TTS: failed to get current provider for voice polish, "
                    "falling back to original text"
                )
                return text
        prompt_tpl = self.config.polish_prompt
        if not prompt_tpl:
            prompt_tpl = (
                "你是语音润色助手。请在以下文本中适当添加 MiMO TTS 音频标签，"
                "使语音更自然生动。\n\n规则：\n"
                "1. 在文本开头添加风格标签，如 (温柔)、(磁性)、(活泼) 等\n"
                "2. 在文本中间适当位置插入音频标签，如 [深呼吸]、[叹气]、[笑]、[语速加快] 等\n"
                "3. 标签应与文本内容情感一致，不要过度使用，每段最多 2-3 个标签\n"
                "4. 保持原文内容不变，只添加标签\n"
                "5. 直接返回添加标签后的文本，不要添加任何解释\n\n"
                "原文：{text}"
            )
        prompt = prompt_tpl.replace("{text}", text)
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            polished = (resp.completion_text or "").strip()
            if polished:
                logger.info(
                    "MiMO TTS: voice polish applied, %d chars -> %d chars",
                    len(text),
                    len(polished),
                )
                return polished
        except Exception as e:
            logger.warning("MiMO TTS: voice polish failed: %s", e)
        return text

    def _build_prompt(self, uid: str, emotion_override: Optional[str] = None) -> str:
        uset = self._get_user_settings(uid)
        # 全局风格提示词
        style = self.config.style_hint
        return build_system_prompt(
            emotion=emotion_override
            if emotion_override is not None
            else (uset["emotion"] or None),
            speed=uset["speed"],
            pitch=uset["pitch"],
            breath=uset["breath"],
            # 官方 mimo-v2.5-tts 文档对唱歌能力的推荐控制方式，是在待合成文本
            # 开头添加 (唱歌)/(sing)/(singing) 标签。这里避免再额外注入一段
            # “请用唱歌方式演绎”的自然语言提示，减少对音色与风格的二次干扰。
            sing=False,
            stress=uset["stress"],
            laughter=uset["laughter"],
            pause=uset["pause"],
            dialect=uset["dialect"],
            volume=uset["volume"],
            style_hint=style or None,
        )

    @staticmethod
    def _merge_prompt_parts(*parts: Optional[str]) -> str:
        merged: list[str] = []
        for part in parts:
            text = str(part or "").strip().strip("，,")
            if text:
                merged.append(text)
        return "，".join(merged)

    def _build_clone_prompt(self, base_prompt: str) -> str:
        """为 voiceclone 单独追加自然语言风格控制与音频标签控制。"""
        style_prompt = self.config.clone_style_prompt.strip()
        audio_tags = self.config.clone_audio_tags.strip()

        tag_prompt = ""
        if audio_tags:
            normalized_tags = re.sub(r"[，、]+", " ", audio_tags)
            normalized_tags = re.sub(r"\s+", " ", normalized_tags).strip()
            if normalized_tags:
                tag_prompt = f"音频标签：{normalized_tags}"

        return self._merge_prompt_parts(base_prompt, style_prompt, tag_prompt)

    @staticmethod
    def _normalize_tts_mode(mode: Optional[str]) -> str:
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

    def _resolve_tts_mode(self, uid: str) -> str:
        return self._normalize_tts_mode(self._get_user_settings(uid).get("tts_mode"))

    def _resolve_design_description(self, uid: str) -> str:
        """解析 design 模式下应使用的音色描述。"""
        uset = self._get_user_settings(uid)
        current_voice = self._resolve_voice(uset["voice"])
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}

        if str(current_voice_info.get("model", "")).lower() == "voicedesign":
            desc = str(current_voice_info.get("description", "")).strip()
            if desc:
                return desc

        return self.config.design_voice_description.strip()

    def _resolve_synthesis_target(
        self, uid: str, uset: Optional[dict] = None
    ) -> tuple[str, Optional[str], str, Optional[str]]:
        """根据当前输出模式解析最终音色、模型与克隆参考音频。

        Args:
            uid: 用户标识
            uset: 可选的用户设置覆盖字典（来自 _do_tts 的本地修改）。
                  若为 None 则从全局存储读取。
        """
        if uset is None:
            uset = self._get_user_settings(uid)
        mode = self._normalize_tts_mode(uset.get("tts_mode", "default"))
        current_voice = self._resolve_voice(uset["voice"])
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}

        if mode == "clone":
            clone_voice_id = self.config.clone_voice_id.strip()
            if clone_voice_id:
                clone_audio_path = self._voice_manager.get_clone_audio_path(
                    clone_voice_id
                )
                if clone_audio_path:
                    return (
                        clone_voice_id,
                        self.config.clone_model,
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
                        self.config.clone_model,
                        mode,
                        clone_audio_path,
                    )
            raise RuntimeError(
                "当前已切换到“克隆”输出，但未找到可用的本地参考音频。请先执行 /voiceclone <ID> <音频路径>。"
            )

        if mode == "design":
            description = self._resolve_design_description(uid)
            if description:
                # 按官方文档，VoiceDesign 直接使用 user 消息中的描述文本生成目标音色，
                # 并不依赖普通 TTS 的 audio.voice 预置音色参数。
                return "", self.config.design_model, mode, None
            raise RuntimeError(
                "当前已切换到“设计”输出，但未配置 design_voice_description，也未选中带描述的设计音色。"
            )

        # default 模式下若当前选中的是本地登记的 design/clone 音色，
        # 不应静默回退到默认音色，否则会出现“我明明设置了某个音色，实际唱出来/读出来却是另一种声音”。
        custom_model = str(current_voice_info.get("model", "")).lower()
        if custom_model == "voiceclone":
            clone_audio_path = self._voice_manager.get_clone_audio_path(current_voice)
            if clone_audio_path:
                return (
                    current_voice,
                    self.config.clone_model,
                    "clone",
                    clone_audio_path,
                )
            raise RuntimeError(
                f"当前音色 {current_voice} 是克隆音色，但未找到可用参考音频。请重新执行 /voiceclone {current_voice} <音频路径>。"
            )

        if custom_model == "voicedesign":
            description = self._resolve_design_description(uid)
            if description:
                return "", self.config.design_model, "design", None
            raise RuntimeError(
                f"当前音色 {current_voice} 是设计音色，但缺少可用描述文本。请重新执行 /voicegen {current_voice} <描述>。"
            )

        return current_voice, None, mode, None

    @staticmethod
    def _tts_mode_label(mode: str) -> str:
        return {
            "default": "默认",
            "design": "设计",
            "clone": "克隆",
        }.get(mode, "[未知]")

    # ── P1-4: 用户设置 LRU 淘汰 ──
    _MAX_IDLE_USERS = 500

    def _evict_stale_users(self) -> bool:
        """淘汰过多的用户条目，防止长期运行时内存无限增长。返回是否有条目被淘汰。"""
        evicted = False
        for store in (self._user_settings, self._user_format):
            if len(store) > self._MAX_IDLE_USERS:
                excess = len(store) - self._MAX_IDLE_USERS
                for uid in list(store.keys())[:excess]:
                    store.pop(uid, None)
                    evicted = True
        return evicted

    # 最大临时音频总占用 (500 MB)
    _CLEANUP_MAX_TOTAL_BYTES = 500 * 1024 * 1024

    def _cleanup_recent_files(self) -> None:
        """Clean up stale temp audio files and enforce 500 MB disk limit."""
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

        # 总大小保护：按时间排序后从最旧文件开始删除，直到总占用低于阈值
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

    def _resolve_voice(self, voice_id: str) -> str:
        info = self._voice_manager.get_voice(voice_id)
        if info:
            return voice_id
        for v in MIMO_VOICE_LIST:
            if v["id"] == voice_id:
                return voice_id
        return self.config.get("default_voice", "mimo_default")

    def _resolve_clone_audio_path(self, raw_path: str) -> Path:
        """Resolve reference audio path for /voiceclone with path traversal protection."""
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return Path(text)

        raw = Path(text)
        plugin_dir = Path(__file__).parent
        data_clone_dir = self._data_dir / "clone"
        legacy_clone_dir = plugin_dir / "clone"

        # 允许的目录白名单：所有 clone 音频只能存放在这些目录下
        allowed_roots: list[Path] = [
            data_clone_dir,
            legacy_clone_dir,
        ]

        candidates: list[Path] = []

        if raw.is_absolute():
            # 绝对路径：直接检查是否在允许目录内
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

        # 全部候选均不在白名单或不存在时，抛出异常而非返回路径
        raise PermissionError(
            f"路径 {raw_path!r} 解析后不在允许的克隆音频目录范围内。"
            f"请将参考音频放入: {data_clone_dir}"
        )

    @staticmethod
    def _apply_singing_tag(text: str) -> str:
        """Prepend official singing tag if not already present."""
        stripped = text.lstrip()
        if not stripped:
            return text

        # 官方文档建议在目标文本最开头加入 (唱歌)/(sing)/(singing)
        # 若用户已经自行提供，则不重复添加。
        if re.match(r"^[\(\[（](?:唱歌|sing|singing)[\)\]）]", stripped, re.IGNORECASE):
            return stripped
        return f"(唱歌){stripped}"

    @staticmethod
    def _extract_auto_tts_text(chain) -> str:
        """尽量只提取最终回复里首段连续可见文本，避免把后续插件附加内容一并朗读。"""
        chunks: list[str] = []
        started = False

        for comp in chain:
            if isinstance(comp, Record):
                break
            if isinstance(comp, Plain) and comp.text:
                chunks.append(comp.text)
                started = True
                continue
            if started:
                break

        return "".join(chunks).strip()

    @staticmethod
    def _build_audio_only_chain(chain, text: str, audio_component) -> list:
        """构造尽量仅包含语音的消息链，避免自动 TTS 时重复发送大量文字。"""
        new_chain: list = []
        consumed = False

        for comp in chain:
            if isinstance(comp, Record):
                continue
            if not consumed and isinstance(comp, Plain) and comp.text:
                comp_text = str(comp.text)
                if text and text in comp_text:
                    remainder = (comp_text.replace(text, "", 1)).strip()
                    if remainder:
                        new_chain.append(Plain(remainder))
                    consumed = True
                    continue
            new_chain.append(comp)

        new_chain.append(audio_component)
        return new_chain

    @staticmethod
    def _log_tts_text(uid: str, mode: str, sing: bool, text: str) -> None:
        """记录 TTS 入参。"""
        logger.info(
            "[MiMO TTS] synthesize text uid=%s mode=%s sing=%s text=%r",
            uid,
            mode,
            sing,
            text,
        )

    @staticmethod
    def _looks_like_hidden_prompt_or_reasoning(text: str) -> bool:
        """识别明显的人格/skill 内部提示词或推理腔文本，避免被自动 TTS 朗读。

        AstrBot 的 on_decorating_result 运行在 ResultDecorateStage 中，若上游已将
        persona/skill 的内部文本写入首段 Plain，这里拿到的就是“可见消息链”。
        在无法从事件结构中稳定区分“主回复”和“泄漏提示词”的情况下，采用保守
        规则：检测到典型英文自述式提示词/推理前缀时，直接跳过自动朗读。
        """
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return False

        head = normalized[:240].lower()
        suspicious_prefixes = (
            "**considering ",
            "considering ",
            "analysis:",
            "chain of thought",
            "thought:",
            "reasoning:",
            "internal monologue:",
            "system prompt",
            "developer prompt",
            "assistant persona",
            "skill:",
            "persona:",
            "你是谁",
            "你是一个",
            "系统提示",
            "开发者提示",
            "角色设定",
            "response style",
            "i need to ",
            "i should ",
            "let me ",
            "the user wants",
        )
        if head.startswith(suspicious_prefixes):
            return True

        suspicious_phrases = (
            "considering a response style",
            "need to provide a short answer",
            "keeping it formal",
            "using commas instead of periods",
            "without punctuation",
            "i need to provide",
            "i should provide",
            "system prompt",
            "developer message",
            "assistant persona",
            "chain-of-thought",
            "internal reasoning",
            "不要向用户展示",
            "以下是你的设定",
            "技能描述",
            "人格设定",
        )
        matched = sum(1 for phrase in suspicious_phrases if phrase in head)
        if matched >= 3:
            return True

        suspicious_patterns = (
            r"^(?:#|##|###)\s*(?:system|developer|persona|skill|thought|reasoning)",
            r"^[\[【](?:system|developer|persona|skill|内部|推理|思考)[\]】]",
            r"(?:请扮演|你的任务是|你的人设是|必须遵循以下规则)",
            r"(?:do not reveal|hidden prompt|internal use only)",
        )
        return any(
            re.search(pattern, head, re.IGNORECASE) for pattern in suspicious_patterns
        )

    # ── TTS command (reusable for auto TTS too) ──

    async def _do_tts(
        self,
        text: str,
        uid: str,
        format_override: Optional[str] = None,
        emotion_override: Optional[str] = None,
        settings_override: Optional[dict] = None,
    ) -> Optional[Path]:
        """Run TTS and return the audio file path.

        Args:
            emotion_override: 若非 None，优先使用此情感值而非全局 uset，
                用于并发安全地传递自动检测的情感。
            settings_override: 若非 None，临时覆盖 uset 中的对应字段（不修改全局 uset），
                用于 /mimo_say 和 /sing 的并发安全。
        """
        provider = self._ensure_provider()
        if not provider:
            raise RuntimeError("API Key 未配置。请在配置中设置 api_key。")

        uset = self._get_user_settings(uid)
        # 并发安全：如有临时覆盖，创建浅拷贝而非修改全局 uset
        if settings_override:
            uset: dict = {**uset, **settings_override}
        prompt = self._build_prompt(uid, emotion_override=emotion_override)
        requested_fmt = format_override or self._get_effective_audio_format(uid)
        fmt = requested_fmt
        # 唱歌模式：使用 sing_voice_override > 当前用户音色 > 插件配置 sing_voice
        # 优先级说明：当前用户音色高于插件默认 sing_voice，避免 clone/design 音色被覆盖
        sing_voice_override = uset.get("sing_voice_override")
        if uset["sing"] and sing_voice_override:
            current_voice = self._resolve_voice(sing_voice_override)
            uset["voice"] = current_voice
        elif uset["sing"]:
            # 当前用户音色已设置（非默认值）时，保持不变；
            # 仅当用户未自定义音色时，才回退到插件配置的 sing_voice。
            is_custom_voice = uset["voice"] != self.config.default_voice
            if not is_custom_voice:
                sing_voice_cfg = self.config.sing_voice.strip()
                if sing_voice_cfg:
                    current_voice = self._resolve_voice(sing_voice_cfg)
                    uset["voice"] = current_voice
        final_text = self._apply_singing_tag(text) if uset["sing"] else text

        self._log_tts_text(
            uid, uset.get("tts_mode", "default"), uset["sing"], final_text
        )

        voice_id, model_override, mode, clone_audio_path = (
            self._resolve_synthesis_target(uid, uset=uset)
        )
        if mode == "clone":
            prompt = self._build_clone_prompt(prompt)
        elif mode == "design":
            design_description = self._resolve_design_description(uid)
            prompt = self._merge_prompt_parts(design_description, prompt)

        raw = await provider.synthesize(
            text=final_text,
            voice=voice_id or None,
            system_prompt=prompt if prompt else None,
            audio_format=fmt,
            model=model_override,
            clone_audio_path=clone_audio_path,
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

        # Write temp file
        tmp_dir = self._data_dir / "temp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out = tmp_dir / f"mimo_{ts}.{actual_fmt}"
        out.write_bytes(raw)
        self._recent_files.append((time.time(), out))
        self._cleanup_recent_files()
        return out

    async def terminate(self) -> None:
        """插件卸载时关闭底层网络会话，避免 Unclosed client session 警告。"""
        if self._provider is not None:
            try:
                await self._provider.close()
            except Exception:
                pass
            self._provider = None

    # ═══════════════════════════════════════════════════════════
    #  Event Handlers
    # ═══════════════════════════════════════════════════════════

    @filter.on_decorating_result(priority=100)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """Auto TTS: intercept LLM output and generate voice reply."""
        uid, uset = self._get_event_settings(event)

        # ── Step 1: 概率判断（最先执行，不通过则直接跳出，节省资源） ──
        if not self._is_tts_active(uid):
            return

        result = event.get_result()
        chain = result.chain if result and result.chain else None
        if not chain:
            return

        # 仅处理真正的模型主回复，尽量避开其它插件/阶段写入的结果。
        if hasattr(result, "is_llm_result") and callable(result.is_llm_result):
            if not result.is_llm_result():
                return

        if any(isinstance(comp, Record) for comp in chain):
            return

        plain = self._extract_auto_tts_text(chain)
        if self._should_skip(plain):
            return
        if self._looks_like_hidden_prompt_or_reasoning(plain):
            logger.warning(
                "MiMO TTS: skip auto TTS because result looks like leaked persona/skill prompt"
            )
            return

        if plain.startswith("/"):
            return

        # ── Step 2: 文本分段模式 ──
        # 分段模式下用 event.send() 逐段独立发送，不改写 result.chain，
        # 避免与 outputpro 等插件的分段回复冲突。
        # 润色延后到确认要发语音的分段才执行，节省 LLM token。
        # 自然对话流程：首段纯文字快速发送，后续段落语音补充。
        if self.config.enable_segmentation:
            segments = self._split_text(plain)
            if not segments:
                return
            logger.info(
                "MiMO TTS: segmentation enabled, split into %d segments", len(segments)
            )

            prob = self.config.segment_voice_probability
            polish_enabled = self.config.enable_voice_polish

            for i, seg in enumerate(segments):
                if len(seg) < self.config.get("min_text_length"):
                    await event.send(MessageChain().message(seg))
                    continue

                # 首段：短于最小文本长度的纯文字快速发送（模拟"是的"等快速回复）
                # 长文本仍走语音流程，避免长段落无语音
                if i == 0 and len(seg) <= self.config.get("min_text_length"):
                    await event.send(MessageChain().message(seg))
                    continue

                # 后续段落：按概率决定是否语音补充
                if random.random() < prob:
                    tts_seg = seg
                    if polish_enabled:
                        tts_seg = await self._polish_text_with_llm(seg, uid)

                    try:
                        emo_override: Optional[str] = None
                        if not uset["emotion"] or uset["emotion"] == "auto":
                            emo_override = detect_emotion(seg) or None
                        audio_path = await self._do_tts(
                            tts_seg, uid, emotion_override=emo_override
                        )
                        if audio_path:
                            chain_msg = MessageChain()
                            if self._should_send_text_with_tts(uid):
                                chain_msg.message(seg)
                            chain_msg.chain.append(
                                Record.fromFileSystem(str(audio_path))
                            )
                            await event.send(chain_msg)
                        else:
                            await event.send(MessageChain().message(seg))
                    except Exception as e:
                        await event.send(
                            MessageChain().message(f"[TTS 合成失败: {e}]")
                        )
                        await event.send(MessageChain().message(seg))
                else:
                    await event.send(MessageChain().message(seg))

            # 清空 result.chain，阻止原始消息发出
            result.chain = []
            return

        # ── Step 3: 原有逻辑 — 全文单次合成 ──
        # 润色仅在全文合成时执行
        tts_text = plain
        if self.config.enable_voice_polish:
            logger.info("MiMO TTS: voice polish enabled, calling LLM...")
            tts_text = await self._polish_text_with_llm(plain, uid)

        orig_emotion = uset["emotion"]
        emo_override: Optional[str] = None
        if not orig_emotion or orig_emotion == "auto":
            emo_override = detect_emotion(plain) or None

        try:
            audio_path = await self._do_tts(tts_text, uid, emotion_override=emo_override)
            if audio_path:
                audio_comp = Record.fromFileSystem(str(audio_path))
                if self._should_send_text_with_tts(uid):
                    result.chain.append(audio_comp)
                else:
                    result.chain = self._build_audio_only_chain(
                        chain, plain, audio_comp
                    )
        except Exception as e:
            result.chain.append(Plain(f"[TTS 合成失败: {e}]"))

    # ── Command Handlers (delegated to handlers/) ──

    @filter.command("mimo_say")
    async def cmd_mimo_say(self, event: AstrMessageEvent):
        async for item in handle_mimo_say(self, event):
            yield item

    @filter.command("sing")
    async def cmd_sing(self, event: AstrMessageEvent):
        async for item in handle_sing(self, event):
            yield item

    @filter.command("ttsraw")
    async def cmd_ttsraw(self, event: AstrMessageEvent):
        async for item in handle_ttsraw(self, event):
            yield item

    @filter.command("tts_off")
    async def cmd_tts_off(self, event: AstrMessageEvent):
        async for item in handle_tts_off(self, event):
            yield item

    @filter.command("tts_on")
    async def cmd_tts_on(self, event: AstrMessageEvent):
        async for item in handle_tts_on(self, event):
            yield item

    @filter.command("text")
    async def cmd_text(self, event: AstrMessageEvent):
        async for item in handle_text(self, event):
            yield item

    @filter.command("tts_help")
    async def cmd_tts_help(self, event: AstrMessageEvent):
        async for item in handle_tts_help(self, event):
            yield item

    @filter.command("tts_restore")
    async def cmd_tts_restore(self, event: AstrMessageEvent):
        async for item in handle_tts_restore(self, event):
            yield item

    @filter.command("emotion")
    async def cmd_emotion(self, event: AstrMessageEvent):
        async for item in handle_emotion(self, event):
            yield item

    @filter.command("emotions")
    async def cmd_emotions(self, event: AstrMessageEvent):
        async for item in handle_emotions(self, event):
            yield item

    @filter.command("speed")
    async def cmd_speed(self, event: AstrMessageEvent):
        async for item in handle_speed(self, event):
            yield item

    @filter.command("pitch")
    async def cmd_pitch(self, event: AstrMessageEvent):
        async for item in handle_pitch(self, event):
            yield item

    @filter.command("breath")
    async def cmd_breath(self, event: AstrMessageEvent):
        async for item in handle_breath(self, event):
            yield item

    @filter.command("stress")
    async def cmd_stress(self, event: AstrMessageEvent):
        async for item in handle_stress(self, event):
            yield item

    @filter.command("dialect")
    async def cmd_dialect(self, event: AstrMessageEvent):
        async for item in handle_dialect(self, event):
            yield item

    @filter.command("volume")
    async def cmd_volume(self, event: AstrMessageEvent):
        async for item in handle_volume(self, event):
            yield item

    @filter.command("laughter")
    async def cmd_laughter(self, event: AstrMessageEvent):
        async for item in handle_laughter(self, event):
            yield item

    @filter.command("pause")
    async def cmd_pause(self, event: AstrMessageEvent):
        async for item in handle_pause(self, event):
            yield item

    @filter.command("preset")
    async def cmd_preset(self, event: AstrMessageEvent):
        async for item in handle_preset(self, event):
            yield item

    @filter.command("presetlist")
    async def cmd_presetlist(self, event: AstrMessageEvent):
        async for item in handle_presetlist(self, event):
            yield item

    @filter.command("voice")
    async def cmd_voice(self, event: AstrMessageEvent):
        async for item in handle_voice(self, event):
            yield item

    @filter.command("voices")
    async def cmd_voices(self, event: AstrMessageEvent):
        async for item in handle_voices(self, event):
            yield item

    @filter.command("ttsswitch")
    async def cmd_ttsswitch(self, event: AstrMessageEvent):
        async for item in handle_ttsswitch(self, event):
            yield item

    @filter.command("voiceclone")
    async def cmd_voiceclone(self, event: AstrMessageEvent):
        async for item in handle_voiceclone(self, event):
            yield item

    @filter.command("voicegen")
    async def cmd_voicegen(self, event: AstrMessageEvent):
        async for item in handle_voicegen(self, event):
            yield item

    @filter.command("ttsformat")
    async def cmd_ttsformat(self, event: AstrMessageEvent):
        async for item in handle_ttsformat(self, event):
            yield item

    @filter.command("ttsconfig")
    async def cmd_ttsconfig(self, event: AstrMessageEvent):
        async for item in handle_ttsconfig(self, event):
            yield item

    @filter.command("ttsinfo")
    async def cmd_ttsinfo(self, event: AstrMessageEvent):
        async for item in handle_ttsinfo(self, event):
            yield item

    # ── Helpers (private) ──

    @staticmethod
    def _parse_opt(text: str, flag: str) -> tuple[str, str]:
        """Parse -flag value from text. Returns (remaining_text, value).

        支持带引号的值，如 ``-emotion "开心"``。
        """
        m = re.search(rf"{flag}\s+(\S+)", text)
        if m:
            val = m.group(1).strip('"').strip("'")
            return text[: m.start()].strip() + " " + text[m.end() :].strip(), val
        return text, ""

    @staticmethod
    def _parse_cmd(event: AstrMessageEvent, cmd: str) -> str:
        """从消息中提取命令参数部分。"""
        return event.message_str.strip()[len(cmd) :].strip()
