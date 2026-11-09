<div align="center">

# whis-tube 🎙️📹

**Server MCP Transkripsi Verbatim YouTube Presisi Tinggi & Ekstraksi Keyframe Visual Cepat**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Groq Whisper Large V3](https://img.shields.io/badge/Whisper-Large%20V3-orange.svg)](https://console.groq.com)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)

🌐 **[English](README.md)** | **[Bahasa Indonesia](README.id.md)**

</div>

---

`whis-tube` adalah Model Context Protocol (MCP) server berbasis Python yang dirancang khusus untuk AI Coding Agents (Claude Code, Cursor, Windsurf, OpenBot, Hermes). Proyek ini memadukan **transkripsi audio verbatim lossless via Groq Whisper Large V3** dengan **ekstraksi keyframe visual HD (720p/1080p) super cepat** untuk validasi visual *ground-truth*.

---

## ✨ Fitur Unggulan

- **Transkripsi Verbatim Murni (Bukan Auto-Caption):** Mengunduh trek audio original (menolak track auto-dubbing AI), decode satu kali ke FLAC 16 kHz mono (filter kejernihan suara dan SoX resampler), dan mentranskripsi dengan presisi kata per kata tanpa sensor atau teks hilang.
- **Peningkatan Bilingual Code-Switching (Indonesia-Inggris):** Deteksi cerdas bahasa Indonesia, ekstraksi otomatis istilah teknis dan ticker (BTC, IHSG, BlackRock, TradingView), glosarium domain (crypto, finance, tech), normalisasi fonetik deterministik, dan pembersihan halusinasi boilerplate hening.
- **Smart Silence-Detected Chunking (<25MB):** Otomatis mendeteksi jeda hening (*silence detection*) untuk memotong audio panjang (1–3+ jam) menjadi segmen ~10 menit. File selalu aman di bawah limit 25 MB Groq Free Plan.
- **Multi-Key Pool & 429 Failover:** Rotasi otomatis multi-key Groq API. Jika salah satu key menyentuh rate limit 429, sistem membaca header `retry-after`, menaruh key dalam status cooldown, dan langsung mengalihkan chunk berikutnya ke key lain tanpa menghentikan proses.
- **Ekstraksi Keyframe Kilat (HLS Range-Seek):** Menarik tangkapan layar 720p atau 1080p pada timestamp detik tertentu dalam waktu 4–7 detik tanpa perlu mengunduh seluruh file video.
- **Agent SOP Ready (`SKILL.md`):** Disertai panduan metodologi riset untuk agen AI agar tidak membuat ringkasan dangkal (*lazy summary*), wajib inline screenshot, dan aturan anti-LaTeX.

---

## 🛠️ Persyaratan Sistem

- **Python:** `>= 3.10`
- **yt-dlp:** Tersedia di PATH sistem (`yt-dlp --version`)
- **ffmpeg & ffprobe:** Tersedia di PATH sistem (`ffmpeg -version`)
- **Groq API Key:** Dapatkan gratis di [console.groq.com](https://console.groq.com)

---

## 🚀 Cara Menjalankan (1 Perintah via `uv`)

Jalankan langsung server MCP tanpa perlu instalasi rumit:

```bash
# Jalankan server MCP langsung
uv run --directory . python -m whis_tube.server
```

Atau instal sebagai package lokal:

```bash
uv pip install -e .
youtube-whisper
```

---

## 🔌 Konfigurasi MCP Client

### 1. Claude Desktop / Claude Code / Cursor
Tambahkan konfigurasi berikut ke file pengaturan MCP kamu (misal: `claude_desktop_config.json` atau `.mcp.json`):

```json
{
  "mcpServers": {
    "youtube-whisper": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/whis-tube",
        "python",
        "-m",
        "whis_tube.server"
      ],
      "env": {
        "GROQ_API_KEY": "gsk_your_key_here"
      }
    }
  }
}
```

### 2. Multi-Key Pool (Rekomendasi Riset Skala Besar)
Jika kamu memiliki beberapa API key Groq gratisan untuk memperbesar kapasitas harian, simpan di `~/.config/groq/keys.json`:

```json
{
  "keys": [
    "gsk_key1...",
    "gsk_key2...",
    "gsk_key3..."
  ]
}
```

Server `youtube-whisper` otomatis mendeteksi file ini, memutar giliran key, dan menangani jeda cooldown secara transparan.

---

## 🧰 Tools yang Disediakan

| Nama Tool | Deskripsi | Parameter |
| :--- | :--- | :--- |
| `transcribe_youtube` | Unduh audio, chunking cerdas (<25MB), dan transkripsi verbatim lengkap dengan timestamp rapi (`.md` dan `_raw.json`) serta optimasi code-switching bilingual. | `url` (str), `output_path` (str, opsional), `language` (str, opsional), `glossary` (str, opsional) |
| `extract_keyframe` | Ambil screenshot HD native (720p / 1080p) pada detik tertentu via HLS seek range dalam 4–7 detik. | `url` (str), `timestamp` (str, `HH:MM:SS`), `output_path` (str, opsional), `resolution` (int, default 720) |
| `get_video_info` | Metadata ringkas video (judul, channel, durasi, status live). | `url` (str) |
| `list_channel_videos` | Katalog daftar video suatu channel berurutan (exclude Shorts) dari video terlama ke terbaru. | `channel_url` (str), `limit` (int, default 30), `sort_order` (str, `oldest_first`/`newest_first`) |
| `check_groq_quota` | Dashboard status kesehatan pool API key Groq, sisa kuota, dan waktu cooldown. | *(tanpa parameter)* |

---

## 📂 Struktur Repositori

```text
whis-tube/
├── .mcp.json               # Konfigurasi standar MCP
├── .env.example            # Template environment variables
├── pyproject.toml          # Dependensi & package metadata
├── SKILL.md                # Standar Operasional Prosedur (SOP) Agent (EN)
├── SKILL.id.md             # Standar Operasional Prosedur (SOP) Agent (ID)
├── README.md               # Dokumentasi Bahasa Inggris
├── README.id.md            # Dokumentasi Bahasa Indonesia
└── src/
    └── whis_tube/
        ├── __init__.py     # Metadata package
        ├── __main__.py     # CLI entrypoint
        ├── server.py       # FastMCP server & registrasi tools
        ├── audio.py        # Logika yt-dlp, SoX FLAC, filter suara & chunking
        ├── code_switch.py  # Ekstraksi glosarium, prompt bilingual & normalisasi fonetik
        ├── groq_pool.py    # Pool multi-key Groq & penanganan error 429
        ├── visual.py       # HLS range-seek frame grabber
        └── utils.py        # Utilitas format timestamp & channel parser
```

---

## 📄 Lisensi

Didistribusikan di bawah lisensi [MIT](LICENSE). Silakan gunakan dan kembangkan secara bebas!
