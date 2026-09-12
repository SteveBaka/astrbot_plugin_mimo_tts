# -*- coding: utf-8 -*-
"""导演模式命令：/direct（公开，即时类）"""

from __future__ import annotations

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.director_assets import list_builtin_scene_names
from ..core.director_characters import character_to_package, looks_like_character_name
from ..core.director_package import dumps_package, loads_package
from ..core.director_parser import match_builtin_scene, parse_director_input

DIRECTOR_USAGE = (
    "用法: /direct <场景名|角色名|三维稿> — 设置会话常驻场景（sticky，持续生效）\n"
    "     /direct once <场景名|角色名|三维稿> — 仅下一次合成生效（pending，优先）\n"
    "     /direct — 查看当前导演场景\n"
    "     /direct off — 清除常驻与一次性场景\n"
    "内置场景: " + "、".join(list_builtin_scene_names()) + "\n"
    "也可粘贴完整稿（角色：… / 场景：… / 指导：…）；"
    "开启「LLM 自由解析」后可直接输入自然语言场景描述"
)


def _match_character(plugin, body: str):
    """角色库精确匹配（场景优先；短名且无三维标签才查）。"""
    if not plugin.config.get("director_characters_enabled", False):
        return None
    store = getattr(plugin, "director_characters", None)
    if store is None:
        return None
    if not looks_like_character_name(body):
        return None
    # 内置场景优先于角色
    if match_builtin_scene(body):
        return None
    entry = store.match_name(body)
    if not entry:
        return None
    return character_to_package(entry), entry


def _maybe_bind_voice(plugin, uset: dict, entry: dict) -> str:
    """会话音色仍为默认时绑定角色音色；已自定义则不覆盖。"""
    voice = str(entry.get("voice") or "").strip()
    if not voice:
        return ""
    current = str(uset.get("voice") or "").strip()
    default = str(plugin.config.get("default_voice", "") or "mimo_default").strip()
    if current and current != default and current != "mimo_default":
        return f"保留当前音色 {current}；角色默认为 {voice}"
    try:
        resolved = plugin.synth.resolve_voice(voice) if plugin.synth else voice
    except Exception:
        resolved = voice
    if resolved:
        uset["voice"] = resolved
        return f"已切换音色 → {resolved}"
    return ""


def _extract_args(event: AstrMessageEvent) -> str:
    raw = str(event.message_str or "").strip()
    m = re.match(r"^/?direct(?:@[^\s]+)?(?:\s+(?P<rest>.*))?$", raw, re.IGNORECASE)
    return (m.group("rest") or "").strip() if m else raw


def _format_director_status(uset: dict) -> str:
    sticky = loads_package(uset.get("director_sticky"))
    pending = loads_package(uset.get("director_pending"))
    if not sticky and not pending:
        return ""
    lines: list[str] = []
    if sticky:
        lines.append(f"会话常驻: {sticky.summary()}")
    if pending:
        lines.append(f"仅下一次（优先）: {pending.summary()}")
    lines.append("清除: /direct off　临时一次: /direct once <场景>")
    return "\n".join(lines)


async def handle_direct(plugin, event: AstrMessageEvent):
    """/direct <场景|三维稿> | once | off — 双层管理常驻与一次性场景"""
    arg = _extract_args(event)
    uid, uset = plugin._get_event_settings(event)

    if not plugin.config.get("director_enabled", False):
        yield MessageEventResult().message(
            "导演模式未启用。请在插件配置「导演模式」中打开 director_enabled。"
        )
        return

    if not arg:
        status = _format_director_status(uset)
        if status:
            yield MessageEventResult().message(f"当前导演场景:\n{status}")
        else:
            yield MessageEventResult().message(
                "当前未设置导演场景。\n" + DIRECTOR_USAGE
            )
        return

    low = arg.lower()
    if low in ("off", "clear", "关闭"):
        uset["director_sticky"] = ""
        uset["director_pending"] = ""
        uset["director_mode"] = ""
        uset["director_payload"] = ""
        plugin._persist_current_state()
        yield MessageEventResult().message("已清除本对话导演场景（常驻 + 一次性）。")
        return

    mode = "session"
    body = arg
    if low.startswith("once ") or low == "once":
        mode = "once"
        body = arg[4:].strip()
        if not body:
            yield MessageEventResult().message(
                "用法: /direct once <场景名|角色名|三维稿>"
            )
            return
    # 可选别名：/direct @小茵 ≡ /direct 小茵
    body = body.lstrip("@").strip()

    voice_note = ""
    matched_char = _match_character(plugin, body)
    if matched_char:
        pkg, entry = matched_char
        voice_note = _maybe_bind_voice(plugin, uset, entry)
        logger.info(
            "MiMO TTS: character apply uid=%s id=%s layer=%s voice=%s",
            uid,
            entry.get("id"),
            "pending" if mode == "once" else "sticky",
            entry.get("voice") or "",
        )
    else:
        pkg = parse_director_input(body)
    if not pkg and plugin.config.get("director_parse_llm", False):
        from ..core.director_llm import parse_director_with_llm

        try:
            pkg = await parse_director_with_llm(plugin, body, uid)
        except Exception as e:
            logger.warning("MiMO TTS: director LLM parse error: %s", e)
            pkg = None
    if not pkg:
        llm_on = bool(plugin.config.get("director_parse_llm", False))
        if llm_on:
            tail = "（已尝试 LLM 自由解析仍未成功，请精简描述或改用内置场景/角色/三维稿）"
        else:
            tail = "（可开启配置「LLM 自由解析」后用自然语言描述）"
        char_hint = ""
        store = getattr(plugin, "director_characters", None)
        if store and plugin.config.get("director_characters_enabled", False):
            names = [e["name"] for e in store.list_enabled()[:8]]
            if names:
                char_hint = "\n可用角色: " + "、".join(names)
        yield MessageEventResult().message(
            "无法识别该场景。\n"
            "可用内置场景: "
            + "、".join(list_builtin_scene_names())
            + char_hint
            + "\n或使用三维稿:\n角色：…\n场景：…\n指导：…\n"
            + tail
        )
        return

    payload = dumps_package(pkg)
    if not payload:
        yield MessageEventResult().message("场景过长，已拒绝写入。请精简后重试。")
        return

    # 双层互不覆盖：session 只写 sticky；once 只写 pending
    if mode == "session":
        uset["director_sticky"] = payload
    else:
        uset["director_pending"] = payload
    plugin._persist_current_state()
    logger.info(
        "MiMO TTS: director set uid=%s layer=%s scene=%s source=%s",
        uid,
        "sticky" if mode == "session" else "pending",
        pkg.scene_name or "(custom)",
        pkg.guidance_source,
    )
    if mode == "session":
        msg = (
            f"已设置会话常驻场景: {pkg.summary()}\n"
            "不影响已设置的一次性场景；关闭: /direct off"
        )
    else:
        msg = (
            f"已设置一次性场景（优先于会话常驻，用尽后回落）: {pkg.summary()}\n"
            "清除全部: /direct off"
        )
    if voice_note:
        msg += f"\n{voice_note}"
    yield MessageEventResult().message(msg)
