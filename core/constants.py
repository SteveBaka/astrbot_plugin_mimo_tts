# -*- coding: utf-8 -*-
"""MiMO TTS Plugin - Constants."""

from pathlib import Path

# Plugin metadata
PLUGIN_ID = "astrbot_plugin_mimo_tts"
PLUGIN_NAME = "MiMO TTS"

# Paths
PLUGIN_DIR = Path(__file__).parent.parent
CONFIG_FILE = PLUGIN_DIR / "config.json"
TEMP_DIR = PLUGIN_DIR / "temp"
AUDIO_SAMPLES_DIR = PLUGIN_DIR / "audio_samples"

# API defaults
DEFAULT_API_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "mimo_default"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3

# Controls defaults
DEFAULT_SPEED = 1.0
DEFAULT_PITCH = 0
DEFAULT_PROBABILITY = 1.0

# Output defaults
DEFAULT_AUDIO_FORMAT = "mp3"
DEFAULT_MIN_TEXT_LENGTH = 1
DEFAULT_MAX_TEXT_LENGTH = 5000

# Audio constants
AUDIO_CLEANUP_TTL_SECONDS: int = 2 * 3600
AUDIO_MIN_VALID_SIZE: int = 100
AUDIO_VALID_EXTENSIONS: list[str] = [".mp3", ".wav", ".ogg", ".opus", ".pcm"]

# Supported emotions (20种)
SUPPORTED_EMOTIONS: tuple[str, ...] = (
    "happy",
    "sad",
    "angry",
    "neutral",
    "whisper",
    "surprised",
    "excited",
    "gentle",
    "serious",
    "romantic",
    "fearful",
    "disgusted",
    "sarcastic",
    "nostalgic",
    "playful",
    "calm",
    "anxious",
    "proud",
    "tender",
    "lazy",
)

# Supported audio formats
SUPPORTED_AUDIO_FORMATS: tuple[str, ...] = ("mp3", "wav", "ogg", "pcm")

# System message skip patterns (regex)
SKIP_PATTERNS: list[str] = [
    r"^\[系统\]",
    r"^\[命令\]",
    r"^\[System\]",
    r"^\[Command\]",
]

# MiMO built-in voice list
MIMO_VOICE_LIST: list[dict[str, str]] = [
    {
        "id": "mimo_default",
        "name": "MiMo-默认",
        "gender": "因集群而异",
        "style": "中国集群默认冰糖",
    },
    {"id": "冰糖", "name": "冰糖", "gender": "女", "style": "中文"},
    {"id": "茉莉", "name": "茉莉", "gender": "女", "style": "中文"},
    {"id": "苏打", "name": "苏打", "gender": "男", "style": "中文"},
    {"id": "白桦", "name": "白桦", "gender": "男", "style": "中文"},
    {"id": "Mia", "name": "Mia", "gender": "女", "style": "英文"},
    {"id": "Chloe", "name": "Chloe", "gender": "女", "style": "英文"},
    {"id": "Milo", "name": "Milo", "gender": "男", "style": "英文"},
    {"id": "Dean", "name": "Dean", "gender": "男", "style": "英文"},
]

# Built-in presets
TTS_PRESETS: dict[str, dict] = {
    "default": {
        "emotion": "neutral",
        "speed": 1.0,
        "pitch": 0,
        "breath": False,
        "stress": False,
        "voice": "mimo_default",
    },
    "gentle_female": {
        "emotion": "gentle",
        "speed": 0.95,
        "pitch": 2,
        "breath": True,
        "stress": False,
        "voice": "冰糖",
    },
    "energetic": {
        "emotion": "excited",
        "speed": 1.2,
        "pitch": 1,
        "breath": False,
        "stress": True,
        "voice": "茉莉",
    },
    "news_anchor": {
        "emotion": "serious",
        "speed": 1.05,
        "pitch": 0,
        "breath": False,
        "stress": True,
        "voice": "苏打",
    },
    "bedtime_story": {
        "emotion": "gentle",
        "speed": 0.85,
        "pitch": 1,
        "breath": True,
        "stress": False,
        "voice": "茉莉",
    },
    "sad_comfort": {
        "emotion": "tender",
        "speed": 0.9,
        "pitch": -1,
        "breath": True,
        "stress": False,
        "voice": "白桦",
    },
    "dramatic": {
        "emotion": "angry",
        "speed": 1.1,
        "pitch": 2,
        "breath": False,
        "stress": True,
        "voice": "Dean",
    },
    "whisper_secret": {
        "emotion": "whisper",
        "speed": 0.8,
        "pitch": -2,
        "breath": True,
        "stress": False,
        "voice": "Chloe",
    },
}
