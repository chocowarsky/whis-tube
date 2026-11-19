#!/usr/bin/env python3
"""Zero-sudo self-healing bootstrap & launcher for whis-tube.

Uses ONLY Python standard library modules so any AI agent or developer can run:
    python3 bootstrap.py
without sudo, apt, brew, pip, or interactive prompts.

Modes:
    python3 bootstrap.py            # Install/repair local binaries, venv, key vault & MCP config
    python3 bootstrap.py --doctor   # Inspect binary, Python env, key pool & MCP readiness
    python3 bootstrap.py --serve    # Silently ensure runtime is ready, then launch MCP stdio server
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from typing import Dict, List, Optional, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent
BIN_DIR = REPO_ROOT / ".bin"
VENV_DIR = REPO_ROOT / ".venv"
LOCAL_BIN = pathlib.Path.home() / ".local" / "bin"

PLACEHOLDER_TOKENS = ("PASTE", "YOUR", "EXAMPLE", "PLACEHOLDER", "HERE", "XXXX", "REDACT", "<", ">")


def _exe_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


def _venv_python() -> pathlib.Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _log(msg: str, quiet: bool = False, force: bool = False) -> None:
    if quiet and not force:
        return
    print(f"[whis-tube:bootstrap] {msg}", file=sys.stderr, flush=True)


def _is_valid_groq_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    k = key.strip()
    if not k.startswith("gsk_") or len(k) < 30:
        return False
    upper = k.upper()
    return not any(tok in upper for tok in PLACEHOLDER_TOKENS)


def _prepend_path(directory: pathlib.Path) -> None:
    if not directory.is_dir():
        return
    dir_str = str(directory)
    cur = os.environ.get("PATH", "")
    parts = cur.split(os.pathsep) if cur else []
    if dir_str not in parts:
        os.environ["PATH"] = f"{dir_str}{os.pathsep}{cur}" if cur else dir_str


def is_working_binary(path_or_name: str | pathlib.Path, version_arg: str = "--version") -> Optional[pathlib.Path]:
    """Return resolved Path if executable exists (not a broken symlink) and passes version check."""
    raw = str(path_or_name)
    candidates: List[pathlib.Path] = []

    if isinstance(path_or_name, pathlib.Path) or os.sep in raw or (os.altsep and os.altsep in raw):
        candidates.append(pathlib.Path(raw))
    else:
        local_bin_candidate = BIN_DIR / _exe_name(raw)
        if local_bin_candidate.exists():
            candidates.append(local_bin_candidate)
        found = shutil.which(raw)
        if found:
            candidates.append(pathlib.Path(found))

    for cand in candidates:
        try:
            if not cand.exists() or not cand.is_file():
                continue
            if os.name != "nt" and not os.access(cand, os.X_OK):
                continue
            res = subprocess.run(
                [str(cand), version_arg],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode == 0:
                return cand.resolve()
        except Exception:
            continue
    return None


def _sync_local_bin_symlink(binary_path: pathlib.Path, name: str) -> None:
    """Ensure ~/.local/bin/<name> points to binary_path if missing, broken, or managed by .bin."""
    if os.name == "nt":
        return
    try:
        LOCAL_BIN.mkdir(parents=True, exist_ok=True)
        link_path = LOCAL_BIN / name
        if link_path.is_symlink():
            if not link_path.exists():
                link_path.unlink()
            else:
                try:
                    resolved = link_path.resolve()
                    if resolved == binary_path.resolve():
                        return
                    if BIN_DIR.resolve() in resolved.parents:
                        link_path.unlink()
                    else:
                        return  # Preserve user's working non-whis-tube binary
                except OSError:
                    link_path.unlink()
        elif link_path.exists():
            return
        link_path.symlink_to(binary_path)
    except OSError as exc:
        _log(f"Warning: could not update {LOCAL_BIN / name}: {exc}", force=True)


def _download_file(url: str, dest: pathlib.Path, quiet: bool = False) -> None:
    _log(f"Downloading {url} ...", quiet=quiet)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "whis-tube-bootstrap/1.2 (+https://github.com/chocowarsky/whis-tube)"},
    )
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, length=1024 * 256)
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _safe_extract_tar(archive: pathlib.Path, dest_dir: pathlib.Path) -> None:
    dest_resolved = dest_dir.resolve()
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            target = (dest_dir / member.name).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise RuntimeError(f"Unsafe tar member path detected: {member.name}")
        tf.extractall(dest_dir)


def _safe_extract_zip(archive: pathlib.Path, dest_dir: pathlib.Path) -> None:
    dest_resolved = dest_dir.resolve()
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            target = (dest_dir / info.filename).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise RuntimeError(f"Unsafe zip member path detected: {info.filename}")
        zf.extractall(dest_dir)


def _extract_binaries_from_tree(
    search_root: pathlib.Path,
    binary_names: List[str],
    dest_dir: pathlib.Path,
) -> Dict[str, pathlib.Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    found: Dict[str, pathlib.Path] = {}
    targets = {_exe_name(n): n for n in binary_names}
    for item in search_root.rglob("*"):
        if item.is_file() and item.name in targets:
            logical_name = targets[item.name]
            if logical_name in found:
                continue
            target_path = dest_dir / item.name
            tmp_path = target_path.with_suffix(".tmp")
            shutil.copy2(item, tmp_path)
            if os.name != "nt":
                os.chmod(tmp_path, 0o755)
            os.replace(tmp_path, target_path)
            found[logical_name] = target_path
    return found


def _uv_download_urls() -> List[str]:
    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    if sys_name == "linux":
        if machine in ("x86_64", "amd64"):
            return ["https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-musl.tar.gz"]
        if machine in ("aarch64", "arm64"):
            return ["https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-unknown-linux-musl.tar.gz"]
    elif sys_name == "darwin":
        if machine in ("arm64", "aarch64"):
            return ["https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz"]
        return ["https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-apple-darwin.tar.gz"]
    elif sys_name == "windows":
        if machine in ("arm64", "aarch64"):
            return ["https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-pc-windows-msvc.zip"]
        return ["https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"]
    raise RuntimeError(f"Unsupported platform for automatic uv download: {sys_name}/{machine}")


def ensure_uv(quiet: bool = False) -> pathlib.Path:
    """Ensure standalone uv & uvx exist without sudo."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    _prepend_path(BIN_DIR)

    local_uv = BIN_DIR / _exe_name("uv")
    local_uvx = BIN_DIR / _exe_name("uvx")
    existing = is_working_binary(local_uv, "--version") or is_working_binary("uv", "--version")
    if existing:
        if local_uv.exists():
            _sync_local_bin_symlink(local_uv, "uv")
        if local_uvx.exists():
            _sync_local_bin_symlink(local_uvx, "uvx")
        return existing

    _log("uv missing or broken; installing standalone uv into .bin/ (zero-sudo)...", quiet=quiet)
    last_err: Optional[Exception] = None
    for url in _uv_download_urls():
        try:
            with tempfile.TemporaryDirectory(prefix="whis_uv_") as tmpdir:
                tmp_root = pathlib.Path(tmpdir)
                archive = tmp_root / pathlib.Path(url).name
                _download_file(url, archive, quiet=quiet)
                extract_dir = tmp_root / "extracted"
                extract_dir.mkdir()
                if archive.name.endswith(".zip"):
                    _safe_extract_zip(archive, extract_dir)
                else:
                    _safe_extract_tar(archive, extract_dir)
                installed = _extract_binaries_from_tree(extract_dir, ["uv", "uvx"], BIN_DIR)
                if "uv" not in installed:
                    raise RuntimeError("uv binary missing from downloaded archive")
                _sync_local_bin_symlink(installed["uv"], "uv")
                if "uvx" in installed:
                    _sync_local_bin_symlink(installed["uvx"], "uvx")
                verified = is_working_binary(installed["uv"], "--version")
                if not verified:
                    raise RuntimeError("Downloaded uv binary failed self-check")
                _log(f"uv ready at {verified}", quiet=quiet)
                return verified
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"Failed to install uv automatically: {last_err}")


def _ffmpeg_download_plans() -> List[Tuple[str, Optional[str]]]:
    """Return candidate (ffmpeg_or_bundle_url, optional_ffprobe_url) pairs by OS/arch."""
    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    if sys_name == "linux":
        if machine in ("x86_64", "amd64"):
            return [
                ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz", None),
                ("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz", None),
            ]
        if machine in ("aarch64", "arm64"):
            return [
                ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz", None),
                ("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz", None),
            ]
    elif sys_name == "darwin":
        return [
            ("https://evermeet.cx/ffmpeg/getrelease/zip", "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"),
        ]
    elif sys_name == "windows":
        return [
            ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip", None),
        ]
    raise RuntimeError(f"Unsupported platform for automatic static ffmpeg download: {sys_name}/{machine}")


def ensure_ffmpeg(quiet: bool = False) -> Tuple[pathlib.Path, pathlib.Path]:
    """Ensure working static ffmpeg & ffprobe binaries exist without sudo."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    _prepend_path(BIN_DIR)

    local_ffmpeg = BIN_DIR / _exe_name("ffmpeg")
    local_ffprobe = BIN_DIR / _exe_name("ffprobe")
    ff = is_working_binary(local_ffmpeg, "-version") or is_working_binary("ffmpeg", "-version")
    fp = is_working_binary(local_ffprobe, "-version") or is_working_binary("ffprobe", "-version")
    if ff and fp:
        if local_ffmpeg.exists():
            _sync_local_bin_symlink(local_ffmpeg, "ffmpeg")
        if local_ffprobe.exists():
            _sync_local_bin_symlink(local_ffprobe, "ffprobe")
        return ff, fp

    _log("ffmpeg/ffprobe missing or broken; installing static build into .bin/ (zero-sudo)...", quiet=quiet)
    last_err: Optional[Exception] = None
    for primary_url, secondary_url in _ffmpeg_download_plans():
        try:
            with tempfile.TemporaryDirectory(prefix="whis_ffmpeg_") as tmpdir:
                tmp_root = pathlib.Path(tmpdir)
                extract_dir = tmp_root / "extracted"
                extract_dir.mkdir()

                def _fetch_and_extract(url: str, label: str) -> None:
                    ext = ".zip" if url.endswith(".zip") or url.endswith("/zip") else ".tar.xz"
                    archive = tmp_root / f"{label}{ext}"
                    _download_file(url, archive, quiet=quiet)
                    if ext == ".zip":
                        _safe_extract_zip(archive, extract_dir)
                    else:
                        _safe_extract_tar(archive, extract_dir)

                _fetch_and_extract(primary_url, "ffmpeg_bundle")
                if secondary_url:
                    _fetch_and_extract(secondary_url, "ffprobe_bundle")

                installed = _extract_binaries_from_tree(extract_dir, ["ffmpeg", "ffprobe"], BIN_DIR)
                if "ffmpeg" not in installed or "ffprobe" not in installed:
                    raise RuntimeError("Archive did not contain both ffmpeg and ffprobe executables")

                _sync_local_bin_symlink(installed["ffmpeg"], "ffmpeg")
                _sync_local_bin_symlink(installed["ffprobe"], "ffprobe")

                ff_ok = is_working_binary(installed["ffmpeg"], "-version")
                fp_ok = is_working_binary(installed["ffprobe"], "-version")
                if not (ff_ok and fp_ok):
                    raise RuntimeError("Downloaded ffmpeg/ffprobe failed verification")

                _log(f"ffmpeg ready at {ff_ok}", quiet=quiet)
                return ff_ok, fp_ok
        except Exception as exc:
            last_err = exc
            _log(f"Mirror failed ({exc}); trying fallback if available...", quiet=quiet)

    raise RuntimeError(f"Failed to install ffmpeg/ffprobe automatically: {last_err}")


def _venv_ready(venv_py: pathlib.Path) -> bool:
    if not venv_py.exists():
        return False
    probe = subprocess.run(
        [
            str(venv_py),
            "-c",
            "import mcp, yt_dlp, requests, dotenv, pydantic, whis_tube",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return probe.returncode == 0


def ensure_venv(uv_path: pathlib.Path, quiet: bool = False) -> pathlib.Path:
    """Ensure local .venv exists with all dependencies installed."""
    venv_py = _venv_python()
    if _venv_ready(venv_py):
        return venv_py

    _log("Syncing Python dependencies into .venv via uv...", quiet=quiet)
    out_stream = sys.stderr if quiet else None
    commands = [
        [str(uv_path), "sync", "--directory", str(REPO_ROOT)],
        [str(uv_path), "sync", "--directory", str(REPO_ROOT), "--python", "3.12"],
    ]
    last_rc = 1
    for cmd in commands:
        res = subprocess.run(cmd, stdout=out_stream, stderr=out_stream, check=False)
        last_rc = res.returncode
        if last_rc == 0 and _venv_ready(venv_py):
            _log(f"Python environment ready at {venv_py}", quiet=quiet)
            return venv_py

    raise RuntimeError(f"uv sync failed (exit code {last_rc})")


def ensure_keys_protection(quiet: bool = False) -> pathlib.Path:
    """Create local keys.json template if missing and enforce chmod 600 + git leak guards."""
    keys_path = REPO_ROOT / "keys.json"
    example_path = REPO_ROOT / "keys.example.json"

    if not keys_path.exists():
        if example_path.exists():
            shutil.copy2(example_path, keys_path)
        else:
            keys_path.write_text(
                json.dumps(
                    {
                        "_instructions": (
                            "Paste your Groq API key(s) in the 'keys' list below "
                            "(get free keys at https://console.groq.com/keys) and save."
                        ),
                        "keys": [
                            "gsk_PASTE_YOUR_GROQ_API_KEY_1_HERE",
                            "gsk_PASTE_YOUR_GROQ_API_KEY_2_HERE",
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        _log(f"Created local key vault template at {keys_path}", quiet=quiet)

    if os.name != "nt":
        try:
            os.chmod(keys_path, 0o600)
        except OSError:
            pass

    git_dir = REPO_ROOT / ".git"
    if git_dir.is_dir() and shutil.which("git"):
        tracked = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", "keys.json"],
            capture_output=True,
            check=False,
        )
        if tracked.returncode == 0:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "update-index", "--skip-worktree", "keys.json"],
                capture_output=True,
                check=False,
            )

        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        pre_commit = hooks_dir / "pre-commit"
        hook_script = """#!/usr/bin/env python3
import re, subprocess, sys

PLACEHOLDERS = ("PASTE", "YOUR", "EXAMPLE", "PLACEHOLDER", "HERE", "XXXX", "REDACT", "<", ">")
KEY_RE = re.compile(r"gsk_[A-Za-z0-9_-]{25,}")

files = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
    capture_output=True, text=True, check=False
).stdout.splitlines()

leaked = []
for path in files:
    blob = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True, text=True, errors="ignore", check=False
    ).stdout
    for match in KEY_RE.findall(blob):
        upper = match.upper()
        if not any(tok in upper for tok in PLACEHOLDERS):
            leaked.append(path)
            break

if leaked:
    print("ERROR: Commit blocked by whis-tube secret guard.", file=sys.stderr)
    print("Real Groq API key(s) detected in staged file(s): " + ", ".join(leaked), file=sys.stderr)
    print("Keep real keys in local keys.json (skip-worktree) or ~/.config/groq/keys.json.", file=sys.stderr)
    sys.exit(1)
"""
        pre_commit.write_text(hook_script, encoding="utf-8")
        if os.name != "nt":
            os.chmod(pre_commit, 0o755)

    return keys_path


def register_mcp_configs(venv_python: pathlib.Path, quiet: bool = False) -> List[str]:
    """Register whis-tube MCP server & Antigravity plugin if Antigravity (~/.gemini) is present."""
    updated: List[str] = []
    gemini_root = pathlib.Path.home() / ".gemini"
    if not gemini_root.exists():
        return updated
    gemini_cfg_dir = gemini_root / "config"
    gemini_cfg_dir.mkdir(parents=True, exist_ok=True)

    # 1. Global Antigravity mcp_config.json
    mcp_cfg_path = gemini_cfg_dir / "mcp_config.json"
    data: Dict[str, object] = {}
    if mcp_cfg_path.exists():
        raw = mcp_cfg_path.read_text(encoding="utf-8").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = {}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers

    servers["youtube-whisper"] = {
        "command": str(venv_python),
        "args": ["-m", "whis_tube.server"],
    }
    tmp_cfg = mcp_cfg_path.with_suffix(".json.tmp")
    tmp_cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_cfg, mcp_cfg_path)
    updated.append(str(mcp_cfg_path))

    # 2. Antigravity plugin folder (~/.gemini/config/plugins/whis-tube)
    plugin_dst = gemini_cfg_dir / "plugins" / "whis-tube"
    plugin_dst.mkdir(parents=True, exist_ok=True)
    for fname in ("plugin.json", "README.md"):
        src = REPO_ROOT / fname
        if src.is_file():
            shutil.copy2(src, plugin_dst / fname)
    for dname in ("assets", "skills"):
        src_dir = REPO_ROOT / dname
        if src_dir.is_dir():
            shutil.copytree(src_dir, plugin_dst / dname, dirs_exist_ok=True)

    plugin_mcp = {
        "mcpServers": {
            "youtube-whisper": {
                "command": str(venv_python),
                "args": ["-m", "whis_tube.server"],
            }
        }
    }
    (plugin_dst / "mcp_config.json").write_text(json.dumps(plugin_mcp, indent=2) + "\n", encoding="utf-8")
    updated.append(str(plugin_dst))
    _log(f"Registered Antigravity MCP & plugin: {', '.join(updated)}", quiet=quiet)
    return updated


def _inspect_key_sources() -> Tuple[int, List[str]]:
    sources: List[str] = []
    seen_keys: set[str] = set()

    def _scan_json(path: pathlib.Path, label: str) -> None:
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_list = payload.get("keys", []) if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
            added = 0
            for entry in raw_list:
                val = entry if isinstance(entry, str) else (
                    (entry.get("key") or entry.get("api_key") or "") if isinstance(entry, dict) else ""
                )
                k = val.strip()
                if _is_valid_groq_key(k) and k not in seen_keys:
                    seen_keys.add(k)
                    added += 1
            if added:
                sources.append(f"{label} ({added})")
        except Exception:
            pass

    _scan_json(REPO_ROOT / "keys.json", "./keys.json")
    _scan_json(REPO_ROOT / "keys.local.json", "./keys.local.json")
    env_keys_path = os.environ.get("GROQ_KEYS_PATH", "").strip()
    if env_keys_path:
        _scan_json(pathlib.Path(env_keys_path).expanduser(), f"GROQ_KEYS_PATH")
    _scan_json(pathlib.Path.home() / ".config" / "groq" / "keys.json", "~/.config/groq/keys.json")

    env_val = os.environ.get("GROQ_API_KEY", "").strip()
    if env_val:
        added_env = 0
        for part in env_val.split(","):
            k = part.strip()
            if _is_valid_groq_key(k) and k not in seen_keys:
                seen_keys.add(k)
                added_env += 1
        if added_env:
            sources.append(f"GROQ_API_KEY ({added_env})")

    return len(seen_keys), sources


def run_doctor(print_report: bool = True) -> int:
    _prepend_path(BIN_DIR)
    _prepend_path(VENV_DIR / ("Scripts" if os.name == "nt" else "bin"))

    uv_p = is_working_binary("uv", "--version")
    ff_p = is_working_binary("ffmpeg", "-version")
    fp_p = is_working_binary("ffprobe", "-version")
    venv_py = _venv_python()
    venv_ok = _venv_ready(venv_py)
    yt_ok = False
    if venv_ok:
        yt_probe = subprocess.run([str(venv_py), "-m", "yt_dlp", "--version"], capture_output=True, text=True, check=False)
        yt_ok = yt_probe.returncode == 0
    key_count, key_sources = _inspect_key_sources()

    all_deps_ok = bool(uv_p and ff_p and fp_p and venv_ok and yt_ok)
    if print_report:
        print("=== whis-tube Doctor ===")
        print(f"Repo Root : {REPO_ROOT}")
        print(f"uv        : {uv_p or 'MISSING'}")
        print(f"ffmpeg    : {ff_p or 'MISSING'}")
        print(f"ffprobe   : {fp_p or 'MISSING'}")
        print(f".venv     : {venv_py if venv_ok else 'NOT READY'}")
        print(f"yt-dlp    : {'OK (python -m yt_dlp)' if yt_ok else 'MISSING'}")
        print(f"Local keys: {REPO_ROOT / 'keys.json'} (exists={(REPO_ROOT / 'keys.json').exists()})")
        if key_count:
            print(f"Groq keys : {key_count} active key(s) from {', '.join(key_sources)}")
        else:
            print(f"Groq keys : 0 active keys -> open {REPO_ROOT / 'keys.json'} and paste your gsk_... key(s)")
    return 0 if all_deps_ok else 1


def ensure_all(quiet: bool = False, register: bool = True) -> pathlib.Path:
    uv_path = ensure_uv(quiet=quiet)
    ensure_ffmpeg(quiet=quiet)
    venv_python = ensure_venv(uv_path, quiet=quiet)
    ensure_keys_protection(quiet=quiet)
    if register:
        register_mcp_configs(venv_python, quiet=quiet)
    return venv_python


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-sudo bootstrap & launcher for whis-tube.")
    parser.add_argument("--serve", action="store_true", help="Ensure runtime quietly and exec MCP stdio server.")
    parser.add_argument("--doctor", action="store_true", help="Inspect installation and Groq key readiness.")
    parser.add_argument("--no-register", action="store_true", help="Skip Antigravity ~/.gemini/config registration.")
    args = parser.parse_args()

    if args.doctor:
        sys.exit(run_doctor(print_report=True))

    if args.serve:
        venv_python = ensure_all(quiet=True, register=False)
        _prepend_path(BIN_DIR)
        _prepend_path(venv_python.parent)
        cmd = [str(venv_python), "-m", "whis_tube.server"]
        if os.name == "nt":
            sys.exit(subprocess.run(cmd, check=False).returncode)
        os.execv(str(venv_python), cmd)

    ensure_all(quiet=False, register=not args.no_register)
    code = run_doctor(print_report=True)
    if code == 0:
        print("\nSetup complete! Paste your Groq API key(s) in keys.json (if not already configured) and you're ready.")
    sys.exit(code)


if __name__ == "__main__":
    main()
