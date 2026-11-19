"""Self-healing runtime path, yt-dlp module resolution, and static binary provisioning."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import threading
from typing import List, Optional, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / ".bin"

_BINARY_LOCK = threading.Lock()
_CACHED_BINARIES: Optional[Tuple[pathlib.Path, pathlib.Path]] = None


def _exe_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


def configure_runtime_path() -> None:
    """Ensure local .bin, active venv bin, and ~/.local/bin are prioritized on PATH."""
    venv_bin = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    candidates = [
        BIN_DIR,
        venv_bin,
        pathlib.Path(sys.executable).resolve().parent,
        pathlib.Path.home() / ".local" / "bin",
    ]
    current = os.environ.get("PATH", "")
    parts = [p for p in current.split(os.pathsep) if p]

    # Insert in reverse so earlier entries in candidates have highest precedence
    for directory in reversed(candidates):
        if directory.is_dir():
            dir_str = str(directory)
            if dir_str in parts:
                parts.remove(dir_str)
            parts.insert(0, dir_str)

    os.environ["PATH"] = os.pathsep.join(parts)


def get_ytdlp_base() -> List[str]:
    """Prefer in-environment `python -m yt_dlp` to avoid external PATH failures."""
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp", "--no-playlist"]
    exe = shutil.which("yt-dlp") or "yt-dlp"
    return [exe, "--no-playlist"]


def is_binary_working(name: str, version_arg: str = "-version") -> Optional[pathlib.Path]:
    """Verify binary exists (ignoring broken symlinks) and exits 0 on version probe."""
    candidates: List[pathlib.Path] = []
    local_bin = BIN_DIR / _exe_name(name)
    if local_bin.exists():
        candidates.append(local_bin)
    found = shutil.which(name)
    if found:
        candidates.append(pathlib.Path(found))

    for cand in candidates:
        try:
            if not cand.exists() or not cand.is_file():
                continue
            if os.name != "nt" and not os.access(cand, os.X_OK):
                continue
            res = subprocess.run(
                [str(cand), version_arg],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode == 0:
                return cand.resolve()
        except Exception:
            continue
    return None


def ensure_runtime_binaries(quiet: bool = True) -> Tuple[pathlib.Path, pathlib.Path]:
    """Guarantee working ffmpeg & ffprobe binaries, auto-bootstrapping zero-sudo if needed."""
    global _CACHED_BINARIES
    with _BINARY_LOCK:
        if _CACHED_BINARIES is not None:
            ff_cached, fp_cached = _CACHED_BINARIES
            if ff_cached.exists() and fp_cached.exists():
                return ff_cached, fp_cached

        configure_runtime_path()
        ff = is_binary_working("ffmpeg", "-version")
        fp = is_binary_working("ffprobe", "-version")

        if not (ff and fp):
            bootstrap_path = REPO_ROOT / "bootstrap.py"
            if bootstrap_path.is_file():
                spec = importlib.util.spec_from_file_location("whis_tube_bootstrap", bootstrap_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.ensure_ffmpeg(quiet=quiet)
                    configure_runtime_path()
                    ff = is_binary_working("ffmpeg", "-version")
                    fp = is_binary_working("ffprobe", "-version")

        if not (ff and fp):
            raise RuntimeError(
                "ffmpeg and ffprobe are required but missing or broken. "
                f"Run 'python3 {REPO_ROOT / 'bootstrap.py'}' to install standalone binaries without sudo."
            )

        _CACHED_BINARIES = (ff, fp)
        return ff, fp
