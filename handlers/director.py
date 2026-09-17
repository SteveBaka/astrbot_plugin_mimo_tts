# -*- coding: utf-8 -*-
"""导演模式命令：/direct（公开，即时类）"""

from __future__ import annotations

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.director_assets import list_builtin_scene_names
from ..core.director_characters import (
    apply_character_binding,
    character_to_package,
    clear_director_layer,
    format_director_applied,
    looks_like_character_name,
)
from ..core.director_composer import format_director_status
from ..core.director_package import dumps_package
from ..core.director_parser import match_builtin_scene, parse_director_input

DIRECTOR_USAGE = (
    "用法: /direct <场景名|角色名|三维稿> — 设置会话常驻配置（sticky，持续生效）\n"
    "     /direct once <场景名|角色名|三维稿> — 设置一次性配置（pending，优先于常驻，用尽回落）\n"
    "     /direct — 查看当前导演配置\n"
    "     /direct off — 清除常驻与一次性配置（有快照时恢复）\n"
    "     /direct off sticky|pending — 只清一层；两层都空后才恢复快照\n"
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


def _extract_args(event: AstrMessageEvent) -> str:
    raw = str(event.message_str or "").strip()
    m = re.match(r"^/?direct(?:@[^\s]+)?(?:\s+(?P<rest>.*))?$", raw, re.IGNORECASE)
    return (m.group("rest") or "").strip() if m else raw


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
        status = format_director_status(uset)
        if status:
            yield MessageEventResult().message(f"当前导演配置:\n{status}")
        else:
            yield MessageEventResult().message(
                "当前未设置导演配置。\n" + DIRECTOR_USAGE
            )
        return

    low = arg.lower()
    if (
        low in ("off", "clear", "关闭")
        or low.startswith("off ")
        or low.startswith("clear ")
    ):
        layer = "all"
        if low.startswith("off ") or low.startswith("clear "):
            tail = low.split(None, 1)[1].strip() if " " in low else ""
            if tail in ("sticky", "常驻"):
                layer = "sticky"
            elif tail in ("pending", "once", "一次性"):
                layer = "pending"
            elif tail not in ("", "all", "全部"):
                yield MessageEventResult().message(
                    "用法: /direct off [sticky|pending]\n"
                    "省略层 = 清除常驻 + 一次性；有快照且两层都空时才恢复音色/模式。"
                )
                return
        result = clear_director_layer(uset, layer)
        plugin._persist_current_state()
        if layer == "all":
            msg = "已清除本对话导演配置（常驻 + 一次性）。"
        else:
            label = "常驻" if layer == "sticky" else "一次性"
            msg = f"已清除本对话导演配置（{label}）。"
        if result.get("restored"):
            msg += (
                f"\n已恢复进入导演前状态：音色 {result.get('voice') or '—'}"
                f"，输出模式 {result.get('tts_mode') or 'default'}"
            )
        elif layer != "all":
            msg += "\n另一层仍生效；两层都清空后才会恢复快照。"
        yield MessageEventResult().message(msg)
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
        voice_note = apply_character_binding(plugin, uset, entry)
        logger.info(
            "MiMO TTS: character apply uid=%s id=%s layer=%s voice=%s source=command",
            uid,
            entry.get("id"),
            "pending" if mode == "once" else "sticky",
            uset.get("voice") or entry.get("voice") or "",
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
            tail = (
                "（已尝试 LLM 自由解析仍未成功，请精简描述或改用内置场景/角色/三维稿）"
            )
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
        "MiMO TTS: director set uid=%s layer=%s scene=%s source=%s character_id=%s",
        uid,
        "sticky" if mode == "session" else "pending",
        pkg.scene_name or "(custom)",
        pkg.guidance_source,
        pkg.character_id or "-",
    )
    msg = format_director_applied(
        plugin,
        pkg,
        mode,
        voice_id=str(uset.get("voice") or ""),
        voice_note=voice_note,
    )
    yield MessageEventResult().message(msg)
