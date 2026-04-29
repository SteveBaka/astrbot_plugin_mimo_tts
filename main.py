# -*- coding: utf-8 -*-
"""
astrbot_plugin_mimo_tts — MiMO TTS Plugin for AstrBot - Enhanced Edition

基于 MiMO-V2.5-TTS 的精细化语音合成插件。
自动拦截 LLM 输出生成语音，支持 20 种情感、语速、音高、呼吸声、
重音、唱歌、方言、音量、笑声、停顿、预设系统等精细化控制。

使用方式：
  - 自动拦截：AI 说话时自动转语音
  - /mimo_say <文本> [选项]：即时语音合成
  - /sing <歌词>：单次唱歌合成
  - /tts_<on/off>：开启或关闭当前对话自动 TTS
  - /text <on/off>：设置当前对话是否同步发送文字
  - /tts_help：快速查看常用指令
  - /tts_restore：将当前会话配置恢复为插件默认设置
  - /ttsswitch <default|design|clone>：切换输出模式
  - /voice [音色名]：查看或切换音色
  - /emotion <情感名|auto|off>：设置情感
  - /speed <0.5~2.0>：设置语速
  - /pitch <-12~+12>：设置音高
  - /breath <on/off>：呼吸声开关
  - /stress <on/off>：重音模式开关
  - /dialect <方言名|off>：设置方言口音
  - /volume <轻声|正常|大声|off>：设置音量
  - /laughter <on/off>：笑声开关
  - /pause <on/off>：停顿开关
  - /preset [预设名]：查看或应用预设
  - /presetlist：列出所有预设
  - /emotions：列出所有情感
  - /voices：列出所有音色
  - /ttsformat <mp3|wav|ogg>：设置音频格式
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.components import Plain, Record

from .core.config import ConfigManager
from .core.constants import (
    AUDIO_MIN_VALID_SIZE,
    AUDIO_VALID_EXTENSIONS,
    MIMO_VOICE_LIST,
    SKIP_PATTERNS,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_EMOTIONS,
    TTS_PRESETS,
)
from .tts.mimo_provider import MiMOProvider
from .tts.prompt_builder import build_system_prompt, detect_emotion
from .voice.voice_manager import VoiceManager


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
            audio_format=self.config.get("audio_format", "mp3"),
            timeout=self.config.get("timeout", 60),
            max_retries=self.config.get("max_retries", 3),
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
            self._save_user_state()

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
                # 唱歌模式仅允许由 /sing 命令临时触发，避免污染普通即时合成与自动 TTS。
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

        return "mp3"

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

    def _should_tts(self, uid: str) -> bool:
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
        if len(t) < self.config.get("min_text_length", 1):
            return True
        if len(t) > self.config.get("max_text_length", 5000):
            return True
        for pat in SKIP_PATTERNS:
            if re.search(pat, t):
                return True
        return False

    def _build_prompt(self, uid: str) -> str:
        uset = self._get_user_settings(uid)
        # 全局风格提示词
        style = self.config.style_hint
        return build_system_prompt(
            emotion=uset["emotion"] or None,
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
        self, uid: str
    ) -> tuple[str, Optional[str], str, Optional[str]]:
        """根据当前输出模式解析最终音色、模型与克隆参考音频。"""
        uset = self._get_user_settings(uid)
        mode = self._resolve_tts_mode(uid)
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
        }.get(mode, "默认")

    # 最大临时音频总占用 (500 MB)
    _CLEANUP_MAX_TOTAL_BYTES = 500 * 1024 * 1024

    def _cleanup_recent_files(self) -> None:
        """清理过期和无效的临时音频文件，防止磁盘空间泄漏。

        1. 超过 2 小时的文件直接从磁盘删除。
        2. 存活但体积过小（< 100 字节，通常为损坏/空文件）的也删除。
        3. 若剩余存活文件的总大小超过 500 MB，按"最旧优先"继续删除，
           直到总占用降至限制以下。
        4. 最终重建列表，仅保留未被删除的存活文件。
        """
        now = time.time()
        kept: list[tuple[float, Path]] = []
        for t, p in self._recent_files:
            try:
                if not p.exists():
                    continue
                expired = (now - t) >= 2 * 3600
                too_small = p.stat().st_size < 100
                if expired or too_small:
                    p.unlink(missing_ok=True)
                else:
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
        """解析 /voiceclone 使用的参考音频路径（带路径穿越防护）。

        支持：
        1. 相对 AstrBot data/plugin_data/<plugin_name>/clone 的路径（推荐）
        2. 相对插件根目录 clone/ 的路径（兼容旧行为）
        3. 相对当前工作目录的路径
        4. 绝对路径（限制在允许的目录范围内）

        安全策略：解析后的路径必须位于 ``_ALLOWED_CLONE_ROOTS`` 允许的目录树内，
        否则抛出 PermissionError，防止通过 ../../ 访问或窃取任意文件。
        """
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
            Path.cwd(),
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
                    Path.cwd() / raw,
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
        """为唱歌模式补齐官方建议的起始 tag。"""
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
            "你是",
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
        if matched >= 2:
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
    ) -> Optional[Path]:
        """Run TTS and return the audio file path."""
        provider = self._ensure_provider()
        if not provider:
            raise RuntimeError("API Key 未配置。请在配置中设置 api_key。")

        prompt = self._build_prompt(uid)
        uset = self._get_user_settings(uid)
        requested_fmt = format_override or self._get_effective_audio_format(uid)
        # AstrBot 的 Record 组件在当前版本下对 RIFF/WAV 兼容性最稳定，
        # 因此这里统一向上游请求 wav，避免 mp3/ogg/pcm 落地后再次被按 RIFF 解析时报错。
        fmt = "wav"
        # 唱歌模式：使用 sing_voice_override > 插件配置 sing_voice > 当前用户音色
        sing_voice_override = uset.get("sing_voice_override")
        if uset["sing"] and sing_voice_override:
            current_voice = self._resolve_voice(sing_voice_override)
            uset["voice"] = current_voice
        elif uset["sing"]:
            sing_voice_cfg = self.config.sing_voice.strip()
            if sing_voice_cfg:
                current_voice = self._resolve_voice(sing_voice_cfg)
                uset["voice"] = current_voice
        final_text = self._apply_singing_tag(text) if uset["sing"] else text

        self._log_tts_text(uid, self._resolve_tts_mode(uid), uset["sing"], final_text)

        voice_id, model_override, mode, clone_audio_path = (
            self._resolve_synthesis_target(uid)
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
        if actual_fmt != "wav":
            logger.warning(
                "MiMO TTS: Record 输出期望 wav，但接口返回了 %s（用户原设置=%s）",
                actual_fmt,
                requested_fmt,
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

    async def on_unload(self) -> None:
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

        if not self._should_tts(uid):
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

        # If emotion is auto, detect from text
        orig_emotion = uset["emotion"]
        if not orig_emotion or orig_emotion == "auto":
            detected = detect_emotion(plain)
            if detected:
                uset["emotion"] = detected

        try:
            audio_path = await self._do_tts(plain, uid)
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
        finally:
            uset["emotion"] = orig_emotion

    async def _handle_say_command(self, event: AstrMessageEvent, command_name: str):
        """
        /mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]
                        [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]
        """
        raw = str(event.message_str or "").strip()
        first, sep, remainder = raw.partition(" ")
        normalized_first = first.lstrip("/").split("@", 1)[0].strip().lower()
        if normalized_first == command_name.lower():
            text = remainder.strip()
        else:
            text = re.sub(
                rf"^/?{re.escape(command_name)}(?:@[^\s]+)?\s*",
                "",
                raw,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
        if not text:
            yield MessageEventResult().message(
                "用法: /mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色] [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]"
            )
            return

        uid, uset = self._get_event_settings(event)

        # Parse inline options
        text, emo = self._parse_opt(text, "-emotion")
        text, spd = self._parse_opt(text, "-speed")
        text, ptc = self._parse_opt(text, "-pitch")
        text, voi = self._parse_opt(text, "-voice")
        text, brt = self._parse_opt(text, "-breath")
        text, sts = self._parse_opt(text, "-stress")
        text, dia = self._parse_opt(text, "-dialect")
        text, vol = self._parse_opt(text, "-volume")
        text = text.strip()

        if not text:
            yield MessageEventResult().message("文本内容不能为空。")
            return

        # Save originals and apply overrides
        orig = dict(uset)
        if emo:
            if emo == "auto":
                detected = detect_emotion(text)
                uset["emotion"] = detected or ""
            elif emo == "off":
                uset["emotion"] = ""
            else:
                uset["emotion"] = emo
        if spd:
            uset["speed"] = max(0.5, min(2.0, float(spd)))
        if ptc:
            uset["pitch"] = max(-12, min(12, int(ptc)))
        if voi:
            uset["voice"] = self._resolve_voice(voi)
        if brt:
            uset["breath"] = brt == "on"
        if sts:
            uset["stress"] = sts == "on"
        if dia:
            uset["dialect"] = "" if dia == "off" else dia
        if vol:
            uset["volume"] = "" if vol == "off" else vol

        try:
            audio_path = await self._do_tts(text, uid)
            if audio_path:
                r = MessageEventResult()
                r.chain.append(Record.fromFileSystem(str(audio_path)))
                yield r
            else:
                yield MessageEventResult().message("TTS 合成失败。")
        except Exception as e:
            yield MessageEventResult().message(f"! {e}")
        finally:
            uset.update(orig)

    @filter.command("mimo_say")
    async def cmd_mimo_say(self, event: AstrMessageEvent):
        async for item in self._handle_say_command(event, "mimo_say"):
            yield item

    @filter.command("tts_off")
    async def cmd_tts_off(self, event: AstrMessageEvent):
        """/tts_off — 关闭当前对话自动 TTS"""
        _, uset = self._get_event_settings(event)
        uset["tts_enabled"] = False
        self._persist_current_state()
        yield MessageEventResult().message(
            "[✓] 已关闭当前对话的自动 TTS。\n如需重新开启，可使用 /tts_on"
        )

    @filter.command("tts_on")
    async def cmd_tts_on(self, event: AstrMessageEvent):
        """/tts_on — 开启当前对话自动 TTS"""
        _, uset = self._get_event_settings(event)
        uset["tts_enabled"] = True
        self._persist_current_state()
        yield MessageEventResult().message(
            "[✓] 已开启当前对话的自动 TTS。\n"
            "仅恢复当前对话的自动朗读，不会修改插件配置面板中的全局自动 TTS 开关。"
        )

    @filter.command("text")
    async def cmd_text(self, event: AstrMessageEvent):
        """/text [on|off] — 设置当前对话自动 TTS 是否同步发送文字"""
        raw = event.message_str.strip()
        arg = raw[len("/text") :].strip().lower()
        _, uset = self._get_event_settings(event)

        if not arg:
            current = uset.get("text_enabled", None)
            current_state = (
                self.config.send_text_with_tts if current is None else bool(current)
            )
            source = "当前对话" if current is not None else "插件全局默认"
            yield MessageEventResult().message(
                f"当前对话文字同步: {'开' if current_state else '关'}\n"
                f"当前生效来源: {source}\n"
                "用法: /text <on|off>"
            )
            return

        if arg not in ("on", "off"):
            yield MessageEventResult().message("用法: /text <on|off>")
            return

        uset["text_enabled"] = arg == "on"
        self._persist_current_state()
        yield MessageEventResult().message(
            f"[✓] 已将当前对话的文字同步设置为: {'开' if uset['text_enabled'] else '关'}\n"
            "仅影响当前聊天的自动 TTS，不会修改插件配置面板中的 send_text_with_tts。"
        )

    @filter.command("tts_help")
    async def cmd_tts_help(self, event: AstrMessageEvent):
        """/tts_help — 快速查看常用 TTS 指令"""
        lines = [
            "MiMO TTS 常用指令:",
            "",
            "/mimo_say <文本>  - 即时合成语音",
            "/sing [-音色名] <歌词>  - 单次唱歌合成（可选指定音色）",
            "/ttsconfig  - 查看当前会话配置",
            "/tts_restore  - 将当前会话配置恢复为插件默认设置",
            "/tts_<on/off>  - 开启或关闭当前对话自动 TTS",
            "/text <on|off>  - 设置当前对话是否同步发送文字",
            "/ttsswitch <default|design|clone>  - 切换输出模式",
            "/voice [音色ID]  - 查看/切换音色",
            "/emotion <情感名|auto|off>  - 设置情感",
            "/ttsformat <mp3|wav|ogg>  - 设置当前格式",
        ]
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("tts_restore")
    async def cmd_tts_restore(self, event: AstrMessageEvent):
        """/tts_restore — 恢复当前会话配置为插件默认值"""
        uid, _ = self._get_event_settings(event)
        self._restore_user_state(uid)
        yield MessageEventResult().message(
            "[✓] 已将当前对话的 TTS 配置恢复为插件默认设置。\n"
            "可使用 /ttsconfig 查看当前生效结果，或用 /tts_help 快速查看常用指令。"
        )

    @filter.command("sing")
    async def cmd_sing(self, event: AstrMessageEvent):
        """/sing [-音色名] <歌词>"""
        raw = event.message_str.strip()
        text = raw[len("/sing") :].strip()
        if not text:
            yield MessageEventResult().message(
                "用法: /sing <歌词>（单次触发，执行后自动恢复原设置）\n"
                "     /sing -冰糖 <歌词> — 使用冰糖音色唱歌"
            )
            return

        uid, _ = self._get_event_settings(event)
        uset = self._get_user_settings(uid)
        orig = uset.copy()
        uset["sing"] = True

        # 支持 -音色名 格式：/sing -冰糖 歌词
        if text.startswith("-") and len(text) > 1:
            parts = text[1:].split(maxsplit=1)
            candidate = parts[0].strip() if parts else ""
            if candidate:
                uset["sing_voice_override"] = candidate
                text = parts[1].strip() if len(parts) > 1 else ""
                logger.debug(
                    f"[MimoTTSPlugin] uid={uid} cmd_sing sing_voice_override={candidate}"
                )

        if not text:
            uset["sing"] = False
            uset.pop("sing_voice_override", None)
            yield MessageEventResult().message(
                "用法: /sing <歌词>（单次触发，执行后自动恢复原设置）\n"
                "     /sing -冰糖 <歌词> — 使用冰糖音色唱歌"
            )
            return

        try:
            audio_path = await self._do_tts(text, uid)
            if audio_path:
                r = MessageEventResult()
                r.chain.append(Record.fromFileSystem(str(audio_path)))
                yield r
            else:
                yield MessageEventResult().message("唱歌合成失败。")
        except Exception as e:
            yield MessageEventResult().message(f"! {e}")
        finally:
            uset.update(orig)

    @filter.command("voice")
    async def cmd_voice(self, event: AstrMessageEvent):
        """/voice [音色名]"""
        raw = event.message_str.strip()
        arg = raw[len("/voice") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            lines = [f"当前音色: {uset['voice']}", "", "内置音色:"]
            for v in MIMO_VOICE_LIST:
                lines.append(
                    f"  {v['id']:10s} {v['name']}  ({v['gender']}声 {v['style']})"
                )
            lines.append("")
            lines.append("用法: /voice <音色ID>")
            yield MessageEventResult().message("\n".join(lines))
            return

        resolved = self._resolve_voice(arg)
        self._get_user_settings(uid)["voice"] = resolved
        self._persist_current_state()
        yield MessageEventResult().message(f"[u2713] 音色已切换为: {resolved}")

    @filter.command("ttsswitch")
    async def cmd_ttsswitch(self, event: AstrMessageEvent):
        """/ttsswitch [default|design|clone] — 切换 TTS 输出来源模式"""
        raw = event.message_str.strip()
        arg = raw[len("/ttsswitch") :].strip()
        uid, uset = self._get_event_settings(event)

        if not arg:
            mode = self._resolve_tts_mode(uid)
            lines = [
                f"当前输出模式: {self._tts_mode_label(mode)} ({mode})",
                f"配置默认模式: {self._tts_mode_label(self._normalize_tts_mode(self.config.tts_output_mode))}",
                f"默认音色: {self.config.default_voice}",
                f"设计音色ID: {self.config.design_voice_id or '(未配置)'}",
                f"克隆音色ID: {self.config.clone_voice_id or '(未配置)'}",
                "",
                "用法: /ttsswitch <default|design|clone>",
                "也支持中文: /ttsswitch 默认 /设计 /克隆",
            ]
            yield MessageEventResult().message("\n".join(lines))
            return

        mode = self._normalize_tts_mode(arg)
        uset["tts_mode"] = mode
        self._persist_current_state()
        yield MessageEventResult().message(
            f"[✓] TTS 输出模式已切换为: {self._tts_mode_label(mode)} ({mode})"
        )

    @filter.command("emotion")
    async def cmd_emotion(self, event: AstrMessageEvent):
        """/emotion [情感名|auto|off]"""
        raw = event.message_str.strip()
        arg = raw[len("/emotion") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            cur = uset["emotion"] or "(自动检测)"
            lines = [f"当前情感: {cur}", "", "支持的情感:"]
            for emo in SUPPORTED_EMOTIONS:
                lines.append(f"  {emo}")
            lines.append("")
            lines.append("用法: /emotion <情感名|auto|off>")
            yield MessageEventResult().message("\n".join(lines))
            return

        if arg == "off":
            self._get_user_settings(uid)["emotion"] = ""
            self._persist_current_state()
            yield MessageEventResult().message("[u2713] 已关闭情感覆盖（自动检测）")
        elif arg == "auto":
            self._get_user_settings(uid)["emotion"] = "auto"
            self._persist_current_state()
            yield MessageEventResult().message("[u2713] 已开启情感自动检测")
        elif arg in SUPPORTED_EMOTIONS:
            self._get_user_settings(uid)["emotion"] = arg
            self._persist_current_state()
            yield MessageEventResult().message(f"[u2713] 情感已设置为: {arg}")
        else:
            yield MessageEventResult().message(
                f"[X] 不支持的情感: {arg}\n可用: {', '.join(SUPPORTED_EMOTIONS)}"
            )

    @filter.command("emotions")
    async def cmd_emotions(self, event: AstrMessageEvent):
        """List all supported emotions."""
        lines = ["支持的情感列表:", ""]
        for emo in SUPPORTED_EMOTIONS:
            lines.append(f"  • {emo}")
        lines.append(f"\n共 {len(SUPPORTED_EMOTIONS)} 种")
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("speed")
    async def cmd_speed(self, event: AstrMessageEvent):
        """/speed [0.5~2.0]"""
        raw = event.message_str.strip()
        arg = raw[len("/speed") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            yield MessageEventResult().message(
                f"当前语速: {uset['speed']}\n用法: /speed <0.5~2.0>"
            )
            return

        try:
            val = max(0.5, min(2.0, float(arg)))
            self._get_user_settings(uid)["speed"] = val
            self._persist_current_state()
            yield MessageEventResult().message(f"[u2713] 语速已设置为: {val}")
        except ValueError:
            yield MessageEventResult().message("[X] 请输入 0.5~2.0 之间的数值。")

    @filter.command("pitch")
    async def cmd_pitch(self, event: AstrMessageEvent):
        """/pitch [-12~+12]"""
        raw = event.message_str.strip()
        arg = raw[len("/pitch") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            yield MessageEventResult().message(
                f"当前音高: {uset['pitch']}\n用法: /pitch <-12~+12>"
            )
            return

        try:
            val = max(-12, min(12, int(arg)))
            self._get_user_settings(uid)["pitch"] = val
            self._persist_current_state()
            yield MessageEventResult().message(f"[u2713] 音高已设置为: {val}")
        except ValueError:
            yield MessageEventResult().message("[X] 请输入 -12~+12 之间的整数。")

    @filter.command("breath")
    async def cmd_breath(self, event: AstrMessageEvent):
        """/breath [on|off]"""
        raw = event.message_str.strip()
        arg = raw[len("/breath") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["breath"] else "关"
            yield MessageEventResult().message(
                f"呼吸声: {state}\n用法: /breath <on|off>"
            )
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["breath"] = val
        self._persist_current_state()
        yield MessageEventResult().message(
            f"[u2713] 呼吸声已{'开启' if val else '关闭'}"
        )

    @filter.command("stress")
    async def cmd_stress(self, event: AstrMessageEvent):
        """/stress [on|off]"""
        raw = event.message_str.strip()
        arg = raw[len("/stress") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["stress"] else "关"
            yield MessageEventResult().message(
                f"重音模式: {state}\n用法: /stress <on|off>"
            )
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["stress"] = val
        self._persist_current_state()
        yield MessageEventResult().message(
            f"[u2713] 重音模式已{'开启' if val else '关闭'}"
        )

    @filter.command("dialect")
    async def cmd_dialect(self, event: AstrMessageEvent):
        """/dialect [方言名|off] — 设置方言口音，如 四川话、粤语、东北话"""
        raw = event.message_str.strip()
        arg = raw[len("/dialect") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            cur = uset["dialect"] or "(无)"
            yield MessageEventResult().message(
                f"当前方言: {cur}\n"
                "用法: /dialect <方言名|off>\n"
                "示例: /dialect 四川话、/dialect 粤语、/dialect 东北话、/dialect 台湾腔"
            )
            return

        if arg == "off":
            self._get_user_settings(uid)["dialect"] = ""
            self._persist_current_state()
            yield MessageEventResult().message("[u2713] 已关闭方言口音")
        else:
            self._get_user_settings(uid)["dialect"] = arg
            self._persist_current_state()
            yield MessageEventResult().message(f"[u2713] 方言已设置为: {arg}")

    @filter.command("volume")
    async def cmd_volume(self, event: AstrMessageEvent):
        """/volume [轻声|正常|大声|off]"""
        raw = event.message_str.strip()
        arg = raw[len("/volume") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            cur = uset["volume"] or "(正常)"
            yield MessageEventResult().message(
                f"当前音量: {cur}\n用法: /volume <轻声|正常|大声|off>"
            )
            return

        if arg == "off":
            self._get_user_settings(uid)["volume"] = ""
            self._persist_current_state()
            yield MessageEventResult().message("[u2713] 音量已恢复为正常")
        else:
            self._get_user_settings(uid)["volume"] = arg
            self._persist_current_state()
            yield MessageEventResult().message(f"[u2713] 音量已设置为: {arg}")

    @filter.command("laughter")
    async def cmd_laughter(self, event: AstrMessageEvent):
        """/laughter [on|off] — 允许自然笑声"""
        raw = event.message_str.strip()
        arg = raw[len("/laughter") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["laughter"] else "关"
            yield MessageEventResult().message(
                f"笑声: {state}\n用法: /laughter <on|off>"
            )
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["laughter"] = val
        self._persist_current_state()
        yield MessageEventResult().message(f"[u2713] 笑声已{'开启' if val else '关闭'}")

    @filter.command("pause")
    async def cmd_pause(self, event: AstrMessageEvent):
        """/pause [on|off] — 增加句间停顿"""
        raw = event.message_str.strip()
        arg = raw[len("/pause") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["pause"] else "关"
            yield MessageEventResult().message(
                f"停顿模式: {state}\n用法: /pause <on|off>"
            )
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["pause"] = val
        self._persist_current_state()
        yield MessageEventResult().message(
            f"[u2713] 停顿模式已{'开启' if val else '关闭'}"
        )

    @filter.command("preset")
    async def cmd_preset(self, event: AstrMessageEvent):
        """/preset [预设名] — 查看/应用预设"""
        raw = event.message_str.strip()
        arg = raw[len("/preset") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            lines = ["预设列表:", ""]
            for name, p in TTS_PRESETS.items():
                lines.append(
                    f"  {name:18s}  情感={p['emotion']:10s}  语速={p['speed']}  音高={p['pitch']:+d}  音色={p['voice']}"
                )
            lines.append("")
            lines.append("用法: /preset <预设名>  （如 /preset bedtime_story）")
            yield MessageEventResult().message("\n".join(lines))
            return

        if arg not in TTS_PRESETS:
            yield MessageEventResult().message(
                f"[X] 未知预设: {arg}\n用 /presetlist 查看所有预设"
            )
            return

        preset = TTS_PRESETS[arg]
        uset = self._get_user_settings(uid)
        uset["emotion"] = preset["emotion"]
        uset["speed"] = preset["speed"]
        uset["pitch"] = preset["pitch"]
        uset["breath"] = preset["breath"]
        uset["stress"] = preset["stress"]
        uset["voice"] = self._resolve_voice(preset["voice"])
        self._persist_current_state()

        yield MessageEventResult().message(
            f"[u2713] 已应用预设: {arg}\n"
            f"  情感={preset['emotion']}  语速={preset['speed']}  音高={preset['pitch']:+d}\n"
            f"  呼吸={'开' if preset['breath'] else '关'}  重音={'开' if preset['stress'] else '关'}  音色={preset['voice']}"
        )

    @filter.command("presetlist")
    async def cmd_presetlist(self, event: AstrMessageEvent):
        """List all TTS presets."""
        lines = ["所有预设:", ""]
        for name, p in TTS_PRESETS.items():
            lines.append(f"  {name}")
            lines.append(
                f"    情感={p['emotion']}  语速={p['speed']}  音高={p['pitch']:+d}  音色={p['voice']}  呼吸={'✓' if p['breath'] else '✗'}  重音={'✓' if p['stress'] else '✗'}"
            )
        lines.append("\n用法: /preset <预设名> 应用预设")
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("voices")
    async def cmd_voices(self, event: AstrMessageEvent):
        """List all built-in voices."""
        lines = ["MiMO 内置音色:", ""]
        for v in MIMO_VOICE_LIST:
            lines.append(
                f"  {v['id']:10s} {v['name']}  ({v['gender']}声 · {v['style']})"
            )
        lines.append(f"\n共 {len(MIMO_VOICE_LIST)} 种  |  用法: /voice <音色ID>")
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("voiceclone")
    async def cmd_voiceclone(self, event: AstrMessageEvent):
        """/voiceclone <ID> <音频路径> — 克隆参考音频的声音"""
        raw = event.message_str.strip()
        arg = raw[len("/voiceclone") :].strip()
        if not arg:
            yield MessageEventResult().message(
                "用法: /voiceclone <ID> <参考音频路径>\n"
                "示例1: /voiceclone my_clone /path/to/sample.wav\n"
                "示例2: /voiceclone my_clone clone/sample.wav\n"
                f"说明: 推荐将参考音频放到 AstrBot 数据目录下: {self._data_dir / 'clone'}"
            )
            return

        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            yield MessageEventResult().message(
                "用法: /voiceclone <ID> <参考音频路径>\n"
                "例如: /voiceclone my_clone clone/sample.wav"
            )
            return

        vid, audio_path = parts[0], parts[1]
        audio_file = self._resolve_clone_audio_path(audio_path)

        if not audio_file.exists():
            plugin_audio_dir = self._data_dir / "clone"
            yield MessageEventResult().message(
                f"[X] 音频文件不存在: {audio_path}\n"
                f"可将参考音频放到 AstrBot 数据目录下: {plugin_audio_dir}\n"
                f"然后使用: /voiceclone {vid} clone/文件名"
            )
            return

        if not audio_file.is_file():
            yield MessageEventResult().message(f"[X] 不是有效文件: {audio_path}")
            return

        if audio_file.suffix.lower() not in AUDIO_VALID_EXTENSIONS:
            yield MessageEventResult().message(
                f"[X] 不支持的音频格式: {audio_file.suffix or '(无后缀)'}\n"
                f"支持: {', '.join(AUDIO_VALID_EXTENSIONS)}"
            )
            return

        if audio_file.stat().st_size < AUDIO_MIN_VALID_SIZE:
            yield MessageEventResult().message(
                f"[X] 音频文件过小，无法用于克隆（至少 {AUDIO_MIN_VALID_SIZE} 字节）"
            )
            return

        provider = self._ensure_provider()
        if not provider:
            yield MessageEventResult().message("API Key 未配置。")
            return

        yield MessageEventResult().message("⏳ 正在登记克隆参考音频…")

        ok = await provider.register_voice(vid, str(audio_file))
        if ok:
            self._voice_manager.register_voice(
                vid, name=vid, model="voiceclone", audio_path=str(audio_file)
            )
            # 同步到配置面板（config 直接引用原始字典，修改会被 AstrBot 持久化）
            self.config.set("clone_enabled", True)
            self.config.set("clone_voice_id", vid)
            uid, _ = self._get_event_settings(event)
            self._get_user_settings(uid)["voice"] = vid
            self._persist_current_state()
            yield MessageEventResult().message(
                f"[✓] 已登记克隆音色: {vid}\n"
                f"  参考音频: {audio_file}\n"
                f"  已自动切换当前音色为: {vid}\n"
                f"  可用 /ttsswitch clone 切到克隆输出模式"
            )
        else:
            yield MessageEventResult().message(
                f"[X] 克隆参考音频登记失败：{provider.last_error or '请查看日志。'}"
            )

    @filter.command("voicegen")
    async def cmd_voicegen(self, event: AstrMessageEvent):
        """/voicegen <ID> <描述文本> — 用文字描述生成全新音色"""
        raw = event.message_str.strip()
        arg = raw[len("/voicegen") :].strip()
        if not arg:
            yield MessageEventResult().message(
                "用法: /voicegen <ID> <音色描述>\n"
                '示例: /voicegen my_voice "温柔甜美的年轻女声，语速适中"'
            )
            return

        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            yield MessageEventResult().message("用法: /voicegen <ID> <音色描述>")
            return

        vid, desc = parts[0], parts[1]

        provider = self._ensure_provider()
        if not provider:
            yield MessageEventResult().message("API Key 未配置。")
            return

        yield MessageEventResult().message("⏳ 正在登记设计音色描述…")

        ok = await provider.design_voice(vid, desc, model=self.config.design_model)
        if ok:
            self._voice_manager.register_voice(
                vid, name=vid, model="voicedesign", description=desc
            )
            # 仅同步可展示的配置项；design_voice_id 改为内部状态，避免出现在插件设置面板。
            self.config.set("design_enabled", True)
            self.config.design_voice_id = vid
            self.config.set("design_voice_description", desc)
            uid, _ = self._get_event_settings(event)
            self._get_user_settings(uid)["voice"] = vid
            self._persist_current_state()
            yield MessageEventResult().message(
                f"[✓] 已登记设计音色: {vid}\n"
                f"  可用 /ttsswitch design 切换到设计模式\n"
                f"  也可用 /voice {vid} 将这条描述设为当前设计音色\n"
                f"  配置面板已同步更新描述信息"
            )
        else:
            yield MessageEventResult().message(
                f"[X] 设计音色登记失败：{provider.last_error or '请查看日志。'}"
            )

    @filter.command("voiceclonelist")
    async def cmd_voiceclonelist(self, event: AstrMessageEvent):
        voices = self._voice_manager.list_voices()
        if not voices:
            yield MessageEventResult().message("暂无已注册的自定义音色。")
            return
        lines = ["已注册的自定义音色:", ""]
        for v in voices:
            extra = ""
            if v.get("model") == "voiceclone" and v.get("audio_path"):
                extra = f"  -> {v.get('audio_path')}"
            elif v.get("model") == "voicedesign" and v.get("description"):
                extra = f"  -> {v.get('description')}"
            lines.append(
                f"  {v['voice_id']:20s}  {v.get('name', '')}  [{v.get('model', '')}]{extra}"
            )
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("ttsformat")
    async def cmd_ttsformat(self, event: AstrMessageEvent):
        """/ttsformat [mp3|wav|ogg] — 设置音频输出格式"""
        raw = event.message_str.strip()
        arg = raw[len("/ttsformat") :].strip()
        uid, _ = self._get_event_settings(event)

        if not arg:
            cur = self._get_effective_audio_format(uid)
            source = "当前对话" if uid in self._user_format else "插件全局默认"
            yield MessageEventResult().message(
                f"当前格式: {cur}\n"
                f"当前生效来源: {source}\n"
                f"支持的格式: {', '.join(SUPPORTED_AUDIO_FORMATS)}\n"
                f"用法: /ttsformat <格式>"
            )
            return

        if arg.lower() not in SUPPORTED_AUDIO_FORMATS:
            yield MessageEventResult().message(
                f"[X] 不支持的格式: {arg}\n支持: {', '.join(SUPPORTED_AUDIO_FORMATS)}"
            )
            return

        self._user_format[uid] = arg.lower()
        self._persist_current_state()
        yield MessageEventResult().message(f"[u2713] 音频格式已设置为: {arg}")

    @filter.command("ttsconfig")
    async def cmd_ttsconfig(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        arg = raw[len("/ttsconfig") :].strip()

        if arg == "reset":
            self._reset_persistent_state()
            yield MessageEventResult().message("[u2713] 所有个人设置已重置。")
            return

        provider = self._ensure_provider()
        status = "[u2713] 正常" if provider else "[X] 未配置"

        uid, _ = self._get_event_settings(event)
        uset = self._get_user_settings(uid)

        lines = [
            f"MiMO TTS 配置状态: {status}",
            f"模型: {self.config.get('model', 'mimo-v2.5-tts')}",
            f"API: {self.config.get('api_base_url', 'https://api.xiaomimimo.com/v1')[:80]}",
            f"持久化文件: {self._state_file}",
            "",
            "── 你的当前设置 ──",
            f"情感: {uset['emotion'] or '(自动)'}",
            f"语速: {uset['speed']}  音高: {uset['pitch']:+d}",
            f"呼吸: {'开' if uset['breath'] else '关'}  重音: {'开' if uset['stress'] else '关'}",
            f"方言: {uset['dialect'] or '(无)'}  音量: {uset['volume'] or '(正常)'}",
            f"笑声: {'开' if uset['laughter'] else '关'}  停顿: {'开' if uset['pause'] else '关'}",
            f"当前对话自动 TTS: {'开' if uset.get('tts_enabled', True) else '关'}",
            f"当前对话文字同步: {'开' if self._should_send_text_with_tts(uid) else '关'}",
            f"音色: {uset['voice']}",
            f"输出模式: {self._tts_mode_label(self._resolve_tts_mode(uid))} ({self._resolve_tts_mode(uid)})",
            f"格式: {self._get_effective_audio_format(uid)}",
            "",
            "用 /preset <预设名> 快速切换风格",
            "用 /tts_help 快速查看指令",
        ]
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("ttsraw")
    async def cmd_ttsraw(self, event: AstrMessageEvent):
        """/ttsraw <文本> — 不带情感的纯文本合成"""
        raw = event.message_str.strip()
        text = raw[len("/ttsraw") :].strip()
        if not text:
            yield MessageEventResult().message("用法: /ttsraw <文本>")
            return
        uid, _ = self._get_event_settings(event)
        try:
            provider = self._ensure_provider()
            if not provider:
                raise RuntimeError("API Key 未配置。")

            fmt = "wav"
            raw_audio = await provider.synthesize(text=text, audio_format=fmt)
            if not raw_audio:
                raise RuntimeError(provider.last_error or "TTS 合成失败。")

            actual_fmt = str(provider.last_output_format or fmt or "mp3").lower()

            tmp_dir = self._data_dir / "temp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            out = tmp_dir / f"mimo_raw_{int(time.time() * 1000)}.{actual_fmt}"
            out.write_bytes(raw_audio)
            self._recent_files.append((time.time(), out))
            self._cleanup_recent_files()

            r = MessageEventResult()
            r.chain.append(Record.fromFileSystem(str(out)))
            yield r
        except Exception as e:
            yield MessageEventResult().message(f"! {e}")

    @filter.command("ttsinfo")
    async def cmd_ttsinfo(self, event: AstrMessageEvent):
        """/ttsinfo — 查看插件信息"""
        lines = [
            "astrbot_plugin_mimo_tts v1.2.3",
            "",
            "基于 MiMO-V2.5-TTS 的精细化语音合成插件",
            "",
            f"支持情感: {len(SUPPORTED_EMOTIONS)} 种",
            f"内置音色: {len(MIMO_VOICE_LIST)} 种",
            f"内置预设: {len(TTS_PRESETS)} 个",
            "控制维度: 情感 语速 音高 呼吸声 重音 方言 音量 笑声 停顿（唱歌仅 /sing）",
            "",
            "主要命令:",
            "  /mimo_say <文本>  - 即时合成",
            "  /tts_off  - 关闭当前对话自动 TTS",
            "  /text on|off  - 切换当前对话文字同步",
            "  /sing <歌词>  - 唱歌模式",
            "  /preset <名>  - 应用预设",
            "  /ttsconfig  - 查看配置",
        ]
        yield MessageEventResult().message("\n".join(lines))

    # ── Helpers (private) ──

    @staticmethod
    def _parse_opt(text: str, flag: str) -> tuple[str, str]:
        """Parse -flag value from text. Returns (remaining_text, value)."""
        m = re.search(rf"{flag}\s+(\S+)", text)
        if m:
            return text[: m.start()].strip() + " " + text[m.end() :].strip(), m.group(1)
        return text, ""
