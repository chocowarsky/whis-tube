"""Unit tests for whis-tube MCP server and utilities."""

import pytest
import asyncio
from whis_tube.server import mcp
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


def test_sanitize_filename():
    assert sanitize_filename("My Video: Ep. 1 / Test?") == "My_Video_Ep_1_Test"


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
