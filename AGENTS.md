# Agent Instructions (`whis-tube`)

Read this file first whenever you explore, clone, or run `whis-tube` from any AI agent harness (Antigravity, Claude Code, Cursor, Windsurf, Codex, OpenCode, Cline, Roo Code, Hermes).

## 1. Zero-Sudo Autonomous Setup (Run Immediately)

Do **not** use `sudo`, `apt`, `brew`, or ask the user for system package permissions. Run the single zero-sudo bootstrap command from the repository root:

```bash
python3 bootstrap.py
```

What `bootstrap.py` automatically provisions using Python's standard library alone:
- Downloads standalone static `uv` & `uvx` into `./.bin/` (and repairs/links `~/.local/bin/uv` & `uvx`).
- Downloads standalone static `ffmpeg` & `ffprobe` (with `libsoxr`, `highpass`, `dynaudnorm`, and HLS support) into `./.bin/` (and repairs/links `~/.local/bin/ffmpeg` & `ffprobe`).
- Creates `./.venv/` and installs all Python dependencies (`mcp`, `yt-dlp`, `requests`, `python-dotenv`, `pydantic`).
- Configures `./keys.json` with `chmod 600`, `git update-index --skip-worktree keys.json`, and a `.git/hooks/pre-commit` secret guard so real API keys are never committed or pushed.
- Auto-registers `youtube-whisper` in Antigravity (`~/.gemini/config/mcp_config.json` & `~/.gemini/config/plugins/whis-tube`) when `~/.gemini` exists.

Verify readiness anytime with:

```bash
python3 bootstrap.py --doctor
```

## 2. API Key Configuration (`./keys.json`)

- **Default user-editable file:** `./keys.json` right in the `whis-tube` directory.
- **Hot-reloaded key discovery priority:**
  1. `<repo_root>/keys.json`
  2. `<repo_root>/keys.local.json`
  3. `<cwd>/keys.json`
  4. `GROQ_KEYS_PATH` environment variable (if set)
  5. `GROQ_API_KEY` environment variable or `.env` (comma-separated keys supported)
  6. `~/.config/groq/keys.json` (global pool fallback)
- Placeholder strings (such as `gsk_PASTE_YOUR_GROQ_API_KEY_1_HERE`) are safely ignored and never shadow real keys in `.env` or `~/.config/groq/keys.json`.
- **Security rule:** Never print, log, echo, or paste raw `gsk_...` API keys into terminal output or chat responses. If `0 active keys` are reported, simply instruct the user to open `./keys.json`, paste their Groq API key(s) from https://console.groq.com/keys, and save.

## 3. Using `whis-tube` (MCP Server or Instant CLI)

### Option A: MCP Tools (`youtube-whisper`)
Start over stdio with `python3 bootstrap.py --serve` or `./.venv/bin/python -m whis_tube.server`.
Available MCP tools:
- `transcribe_youtube(url, output_path="", language="", glossary="", preset="auto")`
- `extract_keyframe(url, timestamp, output_path="", resolution=1080)`
- `get_video_info(url)` (includes channel handle/slug, asset type, sanitized title, and long-run timeout hint)
- `list_channel_videos(channel_url, limit=30, sort_order="oldest_first")`
- `check_groq_quota()`
- `scaffold_channel_workspace(workspace_root, channel_name, channel_url="", channel_slug="", video_id="", title="", duration="", asset_type="videos", status="⏳ In Progress")`
- `audit_research_report(report_path, transcript_path="", catalog_path="", min_frames=0, min_words=0, require_1080p=True)`

### Option B: Direct CLI (Immediate Fallback & Timeout-Safe Mode for `>= 45m` Livestreams)
Every tool works directly via `./.venv/bin/whis-tube`. For videos/livestreams `>= 45 min`, prefer CLI `--transcribe` to avoid 3-minute MCP client timeouts:

```bash
./.venv/bin/whis-tube --check-quota
./.venv/bin/whis-tube --info "https://www.youtube.com/watch?v=VIDEO_ID"
./.venv/bin/whis-tube --list-channel "https://www.youtube.com/@handle/videos" --limit 30 --sort oldest_first
./.venv/bin/whis-tube --scaffold --workspace-root youtube-research --channel-name "Channel Name" --channel-url "https://www.youtube.com/@handle" --video-id VIDEO_ID --title "Video Title" --duration 3600 --asset-type livestreams
./.venv/bin/whis-tube --keyframe "https://www.youtube.com/watch?v=VIDEO_ID" "00:15:30" --resolution 1080 --output frames/
./.venv/bin/whis-tube --transcribe "https://www.youtube.com/watch?v=VIDEO_ID" --output transcripts/ --preset auto
./.venv/bin/whis-tube --audit-report "youtube-research/<slug>/analysis/videos/<report>.md"
```

## 4. Channel Research SOP

For full YouTube channel or livestream intelligence workflows, follow [SKILL.md](SKILL.md) (and [skills/youtube-whisper/SKILL.md](skills/youtube-whisper/SKILL.md)).
