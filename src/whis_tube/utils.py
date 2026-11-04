"""Helper utilities for timecodes, filenames, ffprobe, and channel parsing."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from typing import Any, Dict, List, Optional

from .config import YTDLP_BASE


def fmt_ts(seconds: float) -> str:
    """Format seconds into HH:MM:SS string."""
    s = max(0, int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def parse_ts(ts: str) -> float:
    """Parse timecode (HH:MM:SS, MM:SS, or float seconds) into seconds float."""
    ts = ts.strip()
    if ":" in ts:
        parts = ts.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
    try:
        return float(ts)
    except ValueError:
        raise ValueError(f"Invalid timestamp format: '{ts}'. Expected HH:MM:SS or MM:SS.")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Sanitize string for safe filenames across Linux, macOS, and Windows."""
    clean = re.sub(r'[\\/*?:"<>|.]', "", name)
    clean = re.sub(r"\s+", "_", clean).strip("_")
    return clean[:max_len] or "video"


def run_command(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run CLI subprocess with text output capture."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def ffprobe_duration(path: pathlib.Path) -> float:
    """Get accurate duration in seconds using ffprobe."""
    p = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
    )
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def list_channel_videos(
    channel_url: str,
    limit: int = 50,
    sort_order: str = "oldest_first",
) -> List[Dict[str, Any]]:
    """Enumerate channel uploads and past streams without downloading media bytes.

    Filters out YouTube Shorts (<60s) by default.
    Sorts chronologically (oldest_first) or newest_first.
    """
    cmd = YTDLP_BASE + ["--flat-playlist", "-J", channel_url]
    res = run_command(cmd, check=True)
    data = json.loads(res.stdout)
    entries = data.get("entries") or []

    videos: List[Dict[str, Any]] = []
    for item in entries:
        if not item or not item.get("id"):
            continue
        dur = item.get("duration") or 0
        if dur > 0 and dur <= 60:
            continue  # Exclude Shorts

        vid_id = item["id"]
        title = item.get("title") or "Untitled"
        url = item.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
        upload_date = item.get("upload_date") or ""

        videos.append({
            "id": vid_id,
            "title": title,
            "url": url,
            "duration": dur,
            "duration_formatted": fmt_ts(dur),
            "upload_date": upload_date,
        })

    if sort_order == "oldest_first":
        # If upload_date is present, sort by upload_date, otherwise reverse default newest-first
        if any(v["upload_date"] for v in videos):
            videos.sort(key=lambda x: x["upload_date"] or "99999999")
        else:
            videos = list(reversed(videos))

    return videos[:limit]
