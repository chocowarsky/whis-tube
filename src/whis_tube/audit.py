"""Deterministic workspace scaffolder and research report compliance auditor for whis-tube.

Designed so both frontier and lightweight AI models (e.g. Flash / Hydrogen) produce
consistent, exhaustive, zero-defect YouTube research deliverables on long runs.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

from .utils import (
    classify_asset_type,
    format_catalog_duration,
    parse_ts,
    run_command,
    sanitize_filename,
    slugify_channel,
)

_REPORT_NAME_RE = re.compile(r"^[a-z0-9-]+_(vid|live)_(\d+)_([A-Za-z0-9_-]{11})_(.+)\.md$")
_REPORT_NAME_FALLBACK_RE = re.compile(r"^[a-z0-9-]+_(vid|live)_(\d+)_([A-Za-z0-9-]{6,})_(.+)\.md$")
_LATEX_CMD_RE = re.compile(
    r"\\(?:approx|rightarrow|leftarrow|times|text|frac|cdot|le|ge|leq|geq|begin|end)\b"
)
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_EMBED_FRAME_RE = re.compile(r"!\[[^\]]*\]\(frames/([^)]+\.(?:jpg|jpeg|png))\)")
_TS_RE = re.compile(r"\b(\d{2}:\d{2}:\d{2})\b")
_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*(\[Watch\]\([^)]+\))\s*\|$")

_SECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("Video Metadata", re.compile(r"^##\s+.*(?:video\s+metadata|metadata)", re.IGNORECASE | re.MULTILINE)),
    ("Executive Summary", re.compile(r"^##\s+.*(?:executive\s+summary|ringkasan\s+eksekutif)", re.IGNORECASE | re.MULTILINE)),
    ("Visual Evidence", re.compile(r"^##\s+.*(?:visual\s+evidence|screenshots?|bukti\s+visual)", re.IGNORECASE | re.MULTILINE)),
    ("Deep Conceptual Deconstruction", re.compile(r"^##\s+.*(?:deep\s+conceptual|deconstruction|analisis\s+mendalam|bedah\s+konsep)", re.IGNORECASE | re.MULTILINE)),
    ("Technical Compliance Check", re.compile(r"^##\s+.*(?:technical\s+compliance|compliance\s+check|kepatuhan\s+teknis)", re.IGNORECASE | re.MULTILINE)),
]

_DONE_MARKERS = ("✅", "SELESAI", "DONE")


def _write_crlf(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 text strictly with Windows CRLF (\\r\\n) line endings."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    path.write_bytes(normalized.replace("\n", "\r\n").encode("utf-8"))


def _is_done_status(status: str) -> bool:
    upper = status.upper()
    return any(tok in upper for tok in _DONE_MARKERS)


def _normalize_channel_tab_url(channel_url: str, asset_type: str) -> str:
    """Return canonical channel tab URL ending with /videos or /streams."""
    base = str(channel_url or "").strip().rstrip("/")
    suffix = "streams" if asset_type == "livestreams" else "videos"
    if not base:
        return f"https://www.youtube.com/{suffix}"
    for tail in ("/videos", "/streams", "/featured", "/playlists", "/shorts"):
        if base.endswith(tail):
            base = base[: -len(tail)]
            break
    return f"{base}/{suffix}"


def _parse_catalog_rows(text: str) -> List[Dict[str, str]]:
    """Parse existing Markdown catalog rows into structured dicts."""
    rows: List[Dict[str, str]] = []
    for raw_line in text.splitlines():
        m = _ROW_RE.match(raw_line.strip())
        if not m:
            continue
        rows.append({
            "num": m.group(1).strip(),
            "video_id": m.group(2).strip(),
            "duration": m.group(3).strip(),
            "status": m.group(4).strip(),
            "title": m.group(5).strip(),
            "link": m.group(6).strip(),
        })
    return rows


def _render_catalog(
    channel_name: str,
    tab_url: str,
    asset_type: str,
    rows: List[Dict[str, str]],
) -> str:
    """Render a standardized master catalog file with accurate header counters."""
    is_live = asset_type == "livestreams"
    heading = f"# {'Livestream' if is_live else 'Video'} Catalog: {channel_name}"
    total_label = "Total Livestreams" if is_live else "Total Videos"

    total = len(rows)
    done_count = sum(1 for r in rows if _is_done_status(r["status"]))
    pending_count = total - done_count
    range_suffix = f" (#1 to #{total})" if total > 0 else ""

    lines = [
        heading,
        "",
        f"- **Channel URL:** {tab_url}",
        f"- **{total_label}:** {total}",
        f"- **Transcription Status:** {done_count} Done, {pending_count} Pending{range_suffix}",
        f"- **Analysis Status:** {done_count} Done, {pending_count} Pending{range_suffix}",
        "",
        "| No. | Video ID | Duration | Status | Title | Link |",
        "| :---: | :---: | :---: | :---: | :--- | :---: |",
    ]
    for r in rows:
        clean_title = r["title"].replace("|", "/")
        lines.append(
            f"| {r['num']} | `{r['video_id']}` | {r['duration']} | {r['status']} | {clean_title} | {r['link']} |"
        )
    return "\n".join(lines) + "\n"


def _upsert_catalog_row(
    catalog_path: pathlib.Path,
    channel_name: str,
    tab_url: str,
    asset_type: str,
    video_id: str,
    title: str,
    duration: str,
    status: str,
) -> int:
    """Insert or update a single video row in a CRLF master catalog and return its row number."""
    existing_text = catalog_path.read_text(encoding="utf-8") if catalog_path.is_file() else ""
    rows = _parse_catalog_rows(existing_text)

    existing_tab_url = tab_url
    url_match = re.search(r"^- \*\*Channel URL:\*\*\s*(\S+)", existing_text, re.MULTILINE)
    if url_match and not tab_url:
        existing_tab_url = url_match.group(1).strip()

    row_num = 0
    for row in rows:
        if row["video_id"] == video_id:
            row["status"] = status
            if title:
                row["title"] = title
            if duration:
                row["duration"] = duration
            row_num = int(row["num"])
            break

    if row_num == 0:
        row_num = (max((int(r["num"]) for r in rows), default=0)) + 1
        rows.append({
            "num": str(row_num),
            "video_id": video_id,
            "duration": duration or "0m 00s",
            "status": status,
            "title": title or video_id,
            "link": f"[Watch](https://www.youtube.com/watch?v={video_id})",
        })

    rendered = _render_catalog(channel_name, existing_tab_url, asset_type, rows)
    _write_crlf(catalog_path, rendered)
    return row_num


def scaffold_channel_workspace(
    workspace_root: str,
    channel_name: str,
    channel_url: str = "",
    channel_slug: str = "",
    video_id: str = "",
    title: str = "",
    duration: str = "",
    asset_type: str = "videos",
    status: str = "⏳ In Progress",
) -> Dict[str, Any]:
    """Create or update a standardized youtube-research/<channel-slug> workspace and CRLF catalogs.

    Safely preserves existing catalog rows and strictly enforces Windows CRLF (\\r\\n) endings.
    Can also be called at completion with status='✅ **SELESAI**' (or '✅ **DONE**') to flip a row cleanly.
    """
    slug = slugify_channel(channel_slug or channel_name)
    norm_type = (
        "livestreams"
        if str(asset_type or "").strip().lower() in {"livestreams", "livestream", "live"}
        else classify_asset_type(asset_type)
    )

    root = pathlib.Path(workspace_root).expanduser().resolve()
    channel_dir = root / slug

    for rel in (
        "analysis/videos/frames",
        "analysis/livestreams/frames",
        "raw-transcripts/videos",
        "raw-transcripts/livestreams",
    ):
        (channel_dir / rel).mkdir(parents=True, exist_ok=True)

    cat_video = channel_dir / "catalog_video.md"
    cat_live = channel_dir / "catalog_livestream.md"

    vid_tab_url = _normalize_channel_tab_url(channel_url, "videos")
    live_tab_url = _normalize_channel_tab_url(channel_url, "livestreams")

    if not cat_video.is_file():
        _write_crlf(cat_video, _render_catalog(channel_name, vid_tab_url, "videos", []))
    if not cat_live.is_file():
        _write_crlf(cat_live, _render_catalog(channel_name, live_tab_url, "livestreams", []))

    row_num: Optional[int] = None
    target_catalog = cat_live if norm_type == "livestreams" else cat_video
    target_tab_url = live_tab_url if norm_type == "livestreams" else vid_tab_url

    norm_duration = duration
    if duration and duration.strip().isdigit():
        norm_duration = format_catalog_duration(int(duration.strip()))

    if video_id:
        row_num = _upsert_catalog_row(
            catalog_path=target_catalog,
            channel_name=channel_name,
            tab_url=target_tab_url,
            asset_type=norm_type,
            video_id=video_id.strip(),
            title=title.strip(),
            duration=norm_duration.strip(),
            status=status.strip(),
        )

    safe_title = sanitize_filename(title or video_id or "video")
    prefix = "live" if norm_type == "livestreams" else "vid"
    num_tag = str(row_num or 1)
    vid_clean = sanitize_filename(video_id) if video_id else "<video_id>"

    rec_transcript = channel_dir / "raw-transcripts" / norm_type / f"{vid_clean}_{safe_title}.md"
    rec_analysis = channel_dir / "analysis" / norm_type / f"{slug}_{prefix}_{num_tag}_{vid_clean}_{safe_title}.md"
    rec_frames_dir = channel_dir / "analysis" / norm_type / "frames"

    return {
        "status": "success",
        "channel_name": channel_name,
        "channel_slug": slug,
        "channel_dir": str(channel_dir),
        "asset_type": norm_type,
        "row_number": row_num,
        "catalog_video": str(cat_video),
        "catalog_livestream": str(cat_live),
        "active_catalog": str(target_catalog),
        "recommended_transcript_path": str(rec_transcript),
        "recommended_analysis_path": str(rec_analysis),
        "recommended_frames_dir": str(rec_frames_dir),
    }


def _probe_image_dimensions(path: pathlib.Path) -> Optional[Tuple[int, int]]:
    """Return (width, height) of an image using ffprobe, or None on error."""
    res = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=False,
    )
    if res.returncode != 0:
        return None
    parts = [p.strip() for p in (res.stdout or "").strip().split(",") if p.strip()]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _detect_duration_seconds(report_text: str, raw_json_path: Optional[pathlib.Path]) -> int:
    """Resolve video duration in seconds from raw JSON or report metadata."""
    if raw_json_path and raw_json_path.is_file():
        try:
            payload = json.loads(raw_json_path.read_text(encoding="utf-8"))
            dur = int((payload.get("info") or {}).get("duration") or 0)
            if dur > 0:
                return dur
        except Exception:
            pass

    m = re.search(r"(?:Durasi|Duration)\s*:\*\*\s*(\d{2}:\d{2}:\d{2})", report_text, re.IGNORECASE)
    if m:
        try:
            return int(parse_ts(m.group(1)))
        except ValueError:
            pass
    return 0


def _compute_quality_floors(duration_s: int, is_livestream: bool) -> Tuple[int, int, int]:
    """Return (min_frames, min_words, min_subsections) proportional to duration and asset type."""
    if duration_s >= 5400:
        return (12, 2400, 7)
    if duration_s >= 2700 or is_livestream:
        return (12, 1800, 6)
    if duration_s >= 1200:
        return (10, 1200, 4)
    return (10, 800, 3)


def _check_anti_latex(lines: List[str]) -> List[str]:
    """Return exact violations for any '$' delimiter or LaTeX macro commands."""
    errors: List[str] = []
    dollar_lines: List[int] = []
    cmd_hits: List[str] = []

    for idx, line in enumerate(lines, 1):
        if "$" in line:
            dollar_lines.append(idx)
        for m in _LATEX_CMD_RE.finditer(line):
            cmd_hits.append(f"L{idx}:{m.group(0)}")

    if dollar_lines:
        sample = ", ".join(f"L{n}" for n in dollar_lines[:10])
        suffix = f" (+{len(dollar_lines) - 10} more)" if len(dollar_lines) > 10 else ""
        errors.append(
            f"Anti-LaTeX violation: found '$' character on {len(dollar_lines)} line(s) ({sample}{suffix}). "
            "Use plain text currency ('100 USD', 'Rp 100.000') instead of '$'."
        )
    if cmd_hits:
        errors.append(
            f"Anti-LaTeX violation: found LaTeX command(s) ({', '.join(cmd_hits[:10])}). "
            "Replace with Unicode symbols (→, ×, ≈, ≤, ≥)."
        )
    return errors


def _check_foreign_paths(report_text: str) -> List[str]:
    """Verify no markdown link or image embed leaks absolute host or Windows paths."""
    bad: List[str] = []
    for m in _MD_LINK_RE.finditer(report_text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "#")):
            continue
        if (
            target.startswith(("/", "file://", "\\\\"))
            or re.match(r"^[A-Za-z]:[/\\]", target)
        ):
            bad.append(target)
    if bad:
        return [
            f"Absolute/foreign path(s) found in Markdown links: {', '.join(bad[:6])}. "
            "Use relative paths ('frames/<id>_<HHMMSS>.jpg', '../../raw-transcripts/...')."
        ]
    return []


def _check_frames(
    report_path: pathlib.Path,
    report_text: str,
    video_id: str,
    min_frames: int,
    require_1080p: bool,
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Audit embedded frame count, 1:1 disk parity, zero orphans, and 1920x1080 dimensions."""
    errors: List[str] = []
    warnings: List[str] = []
    frames_dir = report_path.parent / "frames"

    embedded = _EMBED_FRAME_RE.findall(report_text)
    unique_embedded = sorted(set(embedded))

    if len(unique_embedded) < min_frames:
        errors.append(
            f"Insufficient keyframe density: {len(unique_embedded)} embedded, minimum {min_frames} required."
        )

    missing_files: List[str] = []
    non_1080p: List[str] = []
    dims_seen: set[str] = set()

    for fname in unique_embedded:
        fpath = frames_dir / fname
        if not fpath.is_file() or fpath.stat().st_size == 0:
            missing_files.append(fname)
            continue
        dims = _probe_image_dimensions(fpath)
        if dims is None:
            errors.append(f"Corrupt or unreadable image frame: frames/{fname}")
        else:
            w, h = dims
            dims_seen.add(f"{w}x{h}")
            if require_1080p and (w < 1920 or h < 1080):
                non_1080p.append(f"{fname} ({w}x{h})")

    if missing_files:
        errors.append(f"Broken frame link(s) missing on disk: {', '.join(missing_files[:10])}")
    if non_1080p:
        errors.append(
            f"Sub-1080p frame(s) detected (must be 1920x1080): {', '.join(non_1080p[:10])}. "
            "Re-extract with resolution=1080."
        )

    orphans: List[str] = []
    if frames_dir.is_dir() and video_id:
        prefix = f"{video_id}_"
        for disk_file in sorted(frames_dir.iterdir()):
            if disk_file.is_file() and disk_file.name.startswith(prefix) and disk_file.name not in unique_embedded:
                orphans.append(disk_file.name)
    if orphans:
        errors.append(
            f"Orphan unembedded frame(s) found on disk for '{video_id}': {', '.join(orphans[:10])}. "
            "Embed or delete unused candidate frames."
        )

    stats = {
        "embedded_frames": len(unique_embedded),
        "min_frames": min_frames,
        "dimensions": sorted(dims_seen),
        "orphan_frames": len(orphans),
    }
    return errors, warnings, stats


def _check_catalog_and_workspace(
    report_path: pathlib.Path,
    catalog_path: Optional[pathlib.Path],
) -> Tuple[List[str], List[str]]:
    """Verify catalog CRLF line endings and clean channel workspace tree."""
    errors: List[str] = []
    warnings: List[str] = []

    channel_root: Optional[pathlib.Path] = None
    if len(report_path.parents) >= 3 and report_path.parent.parent.name == "analysis":
        channel_root = report_path.parent.parent.parent

    catalogs_to_check: List[pathlib.Path] = []
    if catalog_path:
        catalogs_to_check.append(catalog_path)
    elif channel_root:
        for cname in ("catalog_video.md", "catalog_livestream.md"):
            cand = channel_root / cname
            if cand.is_file():
                catalogs_to_check.append(cand)

    for cat in catalogs_to_check:
        if not cat.is_file():
            errors.append(f"Specified catalog file does not exist: {cat}")
            continue
        raw_bytes = cat.read_bytes()
        lone_lf = raw_bytes.replace(b"\r\n", b"").count(b"\n")
        if lone_lf > 0 or (b"\n" in raw_bytes and b"\r\n" not in raw_bytes):
            errors.append(
                f"Catalog CRLF violation in {cat.name}: found {lone_lf} lone LF line ending(s). "
                "Master catalogs must strictly use Windows CRLF (\\r\\n)."
            )

    if channel_root and channel_root.is_dir():
        clutter: List[str] = []
        for item in channel_root.iterdir():
            name = item.name
            if name.startswith(("_", ".bak")) or ".bak" in name or name.endswith(".tmp"):
                clutter.append(name)
        if clutter:
            errors.append(
                f"Workspace clutter in {channel_root.name}/: {', '.join(sorted(clutter))}. "
                "Remove internal logs, scratchpads, or .bak files from channel root."
            )

    return errors, warnings


def _resolve_transcript_paths(
    report_path: pathlib.Path,
    report_text: str,
    explicit_transcript: str,
) -> Tuple[Optional[pathlib.Path], Optional[pathlib.Path]]:
    """Locate the linked raw transcript .md and _raw.json files."""
    if explicit_transcript:
        t_md = pathlib.Path(explicit_transcript).expanduser().resolve()
        return t_md, t_md.with_name(t_md.stem + "_raw.json")

    for m in _MD_LINK_RE.finditer(report_text):
        target = m.group(1).strip()
        if "raw-transcripts/" in target and target.endswith(".md"):
            resolved = (report_path.parent / target).resolve()
            return resolved, resolved.with_name(resolved.stem + "_raw.json")
    return None, None


def audit_research_report(
    report_path: str,
    transcript_path: str = "",
    catalog_path: str = "",
    min_frames: int = 0,
    min_words: int = 0,
    require_1080p: bool = True,
) -> Dict[str, Any]:
    """Run deterministic quality & compliance audit on a YouTube research analysis report.

    Returns a dict with passed (bool), errors (list[str]), warnings (list[str]), and metrics (dict).
    """
    rpath = pathlib.Path(report_path).expanduser().resolve()
    errors: List[str] = []
    warnings: List[str] = []

    if not rpath.is_file():
        return {
            "passed": False,
            "report_path": str(rpath),
            "errors": [f"Report file not found: {rpath}"],
            "warnings": [],
            "metrics": {},
        }

    report_text = rpath.read_text(encoding="utf-8")
    lines = report_text.splitlines()
    word_count = len(re.findall(r"\S+", report_text))

    # 1. Filename convention
    video_id = ""
    is_livestream = rpath.parent.name == "livestreams"
    fname_match = _REPORT_NAME_RE.match(rpath.name) or _REPORT_NAME_FALLBACK_RE.match(rpath.name)
    if fname_match:
        is_livestream = fname_match.group(1) == "live"
        video_id = fname_match.group(3)
    else:
        errors.append(
            f"Filename '{rpath.name}' does not match standard "
            "'<slug>_(vid|live)_<num>_<video_id>_<sanitized_title>.md'."
        )
        id_match = re.search(r"Video ID:\*\*\s*`?([A-Za-z0-9_-]{6,})`?", report_text)
        if id_match:
            video_id = id_match.group(1)

    # 2. Raw transcript parity & duration detection
    t_md, t_json = _resolve_transcript_paths(rpath, report_text, transcript_path)
    if t_md is None:
        errors.append(
            "Missing relative link to raw transcript markdown ('../../raw-transcripts/<type>/<id>_<title>.md')."
        )
    else:
        if not t_md.is_file() or t_md.stat().st_size == 0:
            errors.append(f"Raw transcript markdown missing or empty: {t_md}")
        if t_json is None or not t_json.is_file() or t_json.stat().st_size == 0:
            errors.append(f"Raw transcript JSON missing or empty: {t_json}")

    duration_s = _detect_duration_seconds(report_text, t_json)
    auto_frames, auto_words, auto_subs = _compute_quality_floors(duration_s, is_livestream)
    req_frames = min_frames if min_frames > 0 else auto_frames
    req_words = min_words if min_words > 0 else auto_words

    # 3. Required sections & structural depth
    missing_sections = [name for name, pat in _SECTION_PATTERNS if not pat.search(report_text)]
    if missing_sections:
        errors.append(f"Missing required report section(s): {', '.join(missing_sections)}.")

    subsection_count = len(re.findall(r"^###\s+", report_text, re.MULTILINE))
    if subsection_count < auto_subs:
        errors.append(
            f"Insufficient topical breakdown: {subsection_count} '###' subsection(s), "
            f"expected at least {auto_subs} for full chronological coverage."
        )

    if word_count < req_words:
        errors.append(
            f"Report depth too shallow: {word_count} words (minimum {req_words} words for this video duration). "
            "Expand speaker attribution, exact figures, case studies, debates, and chronological detail."
        )

    # 4. Chronological timestamp span check (prevents half-read transcripts)
    ts_values: List[float] = []
    for raw_ts in _TS_RE.findall(report_text):
        try:
            sec = parse_ts(raw_ts)
            if duration_s == 0 or sec <= duration_s + 5:
                ts_values.append(sec)
        except ValueError:
            continue

    if duration_s >= 600:
        if not ts_values:
            errors.append("No HH:MM:SS timestamps cited in report body.")
        else:
            max_ts = max(ts_values)
            min_ts = min(ts_values)
            if min_ts > duration_s * 0.25:
                warnings.append(
                    f"Earliest cited timestamp is {min_ts:.0f}s (>25% into {duration_s}s video); check opening coverage."
                )
            if max_ts < duration_s * 0.75:
                errors.append(
                    f"Incomplete chronological coverage: latest cited timestamp is {max_ts:.0f}s "
                    f"(<75% of {duration_s}s duration). Ensure 100% of the transcript was read to the end."
                )

    # 5. Anti-LaTeX & foreign path checks
    errors.extend(_check_anti_latex(lines))
    errors.extend(_check_foreign_paths(report_text))

    # 6. Frame density, 1:1 parity, zero orphans, and 1080p dimensions
    frame_errs, frame_warns, frame_stats = _check_frames(
        rpath, report_text, video_id, req_frames, require_1080p=require_1080p
    )
    errors.extend(frame_errs)
    warnings.extend(frame_warns)

    # 7. Catalog CRLF & clean workspace
    cat_obj = pathlib.Path(catalog_path).expanduser().resolve() if catalog_path else None
    cat_errs, cat_warns = _check_catalog_and_workspace(rpath, cat_obj)
    errors.extend(cat_errs)
    warnings.extend(cat_warns)

    metrics = {
        "video_id": video_id or "unknown",
        "asset_type": "livestreams" if is_livestream else "videos",
        "duration_seconds": duration_s,
        "word_count": word_count,
        "min_words": req_words,
        "subsection_count": subsection_count,
        "min_subsections": auto_subs,
        "timestamps_cited": len(ts_values),
        **frame_stats,
    }
    return {
        "passed": len(errors) == 0,
        "report_path": str(rpath),
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
    }


def format_audit_result(result: Dict[str, Any]) -> str:
    """Render an audit_research_report dictionary as crisp Markdown output."""
    passed = result.get("passed", False)
    status_line = "✅ **AUDIT PASSED**" if passed else "❌ **AUDIT FAILED**"
    m = result.get("metrics") or {}
    lines = [
        f"{status_line} — `{result.get('report_path')}`",
        "",
        f"- **Video ID / Type:** `{m.get('video_id', '?')}` ({m.get('asset_type', '?')})",
        f"- **Word Count:** {m.get('word_count', 0):,} (min: {m.get('min_words', 0):,})",
        f"- **Chronological Subsections (`###`):** {m.get('subsection_count', 0)} (min: {m.get('min_subsections', 0)})",
        f"- **Embedded Frames:** {m.get('embedded_frames', 0)} (min: {m.get('min_frames', 0)}, orphans: {m.get('orphan_frames', 0)})",
        f"- **Verified Frame Dimensions:** {', '.join(m.get('dimensions') or ['none'])}",
    ]
    errors = result.get("errors") or []
    warnings = result.get("warnings") or []
    if errors:
        lines.append("")
        lines.append("### Errors (Must Fix Before Marking DONE)")
        for err in errors:
            lines.append(f"- ❌ {err}")
    if warnings:
        lines.append("")
        lines.append("### Warnings")
        for warn in warnings:
            lines.append(f"- ⚠️ {warn}")
    return "\n".join(lines)
