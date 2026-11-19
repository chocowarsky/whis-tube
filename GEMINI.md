# Gemini / Antigravity Instructions (`whis-tube`)

Follow the universal instructions in [AGENTS.md](AGENTS.md) and research SOP in [skills/youtube-whisper/SKILL.md](skills/youtube-whisper/SKILL.md).

Quick checklist when entering this repository:
1. **Zero-sudo setup (no `sudo` / `apt` / `brew`):** run `python3 bootstrap.py` to auto-install standalone `uv`, `ffmpeg`, `ffprobe`, `.venv` (`yt-dlp`, `mcp`), key protections, and register `~/.gemini/config/mcp_config.json` + `~/.gemini/config/plugins/whis-tube`.
2. **Groq API keys:** users paste keys directly into `./keys.json` (hot-reloaded; protected by `chmod 600`, `skip-worktree`, and `.git/hooks/pre-commit`; never print raw `gsk_...` keys). Fallback: `~/.config/groq/keys.json` or `GROQ_API_KEY`.
3. **MCP & CLI:** `youtube-whisper` exposes `transcribe_youtube`, `extract_keyframe`, `get_video_info`, `list_channel_videos`, and `check_groq_quota`. For immediate terminal usage without waiting for an MCP reload, run `./.venv/bin/whis-tube --check-quota`, `--info`, `--list-channel`, `--keyframe`, or `--transcribe`.
