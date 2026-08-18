# -*- coding: utf-8 -*-
"""自然语言触发唱歌：正则快路径（方案 B）+ LLM 工具兜底（方案 A）。

两路天然互斥：正则命中即 stop_event，LLM 管线不再执行；
正则未命中的自由措辞由 LLM 工具解析兜底（sing-mode-feature.md §12）。
"""

from __future__ import annotations

import asyncio
import re
import time

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Record

from ..core.constants import MIMO_VOICE_LIST

NL_SING_STYLE_RE = re.compile(
    r"^(?:请)?用(?P<style>[\u4e00-\u9fffA-Za-z0-9_]{1,12})的(?:声线|声音|嗓音|音色)(?:来)?唱(?P<lyrics>.+)$",
    re.IGNORECASE,
)
NL_SING_BARE_RE = re.compile(r"^(?:请)?唱(?:一首|一段)?(?P<lyrics>.+)$")

# 歌词长度上限（与 /sing 链路一致的输入卫生）
_NL_LYRICS_MAX = 500


def match_style(plugin, style_name: str):
    """风格名解析层（§12.5）：返回 ("group", 组dict) / ("voice", 音色名) / (None, None)。"""
    name = str(style_name or "").strip()
    if not name:
        return None, None
    group = plugin.config.find_sing_style_by_name(name)
    if group:
        return "group", group
    if any(v["id"] == name for v in MIMO_VOICE_LIST):
        return "voice", name
    return None, None


def build_sing_overrides(plugin, style_name: str, free_as_prompt: bool) -> tuple[dict, str]:
    """构造唱歌 overrides。

    free_as_prompt=True 时（LLM 工具路径），未命中组/音色的风格词
    降级为一次性提示词（如「温柔甜美」→ sing_prompt_override）。
    """
    overrides: dict = {"sing": True}
    kind, hit = match_style(plugin, style_name)
    if kind == "group":
        overrides["sing_style_override"] = hit["name"]
        return overrides, "风格组「%s」" % hit["name"]
    if kind == "voice":
        overrides["sing_voice_override"] = hit
        return overrides, "音色「%s」" % hit
    raw = str(style_name or "").strip()
    if free_as_prompt and raw:
        overrides["sing_prompt_override"] = raw[:200]
        return overrides, "自由风格「%s」" % raw[:20]
    return overrides, "默认链路"


def check_cooldown(plugin, uid: str) -> tuple[bool, float]:
    """会话级冷却检查，返回 (是否放行, 剩余秒数)。"""
    cooldown = plugin.config.nl_sing_cooldown
    last = plugin._nl_sing_last.get(uid, 0.0)
    elapsed = time.time() - last
    if cooldown and elapsed < cooldown:
        return False, cooldown - elapsed
    return True, 0.0


async def handle_nl_sing(plugin, event: AstrMessageEvent) -> None:
    """正则快路径：唤醒消息匹配「用X的声线唱<歌词>」等句式时直接演唱（零 LLM 依赖）。"""
    if not plugin.config.nl_sing_enabled:
        return
    if not getattr(event, "is_wake", False):
        return
    text = str(event.message_str or "").strip()
    if not text or text.startswith("/"):
        return

    m = NL_SING_STYLE_RE.match(text)
    style_name = ""
    if m:
        style_name = m.group("style").strip()
        lyrics = m.group("lyrics").strip()
    else:
        mb = NL_SING_BARE_RE.match(text)
        if not mb:
            return
        lyrics = mb.group("lyrics").strip()
        # 无风格名句式防误触：内容太短或疑问句（"你会唱歌吗"类）不触发
        if len(lyrics) < 4 or lyrics.rstrip().endswith(("？", "?", "吗", "呢")):
            return

    lyrics = lyrics.strip("\"'“”‘’ \u3000")
    if len(lyrics) < 2:
        return

    uid, _ = plugin._get_event_settings(event)

    ok, remain = check_cooldown(plugin, uid)
    if not ok:
        event.stop_event()
        await event.send(
            MessageChain().message("唱歌冷却中，请约 %d 秒后再试" % max(1, int(remain)))
        )
        return

    # 快路径严格模式：未命中组/音色直接提示（不猜测意图）
    if style_name:
        kind, _hit = match_style(plugin, style_name)
        if kind is None:
            event.stop_event()
            names = "、".join(s["name"] for s in plugin.config.sing_styles)
            await event.send(
                MessageChain().message(
                    "未找到唱歌风格或音色「%s」。%s"
                    % (
                        style_name,
                        ("可用风格组：" + names) if names else "风格库为空，可在插件配置「唱歌优化」中添加。",
                    )
                )
            )
            return
    overrides, _desc = build_sing_overrides(plugin, style_name, free_as_prompt=False)

    event.stop_event()
    plugin._nl_sing_last[uid] = time.time()
    await _sing_and_send(plugin, event, lyrics, uid, overrides)


async def handle_nl_sing_tool(plugin, event: AstrMessageEvent, style: str, lyrics: str) -> str:
    """LLM 工具兜底路径：自由措辞由 LLM 解析为 (style, lyrics) 后调用。

    立即返回、后台合成（避免阻塞 agent 循环数十秒）；
    未命中的风格名降级为一次性提示词。必须返回 str（llm_tool 规范）。
    """
    if not plugin.config.nl_sing_enabled or not plugin.config.nl_sing_tool:
        return "唱歌功能未开启。"
    lyrics = str(lyrics or "").strip()[:_NL_LYRICS_MAX]
    style = str(style or "").strip()[:50]
    if len(lyrics) < 2:
        return "歌词为空，无法演唱。"

    uid, _ = plugin._get_event_settings(event)

    ok, remain = check_cooldown(plugin, uid)
    if not ok:
        return "唱歌冷却中，请约 %d 秒后再试。" % max(1, int(remain))

    overrides, desc = build_sing_overrides(plugin, style, free_as_prompt=True)
    plugin._nl_sing_last[uid] = time.time()
    preview = lyrics[:20] + ("…" if len(lyrics) > 20 else "")
    asyncio.create_task(_sing_and_send(plugin, event, lyrics, uid, overrides))
    return "正在演唱（%s）：%s" % (desc, preview)


async def _sing_and_send(plugin, event, lyrics: str, uid: str, overrides: dict) -> None:
    """后台合成并发送音频。"""
    try:
        audio_path = await plugin._do_tts(lyrics, uid, settings_override=overrides)
        if audio_path:
            chain_msg = MessageChain()
            chain_msg.chain.append(Record.fromFileSystem(str(audio_path)))
            await event.send(chain_msg)
        else:
            await event.send(MessageChain().message("唱歌合成失败。"))
    except Exception as e:
        await event.send(MessageChain().message("! %s" % e))
