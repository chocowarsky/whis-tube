"""Unit & compliance tests for whis-tube v1.3.0 (stdlib unittest + pytest compatible)."""

from __future__ import annotations

import inspect
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from whis_tube.audio import _acquire_video_lock, _load_fresh_completed_result, _resolve_confined_path
from whis_tube.audit import (
    _find_missing_sections,
    _parse_catalog_rows,
    audit_research_report,
    format_audit_result,
    scaffold_channel_workspace,
)
from whis_tube.code_switch import is_hallucination_segment, is_prompt_echo_segment
from whis_tube.utils import (
    classify_asset_type,
    format_catalog_duration,
    sanitize_filename,
    slugify_channel,
)
from whis_tube.visual import extract_keyframe, format_markdown_embed


class TestUtilsAndVisual(unittest.TestCase):
    def test_slugify_and_sanitize(self) -> None:
        self.assertEqual(slugify_channel("Micro Macro"), "micro-macro")
        self.assertEqual(slugify_channel("@Ternak Uang!"), "ternak-uang")
        self.assertEqual(
            sanitize_filename("Mic Mac Liveshow - Episode 4 (Live)"),
            "Mic_Mac_Liveshow_-_Episode_4_Live",
        )

    def test_classify_asset_type_and_duration(self) -> None:
        self.assertEqual(classify_asset_type("was_live"), "livestreams")
        self.assertEqual(classify_asset_type("not_live"), "videos")
        self.assertEqual(classify_asset_type(None), "videos")
        self.assertEqual(format_catalog_duration(6886), "1h 54m 46s")
        self.assertEqual(format_catalog_duration(920), "15m 20s")

    def test_visual_defaults_and_relative_embed(self) -> None:
        sig = inspect.signature(extract_keyframe)
        self.assertEqual(sig.parameters["resolution"].default, 1080)

        abs_frame = pathlib.Path("/home/user/youtube-research/micro-macro/analysis/livestreams/frames/MxyOhuzQsVY_001045.jpg")
        embed = format_markdown_embed(abs_frame, "00:10:45")
        self.assertEqual(
            embed,
            "![Visual Evidence: 00:10:45](frames/MxyOhuzQsVY_001045.jpg)\n*Timestamp: 00:10:45*",
        )
        self.assertNotIn("/home/", embed)


class TestHallucinationAndPromptEcho(unittest.TestCase):
    def test_punctuation_insensitive_repetition(self) -> None:
        self.assertTrue(is_hallucination_segment({"text": "Maksudnya, Maksudnya, Maksudnya,"}))
        self.assertTrue(is_hallucination_segment({"text": "Mucur, Mucur, Mucur, Mucur."}))
        self.assertTrue(is_hallucination_segment({"text": "ETH, ETH, ETH, ETH, BNB"}))
        self.assertTrue(is_hallucination_segment({"text": "Sampai jumpa di episode berikutnya."}))
        self.assertTrue(is_hallucination_segment({"text": "Bersambung..."}))

    def test_low_conf_cta_vs_real_speech(self) -> None:
        low_cta = {
            "text": "Jangan lupa subscribe, like, share, dan komen.",
            "no_speech_prob": 0.55,
            "avg_logprob": -0.9,
        }
        self.assertTrue(is_hallucination_segment(low_cta))

        real_speech = {
            "text": "Gimana guys porto kalian merah atau hijau, jangan lupa like share dan subscribe ya",
            "no_speech_prob": 0.05,
            "avg_logprob": -0.25,
        }
        self.assertFalse(is_hallucination_segment(real_speech))

    def test_prompt_echo_detection(self) -> None:
        terms = ["Mic", "Mac", "Liveshow", "BNB", "ETH", "FOMC", "Solana", "CPI", "public equity", "dividend yield"]
        seed = "Pembahasan market structure, public equity, valuation, cash flow, balance sheet, dividend yield."
        echo_seg = {
            "text": "Pembahasan market structure public equity price action dividend yield balance sheet BNB ETH FOMC Solana CPI",
            "no_speech_prob": 0.45,
            "avg_logprob": -0.85,
        }
        self.assertTrue(is_prompt_echo_segment(echo_seg, terms, style_seed=seed))

        normal_seg = {
            "text": "Menurut saya Bitcoin masih konsolidasi di atas 60 ribu sambil nunggu keputusan FOMC bulan depan.",
            "no_speech_prob": 0.04,
            "avg_logprob": -0.22,
        }
        self.assertFalse(is_prompt_echo_segment(normal_seg, terms, style_seed=seed))


class TestLockingAndScaffoldAndAudit(unittest.TestCase):
    def test_stale_lock_recovery_and_fresh_result_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tpath = pathlib.Path(tmp)
            out_md = tpath / "abc12345678_Test.md"
            raw_json = tpath / "abc12345678_Test_raw.json"
            out_md.write_text("# Test\n", encoding="utf-8")
            raw_json.write_text(
                json.dumps({
                    "info": {"id": "abc12345678", "title": "Test", "duration": 120, "channel": "Ch", "language": "id"},
                    "pipeline": {"code_switch": {"active_presets": ["tech"], "glossary_terms_count": 5, "phonetic_corrections_count": 1}},
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Halo dunia", "flags": []}],
                }),
                encoding="utf-8",
            )
            with mock.patch("whis_tube.audio.SCRATCH_DIR", tpath):
                locks_dir = tpath / "locks"
                locks_dir.mkdir()
                stale_lock = locks_dir / "abc12345678.lock"
                stale_lock.write_text(json.dumps({"pid": 99999999, "started_at": 1.0}), encoding="utf-8")
                lock_path, waited = _acquire_video_lock("abc12345678", wait_timeout_s=5.0)
                try:
                    self.assertFalse(waited)
                    self.assertTrue(lock_path.exists())
                finally:
                    lock_path.unlink(missing_ok=True)

            loaded = _load_fresh_completed_result(out_md, raw_json, {"id": "abc12345678"}, t0=0.0)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["total_segments"], 1)
            self.assertEqual(loaded["total_words"], 2)

    def _build_valid_workspace(self, root: pathlib.Path, vid: str = "MxyOhuzQsVY", duration_s: int = 1800) -> pathlib.Path:
        sc = scaffold_channel_workspace(
            workspace_root=str(root),
            channel_name="Micro Macro",
            channel_url="https://www.youtube.com/@MicMacLiveshow",
            video_id=vid,
            title="Test Episode 1",
            duration=str(duration_s),
            asset_type="videos",
            status="⏳ In Progress",
        )
        t_md = pathlib.Path(sc["recommended_transcript_path"])
        t_json = t_md.with_name(t_md.stem + "_raw.json")
        t_md.write_text("# Test Episode 1\n\n**[00:00:10 - 00:00:20]** Halo.\n", encoding="utf-8")
        t_json.write_text(
            json.dumps({"info": {"id": vid, "duration": duration_s}, "segments": []}),
            encoding="utf-8",
        )

        frames_dir = pathlib.Path(sc["recommended_frames_dir"])
        frame_names = [f"{vid}_00{i:02d}00.jpg" for i in range(1, 11)]
        for fn in frame_names:
            (frames_dir / fn).write_bytes(b"fake-jpg-bytes")

        body_blocks = []
        timestamps = [
            "00:01:00", "00:04:00", "00:08:00", "00:12:00", "00:16:00",
            "00:19:00", "00:22:00", "00:25:00", "00:27:00", "00:29:00",
        ]
        filler = " ".join(["Analisis mendalam percakapan pembicara angka metrik studi kasus dan verifikasi visual"] * 18)
        for idx, (fn, ts) in enumerate(zip(frame_names, timestamps), 1):
            body_blocks.append(
                f"### 4.{idx}. Segmen Pembahasan {idx} ({ts})\n\n"
                f"![Visual Evidence {idx}](frames/{fn})\n"
                f"*Timestamp: {ts}*\n\n"
                f"- **Pembicara:** {filler} dengan target 60.000 USD dan pertumbuhan 15%.\n"
            )

        report_text = (
            "# Analisis Video: Test Episode 1\n\n"
            "## 1. Video Metadata\n\n"
            f"- **Video ID:** `{vid}`\n"
            "- **Durasi:** 00:30:00\n"
            f"- **File Transkrip Mentah:** [raw-transcripts/videos/{t_md.name}](../../raw-transcripts/videos/{t_md.name})\n\n"
            "## 2. Executive Summary\n\nRingkasan lengkap dari 00:01:00 sampai 00:29:00.\n\n"
            "## 3. Visual Evidence & Key Screenshots\n\nTabel bukti visual 1920×1080.\n\n"
            "## 4. Deep Conceptual Deconstruction\n\n"
            + "\n".join(body_blocks)
            + "\n## 5. Technical Compliance Check\n\n- [x] Semua terpenuhi.\n"
        )
        rpath = pathlib.Path(sc["recommended_analysis_path"])
        rpath.write_text(report_text, encoding="utf-8")
        return rpath

    def test_scaffold_crlf_and_audit_pass_and_fail_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            rpath = self._build_valid_workspace(root)

            # Verify CRLF on catalogs and idempotent status flip
            cat_video = root / "micro-macro" / "catalog_video.md"
            raw = cat_video.read_bytes()
            self.assertIn(b"\r\n", raw)
            self.assertEqual(raw.replace(b"\r\n", b"").count(b"\n"), 0)

            scaffold_channel_workspace(
                workspace_root=str(root),
                channel_name="Micro Macro",
                channel_url="https://www.youtube.com/@MicMacLiveshow",
                video_id="MxyOhuzQsVY",
                title="Test Episode 1",
                duration="1800",
                asset_type="videos",
                status="✅ **SELESAI**",
            )
            updated_cat = cat_video.read_text(encoding="utf-8")
            self.assertIn("1 Done, 0 Pending (#1 to #1)", updated_cat)
            self.assertIn("✅ **SELESAI**", updated_cat)

            with mock.patch("whis_tube.audit._probe_image_dimensions", return_value=(1920, 1080)):
                res = audit_research_report(str(rpath))
                self.assertTrue(res["passed"], format_audit_result(res))

                # 1. Fail on '$' LaTeX leak
                bad_text = rpath.read_text(encoding="utf-8") + "\nHarga $60,715 dan \\approx 5%.\n"
                rpath.write_text(bad_text, encoding="utf-8")
                res_latex = audit_research_report(str(rpath))
                self.assertFalse(res_latex["passed"])
                self.assertTrue(any("Anti-LaTeX" in e for e in res_latex["errors"]))

                # 2. Fail on orphan frame on disk
                orphan = rpath.parent / "frames" / "MxyOhuzQsVY_009999.jpg"
                orphan.write_bytes(b"orphan")
                res_orphan = audit_research_report(str(rpath))
                self.assertTrue(any("Orphan" in e for e in res_orphan["errors"]))
                orphan.unlink()

            # 3. Fail on 720p frames
            with mock.patch("whis_tube.audit._probe_image_dimensions", return_value=(1280, 720)):
                res_720 = audit_research_report(str(rpath))
                self.assertFalse(res_720["passed"])
                self.assertTrue(any("Sub-1080p" in e for e in res_720["errors"]))

            # 4. Fail on LF-corrupted catalog
            cat_video.write_bytes(cat_video.read_bytes().replace(b"\r\n", b"\n"))
            with mock.patch("whis_tube.audit._probe_image_dimensions", return_value=(1920, 1080)):
                res_lf = audit_research_report(str(rpath))
                self.assertTrue(any("CRLF violation" in e for e in res_lf["errors"]))

    def test_confined_path_and_linear_parsers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            valid = _resolve_confined_path(base, "MxyOhuzQsVY_Test.md")
            self.assertEqual(valid, (base / "MxyOhuzQsVY_Test.md").resolve())

            for bad in ("../evil.md", "../../etc/passwd", "/etc/passwd", "sub/file.md", "..\\evil.md", ".", "..", ""):
                with self.assertRaises(ValueError):
                    _resolve_confined_path(base, bad)

        catalog_sample = (
            "# Video Catalog: Test\r\n\r\n"
            "| No. | Video ID | Duration | Status | Title | Link |\r\n"
            "| :---: | :---: | :---: | :---: | :--- | :---: |\r\n"
            "| 1 | `MxyOhuzQsVY` | 1h 54m 46s | ✅ **SELESAI** | Mic Mac Ep 4 | [Watch](https://www.youtube.com/watch?v=MxyOhuzQsVY) |\r\n"
            "| invalid | `bad` | 1m | ⏳ | Not numeric | [Watch](https://example.com) |\r\n"
        )
        rows = _parse_catalog_rows(catalog_sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_id"], "MxyOhuzQsVY")
        self.assertEqual(rows[0]["num"], "1")

        full_headings = [
            "## 1. Video Metadata",
            "## 2. Executive Summary",
            "## 3. Visual Evidence & Key Screenshots",
            "## 4. Deep Conceptual Deconstruction",
            "## 5. Technical Compliance Check",
        ]
        self.assertEqual(_find_missing_sections(full_headings), [])
        self.assertEqual(
            _find_missing_sections(["## 1. Metadata", "### 4.1. Executive Summary Only"]),
            ["Executive Summary", "Visual Evidence", "Deep Conceptual Deconstruction", "Technical Compliance Check"],
        )


if __name__ == "__main__":
    unittest.main()
