# -*- coding: utf-8 -*-
"""测试引导：注入 astrbot.api 桩与插件包骨架。勿 from conftest import。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_astrbot_stub() -> None:
    if "astrbot.api" in sys.modules:
        return
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")

    class _Logger:
        def debug(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api


def _ensure_pkg() -> None:
    pkg_name = "mimo_tts_plugin"
    if pkg_name in sys.modules:
        return
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(ROOT)]
    pkg.__file__ = str(ROOT / "__init__.py")
    sys.modules[pkg_name] = pkg
    for name in ("core", "tts", "handlers", "emotion", "voice"):
        mod = types.ModuleType(f"{pkg_name}.{name}")
        mod.__path__ = [str(ROOT / name)]
        sys.modules[f"{pkg_name}.{name}"] = mod
        setattr(pkg, name, mod)


_ensure_astrbot_stub()
_ensure_pkg()
