"""Configuration management for whis-tube MCP server."""

from __future__ import annotations

import os
import pathlib
from dotenv import load_dotenv

from .runtime import REPO_ROOT, configure_runtime_path, get_ytdlp_base

configure_runtime_path()
load_dotenv(REPO_ROOT / ".env", override=False)
load_dotenv(override=False)

# Groq API configuration
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = os.environ.get("WHISPER_MODEL", "whisper-large-v3")
GROQ_API_KEY_ENV = os.environ.get("GROQ_API_KEY", "").strip()

# Key vault paths (project-local keys.json takes precedence, falling back to ~/.config/groq/keys.json)
LOCAL_KEYS_PATHS = [
    REPO_ROOT / "keys.json",
    REPO_ROOT / "keys.local.json",
]
DEFAULT_KEYS_PATH = pathlib.Path.home() / ".config" / "groq" / "keys.json"
KEYS_PATH = pathlib.Path(os.environ.get("GROQ_KEYS_PATH") or str(DEFAULT_KEYS_PATH)).expanduser()

for _local_kpath in LOCAL_KEYS_PATHS:
    if _local_kpath.is_file() and os.name != "nt":
        try:
            os.chmod(_local_kpath, 0o600)
        except OSError:
            pass

# Scratch cache directory
if os.name == "nt":
    _base_cache = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home() / "AppData" / "Local")))
    SCRATCH_DIR = _base_cache / "whis-tube" / "scratch"
else:
    SCRATCH_DIR = pathlib.Path.home() / ".cache" / "whis-tube" / "scratch"

SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
try:
    if os.name != "nt":
        os.chmod(SCRATCH_DIR, 0o700)
except OSError:
    pass

KEY_STATE_PATH = SCRATCH_DIR / "groq_key_state.json"
CKPT_ROOT = SCRATCH_DIR / "checkpoints"
CKPT_ROOT.mkdir(parents=True, exist_ok=True)
try:
    if os.name != "nt":
        os.chmod(CKPT_ROOT, 0o700)
except OSError:
    pass

# Chunking and audio pipeline settings
TARGET_CHUNK_S = int(os.environ.get("TARGET_CHUNK_S", "600"))     # ~10 min target
SEARCH_BACK_S = int(os.environ.get("SEARCH_BACK_S", "90"))       # Look back 90s for pause
SEARCH_FWD_S = int(os.environ.get("SEARCH_FWD_S", "30"))         # Look fwd 30s for pause
MAX_UPLOAD_BYTES = 24 * 1024 * 1024                              # 24 MB safe threshold (<25MB limit)
QUOTA_MAX_WAIT_S = int(os.environ.get("GROQ_MAX_WAIT_S", "900")) # In-process wait limit
SCRATCH_RETENTION_DAYS = int(os.environ.get("WHIS_TUBE_CACHE_DAYS", "3"))
SILENCE_THRESHOLDS_DB = (-40, -35, -30, -25, -20)                # Silencedetect thresholds (strictest first)

# yt-dlp base arguments (prefers python -m yt_dlp in active venv)
YTDLP_BASE = get_ytdlp_base()
