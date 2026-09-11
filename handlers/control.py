# -*- coding: utf-8 -*-
"""TTS control handlers: /tts_on, /tts_off, /text, /tts_restore, /tts_help."""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, MessageEventResult


async def handle_tts_off(plugin, event: AstrMessageEvent):
    """/tts_off — 关闭当前对话自动 TTS"""
    _, uset = plugin._get_event_settings(event)
    uset["tts_enabled"] = False
    plugin._persist_current_state()
    yield MessageEventResult().message(
        "[✓] 已关闭当前对话的自动 TTS。\n如需重新开启，可使用 /tts_on"
    )


async def handle_tts_on(plugin, event: AstrMessageEvent):
    """/tts_on — 开启当前对话自动 TTS"""
    _, uset = plugin._get_event_settings(event)
    uset["tts_enabled"] = True
    plugin._persist_current_state()
    yield MessageEventResult().message(
        "[✓] 已开启当前对话的自动 TTS。\n"
        "仅恢复当前对话的自动朗读，不会修改插件配置面板中的全局自动 TTS 开关。"
    )


async def handle_text(plugin, event: AstrMessageEvent):
    """/text [on|off] — 设置当前对话自动 TTS 是否同步发送文字"""
    arg = plugin._parse_cmd(event, "/text").lower()
    _, uset = plugin._get_event_settings(event)

    if not arg:
        current = uset.get("text_enabled", None)
        current_state = (
            plugin.config.send_text_with_tts if current is None else bool(current)
        )
        source = "当前对话" if current is not None else "插件全局默认"
        yield MessageEventResult().message(
            f"当前对话文字同步: {'开' if current_state else '关'}\n"
            f"当前生效来源: {source}\n"
            "用法: /text <on|off>"
        )
        return

    if arg not in ("on", "off"):
        yield MessageEventResult().message("用法: /text <on|off>")
        return

    uset["text_enabled"] = arg == "on"
    plugin._persist_current_state()
    yield MessageEventResult().message(
        f"[✓] 已将当前对话的文字同步设置为: {'开' if uset['text_enabled'] else '关'}\n"
        "仅影响当前聊天的自动 TTS，不会修改插件配置面板中的 send_text_with_tts。"
    )


async def handle_tts_help(plugin, event: AstrMessageEvent):
    """/tts_help — 快速查看常用 TTS 指令"""
    sing_lines = [
        "/sing <歌词>  - 唱一首歌（单次生效，不影响日常语音）",
        "/sing -音色名 <歌词>  - 指定音色，如 /sing -冰糖 小星星",
        "/sing (风格) <歌词>  - 括号风格简写，如 /sing (温柔) 晚风轻拂",
    ]
    if plugin.config.sing_styles:
        sing_lines += [
            "/sing -s 风格组 <歌词>  - 用风格组唱，如 /sing -s 小雪 晚风轻拂",
            '/sing -p "提示词" <歌词>  - 本次按提示词唱（含空格请加引号）',
            "/singstyle list  - 查看全部风格组（管理）",
            "/singstyle set <组名>  - 切换本对话风格组（管理）",
            "/singstyle reset  - 恢复跟随全局（管理）",
        ]
    else:
        sing_lines.append(
            "（风格组未配置：在插件配置「唱歌优化」的 sing_styles 添加后解锁 -s/-p 与 /singstyle）"
        )
    lines = [
        "MiMO TTS 常用指令:",
        "",
        *sing_lines,
        "",
        "/mimo_say <文本>  - 即时合成语音",
        "/direct <场景|三维稿>  - 导演场景（会话常驻；off 清除；需配置开启导演模式）",
        "/direct once <场景>  - 仅下一次合成使用该场景",
        "/ttsconfig  - 查看当前会话配置",
        "/tts_restore  - 将当前会话配置恢复为插件默认设置",
        "/tts_<on/off>  - 开启或关闭当前对话自动 TTS",
        "/text <on|off>  - 设置当前对话是否同步发送文字",
        "/ttsswitch <default|design|clone>  - 切换输出模式",
        "/voice [音色ID]  - 查看/切换音色",
        "/voiceclone <ID> <参考音频路径>  - 声音克隆（可选: /voiceclone <音色名> 切换 /cancel <音色名> 删除）",
        "/emotion <情感名|auto|off>  - 设置情感",
        "/ttsformat <mp3|wav|ogg>  - 设置音频格式",
    ]
    yield MessageEventResult().message("\n".join(lines))


async def handle_tts_restore(plugin, event: AstrMessageEvent):
    """/tts_restore — 恢复当前会话配置为插件默认值"""
    uid, _ = plugin._get_event_settings(event)
    plugin._restore_user_state(uid)
    yield MessageEventResult().message(
        "[✓] 已将当前对话的 TTS 配置恢复为插件默认设置。\n"
        "可使用 /ttsconfig 查看当前生效结果，或用 /tts_help 快速查看常用指令。"
    )
