"""Audio extraction, SoX FLAC mono conversion, silence-detected chunking, and transcription orchestration."""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    CKPT_ROOT,
    MAX_UPLOAD_BYTES,
    MODEL,
    SCRATCH_DIR,
    SEARCH_BACK_S,
    SEARCH_FWD_S,
    SILENCE_THRESHOLDS_DB,
    TARGET_CHUNK_S,
    YTDLP_BASE,
)
from .groq_pool import (
    KeyPool,
    QuotaExhausted,
    load_groq_keys,
    transcribe_chunk,
)
from .utils import (
    ffprobe_duration,
    fmt_ts,
    run_command,
    sanitize_filename,
)

logger = logging.getLogger("whis-tube.audio")


def get_video_info(url: str) -> Dict[str, Any]:
    """Fetch video metadata via yt-dlp."""
    res = run_command(YTDLP_BASE + ["--dump-json", "--", url], check=True)
    return json.loads(res.stdout)


def pick_audio_format(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Select the best original-language, non-dubbed, non-DRC audio-only HTTP format."""
    lang = (info.get("language") or "").lower()
    cands = []
    for f in info.get("formats", []):
        if f.get("vcodec") not in (None, "none") or f.get("acodec") in (None, "none"):
            continue
        proto = str(f.get("protocol") or "")
        if not proto.startswith("http") or "m3u8" in proto:
            continue
        note = (f.get("format_note") or "").lower()
        if "dubbed" in note:
            continue
        cands.append(f)

    if not cands:
        return None

    originals = [
        f for f in cands
        if "original" in (f.get("format_note") or "").lower()
        or (f.get("language_preference") or -1) >= 10
    ]
    if originals:
        cands = originals
    elif lang:
        same = [
            f for f in cands
            if (f.get("language") or "").lower().split("-")[0] in ("", lang.split("-")[0])
        ]
        cands = same or cands

    def is_drc(f: Dict[str, Any]) -> bool:
        return "drc" in str(f.get("format_id", "")).lower() or "drc" in (f.get("format_note") or "").lower()

    if any(not is_drc(f) for f in cands):
        cands = [f for f in cands if not is_drc(f)]

    def rank(f: Dict[str, Any]) -> Tuple[float, int]:
        # Give Opus a 15% edge over AAC at equivalent bitrates
        abr = f.get("abr") or f.get("tbr") or 0
        opus = str(f.get("acodec", "")).startswith("opus")
        return (abr * (1.15 if opus else 1.0), f.get("asr") or 0)

    return max(cands, key=rank)


def download_audio(url: str, info: Dict[str, Any]) -> Tuple[pathlib.Path, Dict[str, Any]]:
    """Download highest-fidelity raw audio track with caching."""
    vid = info["id"]
    fmt = pick_audio_format(info)
    attempts: List[Tuple[str, List[str], bool]] = []
    if fmt:
        attempts.append((str(fmt["format_id"]), [], False))
    attempts.append(("bestaudio", [], False))
    attempts.append(("ba/18/b", ["--extractor-args", "youtube:player_client=android"], True))

    for fsel, extra, degraded in attempts:
        tag = re.sub(r"[^A-Za-z0-9-]", "_", fsel)
        cached = [
            c for c in SCRATCH_DIR.glob(f"yt_{vid}.{tag}.*")
            if not c.name.endswith((".part", ".ytdl", ".flac"))
            and c.stat().st_size > 50 * 1024
            and ffprobe_duration(c) > 0
        ]
        if cached:
            path = cached[0]
            logger.info(f"Reusing cached audio: {path.name}")
        else:
            logger.info(f"Downloading audio with format selector '{fsel}'...")
            p = run_command(
                YTDLP_BASE + extra + ["-f", fsel, "-o", str(SCRATCH_DIR / f"yt_{vid}.{tag}.%(ext)s"), "--", url],
                check=False,
            )
            files = [
                c for c in SCRATCH_DIR.glob(f"yt_{vid}.{tag}.*")
                if not c.name.endswith((".part", ".ytdl", ".flac"))
            ]
            if p.returncode != 0 or not files:
                logger.warning(f"Audio download attempt failed: {(p.stderr or '').strip().splitlines()[-1:]}")
                continue
            path = files[0]

            try:
                probe_res = run_command(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "a:0",
                        "-show_entries",
                        "stream=codec_name,sample_rate,channels,bit_rate",
                        "-of",
                        "json",
                        str(path),
                    ],
                    check=False,
                )
                if probe_res.returncode != 0 or not probe_res.stdout.strip():
                    logger.warning(f"ffprobe failed for {path.name}: {probe_res.stderr}")
                    continue
                probe = json.loads(probe_res.stdout)
            except Exception as probe_err:
                logger.warning(f"Failed to probe audio file {path.name}: {probe_err}")
                continue

            st = (probe.get("streams") or [{}])[0]
            chosen = bool(fmt) and fsel == str(fmt.get("format_id") if fmt else "")

            def _safe_int(val: Any) -> int:
                if val is None:
                    return 0
                s = str(val).strip()
                if s.isdigit():
                    return int(s)
                try:
                    return int(float(s))
                except (ValueError, TypeError):
                    return 0

            raw_sr = _safe_int(st.get("sample_rate"))
            raw_br = _safe_int(st.get("bit_rate"))
            abr_val = (fmt.get("abr") if (chosen and fmt) else 0) or 0
            bitrate_kbps = round(float(abr_val) if abr_val else (raw_br / 1000.0), 1)

            meta = {
                "format_selector": fsel,
                "format_id": fmt.get("format_id") if (chosen and fmt) else fsel,
                "format_note": fmt.get("format_note") if (chosen and fmt) else None,
                "codec": st.get("codec_name"),
                "sample_rate": raw_sr,
                "channels": st.get("channels"),
                "bitrate_kbps": bitrate_kbps,
                "degraded_fallback": degraded,
                "file": path.name,
            }
            if degraded:
                logger.warning("Using degraded progressive fallback audio.")
            return path, meta

    raise RuntimeError(f"All audio download attempts failed for {vid}")


def to_flac16k(src: pathlib.Path) -> pathlib.Path:
    """Decode audio once to lossless 16 kHz mono FLAC with SoX high-precision resampler."""
    if not src.is_file() or src.stat().st_size == 0:
        raise RuntimeError(f"Audio source is missing or empty: {src}")

    out = src.with_suffix(".16k.flac")
    if out.exists() and out.stat().st_size > 0 and ffprobe_duration(out) > 0:
        return out
    out.unlink(missing_ok=True)

    logger.info("Decoding to lossless 16 kHz mono FLAC (SoX resampler)...")
    result = run_command([
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        "aresample=16000:resampler=soxr:precision=28",
        "-ac",
        "1",
        "-sample_fmt",
        "s16",
        "-c:a",
        "flac",
        "-compression_level",
        "8",
        str(out),
    ], check=False)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["ffmpeg did not produce audio"]
        raise RuntimeError(f"Unable to decode an audio stream from {src.name}: {detail[0]}")
    if ffprobe_duration(out) <= 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"Decoded audio is empty or has an invalid duration: {src.name}")
    return out


def parse_silence_events(stderr: str, duration: Optional[float] = None) -> List[Tuple[float, float]]:
    """Parse silencedetect events sequentially to preserve correct start-end pairing."""
    pairs: List[Tuple[float, float]] = []
    current_start: Optional[float] = None
    for line in (stderr or "").splitlines():
        start_match = re.search(r"silence_start:\s*([\d.]+)", line)
        if start_match:
            current_start = float(start_match.group(1))
            continue
        end_match = re.search(r"silence_end:\s*([\d.]+)", line)
        if end_match:
            end_val = float(end_match.group(1))
            start_val = current_start if current_start is not None else 0.0
            if end_val > start_val:
                pairs.append((start_val, end_val))
            current_start = None

    if current_start is not None and duration is not None and duration > current_start:
        pairs.append((current_start, duration))
    return pairs


def detect_silences(flac: pathlib.Path, duration: Optional[float] = None) -> Dict[int, List[Tuple[float, float]]]:
    """Detect silences across multiple decibel thresholds (-40dB to -20dB)."""
    if duration is None:
        duration = ffprobe_duration(flac)

    out = {}
    for db in SILENCE_THRESHOLDS_DB:
        p = run_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(flac),
                "-af",
                f"silencedetect=noise={db}dB:d=0.25",
                "-f",
                "null",
                "-",
            ],
            check=False,
        )
        out[db] = parse_silence_events(p.stderr, duration=duration)
    return out


def plan_cuts(
    duration: float,
    silences: Dict[int, List[Tuple[float, float]]],
) -> List[Tuple[float, float, str]]:
    """Cut audio at the deepest pause near each ~10 min target length."""
    if duration <= 0:
        raise ValueError("Audio duration must be greater than 0.")

    bounds, start = [], 0.0
    while duration - start > TARGET_CHUNK_S + SEARCH_FWD_S:
        target = start + TARGET_CHUNK_S
        cut, how = target, "hard-cut (no pause found)"
        for db in SILENCE_THRESHOLDS_DB:
            window = [
                (s, e) for s, e in silences.get(db, [])
                if target - SEARCH_BACK_S <= (s + e) / 2 <= target + SEARCH_FWD_S
            ]
            if window:
                s, e = max(window, key=lambda se: (min(se[1] - se[0], 2.0), -abs((se[0] + se[1]) / 2 - target)))
                cut, how = (s + e) / 2, f"pause {e - s:.2f}s @ {db} dB"
                break
        bounds.append((start, cut, how))
        start = cut
    bounds.append((start, duration, "end"))
    return bounds


def cut_chunk(flac: pathlib.Path, idx: int, start: float, end: float) -> pathlib.Path:
    """Extract sample-accurate audio chunk from FLAC master."""
    out = flac.with_name(f"{flac.stem}.chunk{idx:03d}.flac")
    run_command([
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(flac),
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-c:a",
        "flac",
        "-compression_level",
        "8",
        str(out),
    ])
    if out.stat().st_size > MAX_UPLOAD_BYTES:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"Chunk {out.name} exceeds upload cap; lower TARGET_CHUNK_S.")
    return out


def _atomic_json(path: pathlib.Path, obj: Any) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_or_make_plan(
    vid: str,
    flac: pathlib.Path,
    real_dur: float,
) -> Tuple[List[Tuple[float, float, str]], bool]:
    """Retrieve saved cutting plan from checkpoint or generate fresh plan."""
    if real_dur <= 0:
        raise ValueError(f"Cannot create plan for zero or negative duration: {real_dur}")
    p = CKPT_ROOT / vid / "plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            if abs(st.get("duration", 0) - real_dur) < 0.5 and st.get("model") == MODEL:
                return [tuple(b) for b in st["bounds"]], True
            shutil.rmtree(p.parent, ignore_errors=True)
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    bounds = plan_cuts(real_dur, detect_silences(flac, duration=real_dur))
    _atomic_json(p, {"duration": real_dur, "model": MODEL, "bounds": bounds})
    return bounds, False


def load_chunk_ckpt(vid: str, idx: int) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    p = CKPT_ROOT / vid / f"chunk{idx:03d}.json"
    if not p.exists():
        return None
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
        return st["segments"], st["words"]
    except Exception:
        return None


def save_chunk_ckpt(vid: str, idx: int, segs: List[Dict[str, Any]], words: List[Dict[str, Any]]) -> None:
    _atomic_json(CKPT_ROOT / vid / f"chunk{idx:03d}.json", {"segments": segs, "words": words})


def transcribe_video(
    url: str,
    output_path: str = "",
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Run full verbatim audio transcription pipeline with multi-key Groq Whisper Large V3."""
    keys = load_groq_keys()
    if not keys:
        raise RuntimeError("No Groq API keys found. Set GROQ_API_KEY or configure ~/.config/groq/keys.json")
    pool = KeyPool(keys)

    info = get_video_info(url)
    vid = info["id"]
    title = info.get("title") or f"Video_{vid}"
    duration = int(info.get("duration") or 0)
    channel = info.get("channel") or info.get("uploader") or "YouTube Creator"
    lang = language or (info.get("language") or "").split("-")[0].lower() or None

    if info.get("live_status") == "is_live":
        raise RuntimeError("Video is currently broadcasting live; wait until the stream ends.")
    if info.get("live_status") in ("is_upcoming", "post_live"):
        raise RuntimeError("Video is an upcoming premiere/live stream and has not aired yet.")

    safe_title = sanitize_filename(title)
    default_name = f"{vid}_{safe_title}.md"

    if not output_path:
        out_dir = pathlib.Path("transcripts")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / default_name
    else:
        target = pathlib.Path(output_path)
        if target.is_dir() or output_path.endswith(("/", "\\")):
            target.mkdir(parents=True, exist_ok=True)
            out_file = target / default_name
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            out_file = target

    t0 = time.time()
    src, audio_meta = download_audio(url, info)
    flac = to_flac16k(src)
    real_dur = ffprobe_duration(flac)
    bounds, reused = load_or_make_plan(vid, flac, real_dur)

    base_prompt = f"{title}. {channel}."
    segments: List[Dict[str, Any]] = []
    words: List[Dict[str, Any]] = []
    resumed = 0
    idx = 0

    try:
        for idx, (start, end, how) in enumerate(bounds):
            cached = load_chunk_ckpt(vid, idx)
            if cached:
                segs, wds = cached
                resumed += 1
            else:
                chunk = cut_chunk(flac, idx, start, end)
                try:
                    tail = " ".join(s["text"] for s in segments[-6:])[-400:]
                    prompt = (base_prompt + " " + tail).strip()[-600:]
                    segs, wds = transcribe_chunk(pool, chunk, start, lang, prompt)
                    save_chunk_ckpt(vid, idx, segs, wds)
                finally:
                    chunk.unlink(missing_ok=True)
            segments.extend(segs)
            words.extend(wds)
    except QuotaExhausted as e:
        e.video, e.progress = vid, f"{idx}/{len(bounds)}"
        raise

    segments.sort(key=lambda s: s["start"])
    flagged = [s for s in segments if s["flags"]]

    # Build verbatim Markdown
    a = audio_meta
    lines = [
        f"# {title}",
        "",
        f"- **Channel / Speaker:** {channel}",
        f"- **URL:** https://www.youtube.com/watch?v={vid}",
        f"- **Duration:** {fmt_ts(duration)} ({duration}s)",
        f"- **Transcription Engine:** Groq {MODEL} (verbatim, temperature 0, language: {lang or 'auto'})",
        f"- **Audio Source:** format {a['format_id']} | {a['codec']} {a['bitrate_kbps']} kbps {a['sample_rate']} Hz | {a['format_note'] or '-'}"
        + (" | DEGRADED FALLBACK" if a["degraded_fallback"] else ""),
        f"- **Preprocessing:** Lossless FLAC 16 kHz mono (SoX resampler), {len(bounds)} silence-aligned chunk(s)",
        f"- **Key Pool:** {pool.live()} valid of {len(keys)} Groq keys",
        f"- **Chunk Cuts:** " + ("; ".join(f"{fmt_ts(e)} ({h})" for _, e, h in bounds[:-1]) if len(bounds) > 1 else "None (single chunk)"),
        f"- **Low-Confidence Segments:** {len(flagged)} of {len(segments)} (flagged for video frame verification)",
        f"- **Extracted Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## Verbatim Transcript (Timestamped)",
        "",
    ]
    for s in segments:
        lines.append(f"**[{fmt_ts(s['start'])} - {fmt_ts(s['end'])}]** {s['text']}\n")

    if flagged:
        lines += [
            "",
            "---",
            "",
            "## Low-Confidence Segments (Verify with Video Frames / Context)",
            "",
        ]
        for s in flagged:
            lines.append(f"- [{fmt_ts(s['start'])}] {', '.join(s['flags'])}: {s['text'][:140]}")

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Build raw metadata JSON
    raw_file = out_file.with_name(out_file.stem + "_raw.json")
    raw_file.write_text(
        json.dumps(
            {
                "info": {
                    "id": vid,
                    "title": title,
                    "duration": duration,
                    "channel": channel,
                    "language": lang,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                },
                "audio": audio_meta,
                "pipeline": {
                    "model": MODEL,
                    "temperature": 0,
                    "preprocess": "flac_16k_mono_soxr",
                    "resumed_chunks": resumed,
                    "chunks": [
                        {"start": round(s, 3), "end": round(e, 3), "cut": h}
                        for s, e, h in bounds
                    ],
                },
                "segments": segments,
                "words": words,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Clean up checkpoint folder upon full success
    shutil.rmtree(CKPT_ROOT / vid, ignore_errors=True)

    elapsed = round(time.time() - t0, 1)
    word_count = sum(len(s["text"].split()) for s in segments)

    return {
        "status": "success",
        "video_id": vid,
        "title": title,
        "channel": channel,
        "duration": fmt_ts(duration),
        "total_segments": len(segments),
        "total_words": word_count,
        "low_confidence_segments": len(flagged),
        "transcript_path": str(out_file.resolve()),
        "raw_json_path": str(raw_file.resolve()),
        "elapsed_seconds": elapsed,
    }
