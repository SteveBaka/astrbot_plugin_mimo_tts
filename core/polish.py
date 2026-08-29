# -*- coding: utf-8 -*-
"""LLM 音色润色：提示词模板与润色调用。"""

from __future__ import annotations

from astrbot.api import logger

from .text_utils import strip_markdown_symbols

# 旧默认模板（等值命中即迁移到 POLISH_PROMPT_DEFAULT）
_POLISH_PROMPT_V1 = (
    "你是一个专业的语音润色专家。请在以下文本中适当添加 MiMO TTS 音频标签，"
    "让播报更自然生动。\n"
    "规则：\n"
    "1. 整体气质用开头风格标签表达，如 (温柔)、(磁性)、(活泼)、(严肃) 等，只加 1 个\n"
    "2. 关键语气处插入音频标签增强表现力，如 [深呼吸]、[叹气]、[轻笑]、[停顿]、"
    "[语速加快]、[语速放慢] 等\n"
    "3. 标签与文本情感一致、宁缺毋滥：整段最多 2-3 个音频标签\n"
    "4. 保持原文内容完全不变，只增删标签\n"
    "5. 不要添加任何解释、代码围栏或思考过程，第一行即润色结果\n\n"
    "原文：{text}"
)
_POLISH_PROMPT_V2 = _POLISH_PROMPT_V1.replace(
    "4. 保持原文内容完全不变，只增删标签",
    "4. 严格保持原文内容一字不变，只增删标签；禁止改写、缩写、扩写、"
    "替换任何词语或标点\n"
    "5. 输出必须是纯文本：禁止任何 Markdown 格式符号（**加粗**、*斜体*、"
    "# 标题、` 代码`、> 引用等），只输出纯文字",
).replace("5. 不要添加任何解释", "6. 不要添加任何解释")

# 标签示例对齐 MiMO 官方词表（哭笑/情绪/呼吸/停顿四类），优先有感染力的
# 标签，数量 1-3 防堆砌
POLISH_PROMPT_DEFAULT = (
    "你是一个专业的语音润色专家。请在以下文本中适当添加 MiMO TTS 音频标签，"
    "让播报声情并茂。\n"
    "规则：\n"
    "1. 整体气质用开头风格标签表达，如 (活泼)、(温柔)、(俏皮)、(严肃) 等，"
    "只加 1 个，须贴合文本情绪\n"
    "2. 在语气起伏处插入 1-3 个音频标签，优先选有感染力的：[轻笑]、[笑]、"
    "[叹气]、[深呼吸]、[气声]、[撒娇]、[激动]、[震惊]，句间节奏用 [停顿]；"
    "避免整段只有功能性标签\n"
    "3. 标签与文本情感一致、宁缺毋滥：没有自然的情绪起伏时不强行添加\n"
    "4. 严格保持原文内容一字不变，只增删标签；禁止改写、缩写、扩写、"
    "替换任何词语或标点\n"
    "5. 输出必须是纯文本：禁止任何 Markdown 格式符号（**加粗**、*斜体*、"
    "# 标题、` 代码`、> 引用等），只输出纯文字\n"
    "6. 不要添加任何解释、代码围栏或思考过程，第一行即润色结果\n\n"
    "原文：{text}"
)


async def polish_text_with_llm(plugin, text: str, uid: str) -> str:
    """调用 LLM 为文本注入 MiMO 音频标签；失败返回原文。"""
    provider_id = plugin.config.polish_llm_provider
    if not provider_id:
        try:
            provider_id = await plugin.context.get_current_chat_provider_id(uid)
        except Exception:
            logger.warning(
                "MiMO TTS: failed to get current provider for voice polish, "
                "falling back to original text"
            )
            return text
    prompt_tpl = plugin.config.polish_prompt
    if prompt_tpl.strip() in (_POLISH_PROMPT_V1.strip(), _POLISH_PROMPT_V2.strip()):
        prompt_tpl = ""  # 旧默认模板等值迁移到当前内置模板
    if not prompt_tpl:
        prompt_tpl = POLISH_PROMPT_DEFAULT
    prompt = prompt_tpl.replace("{text}", text)
    try:
        resp = await plugin.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
        )
        polished = strip_markdown_symbols(resp.completion_text or "")
        if polished:
            logger.info(
                "MiMO TTS: voice polish applied, %d chars -> %d chars",
                len(text),
                len(polished),
            )
            return polished
    except Exception as e:
        logger.warning("MiMO TTS: voice polish failed: %s", e)
    return text
