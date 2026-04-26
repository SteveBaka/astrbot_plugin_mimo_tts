# -*- coding: utf-8 -*-
"""
MiMO TTS Plugin for AstrBot - Enhanced Edition

基于 MiMO-V2.5-TTS 的精细化语音合成插件。
自动拦截 LLM 输出生成语音，支持 20 种情感、语速、音高、呼吸声、
重音、唱歌、方言、音量、笑声、停顿、预设系统等精细化控制。

使用方式：
  - 自动拦截：AI 说话时自动转语音
  - /tts <文本> [选项]：即时语音合成
  - /sing <歌词>：唱歌模式
  - /voice [音色名]：查看/切换音色
  - /emotion [情感名]：查看/设置情感
  - /speed [数值]：查看/设置语速
  - /pitch [数值]：查看/设置音高
  - /breath [on|off]：呼吸声开关
  - /stress [on|off]：重音模式开关
  - /dialect [方言名]：设置方言口音
  - /volume [轻声|正常|大声]：设置音量
  - /laughter [on|off]：笑声开关
  - /pause [on|off]：停顿开关
  - /preset [预设名]：查看/应用预设
  - /presetlist：列出所有预设
  - /emotions：列出所有情感
  - /voices：列出所有音色
  - /ttsformat [格式]：设置音频格式
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import traceback
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.components import Plain, Record

from .core.config import ConfigManager
from .core.constants import (
    PLUGIN_ID,
    PLUGIN_NAME,
    CONFIG_FILE,
    MIMO_VOICE_LIST,
    SUPPORTED_EMOTIONS,
    SUPPORTED_AUDIO_FORMATS,
    TTS_PRESETS,
    SKIP_PATTERNS,
    AUDIO_MIN_VALID_SIZE,
    AUDIO_VALID_EXTENSIONS,
)
from .tts.mimo_provider import MiMOProvider
from .tts.prompt_builder import build_system_prompt, detect_emotion
from .emotion.emotion_detector import EmotionDetector
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

        # ── Emotion detector ──
        self._detector = EmotionDetector()

        # ── Voice manager ──
        self._voice_manager = VoiceManager()

        # ── Audio file cleanup tracking ──
        self._recent_files: list[tuple[float, Path]] = []

        # ── Init done ──
        self._started = False

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

    def _get_user_settings(self, uid: str) -> dict:
        if uid not in self._user_settings:
            self._user_settings[uid] = {
                "emotion": self.config.emotion_override,
                "speed": self.config.default_speed,
                "pitch": self.config.default_pitch,
                "voice": self.config.default_voice,
                "breath": self.config.breath_enabled,
                "stress": self.config.stress_enabled,
                # 唱歌模式仅允许由 /sing 命令临时触发，避免污染普通 /tts 与自动 TTS。
                "sing": False,
                "laughter": self.config.laughter_enabled,
                "pause": self.config.pause_enabled,
                "style_hint": self.config.style_hint,
                "dialect": "",
                "volume": "",
                "tts_mode": self._normalize_tts_mode(self.config.tts_output_mode),
            }
        return self._user_settings[uid]

    def _should_tts(self, uid: str) -> bool:
        return self.config.get("auto_tts", True)

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
            sing=uset["sing"],
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

    def _resolve_synthesis_target(self, uid: str) -> tuple[str, Optional[str], str]:
        """根据当前输出模式解析最终音色与模型。"""
        uset = self._get_user_settings(uid)
        mode = self._resolve_tts_mode(uid)
        current_voice = self._resolve_voice(uset["voice"])
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}

        if mode == "clone":
            clone_voice_id = self.config.clone_voice_id.strip()
            if clone_voice_id:
                return clone_voice_id, self.config.clone_model, mode
            if str(current_voice_info.get("model", "")).lower() == "voiceclone":
                return current_voice, self.config.clone_model, mode
            raise RuntimeError("当前已切换到“克隆”输出，但未配置 clone_voice_id，也未选中可用的克隆音色。")

        if mode == "design":
            description = self._resolve_design_description(uid)
            if description:
                # 按官方文档，VoiceDesign 直接使用 user 消息中的描述文本生成目标音色，
                # 并不依赖普通 TTS 的 audio.voice 预置音色参数。
                return "", self.config.design_model, mode
            raise RuntimeError("当前已切换到“设计”输出，但未配置 design_voice_description，也未选中带描述的设计音色。")

        if self._voice_manager.get_voice(current_voice):
            return self.config.default_voice, None, mode
        return current_voice, None, mode

    @staticmethod
    def _tts_mode_label(mode: str) -> str:
        return {
            "default": "默认",
            "design": "设计",
            "clone": "克隆",
        }.get(mode, "默认")

    def _cleanup_recent_files(self) -> None:
        now = time.time()
        self._recent_files = [
            (t, p) for t, p in self._recent_files
            if (now - t) < 2 * 3600 and p.exists()
        ]
        for _, p in self._recent_files:
            try:
                if p.exists() and p.stat().st_size < 100:
                    p.unlink(missing_ok=True)
            except Exception:
                pass

    def _resolve_voice(self, voice_id: str) -> str:
        info = self._voice_manager.get_voice(voice_id)
        if info:
            return voice_id
        for v in MIMO_VOICE_LIST:
            if v["id"] == voice_id:
                return voice_id
        return self.config.get("default_voice", "mimo_default")

    def _resolve_clone_audio_path(self, raw_path: str) -> Path:
        """解析 /voiceclone 使用的参考音频路径。

        支持：
        1. 绝对路径
        2. 相对当前工作目录的路径
        3. 相对插件根目录的路径
        4. 仅文件名时，自动尝试插件下的 clone/ 目录
        """
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return Path(text)

        raw = Path(text)
        plugin_dir = Path(__file__).parent
        clone_dir = plugin_dir / "clone"
        candidates: list[Path] = []

        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.extend([
                raw,
                plugin_dir / raw,
                clone_dir / raw,
                clone_dir / raw.name,
            ])

        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate.resolve()
            except Exception:
                continue

        # 找不到时，仍返回一个最适合提示给用户的候选路径
        fallback = raw if raw.is_absolute() else (clone_dir / raw.name)
        return fallback

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
            "thought:",
            "reasoning:",
            "internal monologue:",
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
        )
        matched = sum(1 for phrase in suspicious_phrases if phrase in head)
        return matched >= 2

    # ── TTS command (reusable for auto TTS too) ──

    async def _do_tts(
        self, text: str, uid: str, format_override: Optional[str] = None,
    ) -> Optional[Path]:
        """Run TTS and return the audio file path."""
        provider = self._ensure_provider()
        if not provider:
            raise RuntimeError("API Key 未配置。请在配置中设置 api_key。")

        prompt = self._build_prompt(uid)
        uset = self._get_user_settings(uid)
        requested_fmt = format_override or self._user_format.get(uid, "mp3")
        # AstrBot 的 Record 组件在当前版本下对 RIFF/WAV 兼容性最稳定，
        # 因此这里统一向上游请求 wav，避免 mp3/ogg/pcm 落地后再次被按 RIFF 解析时报错。
        fmt = "wav"
        final_text = self._apply_singing_tag(text) if uset["sing"] else text

        voice_id, model_override, mode = self._resolve_synthesis_target(uid)
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
        tmp_dir = Path(__file__).parent / "temp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out = tmp_dir / f"mimo_{ts}.{actual_fmt}"
        out.write_bytes(raw)
        self._recent_files.append((time.time(), out))
        self._cleanup_recent_files()
        return out

    # ═══════════════════════════════════════════════════════════
    #  Event Handlers
    # ═══════════════════════════════════════════════════════════

    @filter.on_decorating_result(priority=9999)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """Auto TTS: intercept LLM output and generate voice reply."""
        if not self._should_tts(event.get_sender_id()):
            return
        if not event.is_private_chat() and not self.config.get("auto_tts_in_group", True):
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
            logger.warning("MiMO TTS: skip auto TTS because result looks like leaked persona/skill prompt")
            return

        uid = event.get_sender_id()
        if plain.startswith("/"):
            return

        # If emotion is auto, detect from text
        uset = self._get_user_settings(uid)
        orig_emotion = uset["emotion"]
        if not orig_emotion or orig_emotion == "auto":
            detected = detect_emotion(plain)
            if detected:
                uset["emotion"] = detected

        try:
            audio_path = await self._do_tts(plain, uid)
            if audio_path:
                result.chain.append(Record.fromFileSystem(str(audio_path)))
        except Exception as e:
            result.chain.append(Plain(f"[TTS 合成失败: {e}]"))
        finally:
            uset["emotion"] = orig_emotion

    @filter.command("tts")
    async def cmd_tts(self, event: AstrMessageEvent):
        """
        /tts <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]
                   [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]
        """
        raw = event.message_str.strip()
        text = raw[len("/tts"):].strip()
        if not text:
            yield MessageEventResult().message("用法: /tts <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色] [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]")
            return

        uid = event.get_sender_id()
        uset = self._get_user_settings(uid)

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

    @filter.command("sing")
    async def cmd_sing(self, event: AstrMessageEvent):
        """ /sing <歌词> """
        raw = event.message_str.strip()
        text = raw[len("/sing"):].strip()
        if not text:
            yield MessageEventResult().message("用法: /sing <歌词>")
            return

        uid = event.get_sender_id()
        uset = self._get_user_settings(uid)
        orig = uset.copy()
        uset["sing"] = True

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
        """ /voice [音色名] """
        raw = event.message_str.strip()
        arg = raw[len("/voice"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            lines = [f"当前音色: {uset['voice']}", "", "内置音色:"]
            for v in MIMO_VOICE_LIST:
                lines.append(f"  {v['id']:10s} {v['name']}  ({v['gender']}声 {v['style']})")
            lines.append("")
            lines.append("用法: /voice <音色ID>")
            yield MessageEventResult().message("\n".join(lines))
            return

        resolved = self._resolve_voice(arg)
        self._get_user_settings(uid)["voice"] = resolved
        yield MessageEventResult().message(f"[u2713] 音色已切换为: {resolved}")

    @filter.command("ttsswitch")
    async def cmd_ttsswitch(self, event: AstrMessageEvent):
        """ /ttsswitch [default|design|clone] — 切换 TTS 输出来源模式 """
        raw = event.message_str.strip()
        arg = raw[len("/ttsswitch"):].strip()
        uid = event.get_sender_id()
        uset = self._get_user_settings(uid)

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
        yield MessageEventResult().message(
            f"[✓] TTS 输出模式已切换为: {self._tts_mode_label(mode)} ({mode})"
        )

    @filter.command("emotion")
    async def cmd_emotion(self, event: AstrMessageEvent):
        """ /emotion [情感名|auto|off] """
        raw = event.message_str.strip()
        arg = raw[len("/emotion"):].strip()
        uid = event.get_sender_id()

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
            yield MessageEventResult().message("[u2713] 已关闭情感覆盖（自动检测）")
        elif arg == "auto":
            self._get_user_settings(uid)["emotion"] = "auto"
            yield MessageEventResult().message("[u2713] 已开启情感自动检测")
        elif arg in SUPPORTED_EMOTIONS:
            self._get_user_settings(uid)["emotion"] = arg
            yield MessageEventResult().message(f"[u2713] 情感已设置为: {arg}")
        else:
            yield MessageEventResult().message(f"[X] 不支持的情感: {arg}\n可用: {', '.join(SUPPORTED_EMOTIONS)}")

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
        """ /speed [0.5~2.0] """
        raw = event.message_str.strip()
        arg = raw[len("/speed"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            yield MessageEventResult().message(f"当前语速: {uset['speed']}\n用法: /speed <0.5~2.0>")
            return

        try:
            val = max(0.5, min(2.0, float(arg)))
            self._get_user_settings(uid)["speed"] = val
            yield MessageEventResult().message(f"[u2713] 语速已设置为: {val}")
        except ValueError:
            yield MessageEventResult().message("[X] 请输入 0.5~2.0 之间的数值。")

    @filter.command("pitch")
    async def cmd_pitch(self, event: AstrMessageEvent):
        """ /pitch [-12~+12] """
        raw = event.message_str.strip()
        arg = raw[len("/pitch"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            yield MessageEventResult().message(f"当前音高: {uset['pitch']}\n用法: /pitch <-12~+12>")
            return

        try:
            val = max(-12, min(12, int(arg)))
            self._get_user_settings(uid)["pitch"] = val
            yield MessageEventResult().message(f"[u2713] 音高已设置为: {val}")
        except ValueError:
            yield MessageEventResult().message("[X] 请输入 -12~+12 之间的整数。")

    @filter.command("breath")
    async def cmd_breath(self, event: AstrMessageEvent):
        """ /breath [on|off] """
        raw = event.message_str.strip()
        arg = raw[len("/breath"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["breath"] else "关"
            yield MessageEventResult().message(f"呼吸声: {state}\n用法: /breath <on|off>")
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["breath"] = val
        yield MessageEventResult().message(f"[u2713] 呼吸声已{'开启' if val else '关闭'}")

    @filter.command("stress")
    async def cmd_stress(self, event: AstrMessageEvent):
        """ /stress [on|off] """
        raw = event.message_str.strip()
        arg = raw[len("/stress"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["stress"] else "关"
            yield MessageEventResult().message(f"重音模式: {state}\n用法: /stress <on|off>")
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["stress"] = val
        yield MessageEventResult().message(f"[u2713] 重音模式已{'开启' if val else '关闭'}")

    @filter.command("dialect")
    async def cmd_dialect(self, event: AstrMessageEvent):
        """ /dialect [方言名|off] — 设置方言口音，如 四川话、粤语、东北话 """
        raw = event.message_str.strip()
        arg = raw[len("/dialect"):].strip()
        uid = event.get_sender_id()

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
            yield MessageEventResult().message("[u2713] 已关闭方言口音")
        else:
            self._get_user_settings(uid)["dialect"] = arg
            yield MessageEventResult().message(f"[u2713] 方言已设置为: {arg}")

    @filter.command("volume")
    async def cmd_volume(self, event: AstrMessageEvent):
        """ /volume [轻声|正常|大声|off] """
        raw = event.message_str.strip()
        arg = raw[len("/volume"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            cur = uset["volume"] or "(正常)"
            yield MessageEventResult().message(
                f"当前音量: {cur}\n"
                "用法: /volume <轻声|正常|大声|off>"
            )
            return

        if arg == "off":
            self._get_user_settings(uid)["volume"] = ""
            yield MessageEventResult().message("[u2713] 音量已恢复为正常")
        else:
            self._get_user_settings(uid)["volume"] = arg
            yield MessageEventResult().message(f"[u2713] 音量已设置为: {arg}")

    @filter.command("laughter")
    async def cmd_laughter(self, event: AstrMessageEvent):
        """ /laughter [on|off] — 允许自然笑声"""
        raw = event.message_str.strip()
        arg = raw[len("/laughter"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["laughter"] else "关"
            yield MessageEventResult().message(f"笑声: {state}\n用法: /laughter <on|off>")
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["laughter"] = val
        yield MessageEventResult().message(f"[u2713] 笑声已{'开启' if val else '关闭'}")

    @filter.command("pause")
    async def cmd_pause(self, event: AstrMessageEvent):
        """ /pause [on|off] — 增加句间停顿"""
        raw = event.message_str.strip()
        arg = raw[len("/pause"):].strip()
        uid = event.get_sender_id()

        if not arg:
            uset = self._get_user_settings(uid)
            state = "开" if uset["pause"] else "关"
            yield MessageEventResult().message(f"停顿模式: {state}\n用法: /pause <on|off>")
            return

        val = arg.lower() in ("on", "true", "1", "开")
        self._get_user_settings(uid)["pause"] = val
        yield MessageEventResult().message(f"[u2713] 停顿模式已{'开启' if val else '关闭'}")

    @filter.command("preset")
    async def cmd_preset(self, event: AstrMessageEvent):
        """ /preset [预设名] — 查看/应用预设"""
        raw = event.message_str.strip()
        arg = raw[len("/preset"):].strip()
        uid = event.get_sender_id()

        if not arg:
            lines = ["预设列表:", ""]
            for name, p in TTS_PRESETS.items():
                lines.append(f"  {name:18s}  情感={p['emotion']:10s}  语速={p['speed']}  音高={p['pitch']:+d}  音色={p['voice']}")
            lines.append("")
            lines.append("用法: /preset <预设名>  （如 /preset bedtime_story）")
            yield MessageEventResult().message("\n".join(lines))
            return

        if arg not in TTS_PRESETS:
            yield MessageEventResult().message(f"[X] 未知预设: {arg}\n用 /presetlist 查看所有预设")
            return

        preset = TTS_PRESETS[arg]
        uset = self._get_user_settings(uid)
        uset["emotion"] = preset["emotion"]
        uset["speed"] = preset["speed"]
        uset["pitch"] = preset["pitch"]
        uset["breath"] = preset["breath"]
        uset["stress"] = preset["stress"]
        uset["voice"] = self._resolve_voice(preset["voice"])

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
            lines.append(f"    情感={p['emotion']}  语速={p['speed']}  音高={p['pitch']:+d}  音色={p['voice']}  呼吸={'✓' if p['breath'] else '✗'}  重音={'✓' if p['stress'] else '✗'}")
        lines.append(f"\n用法: /preset <预设名> 应用预设")
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("voices")
    async def cmd_voices(self, event: AstrMessageEvent):
        """List all built-in voices."""
        lines = ["MiMO 内置音色:", ""]
        for v in MIMO_VOICE_LIST:
            lines.append(f"  {v['id']:10s} {v['name']}  ({v['gender']}声 · {v['style']})")
        lines.append(f"\n共 {len(MIMO_VOICE_LIST)} 种  |  用法: /voice <音色ID>")
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("voiceclone")
    async def cmd_voiceclone(self, event: AstrMessageEvent):
        """ /voiceclone <ID> <音频路径> — 克隆参考音频的声音"""
        raw = event.message_str.strip()
        arg = raw[len("/voiceclone"):].strip()
        if not arg:
            yield MessageEventResult().message(
                "用法: /voiceclone <ID> <参考音频路径>\n"
                "示例1: /voiceclone my_clone /path/to/sample.wav\n"
                "示例2: /voiceclone my_clone clone/sample.wav\n"
                "说明: 推荐将参考音频放到插件目录下的 clone/ 文件夹"
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
            plugin_audio_dir = Path(__file__).parent / "clone"
            yield MessageEventResult().message(
                f"[X] 音频文件不存在: {audio_path}\n"
                f"可将参考音频放到插件目录下: {plugin_audio_dir}\n"
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

        yield MessageEventResult().message("⏳ 正在克隆声音…")

        ok = await provider.register_voice(vid, str(audio_file))
        if ok:
            self._voice_manager.register_voice(vid, name=vid, model="voiceclone")
            # 同步到配置面板
            self.config._cfg["clone_enabled"] = True
            self.config._cfg["clone_voice_id"] = vid
            yield MessageEventResult().message(
                f"[✓] 声音已注册: {vid}\n"
                f"  用 /voice {vid} 切换使用\n"
                f"  参考音频: {audio_file}\n"
                f"  配置面板已同步更新"
            )
        else:
            yield MessageEventResult().message(
                f"[X] 声音克隆失败：{provider.last_error or '请查看日志。'}"
            )

    @filter.command("voicegen")
    async def cmd_voicegen(self, event: AstrMessageEvent):
        """ /voicegen <ID> <描述文本> — 用文字描述生成全新音色"""
        raw = event.message_str.strip()
        arg = raw[len("/voicegen"):].strip()
        if not arg:
            yield MessageEventResult().message(
                "用法: /voicegen <ID> <音色描述>\n"
                "示例: /voicegen my_voice \"温柔甜美的年轻女声，语速适中\""
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

        yield MessageEventResult().message("⏳ 正在设计声音…")

        ok = await provider.design_voice(vid, desc, model=self.config.design_model)
        if ok:
            self._voice_manager.register_voice(vid, name=vid, model="voicedesign", description=desc)
            # 仅同步可展示的配置项；design_voice_id 改为内部状态，避免出现在插件设置面板。
            self.config._cfg["design_enabled"] = True
            self.config.design_voice_id = vid
            self.config._cfg["design_voice_description"] = desc
            yield MessageEventResult().message(
                f"[✓] 声音设计完成: {vid}\n"
                f"  可用 /ttsswitch design 切换到设计模式\n"
                f"  也可用 /voice {vid} 将这条描述设为当前设计音色\n"
                f"  配置面板已同步更新描述信息"
            )
        else:
            yield MessageEventResult().message(
                f"[X] 声音设计失败：{provider.last_error or '请查看日志。'}"
            )

    @filter.command("voiceclonelist")
    async def cmd_voiceclonelist(self, event: AstrMessageEvent):
        voices = self._voice_manager.list_voices()
        if not voices:
            yield MessageEventResult().message("暂无已注册的自定义音色。")
            return
        lines = ["已注册的自定义音色:", ""]
        for v in voices:
            lines.append(f"  {v['voice_id']:20s}  {v.get('name', '')}  [{v.get('model', '')}]")
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("ttsformat")
    async def cmd_ttsformat(self, event: AstrMessageEvent):
        """ /ttsformat [mp3|wav|ogg] — 设置音频输出格式"""
        raw = event.message_str.strip()
        arg = raw[len("/ttsformat"):].strip()
        uid = event.get_sender_id()

        if not arg:
            cur = self._user_format.get(uid, "mp3")
            yield MessageEventResult().message(
                f"当前格式: {cur}\n"
                f"支持的格式: {', '.join(SUPPORTED_AUDIO_FORMATS)}\n"
                f"用法: /ttsformat <格式>"
            )
            return

        if arg.lower() not in SUPPORTED_AUDIO_FORMATS:
            yield MessageEventResult().message(f"[X] 不支持的格式: {arg}\n支持: {', '.join(SUPPORTED_AUDIO_FORMATS)}")
            return

        self._user_format[uid] = arg.lower()
        yield MessageEventResult().message(f"[u2713] 音频格式已设置为: {arg}")

    @filter.command("ttsconfig")
    async def cmd_ttsconfig(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        arg = raw[len("/ttsconfig"):].strip()

        if arg == "reset":
            self._user_settings.clear()
            self._user_format.clear()
            yield MessageEventResult().message("[u2713] 所有个人设置已重置。")
            return

        provider = self._ensure_provider()
        status = "[u2713] 正常" if provider else "[X] 未配置"

        uid = event.get_sender_id()
        uset = self._get_user_settings(uid)

        lines = [
            f"MiMO TTS 配置状态: {status}",
            f"模型: {self.config.get('model', 'mimo-v2.5-tts')}",
            f"API: {self.config.get('api_base_url', 'https://open.bigmodel.cn/api/paas/v4')[:50]}",
            f"",
            f"── 你的当前设置 ──",
            f"情感: {uset['emotion'] or '(自动)'}",
            f"语速: {uset['speed']}  音高: {uset['pitch']:+d}",
            f"呼吸: {'开' if uset['breath'] else '关'}  重音: {'开' if uset['stress'] else '关'}",
            f"方言: {uset['dialect'] or '(无)'}  音量: {uset['volume'] or '(正常)'}",
            f"笑声: {'开' if uset['laughter'] else '关'}  停顿: {'开' if uset['pause'] else '关'}",
            f"音色: {uset['voice']}",
            f"输出模式: {self._tts_mode_label(self._resolve_tts_mode(uid))} ({self._resolve_tts_mode(uid)})",
            f"格式: {self._user_format.get(uid, 'mp3')}",
            f"",
            f"用 /preset <预设名> 快速切换风格",
        ]
        yield MessageEventResult().message("\n".join(lines))

    @filter.command("ttsraw")
    async def cmd_ttsraw(self, event: AstrMessageEvent):
        """ /ttsraw <文本> — 不带情感的纯文本合成"""
        raw = event.message_str.strip()
        text = raw[len("/ttsraw"):].strip()
        if not text:
            yield MessageEventResult().message("用法: /ttsraw <文本>")
            return

        uid = event.get_sender_id()
        try:
            provider = self._ensure_provider()
            if not provider:
                raise RuntimeError("API Key 未配置。")

            fmt = "wav"
            raw_audio = await provider.synthesize(text=text, audio_format=fmt)
            if not raw_audio:
                raise RuntimeError(provider.last_error or "TTS 合成失败。")

            actual_fmt = str(provider.last_output_format or fmt or "mp3").lower()

            tmp_dir = Path(__file__).parent / "temp"
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
        """ /ttsinfo — 查看插件信息"""
        lines = [
            "MiMO TTS Plugin v1.2.0",
            "",
            "基于 MiMO-V2.5-TTS 的精细化语音合成插件",
            "",
            f"支持情感: {len(SUPPORTED_EMOTIONS)} 种",
            f"内置音色: {len(MIMO_VOICE_LIST)} 种",
            f"内置预设: {len(TTS_PRESETS)} 个",
            f"控制维度: 情感 语速 音高 呼吸声 重音 方言 音量 笑声 停顿（唱歌仅 /sing）",
            "",
            "主要命令:",
            "  /tts <文本>  - 即时合成",
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