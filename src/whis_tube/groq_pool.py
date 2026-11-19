"""Groq API Key Pool & multi-key rate-limit rotation logic."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import pathlib
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import dotenv_values

from .code_switch import is_hallucination_segment
from .config import (
    DEFAULT_KEYS_PATH,
    GROQ_API_KEY_ENV,
    GROQ_URL,
    KEY_STATE_PATH,
    KEYS_PATH,
    LOCAL_KEYS_PATHS,
    MODEL,
    QUOTA_MAX_WAIT_S,
    REPO_ROOT,
)

logger = logging.getLogger("whis-tube.groq")
_DURATION_UNITS = {"ms": 0.001, "h": 3600.0, "m": 60.0, "s": 1.0}
_PLACEHOLDER_TOKENS = ("PASTE", "YOUR", "EXAMPLE", "PLACEHOLDER", "HERE", "XXXX", "REDACT", "<", ">")


def is_valid_groq_key(key: Any) -> bool:
    """Return True if key looks like a real Groq key rather than a placeholder template."""
    if not isinstance(key, str):
        return False
    cleaned = key.strip()
    if not cleaned.startswith("gsk_") or len(cleaned) < 30:
        return False
    upper = cleaned.upper()
    return not any(tok in upper for tok in _PLACEHOLDER_TOKENS)


def _extract_keys_from_json(path: pathlib.Path) -> List[str]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            raw_list = data.get("keys", [])
        elif isinstance(data, list):
            raw_list = data
        else:
            raw_list = []

        found: List[str] = []
        for entry in raw_list:
            if isinstance(entry, str):
                candidate = entry.strip()
            elif isinstance(entry, dict):
                candidate = str(entry.get("key") or entry.get("api_key") or "").strip()
            else:
                candidate = ""
            if is_valid_groq_key(candidate):
                found.append(candidate)
        return found
    except Exception as e:
        logger.warning(f"Failed to read keys from {path}: {e}")
        return []


def load_groq_keys_with_sources() -> Tuple[List[str], List[str]]:
    """Hot-load valid Groq API keys across local repo keys.json, workspace, .env, and ~/.config/groq/keys.json."""
    keys: List[str] = []
    sources: List[str] = []

    def _add_key(candidate: str) -> bool:
        if is_valid_groq_key(candidate) and candidate not in keys:
            keys.append(candidate)
            return True
        return False

    # 1. Gather JSON key files in priority order (repo-local first for zero-friction portability)
    candidate_files: List[Tuple[pathlib.Path, str]] = [
        (LOCAL_KEYS_PATHS[0], f"{LOCAL_KEYS_PATHS[0].name} (project)"),
        (LOCAL_KEYS_PATHS[1], f"{LOCAL_KEYS_PATHS[1].name} (project)"),
        (pathlib.Path.cwd() / "keys.json", "keys.json (workspace)"),
    ]

    env_dotenv_files = [REPO_ROOT / ".env", pathlib.Path.cwd() / ".env"]
    dotenv_maps = []
    for env_path in env_dotenv_files:
        if env_path.is_file():
            try:
                dotenv_maps.append(dotenv_values(env_path))
            except Exception:
                pass

    env_keys_path = os.environ.get("GROQ_KEYS_PATH", "").strip()
    if not env_keys_path:
        for dmap in dotenv_maps:
            val = (dmap.get("GROQ_KEYS_PATH") or "").strip()
            if val:
                env_keys_path = val
                break

    if env_keys_path:
        candidate_files.append((pathlib.Path(env_keys_path).expanduser(), "GROQ_KEYS_PATH"))
    candidate_files.append((KEYS_PATH, str(KEYS_PATH)))
    candidate_files.append((DEFAULT_KEYS_PATH, "~/.config/groq/keys.json"))

    seen_paths: set[pathlib.Path] = set()
    for path, label in candidate_files:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)

        if path.is_file() and os.name != "nt" and (path.parent == REPO_ROOT or path.parent == pathlib.Path.cwd()):
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

        extracted = _extract_keys_from_json(path)
        added_count = sum(1 for k in extracted if _add_key(k))
        if added_count:
            sources.append(f"{label} ({added_count})")

    # 2. Check environment / .env GROQ_API_KEY values (comma-separated supported)
    env_candidates = [os.environ.get("GROQ_API_KEY", "").strip(), GROQ_API_KEY_ENV]
    for dmap in dotenv_maps:
        env_candidates.append(str(dmap.get("GROQ_API_KEY") or "").strip())

    env_added = 0
    for raw_env in env_candidates:
        if not raw_env:
            continue
        for part in raw_env.split(","):
            if _add_key(part.strip()):
                env_added += 1
    if env_added:
        sources.append(f"GROQ_API_KEY (.env/env) ({env_added})")

    return keys, sources


def load_groq_keys() -> List[str]:
    """Load API keys from local keys.json, environment variables, or ~/.config/groq/keys.json."""
    keys, _ = load_groq_keys_with_sources()
    return keys


def redact(text: str) -> str:
    """Redact sensitive organization and key patterns from error logs."""
    if not text:
        return ""
    text = re.sub(r"org_[A-Za-z0-9]+", "org_<redacted>", text)
    text = re.sub(r"gsk_[A-Za-z0-9_-]+", "gsk_<redacted>", text)
    return text


def _scan_number(text: str, pos: int) -> Tuple[Optional[float], int]:
    """Scan an unsigned integer or decimal literal starting at ``pos``."""
    n = len(text)
    start = pos
    while pos < n and text[pos].isdigit():
        pos += 1
    if pos == start:
        return None, start
    if pos < n and text[pos] == ".":
        frac_pos = pos + 1
        while frac_pos < n and text[frac_pos].isdigit():
            frac_pos += 1
        if frac_pos > pos + 1:
            pos = frac_pos
    return float(text[start:pos]), pos


def _parse_try_again_duration(body: str) -> Optional[float]:
    """Parse ``try again in <duration>`` in O(N) time without regex backtracking."""
    if not body:
        return None
    lower = body.lower()
    marker = "try again in "
    n = len(lower)
    search_from = 0
    while True:
        idx = lower.find(marker, search_from)
        if idx < 0:
            return None
        pos = idx + len(marker)
        total = 0.0
        matched = False
        while pos < n:
            num, next_pos = _scan_number(lower, pos)
            if num is None:
                break
            unit = None
            for suffix in ("ms", "h", "m", "s"):
                if lower.startswith(suffix, next_pos):
                    unit = suffix
                    pos = next_pos + len(suffix)
                    break
            if unit is None:
                break
            total += num * _DURATION_UNITS[unit]
            matched = True
        if matched:
            return total
        search_from = idx + len(marker)


def parse_wait_s(headers: Dict[str, str], body: str) -> Optional[float]:
    """Parse remaining cooldown seconds from retry-after header or Groq response text."""
    ra = headers.get("retry-after") or headers.get("Retry-After")
    if ra:
        try:
            return float(ra)
        except ValueError:
            pass
    return _parse_try_again_duration(body or "")


def limit_kind(body: str) -> str:
    """Identify which rate limit wall was hit (ASD, ASH, RPD, RPM, TPM, TPD)."""
    m = re.search(r"\((ASD|ASH|RPD|RPM|TPM|TPD)\)", body or "")
    return m.group(1) if m else "unknown"


class QuotaExhausted(RuntimeError):
    def __init__(self, reset_at: float, limit: str):
        self.reset_at = reset_at
        self.limit = limit
        self.video = "?"
        self.progress = "?"
        iso_str = datetime.datetime.fromtimestamp(reset_at).strftime("%Y-%m-%d %H:%M:%S")
        super().__init__(f"All Groq keys rate-limited ({limit}); earliest retry at {iso_str}")


class KeyPool:
    def __init__(
        self,
        keys: List[str],
        state_path: Optional[pathlib.Path] = None,
        max_wait: Optional[float] = None,
    ):
        if not keys:
            raise ValueError(
                f"No valid Groq API keys found. Paste your key(s) into {REPO_ROOT / 'keys.json'} "
                f"or {DEFAULT_KEYS_PATH}."
            )
        self._lock = threading.RLock()
        self.keys = keys
        self.ids = [hashlib.sha256(k.encode()).hexdigest()[:12] for k in keys]
        self.dead: set[int] = set()
        self.cool: Dict[int, Tuple[float, str]] = {}  # key index -> (retry_at_epoch, limit_kind)
        self.state_path = state_path or KEY_STATE_PATH
        self.max_wait = QUOTA_MAX_WAIT_S if max_wait is None else max_wait
        self.i = random.randrange(len(keys))
        self._load()

    def _read_state(self) -> Dict[str, Any]:
        try:
            if self.state_path.exists():
                return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {}

    def _load(self) -> None:
        with self._lock:
            st, now = self._read_state(), time.time()
            for idx, kid in enumerate(self.ids):
                e = st.get(kid) or {}
                if e.get("until", 0) > now:
                    self.cool[idx] = (e["until"], e.get("limit", "unknown"))

    def _save(self) -> None:
        with self._lock:
            now = time.time()
            st = {k: v for k, v in self._read_state().items() if v.get("until", 0) > now}
            for idx, (until, kind) in self.cool.items():
                kid = self.ids[idx]
                if until > st.get(kid, {}).get("until", 0):
                    st[kid] = {
                        "until": until,
                        "limit": kind,
                        "until_iso": datetime.datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M:%S"),
                    }
            try:
                tmp = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
                tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
                os.replace(tmp, self.state_path)
            except OSError as err:
                logger.debug(f"Failed to save key state: {err}")

    def live(self) -> int:
        with self._lock:
            return len([i for i in range(len(self.keys)) if i not in self.dead])

    def cooldown(self, idx: int, wait_s: float, kind: str) -> None:
        with self._lock:
            self.cool[idx] = (time.time() + wait_s, kind)
            self._save()

    def next(self) -> Tuple[int, str]:
        while True:
            with self._lock:
                if self.live() == 0:
                    raise RuntimeError("No valid Groq keys left in pool (all returned HTTP 401/403)")
                now = time.time()
                for _ in range(len(self.keys)):
                    self.i = (self.i + 1) % len(self.keys)
                    if self.i in self.dead:
                        continue
                    if self.cool.get(self.i, (0.0, ""))[0] <= now:
                        self.cool.pop(self.i, None)
                        return self.i, self.keys[self.i]

                candidates = [v for i, v in self.cool.items() if i not in self.dead]
                if not candidates:
                    for idx in range(len(self.keys)):
                        if idx not in self.dead:
                            self.i = idx
                            self.cool.pop(idx, None)
                            return self.i, self.keys[self.i]
                    raise RuntimeError("No valid Groq keys left in pool (all returned HTTP 401/403)")

                reset_at, kind = min(candidates)
                wait = reset_at - now
                if wait > self.max_wait:
                    raise QuotaExhausted(reset_at, kind)

            logger.info(f"All {self.live()} live keys cooling ({kind}); waiting {wait:.1f}s...")
            time.sleep(max(wait, 0) + 0.5)


def groq_call(
    pool: KeyPool,
    chunk: pathlib.Path,
    lang: Optional[str],
    prompt: str,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    """Execute Whisper API call with automatic multi-key failover and backoff."""
    transient = 0
    backoff = 10
    while True:
        ki, key = pool.next()
        data = [
            ("model", MODEL),
            ("response_format", "verbose_json"),
            ("temperature", str(temperature)),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if lang:
            data.append(("language", lang))
        if prompt:
            data.append(("prompt", prompt))

        r = None
        err = ""
        try:
            with open(chunk, "rb") as fh:
                r = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (chunk.name, fh, "audio/flac")},
                    data=data,
                    timeout=300,
                )
        except requests.RequestException as e:
            err = f"network error: {type(e).__name__}"

        if r is not None:
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception as e:
                    err = f"invalid JSON from Groq (HTTP 200): {e}"
                    logger.warning(f"Key#{ki} returned HTTP 200 with invalid JSON: {r.text[:200]}")
            else:
                body = redact(r.text)
                logger.warning(f"Key#{ki} HTTP {r.status_code}: {body[:400]}")

                if r.status_code in (401, 403):
                    pool.dead.add(ki)
                    pool.cool.pop(ki, None)
                    logger.error(f"Key#{ki} rejected (invalid/unauthorized); removed from pool ({pool.live()} left)")
                    continue

                if r.status_code == 429:
                    headers = {k.lower(): v for k, v in r.headers.items()}
                    wait = parse_wait_s(headers, body) or 60.0
                    kind = limit_kind(body)
                    pool.cooldown(ki, wait, kind)
                    logger.info(f"Key#{ki} cooling {kind} for {wait:.0f}s")
                    continue

                if r.status_code in (400, 413, 422):
                    raise RuntimeError(f"Groq rejected audio request (HTTP {r.status_code}): {body[:300]}")

                err = f"HTTP {r.status_code}"

        transient += 1
        if transient >= 6:
            raise RuntimeError(f"Transcription failed for {chunk.name}: {err} after {transient} attempts")
        logger.info(f"Key#{ki} {err}; retrying in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def flag_segment(seg: Dict[str, Any]) -> List[str]:
    """Evaluate quality and flag potential hallucinations or repetitions."""
    flags = []
    if (seg.get("compression_ratio") or 0) > 2.4:
        flags.append("repetition")
    if (seg.get("avg_logprob") or 0) < -0.8:
        flags.append("low_confidence")
    if ((seg.get("no_speech_prob") or 0) > 0.6 and (seg.get("avg_logprob") or 0) < -0.5) or is_hallucination_segment(seg):
        flags.append("possible_hallucination")
    return flags


def transcribe_chunk(
    pool: KeyPool,
    chunk: pathlib.Path,
    offset: float,
    lang: Optional[str],
    prompt: str,
    base_prompt: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Transcribe a single audio chunk with timestamp offset adjustment and repetition retry."""
    def extract_words(res: Dict[str, Any]) -> List[Dict[str, Any]]:
        words_list = []
        for w in (res.get("words") or []):
            if not isinstance(w, dict) or not w.get("word"):
                continue
            w_start = w.get("start")
            w_end = w.get("end")
            start_num = float(w_start) if w_start is not None else 0.0
            end_num = float(w_end) if w_end is not None else start_num
            words_list.append({
                "word": w.get("word"),
                "start": round(start_num + offset, 2),
                "end": round(end_num + offset, 2),
            })
        return words_list

    def parse_segments(res: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = []
        for s in (res.get("segments") or []):
            if not isinstance(s, dict):
                continue
            text = (s.get("text") or "").strip()
            if not text:
                continue
            s_start = s.get("start")
            s_end = s.get("end")
            start_num = float(s_start) if s_start is not None else 0.0
            end_num = float(s_end) if s_end is not None else start_num
            seg = {
                "start": round(start_num + offset, 3),
                "end": round(end_num + offset, 3),
                "text": text,
                "avg_logprob": s.get("avg_logprob"),
                "no_speech_prob": s.get("no_speech_prob"),
                "compression_ratio": s.get("compression_ratio"),
            }
            seg["flags"] = flag_segment(seg)
            out.append(seg)
        return out

    res = groq_call(pool, chunk, lang, prompt, temperature=0.0)
    segs = parse_segments(res)
    words = extract_words(res)

    repetition_count = sum("repetition" in s["flags"] for s in segs)
    if segs and (repetition_count / len(segs) > 0.1):
        logger.info(f"{repetition_count} repetition segments found; retrying at temp=0.2...")
        try:
            retry_prompt = base_prompt if base_prompt else ""
            res_retry = groq_call(pool, chunk, lang, prompt=retry_prompt, temperature=0.2)
            alt_segs = parse_segments(res_retry)
            if sum("repetition" in s["flags"] for s in alt_segs) < repetition_count:
                segs = alt_segs
                words = extract_words(res_retry)
        except Exception as exc:
            logger.warning(f"Retry at temp=0.2 failed ({exc}); keeping first pass output.")

    return segs, words
