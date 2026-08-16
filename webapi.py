# -*- coding: utf-8 -*-
"""Voice Studio WebUI 的 REST API 处理器（从 main.py 迁出，模块化重构）。

所有函数签名为 async def api_xxx(plugin)，由 main.py 注册时以
functools.partial(api_xxx, plugin_instance) 绑定插件实例。
"""

from __future__ import annotations

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
                "sing", "sing_style", "sing_voice_override"):
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
    from quart import jsonify, request

    body = await request.json
    voice_id = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("voice_id", "").strip())
    description = body.get("description", "").strip()[:500]
    name = _re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", body.get("name", voice_id).strip())[:50]
    if not voice_id or not description:
        return jsonify({"error": "缺少 voice_id 或描述"}), 400
    plugin._voice_manager.register_voice(
        voice_id, name=name, model="voicedesign", description=description,
    )
    return jsonify({"status": "ok", "voice_id": voice_id})


async def api_delete_voice(plugin):
    from quart import jsonify, request

    body = await request.json
    voice_id = body.get("voice_id", "")
    if not voice_id:
        return jsonify({"error": "缺少 voice_id"}), 400
    ok = plugin._voice_manager.remove_voice(voice_id)
    if ok:
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

