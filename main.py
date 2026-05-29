# -*- coding: utf-8 -*-

from __future__ import annotations

import random
import re
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
    SEGMENT_PATTERNS,
)
from .core.text_utils import (
    should_skip,
    split_text,
    strip_audio_tags,
    extract_auto_tts_text,
    build_audio_only_chain,
    looks_like_hidden_prompt_or_reasoning,
)
from .core.user_state import UserStateManager
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
from .tts.synthesis import TTSSynthesizer, normalize_tts_mode, tts_mode_label
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
        self._plugin_dir = Path(__file__).resolve().parent
        self._data_dir = Path(StarTools.get_data_dir())

        # ── Core modules ──
        self._voice_manager = VoiceManager(data_dir=self._data_dir)
        self.user_state = UserStateManager(self._data_dir, self.config)
        self.synth = TTSSynthesizer(self.config, self._voice_manager, self._data_dir)

        # ── Plugin logger (WebUI log page) ──
        from .core.plugin_logger import PluginLogger
        self.plog = PluginLogger(self._data_dir, config_ref=self.config)
        self.plog.cleanup_old_logs()

        self.user_state.load()

        # ── Register Web API for Voice Studio page ──
        self._register_web_apis(context)

    def _register_web_apis(self, context: Context):
        """Register REST API endpoints for the Voice Studio WebUI page."""
        p = "astrbot_plugin_mimo_tts"

        context.register_web_api(f"/{p}/config", self._api_get_config, ["GET"], "获取插件配置")
        context.register_web_api(f"/{p}/config/update", self._api_update_config, ["POST"], "更新插件配置")
        context.register_web_api(f"/{p}/tts", self._api_tts_synthesize, ["POST"], "TTS 语音合成")
        context.register_web_api(f"/{p}/voices", self._api_list_voices, ["GET"], "获取音色列表")
        context.register_web_api(f"/{p}/voices/clone-init", self._api_clone_init, ["POST"], "初始化克隆")
        context.register_web_api(f"/{p}/voices/clone-file", self._api_clone_file, ["POST"], "上传克隆音频")
        context.register_web_api(f"/{p}/voices/design", self._api_design_voice, ["POST"], "注册设计音色")
        context.register_web_api(f"/{p}/voices/delete", self._api_delete_voice, ["POST"], "删除音色")
        context.register_web_api(f"/{p}/sessions", self._api_list_sessions, ["GET"], "获取会话配置列表")
        context.register_web_api(f"/{p}/sessions/update", self._api_update_session, ["POST"], "更新会话配置")
        context.register_web_api(f"/{p}/sessions/delete", self._api_delete_session, ["POST"], "删除会话配置")
        context.register_web_api(f"/{p}/sessions/reset", self._api_reset_session, ["POST"], "重置会话配置")
        context.register_web_api(f"/{p}/emotions", self._api_list_emotions, ["GET"], "获取情感列表")
        context.register_web_api(f"/{p}/constants", self._api_get_constants, ["GET"], "获取常量数据")
        context.register_web_api(f"/{p}/health", self._api_health, ["GET"], "健康检查")
        context.register_web_api(f"/{p}/logs", self._api_get_logs, ["GET"], "获取插件日志")
        context.register_web_api(f"/{p}/logs/stats", self._api_log_stats, ["GET"], "日志统计")

    # ── Proxy methods for handler compatibility ──

    @property
    def _user_settings(self) -> dict[str, dict]:
        return self.user_state.user_settings

    @property
    def _user_format(self) -> dict[str, str]:
        return self.user_state.user_format

    @property
    def _recent_files(self) -> list[tuple[float, Path]]:
        return self.user_state.recent_files

    @property
    def _voice_manager_ref(self) -> VoiceManager:
        return self._voice_manager

    @property
    def _state_file(self) -> Path:
        return self.user_state._state_file

    def _get_user_settings(self, uid: str) -> dict:
        return self.user_state.get_settings(uid, normalize_tts_mode)

    def _get_event_settings(self, event: AstrMessageEvent) -> tuple[str, dict]:
        return self.user_state.get_event_settings(event, normalize_tts_mode)

    def _should_send_text_with_tts(self, uid: str) -> bool:
        return self.user_state.should_send_text_with_tts(uid, normalize_tts_mode)

    def _get_effective_audio_format(self, uid: str) -> str:
        return self.user_state.get_effective_audio_format(uid)

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

    def _resolve_voice(self, voice_id: str) -> str:
        return self.synth.resolve_voice(voice_id)

    def _normalize_tts_mode(self, mode: Optional[str]) -> str:
        return normalize_tts_mode(mode)

    def _resolve_tts_mode(self, uid: str) -> str:
        return normalize_tts_mode(self._get_user_settings(uid).get("tts_mode"))

    def _tts_mode_label(self, mode: str) -> str:
        return tts_mode_label(mode)

    def _ensure_provider(self):
        return self.synth.ensure_provider()

    def _persist_current_state(self) -> None:
        self.user_state.persist()

    def _restore_user_state(self, uid: str) -> None:
        self.user_state.restore(uid)

    def _reset_persistent_state(self) -> None:
        self.user_state.reset_all()

    def _resolve_clone_audio_path(self, raw_path: str) -> Path:
        return self.synth.resolve_clone_audio_path(raw_path)

    def _split_text(self, text: str) -> list[str]:
        return split_text(
            text,
            self.config.segment_pattern,
            SEGMENT_PATTERNS,
            self.config.segment_max_count,
        )

    def _should_skip(self, text: str) -> bool:
        return should_skip(
            text,
            self.config.get("min_text_length"),
            self.config.get("max_text_length"),
            SKIP_PATTERNS,
        )

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

    async def _do_tts(
        self,
        text: str,
        uid: str,
        format_override: Optional[str] = None,
        emotion_override: Optional[str] = None,
        settings_override: Optional[dict] = None,
    ) -> Optional[Path]:
        """Run TTS and return the audio file path."""
        self.plog.info("TTS", f"合成开始 uid={uid} len={len(text)}")
        try:
            audio_path = await self.synth.do_tts(
                text=text,
                uid=uid,
                get_user_settings=self._get_user_settings,
                get_effective_audio_format=self._get_effective_audio_format,
                format_override=format_override,
                emotion_override=emotion_override,
                settings_override=settings_override,
            )
        except Exception as e:
            self.plog.error("TTS", f"合成失败: {e}")
            raise
        if audio_path:
            size_kb = round(audio_path.stat().st_size / 1024, 1)
            self.plog.info("TTS", f"合成完成 {size_kb}KB → {audio_path.name}")
            self.user_state.recent_files.append((time.time(), audio_path))
            self.user_state.cleanup_recent_files()
        return audio_path

    async def terminate(self) -> None:
        """Clean up resources when unloaded."""
        self.plog.info("Lifecycle", "插件卸载，清理资源")
        await self.synth.close_provider()

    # ═══════════════════════════════════════════════════════════
    #  Web API for Voice Studio Page
    # ═══════════════════════════════════════════════════════════

    async def _api_health(self):
        from quart import jsonify
        return jsonify({"status": "ok", "version": _read_plugin_version()})

    async def _api_get_config(self):
        from quart import jsonify
        return jsonify({"config": dict(self.config._flat)})

    async def _api_update_config(self):
        from quart import jsonify, request
        body = await request.json
        allowed_keys = set(self.config._SCHEMA_DEFAULTS.keys())
        for k, v in body.items():
            if k in allowed_keys:
                self.config.set(k, v)
        return jsonify({"status": "ok"})

    async def _api_tts_synthesize(self):
        from quart import jsonify, request
        import base64
        body = await request.json
        text = str(body.get("text", ""))[:5000]
        if not text.strip():
            return jsonify({"error": "文本不能为空"}), 400

        uid = str(body.get("uid", "webui"))[:100]
        self.plog.info("WebUI-TTS", f"合成请求 uid={uid} len={len(text)} polish={body.get('voice_polish', False)}")

        # LLM 润色（仅当请求中明确启用时）
        if body.get("voice_polish"):
            text = await self._polish_text_with_llm(text, uid)

        overrides = {}
        for key in ("emotion", "speed", "pitch", "voice", "breath", "stress",
                     "laughter", "pause", "dialect", "volume", "tts_mode"):
            if key in body and body[key] is not None:
                overrides[key] = body[key]

        emotion_override = None
        if "emotion" in overrides:
            if overrides["emotion"] == "auto":
                emotion_override = None
            elif overrides["emotion"] == "off":
                overrides["emotion"] = ""
            else:
                emotion_override = overrides.pop("emotion")

        try:
            audio_path = await self._do_tts(
                text, uid, emotion_override=emotion_override,
                settings_override=overrides or None,
            )
            if audio_path:
                audio_bytes = audio_path.read_bytes()
                b64 = base64.b64encode(audio_bytes).decode()
                fmt = audio_path.suffix.lstrip(".")
                mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg"}.get(fmt, "audio/wav")
                return jsonify({"audio_b64": b64, "format": fmt, "mime": mime})
            return jsonify({"error": "合成失败"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    async def _api_list_voices(self):
        from quart import jsonify
        from .core.constants import MIMO_VOICE_LIST
        builtin = [{**v, "type": "default"} for v in MIMO_VOICE_LIST]
        registered = self._voice_manager.list_voices()
        custom = []
        for v in registered:
            model = v.get("model", "voiceclone")
            vtype = "design" if model == "voicedesign" else "clone"
            custom.append({
                "id": v.get("voice_id", ""),
                "name": v.get("name", ""),
                "type": vtype,
            })
        return jsonify({
            "builtin": builtin,
            "registered": custom,
            "all": builtin + custom,
        })

    async def _api_clone_init(self):
        from quart import jsonify, request
        import re as _re
        body = await request.json
        voice_id = body.get("voice_id", "").strip()
        voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", voice_id)
        if not voice_id:
            return jsonify({"error": "缺少 voice_id"}), 400
        self._pending_clone_voice_id = voice_id
        return jsonify({"status": "ok"})

    async def _api_clone_file(self):
        from quart import jsonify, request
        import base64
        import re as _re
        voice_id = getattr(self, "_pending_clone_voice_id", "")
        if not voice_id:
            return jsonify({"error": "请先调用 clone-init"}), 400
        voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", voice_id)
        if not voice_id:
            return jsonify({"error": "无效的 voice_id"}), 400
        body = await request.json
        file_b64 = body.get("file_b64", "")
        filename = body.get("filename", "audio.wav")
        if not file_b64:
            return jsonify({"error": "缺少音频数据"}), 400
        if len(file_b64) > 20 * 1024 * 1024:
            return jsonify({"error": "文件过大（最大约 15MB）"}), 400
        suffix = Path(filename).suffix.lower()
        if suffix not in (".mp3", ".wav"):
            return jsonify({"error": "仅支持 mp3/wav 格式"}), 400
        clone_dir = self._data_dir / "clone"
        clone_dir.mkdir(parents=True, exist_ok=True)
        save_path = clone_dir / f"{voice_id}{suffix}"
        audio_bytes = base64.b64decode(file_b64)
        save_path.write_bytes(audio_bytes)
        self._voice_manager.register_voice(
            voice_id, name=voice_id, model="voiceclone", audio_path=str(save_path),
        )
        self._pending_clone_voice_id = ""
        return jsonify({"status": "ok", "voice_id": voice_id, "path": str(save_path)})

    async def _api_design_voice(self):
        from quart import jsonify, request
        import re as _re
        body = await request.json
        voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("voice_id", "").strip())
        description = body.get("description", "").strip()[:500]
        name = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("name", voice_id).strip())[:50]
        if not voice_id or not description:
            return jsonify({"error": "缺少 voice_id 或描述"}), 400
        self._voice_manager.register_voice(
            voice_id, name=name, model="voicedesign", description=description,
        )
        return jsonify({"status": "ok", "voice_id": voice_id})

    async def _api_delete_voice(self):
        from quart import jsonify, request
        body = await request.json
        voice_id = body.get("voice_id", "")
        if not voice_id:
            return jsonify({"error": "缺少 voice_id"}), 400
        ok = self._voice_manager.remove_voice(voice_id)
        if ok:
            return jsonify({"status": "ok"})
        return jsonify({"error": f"未找到音色: {voice_id}"}), 404

    async def _api_list_sessions(self):
        from quart import jsonify
        sessions = {}
        for uid, settings in self.user_state.user_settings.items():
            sessions[uid] = {
                "settings": settings,
                "format": self.user_state.user_format.get(uid, "wav"),
                "umo": self.user_state.user_umo.get(uid, ""),
            }
        return jsonify({"sessions": sessions})

    async def _api_update_session(self):
        from quart import jsonify, request
        body = await request.json
        uid = body.get("uid", "")
        settings = body.get("settings", {})
        if not uid:
            return jsonify({"error": "缺少 uid"}), 400
        allowed = {"voice", "emotion", "speed", "pitch", "tts_mode", "tts_enabled", "text_enabled",
                    "enable_segmentation", "enable_voice_polish"}
        filtered = {k: v for k, v in settings.items() if k in allowed}
        uset = self.user_state.get_settings(uid, normalize_tts_mode)
        uset.update(filtered)
        self.user_state.persist()
        return jsonify({"status": "ok"})

    async def _api_delete_session(self):
        from quart import jsonify, request
        body = await request.json
        uid = body.get("uid", "")
        if not uid:
            return jsonify({"error": "缺少 uid"}), 400
        self.user_state.user_settings.pop(uid, None)
        self.user_state.user_format.pop(uid, None)
        self.user_state.persist()
        return jsonify({"status": "ok"})

    async def _api_reset_session(self):
        from quart import jsonify, request
        body = await request.json
        uid = body.get("uid", "")
        if not uid:
            return jsonify({"error": "缺少 uid"}), 400
        self.user_state.restore(uid)
        return jsonify({"status": "ok"})

    async def _api_list_emotions(self):
        from quart import jsonify
        from .core.constants import SUPPORTED_EMOTIONS
        return jsonify({"emotions": list(SUPPORTED_EMOTIONS)})

    async def _api_get_constants(self):
        from quart import jsonify
        from .core.constants import MIMO_VOICE_LIST, SUPPORTED_EMOTIONS, SUPPORTED_AUDIO_FORMATS
        return jsonify({
            "voices": MIMO_VOICE_LIST,
            "emotions": list(SUPPORTED_EMOTIONS),
            "formats": list(SUPPORTED_AUDIO_FORMATS),
        })

    async def _api_get_logs(self):
        from quart import jsonify, request
        args = request.args
        limit = min(int(args.get("limit", 200)), 500)
        level = args.get("level")
        logs = self.plog.read_logs(limit=limit, level=level)
        return jsonify({"logs": logs, "enabled": self.plog.enabled})

    async def _api_log_stats(self):
        from quart import jsonify
        return jsonify(self.plog.get_stats())

    # ═══════════════════════════════════════════════════════════
    #  Event Handlers
    # ═══════════════════════════════════════════════════════════

    @filter.on_decorating_result(priority=100)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """回复消息前拦截 LLM 输出，自动生成语音回复。支持文本分段、LLM 音色润色、概率触发。"""
        uid, uset = self._get_event_settings(event)

        # ── Step 1: 概率判断（最先执行，不通过则直接跳出，节省资源） ──
        if not self._is_tts_active(uid):
            return

        result = event.get_result()
        chain = result.chain if result and result.chain else None
        if not chain:
            return

        if hasattr(result, "is_llm_result") and callable(result.is_llm_result):
            if not result.is_llm_result():
                return

        if any(isinstance(comp, Record) for comp in chain):
            return

        plain = extract_auto_tts_text(chain)
        if self._should_skip(plain):
            return
        if looks_like_hidden_prompt_or_reasoning(plain):
            logger.warning(
                "MiMO TTS: skip auto TTS because result looks like leaked persona/skill prompt"
            )
            return

        if plain.startswith("/"):
            return

        # ── Step 2: 文本分段模式 ──
        if uset.get("enable_segmentation", self.config.enable_segmentation):
            segments = self._split_text(plain)
            if not segments:
                return
            logger.info(
                "MiMO TTS: segmentation enabled, split into %d segments", len(segments)
            )
            self.plog.info("Segmentation", f"分段触发 uid={uid} 段数={len(segments)} prob={self.config.segment_voice_probability}")

            prob = self.config.segment_voice_probability
            polish_enabled = uset.get("enable_voice_polish", self.config.enable_voice_polish)

            for i, seg in enumerate(segments):
                if len(seg) < self.config.get("min_text_length"):
                    await event.send(MessageChain().message(seg))
                    continue

                if i == 0 and len(seg) <= self.config.get("min_text_length"):
                    await event.send(MessageChain().message(seg))
                    continue

                if random.random() < prob:
                    tts_seg = seg
                    if polish_enabled:
                        tts_seg = await self._polish_text_with_llm(seg, uid)

                    try:
                        emo_override: Optional[str] = None
                        if not uset["emotion"] or uset["emotion"] == "auto":
                            from .emotion.emotion_detector import detect_emotion
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

            result.chain = []
            return

        # ── Step 3: 原有逻辑 — 全文单次合成 ──
        tts_text = plain
        if uset.get("enable_voice_polish", self.config.enable_voice_polish):
            logger.info("MiMO TTS: voice polish enabled, calling LLM...")
            self.plog.info("Polish", f"LLM 润色触发 uid={uid}")
            tts_text = await self._polish_text_with_llm(plain, uid)

        orig_emotion = uset["emotion"]
        emo_override: Optional[str] = None
        if not orig_emotion or orig_emotion == "auto":
            from .emotion.emotion_detector import detect_emotion
            emo_override = detect_emotion(plain) or None

        try:
            audio_path = await self._do_tts(tts_text, uid, emotion_override=emo_override)
            if audio_path:
                audio_comp = Record.fromFileSystem(str(audio_path))
                if self._should_send_text_with_tts(uid):
                    result.chain.append(audio_comp)
                else:
                    result.chain = build_audio_only_chain(
                        chain, plain, audio_comp
                    )
        except Exception as e:
            result.chain.append(Plain(f"[TTS 合成失败: {e}]"))

    # ── Command Handlers (delegated to handlers/) ──

    @filter.command("mimo_say")
    async def cmd_mimo_say(self, event: AstrMessageEvent):
        """即时合成语音 /mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]"""
        async for item in handle_mimo_say(self, event):
            yield item

    @filter.command("sing")
    async def cmd_sing(self, event: AstrMessageEvent):
        """唱歌模式 /sing [-音色名] <歌词>"""
        async for item in handle_sing(self, event):
            yield item

    @filter.command("ttsraw")
    async def cmd_ttsraw(self, event: AstrMessageEvent):
        """纯文本合成（不带情感） /ttsraw <文本>"""
        async for item in handle_ttsraw(self, event):
            yield item

    @filter.command("tts_off")
    async def cmd_tts_off(self, event: AstrMessageEvent):
        """关闭当前对话自动 TTS"""
        async for item in handle_tts_off(self, event):
            yield item

    @filter.command("tts_on")
    async def cmd_tts_on(self, event: AstrMessageEvent):
        """开启当前对话自动 TTS"""
        async for item in handle_tts_on(self, event):
            yield item

    @filter.command("text")
    async def cmd_text(self, event: AstrMessageEvent):
        """控制自动 TTS 是否同步发送文字 /text <on|off>"""
        async for item in handle_text(self, event):
            yield item

    @filter.command("tts_help")
    async def cmd_tts_help(self, event: AstrMessageEvent):
        """快速查看常用 TTS 指令"""
        async for item in handle_tts_help(self, event):
            yield item

    @filter.command("tts_restore")
    async def cmd_tts_restore(self, event: AstrMessageEvent):
        """将当前对话配置恢复为插件默认设置"""
        async for item in handle_tts_restore(self, event):
            yield item

    @filter.command("emotion")
    async def cmd_emotion(self, event: AstrMessageEvent):
        """设置情感 /emotion <情感名|auto|off>"""
        async for item in handle_emotion(self, event):
            yield item

    @filter.command("emotions")
    async def cmd_emotions(self, event: AstrMessageEvent):
        """列出所有支持的情感"""
        async for item in handle_emotions(self, event):
            yield item

    @filter.command("speed")
    async def cmd_speed(self, event: AstrMessageEvent):
        """设置语速 /speed <0.5~2.0>"""
        async for item in handle_speed(self, event):
            yield item

    @filter.command("pitch")
    async def cmd_pitch(self, event: AstrMessageEvent):
        """设置音高 /pitch <-12~+12>"""
        async for item in handle_pitch(self, event):
            yield item

    @filter.command("breath")
    async def cmd_breath(self, event: AstrMessageEvent):
        """开关呼吸声 /breath <on|off>"""
        async for item in handle_breath(self, event):
            yield item

    @filter.command("stress")
    async def cmd_stress(self, event: AstrMessageEvent):
        """开关重音模式 /stress <on|off>"""
        async for item in handle_stress(self, event):
            yield item

    @filter.command("dialect")
    async def cmd_dialect(self, event: AstrMessageEvent):
        """设置方言口音 /dialect <方言名|off>"""
        async for item in handle_dialect(self, event):
            yield item

    @filter.command("volume")
    async def cmd_volume(self, event: AstrMessageEvent):
        """设置音量 /volume <轻声|正常|大声|off>"""
        async for item in handle_volume(self, event):
            yield item

    @filter.command("laughter")
    async def cmd_laughter(self, event: AstrMessageEvent):
        """开关笑声 /laughter <on|off>"""
        async for item in handle_laughter(self, event):
            yield item

    @filter.command("pause")
    async def cmd_pause(self, event: AstrMessageEvent):
        """开关停顿模式 /pause <on|off>"""
        async for item in handle_pause(self, event):
            yield item

    @filter.command("preset")
    async def cmd_preset(self, event: AstrMessageEvent):
        """查看/应用预设 /preset [预设名]"""
        async for item in handle_preset(self, event):
            yield item

    @filter.command("presetlist")
    async def cmd_presetlist(self, event: AstrMessageEvent):
        """列出所有预设"""
        async for item in handle_presetlist(self, event):
            yield item

    @filter.command("voice")
    async def cmd_voice(self, event: AstrMessageEvent):
        """查看/切换音色 /voice [音色ID]"""
        async for item in handle_voice(self, event):
            yield item

    @filter.command("voices")
    async def cmd_voices(self, event: AstrMessageEvent):
        """列出所有内置音色"""
        async for item in handle_voices(self, event):
            yield item

    @filter.command("ttsswitch")
    async def cmd_ttsswitch(self, event: AstrMessageEvent):
        """切换 TTS 输出模式 /ttsswitch <default|design|clone>"""
        async for item in handle_ttsswitch(self, event):
            yield item

    @filter.command("voiceclone")
    async def cmd_voiceclone(self, event: AstrMessageEvent):
        """声音克隆 /voiceclone <ID> <音频路径> 或 /voiceclone <音色名> 切换"""
        async for item in handle_voiceclone(self, event):
            yield item

    @filter.command("voicegen")
    async def cmd_voicegen(self, event: AstrMessageEvent):
        """声音设计 /voicegen <ID> <描述文本>"""
        async for item in handle_voicegen(self, event):
            yield item

    @filter.command("ttsformat")
    async def cmd_ttsformat(self, event: AstrMessageEvent):
        """设置音频输出格式 /ttsformat <mp3|wav|ogg>"""
        async for item in handle_ttsformat(self, event):
            yield item

    @filter.command("ttsconfig")
    async def cmd_ttsconfig(self, event: AstrMessageEvent):
        """查看当前会话 TTS 配置"""
        async for item in handle_ttsconfig(self, event):
            yield item

    @filter.command("ttsinfo")
    async def cmd_ttsinfo(self, event: AstrMessageEvent):
        """查看插件版本与功能信息"""
        async for item in handle_ttsinfo(self, event):
            yield item

    # ── Helpers (private) ──

    @staticmethod
    def _parse_opt(text: str, flag: str) -> tuple[str, str]:
        """Parse -flag value from text. Returns (remaining_text, value)."""
        m = re.search(rf"{flag}\s+(\S+)", text)
        if m:
            val = m.group(1).strip('"').strip("'")
            return text[: m.start()].strip() + " " + text[m.end() :].strip(), val
        return text, ""

    @staticmethod
    def _parse_cmd(event: AstrMessageEvent, cmd: str) -> str:
        """从消息中提取命令参数部分。"""
        return event.message_str.strip()[len(cmd) :].strip()
