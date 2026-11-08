"""High-speed HD visual frame extraction via HLS range-seek."""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Any, Dict

from .config import SCRATCH_DIR, YTDLP_BASE
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

    # Validate and clamp resolution
    try:
        res_int = int(resolution)
    except (ValueError, TypeError):
        res_int = 720
    if res_int <= 0:
        res_int = 720
    elif res_int > 4320:
        res_int = 4320
    resolution = res_int

    # 1. Resolve direct HLS manifest stream URL via yt-dlp
    format_selector = (
        f"bestvideo[height<={resolution}][protocol^=m3u8]/"
        f"bestvideo[height<={resolution}]/"
        f"232/bestvideo"
    )
    cmd_resolve = YTDLP_BASE + ["-f", format_selector, "-g", "--", url]
    res_url = run_command(cmd_resolve, check=False)
    if res_url.returncode != 0 or not res_url.stdout.strip():
        # Fallback to general bestvideo selector
        cmd_resolve_fb = YTDLP_BASE + ["-f", "bestvideo/best", "-g", "--", url]
        res_url = run_command(cmd_resolve_fb, check=False)

    if res_url.returncode != 0 or not res_url.stdout.strip():
        # Fallback to general best format selector
        cmd_resolve_best = YTDLP_BASE + ["-g", "--", url]
        res_url = run_command(cmd_resolve_best, check=False)

    lines = [line.strip() for line in (res_url.stdout or "").strip().splitlines() if line.strip()]
    stream_url = lines[0] if lines else ""

    # Extract video ID for clean naming
    cmd_id = YTDLP_BASE + ["--get-id", "--", url]
    res_id = run_command(cmd_id, check=False)
    raw_id = res_id.stdout.strip() if res_id.returncode == 0 and res_id.stdout.strip() else "video"
    vid_id = sanitize_filename(raw_id)

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

    # 3. Fast range-seek via ffmpeg before input flag with reconnect & discontinuity options
    reconnect_args = [
        "-reconnect",
        "1",
        "-reconnect_at_eof",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
    ]

    if stream_url:
        cmd_ffmpeg = [
            "ffmpeg",
            "-y",
            *reconnect_args,
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
            # Retry with timestamp placed after -i (handles HLS stream discontinuities)
            cmd_ffmpeg_retry = [
                "ffmpeg",
                "-y",
                *reconnect_args,
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
            run_command(cmd_ffmpeg_retry, check=False)

    # 4. Fallback 3: yt-dlp section download if direct stream seek failed or stream_url is empty
    if not target_file.exists() or target_file.stat().st_size == 0:
        logger.info(f"Direct stream seek failed; falling back to yt-dlp section download for {url} at {ts_formatted}...")
        clip_start = max(0.0, ts_seconds - 1.0)
        clip_end = ts_seconds + 3.0
        clip_dir = SCRATCH_DIR
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip_path = clip_dir / f"clip_{vid_id}_{ts_tag}_{os.getpid()}.mp4"
        try:
            cmd_clip = YTDLP_BASE + [
                "--download-sections",
                f"*{clip_start:.2f}-{clip_end:.2f}",
                "-f",
                f"bestvideo[height<={resolution}]/bestvideo/best",
                "-o",
                str(clip_path),
                "--force-overwrites",
                "--",
                url,
            ]
            res_clip = run_command(cmd_clip, check=False)
            if clip_path.exists() and clip_path.stat().st_size > 0:
                seek_offset = ts_seconds - clip_start
                cmd_clip_ffmpeg = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{seek_offset:.3f}",
                    "-i",
                    str(clip_path),
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
                run_command(cmd_clip_ffmpeg, check=False)
        finally:
            clip_path.unlink(missing_ok=True)

    if not target_file.exists() or target_file.stat().st_size == 0:
        target_file.unlink(missing_ok=True)
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
