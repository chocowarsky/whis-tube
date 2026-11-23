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
from .audit import (
    audit_research_report as _audit_research_report,
    format_audit_result as _format_audit_result,
    scaffold_channel_workspace as _scaffold_channel_workspace,
)
from .config import DEFAULT_KEYS_PATH, MODEL, REPO_ROOT, YTDLP_BASE
from .groq_pool import KeyPool, QuotaExhausted, load_groq_keys_with_sources
from .runtime import ensure_runtime_binaries, is_binary_working
from .utils import (
    classify_asset_type,
    fmt_ts,
    format_catalog_duration,
    list_channel_videos as _list_channel_videos,
    sanitize_filename,
    slugify_channel,
)
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
    preset: str = "auto",
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
        preset: Domain preset(s) for code-switching ('auto', 'none', or comma-separated names
                such as 'tech', 'finance', 'crypto', 'medical', 'gaming', 'business', or custom
                presets defined in lexicon.json). Defaults to 'auto'.
    """
    logger.info(f"Received transcribe request: {url}")
    try:
        # Run blocking CPU/Network pipeline in thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            lambda: _transcribe_video(
                url,
                output_path=output_path,
                language=language or None,
                glossary=glossary,
                preset=preset,
            ),
        )
        active_presets = res.get("active_presets") or []
        preset_str = ", ".join(active_presets) if active_presets else "neutral"
        glossary_info = f"- **Glossary Terms:** {res.get('glossary_terms_count', 0)}\n" if res.get('glossary_terms_count') else ""
        phonetic_info = f"- **Phonetic Corrections:** {res.get('phonetic_corrections_count', 0)}\n" if res.get('phonetic_corrections_count') else ""
        return (
            f"✅ Transcription Successful!\n\n"
            f"- **Title:** {res['title']}\n"
            f"- **Channel:** {res['channel']}\n"
            f"- **Duration:** {res['duration']}\n"
            f"- **Language:** {res.get('language') or 'auto'}\n"
            f"- **Active Presets:** {preset_str}\n"
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
    resolution: int = 1080,
) -> str:
    """Extract a native 1080p (or 720p) HD keyframe at an exact timecode (HH:MM:SS)
    via HLS m3u8 range-seek without downloading full video bytes.

    Args:
        url: YouTube video URL.
        timestamp: Exact timecode string ('HH:MM:SS' or 'MM:SS', e.g. '00:15:30').
        output_path: Optional output path (.jpg) or folder. Defaults to './frames/<video_id>_<HHMMSS>.jpg'.
        resolution: Target resolution height in pixels (1080 or 720). Defaults to 1080.
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
            f"- **File Path (for `read_file` visual inspection):** `{res['image_path']}`\n\n"
            f"**Markdown Embed Snippet (relative):**\n"
            f"```markdown\n{res['markdown_embed']}\n```"
        )
    except Exception as exc:
        logger.error(f"Error extracting keyframe: {exc}", exc_info=True)
        return f"❌ Failed to extract keyframe: {exc}"


# ── Tool 3: get_video_info ──────────────────────────────────────────────────


@mcp.tool()
async def get_video_info(url: str) -> str:
    """Fetch YouTube video metadata plus deterministic channel routing fields
    (channel handle, slug, asset type, sanitized title, and long-run timeout hint).

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
        title = info.get("title") or f"Video_{vid_id}"
        channel = info.get("channel") or info.get("uploader") or "YouTube Creator"
        uploader_id = info.get("uploader_id") or ""
        channel_url = info.get("uploader_url") or info.get("channel_url") or ""
        live_status = info.get("live_status") or "vod/uploaded"

        slug = slugify_channel(channel)
        asset_type = classify_asset_type(live_status)
        safe_title = sanitize_filename(title)
        prefix = "live" if asset_type == "livestreams" else "vid"

        long_run_hint = ""
        if dur >= 2700:
            long_run_hint = (
                f"\n- **Long-Run Hint:** Duration is {fmt_ts(dur)} (>=45m). "
                "Prefer running `./.venv/bin/whis-tube --transcribe` as a background shell command "
                "to avoid 3-minute MCP client timeouts."
            )

        handle_display = f"{uploader_id} ({channel_url})" if uploader_id and channel_url else (channel_url or uploader_id or "N/A")
        return (
            f"ℹ️ **YouTube Video Information**\n\n"
            f"- **Title:** {title}\n"
            f"- **Sanitized Title:** `{safe_title}`\n"
            f"- **Video ID:** `{vid_id}`\n"
            f"- **Channel:** {channel}\n"
            f"- **Channel Handle / URL:** {handle_display}\n"
            f"- **Suggested Channel Slug:** `{slug}`\n"
            f"- **Asset Type:** `{asset_type}`\n"
            f"- **Duration:** {fmt_ts(dur)} ({format_catalog_duration(dur)}, {dur} seconds)\n"
            f"- **Upload Date:** {info.get('upload_date') or 'N/A'}\n"
            f"- **Live Status:** {live_status}\n"
            f"- **Source Language:** {info.get('language') or 'auto'}\n"
            f"- **View Count:** {vc_str}\n"
            f"- **URL:** https://www.youtube.com/watch?v={vid_id}\n"
            f"- **Recommended Raw Transcript:** `youtube-research/{slug}/raw-transcripts/{asset_type}/{vid_id}_{safe_title}.md`\n"
            f"- **Recommended Analysis Report:** `youtube-research/{slug}/analysis/{asset_type}/{slug}_{prefix}_<num>_{vid_id}_{safe_title}.md`"
            f"{long_run_hint}"
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


# ── Tool 6: scaffold_channel_workspace ──────────────────────────────────────


@mcp.tool()
async def scaffold_channel_workspace(
    workspace_root: str,
    channel_name: str,
    channel_url: str = "",
    channel_slug: str = "",
    video_id: str = "",
    title: str = "",
    duration: str = "",
    asset_type: str = "videos",
    status: str = "⏳ In Progress",
) -> str:
    """Create/update a standardized youtube-research/<channel-slug> workspace and CRLF catalogs.

    Safely preserves existing catalog entries, recalculates Done/Pending header counters, and
    strictly enforces Windows CRLF (\\r\\n) line endings. Call again at completion with
    status='✅ **SELESAI**' (or '✅ **DONE**') to finalize a row cleanly.
    """
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            lambda: _scaffold_channel_workspace(
                workspace_root=workspace_root,
                channel_name=channel_name,
                channel_url=channel_url,
                channel_slug=channel_slug,
                video_id=video_id,
                title=title,
                duration=duration,
                asset_type=asset_type,
                status=status,
            ),
        )
        row_info = f"- **Catalog Row:** #{res['row_number']} ({status})\n" if res.get("row_number") else ""
        return (
            f"📁 **Channel Workspace Ready (CRLF Enforced)**\n\n"
            f"- **Channel:** {res['channel_name']} (`{res['channel_slug']}`)\n"
            f"- **Directory:** `{res['channel_dir']}`\n"
            f"- **Active Catalog:** `{res['active_catalog']}`\n"
            f"{row_info}"
            f"- **Transcript Target:** `{res['recommended_transcript_path']}`\n"
            f"- **Frames Directory:** `{res['recommended_frames_dir']}`\n"
            f"- **Analysis Report Target:** `{res['recommended_analysis_path']}`"
        )
    except Exception as exc:
        logger.error(f"Error scaffolding workspace: {exc}", exc_info=True)
        return f"❌ Failed to scaffold workspace: {exc}"


# ── Tool 7: audit_research_report ───────────────────────────────────────────


@mcp.tool()
async def audit_research_report(
    report_path: str,
    transcript_path: str = "",
    catalog_path: str = "",
    min_frames: int = 0,
    min_words: int = 0,
    require_1080p: bool = True,
) -> str:
    """Run deterministic quality & compliance checks on a YouTube research analysis report.

    Verifies filename standard, all 5 core sections, duration-proportional word/subsection depth,
    chronological timestamp coverage, zero LaTeX/'$' characters, zero absolute/foreign paths,
    1:1 frame parity with zero orphans, 1920x1080 resolution via ffprobe, raw transcript parity,
    catalog CRLF endings, and clean channel root. Must PASS before marking a video DONE.
    """
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            lambda: _audit_research_report(
                report_path=report_path,
                transcript_path=transcript_path,
                catalog_path=catalog_path,
                min_frames=min_frames,
                min_words=min_words,
                require_1080p=require_1080p,
            ),
        )
        return _format_audit_result(res)
    except Exception as exc:
        logger.error(f"Error auditing report: {exc}", exc_info=True)
        return f"❌ Failed to audit research report: {exc}"


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
    parser.add_argument("--resolution", type=int, default=1080, help="Keyframe height: 1080 or 720 (default: 1080).")
    parser.add_argument("--transcribe", metavar="URL", help="Transcribe a YouTube video verbatim.")
    parser.add_argument("--output", default="", help="Output file or directory for --transcribe / --keyframe.")
    parser.add_argument("--language", default="", help="Language code override for --transcribe (e.g. id, en).")
    parser.add_argument("--glossary", default="", help="Comma-separated glossary terms for --transcribe.")
    parser.add_argument(
        "--preset",
        default="auto",
        help="Domain preset(s) for code-switching ('auto', 'none', or comma-separated names like 'tech,finance').",
    )
    parser.add_argument("--scaffold", action="store_true", help="Create/update a channel workspace and CRLF catalogs.")
    parser.add_argument("--workspace-root", default="youtube-research", help="Base workspace directory for --scaffold.")
    parser.add_argument("--channel-name", default="", help="Channel display name for --scaffold.")
    parser.add_argument("--channel-url", default="", help="Channel URL/handle for --scaffold.")
    parser.add_argument("--channel-slug", default="", help="Optional explicit channel slug for --scaffold.")
    parser.add_argument("--video-id", default="", help="Optional video ID to seed or update in catalog.")
    parser.add_argument("--title", default="", help="Optional video title for --scaffold.")
    parser.add_argument("--duration", default="", help="Optional video duration (seconds or '1h 04m 42s') for --scaffold.")
    parser.add_argument("--asset-type", default="videos", help="Asset type ('videos' or 'livestreams') for --scaffold.")
    parser.add_argument("--status", default="⏳ In Progress", help="Catalog row status for --scaffold.")
    parser.add_argument("--audit-report", metavar="REPORT_PATH", help="Run compliance & depth audit on an analysis report.")
    parser.add_argument("--transcript", default="", help="Optional explicit raw transcript .md path for --audit-report.")
    parser.add_argument("--catalog", default="", help="Optional explicit catalog .md path for --audit-report.")
    parser.add_argument("--min-frames", type=int, default=0, help="Override minimum embedded frame count for --audit-report.")
    parser.add_argument("--min-words", type=int, default=0, help="Override minimum report word count for --audit-report.")
    parser.add_argument("--allow-720p", action="store_true", help="Allow 720p frames instead of requiring 1920x1080.")
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
                preset=args.preset,
            )
        )
    elif args.scaffold:
        if not args.channel_name:
            print("❌ --scaffold requires --channel-name", file=sys.stderr)
            sys.exit(2)
        output = asyncio.run(
            scaffold_channel_workspace(
                workspace_root=args.workspace_root,
                channel_name=args.channel_name,
                channel_url=args.channel_url,
                channel_slug=args.channel_slug,
                video_id=args.video_id,
                title=args.title,
                duration=args.duration,
                asset_type=args.asset_type,
                status=args.status,
            )
        )
    elif args.audit_report:
        output = asyncio.run(
            audit_research_report(
                report_path=args.audit_report,
                transcript_path=args.transcript,
                catalog_path=args.catalog,
                min_frames=args.min_frames,
                min_words=args.min_words,
                require_1080p=not args.allow_720p,
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
