"""whis-tube FastMCP server definition & registered tools.

Server Name: youtube-whisper
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import pathlib
import sys
import time
from typing import Optional

# Support mcp 2.x (MCPServer) and mcp 1.x / fastmcp (FastMCP)
try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        from fastmcp import FastMCP

from .audio import get_video_info as _get_video_info
from .audio import transcribe_video as _transcribe_video
from .config import DEFAULT_KEYS_PATH, MODEL, REPO_ROOT, YTDLP_BASE
from .groq_pool import KeyPool, QuotaExhausted, load_groq_keys_with_sources
from .runtime import ensure_runtime_binaries, is_binary_working
from .utils import fmt_ts, list_channel_videos as _list_channel_videos
from .visual import extract_keyframe as _extract_keyframe

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [whis-tube] %(levelname)s: %(message)s",
)
logger = logging.getLogger("whis-tube")

# Initialize MCP Server with the requested public identifier: youtube-whisper
mcp = FastMCP(
    "youtube-whisper",
    instructions=(
        "youtube-whisper: High-precision YouTube verbatim transcription and visual "
        "frame extraction pipeline powered by Groq Whisper Large V3 and FFmpeg HLS range-seek."
    ),
)


# ── Tool 1: transcribe_youtube ──────────────────────────────────────────────


@mcp.tool()
async def transcribe_youtube(
    url: str,
    output_path: str = "",
    language: str = "",
    glossary: str = "",
) -> str:
    """Download audio, apply silence-detected chunking (<25MB), and transcribe verbatim
    via Groq Whisper Large V3 with timestamped segment accuracy and bilingual code-switching.

    Args:
        url: YouTube video URL (standard watch, short link, or completed livestream archive).
        output_path: Optional output path or directory for transcript files (.md & _raw.json).
                     Defaults to './transcripts/<video_id>_<title>.md'.
        language: Optional language code (e.g. 'id', 'en', 'ja'). If omitted, auto-detected
                  with Indonesian code-switching detection.
        glossary: Optional comma-separated custom domain keywords or glossary terms
                  (e.g. 'Sui, Aptos, Arbitrum, LayerZero').
    """
    logger.info(f"Received transcribe request: {url}")
    try:
        # Run blocking CPU/Network pipeline in thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            lambda: _transcribe_video(url, output_path=output_path, language=language or None, glossary=glossary),
        )
        glossary_info = f"- **Glossary Terms:** {res.get('glossary_terms_count', 0)}\n" if res.get('glossary_terms_count') else ""
        phonetic_info = f"- **Phonetic Corrections:** {res.get('phonetic_corrections_count', 0)}\n" if res.get('phonetic_corrections_count') else ""
        return (
            f"✅ Transcription Successful!\n\n"
            f"- **Title:** {res['title']}\n"
            f"- **Channel:** {res['channel']}\n"
            f"- **Duration:** {res['duration']}\n"
            f"- **Language:** {res.get('language') or 'auto'}\n"
            f"- **Total Segments:** {res['total_segments']} ({res['total_words']:,} words)\n"
            f"- **Low-Confidence Segments:** {res['low_confidence_segments']}\n"
            f"{glossary_info}"
            f"{phonetic_info}"
            f"- **Processing Time:** {res['elapsed_seconds']}s\n"
            f"- **Markdown File:** `{res['transcript_path']}`\n"
            f"- **Raw JSON File:** `{res['raw_json_path']}`"
        )
    except QuotaExhausted as qe:
        return f"⚠️ Groq Quota Exhausted: {qe}. Resume pending chunks after cooldown."
    except Exception as exc:
        logger.error(f"Error during transcription: {exc}", exc_info=True)
        return f"❌ Transcription failed: {exc}"


# ── Tool 2: extract_keyframe ────────────────────────────────────────────────


@mcp.tool()
async def extract_keyframe(
    url: str,
    timestamp: str,
    output_path: str = "",
    resolution: int = 720,
) -> str:
    """Extract a native 720p or 1080p HD keyframe at an exact timecode (HH:MM:SS)
    via HLS m3u8 range-seek without downloading full video bytes.

    Args:
        url: YouTube video URL.
        timestamp: Exact timecode string ('HH:MM:SS' or 'MM:SS', e.g. '00:15:30').
        output_path: Optional output path (.jpg) or folder. Defaults to './frames/<video_id>_<HHMMSS>.jpg'.
        resolution: Target resolution height in pixels (720 or 1080). Defaults to 720.
    """
    logger.info(f"Received extract_keyframe request: {url} at {timestamp} ({resolution}p)")
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            lambda: _extract_keyframe(url, timestamp, output_path=output_path, resolution=resolution),
        )
        return (
            f"🖼️ Keyframe Extracted Successfully!\n\n"
            f"- **Timestamp:** {res['timestamp']}\n"
            f"- **Resolution:** {res['dimensions']}\n"
            f"- **File Path:** `{res['image_path']}`\n\n"
            f"**Markdown Embed Snippet:**\n"
            f"```markdown\n{res['markdown_embed']}\n```"
        )
    except Exception as exc:
        logger.error(f"Error extracting keyframe: {exc}", exc_info=True)
        return f"❌ Failed to extract keyframe: {exc}"


# ── Tool 3: get_video_info ──────────────────────────────────────────────────


@mcp.tool()
async def get_video_info(url: str) -> str:
    """Fetch YouTube video metadata (title, channel, duration, upload date, live status).

    Args:
        url: YouTube video URL.
    """
    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, lambda: _get_video_info(url))
        dur = int(info.get("duration") or 0)
        vc = info.get("view_count")
        if isinstance(vc, (int, float)):
            vc_str = f"{int(vc):,}"
        elif isinstance(vc, str) and vc.isdigit():
            vc_str = f"{int(vc):,}"
        else:
            vc_str = "N/A"
        vid_id = info.get("id") or "video"
        return (
            f"ℹ️ **YouTube Video Information**\n\n"
            f"- **Title:** {info.get('title')}\n"
            f"- **Channel:** {info.get('channel') or info.get('uploader')}\n"
            f"- **Duration:** {fmt_ts(dur)} ({dur} seconds)\n"
            f"- **Upload Date:** {info.get('upload_date') or 'N/A'}\n"
            f"- **Live Status:** {info.get('live_status') or 'vod/uploaded'}\n"
            f"- **Source Language:** {info.get('language') or 'auto'}\n"
            f"- **View Count:** {vc_str}\n"
            f"- **URL:** https://www.youtube.com/watch?v={vid_id}"
        )
    except Exception as exc:
        return f"❌ Failed to retrieve video information: {exc}"


# ── Tool 4: list_channel_videos ─────────────────────────────────────────────


@mcp.tool()
async def list_channel_videos(
    channel_url: str,
    limit: int = 30,
    sort_order: str = "oldest_first",
) -> str:
    """Enumerate video uploads from a channel without downloading bytes.
    Excludes Shorts (<60s). Defaults to chronological oldest-to-newest order.

    Args:
        channel_url: YouTube channel uploads URL (e.g. 'https://www.youtube.com/@channel/videos').
        limit: Maximum number of videos to list (default: 30).
        sort_order: 'oldest_first' (recommended for research) or 'newest_first'.
    """
    try:
        loop = asyncio.get_running_loop()
        videos = await loop.run_in_executor(
            None,
            lambda: _list_channel_videos(channel_url, limit=limit, sort_order=sort_order),
        )
        if not videos:
            return f"No videos found for {channel_url}."

        lines = [
            f"📋 **Channel Video Catalog** ({len(videos)} videos, sort: {sort_order})\n",
            "| No | Date | Duration | Title | URL |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for idx, v in enumerate(videos, 1):
            date_str = v["upload_date"] or "-"
            if len(date_str) == 8:
                date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            clean_title = v["title"].replace("|", "/")
            lines.append(f"| {idx:02d} | {date_str} | {v['duration_formatted']} | {clean_title} | [Watch]({v['url']}) |")

        return "\n".join(lines)
    except Exception as exc:
        return f"❌ Failed to list channel videos: {exc}"


# ── Tool 5: check_groq_quota ────────────────────────────────────────────────


@mcp.tool()
async def check_groq_quota() -> str:
    """Inspect Groq API key pool status, binary readiness, active key counts, and cooldown timers."""
    try:
        ff_ok = bool(is_binary_working("ffmpeg", "-version"))
        fp_ok = bool(is_binary_working("ffprobe", "-version"))
        yt_ok = importlib.util.find_spec("yt_dlp") is not None or bool(is_binary_working("yt-dlp", "--version"))
        bin_summary = (
            f"ffmpeg={'OK' if ff_ok else 'MISSING'}, "
            f"ffprobe={'OK' if fp_ok else 'MISSING'}, "
            f"yt-dlp={'OK' if yt_ok else 'MISSING'}"
        )

        keys, sources = load_groq_keys_with_sources()
        if not keys:
            local_keys_file = REPO_ROOT / "keys.json"
            return (
                f"⚠️ No valid Groq API keys detected.\n\n"
                f"- **Primary (Project-Local):** Open `{local_keys_file}`, paste your `gsk_...` key(s), and save.\n"
                f"- **Global Fallback:** `{DEFAULT_KEYS_PATH}` or `GROQ_API_KEY` env var.\n"
                f"- **Runtime Binaries:** {bin_summary}"
            )

        pool = KeyPool(keys)
        now = time.time()
        live_cooling = sum(1 for i, (until, _) in pool.cool.items() if i not in pool.dead and until > now)
        ready_count = pool.live() - live_cooling
        lines = [
            f"⚡ **Groq Key Pool Status** ({len(keys)} total keys registered)\n",
            f"- **Active Model:** `{MODEL}`",
            f"- **Key Sources:** {', '.join(sources) if sources else 'configured'}",
            f"- **Runtime Binaries:** {bin_summary}",
            f"- **Keys Ready:** {ready_count} / {len(keys)}\n",
            "| Key ID | Status | Cooldown Remaining | Reset Time |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for idx in range(len(keys)):
            kid = pool.ids[idx]
            if idx in pool.dead:
                lines.append(f"| `{kid}` | ❌ Dead (401/403) | - | - |")
            elif idx in pool.cool:
                until, kind = pool.cool[idx]
                rem = max(0, int(until - now))
                if rem > 0:
                    lines.append(f"| `{kid}` | ⏳ Cooling ({kind}) | {rem}s | {time.strftime('%H:%M:%S', time.localtime(until))} |")
                else:
                    lines.append(f"| `{kid}` | ✅ Ready | - | - |")
            else:
                lines.append(f"| `{kid}` | ✅ Ready | - | - |")

        return "\n".join(lines)
    except Exception as exc:
        return f"❌ Failed to check Groq quota: {exc}"


def _run_bootstrap(doctor_only: bool = False) -> int:
    bootstrap_file = REPO_ROOT / "bootstrap.py"
    if bootstrap_file.is_file():
        spec = importlib.util.spec_from_file_location("whis_tube_bootstrap", bootstrap_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not doctor_only:
                mod.ensure_all(quiet=False, register=True)
            return mod.run_doctor(print_report=True)

    # Package-only fallback when bootstrap.py is not adjacent
    if not doctor_only:
        ensure_runtime_binaries(quiet=False)
    print(asyncio.run(check_groq_quota()))
    return 0


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whis-tube",
        description="whis-tube MCP server (default with no flags) and direct CLI runner.",
    )
    parser.add_argument("--setup", action="store_true", help="Install/repair runtime dependencies without sudo.")
    parser.add_argument("--doctor", action="store_true", help="Inspect binaries, Python env, and Groq key pool.")
    parser.add_argument("--check-quota", action="store_true", help="Show Groq key pool & binary readiness.")
    parser.add_argument("--info", metavar="URL", help="Fetch YouTube video metadata.")
    parser.add_argument("--list-channel", metavar="CHANNEL_URL", help="List channel videos chronologically.")
    parser.add_argument("--limit", type=int, default=30, help="Max videos for --list-channel (default: 30).")
    parser.add_argument(
        "--sort",
        choices=("oldest_first", "newest_first"),
        default="oldest_first",
        help="Sort order for --list-channel (default: oldest_first).",
    )
    parser.add_argument(
        "--keyframe",
        nargs=2,
        metavar=("URL", "TIMESTAMP"),
        help="Extract HD keyframe from URL at TIMESTAMP (e.g. 00:15:30).",
    )
    parser.add_argument("--resolution", type=int, default=720, help="Keyframe height: 720 or 1080 (default: 720).")
    parser.add_argument("--transcribe", metavar="URL", help="Transcribe a YouTube video verbatim.")
    parser.add_argument("--output", default="", help="Output file or directory for --transcribe / --keyframe.")
    parser.add_argument("--language", default="", help="Language code override for --transcribe (e.g. id, en).")
    parser.add_argument("--glossary", default="", help="Comma-separated glossary terms for --transcribe.")
    return parser


def main():
    """Run the FastMCP server over stdio by default, or execute direct CLI commands."""
    if len(sys.argv) <= 1:
        mcp.run()
        return

    args = _build_cli_parser().parse_args()

    if args.setup:
        sys.exit(_run_bootstrap(doctor_only=False))
    if args.doctor:
        sys.exit(_run_bootstrap(doctor_only=True))

    output: Optional[str] = None
    if args.check_quota:
        output = asyncio.run(check_groq_quota())
    elif args.info:
        output = asyncio.run(get_video_info(args.info))
    elif args.list_channel:
        output = asyncio.run(list_channel_videos(args.list_channel, limit=args.limit, sort_order=args.sort))
    elif args.keyframe:
        url, ts = args.keyframe
        output = asyncio.run(
            extract_keyframe(url, ts, output_path=args.output, resolution=args.resolution)
        )
    elif args.transcribe:
        output = asyncio.run(
            transcribe_youtube(
                args.transcribe,
                output_path=args.output,
                language=args.language,
                glossary=args.glossary,
            )
        )
    else:
        mcp.run()
        return

    print(output)
    if output.lstrip().startswith("❌"):
        sys.exit(1)


if __name__ == "__main__":
    main()
