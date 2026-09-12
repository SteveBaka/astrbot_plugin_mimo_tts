# -*- coding: utf-8 -*-
"""角色库命令：/char（查询公开；reload 管理员）"""

from __future__ import annotations

import re

from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.director_characters import character_to_package

CHAR_USAGE = (
    "用法:\n"
    "  /char — 列出启用中的角色\n"
    "  /char show <名> — 查看角色摘要\n"
    "  /char reload — 重读 characters.json（管理员）\n"
    "应用角色: /direct <角色名> 或 /direct once <角色名>\n"
    "权威文件: plugin_data/astrbot_plugin_mimo_tts/director/characters.json"
)


def _extract_args(event: AstrMessageEvent) -> str:
    raw = str(event.message_str or "").strip()
    m = re.match(r"^/?char(?:@[^\s]+)?(?:\s+(?P<rest>.*))?$", raw, re.IGNORECASE)
    return (m.group("rest") or "").strip() if m else raw


def _store(plugin):
    return getattr(plugin, "director_characters", None)


async def handle_char(plugin, event: AstrMessageEvent):
    """/char [show <名>|reload] — 角色库查询与重载"""
    arg = _extract_args(event)
    store = _store(plugin)
    if store is None:
        yield MessageEventResult().message("角色库未初始化。")
        return

    if not plugin.config.get("director_enabled", False):
        yield MessageEventResult().message(
            "导演模式未启用。请在插件配置「导演模式」中打开 director_enabled。"
        )
        return

    if not plugin.config.get("director_characters_enabled", False):
        yield MessageEventResult().message(
            "角色库未启用。请在插件配置中打开「启用角色库」。"
        )
        return

    low = arg.lower()
    if not arg or low in ("list", "列表"):
        entries = store.list_enabled()
        if not entries:
            yield MessageEventResult().message(
                "角色库为空。可编辑 plugin_data 下 director/characters.json 后 /char reload。"
            )
            return
        lines = ["启用中的角色:"]
        for e in entries:
            lines.append("· " + store.summary_line(e))
        lines.append("应用: /direct <角色名>")
        yield MessageEventResult().message("\n".join(lines))
        return

    if low.startswith("show "):
        name = arg[5:].strip()
        entry = store.get(name)
        if not entry:
            yield MessageEventResult().message(f"未找到角色: {name}\n" + CHAR_USAGE)
            return
        pkg = character_to_package(entry)
        voice = entry.get("voice") or "—"
        yield MessageEventResult().message(
            f"角色 {entry['name']}（{entry['id']}）\n"
            f"音色: {voice}\n"
            f"身份: {entry['character']}\n"
            f"指导: {entry.get('baseline_guidance') or '—'}\n"
            f"场景: {entry.get('scene') or '—'}\n"
            f"应用: /direct {entry['name']}"
            + (f"\n摘要: {pkg.summary()}" if pkg else "")
        )
        return

    if low == "reload":
        try:
            ok = bool(event.is_admin())
        except Exception:
            ok = False
        if not ok:
            yield MessageEventResult().message("该命令仅管理员可用。")
            return
        n = store.reload()
        yield MessageEventResult().message(f"已重读角色库，共 {n} 条。")
        return

    yield MessageEventResult().message(CHAR_USAGE)
