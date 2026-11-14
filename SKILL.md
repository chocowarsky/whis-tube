---
name: youtube-whisper
description: "Verbatim YouTube transcription (Whisper Large V3), 1080p keyframe intelligence, and autonomous channel research SOP."
version: 1.6.0
author: chocowarsky
license: MIT
metadata:
  tags: [YouTube, Whisper, Video, Speech-to-Text, Keyframe, Groq, FastMCP, Code-Switching, Channel-Research, Subagents]
---

# YouTube Whisper Intelligence Skill (SOP)

Standardized, autonomous end-to-end research pipeline for YouTube channels and long-form videos using lossless verbatim transcription via Groq Whisper Large V3, bilingual Indonesian-English code-switching enhancements, rapid HD/Full-HD keyframe extraction (720p/1080p) via HLS range-seek, deterministic catalog-driven workspace organization, and parallel sub-agent orchestration.

## When to Use This Skill

1. **Full-Channel Research from Scratch (Cold Start)**: When tasked with analyzing an entire YouTube channel, playlist, or video archive from zero—including automatic workspace setup, chronological cataloging, transcription, visual proof extraction, and structured analysis reports.
2. **Ad-Hoc / Single-Video Ingestion from New Channels**: When the user provides a single video URL from a channel not yet tracked in the workspace, immediately auto-detect the channel, scaffold the standard workspace directory tree, seed the master catalog, and process the video end-to-end without asking manual setup questions.
3. **Long-Form Video & Livestream Intelligence**: When analyzing videos or completed livestreams ranging from 10 minutes to multi-hour broadcasts (podcasts, market streams, technical presentations).
4. **Strict Verbatim Accuracy Requirements (Ground Truth)**: Never rely on YouTube's default auto-captions, which frequently censor terms, drop punctuation, misspell financial tickers, or omit critical numbers.
5. **Bilingual Indonesian-English Technical Content**: When transcribing Indonesian content discussing crypto, finance, programming, or tech where speakers mix English loanwords and terminology (code-switching).
6. **Visual Ground-Truth Verification (Charts, Slides, Code, Formulas)**: When speakers make visual references ("as seen on this chart", "looking at this slide") or pause for silent B-roll segments, trigger `extract_keyframe` at that exact timestamp and inspect it with vision tools.
7. **Large Historical Backlogs & Timeframe Re-Research**: When auditing, upgrading, or processing large backlogs of videos/streams (e.g. "research 3 bulan terakhir", 20+ items). Never shoulder high volumes sequentially in a single session; fan out across parallel sub-agents (`delegate_task`).

---

## MCP Tool Reference (`youtube-whisper`)

| Tool | Function | Key Arguments |
| :--- | :--- | :--- |
| `transcribe_youtube` | Full verbatim audio transcription with silence-detected smart chunking (<25MB) and bilingual code-switching | `url`, `output_path`, `language`, `glossary` |
| `extract_keyframe` | Ultra-fast native HD frame extraction (720p/1080p) via HLS seek in 4–7 seconds | `url`, `timestamp` (HH:MM:SS), `output_path`, `resolution` |
| `get_video_info` | Fast video metadata (title, channel, duration, live stream status) | `url` |
| `list_channel_videos` | Chronological video/livestream catalog (excluding Shorts <60s) from oldest to newest | `channel_url`, `limit`, `sort_order` |
| `check_groq_quota` | Real-time key pool health and cooldown monitoring | - |

## Key Management & Configuration

- **Canonical Codebase (`whis-tube`)**: All transcription, keyframe extraction, and channel catalog tooling lives exclusively in `~/Documents/whis-tube` (GitHub: `chocowarsky/whis-tube`) and runs via the `youtube-whisper` FastMCP server (`uv run --directory /home/warsky/Documents/whis-tube python -m whis_tube.server`). Never create, maintain, or fall back to ad-hoc CLI scripts in `~/Documents/hermes-trading/tools/`; keep `~/Documents/hermes-trading/` strictly for research domains (`youtube-research/`, `akademi-crypto/`, `market-research/`).
- **Key Pool File**: Stored at `~/.config/groq/keys.json` (`/home/warsky/.config/groq/keys.json`).
- **Format**: JSON array of string API keys (or objects with `key`/`api_key`). Pooled across 14 independent Groq organization accounts to multiply rate limits (7,200 audio seconds/hour and 28,800 audio seconds/day per key).
- **Registration**: Registered in `~/.hermes/config.yaml` under MCP server `youtube-whisper` via environment variable `GROQ_KEYS_PATH: /home/warsky/.config/groq/keys.json`.
- **Single-Key Fallback**: Core Hermes STT and single-key fallbacks read `GROQ_API_KEY` from `~/.hermes/.env` or profile-specific `.env` files.
- **Quota & Health**: Invoke `check_groq_quota` to inspect per-key cooldowns and remaining daily quotas.

---

## Autonomous Cold-Start Channel Research Workflow

If a user instructs you to research a YouTube channel from scratch (e.g., *"Research YouTube channel `@example` end-to-end"*), execute the following phases automatically without asking for manual setup instructions:

### Automatic Workspace Provisioning for Uncataloged Channels (Single-Video Ingest)

When the user shares a specific YouTube video link from a new creator or channel that does not yet exist in `<workspace_root>`:
1. **Auto-Detect Channel Identity**: Query video metadata via `get_video_info(url)` to resolve the canonical channel title and URL. Derive a clean URL-friendly kebab-case directory slug (e.g. `Ternak Uang` -> `ternak-uang`).
2. **Auto-Scaffold Workspace Hierarchy**: Immediately initialize the standardized directory tree under `youtube-research/<channel-slug>/`:
   - `analysis/videos/frames/` and `analysis/livestreams/frames/`
   - `raw-transcripts/videos/` and `raw-transcripts/livestreams/`
   - `catalog_video.md` and `catalog_livestream.md` (formatted with CRLF line endings `\r\n`).
3. **Seed Master Catalog**: Record the ingested video as Row #1 (`⏳ Queued` or `⏳ In Progress`) in `catalog_video.md` (or `catalog_livestream.md` if it was a stream), ensuring consistent tracking from day one.
4. **Execute Full Standard Pipeline**: Proceed seamlessly through verbatim transcription (`transcribe_youtube`), 1080p Full HD keyframe extraction (`extract_keyframe`), multimodal visual verification, comprehensive report authoring (`<slug>_vid_<num>_<video_id>_<sanitized_title>.md`), and flip catalog status to `✅ **SELESAI**`. Never reject an uncataloged link or ask for manual folder creation.

### Phase 1: Channel Enumeration & Workspace Blueprint
1. **Enumerate Both Uploads, Livestreams & Playlists**:
   - YouTube separates regular videos and live broadcasts into distinct tabs. Query both endpoints with a high limit (e.g., `limit=500`) and chronological ordering:
     - Regular videos: `list_channel_videos("https://www.youtube.com/@<handle>/videos", limit=500, sort_order="oldest_first")`
     - Livestreams: `list_channel_videos("https://www.youtube.com/@<handle>/streams", limit=500, sort_order="oldest_first")`
   - **Exhaustive Playlist Auditing**: In addition to `/videos` and `/streams`, inspect public playlists (`https://www.youtube.com/@<handle>/playlists`) to ensure dedicated educational series, unlisted community archives, or scholarship playlists are not missed.
   - **Strict YouTube Shorts Exclusion**: Shorts (<60s) are micro-content and are strictly excluded from all catalogs and pipelines.
   - **Identical Methodological Treatment**: Regular long-form videos and livestreams are functionally and structurally identical video assets—both require the exact same verbatim transcription, visual frame extraction, multimodal vision inspection, and deep analysis report quality.

2. **Initialize the Clean Channel Directory Tree**:
   Create the exact folder hierarchy under `<workspace_root>/<channel-slug>/`:
   ```text
   <channel-slug>/
   ├── analysis/
   │   ├── videos/
   │   │   ├── frames/          # Extracted HD/1080p keyframes (<video_id>_<HHMMSS>.jpg)
   │   │   └── <slug>_vid_<num>_<video_id>_<sanitized_title>.md
   │   └── livestreams/
   │       ├── frames/
   │       └── <slug>_live_<num>_<video_id>_<sanitized_title>.md
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

### Phase 2: Master Catalog Tracking & Parallel Subagent Orchestration
- **Single Source of Truth**: Always read and track progress directly from the master catalogs (`catalog_video.md` / `catalog_livestream.md`).
- **Parallel Subagent Fan-Out for Large Workloads (Max 2 Concurrent)**: Never attempt to process extensive video batches (>5 items) sequentially in a single turn, and never spawn more than 2 subagents concurrently (`max_concurrent_children: 2`). Spawning 5–8 parallel workers overloads the local 9Router gateway and model endpoints, triggering concurrency rejections, timeouts, and cascading failures. When tasked with backfilling, re-researching, or processing multi-month archives:
  1. Partition the queue into chronological chunks processed in waves of at most 2 concurrent subagents (e.g., 1 worker for videos + 1 worker for livestreams, or 2 chunk workers).
  2. Spawn isolated workers via `delegate_task(tasks=[...])` (maximum 2 tasks per active batch).
  3. Provide each sub-agent with a completely self-contained brief: workspace paths, exact video IDs/URLs, target output file paths, 1080p keyframe requirements (minimum 10 frames for videos; 12–16 frames for livestreams), inline markdown embed syntax, and the strict anti-LaTeX rule.
  4. The parent orchestrator maintains master catalog status, verifies deliverables on disk (transcripts, 1080p frames, analysis files), and prevents race conditions.
- **Auditing & Upgrading Existing Channel Workspaces**: When auditing existing workspaces against newer standards:
  - Detect uncataloged recent uploads (including same-day uploads) and reconcile playlist/tab inventories.
  - Verify raw transcript completeness (`.md` + `_raw.json`), word count, and absence of intro countdown language drift.
  - Audit embedded keyframe density (minimum 10 frames per video; 12–16 per livestream) and actual image dimensions via `ffprobe`/PIL (must be `1920x1080`; replace 720p/360p or corrupt frames).
  - Normalize any migrated Windows or foreign absolute paths (`C:\`, `C:/`) in headers or report links to local workspace-relative paths.
  - Confirm zero LaTeX syntax (`$`, `$$`, `\approx`, `\rightarrow`, `\times`, `\text{}`) and zero broken frame links.
  - Verify analysis report filenames include `<sanitized_title>` (`<slug>_vid_<num>_<video_id>_<sanitized_title>.md` / `<slug>_live_<num>_<video_id>_<sanitized_title>.md`).
  - Clean up unreferenced/orphan frames from `frames/` to keep storage lean.
- Update both header counters and row statuses to `✅ **DONE**` only after verifying that the transcript, visual frames, and analysis report exist and pass all quality checks.

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
- **Visual Audit & Minimum Frame Density**: Extract at least 10 strategic keyframes per regular video (and proportionally more for multi-hour livestreams, e.g. 12–16 frames), inspect key exhibits with vision tools to confirm real on-screen figures, and remove any unused candidate frames so only embedded evidence remains on disk.
- **Mandatory Inline Embedding**: Embed every selected visual frame directly adjacent to its discussion inside the analysis Markdown report:
  ```markdown
  ![Visual Evidence Description](frames/<video_id>_001530.jpg)
  *Timestamp: 00:15:30*
  ```

---

### Phase 5: Analysis Report Standard & Anti-LaTeX Formatting
- **Analysis Filename Standard**: Include the sanitized video title directly in every analysis report filename (matching the readability of `raw-transcripts/`):
  - Videos: `analysis/videos/<slug>_vid_<num>_<video_id>_<sanitized_title>.md`
  - Livestreams: `analysis/livestreams/<slug>_live_<num>_<video_id>_<sanitized_title>.md`
  - Sanitization rules: strip filesystem-unsafe characters (`/ \ : * ? " < > |`) and parentheses `()` (which break Hermes desktop `MEDIA:/` rendering), collapse consecutive whitespace, and cap title length at ~60–80 chars.
- Structure every report under `analysis/<type>/<slug>_vid_<num>_<video_id>_<sanitized_title>.md` (or `_live_`) with:
  1. **Video Metadata** (Title, Channel, URL, Video ID, Duration, Model, Core Topics).
  2. **Executive Summary** (Content-driven, zero-bias synthesis).
  3. **Visual Evidence & Key Screenshots** (10+ inline 1080p frames with exact timestamps and factual visual context).
  4. **Deep Conceptual Deconstruction** (Detailed breakdown, diagrams/flows, real case studies, verified numbers from the verbatim transcript).
  5. **Technical Compliance Check** (Verify all frame paths exist on disk and zero LaTeX syntax appears).
- **Anti-LaTeX Constraint**: Never wrap monetary figures or mathematical expressions in LaTeX syntax (`$100`, `$$...$$`, `\approx`, `\rightarrow`, `\times`), which breaks rendering in Markdown viewers and messaging apps like Telegram. Always use plain text currency labels (`100 USD`, `Rp 100.000`) and standard Unicode symbols (`→`, `←`, `×`, `≈`, `≤`, `≥`, `%`).
- **Output Language Note**: Keep all repository code, technical configs, tool scripts, and operational docs in English; write the final analysis report prose in the language requested by the user.
