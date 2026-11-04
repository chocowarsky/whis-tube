# whis-tube 🎙️📹

> **High-Fidelity YouTube Verbatim Transcription & Visual Keyframe Intelligence MCP Server**

`whis-tube` adalah Model Context Protocol (MCP) server berbasis Python yang dirancang untuk AI Coding Agents (Claude Code, Cursor, Windsurf, OpenBot, Hermes). Proyek ini menggabungkan **transkripsi audio verbatim lossless via Groq Whisper Large V3** dengan **ekstraksi keyframe HD (720p/1080p) super cepat** untuk verifikasi visual ground-truth.

---

## ✨ Fitur Unggulan

- **Transkripsi Verbatim (Bukan Auto-Caption):** Mengunduh trek audio original (menolak track auto-dubbing AI), decode satu kali ke FLAC 16 kHz mono (SoX resampler), dan mentranskripsi dengan presisi kata per kata.
- **Smart Silence-Detected Chunking (<25MB):** Otomatis mendeteksi jeda hening (*silence detection*) untuk memotong audio panjang (1–3+ jam) menjadi segmen ~10 menit. File selalu aman di bawah limit 25 MB Groq Free Plan.
- **Multi-Key Pool & 429 Failover:** Rotasi otomatis multi-key Groq API. Jika salah satu key menyentuh rate limit 429, sistem membaca header `retry-after`, menaruh key dalam status cooldown, dan langsung mengalihkan chunk berikutnya ke key lain.
- **Ekstraksi Keyframe Kilat (HLS Range-Seek):** Menarik tangkapan layar 720p atau 1080p pada timestamp detik tertentu dalam waktu 4–7 detik tanpa perlu mengunduh seluruh file video.
- **Agent SOP Ready (`SKILL.md`):** Disertai panduan metodologi riset untuk agen AI agar tidak membuat ringkasan dangkal (*lazy summary*).

---

## 🛠️ Persyaratan Sistem

- **Python:** `>= 3.10`
- **yt-dlp:** Tersedia di PATH sistem (`yt-dlp --version`)
- **ffmpeg & ffprobe:** Tersedia di PATH sistem (`ffmpeg -version`)
- **Groq API Key:** Dapatkan gratis di [console.groq.com](https://console.groq.com)

---

## 🚀 Cara Menjalankan (1 Perintah via `uv`)

Kamu bisa langsung menjalankan server MCP ini tanpa perlu instalasi rumit menggunakan `uv`:

```bash
# Jalankan langsung server MCP
uv run --directory . python -m whis_tube.server
```

Atau instal sebagai CLI package lokal:

```bash
uv pip install -e .
youtube-whisper
```

---

## 🔌 Konfigurasi MCP Client

### 1. Claude Desktop / Claude Code
Tambahkan konfigurasi berikut ke file konfigurasi Claude (`claude_desktop_config.json` atau `.claude.json`):

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

### 2. Multi-Key Pool (Rekomendasi untuk Riset Skala Besar)
Jika kamu memiliki beberapa API key Groq untuk mengatasi limit harian, buat file di `~/.config/groq/keys.json`:

```json
{
  "keys": [
    "gsk_key1...",
    "gsk_key2...",
    "gsk_key3..."
  ]
}
```

Server `youtube-whisper` akan secara otomatis memutar dan mengelola antrean cooldown dari semua key tersebut.

---

## 🧰 Tools yang Disediakan

| Nama Tool | Deskripsi | Argumen |
| :--- | :--- | :--- |
| `transcribe_youtube` | Transkripsi penuh audio video menjadi teks verbatim ber-timestamp (`.md` dan `_raw.json`). | `url` (str), `output_path` (str, opsional), `language` (str, opsional) |
| `extract_keyframe` | Mengambil screenshot HD native (720p / 1080p) pada detik tertentu via HLS seek. | `url` (str), `timestamp` (str, `HH:MM:SS`), `output_path` (str, opsional), `resolution` (int, default 720) |
| `get_video_info` | Mengambil informasi ringkas metadata video (judul, channel, durasi, status live). | `url` (str) |
| `list_channel_videos` | Katalog daftar video suatu channel, difilter tanpa Shorts, berurutan kronologis. | `channel_url` (str), `limit` (int, default 30), `sort_order` (str, `oldest_first`/`newest_first`) |
| `check_groq_quota` | Melihat status kesehatan dan cooldown pool API key Groq secara langsung. | *(tanpa argumen)* |

---

## 📂 Struktur Repositori

```text
whis-tube/
├── .mcp.json               # Konfigurasi bawaan MCP
├── .env.example            # Contoh variabel lingkungan
├── pyproject.toml          # Konfigurasi package & dependensi
├── SKILL.md                # Panduan instruksi untuk AI Agent
├── README.md               # Dokumentasi utama
└── src/
    └── whis_tube/
        ├── __init__.py     # Metadata package
        ├── __main__.py     # Entrypoint modul
        ├── server.py       # Definisi FastMCP & @mcp.tool()
        ├── audio.py        # Pipeline download, SoX FLAC, silence-detect & chunking
        ├── groq_pool.py    # Pool key Groq, failover 429 & Whisper API client
        ├── visual.py       # Range-seek HLS m3u8 frame grabber
        └── utils.py        # Formatter timestamp, ffprobe & channel parser
```

---

## 📄 Lisensi

Didistribusikan di bawah lisensi [MIT](LICENSE). Silakan gunakan dan modifikasi secara bebas untuk kebutuhan agen AI kamu.
