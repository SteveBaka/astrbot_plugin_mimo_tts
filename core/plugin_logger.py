# -*- coding: utf-8 -*-
"""Plugin logger for WebUI log viewer.

Writes structured log entries to a file with 7-day rolling cleanup.
Does NOT interfere with AstrBot's built-in logger — this is a separate
file-based log specifically for the WebUI log page.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_MAX_LOG_AGE_DAYS = 7
_MAX_LOG_LINES = 2000


class PluginLogger:
    """File-based plugin logger with 7-day rolling cleanup."""

    def __init__(self, data_dir: Path, config_ref=None):
        self._log_dir = data_dir / "logs"
        self._config_ref = config_ref
        self._lock = threading.Lock()
        self._log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        """Dynamically read enable_plugin_log from config."""
        if self._config_ref is not None:
            try:
                return bool(self._config_ref.get("enable_plugin_log", False))
            except Exception:
                pass
        return False

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Sync back to config (for API update path)."""
        if self._config_ref is not None:
            try:
                self._config_ref.set("enable_plugin_log", bool(value))
            except Exception:
                pass

    def _log_file(self) -> Path:
        """Return today's log file path."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self._log_dir / f"mimo_tts_{today}.log"

    def write(self, level: str, category: str, message: str, detail: Optional[str] = None) -> None:
        """Write a log entry if logging is enabled."""
        if not self._enabled:
            return
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "cat": category,
            "msg": message,
        }
        if detail:
            entry["detail"] = detail
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                with open(self._log_file(), "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def info(self, category: str, message: str, detail: Optional[str] = None) -> None:
        self.write("INFO", category, message, detail)

    def warn(self, category: str, message: str, detail: Optional[str] = None) -> None:
        self.write("WARN", category, message, detail)

    def error(self, category: str, message: str, detail: Optional[str] = None) -> None:
        self.write("ERROR", category, message, detail)

    def cleanup_old_logs(self) -> None:
        """Delete log files older than 7 days."""
        cutoff = time.time() - _MAX_LOG_AGE_DAYS * 86400
        try:
            for f in self._log_dir.glob("mimo_tts_*.log"):
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
        except Exception:
            pass

    def read_logs(self, limit: int = 200, level: Optional[str] = None) -> list[dict]:
        """Read recent log entries from today's log file, newest first."""
        log_file = self._log_file()
        if not log_file.exists():
            return []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return []

        # Also read yesterday's file for continuity
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_file = self._log_dir / f"mimo_tts_{yesterday}.log"
        if yesterday_file.exists():
            try:
                with open(yesterday_file, "r", encoding="utf-8") as f:
                    lines = f.readlines() + lines
            except Exception:
                pass

        entries: list[dict] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if level and entry.get("level") != level:
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    break
            except Exception:
                continue

        return entries

    def get_stats(self) -> dict:
        """Return log statistics."""
        total_files = 0
        total_size = 0
        try:
            for f in self._log_dir.glob("mimo_tts_*.log"):
                total_files += 1
                total_size += f.stat().st_size
        except Exception:
            pass
        return {
            "enabled": self._enabled,
            "log_dir": str(self._log_dir),
            "total_files": total_files,
            "total_size_kb": round(total_size / 1024, 1),
            "max_age_days": _MAX_LOG_AGE_DAYS,
        }
