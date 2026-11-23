---
name: youtube-whisper
description: "Verbatim YouTube transcription (Whisper Large V3), 1080p keyframe intelligence, deterministic compliance auditing, and autonomous channel research SOP."
version: 1.7.0
author: chocowarsky
license: MIT
metadata:
  tags: [YouTube, Whisper, Video, Speech-to-Text, Keyframe, Groq, FastMCP, Code-Switching, Channel-Research, Subagents, Quality-Audit, Long-Run]
---

# YouTube Whisper Intelligence Skill (SOP)

Standardized, autonomous end-to-end research pipeline for YouTube channels and long-form videos using lossless verbatim transcription via Groq Whisper Large V3, bilingual Indonesian-English code-switching enhancements, rapid native 1080p keyframe extraction via HLS range-seek, deterministic CRLF workspace scaffolding, machine-verified report auditing, and parallel subagent orchestration.

This SOP is engineered to produce **consistent, exhaustive, zero-defect research reports across ALL agent tiers** — including fast/lightweight models (`Hydrogen`, `Flash`, smaller subagents) on multi-hour broadcasts.

---

## Non-Negotiable Execution Contract (Zero Shortcuts)

Every agent running this skill **MUST** follow all 7 rules below without exception:

1. **100% Full Transcript Read (Never Skim or Stop Early):** Check the total line count of the raw `.md` transcript (`wc -l`) and read **every single line from line 1 to EOF** in sequential chunks of at most `800` lines (`1–800`, `801–1600`, `1601–2400`, ...). Never write analysis from partial reads or memory.
2. **Progressive Block Notes on Long Runs (`>= 45 min` / `> 1,000 lines`):** As you read each transcript chunk, extract structured notes for **every 10–15 minute topical block** so details from the middle and final hours are never lost or compressed.
3. **Full Conversation Richness (Anti-Shallowness Standard):** Never flatten a rich discussion into vague generic bullets. For every topical block, explicitly preserve:
   - **Speaker Attribution & Dynamics:** Identify every speaker/host, their distinct thesis, debates, counter-arguments, concessions, and clarifying humor/context.
   - **Exact Ground-Truth Numbers:** Record exact prices, OHLC candles, percentages, basis points, ratios, valuations, dates, tickers, and timeframes.
   - **Case Studies, Anecdotes & Named Entities:** Capture every real-world example, personal story, analogy, paper/book citation, project/company/person name, warning, and caveat.
4. **Filter Whisper Hallucinations & Reconcile Visually:** Never quote flagged `possible_hallucination` / `prompt_echo` / `low_confidence` silence artifacts (such as repeated words `"Maksudnya, Maksudnya"`, `"Terima kasih."`, `"Sampai jumpa di episode berikutnya."`, `"Bersambung..."`, or echoed glossary lists) as real speech. Cross-check unfamiliar names, sites, or tickers against 1080p screenshots via `read_file` and explicitly note phonetic corrections (e.g., audio `"Trini Research"` → on-screen `"Citrini Research"`).
5. **Timeout-Safe Long Transcription (`>= 45 min` / `>= 2700s`):** MCP clients often enforce a 3-minute request timeout. For videos/livestreams `>= 45 min`, **run `./.venv/bin/whis-tube --transcribe ...` via a shell command (background task)** instead of a synchronous MCP call. If an MCP `transcribe_youtube` call times out at 3 minutes, **never blind-retry immediately** — check whether the output files are already written or wait cleanly (`whis-tube` uses a PID-aware per-video lock and chunk checkpoints so progress is preserved without duplicate quota burn).
6. **Mandatory 1080p Visual Inspection (`read_file`):** Extract keyframes in batches of `4–5` at `resolution=1080`. Call `read_file` on **every** extracted image to verify actual on-screen data. If a capture misses a screen share or chart by 10–20 seconds, re-extract at the exact timestamp and delete the missed candidate so zero orphan frames remain.
7. **Mandatory Deterministic Audit Gate (`audit_research_report`):** Never flip a catalog row to `✅ **SELESAI**` or `✅ **DONE**` until `audit_research_report` (or `./.venv/bin/whis-tube --audit-report`) returns `✅ **AUDIT PASSED**`. If it returns `❌ **AUDIT FAILED**`, fix every reported error and re-run until `PASS`.

---

## When to Use This Skill

1. **Ad-Hoc / Single-Video Ingestion from New or Existing Channels:** When the user shares a single YouTube video or livestream URL, immediately inspect metadata, auto-provision or update the standardized workspace under `youtube-research/<channel-slug>/`, and execute the full 7-step pipeline without asking manual setup questions.
2. **Full-Channel Research from Scratch (Cold Start):** When tasked with analyzing an entire YouTube channel, playlist, or video archive from zero—including chronological cataloging, transcription, visual proof extraction, and structured analysis reports.
3. **Long-Form Video & Livestream Intelligence:** Multi-hour podcasts, market broadcasts, livestreams, and technical deep-dives (`10 min` to `3+ hours`).
4. **Strict Verbatim Accuracy Requirements (Ground Truth):** Never rely on YouTube auto-captions, which censor terms, drop punctuation, misspell financial tickers, and omit critical numbers.
5. **Bilingual Indonesian-English Technical Content:** Indonesian discussions mixing English finance, crypto, software, AI, medical, gaming, or business terminology.
6. **Visual Ground-Truth Verification:** Charts, TradingView OHLC candles, dashboards, slides, code, formulas, and silent standby screens verified via native `1920x1080` frames.
7. **Large Historical Backlogs & Audits:** Multi-month backfills or workspace upgrades executed safely via parallel subagents (`max 2 concurrent`).

---

## Tool Reference (`youtube-whisper` MCP & Direct CLI)

Every tool is available both over MCP (`youtube-whisper`) and directly via `./.venv/bin/whis-tube`:

| MCP Tool | Direct CLI Flag | Function | Key Arguments |
| :--- | :--- | :--- | :--- |
| `get_video_info` | `--info URL` | Fast metadata + deterministic routing (`channel_slug`, `@handle`, `asset_type`, `sanitized_title`, long-run hint) | `url` |
| `check_groq_quota` | `--check-quota` | Real-time key pool health, cooldown timers, and binary readiness (`ffmpeg`, `ffprobe`, `yt-dlp`) | - |
| `scaffold_channel_workspace` | `--scaffold` | Deterministically creates `youtube-research/<slug>/` tree & updates CRLF (`\r\n`) master catalogs | `workspace_root`, `channel_name`, `channel_url`, `video_id`, `title`, `duration`, `asset_type`, `status` |
| `transcribe_youtube` | `--transcribe URL` | Verbatim Groq Whisper Large V3 transcription with silence chunking (`<25MB`), bilingual presets, prompt-echo detection & PID lock | `url`, `output_path`, `language`, `glossary`, `preset` |
| `extract_keyframe` | `--keyframe URL TS` | Ultra-fast native `1080p` (default) frame extraction via HLS seek returning relative `frames/` embed snippet | `url`, `timestamp`, `output_path`, `resolution` (default `1080`) |
| `audit_research_report` | `--audit-report PATH` | Hard PASS/FAIL gate verifying depth, 5 sections, timestamp span, zero `$`/LaTeX, 1:1 `1920x1080` frames, transcript parity & CRLF catalogs | `report_path`, `transcript_path`, `catalog_path`, `min_frames`, `min_words` |
| `list_channel_videos` | `--list-channel URL` | Chronological video/livestream catalog (excluding Shorts `<60s`) from oldest to newest | `channel_url`, `limit`, `sort_order` |

## Key Management & Configuration

- **Zero-Sudo Bootstrap (`bootstrap.py`):** If `ffmpeg`, `ffprobe`, `uv`, or `.venv` are missing, run `python3 bootstrap.py` from the `whis-tube` root without `sudo`. All binaries install rootlessly into `./.bin/` and `./.venv/`.
- **Canonical Codebase (`whis-tube`):** Runs via the `youtube-whisper` FastMCP server (`python3 bootstrap.py --serve` or `./.venv/bin/python -m whis_tube.server`) or directly via `./.venv/bin/whis-tube`.
- **Key Discovery Priority (Hot-Reloaded, Never Expose Raw Keys):**
  1. `<repo_root>/keys.json` (protected via `chmod 600`, `git --skip-worktree`, and `.git/hooks/pre-commit`)
  2. `<repo_root>/keys.local.json` and `<workspace>/keys.json`
  3. `GROQ_KEYS_PATH` environment variable
  4. `GROQ_API_KEY` environment variable / `.env`
  5. `~/.config/groq/keys.json` (global pooled fallback)
- **Antigravity Registration:** Installed automatically by `python3 bootstrap.py` into `~/.gemini/config/plugins/whis-tube` and `~/.gemini/config/mcp_config.json`.

---

## Deterministic 7-Step Single-Video Pipeline (State Machine)

Execute these exact steps in order whenever ingesting a video or livestream URL:

### Step 0 — Pre-Flight Metadata & Quota Check
1. Call `get_video_info(url)` and `check_groq_quota()`.
2. Read the exact returned fields — **never guess them**:
   - `Video ID`, `Title`, `Sanitized Title`, `Channel`, `Channel Handle / URL`, `Suggested Channel Slug`, `Asset Type` (`videos` or `livestreams`), `Duration`, and `Long-Run Hint`.
3. Confirm at least 1 active Groq key and `ffmpeg=OK, ffprobe=OK, yt-dlp=OK`.

### Step 1 — Deterministic Workspace Provisioning & Catalog Seeding (CRLF Enforced)
1. Call `scaffold_channel_workspace` (or `./.venv/bin/whis-tube --scaffold`) with:
   - `workspace_root`: `"<workspace_root>/youtube-research"`
   - `channel_name`, `channel_url`, `channel_slug`, `video_id`, `title`, `duration`, `asset_type`
   - `status`: `"⏳ In Progress"`
2. Use the exact returned `Transcript Target`, `Frames Directory`, `Analysis Report Target`, and `Catalog Row` number (`#1`, `#2`, ...).
   - **Never hand-edit CRLF catalogs with plain text tools** if `scaffold_channel_workspace` can update them cleanly with guaranteed `\r\n` endings.

### Step 2 — Verbatim Audio Transcription (Timeout-Safe for Long Streams)
1. Choose the timeout-safe execution mode based on `Duration`:
   - **Duration `< 45 min` (`< 2700s`):** Call MCP `transcribe_youtube(url=..., output_path=<Transcript Target>, preset="auto")`.
   - **Duration `>= 45 min` (`>= 2700s`):** Run the direct CLI command via shell so it never hits the 3-minute MCP client timeout:
     ```bash
     /path/to/whis-tube/.venv/bin/whis-tube --transcribe "https://www.youtube.com/watch?v=<id>" \
       --output "<Transcript Target>" --preset auto
     ```
2. Verify both `<id>_<sanitized_title>.md` and `<id>_<sanitized_title>_raw.json` exist on disk and are non-empty.
3. **Surgical HLS Slice Repair for Countdown Language-Drift:** If an opening countdown drifts into wrong-language translation (e.g., Welsh/English on an Indonesian stream), extract only the affected window as FLAC via HLS seek, re-transcribe with pinned `language="id"`, and splice back into `.md` and `_raw.json`.

### Step 3 — Mandatory 100% Full Transcript Read & Per-Block Detail Extraction
1. Count total lines (`wc -l <Transcript Target>`) and read **every line from 1 to EOF** in chunks of `<= 800` lines using `read_file`.
2. While reading each chunk, build a complete chronological outline covering **every 10–15 minute block**:
   - Exact timestamp range (`HH:MM:SS - HH:MM:SS`)
   - Every speaker's name/role, thesis, arguments, disagreements, and takeaways
   - Every exact number, price level, OHLC value, percentage, date, ticker, metric, and ratio
   - Every named person, company, protocol, book/paper, case study, and personal anecdote
   - Every visual cue (`"share screen"`, `"chart"`, `"slide"`, `"lihat"`, `"dashboard"`, `"grafik"`) and every flagged `Low-Confidence / prompt_echo` timestamp requiring visual verification.
3. Discard flagged silence/prompt-echo hallucinations (`Maksudnya, Maksudnya`, `Terima kasih.`, `Sampai jumpa...`, echoed glossary lists) — never quote them as real spoken facts.

### Step 4 — Batch 1080p Keyframe Extraction & Mandatory Multimodal Inspection
1. Select strategic timestamps meeting the **Proportional Depth Matrix** below (covering standby/intro, speaker layout, every on-screen chart/slide/dashboard/website, key low-confidence segments, major topic pivots, and closing).
2. Extract keyframes in **small batches of 4–5 calls** via `extract_keyframe(url=..., timestamp="HH:MM:SS", output_path="<Frames Dir>/<id>_<HHMMSS>.jpg", resolution=1080)`.
3. Inspect **EVERY extracted image** using `read_file`:
   - Read exact numbers, tickers, URLs, titles, OHLC values, dates, and labels directly from the `1920x1080` pixels.
   - Reconcile any phonetic transcription errors against visual ground truth (note corrections transparently in the report).
   - If a screen share appeared 10–20s earlier or later than the extracted timestamp, re-extract at the exact visible moment and **delete the unused candidate `.jpg`** immediately so zero orphan frames remain.

### Step 5 — Author Exhaustive 5-Section Analysis Report (Strict Anti-LaTeX)
Write the complete analysis report to `<Analysis Report Target>` (`<slug>_(vid|live)_<num>_<video_id>_<sanitized_title>.md`) following the **Proportional Depth Matrix** and **Report Blueprint** below.

### Step 6 — Mandatory Deterministic Compliance Gate (`audit_research_report`)
1. Run `audit_research_report(report_path="<Analysis Report Target>")` (or `./.venv/bin/whis-tube --audit-report "<Analysis Report Target>"`).
2. If the audit returns `❌ **AUDIT FAILED**`:
   - Fix **every** reported error (shallow word count, missing late-video timestamps, `$`/LaTeX occurrences, absolute paths, sub-1080p frames, missing/orphan frames, CRLF violations, or workspace clutter).
   - Re-run `audit_research_report` until it returns `✅ **AUDIT PASSED**`.

### Step 7 — Finalize Master Catalog (CRLF Preserved) & Verify
1. Call `scaffold_channel_workspace` with the same channel/video parameters and `status="✅ **SELESAI**"` (for Indonesian reports) or `status="✅ **DONE**"` (for English reports) to atomically update the row status and `Done / Pending` header counters while strictly preserving Windows CRLF (`\r\n`).
2. Re-run `audit_research_report(report_path="<Analysis Report Target>")` one final time to confirm `✅ **AUDIT PASSED**` with clean catalog CRLF and zero leftover scratch files.

---

## Proportional Depth & Visual Density Matrix

Never produce a short, superficial summary for a long video. Match or exceed every floor below:

| Video / Stream Duration | Min `1920x1080` Frames | Min `###` Chronological Subsections | Min Report Word Count | Chronological Span Required |
| :--- | :---: | :---: | :---: | :--- |
| **Short (`< 20 min`)** | `10` frames | `>= 3` subsections | `>= 800` words | Opening (`<= 25%`) → Closing (`>= 75%`) |
| **Standard (`20–45 min`)** | `10` frames | `>= 4` subsections | `>= 1,200` words | Opening (`<= 25%`) → Closing (`>= 75%`) |
| **Long (`45–90 min` or livestream)** | `12–16` frames | `>= 6` subsections | `>= 1,800` words | Opening (`<= 25%`) → Closing (`>= 75%`) |
| **Multi-Hour (`>= 90 min`)** | `14–16+` frames | `>= 7` subsections (1 per ~10–15m block) | `>= 2,400` words | Opening (`<= 25%`) → Closing (`>= 75%`) |

---

## Analysis Report Blueprint & Anti-LaTeX Standard

- **Analysis Filename Standard:**
  - Videos: `analysis/videos/<slug>_vid_<num>_<video_id>_<sanitized_title>.md`
  - Livestreams: `analysis/livestreams/<slug>_live_<num>_<video_id>_<sanitized_title>.md`
  - Sanitization: strip `/ \ : * ? " < > | . ()`, collapse spaces to `_`, cap at 80 chars.
- **Required 5-Section Structure:**
  1. **`## 1. Video Metadata`**: Title, Channel & All Speakers/Hosts, Canonical URL, Video ID, Upload Date, Duration (noting any intro standby/countdown range), Transcription Engine (`whisper-large-v3`), Bilingual Code-Switching stats (presets, glossary terms, phonetic corrections), Audio Source & Preprocessing, Transcript Statistics (segments, words, low-confidence count), **relative link** to raw transcript (`[raw-transcripts/<type>/<id>_<sanitized_title>.md](../../raw-transcripts/<type>/<id>_<sanitized_title>.md)`), and Core Topics.
  2. **`## 2. Executive Summary`**: Content-driven, zero-bias synthesis organized into numbered high-signal points, each citing exact timestamp ranges (`HH:MM:SS - HH:MM:SS`), named speakers, and verified figures.
  3. **`## 3. Visual Evidence & Key Screenshots`**: Markdown inventory table listing every extracted `1920x1080` frame (`No.`, `Timestamp`, `Resolution`, `File Frame`, `Visual Context & Ground-Truth Verification`).
  4. **`## 4. Deep Conceptual Deconstruction`**: Chronological `### 4.1.`, `### 4.2.`, ... subsections covering the entire broadcast from start to finish:
     - Embed every selected visual frame **directly adjacent** to its discussion using relative paths:
       ```markdown
       ![Descriptive visual caption with verified numbers](frames/<video_id>_001530.jpg)
       *Timestamp: 00:15:30*
       ```
     - Explicitly attribute viewpoints by speaker name, record exact chart OHLC/prices/metrics, preserve real case studies/anecdotes/debates, and document visual corrections of phonetic errors or low-confidence gaps.
  5. **`## 5. Technical Compliance Check`**: Checklist confirming verbatim transcript completeness (`.md` + `_raw.json`), 100% full transcript line read, `1920x1080` frame density & `read_file` visual inspection, 1:1 inline relative embedding with zero orphans, CRLF catalog check, and strict Anti-LaTeX compliance.
- **Strict Anti-LaTeX Constraint (Zero Tolerance):**
  - **NEVER** write a single `$` character anywhere in the report (`$100`, `$60,715`, `$$...$$`) and **NEVER** use LaTeX macros (`\approx`, `\rightarrow`, `\leftarrow`, `\times`, `\text{}`, `\frac`).
  - Always use plain-text currency (`100 USD`, `60.715 USD`, `Rp 100.000`) and standard Unicode symbols (`→`, `←`, `×`, `≈`, `≤`, `≥`, `–`, `%`).
- **Output Language Note:** Keep all repository code, configs, tool scripts, and operational docs in English; write the final analysis report prose in the language requested by the user (or matching the video's primary language, e.g., Indonesian for Indonesian broadcasts).

---

## Full-Channel Cold-Start & Parallel Subagent Orchestration

### Channel Enumeration & Clean Directory Blueprint
1. **Enumerate Uploads, Livestreams & Playlists:**
   - Regular videos: `list_channel_videos("https://www.youtube.com/@<handle>/videos", limit=500, sort_order="oldest_first")`
   - Livestreams: `list_channel_videos("https://www.youtube.com/@<handle>/streams", limit=500, sort_order="oldest_first")`
   - Public playlists: inspect `https://www.youtube.com/@<handle>/playlists` so unlisted series/archives are not missed.
   - **Strict Shorts Exclusion:** Videos `<= 60s` are strictly excluded from all catalogs and pipelines.
   - **Identical Quality Standard:** Regular videos and livestreams receive the exact same verbatim transcription, 1080p visual inspection, deep analysis depth, and `audit_research_report` gate.
2. **Standardized Clean Directory Hierarchy (`youtube-research/<channel-slug>/`):**
   ```text
   <channel-slug>/
   ├── analysis/
   │   ├── videos/
   │   │   ├── frames/          # Native 1920x1080 keyframes (<video_id>_<HHMMSS>.jpg)
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
   ├── catalog_video.md         # Master CRLF (\r\n) source of truth for regular videos
   └── catalog_livestream.md    # Master CRLF (\r\n) source of truth for livestreams
   ```
   - **Zero Workspace Clutter:** Keep `<channel-slug>/` strictly clean—never leave `_jobs/`, `_synthesis/`, `.tmp`, or `.bak-*` files inside the channel directory.

### Parallel Subagent Fan-Out (Max 2 Concurrent)
- **Single Source of Truth:** Always track progress in `catalog_video.md` / `catalog_livestream.md`.
- **Large Batches (`> 5 items`):** Never shoulder 10–50+ videos sequentially in a single turn, and **never spawn more than 2 subagents concurrently**:
  1. Partition the queue into chronological chunks processed in waves of at most 2 concurrent workers via `invoke_subagent` (in Antigravity) or `delegate_task`.
  2. Give each subagent a self-contained brief: exact workspace paths, video IDs/URLs, target paths, CLI `--transcribe` rule for `>=45m` streams, 1080p frame minimums, Anti-LaTeX rule, and mandatory `audit_research_report` pass requirement.
  3. The parent orchestrator updates master catalogs via `scaffold_channel_workspace` (preventing CRLF corruption and write races) and verifies `✅ **AUDIT PASSED**` for every deliverable.
- **Auditing Existing Workspaces:** Run `audit_research_report` across every existing report to catch missing titles in filenames, sub-1080p frames, orphan frames, foreign paths (`C:\`, `/home/`), LaTeX `$` leaks, shallow depth, or LF catalog corruption.
