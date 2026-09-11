# -*- coding: utf-8 -*-
"""TTS synthesis orchestration for MiMO TTS plugin.

Handles voice resolution, mode switching, prompt building, and actual synthesis.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from astrbot.api import logger

from ..core.constants import MIMO_VOICE_LIST
from ..core.director_composer import apply_director_to_prompt
from ..core.style_lib import (
    EMOTION_TO_TAG,
    extract_style_words,
    match_style_entry_by_name,
    match_style_examples,
    style_words_to_hint,
)
from ..core.text_utils import log_tts_text, strip_markdown_symbols
from ..tts.mimo_provider import MiMOProvider
from ..tts.prompt_builder import build_control_prompt
from .sing import prepare_sing

if TYPE_CHECKING:
    from ..voice.voice_manager import VoiceManager


def normalize_tts_mode(mode: Optional[str]) -> str:
    """Normalize TTS mode string to canonical form."""
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


def tts_mode_label(mode: str) -> str:
    """Return human-readable label for TTS mode."""
    return {
        "default": "默认",
        "design": "设计",
        "clone": "克隆",
    }.get(mode, "[未知]")


def merge_prompt_parts(*parts: Optional[str]) -> str:
    """Merge multiple prompt parts with Chinese comma separator."""
    merged: list[str] = []
    for part in parts:
        text = str(part or "").strip().strip("，,")
        if text:
            merged.append(text)
    return "，".join(merged)


class TTSSynthesizer:
    """Orchestrates TTS synthesis: voice resolution, mode switching, prompt building."""

    def __init__(self, config, voice_manager: "VoiceManager", data_dir: Path):
        self._config = config
        self._voice_manager = voice_manager
        self._data_dir = data_dir
        self._provider: Optional[MiMOProvider] = None
        # 歌词润色回调（main.py 注入 _polish_lyrics_with_llm）：
        # None 或配置开关关闭时零影响（sing-mode-feature.md §4.3）
        self.lyrics_polisher = None

    @property
    def provider(self) -> Optional[MiMOProvider]:
        return self._provider

    def ensure_provider(self) -> Optional[MiMOProvider]:
        """Get or create the TTS provider."""
        if self._provider is not None:
            return self._provider

        api_key = self._config.get("api_key", "")
        if not api_key:
            return None

        api_base_url = self._config.get("api_base_url", "")
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
            model=self._config.get("model", "mimo-v2.5-tts"),
            voice=self._config.get("default_voice", "mimo_default"),
            audio_format=self._config.get("audio_format", "wav"),
            timeout=self._config.get("timeout", 60),
            max_retries=self._config.get("max_retries"),
        )
        return self._provider

    async def close_provider(self) -> None:
        """Close the TTS provider session."""
        if self._provider is not None:
            try:
                await self._provider.close()
            except Exception:
                pass
            self._provider = None

    def resolve_voice(self, voice_id: str) -> str:
        """Resolve voice ID to a valid voice."""
        info = self._voice_manager.get_voice(voice_id)
        if info:
            return voice_id
        for v in MIMO_VOICE_LIST:
            if v["id"] == voice_id:
                return voice_id
        return self._config.get("default_voice", "mimo_default")

    def resolve_design_description(
        self, uid: str, get_user_settings,
        design_description: Optional[str] = None,
    ) -> str:
        """Resolve the voice design description for the given uid.

        ``design_description``（非空）优先——WebUI 试听一键保存（v2.2.5）
        合成页「设计描述」实时 override，保证"试听的即保存的"；否则回退
        该设计音色 per-voice description（v2.2.9 起从配置
        ``design_style_pool`` 读取——配置面板联动权威数据源，留空 = 用
        全局）> 注册表旧描述（惰性迁移并入池）> 配置 design_voice_description。

        描述可填 style_examples 分类名（方案 A 精确引用），do_tts 设计分支
        自动补全词表提示与画面感例句。
        """
        if str(design_description or "").strip():
            return str(design_description).strip()
        uset = get_user_settings(uid)
        current_voice = self.resolve_voice(uset["voice"])
        # 配置池权威（联动 conf_schema）
        entry = self._config.get_design_pool_entry(current_voice)
        if entry is not None:
            desc = entry.get("description", "").strip()
            if desc:
                return desc
            # 条目存在但描述为空 = 显式清空 → 回退全局
            return self._config.design_voice_description.strip()
        # 惰性迁移：注册表旧描述（/voicegen 写入）→ 池
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}
        if str(current_voice_info.get("model", "")).lower() == "voicedesign":
            legacy = str(
                current_voice_info.get("description", "") or ""
            ).strip()
            if legacy:
                self._config.upsert_design_pool_entry(current_voice, legacy)
                return legacy
        return self._config.design_voice_description.strip()

    def resolve_synthesis_target(
        self, uid: str, get_user_settings, uset: Optional[dict] = None
    ) -> tuple[str, Optional[str], str, Optional[str]]:
        """Resolve final voice, model, mode, and clone audio path."""
        if uset is None:
            uset = get_user_settings(uid)
        mode = normalize_tts_mode(uset.get("tts_mode", "default"))
        current_voice = self.resolve_voice(uset["voice"])
        current_voice_info = self._voice_manager.get_voice(current_voice) or {}

        if mode == "clone":
            # 当前选中音色优先（对齐 design 语义）：用户 /voiceclone <名> 切换
            # 的音色为准；config.clone_voice_id 仅作兜底（兼容老用法）。
            if str(current_voice_info.get("model", "")).lower() == "voiceclone":
                clone_audio_path = self._voice_manager.get_clone_audio_path(
                    current_voice
                )
                if clone_audio_path:
                    return (
                        current_voice,
                        self._config.clone_model,
                        mode,
                        clone_audio_path,
                    )
            clone_voice_id = self._config.clone_voice_id.strip()
            if clone_voice_id:
                clone_audio_path = self._voice_manager.get_clone_audio_path(
                    clone_voice_id
                )
                if clone_audio_path:
                    return (
                        clone_voice_id,
                        self._config.clone_model,
                        mode,
                        clone_audio_path,
                    )
            raise RuntimeError(
                '当前已切换到"克隆"输出，但未找到可用的本地参考音频。请先执行 /voiceclone <ID> <音频路径>。'
            )

        if mode == "design":
            description = self.resolve_design_description(
                uid, get_user_settings, uset.get("design_description")
            )
            if description:
                return "", self._config.design_model, mode, None
            raise RuntimeError(
                '当前已切换到"设计"输出，但未配置 design_voice_description，也未选中带描述的设计音色。'
            )

        custom_model = str(current_voice_info.get("model", "")).lower()
        if custom_model == "voiceclone":
            clone_audio_path = self._voice_manager.get_clone_audio_path(current_voice)
            if clone_audio_path:
                return (
                    current_voice,
                    self._config.clone_model,
                    "clone",
                    clone_audio_path,
                )
            raise RuntimeError(
                f"当前音色 {current_voice} 是克隆音色，但未找到可用参考音频。请重新执行 /voiceclone {current_voice} <音频路径>。"
            )

        if custom_model == "voicedesign":
            description = self.resolve_design_description(
                uid, get_user_settings, uset.get("design_description")
            )
            if description:
                return "", self._config.design_model, "design", None
            raise RuntimeError(
                f"当前音色 {current_voice} 是设计音色，但缺少可用描述文本。请重新执行 /voicegen {current_voice} <描述>。"
            )

        return current_voice, None, mode, None

    def _map_sing_voice_candidate(self, candidate: str) -> str:
        """唱歌音色候选映射：风格库名 → 该组绑定 voice；预置音色/其他值原样返回。"""
        name = str(candidate or "").strip()
        if not name or any(v["id"] == name for v in MIMO_VOICE_LIST):
            return name
        group = self._config.find_sing_style_by_name(name)
        if group and group.get("voice"):
            return str(group["voice"]).strip()
        return name

    def build_prompt(
        self,
        uid: str,
        get_user_settings,
        emotion_override: Optional[str] = None,
        uset: Optional[dict] = None,
    ) -> str:
        """Build the user-role control prompt.

        Args:
            uset: 已合并 settings_override 的设置副本；None 时回读持久化设置。
                  传入合并副本是必须的：否则 /mimo_say、WebUI 的单次参数
                  覆盖不会进入控制提示词（v2.1.2 修复）。
        """
        if uset is None:
            uset = get_user_settings(uid)
        style = self._config.style_hint
        return build_control_prompt(
            emotion=emotion_override
            if emotion_override is not None
            else (uset["emotion"] or None),
            speed=uset["speed"],
            pitch=uset["pitch"],
            breath=uset["breath"],
            sing=False,
            stress=uset["stress"],
            laughter=uset["laughter"],
            pause=uset["pause"],
            dialect=uset["dialect"],
            volume=uset["volume"],
            style_hint=style or None,
        )

    def resolve_clone_style_prompt(
        self, voice_id: str, override: str = ""
    ) -> str:
        """Resolve the clone style control text for the given voice.

        ``override``（非空）优先——WebUI 试听一键保存（v2.2.6）合成页
        「克隆音色风格控制」实时 override（仅本次合成不落库），保证"试听的
        即保存的"；否则回退该克隆音色 per-voice style_prompt（v2.2.8 起
        从配置 ``clone_style_pool`` 读取——配置面板联动权威数据源）>
        配置 clone_style_prompt。

        兼容迁移：pool 无该音色但注册表旧条目（v2.2.7 写入的
        style_prompt）存在时，惰性并入 pool（config 联动）并返回。
        """
        if str(override or "").strip():
            return str(override).strip()
        entry = self._config.get_clone_pool_entry(voice_id)
        if entry is not None:
            value = entry.get("style", "").strip()
            if value:
                return value
            # 条目存在但风格为空 = 显式清空 → 回退全局（与"留空=用全局"一致）
            return self._config.clone_style_prompt.strip()
        # 惰性迁移：v2.2.7 registry per-voice 旧数据 → pool
        info = self._voice_manager.get_voice(voice_id) or {}
        if str(info.get("model", "")).lower() == "voiceclone":
            legacy = str(info.get("style_prompt", "") or "").strip()
            legacy_tags = str(info.get("audio_tags", "") or "").strip()
            if legacy or legacy_tags:
                self._config.upsert_clone_pool_entry(
                    voice_id, legacy, legacy_tags
                )
                return legacy
        return self._config.clone_style_prompt.strip()

    def resolve_clone_audio_tags(self, voice_id: str, override: str = "") -> str:
        """Resolve the clone audio tags text for the given voice.

        ``override``（非空）优先——WebUI 试听（v2.2.7）实时 override；
        否则回退该克隆音色 per-voice audio_tags（v2.2.8 起从配置
        ``clone_style_pool`` 读取，联动权威数据源）> 全局 clone_audio_tags。
        """
        if str(override or "").strip():
            return str(override).strip()
        entry = self._config.get_clone_pool_entry(voice_id)
        if entry is not None:
            value = entry.get("audio_tags", "").strip()
            if value:
                return value
            # 条目存在但标签为空 = 显式清空 → 回退全局
            return self._config.clone_audio_tags.strip()
        # 惰性迁移：v2.2.7 registry per-voice 旧数据 → pool
        info = self._voice_manager.get_voice(voice_id) or {}
        if str(info.get("model", "")).lower() == "voiceclone":
            legacy_tags = str(info.get("audio_tags", "") or "").strip()
            legacy_style = str(info.get("style_prompt", "") or "").strip()
            if legacy_tags or legacy_style:
                self._config.upsert_clone_pool_entry(
                    voice_id, legacy_style, legacy_tags
                )
                return legacy_tags
        return self._config.clone_audio_tags.strip()

    def build_clone_prompt(
        self,
        base_prompt: str,
        style_prompt: Optional[str] = None,
        audio_tags: Optional[str] = None,
    ) -> str:
        """Build clone-specific prompt with style and audio tags.

        ``style_prompt`` 为已解析的克隆风格控制文本（调用方
        ``resolve_clone_style_prompt`` 已处理 override > per-voice > 全局
        的回退链）；缺省（None）时回退读全局 clone_style_prompt，与旧
        调用行为一致；显式传空字符串表示"无风格增强"（零追加）。

        ``audio_tags`` 同理（``resolve_clone_audio_tags`` 已处理
        override > per-voice > 全局；缺省 None 读全局，显式空 = 零标签）。
        """
        if style_prompt is None:
            style_prompt = self._config.clone_style_prompt
        style_prompt = str(style_prompt or "").strip()
        # 风格示例池方案 A（§14.9 P2）：精确等于示例池分类名 → 条目直取
        # （全部 words 词表提示 + 例句注入，与 design 同构）
        entry = match_style_entry_by_name(style_prompt, self._config.style_examples)
        if entry:
            words = [
                w for w in (entry.get("words") or []) if str(w or "").strip()
            ]
            parts = [style_prompt]
            hint = style_words_to_hint(words)
            if hint:
                parts.append(hint)
            examples = [
                e for e in (entry.get("examples") or []) if str(e or "").strip()
            ][:2]
            if examples:
                parts.append("参考示例：" + "；".join(examples))
            style_prompt = merge_prompt_parts(*parts)
            logger.info(
                "MiMO TTS: clone style entry matched: %s (words=%s, examples=%d)",
                entry.get("name"),
                words,
                len(examples),
            )
        else:
            # 风格词表赋能（v2.2.0）：克隆风格文本中的官方词（温柔/磁性…）
            # 自动提取并追加结构化提示，让服务端以词表语言理解风格
            style_words = extract_style_words(style_prompt)
            if style_words:
                style_prompt = merge_prompt_parts(
                    style_prompt, style_words_to_hint(style_words)
                )
                logger.info("MiMO TTS: clone style words enhanced: %s", style_words)
                # 风格示例池（§14.9 P2）：命中词对应例句并入（零 LLM）
                examples = match_style_examples(
                    style_prompt, self._config.style_examples
                )
                if examples:
                    style_prompt = merge_prompt_parts(
                        style_prompt, "参考示例：" + "；".join(examples)
                    )
                    logger.info(
                        "MiMO TTS: clone style examples matched: %s", examples
                    )
        if audio_tags is None:
            audio_tags = self._config.clone_audio_tags
        audio_tags = str(audio_tags or "").strip()

        tag_prompt = ""
        if audio_tags:
            normalized_tags = re.sub(r"[，、]+", " ", audio_tags)
            normalized_tags = re.sub(r"\s+", " ", normalized_tags).strip()
            if normalized_tags:
                tag_prompt = f"音频标签：{normalized_tags}"

        return merge_prompt_parts(base_prompt, style_prompt, tag_prompt)

    def resolve_clone_audio_path(self, raw_path: str) -> Path:
        """Resolve reference audio path with path traversal protection."""
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return Path(text)

        raw = Path(text)
        plugin_dir = Path(__file__).resolve().parent.parent
        data_clone_dir = self._data_dir / "clone"
        legacy_clone_dir = plugin_dir / "clone"

        allowed_roots: list[Path] = [
            data_clone_dir,
            legacy_clone_dir,
        ]

        candidates: list[Path] = []

        if raw.is_absolute():
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

        raise PermissionError(
            f"路径 {raw_path!r} 解析后不在允许的克隆音频目录范围内。"
            f"请将参考音频放入: {data_clone_dir}"
        )

    async def do_tts(
        self,
        text: str,
        uid: str,
        get_user_settings,
        get_effective_audio_format,
        format_override: Optional[str] = None,
        emotion_override: Optional[str] = None,
        settings_override: Optional[dict] = None,
    ) -> Optional[Path]:
        """Run TTS and return the audio file path."""
        provider = self.ensure_provider()
        if not provider:
            raise RuntimeError("API Key 未配置。请在配置中设置 api_key。")

        uset = get_user_settings(uid)
        if settings_override:
            uset: dict = {**uset, **settings_override}
        prompt = self.build_prompt(
            uid, get_user_settings, emotion_override=emotion_override, uset=uset
        )
        requested_fmt = format_override or get_effective_audio_format(uid)
        fmt = requested_fmt

        sing_voice_override = uset.get("sing_voice_override")
        if uset["sing"] and sing_voice_override:
            current_voice = self.resolve_voice(
                self._map_sing_voice_candidate(sing_voice_override)
            )
            uset["voice"] = current_voice
        elif uset["sing"]:
            is_custom_voice = uset["voice"] != self._config.default_voice
            if not is_custom_voice:
                sing_voice_cfg = self._config.sing_voice.strip()
                if sing_voice_cfg:
                    current_voice = self.resolve_voice(
                        self._map_sing_voice_candidate(sing_voice_cfg)
                    )
                    uset["voice"] = current_voice
        if uset["sing"]:
            # 唱歌链路编排已模块化至 tts/sing.py
            final_text, prompt = await prepare_sing(
                self, text, uset, uid, get_user_settings, emotion_override, prompt
            )
        else:
            # Markdown 符号清洗（唱歌歌词豁免）：上游 LLM 常输出 **加粗**
            # 等符号，TTS 会原样读出；保留 (风格) 与 [音频标签]
            final_text = strip_markdown_symbols(text)

        log_tts_text(uid, uset.get("tts_mode", "default"), uset["sing"], final_text)

        if uset["sing"]:
            # 唱歌仅 mimo-v2.5-tts（预置音色）支持：强制回退 default 模型，
            # 跳过 design/clone 路由与其 prompt 增强；自定义克隆/设计音色 ID
            # 不被基础模型接受，需兜底到预置音色（sing_voice > default_voice）。
            voice_id = uset.get("voice") or ""
            if not any(v["id"] == voice_id for v in MIMO_VOICE_LIST):
                for raw_candidate in (
                    self._config.sing_voice.strip(),
                    self._config.default_voice.strip(),
                    "mimo_default",
                ):
                    candidate = self._map_sing_voice_candidate(raw_candidate)
                    if candidate and any(v["id"] == candidate for v in MIMO_VOICE_LIST):
                        voice_id = candidate
                        break
                uset["voice"] = voice_id
            model_override = None
            mode = "default"
            clone_audio_path = None
            logger.info(
                "MiMO TTS: singing forces default model with preset voice=%s", voice_id
            )
        else:
            voice_id, model_override, mode, clone_audio_path = (
                self.resolve_synthesis_target(uid, get_user_settings, uset=uset)
            )
            if mode == "clone":
                prompt = self.build_clone_prompt(
                    prompt,
                    style_prompt=self.resolve_clone_style_prompt(
                        voice_id, uset.get("clone_style_prompt")
                    ),
                    audio_tags=self.resolve_clone_audio_tags(
                        voice_id, uset.get("clone_audio_tags")
                    ),
                )
            elif mode == "design":
                design_description = self.resolve_design_description(
                    uid, get_user_settings, uset.get("design_description")
                )
                # 方案 A（§14.5）：设计描述精确等于示例池分类名 → 条目直取，
                # 用该条目全部 words 生成词表提示 + 全部例句注入（快速切换 name）
                entry = match_style_entry_by_name(
                    design_description, self._config.style_examples
                )
                if entry:
                    words = [w for w in (entry.get("words") or []) if str(w or "").strip()]
                    parts = [design_description]
                    hint = style_words_to_hint(words)
                    if hint:
                        parts.append(hint)
                    examples = [
                        e for e in (entry.get("examples") or []) if str(e or "").strip()
                    ][:2]
                    if examples:
                        parts.append("参考示例：" + "；".join(examples))
                    design_description = merge_prompt_parts(*parts)
                    logger.info(
                        "MiMO TTS: voicedesign style entry matched: %s "
                        "(words=%s, examples=%d)",
                        entry.get("name"),
                        words,
                        len(examples),
                    )
                else:
                    # 自由文本链路：官方词自动提取追加结构化提示
                    design_words = extract_style_words(design_description)
                    if design_words:
                        design_description = merge_prompt_parts(
                            design_description,
                            style_words_to_hint(design_words),
                        )
                        logger.info(
                            "MiMO TTS: voicedesign style words enhanced: %s",
                            design_words,
                        )
                        # 风格示例池（§14 导演模式先导，P1）：命中词对应的
                        # 画面感例句直接并入描述（"参考示例：…"），零 LLM
                        examples = match_style_examples(
                            design_description, self._config.style_examples
                        )
                        if examples:
                            design_description = merge_prompt_parts(
                                design_description,
                                "参考示例：" + "；".join(examples),
                            )
                            logger.info(
                                "MiMO TTS: style examples matched: %s", examples
                            )
                prompt = merge_prompt_parts(design_description, prompt)
                # 官方 voicedesign 智能润色参数（仅设计模式生效）；
                # 与插件 LLM 润色同时开启时提示二选一，避免双重润色
                if self._config.optimize_text_preview:
                    if self._config.enable_voice_polish:
                        logger.warning(
                            "MiMO TTS: optimize_text_preview 与 LLM 音色润色同时开启，"
                            "可能双重润色，建议在配置中二选一"
                        )
                    logger.info(
                        "MiMO TTS: optimize_text_preview=true (voicedesign 官方润色)"
                    )
            elif mode == "default" and self._config.tts_example_inject:
                # 风格示例池普通 TTS 注入（§14.9 P2，默认关）：按 emotion →
                # 官方词映射匹配示例池，命中即并入 user 控制通道（零 LLM）
                emotion = str(uset.get("emotion") or "").strip().lower()
                tag = EMOTION_TO_TAG.get(emotion)
                if tag:
                    examples = match_style_examples(
                        tag, self._config.style_examples
                    )
                    if examples:
                        prompt = merge_prompt_parts(
                            prompt, "参考示例：" + "；".join(examples)
                        )
                        logger.info(
                            "MiMO TTS: tts style examples matched: %s (emotion=%s)",
                            examples,
                            emotion,
                        )

        # 导演模式（§16.10 切片）：仅 default 且非唱歌；开关关闭时零改动
        if (
            mode == "default"
            and not uset.get("sing")
            and self._config.director_enabled
        ):
            before = prompt
            prompt = apply_director_to_prompt(prompt, uset)
            if prompt != before:
                logger.info(
                    "MiMO TTS: director prompt applied mode=%s",
                    uset.get("director_mode"),
                )

        raw = await provider.synthesize(
            text=final_text,
            voice=voice_id or None,
            control_prompt=prompt if prompt else None,
            audio_format=fmt,
            model=model_override,
            clone_audio_path=clone_audio_path,
            temperature=self._config.temperature,
            top_p=self._config.top_p,
            optimize_text_preview=(
                self._config.optimize_text_preview and mode == "design"
            ),
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

        tmp_dir = self._data_dir / "temp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        out = tmp_dir / f"mimo_{ts}.{actual_fmt}"
        out.write_bytes(raw)
        return out
