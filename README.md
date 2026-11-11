<div align="center">

# whis-tube 🎙️📹

**High-Fidelity YouTube Verbatim Transcription & Rapid Visual Keyframe Intelligence MCP Server**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Groq Whisper Large V3](https://img.shields.io/badge/Whisper-Large%20V3-orange.svg)](https://console.groq.com)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)
</div>

---

`whis-tube` is a Python-based Model Context Protocol (MCP) server engineered specifically for AI Coding Agents (Claude Code, Cursor, Windsurf, OpenBot, Hermes). It combines **lossless verbatim audio transcription via Groq Whisper Large V3** with **blazing-fast HD (720p/1080p) visual keyframe extraction** for ground-truth visual validation.

---

## ✨ Key Features

- **True Verbatim Audio Ground-Truth (No Auto-Captions):** Fetches the original audio track (actively rejecting AI auto-dubbing), decodes once to FLAC 16 kHz mono using the SoX resampler and speech-clarity filter (`highpass`, `dynaudnorm`), and transcribes every spoken word with timestamp accuracy.
- **Bilingual Indonesian-English Code-Switching:** Smart language detection, automated ticker and brand extraction (BTC, IHSG, BlackRock, TradingView), domain glossaries (crypto, finance, tech), deterministic phonetic collision normalization, and boilerplate hallucination filtering.
- **Smart Silence-Detected Chunking (<25MB):** Automatically detects pauses and silence intervals to slice long audio (1–3+ hours) into ~10-minute segments. Requests strictly remain under Groq's 25 MB payload limit.
- **Multi-Key Pool & 429 Failover:** Rotates across multiple Groq API keys seamlessly. When an HTTP 429 rate limit is encountered, the server reads the `retry-after` header, flags the key for cooldown, and transparently dispatches remaining chunks to another available key without failing the task.
- **Rapid Visual Keyframe Extraction (HLS Range-Seek):** Extracts crisp native 720p/1080p frames in 4–7 seconds on exact timestamps without downloading the entire video file.
- **Agent SOP Ready (`SKILL.md`):** Includes comprehensive research methodology guidelines for AI agents, preventing lazy summaries and mandating inline visual verification for charts, slides, and technical formulas.

---

## 🛠️ System Requirements

- **Python:** `>= 3.10`
- **yt-dlp:** Available in system PATH (`yt-dlp --version`)
- **ffmpeg & ffprobe:** Available in system PATH (`ffmpeg -version`)
- **Groq API Key:** Free tier keys available at [console.groq.com](https://console.groq.com)

---

## 🚀 Quickstart (One Command via `uv`)

Run the MCP server directly without manual virtualenv management:

```bash
# Run the MCP server directly
uv run --directory . python -m whis_tube.server
```

Or install locally in editable mode:

```bash
uv pip install -e .
youtube-whisper
```

---

## 🔌 MCP Client Configuration

### 1. Claude Desktop / Claude Code / Cursor
Add the server entry to your MCP configuration file (e.g., `claude_desktop_config.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "youtube-whisper": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/whis-tube",
        "python",
        "-m",
        "whis_tube.server"
      ],
      "env": {
        "GROQ_API_KEY": "gsk_your_key_here"
      }
    }
  }
}
```

### 2. Multi-Key Pool (Recommended for Heavy Research)
If you maintain multiple free-tier Groq API keys to maximize hourly/daily quotas, store them in `~/.config/groq/keys.json`:

```json
{
  "keys": [
    "gsk_key1...",
    "gsk_key2...",
    "gsk_key3..."
  ]
}
```

The `youtube-whisper` server automatically detects this pool file, manages round-robin rotation, and tracks key cooldown periods automatically.

---

## 🧰 Available MCP Tools

| Tool Name | Description | Arguments |
| :--- | :--- | :--- |
| `transcribe_youtube` | Downloads original audio, chunks at silence (<25MB), and transcribes verbatim into timestamped `.md` and structured `_raw.json` with bilingual code-switching. | `url` (str), `output_path` (str, optional), `language` (str, optional), `glossary` (str, optional) |
| `extract_keyframe` | Extracts native HD frames (720p / 1080p) at exact timestamps (`HH:MM:SS`) in 4–7 seconds via HLS seek. | `url` (str), `timestamp` (str), `output_path` (str, optional), `resolution` (int, default 720) |
| `get_video_info` | Retrieves concise metadata (title, channel, duration, live stream status). | `url` (str) |
| `list_channel_videos` | Generates a chronological catalog of channel uploads (excluding Shorts), ordered oldest to newest. | `channel_url` (str), `limit` (int, default 30), `sort_order` (str, `oldest_first`/`newest_first`) |
| `check_groq_quota` | Real-time health dashboard inspecting active Groq API keys, usage cooldowns, and pool readiness. | *(none)* |

---

## 📂 Repository Structure

```text
whis-tube/
├── .mcp.json               # Default MCP client configuration
├── .env.example            # Environment variables template
├── pyproject.toml          # Package configuration & dependencies
├── SKILL.md                # AI Agent Research Methodology & SOP (English)
├── README.md               # English Documentation
└── src/
    └── whis_tube/
        ├── __init__.py     # Package metadata
        ├── __main__.py     # Module CLI entrypoint
        ├── server.py       # FastMCP server & registered tool definitions
        ├── audio.py        # yt-dlp, SoX FLAC encoding, clarity filter & chunking
        ├── code_switch.py  # Bilingual Indonesian-English code-switching & phonetic rules
        ├── groq_pool.py    # Multi-key Groq pool & automatic 429 failover
        ├── visual.py       # HLS range-seek frame grabber
        └── utils.py        # Timestamp formatting & channel parser
```

---

## 📄 License

Distributed under the [MIT](LICENSE) License. Free for personal and commercial agent workflows.
