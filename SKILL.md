---
name: youtube-whisper
description: "Verbatim YouTube transcription (Whisper Large V3) and high-speed HD keyframe extraction pipeline for video intelligence."
version: 1.0.0
author: chocowarsky
license: MIT
metadata:
  tags: [YouTube, Whisper, Video, Speech-to-Text, Keyframe, Groq, FastMCP]
---

# YouTube Whisper Intelligence Skill

Pipeline standar untuk riset mendalam video YouTube menggunakan transkripsi verbatim (kata per kata) lossless via Groq Whisper Large V3 dan ekstraksi frame visual HD (720p/1080p) otomatis via HLS range-seek.

## Kapan Menggunakan Skill Ini

1. **Riset Video YouTube Berdurasi Panjang**: Saat pengguna meminta ringkasan, transkrip, atau analisis mendalam dari video 10 menit hingga beberapa jam (podcast, livestream, presentasi teknis).
2. **Kebutuhan Akurasi Verbatim (Ground Truth)**: Jangan pernah mengandalkan *auto-captions* bawaan YouTube yang sering memotong angka, menghilangkan tanda baca, atau salah mengeja ticker finansial dan istilah teknis.
3. **Verifikasi Visual (Charts, Slides, Formula)**: Saat transkrip merujuk pada visual ("lihat di chart ini", "seperti pada slide"), panggil tool `extract_keyframe` untuk menarik gambar HD di timestamp tersebut dan lakukan inspeksi vision.

---

## Daftar Tools MCP (`youtube-whisper`)

| Tool | Fungsi | Parameter Utama |
| :--- | :--- | :--- |
| `transcribe_youtube` | Transkripsi audio penuh verbatim dengan smart chunking (<25MB) | `url`, `output_path`, `language` |
| `extract_keyframe` | Ambil tangkapan layar HD (720p/1080p) dalam hitungan detik | `url`, `timestamp` (HH:MM:SS), `resolution` |
| `get_video_info` | Metadata video (judul, channel, durasi, status live) | `url` |
| `list_channel_videos` | Katalog video channel berurutan (exclude Shorts) | `channel_url`, `limit`, `sort_order` |
| `check_groq_quota` | Periksa ketersediaan key pool dan sisa waktu cooldown | - |

---

## Standar Kualitas & Prosedur Kerja

### 1. Transkripsi Audio (Zero-Shortcuts)
- Panggil `transcribe_youtube(url="<link>")`.
- Script otomatis memisahkan audio original (menghindari dubbing AI), decode ke FLAC mono 16 kHz (SoX resampler), memotong di titik jeda hening (*silence detection*), dan mentranskripsikannya ke Groq API.
- Output tersimpan dalam dua format:
  - File `.md`: Transkrip ber-timestamp rapi `[HH:MM:SS - HH:MM:SS]`.
  - File `_raw.json`: Data mentah segmen, kata per kata, dan flag *low_confidence*.

### 2. Validasi Visual & Ambiguitas
- Jika transkrip menandai adanya *low_confidence* atau pembicara merujuk grafik/tabel di layar:
  ```python
  extract_keyframe(url=url, timestamp="00:15:30", resolution=720)
  ```
- **Wajib Inline Embed**: Tempatkan gambar hasil ekstraksi langsung di laporan markdown:
  ```markdown
  ![Visual Frame: 00:15:30](frames/<video_id>_001530.jpg)
  *Tangkapan Layar: [00:15:30] - Grafik Harga & Indikator*
  ```

### 3. Katalog Channel Kronologis (Oldest to Newest)
- Saat menganalisis seluruh channel atau seri video:
  - Selalu mulai dari video debut/terlama (`#01 / #001`) ke yang terbaru (`#N`).
  - Filter keluar YouTube Shorts (<60 detik).
  - Gunakan `list_channel_videos(channel_url, sort_order="oldest_first")`.

### 4. Larangan Format LaTeX di Chat/Laporan
- Jangan membungkus angka uang atau formula matematika dalam sintaks LaTeX (`$100`, `\approx`, `\rightarrow`).
- Gunakan teks standar atau simbol Unicode:
  - Gunakan `100 USD` atau `Rp 100.000` (bukan `$100`).
  - Gunakan `→`, `×`, `≈`, `≤`, `≥`, `%`.
