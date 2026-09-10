# -*- coding: utf-8 -*-
"""无 AstrBot 环境下为 astrbot.api 提供最小桩，便于单测导入核心模块。"""

from __future__ import annotations

import logging
import sys
import types

try:  # pragma: no cover - 部署环境已安装 astrbot 时直接走真实包
    import astrbot  # noqa: F401
except ImportError:
    _pkg = types.ModuleType("astrbot")
    _api = types.ModuleType("astrbot.api")
    _api.logger = logging.getLogger("mimo-tts-test")
    _pkg.api = _api
    sys.modules["astrbot"] = _pkg
    sys.modules["astrbot.api"] = _api
