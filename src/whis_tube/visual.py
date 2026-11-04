"""High-speed HD visual frame extraction via HLS range-seek."""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Any, Dict

from .config import YTDLP_BASE
from .utils import fmt_ts, parse_ts, run_command, sanitize_filename

logger = logging.getLogger("whis-tube.visual")


def extract_keyframe(
    url: str,
    timestamp: str,
    output_path: str = "",
    resolution: int = 720,
) -> Dict[str, Any]:
    """Extract a native 720p or 1080p HD keyframe at an exact timecode in seconds.

    Uses direct HLS m3u8 playlist range-seek with ffmpeg for fast extraction (4–7s)
    without downloading full video files or triggering CDN throttling.

    Args:
        url: YouTube video URL.
        timestamp: Timecode string ('HH:MM:SS', 'MM:SS', or seconds).
        output_path: Optional destination image path (.jpg). If directory or empty,
                     automatically generated as '<video_id>_<HHMMSS>.jpg'.
        resolution: Height in pixels (720 or 1080). Defaults to 720.

    Returns:
        Dict with image_path, timestamp, resolution, and markdown_embed string.
    """
    ts_seconds = parse_ts(timestamp)
    ts_formatted = fmt_ts(ts_seconds)
    ts_tag = ts_formatted.replace(":", "")

    # 1. Resolve direct HLS manifest stream URL via yt-dlp
    format_selector = (
        f"bestvideo[height<={resolution}][protocol^=m3u8]/"
        f"bestvideo[height<={resolution}]/"
        f"232/bestvideo"
    )
    cmd_resolve = YTDLP_BASE + ["-f", format_selector, "-g", url]
    res_url = run_command(cmd_resolve, check=False)
    if res_url.returncode != 0 or not res_url.stdout.strip():
        # Fallback to general bestvideo selector
        cmd_resolve_fb = YTDLP_BASE + ["-f", "bestvideo/best", "-g", url]
        res_url = run_command(cmd_resolve_fb, check=True)

    stream_url = res_url.stdout.strip().splitlines()[0]

    # Extract video ID for clean naming
    cmd_id = YTDLP_BASE + ["--get-id", url]
    res_id = run_command(cmd_id, check=False)
    vid_id = res_id.stdout.strip() if res_id.returncode == 0 and res_id.stdout.strip() else "video"

    # 2. Determine target file path
    default_name = f"{vid_id}_{ts_tag}.jpg"
    if not output_path:
        out_dir = pathlib.Path("frames")
        out_dir.mkdir(parents=True, exist_ok=True)
        target_file = out_dir / default_name
    else:
        target = pathlib.Path(output_path)
        if target.is_dir() or output_path.endswith(("/", "\\")):
            target.mkdir(parents=True, exist_ok=True)
            target_file = target / default_name
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target_file = target

    # 3. Fast range-seek via ffmpeg before input flag
    cmd_ffmpeg = [
        "ffmpeg",
        "-y",
        "-ss",
        ts_formatted,
        "-i",
        stream_url,
        "-frames:v",
        "1",
        "-update",
        "1",
        "-q:v",
        "2",
        str(target_file),
        "-loglevel",
        "error",
    ]
    res_ffmpeg = run_command(cmd_ffmpeg, check=False)
    if res_ffmpeg.returncode != 0 or not target_file.exists() or target_file.stat().st_size == 0:
        # Retry with timestamp placed after -i (slower, but covers edge cases on tricky streams)
        cmd_ffmpeg_retry = [
            "ffmpeg",
            "-y",
            "-i",
            stream_url,
            "-ss",
            ts_formatted,
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(target_file),
            "-loglevel",
            "error",
        ]
        run_command(cmd_ffmpeg_retry, check=True)

    if not target_file.exists() or target_file.stat().st_size == 0:
        raise RuntimeError(f"Failed to extract frame at {ts_formatted} from {url}")

    # Inspect dimensions
    probe = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(target_file),
        ],
        check=False,
    )
    dim_str = probe.stdout.strip() if probe.returncode == 0 else f"?x{resolution}"

    return {
        "status": "success",
        "video_id": vid_id,
        "timestamp": ts_formatted,
        "seconds": ts_seconds,
        "dimensions": dim_str,
        "image_path": str(target_file.resolve()),
        "markdown_embed": f"![Visual Frame: {ts_formatted}]({target_file.as_posix()})\n*Tangkapan Layar: [{ts_formatted}]*",
    }
