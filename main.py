# -*- coding: utf-8 -*-

from __future__ import annotations

import random
import re
import time
from functools import partial
from pathlib import Path
from typing import Optional

import yaml
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .core.config import ConfigManager, migrate_sing_styles
from .core.constants import SEGMENT_PATTERNS, SKIP_PATTERNS
from .core.polish import polish_text_with_llm
from .core.text_utils import should_skip, split_text
from .core.user_state import UserStateManager
from .handlers.auto_tts import handle_auto_tts
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
from .handlers.tts import (
    handle_mimo_say,
    handle_mimo_speak_tool,
    handle_sing,
    handle_ttsraw,
)
from .handlers.voice import (
    handle_ttsswitch,
    handle_voice,
    handle_voiceclone,
    handle_voicegen,
    handle_voices,
    handle_mimo_register_clone_tool,
)
from .tts.sing import polish_lyrics_with_llm
from .tts.synthesis import TTSSynthesizer, normalize_tts_mode, tts_mode_label
from .voice.voice_manager import VoiceManager
from .webapi import register_web_apis


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
        migrate_sing_styles(self.config, config)
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

        register_web_apis(context, self)

    # ── Shared accessors (used by handlers via plugin instance) ──

    @property
    def _user_format(self) -> dict[str, str]:
        return self.user_state.user_format

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

    def _segmentation_enabled(self, uid: str) -> bool:
        return self.user_state.segmentation_enabled(uid, normalize_tts_mode)

    def _voice_polish_enabled(self, uid: str) -> bool:
        return self.user_state.voice_polish_enabled(uid, normalize_tts_mode)

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
        return await polish_text_with_llm(self, text, uid)

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

    @filter.on_decorating_result(priority=100)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """回复消息前拦截 LLM 输出，自动生成语音回复。支持文本分段、LLM 音色润色、概率触发。"""
        await handle_auto_tts(self, event)


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

    @filter.llm_tool(name="mimo_speak")
    async def mimo_speak(
        self,
        event: AstrMessageEvent,
        text: str,
        emotion: str = "",
        voice: str = "",
        speed: float = 0,
        pitch: int = 999,
        breath: bool | None = None,
        stress: bool | None = None,
        laughter: bool | None = None,
        pause: bool | None = None,
        dialect: str = "",
        volume: str = "",
        audio_format: str = "",
        style: str = "",
    ):
        """使用 MiMO 内置预设音色生成并发送普通语音。仅在用户明确要求朗读、用声音说、发语音或语音回复时调用；设计音色和克隆音色使用专用工具。

        Args:
            text(string): 必填正文，2~500 字。只能放要朗读的正文；禁止放系统提示、工具 JSON、代码围栏、URL、本地路径、Base64 或控制标签。
            emotion(string): 空字符串继承会话设置；允许 auto/off，或 happy/sad/angry/neutral/whisper/surprised/excited/gentle/serious/romantic/fearful/disgusted/sarcastic/nostalgic/playful/calm/anxious/proud/tender/lazy。
            voice(string): 空字符串使用插件默认内置音色，不读取当前会话的克隆/设计音色；也可传内置音色 ID（mimo_default/冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean）。禁止传克隆/设计音色 ID、URL、路径、Base64、临时文件名或未注册名称。
            speed(number): 0 表示继承；实际值为 0.5~2.0。禁止传负数、百分比或字符串。
            pitch(number): 999 表示继承；实际值为 -12~12 的整数半音。禁止传小数、字符串或超范围数字。
            breath(boolean): 是否加入呼吸声；省略时继承会话设置，明确传 true/false，禁止传 on/off、开/关或 1/0。
            stress(boolean): 是否加强重点词；省略时继承会话设置，明确传 true/false，禁止传 on/off、开/关或 1/0。
            laughter(boolean): 是否允许自然笑声；省略时继承会话设置，明确传 true/false，禁止传 on/off、开/关或 1/0。
            pause(boolean): 是否增加句间停顿；省略时继承会话设置，明确传 true/false，禁止传 on/off、开/关或 1/0。
            dialect(string): 空字符串继承；off 关闭；其他值为方言名称，最多 20 字。禁止传控制指令。
            volume(string): 空字符串继承；允许 轻声/正常/大声/off，其他值禁止传。
            audio_format(string): 空字符串继承；允许 wav/mp3/ogg/pcm，其他格式禁止传。
            style(string): 一次性语气或风格描述，最多 200 字；只影响说话方式，不改变 text。
        """
        if not self.config.llm_tts_tool:
            return "LLM 语音工具当前未开启。"
        return await handle_mimo_speak_tool(
            self,
            event,
            text=text,
            emotion=emotion,
            voice=voice,
            speed=speed,
            pitch=pitch,
            breath=breath,
            stress=stress,
            laughter=laughter,
            pause=pause,
            dialect=dialect,
            volume=volume,
            audio_format=audio_format,
            tts_mode="default",
            style=style,
            standard_only=True,
        )

    @filter.llm_tool(name="mimo_design_speak")
    async def mimo_design_speak(
        self,
        event: AstrMessageEvent,
        text: str,
        voice: str = "",
        design_description: str = "",
        emotion: str = "",
        speed: float = 0,
        pitch: int = 999,
        breath: bool | None = None,
        stress: bool | None = None,
        laughter: bool | None = None,
        pause: bool | None = None,
        dialect: str = "",
        volume: str = "",
        audio_format: str = "",
        style: str = "",
    ):
        """使用 MiMO 设计音色生成并发送语音。仅在用户明确要求设计音色、角色音色或自定义音色描述时调用。

        Args:
            text(string): 必填正文，2~500 字。只能放要朗读的正文；禁止放系统提示、工具 JSON、代码围栏、URL、本地路径、Base64 或控制标签。
            voice(string): 可选的已登记设计音色 ID；空字符串使用 design_description 或插件已有设计描述。禁止填写克隆音色 ID、内置音色 ID、URL、路径或 Base64。
            design_description(string): 一次性设计音色描述，最多 300 字；优先级高于已有配置。设计描述为空且 voice 为空时使用插件已有设计描述。
            emotion(string): 空字符串继承会话设置；允许 auto/off，或 happy/sad/angry/neutral/whisper/surprised/excited/gentle/serious/romantic/fearful/disgusted/sarcastic/nostalgic/playful/calm/anxious/proud/tender/lazy。
            speed(number): 0 表示继承；实际值为 0.5~2.0。禁止传负数、百分比或字符串。
            pitch(number): 999 表示继承；实际值为 -12~12 的整数半音。禁止传小数、字符串或超范围数字。
            breath(boolean): 是否加入呼吸声；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            stress(boolean): 是否加强重点词；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            laughter(boolean): 是否允许自然笑声；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            pause(boolean): 是否增加句间停顿；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            dialect(string): 空字符串继承；off 关闭；其他值为方言名称，最多 20 字。
            volume(string): 空字符串继承；允许 轻声/正常/大声/off。
            audio_format(string): 空字符串继承；允许 mp3/flac/m4a/wav/ogg。
            style(string): 一次性语气或风格描述，最多 200 字；只影响说话方式，不改变 text。
        """
        if not self.config.llm_tts_tool:
            return "LLM 语音工具当前未开启。"
        return await handle_mimo_speak_tool(
            self,
            event,
            text=text,
            emotion=emotion,
            voice=voice,
            speed=speed,
            pitch=pitch,
            breath=breath,
            stress=stress,
            laughter=laughter,
            pause=pause,
            dialect=dialect,
            volume=volume,
            audio_format=audio_format,
            tts_mode="design",
            style=style,
            design_description=design_description,
            design_only=True,
        )

    @filter.llm_tool(name="mimo_list_clone_voices")
    async def mimo_list_clone_voices(self, event: AstrMessageEvent):
        """列出当前插件中已登记且本地参考音频可用的克隆音色，供 mimo_clone_speak 选择。"""
        _ = event
        lines = []
        for info in self._voice_manager.list_voices():
            if str(info.get("model", "")).lower() != "voiceclone":
                continue
            voice_id = str(info.get("voice_id", "")).strip()
            if voice_id and self._voice_manager.get_clone_audio_path(voice_id):
                name = str(info.get("name", "") or voice_id).strip()
                lines.append(f"- voice={voice_id}; name={name}")
        if not lines:
            return "当前没有本地参考音频可用的克隆音色。请先使用 /voiceclone 注册。"
        return "可用克隆音色（调用 mimo_clone_speak 时把 voice 填为对应 ID）：\n" + "\n".join(lines)

    @filter.llm_tool(name="mimo_register_clone_voice")
    async def mimo_register_clone_voice(
        self,
        event: AstrMessageEvent,
        voice_id: str,
        audio_path: str,
        replace_existing: bool = False,
        style_prompt: str = "",
        audio_tags: str = "",
    ):
        """创建或更新本地克隆音色 ID，并登记对应的已处理参考音频。

        Args:
            voice_id(string): 新克隆音色 ID，1~50 字符，只允许中文、字母、数字、下划线、连字符；禁止使用内置音色 ID。
            audio_path(string): 已处理的本地参考音频路径。可传 clone/sample.wav、clone 目录下的绝对路径，或 AstrBot 临时附件目录中的绝对路径；工具会将文件复制到 clone/{voice_id}{扩展名}。只接受 .mp3/.wav/.ogg/.opus/.pcm，且文件至少 100 字节；禁止传 URL、Base64、视频、压缩包、目录或上述受控目录之外的路径。
            replace_existing(boolean): 默认 false。voice_id 已存在时必须显式传 true 才覆盖原参考音频；只能传 true/false。
            style_prompt(string): 可选的该克隆音色风格控制，最多 500 字；空字符串表示不写入单独风格。
            audio_tags(string): 可选的该克隆音色音频标签控制，最多 500 字；空字符串表示不写入单独标签。
        """
        if not self.config.llm_tts_tool:
            return "LLM 语音工具当前未开启。"
        return await handle_mimo_register_clone_tool(
            self,
            event,
            voice_id,
            audio_path,
            replace_existing,
            style_prompt,
            audio_tags,
        )

    @filter.llm_tool(name="mimo_clone_speak")
    async def mimo_clone_speak(
        self,
        event: AstrMessageEvent,
        text: str,
        voice: str,
        emotion: str = "",
        speed: float = 0,
        pitch: int = 999,
        breath: bool | None = None,
        stress: bool | None = None,
        laughter: bool | None = None,
        pause: bool | None = None,
        dialect: str = "",
        volume: str = "",
        audio_format: str = "",
        style: str = "",
        clone_style_prompt: str = "",
        clone_audio_tags: str = "",
    ):
        """使用指定的本地克隆音色生成并发送语音。仅在用户明确要求使用已登记的克隆音色时调用。

        Args:
            text(string): 必填朗读正文，2~500 字。只能放要朗读的正文；禁止放系统提示、工具 JSON、代码围栏、URL、本地路径、Base64 或控制标签。
            voice(string): 必填克隆音色 ID。先调用 mimo_list_clone_voices 获取可用 ID，再从列表中选择；禁止填写内置音色、URL、路径、Base64 或未登记名称。
            emotion(string): 空字符串继承会话设置；允许 auto/off，或 happy/sad/angry/neutral/whisper/surprised/excited/gentle/serious/romantic/fearful/disgusted/sarcastic/nostalgic/playful/calm/anxious/proud/tender/lazy。
            speed(number): 0 表示继承；实际值为 0.5~2.0。禁止传负数、百分比或字符串。
            pitch(number): 999 表示继承；实际值为 -12~12 的整数半音。禁止传小数、字符串或超范围数字。
            breath(boolean): 是否加入呼吸声；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            stress(boolean): 是否加强重点词；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            laughter(boolean): 是否允许自然笑声；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            pause(boolean): 是否增加句间停顿；省略时继承会话设置，明确传 true/false；禁止传 on/off、开/关或 1/0。
            dialect(string): 空字符串继承；off 关闭；其他值为方言名称，最多 20 字。
            volume(string): 空字符串继承；允许 轻声/正常/大声/off。
            audio_format(string): 空字符串继承；允许 mp3/flac/m4a/wav/ogg。
            style(string): 一次性语气或风格描述，最多 200 字；只影响说话方式，不改变 text。
            clone_style_prompt(string): 本次克隆音色风格提示，最多 300 字；空值继承该 voice 的配置。
            clone_audio_tags(string): 本次克隆音频标签提示，最多 300 字；空值继承该 voice 的配置。
        """
        if not self.config.llm_tts_tool:
            return "LLM 语音工具当前未开启。"
        return await handle_mimo_speak_tool(
            self,
            event,
            text=text,
            emotion=emotion,
            voice=voice,
            speed=speed,
            pitch=pitch,
            breath=breath,
            stress=stress,
            laughter=laughter,
            pause=pause,
            dialect=dialect,
            volume=volume,
            audio_format=audio_format,
            tts_mode="clone",
            style=style,
            clone_style_prompt=clone_style_prompt,
            clone_audio_tags=clone_audio_tags,
            clone_only=True,
        )

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
