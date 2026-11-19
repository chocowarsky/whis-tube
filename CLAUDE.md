# Claude Code Instructions (`whis-tube`)

Follow the universal instructions in [AGENTS.md](AGENTS.md) and research SOP in [SKILL.md](SKILL.md).

Quick checklist when entering this repository:
1. **Zero-sudo setup (no `sudo` / `apt` / `brew`):** run `python3 bootstrap.py` to auto-install standalone `uv`, `ffmpeg`, `ffprobe`, `.venv` (`yt-dlp`, `mcp`), key protections, and verify readiness.
2. **Groq API keys:** users paste keys directly into `./keys.json` (hot-reloaded; protected by `chmod 600`, `skip-worktree`, and `.git/hooks/pre-commit`; never print raw `gsk_...` keys). Fallback: `~/.config/groq/keys.json` or `GROQ_API_KEY`.
3. **MCP & CLI:** `.mcp.json` launches `python3 bootstrap.py --serve` automatically; if MCP tools aren't loaded in the current session, run `./.venv/bin/whis-tube --check-quota`, `--info`, `--list-channel`, `--keyframe`, or `--transcribe`.
