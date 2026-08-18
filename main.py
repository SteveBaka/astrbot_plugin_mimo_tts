# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from functools import partial
import random
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.message_components import Plain, Record

from .core.config import (
    _SING_STYLES_PRESET_V1,
    _SING_STYLES_PRESET_V2,
    ConfigManager,
    SING_STYLES_PRESET,
)
from .core.constants import SEGMENT_PATTERNS, SKIP_PATTERNS
from .core.text_utils import (
    should_skip,
    split_text,
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
from .handlers.singstyle import (
    handle_singstyle_list,
    handle_singstyle_reset,
    handle_singstyle_set,
    handle_singstyle_show,
)
from .handlers.nl_sing import handle_nl_sing, handle_nl_sing_tool
from .handlers.settings import handle_ttsconfig, handle_ttsformat, handle_ttsinfo
from .handlers.tts import handle_mimo_say, handle_sing, handle_ttsraw
from .handlers.voice import (
    handle_ttsswitch,
    handle_voice,
    handle_voiceclone,
    handle_voicegen,
    handle_voices,
)
from .tts.sing import polish_lyrics_with_llm
from .tts.synthesis import TTSSynthesizer, normalize_tts_mode, tts_mode_label
from .voice.voice_manager import VoiceManager
from .webapi import (
    api_clone_file,
    api_clone_init,
    api_clone_style,
    api_clone_style_pool,
    api_delete_session,
    api_delete_voice,
    api_design_style_pool,
    api_design_voice,
    api_get_config,
    api_get_constants,
    api_get_logs,
    api_health,
    api_list_emotions,
    api_list_sessions,
    api_list_voices,
    api_log_stats,
    api_reset_session,
    api_tts_synthesize,
    api_update_config,
    api_update_session,
)


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
        # 风格库预设迁移：空值（[]/空串）补预设；旧版预设（无 speed/pitch）
        # 升级为新预设（AstrBot 只对缺失键填默认值，已保存值需自行迁移）
        raw_styles = str(self.config.get("sing_styles") or "").strip()
        if (
            raw_styles in ("", "[]")
            or raw_styles == _SING_STYLES_PRESET_V1.strip()
            or raw_styles == _SING_STYLES_PRESET_V2.strip()
        ):
            self.config.set("sing_styles", SING_STYLES_PRESET)
            save_cfg = getattr(config, "save_config", None)
            if callable(save_cfg):
                try:
                    save_cfg()
                    logger.info("MiMO TTS: sing_styles preset migrated/upgraded")
                except Exception:
                    logger.warning("MiMO TTS: sing_styles preset migration not persisted")
        self._plugin_dir = Path(__file__).resolve().parent
        self._data_dir = Path(StarTools.get_data_dir())

        # ── Core modules ──
        self._voice_manager = VoiceManager(data_dir=self._data_dir)
        self.user_state = UserStateManager(self._data_dir, self.config)
        self.synth = TTSSynthesizer(self.config, self._voice_manager, self._data_dir)
        # 歌词润色回调注入：所有唱歌入口（命令/WebUI/NL）共用同一润色链路
        self.synth.lyrics_polisher = partial(polish_lyrics_with_llm, self)
        # 自然语言唱歌：会话级冷却时间戳
        self._nl_sing_last: dict[str, float] = {}

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

        context.register_web_api(f"/{p}/config", partial(api_get_config, self), ["GET"], "获取插件配置")
        context.register_web_api(f"/{p}/config/update", partial(api_update_config, self), ["POST"], "更新插件配置")
        context.register_web_api(f"/{p}/tts", partial(api_tts_synthesize, self), ["POST"], "TTS 语音合成")
        context.register_web_api(f"/{p}/voices", partial(api_list_voices, self), ["GET"], "获取音色列表")
        context.register_web_api(f"/{p}/voices/clone-init", partial(api_clone_init, self), ["POST"], "初始化克隆")
        context.register_web_api(f"/{p}/voices/clone-file", partial(api_clone_file, self), ["POST"], "上传克隆音频")
        context.register_web_api(f"/{p}/voices/design", partial(api_design_voice, self), ["POST"], "注册设计音色")
        context.register_web_api(f"/{p}/voices/clone-style", partial(api_clone_style, self), ["POST"], "保存克隆音色风格")
        context.register_web_api(f"/{p}/voices/clone-style-pool", partial(api_clone_style_pool, self), ["GET"], "克隆音色风格控制池")
        context.register_web_api(f"/{p}/voices/design-style-pool", partial(api_design_style_pool, self), ["GET"], "设计音色风格控制池")
        context.register_web_api(f"/{p}/voices/delete", partial(api_delete_voice, self), ["POST"], "删除音色")
        context.register_web_api(f"/{p}/sessions", partial(api_list_sessions, self), ["GET"], "获取会话配置列表")
        context.register_web_api(f"/{p}/sessions/update", partial(api_update_session, self), ["POST"], "更新会话配置")
        context.register_web_api(f"/{p}/sessions/delete", partial(api_delete_session, self), ["POST"], "删除会话配置")
        context.register_web_api(f"/{p}/sessions/reset", partial(api_reset_session, self), ["POST"], "重置会话配置")
        context.register_web_api(f"/{p}/emotions", partial(api_list_emotions, self), ["GET"], "获取情感列表")
        context.register_web_api(f"/{p}/constants", partial(api_get_constants, self), ["GET"], "获取常量数据")
        context.register_web_api(f"/{p}/health", partial(api_health, self), ["GET"], "健康检查")
        context.register_web_api(f"/{p}/logs", partial(api_get_logs, self), ["GET"], "获取插件日志")
        context.register_web_api(f"/{p}/logs/stats", partial(api_log_stats, self), ["GET"], "日志统计")

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

    def _should_send_text_async(self, uid: str) -> bool:
        return self.user_state.should_send_text_async(uid, normalize_tts_mode)

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
                "你是一个专业的语音润色专家。请在以下文本中适当添加 MiMO TTS 音频标签，"
                "让播报更自然生动。\n"
                "规则：\n"
                "1. 整体气质用开头风格标签表达，如 (温柔)、(磁性)、(活泼)、(严肃) 等，只加 1 个\n"
                "2. 关键语气处插入音频标签增强表现力，如 [深呼吸]、[叹气]、[轻笑]、[停顿]、"
                "[语速加快]、[语速放慢] 等\n"
                "3. 标签与文本情感一致、宁缺毋滥：整段最多 2-3 个音频标签\n"
                "4. 保持原文内容完全不变，只增删标签\n"
                "5. 不要添加任何解释、代码围栏或思考过程，第一行即润色结果\n\n"
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

    async def _send_tts_audio_background(
        self, event: AstrMessageEvent, text: str, uid: str, polish_enabled: bool = False
    ) -> None:
        """后台执行润色+TTS合成并发送音频（用于文字先发、语音后发场景）。"""
        try:
            tts_text = text
            if polish_enabled:
                logger.info("MiMO TTS: voice polish in background, calling LLM...")
                self.plog.info("Polish", f"LLM 润色触发 uid={uid}")
                tts_text = await self._polish_text_with_llm(text, uid)

            emo_override: Optional[str] = None
            if not self.user_state.get_settings(uid, normalize_tts_mode).get("emotion") or \
               self.user_state.get_settings(uid, normalize_tts_mode).get("emotion") == "auto":
                from .emotion.emotion_detector import detect_emotion
                emo_override = detect_emotion(text) or None

            audio_path = await self._do_tts(tts_text, uid, emotion_override=emo_override)
            if audio_path:
                audio_comp = Record.fromFileSystem(str(audio_path))
                chain_msg = MessageChain()
                chain_msg.chain.append(audio_comp)
                await event.send(chain_msg)
        except Exception as e:
            logger.warning("MiMO TTS: background TTS failed: %s", e)
            self.plog.error("TTS", f"后台合成失败: {e}")

    async def terminate(self) -> None:
        """Clean up resources when unloaded."""
        self.plog.info("Lifecycle", "插件卸载，清理资源")
        await self.synth.close_provider()

    # Web API 处理器已模块化至 webapi.py（注册见 _register_web_apis）

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
        polish_enabled = uset.get("enable_voice_polish", self.config.enable_voice_polish)
        tts_text = plain

        if self._should_send_text_with_tts(uid):
            if self._should_send_text_async(uid):
                await event.send(MessageChain().message(plain))
                result.chain = []
                asyncio.create_task(
                    self._send_tts_audio_background(event, plain, uid, polish_enabled)
                )
            else:
                if polish_enabled:
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
                        result.chain.append(audio_comp)
                except Exception as e:
                    result.chain.append(Plain(f"[TTS 合成失败: {e}]"))
        else:
            if polish_enabled:
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
                    result.chain = build_audio_only_chain(
                        chain, plain, audio_comp
                    )
            except Exception as e:
                result.chain.append(Plain(f"[TTS 合成失败: {e}]"))

    @filter.event_message_type(filter.EventMessageType.ALL, priority=99)
    async def on_nl_sing(self, event: AstrMessageEvent):
        """自然语言触发唱歌（快路径）：唤醒消息匹配「用X的声线唱<歌词>」等句式时直接演唱。"""
        await handle_nl_sing(self, event)

    @filter.llm_tool(name="mimo_sing_song")
    async def mimo_sing_song(self, event: AstrMessageEvent, style: str, lyrics: str):
        """用指定歌声风格演唱一段歌词。仅在用户明确要求"唱歌/唱一段/用XX声线唱"时调用，歌词必须一字不改。

        Args:
            style(string): 唱歌风格组或音色名称（如"小雪"、"茉莉"），用户未指定时传空字符串；自由风格词（如"温柔甜美"）也可传入
            lyrics(string): 歌词原文，一字不改
        """
        return await handle_nl_sing_tool(self, event, style, lyrics)

    # ── Command Handlers (delegated to handlers/) ──

    # ── Public commands (no permission required) ──

    @filter.command("mimo_say")
    async def cmd_mimo_say(self, event: AstrMessageEvent):
        """即时合成语音 /mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]"""
        async for item in handle_mimo_say(self, event):
            yield item

    @filter.command("sing")
    async def cmd_sing(self, event: AstrMessageEvent):
        """唱歌模式 /sing [-音色名] [-s 风格组] [-p 提示词] <歌词>，支持 (风格) 括号简写"""
        async for item in handle_sing(self, event):
            yield item

    @filter.command_group("singstyle")
    def singstyle(self):
        """唱歌风格组管理（/singstyle show|list|set|reset，管理类命令）"""

    @singstyle.command("show")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def singstyle_show(self, event: AstrMessageEvent):
        """查看当前对话的唱歌风格设置"""
        async for item in handle_singstyle_show(self, event):
            yield item

    @singstyle.command("list")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def singstyle_list(self, event: AstrMessageEvent):
        """列出全部可用的唱歌风格组"""
        async for item in handle_singstyle_list(self, event):
            yield item

    @singstyle.command("set")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def singstyle_set(self, event: AstrMessageEvent):
        """切换当前对话的唱歌风格组 /singstyle set <组名>"""
        async for item in handle_singstyle_set(self, event):
            yield item

    @singstyle.command("reset")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def singstyle_reset(self, event: AstrMessageEvent):
        """恢复当前对话跟随全局唱歌风格"""
        async for item in handle_singstyle_reset(self, event):
            yield item

    @filter.command("ttsinfo")
    async def cmd_ttsinfo(self, event: AstrMessageEvent):
        """查看插件版本与功能信息"""
        async for item in handle_ttsinfo(self, event):
            yield item

    # ── Admin commands (requires AstrBot admin permission) ──

    @filter.command("ttsraw")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_ttsraw(self, event: AstrMessageEvent):
        """纯文本合成（不带情感） /ttsraw <文本>"""
        async for item in handle_ttsraw(self, event):
            yield item

    @filter.command("tts_off")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tts_off(self, event: AstrMessageEvent):
        """关闭当前对话自动 TTS"""
        async for item in handle_tts_off(self, event):
            yield item

    @filter.command("tts_on")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tts_on(self, event: AstrMessageEvent):
        """开启当前对话自动 TTS"""
        async for item in handle_tts_on(self, event):
            yield item

    @filter.command("text")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_text(self, event: AstrMessageEvent):
        """控制自动 TTS 是否同步发送文字 /text <on|off>"""
        async for item in handle_text(self, event):
            yield item

    @filter.command("tts_help")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tts_help(self, event: AstrMessageEvent):
        """快速查看常用 TTS 指令"""
        async for item in handle_tts_help(self, event):
            yield item

    @filter.command("tts_restore")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_tts_restore(self, event: AstrMessageEvent):
        """将当前对话配置恢复为插件默认设置"""
        async for item in handle_tts_restore(self, event):
            yield item

    @filter.command("emotion")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_emotion(self, event: AstrMessageEvent):
        """设置情感 /emotion <情感名|auto|off>"""
        async for item in handle_emotion(self, event):
            yield item

    @filter.command("emotions")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_emotions(self, event: AstrMessageEvent):
        """列出所有支持的情感"""
        async for item in handle_emotions(self, event):
            yield item

    @filter.command("speed")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_speed(self, event: AstrMessageEvent):
        """设置语速 /speed <0.5~2.0>"""
        async for item in handle_speed(self, event):
            yield item

    @filter.command("pitch")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_pitch(self, event: AstrMessageEvent):
        """设置音高 /pitch <-12~+12>"""
        async for item in handle_pitch(self, event):
            yield item

    @filter.command("breath")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_breath(self, event: AstrMessageEvent):
        """开关呼吸声 /breath <on|off>"""
        async for item in handle_breath(self, event):
            yield item

    @filter.command("stress")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_stress(self, event: AstrMessageEvent):
        """开关重音模式 /stress <on|off>"""
        async for item in handle_stress(self, event):
            yield item

    @filter.command("dialect")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_dialect(self, event: AstrMessageEvent):
        """设置方言口音 /dialect <方言名|off>"""
        async for item in handle_dialect(self, event):
            yield item

    @filter.command("volume")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_volume(self, event: AstrMessageEvent):
        """设置音量 /volume <轻声|正常|大声|off>"""
        async for item in handle_volume(self, event):
            yield item

    @filter.command("laughter")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_laughter(self, event: AstrMessageEvent):
        """开关笑声 /laughter <on|off>"""
        async for item in handle_laughter(self, event):
            yield item

    @filter.command("pause")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_pause(self, event: AstrMessageEvent):
        """开关停顿模式 /pause <on|off>"""
        async for item in handle_pause(self, event):
            yield item

    @filter.command("preset")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_preset(self, event: AstrMessageEvent):
        """查看/应用预设 /preset [预设名]"""
        async for item in handle_preset(self, event):
            yield item

    @filter.command("presetlist")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_presetlist(self, event: AstrMessageEvent):
        """列出所有预设"""
        async for item in handle_presetlist(self, event):
            yield item

    @filter.command("voice")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_voice(self, event: AstrMessageEvent):
        """查看/切换音色 /voice [音色ID]"""
        async for item in handle_voice(self, event):
            yield item

    @filter.command("voices")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_voices(self, event: AstrMessageEvent):
        """列出所有内置音色"""
        async for item in handle_voices(self, event):
            yield item

    @filter.command("ttsswitch")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_ttsswitch(self, event: AstrMessageEvent):
        """切换 TTS 输出模式 /ttsswitch <default|design|clone>"""
        async for item in handle_ttsswitch(self, event):
            yield item

    @filter.command("voiceclone")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_voiceclone(self, event: AstrMessageEvent):
        """声音克隆 /voiceclone <ID> <音频路径> 或 /voiceclone <音色名> 切换"""
        async for item in handle_voiceclone(self, event):
            yield item

    @filter.command("voicegen")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_voicegen(self, event: AstrMessageEvent):
        """声音设计 /voicegen <ID> <描述文本>"""
        async for item in handle_voicegen(self, event):
            yield item

    @filter.command("ttsformat")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_ttsformat(self, event: AstrMessageEvent):
        """设置音频输出格式 /ttsformat <mp3|wav|ogg>"""
        async for item in handle_ttsformat(self, event):
            yield item

    @filter.command("ttsconfig")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_ttsconfig(self, event: AstrMessageEvent):
        """查看当前会话 TTS 配置"""
        async for item in handle_ttsconfig(self, event):
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
        """从消息中提取命令参数部分（兼容 @bot 后缀与无斜杠写法）。"""
        raw = str(event.message_str or "").strip()
        base = cmd.lstrip("/")
        m = re.match(
            rf"^/?{re.escape(base)}(?:@[^\s]+)?(?:\s+|$)", raw, re.IGNORECASE
        )
        if m:
            return raw[m.end():].strip()
        return raw[len(cmd):].strip()
