"""Unit tests for audio processing, silence detection, and chunk planning."""

import json
import pathlib
from unittest.mock import MagicMock, patch
import pytest

from whis_tube.audio import (
    load_or_make_plan,
    parse_silence_events,
    pick_audio_format,
    plan_cuts,
)


def test_parse_silence_events_normal():
    stderr = """
[silencedetect @ 0x55] silence_start: 12.500
[silencedetect @ 0x55] silence_end: 15.200 | silence_duration: 2.700
[silencedetect @ 0x55] silence_start: 100.000
[silencedetect @ 0x55] silence_end: 102.500 | silence_duration: 2.500
"""
    events = parse_silence_events(stderr, duration=200.0)
    assert events == [(12.5, 15.2), (100.0, 102.5)]


def test_parse_silence_events_starts_with_silence():
    # When file starts with silence, ffmpeg logs silence_end without preceding silence_start
    stderr = """
[silencedetect @ 0x55] silence_end: 3.500 | silence_duration: 3.500
[silencedetect @ 0x55] silence_start: 45.000
[silencedetect @ 0x55] silence_end: 48.000 | silence_duration: 3.000
"""
    events = parse_silence_events(stderr, duration=100.0)
    # The first event must start at 0.0, not be discarded or mispaired!
    assert events == [(0.0, 3.5), (45.0, 48.0)]


def test_parse_silence_events_ends_with_silence():
    # When file ends with silence, ffmpeg logs silence_start without silence_end at EOF
    stderr = """
[silencedetect @ 0x55] silence_start: 10.000
[silencedetect @ 0x55] silence_end: 12.000
[silencedetect @ 0x55] silence_start: 590.000
"""
    events = parse_silence_events(stderr, duration=600.0)
    assert events == [(10.0, 12.0), (590.0, 600.0)]


def test_plan_cuts_short_audio():
    # Audio under target chunk + fwd window (e.g. 500s) should yield exactly 1 chunk
    bounds = plan_cuts(500.0, {})
    assert len(bounds) == 1
    assert bounds[0] == (0.0, 500.0, "end")


def test_plan_cuts_long_audio_with_pauses():
    # 1500s video (~25 mins), pause at 605s (between 510s and 630s window)
    silences = {
        -30: [(604.0, 606.0)],
    }
    bounds = plan_cuts(1500.0, silences)
    assert len(bounds) >= 2
    # First cut should be around 605s
    first_cut = bounds[0]
    assert first_cut[0] == 0.0
    assert abs(first_cut[1] - 605.0) < 0.1
    assert "pause" in first_cut[2]
    assert "-30 dB" in first_cut[2]


def test_plan_cuts_no_pauses_hard_cut():
    # Long video with no detected silences -> hard cuts at TARGET_CHUNK_S (600s)
    bounds = plan_cuts(1500.0, {})
    assert len(bounds) == 3
    assert bounds[0][1] == 600.0
    assert bounds[0][2] == "hard-cut (no pause found)"
    assert bounds[1][0] == 600.0
    assert bounds[1][1] == 1200.0
    assert bounds[2][1] == 1500.0
    assert bounds[2][2] == "end"


def test_plan_cuts_invalid_duration():
    with pytest.raises(ValueError, match="Audio duration must be greater than 0"):
        plan_cuts(0.0, {})
    with pytest.raises(ValueError, match="Audio duration must be greater than 0"):
        plan_cuts(-10.0, {})


def test_pick_audio_format():
    info = {
        "formats": [
            {
                "format_id": "140",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "format_note": "medium",
            },
            {
                "format_id": "251",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 128,
                "format_note": "medium",
            },
            {
                "format_id": "251-drc",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "format_note": "DRC audio",
            },
            {
                "format_id": "dubbed-spanish",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "format_note": "dubbed (es)",
            },
        ]
    }
    chosen = pick_audio_format(info)
    # Opus format 251 should win over AAC 140 (15% Opus weighting), and DRC/dubbed should be excluded
    assert chosen is not None
    assert chosen["format_id"] == "251"


def test_pick_audio_format_empty():
    assert pick_audio_format({}) is None
    assert pick_audio_format({"formats": []}) is None
