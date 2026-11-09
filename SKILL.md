---
name: youtube-whisper
description: "Verbatim YouTube transcription (Whisper Large V3) and high-speed HD keyframe extraction pipeline for video intelligence."
version: 1.1.0
author: chocowarsky
license: MIT
metadata:
  tags: [YouTube, Whisper, Video, Speech-to-Text, Keyframe, Groq, FastMCP, Code-Switching]
---

# YouTube Whisper Intelligence Skill (SOP)

🌐 **[English Version](SKILL.md)** | **[Versi Bahasa Indonesia](SKILL.id.md)**

Standardized pipeline for deep research on YouTube videos using verbatim (lossless word-for-word) transcription via Groq Whisper Large V3, bilingual Indonesian-English code-switching enhancements, and rapid visual HD frame extraction (720p/1080p) via HLS range-seek.

## When to Use This Skill

1. **Long-Form Video Intelligence**: When a user requests summaries, verbatim transcripts, or deep analysis of videos ranging from 10 minutes to several hours (podcasts, livestreams, technical presentations).
2. **Strict Verbatim Accuracy Requirements (Ground Truth)**: Never rely on YouTube's default auto-captions, which frequently censor terms, drop punctuation, misspell financial tickers, or omit critical numbers.
3. **Bilingual Indonesian-English Technical Content**: When transcribing Indonesian videos discussing crypto, finance, programming, or tech where speakers mix English loanwords and terminology (code-switching).
4. **Visual Ground-Truth Verification (Charts, Slides, Code, Formulas)**: When speakers make visual references ("as seen in this diagram", "the chart clearly shows"), immediately trigger `extract_keyframe` at that timestamp to perform multimodal vision inspection.

---

## MCP Tool Reference (`youtube-whisper`)

| Tool | Function | Key Arguments |
| :--- | :--- | :--- |
| `transcribe_youtube` | Full verbatim audio transcription with silence-detected smart chunking (<25MB) and bilingual code-switching | `url`, `output_path`, `language`, `glossary` |
| `extract_keyframe` | Ultra-fast native HD frame extraction (720p/1080p) via HLS seek in 4–7 seconds | `url`, `timestamp` (HH:MM:SS), `resolution` |
| `get_video_info` | Fast video metadata (title, channel, duration, live stream status) | `url` |
| `list_channel_videos` | Chronological video catalog (excluding Shorts) from oldest to newest | `channel_url`, `limit`, `sort_order` |
| `check_groq_quota` | Real-time key pool health and cooldown monitoring | - |

---

## Operational Procedures & Quality Standards

### 1. Audio Transcription & Bilingual Code-Switching
- Invoke `transcribe_youtube(url="<link>", glossary="...")`.
- The pipeline isolates the original audio track (rejecting AI auto-dubbing), applies a speech-clarity filter (`highpass=f=80,dynaudnorm=f=150:g=15:p=0.95`), and decodes to 16 kHz mono FLAC via SoX resampling.
- Automatically detects Indonesian content from metadata even when YouTube mislabels the audio language as English.
- Extracts financial tickers (BTC, IHSG, FOMC), CamelCase brands (BlackRock, TradingView, Pump.fun), and domain keywords to prime Whisper Large V3 with style seeds and token-budgeted prompts (<600 chars).
- Applies deterministic phonetic normalizations (e.g. correcting phonetic slips like "busai" -> "Bursa Efek", "PAMFAN" -> "Pump.fun", "Starling" -> "Starlink") and filters silence/boilerplate hallucinations.
- Supports custom user lexicons via optional `~/.config/whis-tube/lexicon.json` or tool parameter `glossary="term1, term2"`.
- Outputs are saved in two parallel formats:
  - `.md` file: Clean, timestamped markdown transcript `[HH:MM:SS - HH:MM:SS]`.
  - `_raw.json` file: Segment-level confidence metrics, word timestamps, code-switching metadata, and low-confidence flags.

### 2. Visual Validation & Ambiguity Resolution
- Whenever a transcript flags low confidence or a speaker refers to visual exhibits on screen:
  ```python
  extract_keyframe(url=url, timestamp="00:15:30", resolution=720)
  ```
- **Mandatory Inline Embedding**: Always embed the resulting image directly into the report:
  ```markdown
  ![Visual Frame: 00:15:30](frames/<video_id>_001530.jpg)
  *Visual Evidence: [00:15:30] - Technical Architecture Diagram*
  ```

### 3. Chronological Channel Catalogs (Oldest to Newest)
- When analyzing an entire series, course, or channel history:
  - Always catalog chronologically starting from the debut video (`#01 / #001`) forward to recent uploads (`#N`).
  - Filter out YouTube Shorts (<60s).
  - Use `list_channel_videos(channel_url, sort_order="oldest_first")`.

### 4. Anti-LaTeX Constraint for Chat Readability
- Avoid wrapping monetary figures or mathematical expressions in LaTeX syntax (`$100`, `\approx`, `\rightarrow`) which breaks rendering in messaging platforms like Telegram.
- Use clean plain text or standard Unicode symbols:
  - Write `100 USD` or `Rp 100.000` (instead of `$100`).
  - Use `→`, `×`, `≈`, `≤`, `≥`, `%`.
