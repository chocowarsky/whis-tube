"""Helper utilities for timecodes, filenames, ffprobe, and channel parsing."""

from __future__ import annotations

import json
import math
import pathlib
import re
import subprocess
from typing import Any, Dict, List, Optional

from .config import YTDLP_BASE


def fmt_ts(seconds: float) -> str:
    """Format seconds into HH:MM:SS string safely handling NaN/Inf/Overflow."""
    try:
        val = float(seconds)
        if math.isnan(val) or math.isinf(val) or val < 0:
            return "00:00:00"
        s = int(val)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"
    except (ValueError, TypeError, OverflowError):
        return "00:00:00"


def parse_ts(ts: str) -> float:
    """Parse a finite, non-negative HH:MM:SS, MM:SS, or seconds timestamp."""
    import math

    ts = ts.strip()
    try:
        if ":" in ts:
            parts = ts.split(":")
            if len(parts) == 3:
                hours, minutes, seconds = map(float, parts)
                if minutes >= 60 or seconds >= 60:
                    raise ValueError
                value = hours * 3600 + minutes * 60 + seconds
            elif len(parts) == 2:
                minutes, seconds = map(float, parts)
                if seconds >= 60:
                    raise ValueError
                value = minutes * 60 + seconds
            else:
                raise ValueError
        else:
            value = float(ts)
        if not math.isfinite(value) or value < 0:
            raise ValueError
        return value
    except (ValueError, OverflowError):
        raise ValueError(f"Invalid timestamp format: '{ts}'. Expected a finite, non-negative HH:MM:SS or MM:SS.")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Sanitize string for safe filenames across Linux, macOS, and Windows."""
    clean = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(name or ""))
    clean = re.sub(r'[\\/*?:"<>|.]', "", clean)
    clean = re.sub(r"\s+", "_", clean).strip("_")
    res = clean[:max_len]
    if res.upper() in {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
        "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
        "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }:
        res = f"{res}_file"
    return res or "video"


def run_command(
    cmd: List[str],
    check: bool = True,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Run CLI subprocess with text output capture and optional timeout."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)


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
    cmd = YTDLP_BASE + ["--flat-playlist", "-J", "--", channel_url]
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
