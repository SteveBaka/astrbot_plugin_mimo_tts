# -*- coding: utf-8 -*-
"""角色库命令：/char（查询公开；add/set/del 仅管理员）"""

from __future__ import annotations

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult

from ..core.director_characters import character_to_package, parse_char_fields

CHAR_USAGE = (
    "用法:\n"
    "  /char — 列出启用中的角色\n"
    "  /char show <名> — 查看角色摘要\n"
    "  /char add id=<id> name=<名> voice=<音色> character=<身份> [guidance=<指导>] [scene=<场景>]\n"
    "  /char set <名> name=… voice=… character=… guidance=… scene=… enabled=true|false\n"
    "  /char del <名> — 删除角色（管理员）\n"
    "应用角色: /direct <角色名> 或 /direct once <角色名>\n"
    "也可在插件配置「导演模式 → 角色库」JSON 中维护，保存即生效"
)


def _extract_args(event: AstrMessageEvent) -> str:
    raw = str(event.message_str or "").strip()
    m = re.match(r"^/?char(?:@[^\s]+)?(?:\s+(?P<rest>.*))?$", raw, re.IGNORECASE)
    return (m.group("rest") or "").strip() if m else raw


def _store(plugin):
    return getattr(plugin, "director_characters", None)


def _is_admin(event: AstrMessageEvent) -> bool:
    try:
        return bool(event.is_admin())
    except Exception:
        return False


_FIELD_KEYS = (
    "id",
    "name",
    "voice",
    "character",
    "guidance",
    "baseline_guidance",
    "scene",
    "enabled",
)


def _parse_fields(text: str) -> dict:
    """解析 key=value（值可含空格，以下一个 key= 为界）。"""
    return parse_char_fields(text)


async def handle_char(plugin, event: AstrMessageEvent):
    """/char [show|add|set|del <名>] — 角色库查询与管理"""
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
                "角色库为空。可用 /char add id=… name=… voice=… character=… 添加，"
                "或在配置面板「角色库」JSON 中维护。"
            )
            return
        lines = [f"启用中的角色（数据源: {store.source}）:"]
        for e in entries:
            lines.append("· " + store.summary_line(e))
        lines.append("应用: /direct <角色名>　详情: /char show <名>")
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
            f"启用: {'是' if entry.get('enabled', True) else '否'}\n"
            f"应用: /direct {entry['name']}"
            + (f"\n摘要: {pkg.summary()}" if pkg else "")
        )
        return

    if low == "add" or low.startswith("add "):
        if not _is_admin(event):
            yield MessageEventResult().message("该命令仅管理员可用。")
            return
        fields = _parse_fields(arg[3:].strip() if low.startswith("add ") else "")
        if (
            not fields.get("id")
            or not fields.get("name")
            or not fields.get("character")
        ):
            yield MessageEventResult().message(
                "用法: /char add id=<id> name=<名> voice=<音色> character=<身份> [guidance=…]\n"
                "例: /char add id=xiaoyin name=小茵 voice=茉莉 character=邻家学姐，说话轻"
            )
            return
        entry, mode = store.upsert_entry(fields)
        if not entry:
            yield MessageEventResult().message(f"添加失败: {mode}")
            return
        logger.info("MiMO TTS: character %s id=%s via /char", mode, entry.get("id"))
        verb = "已更新" if mode == "updated" else "已添加"
        yield MessageEventResult().message(
            f"{verb}角色: {store.summary_line(entry)}\n应用: /direct {entry['name']}"
        )
        return

    if low.startswith("set "):
        if not _is_admin(event):
            yield MessageEventResult().message("该命令仅管理员可用。")
            return
        rest = arg[4:].strip()
        name = rest.split(None, 1)[0] if rest else ""
        payload = rest[len(name) :].strip() if name else ""
        fields = _parse_fields(payload)
        if not name or not fields:
            yield MessageEventResult().message(
                "用法: /char set <名> name=… voice=… character=… guidance=… scene=… enabled=true|false"
            )
            return
        entry, err = store.update_fields(name, fields)
        if not entry:
            yield MessageEventResult().message(f"更新失败: {err}")
            return
        yield MessageEventResult().message(f"已更新角色: {store.summary_line(entry)}")
        return

    if low.startswith("del ") or low.startswith("delete ") or low.startswith("rm "):
        if not _is_admin(event):
            yield MessageEventResult().message("该命令仅管理员可用。")
            return
        for prefix in ("del ", "delete ", "rm "):
            if low.startswith(prefix):
                name = arg[len(prefix) :].strip()
                break
        else:
            name = ""
        if not name:
            yield MessageEventResult().message("用法: /char del <名>")
            return
        entry, err = store.delete_entry(name)
        if not entry:
            yield MessageEventResult().message(f"删除失败: {err}")
            return
        logger.info("MiMO TTS: character deleted id=%s via /char", entry.get("id"))
        yield MessageEventResult().message(
            f"已删除角色: {entry.get('name')}（{entry.get('id')}）\n"
            "会话中已应用的配置在下次合成时会降级为内联文案。"
        )
        return

    if low == "reload":
        yield MessageEventResult().message(
            "无需 /char reload：配置面板保存「角色库」JSON 或使用 /char add/set/del 后立即生效。"
        )
        return

    yield MessageEventResult().message(CHAR_USAGE)
