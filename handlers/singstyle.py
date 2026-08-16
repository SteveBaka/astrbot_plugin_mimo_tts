# -*- coding: utf-8 -*-
"""唱歌风格组管理: /singstyle show|list|set|reset"""

from __future__ import annotations

import re

from astrbot.api.event import AstrMessageEvent, MessageEventResult


def _format_styles(styles: list[dict]) -> str:
    if not styles:
        return "（风格库为空：请在插件配置「唱歌优化」的 sing_styles 中添加）"
    lines = []
    for s in styles:
        line = f"- {s['name']}：{s['style'] or '（无描述）'}"
        if s.get("tags"):
            line += f"　演绎 {'、'.join(s['tags'])}"
        if s.get("voice"):
            line += f"　音色 {s['voice']}"
        extra = []
        if s.get("speed") is not None:
            extra.append(f"语速 {s['speed']}")
        if s.get("pitch") is not None:
            extra.append(f"音高 {s['pitch']:+d}" if s["pitch"] else "音高 0")
        if extra:
            line += "　" + "·".join(extra)
        lines.append(line)
    return "\n".join(lines)


def _sub_arg(event: AstrMessageEvent, sub: str) -> str:
    """提取 /singstyle <sub> 之后的参数（兼容 @bot 后缀与无斜杠写法）。"""
    raw = str(event.message_str or "").strip()
    m = re.match(
        rf"^/?singstyle(?:@[^\s]+)?\s+{sub}(?:\s+(?P<rest>.*))?$",
        raw,
        re.IGNORECASE,
    )
    return (m.group("rest") or "").strip() if m else ""


async def handle_singstyle_show(plugin, event: AstrMessageEvent):
    """/singstyle show — 查看当前对话的唱歌风格设置"""
    _, uset = plugin._get_event_settings(event)
    current = str(uset.get("sing_style", "") or "")
    group = plugin.config.find_sing_style_by_name(current) if current else None
    if group:
        yield MessageEventResult().message(
            f"当前对话唱歌风格组: {group['name']}\n"
            f"风格: {group['style'] or '（无描述）'}"
            + (f"\n演绎词: {'、'.join(group['tags'])}" if group.get("tags") else "")
            + (f"\n绑定音色: {group['voice']}" if group.get("voice") else "")
            + "\n切换: /singstyle set <组名>　恢复默认: /singstyle reset"
        )
    elif current:
        yield MessageEventResult().message(
            f"当前对话选中了风格组「{current}」，但风格库中已不存在（配置可能已修改）。\n"
            "可用 /singstyle list 查看现有组，或 /singstyle reset 恢复默认。"
        )
    else:
        yield MessageEventResult().message(
            "当前对话未指定风格组（跟随默认唱歌链路，仅自动注入 (唱歌) 标签）。\n"
            "查看全部: /singstyle list　切换: /singstyle set <组名>"
        )


async def handle_singstyle_list(plugin, event: AstrMessageEvent):
    """/singstyle list — 列出全部可用的唱歌风格组"""
    _, uset = plugin._get_event_settings(event)
    styles = plugin.config.sing_styles
    raw = str(plugin.config.get("sing_styles") or "").strip()
    if not styles and raw and raw not in ("", "[]"):
        yield MessageEventResult().message(
            "⚠️ 唱歌风格库 JSON 格式错误（解析失败已回退空库）。\n"
            "请检查：最外层必须是数组 [ ]；引号用英文直引号；多组用逗号分隔。\n"
            "正确示例：[\"name\": 需为 [ {\"name\": \"小雪\"} ] 形式"
        )
        return
    current = str(uset.get("sing_style", "") or "")
    header = "唱歌风格库:" if styles else "唱歌风格库为空。"
    if current:
        header += f"（当前对话: {current}）"
    yield MessageEventResult().message(header + "\n" + _format_styles(styles))


async def handle_singstyle_set(plugin, event: AstrMessageEvent):
    """/singstyle set <组名> — 切换当前对话的唱歌风格组（持久保存）"""
    arg = _sub_arg(event, "set")
    if not arg:
        yield MessageEventResult().message(
            "用法: /singstyle set <组名>（查看可用组: /singstyle list）"
        )
        return
    group = plugin.config.find_sing_style_by_name(arg)
    if not group:
        yield MessageEventResult().message(
            f"未找到风格组「{arg}」。\n可用风格组:\n" + _format_styles(plugin.config.sing_styles)
        )
        return
    _, uset = plugin._get_event_settings(event)
    uset["sing_style"] = group["name"]
    plugin._persist_current_state()
    yield MessageEventResult().message(
        f"[✓] 当前对话唱歌风格组已设为「{group['name']}」（对后续 /sing 持续生效）。\n"
        f"风格: {group['style'] or '（无描述）'}"
        + (f"\n演绎词: {'、'.join(group['tags'])}" if group.get("tags") else "")
        + (f"\n绑定音色: {group['voice']}" if group.get("voice") else "")
        + "\n立即体验: /sing <歌词>　临时换组: /sing -s 其他组 <歌词>　恢复默认: /singstyle reset"
    )


async def handle_singstyle_reset(plugin, event: AstrMessageEvent):
    """/singstyle reset — 恢复当前对话默认唱歌链路"""
    _, uset = plugin._get_event_settings(event)
    uset["sing_style"] = ""
    plugin._persist_current_state()
    yield MessageEventResult().message(
        "[✓] 当前对话已恢复默认唱歌链路（仅自动注入 (唱歌) 标签，下次 /sing 生效）。"
    )
