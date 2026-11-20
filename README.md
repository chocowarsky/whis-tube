<div align="center">

# whis-tube 🎙️📹

**High-Fidelity YouTube Verbatim Transcription & Rapid Visual Keyframe Intelligence MCP Server**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Groq Whisper Large V3](https://img.shields.io/badge/Whisper-Large%20V3-orange.svg)](https://console.groq.com)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)
</div>

---

`whis-tube` is a self-contained, zero-sudo Model Context Protocol (MCP) server and CLI engineered for AI Coding Agents (Antigravity, Claude Code, Cursor, Windsurf, Codex, OpenCode, Cline, Hermes). It combines **lossless verbatim audio transcription via Groq Whisper Large V3** with **blazing-fast HD (720p/1080p) visual keyframe extraction** for ground-truth visual validation.

---

## ✨ Key Features

- **Zero-Sudo 1-Command Setup (`bootstrap.py`):** Uses only Python's standard library to download standalone static `uv`, `ffmpeg`, and `ffprobe` (with `libsoxr` & HLS support) into `./.bin/`, create `./.venv/` with `yt-dlp` and `mcp`, and register Antigravity MCP/plugin configs—no `sudo`, `apt`, or `brew` required.
- **Drop-In Project Key Vault (`./keys.json`):** Open `keys.json` right inside the cloned folder, paste your Groq API key(s), and save. Changes hot-reload automatically without restarting, and keys are shielded via `chmod 600`, `git --skip-worktree`, and a `.git/hooks/pre-commit` secret guard so keys are never leaked to GitHub.
- **True Verbatim Audio Ground-Truth (No Auto-Captions):** Fetches the original audio track (actively rejecting AI auto-dubbing), decodes once to FLAC 16 kHz mono using the SoX resampler and speech-clarity filter (`highpass`, `dynaudnorm`), and transcribes every spoken word with timestamp accuracy.
- **Universal Domain Presets & Hot-Reloaded Custom Lexicon (`lexicon.json`):** Neutral bilingual default for general content (zero forced finance bias), auto-detection across 6 built-in presets (`tech`, `finance`, `crypto`, `medical`, `gaming`, `business`), explicit override via `preset` / `--preset` (`auto`, `none`, or custom preset names), automated ticker/brand extraction, and drop-in customization via `lexicon.json` (copy `lexicon.example.json` → `lexicon.json` in project root or `~/.config/whis-tube/lexicon.json`).
- **Smart Silence-Detected Chunking (<25MB):** Automatically detects pauses and silence intervals to slice long audio (1–3+ hours) into ~10-minute segments. Requests strictly remain under Groq's 25 MB payload limit.
- **Multi-Key Pool & 429 Failover:** Rotates across multiple Groq API keys seamlessly. When an HTTP 429 rate limit is encountered, the server reads the `retry-after` header, flags the key for cooldown, and transparently dispatches remaining chunks to another available key without failing the task.
- **Rapid Visual Keyframe Extraction (HLS Range-Seek):** Extracts crisp native 720p/1080p frames in 4–7 seconds on exact timestamps without downloading the entire video file.
- **Universal Agent Discovery & Direct CLI Fallback:** Ships with `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and `SKILL.md` so any agent harness immediately knows how to set up and run every tool—either over MCP or directly via `./.venv/bin/whis-tube`.

---

## ⚡ 2-Step Quickstart (Zero-Sudo)

### Step 1: Clone & Auto-Bootstrap (No `sudo`, No Prompts)

```bash
git clone https://github.com/chocowarsky/whis-tube.git
cd whis-tube
python3 bootstrap.py
```

This automatically installs standalone `uv`, `ffmpeg`, `ffprobe`, `.venv` (`yt-dlp`, `mcp`, `requests`, `python-dotenv`, `pydantic`), configures Antigravity (`~/.gemini/config`), and verifies readiness.

### Step 2: Add Your Groq API Key(s)

Open **`keys.json`** right in the `whis-tube` folder, paste one or more free Groq keys from [console.groq.com/keys](https://console.groq.com/keys), and save:

```json
{
  "keys": [
    "gsk_your_first_key_here",
    "gsk_your_second_key_here"
  ]
}
```

Check readiness anytime:

```bash
python3 bootstrap.py --doctor
./.venv/bin/whis-tube --check-quota
```

> **Key Discovery Priority:** `./keys.json` (project root) → `./keys.local.json` → `<workspace>/keys.json` → `GROQ_KEYS_PATH` → `GROQ_API_KEY` (`.env` or env var) → `~/.config/groq/keys.json`. Placeholder templates are automatically ignored so they never shadow real keys.

---

## 🔌 MCP Client & CLI Usage

### 1. Google Antigravity (IDE, CLI `agy` & Desktop)
Running `python3 bootstrap.py` automatically registers `youtube-whisper` in `~/.gemini/config/mcp_config.json` and installs the plugin bundle into `~/.gemini/config/plugins/whis-tube`.

Or install directly with `agy`:

```bash
agy plugin install /path/to/whis-tube
agy plugin validate --strict ~/.gemini/config/plugins/whis-tube
```

### 2. Claude Code / Cursor / Windsurf / Generic MCP Clients
`.mcp.json` at the repo root auto-launches the self-healing server via `python3 bootstrap.py --serve`:

```json
{
  "mcpServers": {
    "youtube-whisper": {
      "command": "python3",
      "args": ["bootstrap.py", "--serve"]
    }
  }
}
```

If pointing from an external workspace config, pass the full path to `bootstrap.py` (or `./.venv/bin/python -m whis_tube.server`).

### 3. Direct CLI Mode (Works Immediately Without MCP Reload)

```bash
./.venv/bin/whis-tube --check-quota
./.venv/bin/whis-tube --info "https://www.youtube.com/watch?v=VIDEO_ID"
./.venv/bin/whis-tube --list-channel "https://www.youtube.com/@handle/videos" --limit 30 --sort oldest_first
./.venv/bin/whis-tube --keyframe "https://www.youtube.com/watch?v=VIDEO_ID" "00:15:30" --resolution 1080 --output frames/
./.venv/bin/whis-tube --transcribe "https://www.youtube.com/watch?v=VIDEO_ID" --output transcripts/ --language id --preset auto
./.venv/bin/whis-tube --transcribe "https://www.youtube.com/watch?v=VIDEO_ID" --preset tech --glossary "FastMCP, Docker, Kubernetes"
```

### 4. Customizing Presets & Lexicons (`lexicon.json`)
Copy `lexicon.example.json` to `./lexicon.json` (project root) or `~/.config/whis-tube/lexicon.json` to define custom domain presets (`triggers`, `style_seed`, `glossary`, `phonetic_rules`), override built-in presets, or change `default_preset` without editing Python code. Discovery order (highest priority first, hot-reloaded on every run):

1. `<repo_root>/lexicon.json`
2. `<repo_root>/lexicon.local.json`
3. `<workspace>/lexicon.json`
4. `WHIS_TUBE_LEXICON_PATH` environment variable
5. `~/.config/whis-tube/lexicon.json`

---

## 🧰 Available MCP Tools

| Tool Name | Description | Arguments |
| :--- | :--- | :--- |
| `transcribe_youtube` | Downloads original audio, chunks at silence (<25MB), and transcribes verbatim into timestamped `.md` and structured `_raw.json` with universal code-switching & domain presets. | `url` (str), `output_path` (str, optional), `language` (str, optional), `glossary` (str, optional), `preset` (str, default `"auto"`) |
| `extract_keyframe` | Extracts native HD frames (720p / 1080p) at exact timestamps (`HH:MM:SS`) in 4–7 seconds via HLS seek. | `url` (str), `timestamp` (str), `output_path` (str, optional), `resolution` (int, default 720) |
| `get_video_info` | Retrieves concise metadata (title, channel, duration, live stream status). | `url` (str) |
| `list_channel_videos` | Generates a chronological catalog of channel uploads (excluding Shorts), ordered oldest to newest. | `channel_url` (str), `limit` (int, default 30), `sort_order` (str, `oldest_first`/`newest_first`) |
| `check_groq_quota` | Real-time health dashboard inspecting active Groq API keys, binary readiness, usage cooldowns, and pool status. | *(none)* |

---

## 📂 Repository Structure

```text
whis-tube/
├── AGENTS.md                 # Universal AI agent bootstrap & tool instructions
├── CLAUDE.md                 # Claude Code entrypoint instructions
├── GEMINI.md                 # Gemini CLI / Antigravity entrypoint instructions
├── bootstrap.py              # Zero-sudo stdlib installer, binary manager & --serve launcher
├── keys.json                 # Local API key file (edit & save; protected by skip-worktree)
├── keys.example.json         # Clean placeholder template for keys.json
├── lexicon.example.json      # Template for custom domain presets, style seeds & phonetic rules
├── plugin.json               # Antigravity plugin manifest
├── mcp_config.json           # Antigravity MCP server configuration
├── .mcp.json                 # Claude Code / Cursor self-healing MCP configuration
├── .env.example              # Optional environment variables template
├── pyproject.toml            # Package configuration & dependencies
├── SKILL.md                  # AI Agent Research Methodology & SOP
├── README.md                 # Documentation
├── assets/
│   └── logo.svg              # Plugin icon for Antigravity UI
├── skills/
│   └── youtube-whisper/
│       └── SKILL.md          # Bundled Antigravity plugin skill
└── src/
    └── whis_tube/
        ├── __init__.py       # Package metadata
        ├── __main__.py       # Module CLI entrypoint
        ├── runtime.py        # Self-healing PATH, python -m yt_dlp & static ffmpeg guard
        ├── config.py         # Configuration & local/global key path discovery
        ├── server.py         # FastMCP server, tool definitions & direct CLI runner
        ├── audio.py          # yt-dlp, SoX FLAC encoding, clarity filter & chunking
        ├── code_switch.py    # Bilingual Indonesian-English code-switching & phonetic rules
        ├── groq_pool.py      # Multi-key Groq pool, hot-reload & automatic 429 failover
        ├── visual.py         # HLS range-seek frame grabber
        └── utils.py          # Timestamp formatting & channel parser
```

---

## 📄 License

Distributed under the [MIT](LICENSE) License. Free for personal and commercial agent workflows.
