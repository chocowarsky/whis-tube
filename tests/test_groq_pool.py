"""Unit tests for Groq API Key Pool & multi-key rotation logic."""

import json
import pathlib
import time
from unittest.mock import MagicMock, patch
import pytest

from whis_tube.groq_pool import (
    KeyPool,
    QuotaExhausted,
    flag_segment,
    limit_kind,
    load_groq_keys,
    parse_wait_s,
    redact,
)


def test_redact():
    assert redact("Failed org_12345abcdef in account") == "Failed org_<redacted> in account"
    assert redact("Authorization: Bearer gsk_abc123XYZ_SECRET_456") == "Authorization: Bearer gsk_<redacted>"
    assert redact("") == ""
    assert redact(None) == ""


def test_parse_wait_s():
    # Header numeric
    assert parse_wait_s({"retry-after": "15"}, "") == 15.0
    assert parse_wait_s({"Retry-After": "30.5"}, "") == 30.5
    assert parse_wait_s({"retry-after": "invalid"}, "") is None

    # Body string format
    assert parse_wait_s({}, "Rate limit reached. Please try again in 5s.") == 5.0
    assert parse_wait_s({}, "try again in 2m30s") == 150.0
    assert parse_wait_s({}, "try again in 1h10m5s") == 3600.0 + 600.0 + 5.0
    assert parse_wait_s({}, "try again in 500ms") == 0.5
    assert parse_wait_s({}, "no retry info") is None


def test_limit_kind():
    assert limit_kind("Rate limit hit (RPM)") == "RPM"
    assert limit_kind("Rate limit hit (RPD)") == "RPD"
    assert limit_kind("Rate limit hit (TPM)") == "TPM"
    assert limit_kind("Rate limit hit (TPD)") == "TPD"
    assert limit_kind("Rate limit hit (ASD)") == "ASD"
    assert limit_kind("Rate limit hit (ASH)") == "ASH"
    assert limit_kind("Unknown error format") == "unknown"


def test_load_groq_keys(tmp_path):
    # From environment
    with patch("whis_tube.groq_pool.GROQ_API_KEY_ENV", "key1, key2 ,key3"):
        with patch("whis_tube.groq_pool.KEYS_PATH", tmp_path / "nonexistent.json"):
            keys = load_groq_keys()
            assert keys == ["key1", "key2", "key3"]

    # From JSON file (dict format)
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps({"keys": ["file_key_1", "file_key_2"]}), encoding="utf-8")
    with patch("whis_tube.groq_pool.GROQ_API_KEY_ENV", ""):
        with patch("whis_tube.groq_pool.KEYS_PATH", keys_file):
            keys = load_groq_keys()
            assert keys == ["file_key_1", "file_key_2"]

    # From JSON file (list format)
    keys_file.write_text(json.dumps(["list_key_1", "list_key_2"]), encoding="utf-8")
    with patch("whis_tube.groq_pool.GROQ_API_KEY_ENV", ""):
        with patch("whis_tube.groq_pool.KEYS_PATH", keys_file):
            keys = load_groq_keys()
            assert keys == ["list_key_1", "list_key_2"]


def test_key_pool_init_empty():
    with pytest.raises(ValueError, match="No Groq API keys provided"):
        KeyPool([])


def test_key_pool_rotation(tmp_path):
    keys = ["gsk_key_1", "gsk_key_2", "gsk_key_3"]
    pool = KeyPool(keys, state_path=tmp_path / "state.json")
    assert pool.live() == 3

    # Consecutive next calls rotate through available keys
    obtained = set()
    for _ in range(3):
        idx, k = pool.next()
        obtained.add(k)
    assert len(obtained) == 3


def test_key_pool_min_empty_sequence_bug_fix(tmp_path):
    """Regression test: Prevent 'ValueError: min() arg is an empty sequence'
    when live keys exist but cooldown dictionary is empty or only dead keys exist.
    """
    keys = ["gsk_key_live", "gsk_key_dead"]
    pool = KeyPool(keys, state_path=tmp_path / "state.json")

    # Mark key 1 as dead
    pool.dead.add(1)
    # Populate cool with ONLY the dead key (so live keys have no cool entries)
    pool.cool[1] = (time.time() + 100.0, "RPM")

    # This previously triggered min(v for i, v in self.cool.items() if i not in self.dead)
    # on an empty sequence, raising ValueError: min() arg is an empty sequence.
    idx, key = pool.next()
    assert idx == 0
    assert key == "gsk_key_live"
    assert pool.live() == 1


def test_key_pool_cooldown_and_ready(tmp_path):
    keys = ["gsk_k1", "gsk_k2"]
    pool = KeyPool(keys, state_path=tmp_path / "state.json")

    # Put key 0 in cooldown for 0.1s
    pool.cooldown(0, 0.1, "RPM")
    assert 0 in pool.cool

    # Next call should return key 1
    idx, k = pool.next()
    assert idx == 1
    assert k == "gsk_k2"

    # Wait for cooldown to expire
    time.sleep(0.15)
    idx, k = pool.next()
    # Key 0 should now be uncooled and ready
    assert idx == 0
    assert k == "gsk_k1"


def test_key_pool_all_dead(tmp_path):
    keys = ["gsk_dead_1", "gsk_dead_2"]
    pool = KeyPool(keys, state_path=tmp_path / "state.json")
    pool.dead.add(0)
    pool.dead.add(1)

    with pytest.raises(RuntimeError, match="No valid Groq keys left in pool"):
        pool.next()


def test_key_pool_quota_exhausted(tmp_path):
    keys = ["gsk_cooling_key"]
    pool = KeyPool(keys, state_path=tmp_path / "state.json", max_wait=5.0)
    # Put key into cooldown for 100 seconds (which exceeds max_wait=5.0)
    pool.cooldown(0, 100.0, "RPD")

    with pytest.raises(QuotaExhausted) as exc_info:
        pool.next()
    assert "RPD" in str(exc_info.value)


def test_flag_segment():
    # Normal segment
    seg_normal = {"compression_ratio": 1.2, "avg_logprob": -0.4, "no_speech_prob": 0.1}
    assert flag_segment(seg_normal) == []

    # Repetition
    seg_rep = {"compression_ratio": 2.5, "avg_logprob": -0.4, "no_speech_prob": 0.1}
    assert "repetition" in flag_segment(seg_rep)

    # Low confidence
    seg_low = {"compression_ratio": 1.2, "avg_logprob": -1.2, "no_speech_prob": 0.1}
    assert "low_confidence" in flag_segment(seg_low)

    # Possible hallucination
    seg_hal = {"compression_ratio": 1.2, "avg_logprob": -0.8, "no_speech_prob": 0.8}
    assert "possible_hallucination" in flag_segment(seg_hal)
