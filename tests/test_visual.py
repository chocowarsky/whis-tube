"""Unit tests for visual frame extraction logic and fallbacks."""

import pathlib
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from whis_tube.visual import extract_keyframe


def test_extract_keyframe_success(tmp_path):
    target_img = tmp_path / "custom_dir" / "frame_000105.jpg"
    target_img.parent.mkdir(parents=True, exist_ok=True)

    def mock_run(cmd, check=True):
        if "-g" in cmd:
            # yt-dlp stream url resolution
            return subprocess.CompletedProcess(cmd, 0, stdout="https://manifest.googlevideo.com/m3u8\n", stderr="")
        elif "--get-id" in cmd:
            # yt-dlp get-id
            return subprocess.CompletedProcess(cmd, 0, stdout="test_vid_123\n", stderr="")
        elif "ffprobe" in cmd:
            # ffprobe dimensions
            return subprocess.CompletedProcess(cmd, 0, stdout="1280x720\n", stderr="")
        elif "ffmpeg" in cmd:
            # ffmpeg extraction creates output file
            target_path = pathlib.Path(cmd[cmd.index("-q:v") + 2])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 1024)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("whis_tube.visual.run_command", side_effect=mock_run):
        res = extract_keyframe(
            "https://www.youtube.com/watch?v=test_vid_123",
            "00:01:05",
            output_path=str(target_img),
            resolution=720,
        )

        assert res["status"] == "success"
        assert res["video_id"] == "test_vid_123"
        assert res["timestamp"] == "00:01:05"
        assert res["seconds"] == 65.0
        assert res["dimensions"] == "1280x720"
        assert pathlib.Path(res["image_path"]).exists()
        assert "![Visual Frame: 00:01:05]" in res["markdown_embed"]


def test_extract_keyframe_retry_and_clip_fallback(tmp_path):
    """Verify that when direct stream ffmpeg range seek fails,
    the fallback to yt-dlp section download extracts the frame successfully.
    """
    out_file = tmp_path / "fallback_frame.jpg"

    def mock_run(cmd, check=True):
        if "-g" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="https://manifest.googlevideo.com/m3u8\n", stderr="")
        elif "--get-id" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="vid_fallback\n", stderr="")
        elif "--download-sections" in cmd:
            # yt-dlp section download fallback
            out_arg = cmd[cmd.index("-o") + 1]
            p = pathlib.Path(out_arg)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"dummy_mp4_bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        elif "ffprobe" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="1920x1080\n", stderr="")
        elif "ffmpeg" in cmd:
            # If input is the direct stream URL, simulate failure
            if "https://manifest.googlevideo.com/m3u8" in cmd:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 403 Forbidden")
            # If input is the local clip, simulate success
            out_arg = cmd[cmd.index("-q:v") + 2]
            p = pathlib.Path(out_arg)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 512)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("whis_tube.visual.run_command", side_effect=mock_run):
        res = extract_keyframe(
            "https://www.youtube.com/watch?v=vid_fallback",
            "00:02:30",
            output_path=str(out_file),
            resolution=1080,
        )

        assert res["status"] == "success"
        assert res["video_id"] == "vid_fallback"
        assert res["timestamp"] == "00:02:30"
        assert res["dimensions"] == "1920x1080"
        assert pathlib.Path(res["image_path"]).exists()


def test_extract_keyframe_exhausted_failure(tmp_path):
    out_file = tmp_path / "fail_frame.jpg"

    def mock_run(cmd, check=True):
        if "-g" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="https://manifest.googlevideo.com/m3u8\n", stderr="")
        elif "--get-id" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="vid_fail\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Total failure")

    with patch("whis_tube.visual.run_command", side_effect=mock_run):
        with pytest.raises(RuntimeError, match="Failed to extract frame"):
            extract_keyframe(
                "https://www.youtube.com/watch?v=vid_fail",
                "00:00:10",
                output_path=str(out_file),
            )
