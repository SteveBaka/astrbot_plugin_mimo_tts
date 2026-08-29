# -*- coding: utf-8 -*-
"""core/segmentation.py 纯逻辑单测（不依赖 AstrBot，pytest 直接运行）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.segmentation import (  # noqa: E402
    BUNDLED,
    DROP,
    SegmentPlan,
    TEXT_FALLBACK,
    TEXT_FIRST,
    VOICE_ONLY,
    plan_segments,
    resolve_delivery,
)
from core.text_utils import strip_markdown_symbols, strip_tts_tags  # noqa: E402


class TestStripMarkdownSymbols:
    def test_bold_removed_content_kept(self):
        assert strip_markdown_symbols("可以点**清炒蟹粉**——很鲜") == "可以点清炒蟹粉——很鲜"

    def test_single_asterisk_and_backtick_removed(self):
        assert strip_markdown_symbols("*清炒蟹粉* 和 `代码`") == "清炒蟹粉 和 代码"

    def test_strikethrough_and_double_underscore(self):
        assert strip_markdown_symbols("~~旧~~ __新__") == "旧 新"

    def test_heading_marker_removed(self):
        # 行首 # 清洗后保留换行结构（strip_markdown_symbols 不压缩换行）
        assert strip_markdown_symbols("# 标题\n正文") == "标题\n正文"

    def test_mimo_tags_preserved(self):
        text = "(温柔)可以点**清炒蟹粉**[停顿]很好吃"
        assert strip_markdown_symbols(text) == "(温柔)可以点清炒蟹粉[停顿]很好吃"

    def test_empty_and_plain_text_untouched(self):
        assert strip_markdown_symbols("") == ""
        assert strip_markdown_symbols("普通句子，没有任何格式。") == "普通句子，没有任何格式。"


class TestStripTtsTags:
    def test_polish_output_fully_stripped(self):
        # 润色输出典型形态：开头 (风格) + 正文 + [音频标签]
        assert (
            strip_tts_tags("(活泼)明天上海又是雨天[叹气]，气温在25-32℃之间，闷热感还是有的")
            == "明天上海又是雨天，气温在25-32℃之间，闷热感还是有的"
        )

    def test_multiple_leading_style_tags(self):
        assert strip_tts_tags("(温柔)(轻快)早上好[停顿]今天天气不错") == "早上好今天天气不错"

    def test_normal_parentheses_kept(self):
        # 正文普通括号内容不是 TTS 标签，保留
        assert strip_tts_tags("这份蟹粉(约380元)值得尝试") == "这份蟹粉(约380元)值得尝试"

    def test_audio_tags_mid_sentence(self):
        assert strip_tts_tags("我记得上次带朋友去[轻笑]，他第一口就没停下来") == "我记得上次带朋友去，他第一口就没停下来"

    def test_empty_untouched(self):
        assert strip_tts_tags("") == ""
        assert strip_tts_tags("纯文本无标签") == "纯文本无标签"


class TestPlanSegments:
    def test_short_segment_never_rolls_dice(self):
        plans = plan_segments(["好", "这是一段足够长的文本内容"], min_length=5, probability=1.0)
        assert plans[0] == SegmentPlan(text="好", short=True, want_voice=False)
        assert plans[1].short is False
        assert plans[1].want_voice is True

    def test_probability_zero_all_miss(self):
        plans = plan_segments(["第一段内容足够长", "第二段内容也足够长"], min_length=5, probability=0.0)
        assert all(not p.want_voice for p in plans)

    def test_probability_one_all_hit(self):
        plans = plan_segments(["第一段内容足够长", "第二段内容也足够长"], min_length=5, probability=1.0)
        assert all(p.want_voice for p in plans)

    def test_injected_rng_is_deterministic(self):
        # rng 依次返回 0.9 / 0.1：prob=0.5 时首段命中、次段未命中
        rolls = iter([0.9, 0.1])
        plans = plan_segments(
            ["第一段内容足够长", "第二段内容也足够长"],
            min_length=5,
            probability=0.5,
            rng=lambda: next(rolls),
        )
        assert [p.want_voice for p in plans] == [False, True]

    def test_order_preserved(self):
        plans = plan_segments(["甲段内容足够长哦", "乙段", "丙段内容足够长哦"], min_length=5, probability=0.5)
        assert [p.text for p in plans] == ["甲段内容足够长哦", "乙段", "丙段内容足够长哦"]

    def test_separator_segments_are_blank(self):
        # markdown 分隔线等纯装饰段：blank=True，整段丢弃
        plans = plan_segments(["---", "***", "___", "===  ===", "正文内容足够长"], min_length=5, probability=1.0)
        assert [p.blank for p in plans] == [True, True, True, True, False]
        assert all(not p.want_voice for p in plans[:4])

    def test_blank_resolves_to_drop_unconditionally(self):
        assert resolve_delivery(
            short=False, want_voice=False, text_enabled=True, text_async=False,
            fallback_enabled=True, blank=True,
        ) == DROP
        assert resolve_delivery(
            short=False, want_voice=False, text_enabled=True, text_async=False,
            fallback_enabled=False, blank=True,
        ) == DROP


def _resolve(**overrides) -> str:
    kwargs = dict(
        short=False,
        want_voice=True,
        text_enabled=True,
        text_async=False,
        fallback_enabled=True,
    )
    kwargs.update(overrides)
    return resolve_delivery(**kwargs)


class TestResolveDelivery:
    def test_short_segment_unconditional_text(self):
        # 短段是固定策略，不受 fallback / text 开关约束
        assert _resolve(short=True) == TEXT_FALLBACK
        assert _resolve(short=True, fallback_enabled=False) == TEXT_FALLBACK

    def test_dice_miss_follows_fallback_switch(self):
        assert _resolve(want_voice=False) == TEXT_FALLBACK
        assert _resolve(want_voice=False, fallback_enabled=False) == DROP

    def test_hit_text_off_is_voice_only(self):
        assert _resolve(text_enabled=False) == VOICE_ONLY

    def test_hit_text_on_sync_is_bundled(self):
        assert _resolve(text_async=False) == BUNDLED

    def test_hit_text_on_async_is_text_first(self):
        assert _resolve(text_async=True) == TEXT_FIRST

    def test_full_matrix(self):
        # 2^5 = 32 种组合逐一覆盖，防止未来改动引入未定义分支
        for short in (False, True):
            for want_voice in (False, True):
                for text_enabled in (False, True):
                    for text_async in (False, True):
                        for fallback in (False, True):
                            action = resolve_delivery(
                                short=short,
                                want_voice=want_voice,
                                text_enabled=text_enabled,
                                text_async=text_async,
                                fallback_enabled=fallback,
                            )
                            assert action in (
                                BUNDLED, TEXT_FIRST, VOICE_ONLY, TEXT_FALLBACK, DROP,
                            )
                            if short:
                                assert action == TEXT_FALLBACK
                            elif not want_voice:
                                assert action == (TEXT_FALLBACK if fallback else DROP)
