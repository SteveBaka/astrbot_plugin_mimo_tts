# -*- coding: utf-8 -*-
"""Voice Studio WebUI 的 REST API 处理器（从 main.py 迁出，模块化重构）。

所有函数签名为 async def api_xxx(plugin)，由 main.py 注册时以
functools.partial(api_xxx, plugin_instance) 绑定插件实例。
"""

from __future__ import annotations

from functools import partial

import base64
import re as _re
from pathlib import Path

from .tts.synthesis import normalize_tts_mode


def _plugin_version() -> str:
    """Read version from metadata.yaml (plugin root is parent of this file's package)."""
    try:
        import yaml

        meta_path = Path(__file__).resolve().parent / "metadata.yaml"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
            v = str(meta.get("version", "")).strip()
            if v:
                return v
    except Exception:
        pass
    return "unknown"


async def api_health(plugin):
    from quart import jsonify

    return jsonify({"status": "ok", "version": _plugin_version()})


async def api_get_config(plugin):
    from quart import jsonify

    return jsonify({"config": dict(plugin.config._flat)})


async def api_update_config(plugin):
    from quart import jsonify, request

    body = await request.json
    allowed_keys = set(plugin.config._SCHEMA_DEFAULTS.keys())
    for k, v in body.items():
        if k in allowed_keys:
            plugin.config.set(k, v)
    return jsonify({"status": "ok"})


async def api_tts_synthesize(plugin):
    from quart import jsonify, request

    body = await request.json
    text = str(body.get("text", ""))[:5000]
    if not text.strip():
        return jsonify({"error": "文本不能为空"}), 400

    uid = str(body.get("uid", "webui"))[:100]
    plugin.plog.info(
        "WebUI-TTS",
        f"合成请求 uid={uid} len={len(text)} polish={body.get('voice_polish', False)}",
    )

    # LLM 润色（仅当请求中明确启用时）
    if body.get("voice_polish"):
        text = await plugin._polish_text_with_llm(text, uid)

    overrides = {}
    for key in ("emotion", "speed", "pitch", "voice", "breath", "stress",
                "laughter", "pause", "dialect", "volume", "tts_mode",
                "sing", "sing_style", "sing_voice_override",
                "design_description", "clone_style_prompt"):
        if key in body and body[key] is not None:
            overrides[key] = body[key]

    emotion_override = None
    if "emotion" in overrides:
        if overrides["emotion"] == "auto":
            emotion_override = None
        elif overrides["emotion"] == "off":
            overrides["emotion"] = ""
        else:
            emotion_override = overrides.pop("emotion")

    try:
        audio_path = await plugin._do_tts(
            text, uid, emotion_override=emotion_override,
            settings_override=overrides or None,
        )
        if audio_path:
            audio_bytes = audio_path.read_bytes()
            b64 = base64.b64encode(audio_bytes).decode()
            fmt = audio_path.suffix.lstrip(".")
            mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg"}.get(
                fmt, "audio/wav"
            )
            return jsonify({"audio_b64": b64, "format": fmt, "mime": mime})
        return jsonify({"error": "合成失败"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


async def api_list_voices(plugin):
    from quart import jsonify

    from .core.constants import MIMO_VOICE_LIST

    builtin = [{**v, "type": "default"} for v in MIMO_VOICE_LIST]
    registered = plugin._voice_manager.list_voices()
    custom = []
    for v in registered:
        model = v.get("model", "voiceclone")
        vtype = "design" if model == "voicedesign" else "clone"
        custom.append({
            "id": v.get("voice_id", ""),
            "name": v.get("name", ""),
            "type": vtype,
        })
    return jsonify({
        "builtin": builtin,
        "registered": custom,
        "all": builtin + custom,
    })


async def api_clone_init(plugin):
    from quart import jsonify, request

    body = await request.json
    voice_id = body.get("voice_id", "").strip()
    voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", voice_id)
    if not voice_id:
        return jsonify({"error": "缺少 voice_id"}), 400
    plugin._pending_clone_voice_id = voice_id
    return jsonify({"status": "ok"})


async def api_clone_file(plugin):
    from quart import jsonify, request

    voice_id = getattr(plugin, "_pending_clone_voice_id", "")
    if not voice_id:
        return jsonify({"error": "请先调用 clone-init"}), 400
    voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", voice_id)
    if not voice_id:
        return jsonify({"error": "无效的 voice_id"}), 400
    body = await request.json
    file_b64 = body.get("file_b64", "")
    filename = body.get("filename", "audio.wav")
    if not file_b64:
        return jsonify({"error": "缺少音频数据"}), 400
    if len(file_b64) > 20 * 1024 * 1024:
        return jsonify({"error": "文件过大（最大约 15MB）"}), 400
    suffix = Path(filename).suffix.lower()
    if suffix not in (".mp3", ".wav"):
        return jsonify({"error": "仅支持 mp3/wav 格式"}), 400
    clone_dir = plugin._data_dir / "clone"
    clone_dir.mkdir(parents=True, exist_ok=True)
    save_path = clone_dir / f"{voice_id}{suffix}"
    audio_bytes = base64.b64decode(file_b64)
    save_path.write_bytes(audio_bytes)
    plugin._voice_manager.register_voice(
        voice_id, name=voice_id, model="voiceclone", audio_path=str(save_path),
    )
    plugin._pending_clone_voice_id = ""
    return jsonify({"status": "ok", "voice_id": voice_id, "path": str(save_path)})


async def api_design_voice(plugin):
    """注册设计音色 / 保存 per-voice 设计描述（WebUI 一键保存 + 设计池行内编辑）。

    description 允许为空（设计池行内清空 = 回退全局 design_voice_description）；
    v2.2.9 起写入配置「设计音色风格控制池」（与配置面板联动权威数据源）。
    """
    from quart import jsonify, request

    body = await request.json
    voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("voice_id", "").strip())
    description = body.get("description", "").strip()[:500]
    name = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("name", voice_id).strip())[:50]
    if not voice_id:
        return jsonify({"error": "缺少 voice_id"}), 400
    plugin._voice_manager.register_voice(
        voice_id, name=name, model="voicedesign", description=description,
    )
    # v2.2.9：写入配置「设计音色风格控制池」（与配置面板联动权威数据源）
    plugin.config.upsert_design_pool_entry(voice_id, description)
    return jsonify({"status": "ok", "voice_id": voice_id})


async def api_design_style_pool(plugin):
    """设计音色风格控制池（v2.2.9）：全局描述 + 各设计音色 per-voice 描述。

    数据源为配置 ``design_style_pool``（与配置面板联动）；描述可填
    style_examples 分类名（方案 A），供 WebUI 音色管理页查看/行内编辑。
    """
    from quart import jsonify

    registered = {
        v.get("voice_id", ""): v.get("name", v.get("voice_id", ""))
        for v in plugin._voice_manager.list_voices()
        if str(v.get("model", "")).lower() == "voicedesign"
    }
    voices = []
    for entry in plugin.config.design_style_pool:
        if entry.get("name") in registered:
            voices.append({
                "voice_id": entry.get("name", ""),
                "name": registered[entry.get("name", "")],
                "description": entry.get("description", ""),
            })
    voices.sort(key=lambda x: x["voice_id"])
    return jsonify({
        "global": {
            "description": str(
                plugin.config.get("design_voice_description", "") or ""
            ),
        },
        "voices": voices,
    })


async def api_clone_style(plugin):
    """保存/更新克隆音色的 per-voice 风格控制（WebUI 试听一键保存，C2）。

    仅允许对已注册的克隆音色更新 style_prompt / audio_tags 字段；v2.2.8 起
    写入配置 ``clone_style_pool``（与配置面板联动权威数据源），不再写
    注册表条目（register_voice 保留原 name / audio_path 不动）。
    """
    from quart import jsonify, request

    body = await request.json
    voice_id = _re.sub(
        r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("voice_id", "").strip()
    )
    style = body.get("style", "").strip()[:500]
    audio_tags = body.get("audio_tags", "").strip()[:500]
    if not voice_id:
        return jsonify({"error": "缺少 voice_id"}), 400
    info = plugin._voice_manager.get_voice(voice_id)
    if not info or str(info.get("model", "")).lower() != "voiceclone":
        return jsonify({"error": f"未找到克隆音色: {voice_id}"}), 404
    plugin.config.upsert_clone_pool_entry(voice_id, style, audio_tags)
    return jsonify({"status": "ok", "voice_id": voice_id})


async def api_clone_style_pool(plugin):
    """克隆音色风格控制池（v2.2.7）：全局风格/标签 + 各克隆音色 per-voice 记录。

    供 WebUI 音色管理页查看/管理"音色风格控制标签池"——展示每个克隆
    音色保存的风格控制与音频标签（空 = 用全局）。v2.2.8 起数据源为配置
    ``clone_style_pool``（与配置面板联动）。
    """
    from quart import jsonify

    registered = {
        v.get("voice_id", ""): v.get("name", v.get("voice_id", ""))
        for v in plugin._voice_manager.list_voices()
        if str(v.get("model", "")).lower() == "voiceclone"
    }
    voices = []
    for entry in plugin.config.clone_style_pool:
        if entry.get("name") in registered:
            voices.append({
                "voice_id": entry.get("name", ""),
                "name": registered[entry.get("name", "")],
                "style_prompt": entry.get("style", ""),
                "audio_tags": entry.get("audio_tags", ""),
            })
    voices.sort(key=lambda x: x["voice_id"])
    return jsonify({
        "global": {
            "style_prompt": str(
                plugin.config.get("clone_style_prompt", "") or ""
            ),
            "audio_tags": str(
                plugin.config.get("clone_audio_tags", "") or ""
            ),
        },
        "voices": voices,
    })


async def api_delete_voice(plugin):
    from quart import jsonify, request

    body = await request.json
    voice_id = body.get("voice_id", "")
    if not voice_id:
        return jsonify({"error": "缺少 voice_id"}), 400
    ok = plugin._voice_manager.remove_voice(voice_id)
    if ok:
        # 联动清理：删除音色时同步移除克隆/设计风格控制池条目；
        # 清理失败不影响删除本身（防御性，v2.2.9）
        for cleaner in ("remove_clone_pool_entry", "remove_design_pool_entry"):
            try:
                fn = getattr(plugin.config, cleaner)
                fn(voice_id)
            except Exception:
                pass
        return jsonify({"status": "ok"})
    return jsonify({"error": f"未找到音色: {voice_id}"}), 404


async def api_list_sessions(plugin):
    from quart import jsonify

    sessions = {}
    for uid, settings in plugin.user_state.user_settings.items():
        sessions[uid] = {
            "settings": settings,
            "format": plugin.user_state.user_format.get(uid, "wav"),
            "umo": plugin.user_state.user_umo.get(uid, ""),
        }
    return jsonify({"sessions": sessions})


async def api_update_session(plugin):
    from quart import jsonify, request

    body = await request.json
    uid = body.get("uid", "")
    settings = body.get("settings", {})
    if not uid:
        return jsonify({"error": "缺少 uid"}), 400
    allowed = {"voice", "emotion", "speed", "pitch", "tts_mode", "tts_enabled",
               "text_enabled", "text_async", "enable_segmentation",
               "enable_voice_polish", "sing_style"}
    filtered = {k: v for k, v in settings.items() if k in allowed}
    uset = plugin.user_state.get_settings(uid, normalize_tts_mode)
    uset.update(filtered)
    plugin.user_state.persist()
    return jsonify({"status": "ok"})


async def api_delete_session(plugin):
    from quart import jsonify, request

    body = await request.json
    uid = body.get("uid", "")
    if not uid:
        return jsonify({"error": "缺少 uid"}), 400
    plugin.user_state.user_settings.pop(uid, None)
    plugin.user_state.user_format.pop(uid, None)
    plugin.user_state.persist()
    return jsonify({"status": "ok"})


async def api_reset_session(plugin):
    from quart import jsonify, request

    body = await request.json
    uid = body.get("uid", "")
    if not uid:
        return jsonify({"error": "缺少 uid"}), 400
    plugin.user_state.restore(uid)
    return jsonify({"status": "ok"})


async def api_list_emotions(plugin):
    from quart import jsonify

    from .core.constants import SUPPORTED_EMOTIONS

    return jsonify({"emotions": list(SUPPORTED_EMOTIONS)})


async def api_get_constants(plugin):
    from quart import jsonify

    from .core.constants import MIMO_VOICE_LIST, SUPPORTED_AUDIO_FORMATS, SUPPORTED_EMOTIONS

    return jsonify({
        "voices": MIMO_VOICE_LIST,
        "emotions": list(SUPPORTED_EMOTIONS),
        "formats": list(SUPPORTED_AUDIO_FORMATS),
    })


async def api_get_logs(plugin):
    from quart import jsonify, request

    args = request.args
    limit = min(int(args.get("limit", 200)), 500)
    level = args.get("level")
    logs = plugin.plog.read_logs(limit=limit, level=level)
    return jsonify({"logs": logs, "enabled": plugin.plog.enabled})


async def api_log_stats(plugin):
    from quart import jsonify

    return jsonify(plugin.plog.get_stats())


def register_web_apis(context, plugin) -> None:
    """注册 Voice Studio 插件页全部 REST 端点。"""
    p = "astrbot_plugin_mimo_tts"
    routes = [
        ("config", api_get_config, ["GET"], "获取插件配置"),
        ("config/update", api_update_config, ["POST"], "更新插件配置"),
        ("tts", api_tts_synthesize, ["POST"], "TTS 语音合成"),
        ("voices", api_list_voices, ["GET"], "获取音色列表"),
        ("voices/clone-init", api_clone_init, ["POST"], "初始化克隆"),
        ("voices/clone-file", api_clone_file, ["POST"], "上传克隆音频"),
        ("voices/design", api_design_voice, ["POST"], "注册设计音色"),
        ("voices/clone-style", api_clone_style, ["POST"], "保存克隆音色风格"),
        ("voices/clone-style-pool", api_clone_style_pool, ["GET"], "克隆音色风格控制池"),
        ("voices/design-style-pool", api_design_style_pool, ["GET"], "设计音色风格控制池"),
        ("voices/delete", api_delete_voice, ["POST"], "删除音色"),
        ("sessions", api_list_sessions, ["GET"], "获取会话配置列表"),
        ("sessions/update", api_update_session, ["POST"], "更新会话配置"),
        ("sessions/delete", api_delete_session, ["POST"], "删除会话配置"),
        ("sessions/reset", api_reset_session, ["POST"], "重置会话配置"),
        ("emotions", api_list_emotions, ["GET"], "获取情感列表"),
        ("constants", api_get_constants, ["GET"], "获取常量数据"),
        ("health", api_health, ["GET"], "健康检查"),
        ("logs", api_get_logs, ["GET"], "获取插件日志"),
        ("logs/stats", api_log_stats, ["GET"], "日志统计"),
    ]
    for path, fn, methods, desc in routes:
        context.register_web_api(f"/{p}/{path}", partial(fn, plugin), methods, desc)
