# GitHub Copilot Instructions (`whis-tube`)

`whis-tube` is a zero-sudo local YouTube verbatim transcription & 1080p keyframe MCP server (`Python 3.10+`).

- Read `AGENTS.md` and `skills/youtube-whisper/SKILL.md` before modifying code or running transcription pipelines.
- **Security:** Never print, log, hardcode, or commit real `gsk_...` Groq API keys or touch user `./keys.json` contents.
- **Verify setup:** `python3 bootstrap.py --doctor --json`
- **Run tests:** `./.venv/bin/python -m unittest discover -s tests -v` (or `python3 -m unittest discover -s tests -v`).
