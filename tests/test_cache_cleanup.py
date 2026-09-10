# -*- coding: utf-8 -*-
"""缓存清理机制单测：temp 孤儿扫描、派生映射淘汰、日志滚动清理。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.plugin_logger import PluginLogger  # noqa: E402
from core.user_state import UserStateManager  # noqa: E402


def _make_manager(tmp_path: Path) -> UserStateManager:
    return UserStateManager(tmp_path, config=None)


def _make_file(path: Path, age_seconds: float) -> Path:
    path.write_bytes(b"x" * 256)
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


class TestCleanupTempDir:
    def test_removes_old_orphans(self, tmp_path):
        mgr = _make_manager(tmp_path)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        _make_file(temp_dir / "mimo_1000.wav", age_seconds=7200)
        _make_file(temp_dir / "mimo_2000.mp3", age_seconds=7200)

        removed = mgr.cleanup_temp_dir()

        assert removed == 2
        assert list(temp_dir.iterdir()) == []

    def test_keeps_recent_files(self, tmp_path):
        mgr = _make_manager(tmp_path)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        _make_file(temp_dir / "mimo_recent.wav", age_seconds=60)

        assert mgr.cleanup_temp_dir() == 0
        assert (temp_dir / "mimo_recent.wav").exists()

    def test_keeps_tracked_files_even_if_old(self, tmp_path):
        mgr = _make_manager(tmp_path)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        tracked = _make_file(temp_dir / "mimo_tracked.wav", age_seconds=7200)
        mgr._recent_files.append((time.time(), tracked))

        assert mgr.cleanup_temp_dir() == 0
        assert tracked.exists()

    def test_missing_dir_returns_zero(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.cleanup_temp_dir(tmp_path / "no_such_dir") == 0

    def test_default_dir_is_data_dir_temp(self, tmp_path):
        mgr = _make_manager(tmp_path)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        _make_file(temp_dir / "mimo_old.wav", age_seconds=7200)

        assert mgr.cleanup_temp_dir() == 1


class TestEvictDerivedStores:
    def test_umo_and_cooldown_follow_settings_eviction(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._user_settings["u1"] = {"x": 1}
        mgr._user_settings["u2"] = {"x": 2}
        mgr._user_umo["u1"] = "umo1"
        mgr._user_umo["ghost"] = "umo-ghost"
        mgr._nl_sing_last["u1"] = time.time()
        mgr._nl_sing_last["ghost"] = time.time()

        mgr._evict_stale_users()

        assert "ghost" not in mgr._user_umo
        assert "ghost" not in mgr._nl_sing_last
        assert mgr._user_umo["u1"] == "umo1"
        assert "u1" in mgr._nl_sing_last

    def test_settings_over_limit_evicts_oldest_and_derived(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._MAX_IDLE_USERS = 2
        for uid in ("u1", "u2", "u3"):
            mgr._user_settings[uid] = {"x": uid}
            mgr._user_umo[uid] = f"umo-{uid}"
            mgr._nl_sing_last[uid] = time.time()

        mgr._evict_stale_users()

        assert list(mgr._user_settings) == ["u2", "u3"]
        assert "u1" not in mgr._user_umo
        assert "u1" not in mgr._nl_sing_last

    def test_restore_clears_derived_stores(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._user_settings["u1"] = {"x": 1}
        mgr._user_format["u1"] = "mp3"
        mgr._user_umo["u1"] = "umo1"
        mgr._nl_sing_last["u1"] = time.time()

        mgr.restore("u1")

        assert "u1" not in mgr._user_umo
        assert "u1" not in mgr._nl_sing_last
        assert "u1" not in mgr._user_settings
        assert "u1" not in mgr._user_format

    def test_reset_all_clears_derived_stores(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._user_umo["u1"] = "umo1"
        mgr._nl_sing_last["u1"] = time.time()

        mgr.reset_all()

        assert mgr._user_umo == {}
        assert mgr._nl_sing_last == {}


class TestPluginLogDailyCleanup:
    def test_maybe_cleanup_runs_once_per_day(self, tmp_path, monkeypatch):
        plog = PluginLogger(tmp_path)
        calls = []
        original = plog.cleanup_old_logs

        def spy():
            calls.append(1)
            original()

        monkeypatch.setattr(plog, "cleanup_old_logs", spy)

        plog._maybe_cleanup_old_logs()
        plog._maybe_cleanup_old_logs()

        assert len(calls) == 1

    def test_cleanup_removes_files_older_than_7_days(self, tmp_path):
        plog = PluginLogger(tmp_path)
        old_file = _make_file(plog._log_dir / "mimo_tts_old.log", age_seconds=8 * 86400)
        new_file = _make_file(plog._log_dir / "mimo_tts_new.log", age_seconds=60)

        plog.cleanup_old_logs()

        assert not old_file.exists()
        assert new_file.exists()
