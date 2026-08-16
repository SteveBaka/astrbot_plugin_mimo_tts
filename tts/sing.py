# -*- coding: utf-8 -*-
"""唱歌模式编排：风格链解析、组预设覆盖、标签注入与演唱指导润色。

数据流（v2.2.14 双通道）见 docs/sing-mode-feature.md §6b：
  - 标签通道（assistant 开头 (唱歌 词…)）：喂服务端风格标签解析器，
    官方语法、实测不唱出；标签来自 用户括号词 > 组 style_tags > 词表提取 > LLM 筛选；
  - user 控制指令（自由文本通道）：画面感演唱描述（官方示例同构）。

音频标签 [xx] 在唱歌中会被唱出（实测），一律不进 assistant 文本。
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import TYPE_CHECKING, Optional

from astrbot.api import logger

from ..core.config import resolve_sing_style
from ..core.style_lib import (
    SING_TAG_PROMPT,
    SING_TAGS_MAX,
    collect_sing_tags,
    filter_official_tags,
)
from ..core.text_utils import (
    apply_singing_tag,
    extract_leading_styles,
    strip_audio_tags,
)

if TYPE_CHECKING:
    from .synthesis import TTSSynthesizer

# 润色/标签筛选 LLM 结果缓存：{(provider_id, purpose, key) -> (expire_ts, text)}
# 相同歌词+相同风格在 TTL 内直接复用，重复唱歌零 LLM 延迟。
_POLISH_CACHE: dict[tuple, tuple[float, str]] = {}
_POLISH_CACHE_MAX = 64


def _polish_cache_key(provider_id: str, purpose: str, lyrics: str, style_desc: str) -> str:
    digest = hashlib.sha1(
        f"{provider_id}|{purpose}|{lyrics}|{style_desc}".encode("utf-8")
    ).hexdigest()
    return digest


def _polish_cache_get(provider_id: str, purpose: str, lyrics: str, style_desc: str):
    key = (provider_id, purpose, _polish_cache_key(provider_id, purpose, lyrics, style_desc))
    entry = _POLISH_CACHE.get(key)
    if not entry:
        return None
    expire, text = entry
    if time.monotonic() > expire:
        _POLISH_CACHE.pop(key, None)
        return None
    return text


def _polish_cache_put(
    provider_id: str, purpose: str, lyrics: str, style_desc: str,
    text: str, ttl: int,
) -> None:
    if ttl <= 0:
        return
    key = (provider_id, purpose, _polish_cache_key(provider_id, purpose, lyrics, style_desc))
    if len(_POLISH_CACHE) >= _POLISH_CACHE_MAX:
        now = time.monotonic()
        for k in list(_POLISH_CACHE):
            if _POLISH_CACHE[k][0] <= now:
                _POLISH_CACHE.pop(k, None)
        if len(_POLISH_CACHE) >= _POLISH_CACHE_MAX:
            _POLISH_CACHE.pop(next(iter(_POLISH_CACHE)), None)
    _POLISH_CACHE[key] = (time.monotonic() + ttl, text)


async def prepare_sing(
    synth: "TTSSynthesizer",
    text: str,
    uset: dict,
    uid: str,
    get_user_settings,
    emotion_override: Optional[str],
    prompt: str,
) -> tuple[str, str]:
    """唱歌链路编排，返回 (final_text, prompt)。

    顺序（v2.2.14 双通道）：括号风格词提取 → 优先级链解析 → 组预设覆盖
    （voice/speed/pitch）→ 风格标签收集（用户括号词 > 组 style_tags >
    本地词表从描述提取 > LLM 筛选兜底）→ 演绎词/演唱指导走 user 通道 →
    assistant 开头 (唱歌 词…) 标签注入 → user 控制指令合并风格描述。
    """
    lyrics, bracket_styles = extract_leading_styles(text)
    named = (
        str(uset.get("sing_style_override") or "").strip()
        or str(uset.get("sing_style") or "").strip()
    )
    if named and synth._config.find_sing_style_by_name(named) is None:
        logger.warning(
            "MiMO TTS: sing style %r not found in library, falling back", named
        )
    style_text, static_tags, style_source, group = resolve_sing_style(
        synth._config.sing_styles,
        named,
        str(uset.get("sing_prompt_override") or ""),
        bracket_styles,
    )
    # 组预设覆盖（voice/speed/pitch，仅本次合成、不持久化）：
    # speed/pitch 写入 uset 后需重建控制 prompt；命令显式 -音色 优先于组 voice
    if group:
        if group.get("voice") and not uset.get("sing_voice_override"):
            uset["voice"] = synth.resolve_voice(group["voice"])
        prompt_changed = False
        if group.get("speed") is not None:
            uset["speed"] = float(group["speed"])
            prompt_changed = True
        if group.get("pitch") is not None:
            uset["pitch"] = int(group["pitch"])
            prompt_changed = True
        if prompt_changed:
            prompt = synth.build_prompt(
                uid,
                get_user_settings,
                emotion_override=emotion_override,
                uset=uset,
            )
    # ── 风格标签收集（标签通道，assistant 开头 (唱歌 词…)）──
    # 优先级：用户括号词 > 组 style_tags（显式，支持自定义词）> 本地词表
    # 从风格描述提取（官方词）；不足 2 词且开启歌词润色时 LLM 筛选兜底。
    source_mode = str(synth._config.sing_style_source or "prompt")
    style_tags: list[str] = []
    if source_mode == "tag":
        logger.warning(
            "MiMO TTS: sing_style_source=tag 已收窄（v2.2.0 实测矩阵：唱歌模式"
            "不识别 (唱歌 词…) 任何组合，朗读/杂音）——本次仅收集风格词记日志，"
            "assistant 只注入 (唱歌)，风格走 user 自然语言（建议切 prompt）"
        )
    if source_mode in ("tag", "prompt"):
        explicit_tags: list[str] = list(bracket_styles or [])
        if group:
            explicit_tags += list(group.get("style_tags") or [])
        style_tags = collect_sing_tags(
            explicit_tags, None, str(style_text or ""), max_tags=SING_TAGS_MAX
        )
        if (
            source_mode == "tag"
            and synth._config.sing_lyrics_polish
            and synth.lyrics_polisher
            and len(style_tags) < 2
        ):
            try:
                extra = await synth.lyrics_polisher(
                    lyrics, uid, str(style_text or ""), purpose="tag"
                )
                for w in filter_official_tags(
                    str(extra or "").split()
                ):
                    if w not in style_tags:
                        style_tags.append(w)
                    if len(style_tags) >= SING_TAGS_MAX:
                        break
            except Exception as e:
                logger.warning("MiMO TTS: style tag select failed: %s", e)
        if source_mode == "prompt":
            # prompt 模式：标签仅供日志，不注入 assistant 通道
            logger.info(
                "MiMO TTS: style source=prompt, collected tags=%s (not injected)",
                style_tags,
            )
            style_tags = []
    # 静态演绎词走 user 通道自然语言（官方两通道原则：自然语言控制 →
    # user content；实测 [xx] 紧跟 (唱歌) 会被当作歌词唱出）
    if static_tags:
        style_text = resolve_style_with_tags(style_text, static_tags)
    # 歌词 LLM 润色（user 通道，默认）：产出画面感演唱描述并入风格文本。
    # 辅助链路：标签筛选（purpose="tag"）已在上面执行过，缓存避免重复调用。
    if synth._config.sing_lyrics_polish and synth.lyrics_polisher:
        try:
            # 润色上下文：附实际生效音色/语速/音高，让指导与配置磨合（不并入 user prompt）
            from .synthesis import merge_prompt_parts

            polish_ctx = style_text
            extras = []
            if uset.get("voice"):
                extras.append("音色%s" % uset["voice"])
            if uset.get("speed") is not None and uset.get("speed") != 1.0:
                extras.append("语速%s" % uset["speed"])
            if uset.get("pitch"):
                extras.append("音高%+d" % uset["pitch"])
            if extras:
                polish_ctx = merge_prompt_parts(style_text, "，".join(extras))
            polished = await synth.lyrics_polisher(
                lyrics, uid, polish_ctx, purpose="direct"
            )
            if polished:
                from .synthesis import merge_prompt_parts

                style_text = merge_prompt_parts(style_text, polished)
        except Exception as e:
            logger.warning("MiMO TTS: lyrics polish failed, using raw: %s", e)
    # ── assistant 文本：唱歌模式只注入精确 (唱歌) 标签 ──
    # 实测矩阵（v2.2.0，五种括号写法 × 直连服务端）：
    #   (唱歌 温柔 甜美) 朗读+异常发音；(唱歌 温柔，甜美) 朗读+异常发音；
    #   (唱歌)(温柔)(甜美) 前半段杂音唱歌；(唱歌 温柔) 富有感情朗读；
    #   仅 (唱歌) 正常唱歌 —— 唱歌模式不识别任何风格标签组合，
    #   风格一律走 user 自然语言通道（prompt 模式）。tag 模式保留收集仅日志。
    final_text, _redundant = apply_singing_tag(lyrics)
    # 风格文本走官方 user 通道（自由文本：演绎词 + 画面感演唱描述）
    if style_text:
        from .synthesis import merge_prompt_parts

        prompt = merge_prompt_parts(prompt, style_text)
    logger.info(
        "MiMO TTS: sing style source=%s tags=%s static_tags=%s style_prompt=%s",
        style_source,
        style_tags,
        static_tags,
        bool(style_text),
    )
    return final_text, prompt


def resolve_style_with_tags(style_text: str, static_tags: list[str]) -> str:
    """演绎词并入风格文本（"演唱中自然融入轻笑、气声"）。"""
    from .synthesis import merge_prompt_parts

    return merge_prompt_parts(
        style_text, f"演唱中自然融入{'、'.join(static_tags)}"
    )


async def polish_lyrics_with_llm(
    plugin, lyrics: str, uid: str, style_desc: str, purpose: str = "direct"
) -> str:
    """唱歌 LLM 辅助（v2.2.14 双用途，purpose 决定模板与输出清洗）。

    - purpose="direct"（默认）：画面感演唱描述（官方 user 通道示例同构），
      注入 user 控制指令；失败/为空返回 ""（跳过注入）。
    - purpose="tag"：官方风格标签筛选（第 3 层兜底），输出经官方词表
      白名单过滤的词（空格分隔）；失败/为空返回 ""（回退纯 (唱歌) 或
      本地提取结果）。

    延迟优化（v2.2.13/14）：
    - 同歌词+同风格结果缓存（sing_polish_cache_ttl，默认 600s），重复唱歌
      零 LLM 延迟；缓存 key 含 provider/purpose/歌词/风格。
    - LLM 超时看门狗（sing_polish_timeout，默认 20s，0=不限）：超时降级，
      不让一次润色卡住整个唱歌流程。
    - 默认模板内置"禁止思考、直接输出"硬约束——AstrBot llm_generate 的
      kwargs 不透传请求体（_prepare_chat_payload 丢弃），插件侧只能走 prompt 层。

    隔离不变量（docs/sing-mode-feature.md §2.5/§11.3c）：
    llm_generate 裸调用，永不传 system_prompt/contexts。
    """
    # Provider 链：唱歌专用 > 通用润色 > 当前对话模型
    provider_id = (
        plugin.config.sing_polish_llm_provider
        or plugin.config.polish_llm_provider
    )
    if not provider_id:
        try:
            provider_id = await plugin.context.get_current_chat_provider_id(uid)
        except Exception:
            logger.warning("MiMO TTS: no provider for lyrics polish, skip")
            return ""

    purpose = purpose if purpose in ("direct", "tag") else "direct"
    ttl = int(plugin.config.sing_polish_cache_ttl or 0)
    timeout = int(plugin.config.sing_polish_timeout or 0)

    cached = _polish_cache_get(provider_id, purpose, lyrics, style_desc)
    if cached is not None:
        logger.info(
            "MiMO TTS: polish cache hit uid=%s purpose=%s (%d 字)",
            uid,
            purpose,
            len(cached),
        )
        return cached

    if purpose == "tag":
        tpl = plugin.config.sing_tag_prompt or SING_TAG_PROMPT
    else:
        tpl = plugin.config.sing_direct_prompt or (
            "你是一个专业的演唱指导。请根据【歌词】与【风格】，用一句 60 字以内的演唱描述，"
            "指导如何唱出理想效果。\n"
            "要求：\n"
            "1. 用\"像……一样\"的画面比喻点明整体气质（如\"像晨露一样清透\"），"
            "再给出明快/轻柔/活泼等语调基调，结尾带节奏或音高走向（如\"语速略快，句尾上扬\"）\n"
            "2. 与已配置的音色、语速、音高协调，顺势突出其长处，绝不给出冲突的节奏或音高指令\n"
            "3. 贴合人设与语境（撒娇/叙事/俏皮等），让描述具体可感\n"
            "4. 禁止出现\"收束/收紧/压低/减弱/收小\"等收窄类词汇（会导致声音压窄）\n"
            "5. 禁止时间轴分句（\"开头/中段/结尾\"）、禁止 [] 或 () 标签、不要出现歌词原文\n"
            "6. 不要思考、不要分析过程，第一句就是最终描述\n\n"
            "当前风格：{style}\n歌词：{text}"
        )
    style_line = style_desc or "未指定，保持自然演唱"
    prompt = tpl.replace("{text}", lyrics).replace("{style}", style_line)

    async def _call() -> str:
        resp = await plugin.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
        )
        return resp.completion_text or ""

    try:
        if timeout > 0:
            completion = await asyncio.wait_for(_call(), timeout=timeout)
        else:
            completion = await _call()
        if purpose == "tag":
            # 标签筛选：官方词表白名单过滤（防 LLM 幻觉词注入 assistant 括号）
            words = filter_official_tags(completion.replace("，", " ").split())
            if not words:
                logger.info("MiMO TTS: style tag select empty, keep local tags")
                return ""
            _polish_cache_put(provider_id, purpose, lyrics, style_desc, " ".join(words), ttl)
            plugin.plog.info(
                "Polish", "风格标签筛选 uid=%s -> %s" % (uid, " ".join(words))
            )
            return " ".join(words)
        # direct：画面感演唱描述清洗（剥标签 + 长度上限）
        direction = strip_audio_tags(completion.strip())[:200].strip()
        if direction:
            _polish_cache_put(provider_id, purpose, lyrics, style_desc, direction, ttl)
            plugin.plog.info(
                "Polish", "演唱描述 uid=%s %d 字（user 通道）" % (uid, len(direction))
            )
            return direction
        logger.info("MiMO TTS: empty polish direction, skip")
        return ""
    except asyncio.TimeoutError:
        logger.warning(
            "MiMO TTS: lyrics polish (purpose=%s) timeout after %ss, skip",
            purpose,
            timeout,
        )
        return ""
    except Exception as e:
        logger.warning("MiMO TTS: lyrics polish (purpose=%s) failed: %s", purpose, e)
        return ""
