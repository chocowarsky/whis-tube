---
name: youtube-whisper
description: "Verbatim YouTube transcription (Whisper Large V3), 1080p keyframe intelligence, and autonomous channel research SOP."
version: 1.3.0
author: chocowarsky
license: MIT
metadata:
  tags: [YouTube, Whisper, Video, Speech-to-Text, Keyframe, Groq, FastMCP, Code-Switching, Channel-Research]
---

# YouTube Whisper Intelligence Skill (SOP)

Standardized, autonomous end-to-end research pipeline for YouTube channels and long-form videos using lossless verbatim transcription via Groq Whisper Large V3, bilingual Indonesian-English code-switching enhancements, rapid HD/Full-HD keyframe extraction (720p/1080p) via HLS range-seek, and deterministic catalog-driven workspace organization.

## When to Use This Skill

1. **Full-Channel Research from Scratch (Cold Start)**: When tasked with analyzing an entire YouTube channel, playlist, or video archive from zero—including automatic workspace setup, chronological cataloging, transcription, visual proof extraction, and structured analysis reports.
2. **Long-Form Video & Livestream Intelligence**: When analyzing videos or completed livestreams ranging from 10 minutes to multi-hour broadcasts (podcasts, market streams, technical presentations).
3. **Strict Verbatim Accuracy Requirements (Ground Truth)**: Never rely on YouTube's default auto-captions, which frequently censor terms, drop punctuation, misspell financial tickers, or omit critical numbers.
4. **Bilingual Indonesian-English Technical Content**: When transcribing Indonesian content discussing crypto, finance, programming, or tech where speakers mix English loanwords and terminology (code-switching).
5. **Visual Ground-Truth Verification (Charts, Slides, Code, Formulas)**: When speakers make visual references ("as seen on this chart", "looking at this slide") or pause for silent B-roll segments, trigger `extract_keyframe` at that exact timestamp and inspect it with vision tools.

---

## MCP Tool Reference (`youtube-whisper`)

| Tool | Function | Key Arguments |
| :--- | :--- | :--- |
| `transcribe_youtube` | Full verbatim audio transcription with silence-detected smart chunking (<25MB) and bilingual code-switching | `url`, `output_path`, `language`, `glossary` |
| `extract_keyframe` | Ultra-fast native HD frame extraction (720p/1080p) via HLS seek in 4–7 seconds | `url`, `timestamp` (HH:MM:SS), `output_path`, `resolution` |
| `get_video_info` | Fast video metadata (title, channel, duration, live stream status) | `url` |
| `list_channel_videos` | Chronological video/livestream catalog (excluding Shorts <60s) from oldest to newest | `channel_url`, `limit`, `sort_order` |
| `check_groq_quota` | Real-time key pool health and cooldown monitoring | - |

---

## Autonomous Cold-Start Channel Research Workflow

If a user instructs you to research a YouTube channel from scratch (e.g., *"Research YouTube channel `@example` end-to-end"*), execute the following phases automatically without asking for manual setup instructions:

### Phase 1: Channel Enumeration & Workspace Blueprint
1. **Enumerate Both Uploads & Livestreams**:
   - YouTube separates regular videos and live broadcasts into distinct tabs. Query both endpoints with a high limit (e.g., `limit=500`) and chronological ordering:
     - Regular videos: `list_channel_videos("https://www.youtube.com/@<handle>/videos", limit=500, sort_order="oldest_first")`
     - Livestreams: `list_channel_videos("https://www.youtube.com/@<handle>/streams", limit=500, sort_order="oldest_first")`
   - **Strict YouTube Shorts Exclusion**: Shorts (<60s) are micro-content and are strictly excluded from all catalogs and pipelines.
   - **Identical Methodological Treatment**: Regular long-form videos and livestreams are functionally and structurally identical video assets—both require the exact same verbatim transcription, visual frame extraction, multimodal vision inspection, and deep analysis report quality.

2. **Initialize the Clean Channel Directory Tree**:
   Create the exact folder hierarchy under `<workspace_root>/<channel-slug>/`:
   ```text
   <channel-slug>/
   ├── analysis/
   │   ├── videos/
   │   │   ├── frames/          # Extracted HD/1080p keyframes (<video_id>_<HHMMSS>.jpg)
   │   │   └── <slug>_vid_<num>_<video_id>.md
   │   └── livestreams/
   │       ├── frames/
   │       └── <slug>_live_<num>_<video_id>.md
   ├── raw-transcripts/
   │   ├── videos/
   │   │   ├── <video_id>_<sanitized_title>.md
   │   │   └── <video_id>_<sanitized_title>_raw.json
   │   └── livestreams/
   │       ├── <video_id>_<sanitized_title>.md
   │       └── <video_id>_<sanitized_title>_raw.json
   ├── catalog_video.md         # Master source of truth for regular videos
   └── catalog_livestream.md    # Master source of truth for livestreams (if channel has streams)
   ```
   - **Clean Channel Workspace Constraint**: Keep the channel root uncluttered containing strictly the official artifacts (`analysis/`, `raw-transcripts/`, and the master catalog files). Never leave internal work logs (`_jobs/`), synthesis scratchpads (`_synthesis/`), or stale backup files (`.bak-*`) inside the channel directory.

3. **Initialize Master Catalogs (Oldest = #1)**:
   Populate `catalog_video.md` and `catalog_livestream.md` starting from the oldest video as `#1` (no zero-padding like `001` unless requested) up to `#N`:
   ```markdown
   # Video Catalog: <Channel Name>

   - **Channel URL:** https://www.youtube.com/@<handle>/videos
   - **Total Videos:** <N>
   - **Transcription Status:** 0 Done, <N> Pending (#1 to #<N>)
   - **Analysis Status:** 0 Done, <N> Pending (#1 to #<N>)

   | No. | Video ID | Duration | Status | Title | Link |
   | :---: | :---: | :---: | :---: | :--- | :---: |
   | 1 | `<id>` | 15m 20s | ⏳ Queued | <Title> | [Watch](https://www.youtube.com/watch?v=<id>) |
   ```
   - **Catalog File Formatting & Clean Backup Policy**: Master catalog markdown files must strictly preserve Windows CRLF line endings (`\r\n`) across all modifications. Store any temporary pre-edit backup in a scratch directory and never leave `.bak-*` files inside the channel directory.

---

### Phase 2: Master Catalog as the Single Source of Truth
- Always read and track progress directly from the master catalogs (`catalog_video.md` / `catalog_livestream.md`, or existing localized catalog files inside legacy directories).
- Process items sequentially from the queue (`⏳ Queued` / `⏳ Pending`), and update both the header counters and the row status to `✅ **DONE**` only after verifying that the transcript, visual frames, and analysis report exist and pass all quality checks.

---

### Phase 3: Verbatim Audio Transcription & Bilingual Code-Switching
- Call `transcribe_youtube(url="https://www.youtube.com/watch?v=<id>", output_path=".../raw-transcripts/<type>/<id>_<sanitized_title>.md", glossary="...")`.
- The pipeline isolates the original audio track (rejecting AI auto-dubbing), applies a speech-clarity filter (`highpass=f=80,dynaudnorm=f=150:g=15:p=0.95`), and decodes to 16 kHz mono FLAC via SoX resampling.
- Automatically resolves Indonesian content from metadata even when YouTube mislabels the audio language as English.
- Extracts financial tickers (BTC, IHSG, FOMC), CamelCase brands (BlackRock, TradingView, Pump.fun), and domain keywords to prime Whisper Large V3 with style seeds and token-budgeted prompts (<600 chars).
- Applies deterministic phonetic normalizations (e.g., `"busai"` → `"Bursa Efek"`, `"PAMFAN"` → `"Pump.fun"`, `"Starling"` → `"Starlink"`) and filters silence/boilerplate hallucinations.
- Supports custom user lexicons via optional `~/.config/whis-tube/lexicon.json` or tool parameter `glossary="term1, term2"`.
- **Mandatory Full Read**: Always read the full `.md` transcript file before writing any analysis—never synthesize from memory or partial snippets.
- **Surgical HLS Slice Repair for Countdown Language-Drift**: If a long livestream drifts into wrong-language translation during opening countdown music, extract only the affected time window as FLAC via HLS seek, re-transcribe with pinned `language`, and splice back into the `.md` and `_raw.json` files.

---

### Phase 4: High-Resolution Visual Extraction & Ground-Truth Audit
- Whenever a transcript flags low confidence, mentions on-screen charts/slides, or contains silent B-roll gaps:
  ```python
  extract_keyframe(
      url="https://www.youtube.com/watch?v=<id>",
      timestamp="00:15:30",
      output_path=".../analysis/<type>/frames/<id>_001530.jpg",
      resolution=1080,
  )
  ```
- **Resolution & Naming Standard**: Prefer `resolution=1080` (Full HD 1920x1080) or minimum `720` (HD 1280x720) so small chart tickers and slide text remain crisp. Always name files `<video_id>_<HHMMSS>.jpg` inside `frames/`.
- **Visual Audit & Minimum Frame Density**: Extract at least 10 strategic keyframes per regular video (and proportionally more for multi-hour livestreams), inspect key exhibits with vision tools to confirm real on-screen figures, and remove any unused candidate frames so only embedded evidence remains on disk.
- **Mandatory Inline Embedding**: Embed every selected visual frame directly adjacent to its discussion inside the analysis Markdown report:
  ```markdown
  ![Visual Evidence Description](frames/<video_id>_001530.jpg)
  *Timestamp: 00:15:30*
  ```

---

### Phase 5: Analysis Report Standard & Anti-LaTeX Formatting
- Structure every report under `analysis/<type>/<slug>_vid_<num>_<id>.md` (or `_live_`) with:
  1. **Video Metadata** (Title, Channel, URL, Video ID, Duration, Model, Core Topics).
  2. **Executive Summary** (Content-driven, zero-bias synthesis).
  3. **Visual Evidence & Key Screenshots** (10+ inline 1080p frames with exact timestamps and factual visual context).
  4. **Deep Conceptual Deconstruction** (Detailed breakdown, diagrams/flows, real case studies, verified numbers from the verbatim transcript).
  5. **Technical Compliance Check** (Verify all frame paths exist on disk and zero LaTeX syntax appears).
- **Anti-LaTeX Constraint**: Never wrap monetary figures or mathematical expressions in LaTeX syntax (`$100`, `$$...$$`, `\approx`, `\rightarrow`, `\times`), which breaks rendering in Markdown viewers and messaging apps like Telegram. Always use plain text currency labels (`100 USD`, `Rp 100.000`) and standard Unicode symbols (`→`, `←`, `×`, `≈`, `≤`, `≥`, `%`).
- **Output Language Note**: Keep all repository code, technical configs, tool scripts, and operational docs in English; write the final analysis report prose in the language requested by the user.
