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
    DEFAULT_KEYS_PATH,
    MAX_UPLOAD_BYTES,
    MODEL,
    REPO_ROOT,
    SCRATCH_DIR,
    SCRATCH_RETENTION_DAYS,
    SEARCH_BACK_S,
    SEARCH_FWD_S,
    SILENCE_THRESHOLDS_DB,
    TARGET_CHUNK_S,
    YTDLP_BASE,
)
from .runtime import ensure_runtime_binaries
from .code_switch import (
    build_whisper_prompt,
    extract_metadata_terms,
    is_hallucination_segment,
    is_prompt_echo_segment,
    load_lexicon_config,
    normalize_code_switch_text,
    resolve_active_presets,
    resolve_language,
    resolve_style_seed,
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
    """Decode audio once to lossless 16 kHz mono FLAC with speech clarity filter & SoX high-precision resampler."""
    if not src.is_file() or src.stat().st_size == 0:
        raise RuntimeError(f"Audio source is missing or empty: {src}")

    out = src.with_suffix(".16k.flac")
    if out.exists() and out.stat().st_size > 0 and ffprobe_duration(out) > 0:
        return out
    out.unlink(missing_ok=True)

    logger.info("Decoding to lossless 16 kHz mono FLAC (speech clarity filter & SoX resampler)...")
    filter_chain = "highpass=f=80,dynaudnorm=f=150:g=15:p=0.95,aresample=16000:resampler=soxr:precision=28"
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
        filter_chain,
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
        logger.warning("Clarity filter with SoX resampler failed; attempting basic aresample fallback...")
        out.unlink(missing_ok=True)
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
            "aresample=16000",
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


def _resolve_confined_path(base_dir: pathlib.Path, filename: str) -> pathlib.Path:
    """Resolve a filename strictly within base_dir to prevent path traversal (CWE-22)."""
    base_real = os.path.realpath(str(base_dir))
    name = str(filename or "")
    if (
        not name
        or name in (".", "..")
        or os.path.isabs(name)
        or "/" in name
        or "\\" in name
        or os.path.basename(name) != name
    ):
        raise ValueError(f"Invalid output filename: {filename}")
    candidate = os.path.realpath(os.path.join(base_real, name))
    base_prefix = base_real if base_real.endswith(os.sep) else base_real + os.sep
    if not candidate.startswith(base_prefix):
        raise ValueError(f"Unsafe path outside target directory: {filename}")
    return pathlib.Path(candidate)


def _atomic_json(path: pathlib.Path, obj: Any) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _ckpt_dir(vid: str) -> pathlib.Path:
    """Resolve a per-video checkpoint directory strictly inside CKPT_ROOT."""
    return _resolve_confined_path(CKPT_ROOT, sanitize_filename(vid))


def load_or_make_plan(
    vid: str,
    flac: pathlib.Path,
    real_dur: float,
) -> Tuple[List[Tuple[float, float, str]], bool]:
    """Retrieve saved cutting plan from checkpoint or generate fresh plan."""
    if real_dur <= 0:
        raise ValueError(f"Cannot create plan for zero or negative duration: {real_dur}")
    p = _ckpt_dir(vid) / "plan.json"
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
    p = _ckpt_dir(vid) / f"chunk{idx:03d}.json"
    if not p.exists():
        return None
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
        return st["segments"], st["words"]
    except Exception:
        return None


def save_chunk_ckpt(vid: str, idx: int, segs: List[Dict[str, Any]], words: List[Dict[str, Any]]) -> None:
    _atomic_json(_ckpt_dir(vid) / f"chunk{idx:03d}.json", {"segments": segs, "words": words})


def prune_scratch_cache(retention_days: int = SCRATCH_RETENTION_DAYS) -> int:
    """Remove stale scratch audio files and abandoned checkpoints older than retention_days."""
    if retention_days < 0:
        return 0
    cutoff = time.time() - (retention_days * 86400)
    removed = 0

    for item in SCRATCH_DIR.glob("yt_*"):
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:
            logger.debug(f"Failed to prune scratch file {item.name}: {exc}")

    if CKPT_ROOT.is_dir():
        for ckpt_dir in CKPT_ROOT.iterdir():
            try:
                if ckpt_dir.is_dir() and ckpt_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(ckpt_dir, ignore_errors=True)
                    removed += 1
            except OSError as exc:
                logger.debug(f"Failed to prune checkpoint dir {ckpt_dir.name}: {exc}")

    if removed:
        logger.info(f"Pruned {removed} stale scratch item(s) older than {retention_days} day(s).")
    return removed


def _is_pid_alive(pid: int) -> bool:
    """Check whether a local process ID is still running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _acquire_video_lock(vid: str, wait_timeout_s: float = 120.0) -> Tuple[pathlib.Path, bool]:
    """Acquire an exclusive PID-aware lock for a video ID.

    Prevents duplicate Groq calls and file races when an MCP client times out at 3m
    while the server is still finishing the final chunks in the background.

    Returns:
        Tuple of (lock_path, waited_for_active_run).
    """
    locks_dir = SCRATCH_DIR / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(locks_dir, 0o700)
        except OSError:
            pass

    lock_path = locks_dir / f"{sanitize_filename(vid)}.lock"
    deadline = time.time() + wait_timeout_s
    waited = False

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, json.dumps({"pid": os.getpid(), "started_at": time.time()}).encode("utf-8"))
            finally:
                os.close(fd)
            return lock_path, waited
        except FileExistsError:
            stale = False
            try:
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                owner_pid = int(payload.get("pid") or 0)
                started_at = float(payload.get("started_at") or 0.0)
                if owner_pid != os.getpid() and not _is_pid_alive(owner_pid):
                    stale = True
                elif (time.time() - started_at) > 7200:
                    stale = True
            except Exception:
                try:
                    if (time.time() - lock_path.stat().st_mtime) > 10:
                        stale = True
                except OSError:
                    stale = True

            if stale:
                lock_path.unlink(missing_ok=True)
                continue

            if time.time() >= deadline:
                raise RuntimeError(
                    f"Another transcription for video '{vid}' is still active. "
                    "Wait for it to finish rather than launching duplicate runs."
                )
            if not waited:
                logger.info(f"Another transcription for '{vid}' is in progress; waiting cleanly for completion...")
                waited = True
            time.sleep(2.0)


def _load_fresh_completed_result(
    out_file: pathlib.Path,
    raw_file: pathlib.Path,
    info: Dict[str, Any],
    t0: float,
    max_age_s: float = 600.0,
) -> Optional[Dict[str, Any]]:
    """If an in-flight transcription just finished writing output files, return its summary."""
    if not (out_file.is_file() and raw_file.is_file()):
        return None
    try:
        if out_file.stat().st_size == 0 or raw_file.stat().st_size == 0:
            return None
        if (time.time() - raw_file.stat().st_mtime) > max_age_s:
            return None
        raw = json.loads(raw_file.read_text(encoding="utf-8"))
        segs = raw.get("segments") or []
        cs = ((raw.get("pipeline") or {}).get("code_switch")) or {}
        r_info = raw.get("info") or {}
        vid = r_info.get("id") or info.get("id") or "video"
        duration = int(r_info.get("duration") or info.get("duration") or 0)
        flagged = [s for s in segs if s.get("flags")]
        return {
            "status": "success",
            "video_id": vid,
            "title": r_info.get("title") or info.get("title") or f"Video_{vid}",
            "channel": r_info.get("channel") or info.get("channel") or "YouTube Creator",
            "duration": fmt_ts(duration),
            "language": r_info.get("language") or cs.get("resolved_language"),
            "total_segments": len(segs),
            "total_words": sum(len(str(s.get("text") or "").split()) for s in segs),
            "low_confidence_segments": len(flagged),
            "active_presets": cs.get("active_presets") or [],
            "glossary_terms_count": int(cs.get("glossary_terms_count") or 0),
            "phonetic_corrections_count": int(cs.get("phonetic_corrections_count") or 0),
            "transcript_path": str(out_file.resolve()),
            "raw_json_path": str(raw_file.resolve()),
            "elapsed_seconds": round(time.time() - t0, 1),
        }
    except Exception:
        return None


def transcribe_video(
    url: str,
    output_path: str = "",
    language: Optional[str] = None,
    glossary: str = "",
    preset: str = "auto",
) -> Dict[str, Any]:
    """Run full verbatim audio transcription pipeline with multi-key Groq Whisper Large V3."""
    ensure_runtime_binaries()
    keys = load_groq_keys()
    if not keys:
        raise RuntimeError(
            f"No valid Groq API keys found. Open {REPO_ROOT / 'keys.json'} and paste your gsk_... key(s), "
            f"or configure {DEFAULT_KEYS_PATH}."
        )
    pool = KeyPool(keys)

    info = get_video_info(url)
    vid = sanitize_filename(str(info.get("id") or "video"))
    title = info.get("title") or f"Video_{vid}"
    duration = int(info.get("duration") or 0)
    channel = info.get("channel") or info.get("uploader") or "YouTube Creator"

    if info.get("live_status") == "is_live":
        raise RuntimeError("Video is currently broadcasting live; wait until the stream ends.")
    if info.get("live_status") in ("is_upcoming", "post_live"):
        raise RuntimeError("Video is an upcoming premiere/live stream and has not aired yet.")

    safe_title = sanitize_filename(title)
    default_name = f"{vid}_{safe_title}.md"

    if not output_path:
        out_dir = pathlib.Path("transcripts")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = _resolve_confined_path(out_dir, default_name)
    else:
        target = pathlib.Path(output_path)
        if target.is_dir() or output_path.endswith(("/", "\\")):
            target.mkdir(parents=True, exist_ok=True)
            out_file = _resolve_confined_path(target, default_name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            out_file = _resolve_confined_path(target.parent, target.name)

    raw_file = _resolve_confined_path(out_file.parent, out_file.stem + "_raw.json")
    t0 = time.time()
    lock_path, waited_for_active = _acquire_video_lock(vid)
    try:
        if waited_for_active:
            completed = _load_fresh_completed_result(out_file, raw_file, info, t0)
            if completed is not None:
                logger.info(f"Reusing freshly completed transcription for '{vid}' at {out_file.name}")
                return completed

        src, audio_meta = download_audio(url, info)
        flac = to_flac16k(src)
        real_dur = ffprobe_duration(flac)
        bounds, reused = load_or_make_plan(vid, flac, real_dur)

        lang = resolve_language(language, info, audio_meta)
        lexicon_cfg = load_lexicon_config()
        active_presets = resolve_active_presets(info, preset=preset, lexicon_cfg=lexicon_cfg)
        style_seed = resolve_style_seed(lang, active_presets, lexicon_cfg=lexicon_cfg)
        terms = extract_metadata_terms(
            info,
            custom_glossary=glossary,
            max_terms=40,
            preset=preset,
            active_presets=active_presets,
            lexicon_cfg=lexicon_cfg,
        )
        base_prompt = build_whisper_prompt(
            title,
            channel,
            lang,
            terms,
            prev_segments=None,
            include_tail=False,
            active_presets=active_presets,
            lexicon_cfg=lexicon_cfg,
        )

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
                        prompt = build_whisper_prompt(
                            title=title,
                            channel=channel,
                            lang=lang,
                            terms=terms,
                            prev_segments=segments,
                            include_tail=True,
                            max_chars=600,
                            active_presets=active_presets,
                            lexicon_cfg=lexicon_cfg,
                        )
                        segs, wds = transcribe_chunk(pool, chunk, start, lang, prompt, base_prompt=base_prompt)
                        for s in segs:
                            if is_prompt_echo_segment(s, terms, style_seed=style_seed):
                                flags = list(s.get("flags") or [])
                                if "prompt_echo" not in flags:
                                    flags.append("prompt_echo")
                                if "possible_hallucination" not in flags:
                                    flags.append("possible_hallucination")
                                s["flags"] = flags
                        save_chunk_ckpt(vid, idx, segs, wds)
                    finally:
                        chunk.unlink(missing_ok=True)
                segments.extend(segs)
                words.extend(wds)
        except QuotaExhausted as e:
            e.video, e.progress = vid, f"{idx}/{len(bounds)}"
            raise

        segments.sort(key=lambda s: s["start"])

        # Filter pure silence hallucinations at start and end
        while segments and is_hallucination_segment(segments[0]) and (
            "possible_hallucination" in segments[0].get("flags", [])
            or (segments[0].get("no_speech_prob") or 0) > 0.4
            or (segments[0].get("avg_logprob") or 0) < -0.8
        ):
            segments.pop(0)

        while segments and is_hallucination_segment(segments[-1]) and (
            "possible_hallucination" in segments[-1].get("flags", [])
            or (segments[-1].get("no_speech_prob") or 0) > 0.4
            or (segments[-1].get("avg_logprob") or 0) < -0.8
        ):
            segments.pop()

        # Apply deterministic phonetic normalization for bilingual code-switching
        phonetic_corrections_count = 0
        for s in segments:
            orig_text = s.get("text", "")
            norm_text = normalize_code_switch_text(
                orig_text,
                active_presets=active_presets,
                lexicon_cfg=lexicon_cfg,
            )
            if norm_text != orig_text:
                phonetic_corrections_count += 1
                s["text"] = norm_text

        for w in words:
            orig_word = w.get("word", "")
            norm_word = normalize_code_switch_text(
                orig_word,
                active_presets=active_presets,
                lexicon_cfg=lexicon_cfg,
            )
            if norm_word != orig_word:
                w["word"] = norm_word

        flagged = [s for s in segments if s.get("flags")]
        preset_summary = ", ".join(active_presets) if active_presets else "neutral"

        # Build verbatim Markdown
        a = audio_meta
        lines = [
            f"# {title}",
            "",
            f"- **Channel / Speaker:** {channel}",
            f"- **URL:** https://www.youtube.com/watch?v={vid}",
            f"- **Duration:** {fmt_ts(duration)} ({duration}s)",
            f"- **Transcription Engine:** Groq {MODEL} (verbatim, temperature 0, language: {lang or 'auto'})",
            f"- **Bilingual Code-Switching:** {'Enabled' if lang == 'id' else 'Off'} (presets: {preset_summary}, glossary terms: {len(terms)}, phonetic corrections: {phonetic_corrections_count})",
            f"- **Audio Source:** format {a['format_id']} | {a['codec']} {a['bitrate_kbps']} kbps {a['sample_rate']} Hz | {a['format_note'] or '-'}"
            + (" | DEGRADED FALLBACK" if a["degraded_fallback"] else ""),
            f"- **Preprocessing:** Lossless FLAC 16 kHz mono (clarity filter & SoX resampler), {len(bounds)} silence-aligned chunk(s)",
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

        with open(out_file, "w", encoding="utf-8") as md_fh:
            md_fh.write("\n".join(lines) + "\n")

        # Build raw metadata JSON
        with open(raw_file, "w", encoding="utf-8") as raw_fh:
            json.dump(
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
                        "preprocess": "flac_16k_mono_soxr_clarity",
                        "resumed_chunks": resumed,
                        "code_switch": {
                            "resolved_language": lang,
                            "active_presets": active_presets,
                            "glossary_terms_count": len(terms),
                            "phonetic_corrections_count": phonetic_corrections_count,
                            "terms": terms,
                        },
                        "chunks": [
                            {"start": round(s, 3), "end": round(e, 3), "cut": h}
                            for s, e, h in bounds
                        ],
                    },
                    "segments": segments,
                    "words": words,
                },
                raw_fh,
                indent=2,
                ensure_ascii=False,
            )

        # Clean up checkpoint folder and stale scratch cache upon full success
        shutil.rmtree(_ckpt_dir(vid), ignore_errors=True)
        prune_scratch_cache()

        elapsed = round(time.time() - t0, 1)
        word_count = sum(len(s["text"].split()) for s in segments)

        return {
            "status": "success",
            "video_id": vid,
            "title": title,
            "channel": channel,
            "duration": fmt_ts(duration),
            "language": lang,
            "total_segments": len(segments),
            "total_words": word_count,
            "low_confidence_segments": len(flagged),
            "active_presets": active_presets,
            "glossary_terms_count": len(terms),
            "phonetic_corrections_count": phonetic_corrections_count,
            "transcript_path": str(out_file.resolve()),
            "raw_json_path": str(raw_file.resolve()),
            "elapsed_seconds": elapsed,
        }
    finally:
        lock_path.unlink(missing_ok=True)
