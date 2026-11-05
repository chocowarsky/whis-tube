"""Unit tests for whis-tube MCP server and utilities."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from whis_tube.server import (
    check_groq_quota,
    get_video_info,
    list_channel_videos,
    mcp,
)
from whis_tube.utils import fmt_ts, parse_ts, sanitize_filename


def test_time_formatting():
    assert fmt_ts(0) == "00:00:00"
    assert fmt_ts(65) == "00:01:05"
    assert fmt_ts(3665) == "01:01:05"


def test_time_parsing():
    assert parse_ts("00:01:05") == 65.0
    assert parse_ts("01:01:05") == 3665.0
    assert parse_ts("10:30") == 630.0
    assert parse_ts("45") == 45.0


def test_time_parsing_invalid():
    with pytest.raises(ValueError, match="Invalid timestamp format"):
        parse_ts("invalid:time:format:extra")


def test_sanitize_filename():
    assert sanitize_filename("My Video: Ep. 1 / Test?") == "My_Video_Ep_1_Test"
    assert sanitize_filename("../../../etc/passwd") == "etcpasswd"
    assert sanitize_filename("") == "video"


@pytest.mark.asyncio
async def test_mcp_server_tools():
    # Verify server name
    assert mcp.name == "youtube-whisper"

    # Verify registered tools
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]

    expected = [
        "transcribe_youtube",
        "extract_keyframe",
        "get_video_info",
        "list_channel_videos",
        "check_groq_quota",
    ]
    for exp in expected:
        assert exp in tool_names, f"Expected tool '{exp}' not found in registered tools"


@pytest.mark.asyncio
async def test_get_video_info_view_count_variations():
    # 1. Normal numeric view_count
    with patch("whis_tube.server._get_video_info") as mock_info:
        mock_info.return_value = {
            "id": "abc123xyz",
            "title": "Test Title",
            "channel": "Test Channel",
            "duration": 120,
            "upload_date": "20261105",
            "live_status": "not_live",
            "language": "id",
            "view_count": 1500000,
        }
        res = await get_video_info("https://www.youtube.com/watch?v=abc123xyz")
        assert "View Count:** 1,500,000" in res
        assert "Test Title" in res

    # 2. None view_count (common yt-dlp edge case)
    with patch("whis_tube.server._get_video_info") as mock_info:
        mock_info.return_value = {
            "id": "abc123xyz",
            "title": "Test Title",
            "view_count": None,
        }
        res = await get_video_info("https://www.youtube.com/watch?v=abc123xyz")
        assert "View Count:** N/A" in res

    # 3. Missing view_count key
    with patch("whis_tube.server._get_video_info") as mock_info:
        mock_info.return_value = {
            "id": "abc123xyz",
            "title": "Test Title",
        }
        res = await get_video_info("https://www.youtube.com/watch?v=abc123xyz")
        assert "View Count:** N/A" in res

    # 4. String view_count that is digits
    with patch("whis_tube.server._get_video_info") as mock_info:
        mock_info.return_value = {
            "id": "abc123xyz",
            "title": "Test Title",
            "view_count": "45200",
        }
        res = await get_video_info("https://www.youtube.com/watch?v=abc123xyz")
        assert "View Count:** 45,200" in res

    # 5. String view_count that is non-digit
    with patch("whis_tube.server._get_video_info") as mock_info:
        mock_info.return_value = {
            "id": "abc123xyz",
            "title": "Test Title",
            "view_count": "hidden",
        }
        res = await get_video_info("https://www.youtube.com/watch?v=abc123xyz")
        assert "View Count:** N/A" in res


@pytest.mark.asyncio
async def test_get_video_info_error():
    with patch("whis_tube.server._get_video_info", side_effect=RuntimeError("Network error")):
        res = await get_video_info("https://www.youtube.com/watch?v=invalid")
        assert "Gagal mengambil informasi video: Network error" in res


@pytest.mark.asyncio
async def test_check_groq_quota_empty_and_active(tmp_path):
    with patch("whis_tube.server.load_groq_keys", return_value=[]):
        res = await check_groq_quota()
        assert "Tidak ada API key Groq yang terdeteksi" in res

    with patch("whis_tube.server.load_groq_keys", return_value=["gsk_dummy_1", "gsk_dummy_2"]):
        with patch("whis_tube.groq_pool.KEY_STATE_PATH", tmp_path / "state.json"):
            res = await check_groq_quota()
            assert "⚡ **Groq Key Pool Status** (2 total key terdaftar)" in res
            assert "Key Siap Digunakan:** 2 / 2" in res
            assert "✅ Ready" in res


@pytest.mark.asyncio
async def test_list_channel_videos_formatting():
    with patch("whis_tube.server._list_channel_videos") as mock_list:
        mock_list.return_value = [
            {
                "id": "vid1",
                "title": "Video 1 | Episode 1",
                "url": "https://www.youtube.com/watch?v=vid1",
                "duration": 300,
                "duration_formatted": "00:05:00",
                "upload_date": "20261101",
            }
        ]
        res = await list_channel_videos("https://www.youtube.com/@channel/videos")
        assert "Katalog Video Channel" in res
        assert "Video 1 / Episode 1" in res
        assert "2026-11-01" in res
        assert "[Tonton](https://www.youtube.com/watch?v=vid1)" in res

    with patch("whis_tube.server._list_channel_videos", return_value=[]):
        res = await list_channel_videos("https://www.youtube.com/@channel/videos")
        assert "Tidak ada video ditemukan" in res
