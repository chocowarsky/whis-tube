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
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import (
    GROQ_API_KEY_ENV,
    GROQ_URL,
    KEY_STATE_PATH,
    KEYS_PATH,
    MODEL,
    QUOTA_MAX_WAIT_S,
)

logger = logging.getLogger("whis-tube.groq")
_TRY_AGAIN_RE = re.compile(r"try again in ((?:\d+(?:\.\d+)?(?:h|ms|m|s))+)", re.I)


def load_groq_keys() -> List[str]:
    """Load API keys from environment variable or JSON config file."""
    keys: List[str] = []
    if GROQ_API_KEY_ENV:
        # Support comma-separated keys in GROQ_API_KEY
        keys.extend([k.strip() for k in GROQ_API_KEY_ENV.split(",") if k.strip()])

    if KEYS_PATH.exists():
        try:
            data = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                file_keys = data.get("keys", [])
            elif isinstance(data, list):
                file_keys = data
            else:
                file_keys = []
            for k in file_keys:
                if isinstance(k, str) and k.strip() and k.strip() not in keys:
                    keys.append(k.strip())
        except Exception as e:
            logger.warning(f"Failed to read keys from {KEYS_PATH}: {e}")

    return keys


def redact(text: str) -> str:
    """Redact sensitive organization and key patterns from error logs."""
    return re.sub(r"org_[A-Za-z0-9]+", "org_<redacted>", text or "")


def parse_wait_s(headers: Dict[str, str], body: str) -> Optional[float]:
    """Parse remaining cooldown seconds from retry-after header or Groq response text."""
    ra = headers.get("retry-after")
    if ra:
        try:
            return float(ra)
        except ValueError:
            pass
    m = _TRY_AGAIN_RE.search(body or "")
    if not m:
        return None
    units = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    return sum(float(n) * units[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", m.group(1)))


def limit_kind(body: str) -> str:
    """Identify which rate limit wall was hit (ASD, ASH, RPD, RPM)."""
    m = re.search(r"\((ASD|ASH|RPD|RPM)\)", body or "")
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
            raise ValueError(f"No Groq API keys provided or found in {KEYS_PATH}")
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
        st, now = self._read_state(), time.time()
        for idx, kid in enumerate(self.ids):
            e = st.get(kid) or {}
            if e.get("until", 0) > now:
                self.cool[idx] = (e["until"], e.get("limit", "unknown"))

    def _save(self) -> None:
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
            tmp = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as err:
            logger.debug(f"Failed to save key state: {err}")

    def live(self) -> int:
        return len(self.keys) - len(self.dead)

    def cooldown(self, idx: int, wait_s: float, kind: str) -> None:
        self.cool[idx] = (time.time() + wait_s, kind)
        self._save()

    def next(self) -> Tuple[int, str]:
        while True:
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

            reset_at, kind = min(v for i, v in self.cool.items() if i not in self.dead)
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
                return r.json()
            body = redact(r.text)
            logger.warning(f"Key#{ki} HTTP {r.status_code}: {body[:400]}")

            if r.status_code in (401, 403):
                pool.dead.add(ki)
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
    if (seg.get("avg_logprob") or 0) < -1.0:
        flags.append("low_confidence")
    if (seg.get("no_speech_prob") or 0) > 0.6 and (seg.get("avg_logprob") or 0) < -0.5:
        flags.append("possible_hallucination")
    return flags


def transcribe_chunk(
    pool: KeyPool,
    chunk: pathlib.Path,
    offset: float,
    lang: Optional[str],
    prompt: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Transcribe a single audio chunk with timestamp offset adjustment and repetition retry."""
    def extract_words(res: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "word": w.get("word"),
                "start": round(w["start"] + offset, 2),
                "end": round(w["end"] + offset, 2),
            }
            for w in (res.get("words") or [])
            if w.get("word")
        ]

    def parse_segments(res: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = []
        for s in res.get("segments", []):
            text = (s.get("text") or "").strip()
            if not text:
                continue
            seg = {
                "start": round(s["start"] + offset, 3),
                "end": round(s["end"] + offset, 3),
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
            res_retry = groq_call(pool, chunk, lang, prompt="", temperature=0.2)
            alt_segs = parse_segments(res_retry)
            if sum("repetition" in s["flags"] for s in alt_segs) < repetition_count:
                segs = alt_segs
                words = extract_words(res_retry)
        except QuotaExhausted:
            logger.warning("Quota exhausted during retry; keeping first pass output.")

    return segs, words
