# Gemini / Antigravity Instructions (`whis-tube`)

Follow the universal instructions in [AGENTS.md](AGENTS.md) and research SOP in [skills/youtube-whisper/SKILL.md](skills/youtube-whisper/SKILL.md).

Quick checklist when entering this repository:
1. **Zero-sudo setup (no `sudo` / `apt` / `brew`):** run `python3 bootstrap.py` to auto-install standalone `uv`, `ffmpeg`, `ffprobe`, `.venv` (`yt-dlp`, `mcp`), key protections, and register `~/.gemini/config/mcp_config.json` + `~/.gemini/config/plugins/whis-tube`.
2. **Groq API keys:** users paste keys directly into `./keys.json` (hot-reloaded; protected by `chmod 600`, `skip-worktree`, and `.git/hooks/pre-commit`; never print raw `gsk_...` keys). Fallback: `~/.config/groq/keys.json` or `GROQ_API_KEY`.
3. **MCP & CLI:** `youtube-whisper` exposes `transcribe_youtube`, `extract_keyframe` (defaults to `1080p` with relative `frames/` embed), `get_video_info` (with channel slug/handle/sanitized title routing), `list_channel_videos`, `check_groq_quota`, `scaffold_channel_workspace`, and `audit_research_report`. For long streams (`>= 45 min`) or immediate terminal usage, run `./.venv/bin/whis-tube --transcribe`, `--scaffold`, `--audit-report`, `--keyframe`, `--info`, `--list-channel`, or `--check-quota`. Always pass `audit_research_report` before marking any video complete.
