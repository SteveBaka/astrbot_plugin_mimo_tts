# -*- coding: utf-8 -*-
"""导演模式可选 LLM 解析：自由描述 → ScenePackage（P3c B1）。

快路径（内置场景 / 三维标签）未命中时才调用；产物必须过
``sanitize_package``。失败返回 None，由调用方降级为无法识别。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Optional

from astrbot.api import logger

from .director_package import ScenePackage, sanitize_package

DIRECTOR_PARSE_PROMPT_DEFAULT = (
    "你是语音导演助手。把用户描述的朗读场景整理成 JSON，供 TTS 注入。\n"
    "只输出一个 JSON 对象，不要思考过程、不要 Markdown 代码围栏、不要解释。\n"
    "字段：\n"
    "- scene_name: 简短场景名（可空字符串）\n"
    "- character: 角色身份散文，1-2 句（可空）\n"
    "- scene: 场景/环境散文，1 句（可空）\n"
    "- guidance: 表演指导散文，可含「语速与顿挫 / 气声与实声 / 咬字肌理」要点，"
    "禁止写身体动作，禁止使用 [] 或 () 标签\n"
    "- style_words: 字符串数组，可为空；优先官方风格词如 磁性/温柔/深沉\n"
    "guidance 与 character 不要与 style_words 重复堆砌同义词。\n\n"
    "用户描述：{text}"
)

# 简单 TTL 缓存：key -> (expire_ts, package)
_PARSE_CACHE: dict[str, tuple[float, ScenePackage]] = {}
_PARSE_CACHE_MAX = 64


def extract_json_object(raw: str) -> Optional[dict[str, Any]]:
    """从 LLM 文本中提取第一个 JSON 对象；失败返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = text[start : end + 1]
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _cache_key(provider_id: str, tpl_hash: str, text: str) -> str:
    digest = hashlib.sha1(
        f"{provider_id}\x00{tpl_hash}\x00{text}".encode("utf-8")
    ).hexdigest()
    return digest


def _cache_get(key: str) -> Optional[ScenePackage]:
    item = _PARSE_CACHE.get(key)
    if not item:
        return None
    expire, pkg = item
    if time.time() >= expire:
        _PARSE_CACHE.pop(key, None)
        return None
    return pkg


def _cache_put(key: str, pkg: ScenePackage, ttl: int) -> None:
    if ttl <= 0:
        return
    while len(_PARSE_CACHE) >= _PARSE_CACHE_MAX:
        _PARSE_CACHE.pop(next(iter(_PARSE_CACHE)), None)
    _PARSE_CACHE[key] = (time.time() + ttl, pkg)


def clear_parse_cache() -> None:
    _PARSE_CACHE.clear()


async def parse_director_with_llm(
    plugin, text: str, uid: str
) -> Optional[ScenePackage]:
    """自由描述 → LLM JSON → ScenePackage；失败返回 None。"""
    raw = str(text or "").strip()
    if not raw:
        return None

    # Provider 链：导演专用 > 通用润色 > 当前对话（§16.10.3 / P3c-B2）
    provider_id = (
        plugin.config.director_parse_llm_provider
        or plugin.config.polish_llm_provider
    )
    if not provider_id:
        try:
            provider_id = await plugin.context.get_current_chat_provider_id(uid)
        except Exception:
            logger.warning("MiMO TTS: no provider for director parse, skip")
            return None
    if not provider_id:
        return None

    ttl = int(plugin.config.director_cache_ttl or 0)
    timeout = int(plugin.config.director_timeout or 0)
    tpl = plugin.config.director_parse_prompt or DIRECTOR_PARSE_PROMPT_DEFAULT
    tpl_hash = hashlib.sha1(tpl.encode("utf-8")).hexdigest()[:8]
    key = _cache_key(provider_id, tpl_hash, raw)
    cached = _cache_get(key)
    if cached is not None:
        logger.info(
            "MiMO TTS: director parse cache hit uid=%s scene=%s",
            uid,
            cached.scene_name or "(custom)",
        )
        return cached

    prompt = tpl.replace("{text}", raw)

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
    except asyncio.TimeoutError:
        logger.warning(
            "MiMO TTS: director parse timeout after %ss, skip", timeout
        )
        return None
    except Exception as e:
        logger.warning("MiMO TTS: director parse failed: %s", e)
        return None

    data = extract_json_object(completion)
    if not data:
        logger.info("MiMO TTS: director parse got non-JSON, skip")
        return None
    if not data.get("scene_name"):
        data = {**data, "scene_name": raw[:20]}
    data["guidance_source"] = "auto"
    pkg = sanitize_package(data)
    if not pkg:
        logger.info("MiMO TTS: director parse empty after sanitize, skip")
        return None
    _cache_put(key, pkg, ttl)
    logger.info(
        "MiMO TTS: director parse=json uid=%s scene=%s",
        uid,
        pkg.scene_name or "(custom)",
    )
    return pkg
