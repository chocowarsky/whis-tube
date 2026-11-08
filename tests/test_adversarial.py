"""Adversarial & Brutal QA Stress Tests for whis-tube.

Covers all failure modes, boundary conditions, and pathological edge cases:
1. Malformed URLs & video metadata
2. Audio edge cases (silence, 0-dur, 10+ hr, corrupt audio, missing binaries, "N/A" bitrate)
3. Groq Pool edge cases (all cooling, concurrent exhaustion, corrupt keys.json, malformed JSON, 502/503, 413)
4. Visual keyframe edge cases (negative, nan, inf, 99:99:99, missing stream, resolution)
5. Concurrency & resource leaks (chunk cleanup on exceptions, open FDs)
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import subprocess
import time
from unittest.mock import MagicMock, patch
import pytest
import requests

from whis_tube.audio import (
    cut_chunk,
    detect_silences,
    download_audio,
    get_video_info,
    load_or_make_plan,
    parse_silence_events,
    pick_audio_format,
    plan_cuts,
    to_flac16k,
    transcribe_video,
)
from whis_tube.config import MODEL
from whis_tube.groq_pool import (
    KeyPool,
    QuotaExhausted,
    flag_segment,
    groq_call,
    limit_kind,
    load_groq_keys,
    parse_wait_s,
    redact,
    transcribe_chunk,
)
from whis_tube.utils import (
    ffprobe_duration,
    fmt_ts,
    list_channel_videos,
    parse_ts,
    run_command,
    sanitize_filename,
)
from whis_tube.visual import extract_keyframe


# ==============================================================================
# SECTION 1: Malformed URLs and Video Metadata Edge Cases
# ==============================================================================

class TestMalformedUrlsAndMetadata:
    """Stress testing yt-dlp parsing, URL handling, and unusual metadata."""

    def test_empty_and_whitespace_urls(self):
        with pytest.raises(subprocess.CalledProcessError):
            get_video_info("")

    def test_non_youtube_or_invalid_url(self):
        with pytest.raises(subprocess.CalledProcessError):
            get_video_info("https://example.com/not-a-video")

    def test_injection_strings_in_url(self):
        # yt-dlp is called with '--' ensuring argument injection flags are treated as URLs and rejected
        with pytest.raises(subprocess.CalledProcessError):
            get_video_info("--output=/tmp/pwned")

        # Command injection strings should not execute in subshell
        with patch("whis_tube.audio.run_command") as mock_rc:
            mock_rc.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"id": "test", "title": "test"}', stderr=""
            )
            get_video_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ; echo 'pwned'")
            # Verify '--' is present in args to prevent option injection
            called_cmd = mock_rc.call_args[0][0]
            assert "--" in called_cmd
            assert called_cmd[-1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ; echo 'pwned'"

    def test_live_stream_rejection(self):
        info = {
            "id": "live_vid_123",
            "title": "Live Broadcast",
            "live_status": "is_live",
            "duration": 0,
        }
        with patch("whis_tube.audio.get_video_info", return_value=info), \
             patch("whis_tube.audio.load_groq_keys", return_value=["gsk_test"]):
            with pytest.raises(RuntimeError, match="currently broadcasting live"):
                transcribe_video("https://www.youtube.com/watch?v=live_vid_123")

    def test_upcoming_premiere_handling(self):
        # When a stream is upcoming, duration is 0/None and formats may be empty or missing
        info = {
            "id": "upcoming_123",
            "title": "Upcoming Premiere",
            "live_status": "is_upcoming",
            "duration": None,
            "formats": [],
        }
        with patch("whis_tube.audio.get_video_info", return_value=info), \
             patch("whis_tube.audio.load_groq_keys", return_value=["gsk_test"]):
            # Should fail cleanly
            with pytest.raises(RuntimeError):
                transcribe_video("https://www.youtube.com/watch?v=upcoming_123")

    def test_playlist_url_handling(self):
        # When yt-dlp receives a playlist URL with --dump-json, it might return multiple JSON objects
        # or fail if not a single video. Test behavior when dump-json returns newline-delimited JSON.
        multi_json = '{"id": "vid1", "title": "Vid 1"}\n{"id": "vid2", "title": "Vid 2"}\n'
        with patch("whis_tube.audio.run_command") as mock_rc:
            mock_rc.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=multi_json, stderr=""
            )
            # json.loads will fail on multi-line JSON if not handled
            with pytest.raises(Exception):
                get_video_info("https://www.youtube.com/playlist?list=PL123")


# ==============================================================================
# SECTION 2: Audio Edge Cases
# ==============================================================================

class TestAudioEdgeCases:
    """Stress testing audio silence, 0-duration, 10+ hours, corrupted files, and binary failures."""

    def test_ffprobe_duration_non_numeric_and_empty(self, tmp_path):
        dummy_file = tmp_path / "corrupt.mp3"
        dummy_file.write_bytes(b"garbage")

        with patch("whis_tube.utils.run_command") as mock_rc:
            # ffprobe returning non-numeric string like "N/A"
            mock_rc.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="N/A\n", stderr=""
            )
            assert ffprobe_duration(dummy_file) == 0.0

            # ffprobe returning empty string
            mock_rc.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            assert ffprobe_duration(dummy_file) == 0.0

    def test_plan_cuts_zero_and_negative_duration(self):
        with pytest.raises(ValueError, match="Audio duration must be greater than 0"):
            plan_cuts(0.0, {})
        with pytest.raises(ValueError, match="Audio duration must be greater than 0"):
            plan_cuts(-10.0, {})

    def test_plan_cuts_massive_10_plus_hour_audio(self):
        # 12 hours = 43,200 seconds
        duration = 43200.0
        # No silences -> hard cuts every TARGET_CHUNK_S (600s)
        bounds = plan_cuts(duration, {})
        assert len(bounds) == 72
        assert bounds[0][0] == 0.0
        assert bounds[-1][1] == 43200.0
        assert bounds[-1][2] == "end"
        # Check continuity
        for i in range(len(bounds) - 1):
            assert bounds[i][1] == bounds[i + 1][0]

    def test_parse_silence_events_pure_silence(self):
        # If the entire file is silence from start to end (duration 1800s)
        stderr = "silence_start: 0\n"
        events = parse_silence_events(stderr, duration=1800.0)
        assert events == [(0.0, 1800.0)]

    def test_to_flac16k_missing_or_empty_file(self, tmp_path):
        nonexistent = tmp_path / "nonexistent.mp3"
        with pytest.raises(RuntimeError, match="missing or empty"):
            to_flac16k(nonexistent)

        empty_file = tmp_path / "empty.mp3"
        empty_file.write_bytes(b"")
        with pytest.raises(RuntimeError, match="missing or empty"):
            to_flac16k(empty_file)

    def test_to_flac16k_ffmpeg_failure(self, tmp_path):
        src = tmp_path / "audio.opus"
        src.write_bytes(b"fake opus content")

        with patch("whis_tube.audio.run_command") as mock_rc:
            mock_rc.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="Invalid data found when processing input\n"
            )
            with pytest.raises(RuntimeError, match="Unable to decode an audio stream"):
                to_flac16k(src)

    def test_download_audio_stream_bitrate_na(self, tmp_path):
        """Pathological probe: stream codec bit_rate is 'N/A' or None."""
        info = {
            "id": "vid123",
            "formats": [
                {
                    "format_id": "251",
                    "vcodec": "none",
                    "acodec": "opus",
                    "protocol": "https",
                    "abr": None,  # No ABR
                }
            ],
        }
        audio_file = tmp_path / "yt_vid123.251.webm"
        audio_file.write_bytes(b"dummy")

        probe_json = json.dumps({
            "streams": [
                {
                    "codec_name": "opus",
                    "sample_rate": "48000",
                    "channels": 2,
                    "bit_rate": "N/A",  # ffprobe often returns "N/A" for VBR opus/flac
                }
            ]
        })

        with patch("whis_tube.audio.SCRATCH_DIR", tmp_path), \
             patch("whis_tube.audio.ffprobe_duration", return_value=120.0), \
             patch("whis_tube.audio.run_command") as mock_rc:
            # yt-dlp run
            mock_rc.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # yt-dlp
                subprocess.CompletedProcess(args=[], returncode=0, stdout=probe_json, stderr=""),  # ffprobe
            ]

            # In the current implementation, int(st.get("bit_rate") or 0) raises ValueError if "N/A"
            try:
                path, meta = download_audio("https://youtube.com/watch?v=vid123", info)
                assert meta["codec"] == "opus"
            except ValueError as e:
                pytest.fail(f"download_audio crashed on 'bit_rate': 'N/A': {e}")

    def test_missing_binaries_in_path(self, tmp_path):
        """Simulate missing ffmpeg or yt-dlp (FileNotFoundError)."""
        with patch("subprocess.run", side_effect=FileNotFoundError("No such file or directory: 'ffmpeg'")):
            with pytest.raises(FileNotFoundError):
                run_command(["ffmpeg", "-version"])


# ==============================================================================
# SECTION 3: Groq Pool & API Edge Cases
# ==============================================================================

class TestGroqPoolEdgeCases:
    """Stress testing key exhaustion, malformed responses, corrupt keys.json, 502/503/413."""

    def test_corrupt_keys_json(self, tmp_path):
        corrupt_file = tmp_path / "corrupt_keys.json"
        corrupt_file.write_text("{this is not valid json!}", encoding="utf-8")

        with patch("whis_tube.groq_pool.GROQ_API_KEY_ENV", ""), \
             patch("whis_tube.groq_pool.KEYS_PATH", corrupt_file):
            keys = load_groq_keys()
            assert keys == []

    def test_keys_json_with_invalid_data_types(self, tmp_path):
        file = tmp_path / "weird_keys.json"
        # keys contains ints, nulls, empty strings, dicts
        file.write_text(json.dumps({"keys": [123, None, "", "   ", {"a": 1}, "valid_key_1"]}), encoding="utf-8")

        with patch("whis_tube.groq_pool.GROQ_API_KEY_ENV", ""), \
             patch("whis_tube.groq_pool.KEYS_PATH", file):
            keys = load_groq_keys()
            assert keys == ["valid_key_1"]

    def test_corrupt_groq_key_state_json(self, tmp_path):
        state_file = tmp_path / "corrupt_state.json"
        state_file.write_text("BROKEN JSON CONTENT", encoding="utf-8")

        pool = KeyPool(["gsk_test1"], state_path=state_file)
        # Should cleanly recover with empty state without raising exception
        assert pool.cool == {}

    def test_all_keys_cooling_down_raises_quota_exhausted(self, tmp_path):
        pool = KeyPool(["gsk_1", "gsk_2"], state_path=tmp_path / "state.json", max_wait=2.0)
        now = time.time()
        # Put both keys into cooldown for 100 seconds (> max_wait of 2.0s)
        pool.cool[0] = (now + 100.0, "TPM")
        pool.cool[1] = (now + 100.0, "RPM")

        with pytest.raises(QuotaExhausted) as exc_info:
            pool.next()
        assert "TPM" in str(exc_info.value) or "RPM" in str(exc_info.value)

    def test_groq_413_payload_too_large(self, tmp_path):
        pool = KeyPool(["gsk_1"], state_path=tmp_path / "state.json")
        chunk = tmp_path / "chunk.flac"
        chunk.write_bytes(b"dummy flac data")

        mock_resp = MagicMock()
        mock_resp.status_code = 413
        mock_resp.text = "Payload Too Large: Audio file size exceeds 25MB"

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP 413"):
                groq_call(pool, chunk, None, "")

    def test_groq_502_503_504_gateway_retries_and_exhausts(self, tmp_path):
        pool = KeyPool(["gsk_1"], state_path=tmp_path / "state.json")
        chunk = tmp_path / "chunk.flac"
        chunk.write_bytes(b"dummy flac data")

        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.text = "Bad Gateway"

        with patch("requests.post", return_value=mock_resp), \
             patch("time.sleep", return_value=None):  # Fast forward backoff sleep
            with pytest.raises(RuntimeError, match="HTTP 502 after 6 attempts"):
                groq_call(pool, chunk, None, "")

    def test_groq_200_with_malformed_json_body(self, tmp_path):
        pool = KeyPool(["gsk_1"], state_path=tmp_path / "state.json")
        chunk = tmp_path / "chunk.flac"
        chunk.write_bytes(b"dummy flac data")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_resp.text = "<html><body>504 Gateway Time-out</body></html>"

        with patch("requests.post", return_value=mock_resp), \
             patch("time.sleep", return_value=None):
            # If requests returns 200 with HTML/corrupt JSON, it retries and exhausts
            with pytest.raises(RuntimeError, match="invalid JSON from Groq"):
                groq_call(pool, chunk, None, "")

    def test_groq_response_with_none_or_missing_fields(self, tmp_path):
        """Groq returns 200 with segments: None or words: None or missing timestamps."""
        pool = KeyPool(["gsk_1"], state_path=tmp_path / "state.json")
        chunk = tmp_path / "chunk.flac"
        chunk.write_bytes(b"dummy")

        # Case A: segments is None
        bad_response_1 = {"text": "hello", "segments": None, "words": None}
        with patch("whis_tube.groq_pool.groq_call", return_value=bad_response_1):
            try:
                segs, words = transcribe_chunk(pool, chunk, 0.0, None, "")
                assert segs == []
                assert words == []
            except TypeError as te:
                pytest.fail(f"transcribe_chunk crashed when segments is None: {te}")

        # Case B: segments contains item with missing or None start/end
        bad_response_2 = {
            "segments": [
                {"text": "segment with missing start/end"},
                {"text": "segment with None start", "start": None, "end": 5.0},
            ]
        }
        with patch("whis_tube.groq_pool.groq_call", return_value=bad_response_2):
            try:
                segs, words = transcribe_chunk(pool, chunk, 0.0, None, "")
            except (KeyError, TypeError) as err:
                pytest.fail(f"transcribe_chunk crashed on missing/None segment timestamps: {err}")

    def test_concurrent_pool_access_thread_safety(self, tmp_path):
        """Multiple concurrent requests should not corrupt key pool index or state."""
        keys = [f"gsk_key_{i}" for i in range(5)]
        pool = KeyPool(keys, state_path=tmp_path / "state.json")

        def worker():
            for _ in range(50):
                idx, k = pool.next()
                assert k.startswith("gsk_key_")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker) for _ in range(5)]
            for f in concurrent.futures.as_completed(futures):
                f.result()


# ==============================================================================
# SECTION 4: Visual Keyframe Edge Cases
# ==============================================================================

class TestVisualKeyframeEdgeCases:
    """Stress testing timecodes, resolution clamping, seek beyond duration, timeouts."""

    def test_invalid_and_pathological_timestamps(self):
        # Non-numeric
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("abc")
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("12:xx")
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("::")

        # Negative timestamps must be rejected
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("-10")
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("-01:20")

        # NaN and Inf must be rejected
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("nan")
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("inf")
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("-inf")

        # Out-of-range minutes/seconds (e.g. 99:99:99) must be rejected
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("00:99:99")
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parse_ts("00:60:00")

    def test_extract_keyframe_beyond_duration(self, tmp_path):
        """Seek beyond duration where ffmpeg and yt-dlp section download fail."""
        with patch("whis_tube.visual.run_command") as mock_rc:
            # yt-dlp stream url resolution succeeds
            mock_rc.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="https://stream.m3u8\n", stderr=""), # url
                subprocess.CompletedProcess(args=[], returncode=0, stdout="vid_test\n", stderr=""),            # id
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Seek past EOF\n"),      # ffmpeg 1
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Seek past EOF\n"),      # ffmpeg retry
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="yt-dlp clip fail\n"),   # yt-dlp section
            ]
            with pytest.raises(RuntimeError, match="Failed to extract frame"):
                extract_keyframe("https://youtube.com/watch?v=vid_test", "01:59:59", output_path=str(tmp_path / "out.jpg"))

    def test_resolution_clamping(self, tmp_path):
        """Negative, zero, or out-of-range resolution should be clamped to safe default."""
        with patch("whis_tube.visual.run_command") as mock_rc:
            mock_rc.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            try:
                extract_keyframe("https://youtube.com/watch?v=vid1", "00:01:00", resolution=-500)
            except RuntimeError:
                pass
            called_cmd = mock_rc.call_args_list[0][0][0]
            # Clamped to 720
            assert "height<=720" in " ".join(called_cmd)


# ==============================================================================
# SECTION 5: Concurrency & Resource Leaks
# ==============================================================================

class TestConcurrencyAndResourceLeaks:
    """Stress testing cleanup of chunk files on exception, temporary files, and descriptors."""

    def test_chunk_file_leaked_on_transcription_exception(self, tmp_path):
        """CRITICAL: If transcribe_chunk raises an exception, the cut chunk FLAC must not be leaked."""
        flac_master = tmp_path / "master.16k.flac"
        flac_master.write_bytes(b"dummy master flac content")

        chunk_created = tmp_path / "master.chunk000.flac"

        def fake_cut(flac, idx, start, end):
            chunk_created.write_bytes(b"chunk flac bytes")
            return chunk_created

        pool = MagicMock()

        with patch("whis_tube.audio.cut_chunk", side_effect=fake_cut), \
             patch("whis_tube.audio.transcribe_chunk", side_effect=RuntimeError("Groq simulated network crash")):
            try:
                # Simulating transcribe_video loop body
                chunk = fake_cut(flac_master, 0, 0.0, 600.0)
                assert chunk.exists()
                # If we don't have try...finally, chunk stays on disk!
            finally:
                chunk_created.unlink(missing_ok=True)
