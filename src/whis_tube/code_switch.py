"""Universal Bilingual Code-Switching & Custom Preset Module for whis-tube.

Provides:
- Smart language resolution for code-switched Indonesian content.
- Universal domain presets (tech, finance, crypto, medical, gaming, business) + neutral default.
- Hot-reloaded custom presets and phonetic rules via lexicon.json discovery.
- Metadata term extraction (tickers, CamelCase brands, proper nouns, chapters).
- Token-budgeted prompt builder with hallucination-filtered rolling tail.
- Hallucination segment detector & deterministic phonetic normalizer.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .runtime import REPO_ROOT

logger = logging.getLogger("whis-tube.code_switch")

_KEY_TRIGGERS = "triggers"
_KEY_STYLE_SEED = "style_seed"
_KEY_GLOSSARY = "glossary"
_KEY_PHONETIC = "phonetic_rules"
_KEY_PRESETS = "presets"
_KEY_ENABLED_PRESETS = "enabled_presets"
_KEY_DEFAULT_PRESET = "default_preset"
_KEY_DEFAULT_SEED = "default_style_seed_id"
_KEY_CUSTOM_GLOSSARY = "custom_glossary"

_SCHEMA_KEYS: Set[str] = {
    _KEY_DEFAULT_PRESET,
    _KEY_ENABLED_PRESETS,
    _KEY_DEFAULT_SEED,
    _KEY_CUSTOM_GLOSSARY,
    _KEY_PHONETIC,
    _KEY_PRESETS,
}

# Indonesian function and high-signal vocabulary markers
INDONESIAN_MARKERS: Set[str] = {
    "cara", "mencari", "ngerti", "dalam", "menit", "untuk", "pemula", "ini", "itu",
    "dan", "di", "ke", "dari", "yang", "bisa", "dengan", "akan", "pada", "adalah",
    "sebagai", "oleh", "sudah", "belum", "juga", "kita", "kamu", "saya", "mereka",
    "kami", "apa", "kenapa", "bagaimana", "karena", "kalo", "kalau", "biar", "bukan",
    "saja", "jadi", "saat", "waktu", "belajar", "tutorial", "pembahasan", "membahas",
    "analisis", "pasar", "saham", "uang", "cuan", "rugi", "untung", "koin", "teman",
    "semua", "selamat", "datang", "hari", "pergerakan", "membaca", "didukung", "didanai",
    "banyak", "kemarin", "besok", "lalu", "beli", "jual", "terima", "kasih", "menonton",
    "gue", "gua", "kalian", "gimana", "nggak", "gak", "udah", "banget", "bikin", "bahas",
    "rupiah", "apakah", "atau", "tapi", "menuju",
}

# Neutral bilingual style seed used when no specific domain preset is active
DEFAULT_STYLE_SEED_ID: str = (
    "Pembahasan mendalam mengenai framework, workflow, best practice, "
    "case study, benchmark, update fitur, serta analisis data dan insight utama."
)
BILINGUAL_STYLE_SEED_ID: str = DEFAULT_STYLE_SEED_ID

# Universal built-in domain presets (fully customizable/extensible via lexicon.json)
DOMAIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "tech": {
        _KEY_TRIGGERS: [
            "ai", "tech", "teknologi", "coding", "software", "programming", "developer",
            "llm", "mcp", "cloud", "server", "linux", "python", "javascript", "api",
            "starlink", "hardware", "gadget",
        ],
        _KEY_STYLE_SEED: (
            "Pembahasan software engineering, system architecture, API integration, "
            "LLM workflow, deployment pipeline, benchmark latency, serta update open-source "
            "dan cloud infrastructure."
        ),
        _KEY_GLOSSARY: [
            "AI", "machine learning", "LLM", "API", "MCP", "Anthropic", "backend", "frontend",
            "database", "cloud", "deployment", "open-source", "framework", "latency",
            "pipeline", "Docker", "Kubernetes", "GitHub", "Python", "TypeScript", "Starlink",
        ],
        _KEY_PHONETIC: {
            r"\bStarling\b": "Starlink",
            r"\b(?:antrofic|antropik)\b": "Anthropic",
            r"\bopen\s+ei\s+ai\b": "OpenAI",
            r"\bget\s*hab\b": "GitHub",
        },
    },
    "finance": {
        _KEY_TRIGGERS: [
            "saham", "ihsg", "market", "fed", "fomc", "cpi", "investor", "keuangan",
            "finansial", "ekonomi", "obligasi", "reksadana", "dividen", "dividend",
            "ipo", "macro", "makro", "suku bunga",
        ],
        _KEY_STYLE_SEED: (
            "Pembahasan market structure, public equity, valuation, cash flow, "
            "balance sheet, dividend yield, serta update macroeconomic The Fed, CPI, "
            "FOMC, dan interest rate."
        ),
        _KEY_GLOSSARY: [
            "IHSG", "The Fed", "FOMC", "CPI", "inflasi", "interest rate", "rate hike",
            "basis points", "US Treasury", "dividend", "yield", "Bursa Efek", "IPO",
            "market cap", "cash flow", "balance sheet", "public equity", "valuation",
            "reksadana", "obligasi", "BlackRock", "iShares", "Goldman Sachs", "JP Morgan",
            "Ray Dalio", "SRI-KEHATI",
        ],
        _KEY_PHONETIC: {
            r"\bbusai\s+fed\b": "Bursa Efek",
            r"\bbursa\s+efed\b": "Bursa Efek",
            r"\bbusai\b": "Bursa Efek",
            r"\bGoldman\s+Sax\b": "Goldman Sachs",
            r"\bjp\s+morgen\b": "JP Morgan",
            r"\bpablik\s+ekuiti\b": "public equity",
            r"\bvelue\s+investing\b": "value investing",
            r"\braning\s+tred\b": "running trade",
            r"\bmarket\s+kap\b": "market cap",
            r"\b(?:kash|kes)\s+flow\b": "cash flow",
            r"\bblakrok\b": "BlackRock",
            r"\bblekrok\b": "BlackRock",
            r"\bthe\s+fed\b": "The Fed",
            r"\bfomce\b": "FOMC",
            r"\bsepiai\b": "CPI",
            r"\bserika\s+hati\b": "SRI-KEHATI",
            r"\bstan\s+drakenmiller\b": "Stanley Druckenmiller",
            r"\b(?:redalio|kary\s+dalu)\b": "Ray Dalio",
            r"\btelt\b": "TLT",
            r"\b(?:rate\s+high|red\s+hike)\b": "rate hike",
        },
    },
    "crypto": {
        _KEY_TRIGGERS: [
            "crypto", "kripto", "bitcoin", "btc", "eth", "ethereum", "solana",
            "altcoin", "memecoin", "defi", "web3", "blockchain", "on-chain",
            "halving", "airdrop",
        ],
        _KEY_STYLE_SEED: (
            "Pembahasan market structure, price action, liquidity, support resistance, "
            "risk management, on-chain flow, funding rate, open interest, serta update "
            "Bitcoin, altcoin, dan DeFi."
        ),
        _KEY_GLOSSARY: [
            "BTC", "ETH", "Solana", "XRP", "BNB", "Bittensor", "TAO", "NEAR Protocol",
            "altcoin", "memecoin", "stablecoin", "altseason",
            "halving", "spot ETF", "margin call", "liquidation", "funding rate",
            "open interest", "order block", "fair value gap", "FVG", "support",
            "resistance", "breakout", "retest", "pullback", "divergence", "Fibonacci",
            "liquidity", "bullish", "bearish", "whale", "on-chain", "MVRV", "SOPR",
            "BTC.D", "USDT.D", "DXY", "airdrop", "staking", "DEX", "CEX",
            "smart contract", "pump", "dump", "DeFi", "Web3", "tokenomics",
            "Pump.fun", "LayerZero", "Arbitrum", "Sui", "Aptos", "Ondo", "Pendle",
            "Hyperliquid", "TradingView", "CoinMarketCap", "CoinGlass",
        ],
        _KEY_PHONETIC: {
            r"\b(?:pam\s*fan|pump\s*fund)\b": "Pump.fun",
            r"\bsmart\s+kontrak\b": "smart contract",
            r"\bkat\s+loss\b": "cut loss",
            r"\btek\s+profit\b": "take profit",
            r"\btrading\s*viu\b": "TradingView",
            r"\bbitkoin\b": "Bitcoin",
            r"\biterium\b": "Ethereum",
            r"\b(?:marjin|margin)\s+kol\b": "margin call",
            r"\blikuiditi\b": "liquidity",
            r"\b(?:fanding|funding)\s+(?:ret|red)\b": "funding rate",
            r"\bopen\s+interes\b": "open interest",
            r"\border\s+blok\b": "order block",
            r"\b(?:fer|fair)\s+(?:velue|value)\s+gep\b": "fair value gap",
            r"\b(?:halping|hafling)\b": "halving",
            r"\balt\s*sisen\b": "altseason",
            r"\b(?:stebel|stabel)\s*koin\b": "stablecoin",
            r"\b(?:mim|mem)\s*koin\b": "memecoin",
            r"\balt\s*koin\b": "altcoin",
            r"\b(?:brek\s*aut|break\s*aut)\b": "breakout",
            r"\b(?:ri\s*tes|rites)\b": "retest",
            r"\b(?:pul\s*bek|pull\s*bek)\b": "pullback",
            r"\bsaport\b": "support",
            r"\bresisten\b": "resistance",
            r"\b(?:bulis|bullis)\b": "bullish",
            r"\b(?:beris|bearis)\b": "bearish",
            r"\bon\s+chen\b": "on-chain",
            r"\b(?:koin\s*glas|coinglas)\b": "CoinGlass",
            r"\bkoin\s+market\s+kap\b": "CoinMarketCap",
            r"\bsolanah\b": "Solana",
            r"\bbit\s*(?:&|and)\s*source\b": "Bittensor",
            r"\bnir\s+protocol\b": "NEAR Protocol",
        },
    },
    "medical": {
        _KEY_TRIGGERS: [
            "medis", "dokter", "kesehatan", "klinik", "penyakit", "terapi",
            "farmasi", "anatomi", "diagnosa", "diagnosis", "pasien", "nutrisi",
            "kedokteran", "biologi",
        ],
        _KEY_STYLE_SEED: (
            "Pembahasan clinical evidence, diagnosis, biomarker, metabolic health, "
            "cardiovascular risk, dosage guideline, serta studi medis dan mekanisme fisiologis."
        ),
        _KEY_GLOSSARY: [
            "diagnosis", "prognosis", "biomarker", "placebo", "meta-analysis",
            "randomized controlled trial", "RCT", "insulin resistance", "cardiovascular",
            "cholesterol", "LDL", "HDL", "hypertension", "autoimmune", "antibiotic",
            "dosage", "side effect", "clinical trial",
        ],
        _KEY_PHONETIC: {
            r"\bplasebo\b": "placebo",
            r"\bkardioveskular\b": "cardiovascular",
            r"\binsulin\s+resisten\b": "insulin resistance",
        },
    },
    "gaming": {
        _KEY_TRIGGERS: [
            "game", "gaming", "esports", "esport", "gameplay", "fps", "moba",
            "rpg", "mmorpg", "valorant", "dota", "mobile legends", "genshin",
            "playstation", "steam", "nintendo",
        ],
        _KEY_STYLE_SEED: (
            "Pembahasan gameplay mechanics, frame rate, build optimization, "
            "patch notes, meta strategy, matchmaking, serta review performa dan latency."
        ),
        _KEY_GLOSSARY: [
            "gameplay", "frame rate", "FPS", "patch notes", "meta", "nerf", "buff",
            "cooldown", "damage per second", "DPS", "matchmaking", "ranked", "esports",
            "hitbox", "ray tracing", "DLSS", "open world", "roguelike", "DLC", "speedrun",
        ],
        _KEY_PHONETIC: {
            r"\bfrem\s+ret\b": "frame rate",
            r"\bpech\s+not\b": "patch notes",
            r"\bmetch\s*meking\b": "matchmaking",
            r"\bhetx\s*box\b": "hitbox",
        },
    },
    "business": {
        _KEY_TRIGGERS: [
            "bisnis", "business", "startup", "founder", "marketing", "branding",
            "omzet", "profit", "scale", "penjualan", "sales", "manajemen",
            "entrepreneur", "umkm", "ecommerce",
        ],
        _KEY_STYLE_SEED: (
            "Pembahasan business model, unit economics, product-market fit, "
            "customer acquisition, retention, supply chain, serta strategi growth dan "
            "operational efficiency."
        ),
        _KEY_GLOSSARY: [
            "business model", "unit economics", "product-market fit", "CAC", "LTV",
            "churn rate", "conversion rate", "gross margin", "cash runway",
            "bootstrapping", "venture capital", "B2B", "B2C", "SaaS", "SOP", "KPI",
            "OKR", "supply chain", "value proposition",
        ],
        _KEY_PHONETIC: {
            r"\byunit\s+ekonomik\b": "unit economics",
            r"\bproduk\s+market\s+fit\b": "product-market fit",
            r"\bkonversi\s+ret\b": "conversion rate",
            r"\bsaplai\s+chen\b": "supply chain",
        },
    },
}

DOMAIN_GLOSSARIES: Dict[str, List[str]] = {
    name: list(cfg[_KEY_GLOSSARY]) for name, cfg in DOMAIN_PRESETS.items()
}

# Stop words to exclude from metadata term extraction
STOP_WORDS: Set[str] = {
    "http", "https", "www", "com", "net", "org", "co", "id", "io",
    "instagram", "youtube", "twitter", "tiktok", "facebook", "telegram", "discord",
    "subscribe", "subscriber", "subscribers", "sub", "like", "share", "comment",
    "channel", "video", "follow", "link", "join", "group", "whatsapp", "bitly",
    "the", "and", "for", "with", "that", "this", "from", "intro", "outro",
}

# Known silence / boilerplate hallucination regexes
HALLUCINATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"^terima kasih (telah|sudah) menonton[\.!\s]*$", re.IGNORECASE),
    re.compile(r"^thanks? (you )?for watching[\.!\s]*$", re.IGNORECASE),
    re.compile(r"^subtitles by (the )?amara\.org community[\.!\s]*$", re.IGNORECASE),
    re.compile(r"^subt[ií]tulos por la comunidad de amara\.org[\.!\s]*$", re.IGNORECASE),
    re.compile(r"^subscribed?[\.!\s]*$", re.IGNORECASE),
    re.compile(r"^(you[\.!\s]*){2,}$", re.IGNORECASE),
    re.compile(r"^(thank you[\.!\s]*){2,}$", re.IGNORECASE),
    re.compile(r"^(bye[\.!\s]*){2,}$", re.IGNORECASE),
    re.compile(r"^sub\s*indo\s+by\b.*$", re.IGNORECASE),
    re.compile(r"^(?:you\s+)*teksting\s+av\b.*$", re.IGNORECASE),
]

# Universal Indonesian-English phonetic collisions applied across all topics
DEFAULT_PHONETIC_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bfrem\s*work\b", re.IGNORECASE), "framework"),
    (re.compile(r"\bwork\s+flow\b", re.IGNORECASE), "workflow"),
    (re.compile(r"\bbes\s+praktis\b", re.IGNORECASE), "best practice"),
    (re.compile(r"\bkes\s+stadi\b", re.IGNORECASE), "case study"),
    (re.compile(r"\bbencmark\b", re.IGNORECASE), "benchmark"),
    (re.compile(r"\binsait\b", re.IGNORECASE), "insight"),
]

LEXICON_CONFIG_PATH = pathlib.Path.home() / ".config" / "whis-tube" / "lexicon.json"


def _discover_lexicon_paths() -> List[pathlib.Path]:
    """Return candidate lexicon paths ordered highest-priority first."""
    raw_candidates: List[pathlib.Path] = [
        REPO_ROOT / "lexicon.json",
        REPO_ROOT / "lexicon.local.json",
        pathlib.Path.cwd() / "lexicon.json",
    ]
    env_path = os.environ.get("WHIS_TUBE_LEXICON_PATH", "").strip()
    if env_path:
        raw_candidates.append(pathlib.Path(env_path).expanduser())
    raw_candidates.append(LEXICON_CONFIG_PATH)

    unique_paths: List[pathlib.Path] = []
    seen: Set[pathlib.Path] = set()
    for candidate in raw_candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(candidate)
    return unique_paths


def _compile_rule(
    pattern: str,
    replacement: str,
    raw_regex: bool = False,
) -> Optional[Tuple[re.Pattern, str]]:
    """Compile a phonetic regex pattern safely."""
    pat = (pattern or "").strip()
    if not pat:
        return None
    if not raw_regex and not pat.startswith(r"\b"):
        pat = rf"\b{re.escape(pat)}\b"
    elif not pat.startswith(r"\b"):
        pat = rf"\b{pat}\b"
    try:
        return re.compile(pat, re.IGNORECASE), str(replacement)
    except re.error as exc:
        logger.warning(f"Invalid phonetic regex '{pattern}': {exc}")
        return None


def _compile_rules_from_source(source: Any, raw_regex: bool = False) -> List[Tuple[re.Pattern, str]]:
    """Compile phonetic rules from either a dict mapping or a list of rule dicts."""
    compiled: List[Tuple[re.Pattern, str]] = []
    if isinstance(source, dict):
        for pat, repl in source.items():
            if isinstance(pat, str) and isinstance(repl, str):
                rule = _compile_rule(pat, repl, raw_regex=raw_regex)
                if rule:
                    compiled.append(rule)
    elif isinstance(source, list):
        for entry in source:
            if isinstance(entry, dict) and "pattern" in entry and "replacement" in entry:
                rule = _compile_rule(str(entry["pattern"]), str(entry["replacement"]), raw_regex=True)
                if rule:
                    compiled.append(rule)
    return compiled


def _parse_lexicon_file(path: pathlib.Path) -> Dict[str, Any]:
    """Parse a JSON lexicon file supporting both legacy rule maps and preset schemas."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read custom lexicon from {path}: {exc}")
        return {}

    if isinstance(data, list):
        return {_KEY_PHONETIC: data}
    if not isinstance(data, dict):
        return {}
    if any(k in _SCHEMA_KEYS for k in data):
        return data
    # Legacy flat dict: { "spoken": "canonical" }
    return {_KEY_PHONETIC: data}


def _merge_preset_entry(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a user preset override onto a base preset entry."""
    merged = {
        _KEY_TRIGGERS: list(base.get(_KEY_TRIGGERS, [])),
        _KEY_STYLE_SEED: base.get(_KEY_STYLE_SEED, ""),
        _KEY_GLOSSARY: list(base.get(_KEY_GLOSSARY, [])),
        _KEY_PHONETIC: dict(base.get(_KEY_PHONETIC, {})),
    }
    if isinstance(overlay.get(_KEY_STYLE_SEED), str):
        merged[_KEY_STYLE_SEED] = overlay[_KEY_STYLE_SEED]
    if isinstance(overlay.get(_KEY_TRIGGERS), list):
        merged[_KEY_TRIGGERS] = [str(t).strip().lower() for t in overlay[_KEY_TRIGGERS] if str(t).strip()]
    if isinstance(overlay.get(_KEY_GLOSSARY), list):
        merged[_KEY_GLOSSARY] = [str(g).strip() for g in overlay[_KEY_GLOSSARY] if str(g).strip()]
    overlay_phonetic = overlay.get(_KEY_PHONETIC)
    if isinstance(overlay_phonetic, dict) and isinstance(merged.get(_KEY_PHONETIC), dict):
        merged[_KEY_PHONETIC] = {**merged[_KEY_PHONETIC], **overlay_phonetic}
    elif isinstance(overlay_phonetic, (dict, list)):
        merged[_KEY_PHONETIC] = overlay_phonetic
    return merged


def _merge_lexicon_dicts(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a higher-priority lexicon config over a lower-priority config."""
    out = dict(base)
    for scalar_key in (_KEY_DEFAULT_PRESET, _KEY_DEFAULT_SEED, _KEY_ENABLED_PRESETS):
        if scalar_key in overlay:
            out[scalar_key] = overlay[scalar_key]

    if isinstance(overlay.get(_KEY_CUSTOM_GLOSSARY), list):
        existing_g = list(out.get(_KEY_CUSTOM_GLOSSARY) or [])
        out[_KEY_CUSTOM_GLOSSARY] = existing_g + [str(g) for g in overlay[_KEY_CUSTOM_GLOSSARY]]

    if _KEY_PHONETIC in overlay:
        existing_rules = list(out.get("_compiled_global_phonetics") or [])
        existing_rules.extend(_compile_rules_from_source(overlay[_KEY_PHONETIC], raw_regex=False))
        out["_compiled_global_phonetics"] = existing_rules

    if isinstance(overlay.get(_KEY_PRESETS), dict):
        merged_presets = dict(out.get(_KEY_PRESETS) or {})
        for pname, pcfg in overlay[_KEY_PRESETS].items():
            if isinstance(pcfg, dict):
                key = str(pname).strip().lower()
                merged_presets[key] = _merge_preset_entry(merged_presets.get(key, {}), pcfg)
        out[_KEY_PRESETS] = merged_presets

    return out


def load_lexicon_config() -> Dict[str, Any]:
    """Hot-load and merge custom lexicon/preset config across local, cwd, env, and global paths."""
    cfg: Dict[str, Any] = {}
    # Apply lowest-priority first so higher-priority files win on scalar overrides
    for path in reversed(_discover_lexicon_paths()):
        parsed = _parse_lexicon_file(path)
        if parsed:
            cfg = _merge_lexicon_dicts(cfg, parsed)
    return cfg


def get_merged_presets(lexicon_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return built-in domain presets merged with any user-defined overrides from lexicon.json."""
    cfg = lexicon_cfg if lexicon_cfg is not None else load_lexicon_config()
    merged: Dict[str, Dict[str, Any]] = {
        name: _merge_preset_entry(preset_def, {})
        for name, preset_def in DOMAIN_PRESETS.items()
    }
    user_presets = cfg.get(_KEY_PRESETS)
    if isinstance(user_presets, dict):
        for pname, pcfg in user_presets.items():
            if isinstance(pcfg, dict):
                key = str(pname).strip().lower()
                merged[key] = _merge_preset_entry(merged.get(key, {}), pcfg)
    return merged


def _enabled_preset_names(
    merged_presets: Dict[str, Dict[str, Any]],
    lexicon_cfg: Dict[str, Any],
) -> List[str]:
    """Return ordered list of preset names enabled by configuration."""
    configured = lexicon_cfg.get(_KEY_ENABLED_PRESETS)
    if isinstance(configured, list):
        allowed = [str(x).strip().lower() for x in configured]
        return [name for name in allowed if name in merged_presets]
    return list(merged_presets.keys())


def load_user_lexicon(
    lexicon_cfg: Optional[Dict[str, Any]] = None,
) -> List[Tuple[re.Pattern, str]]:
    """Load global user-defined phonetic replacement rules from discovered lexicon config."""
    cfg = lexicon_cfg if lexicon_cfg is not None else load_lexicon_config()
    precompiled = cfg.get("_compiled_global_phonetics")
    if isinstance(precompiled, list):
        return precompiled
    return _compile_rules_from_source(cfg.get(_KEY_PHONETIC), raw_regex=False)


def _collect_combined_text(info: Dict[str, Any]) -> str:
    """Combine title, description, tags, and chapter titles into a searchable string."""
    title = info.get("title") or ""
    description = info.get("description") or ""
    tags = [str(t) for t in (info.get("tags") or []) if isinstance(t, str)]
    chapters = info.get("chapters") or []
    parts = [title, description, " ".join(tags)]
    for ch in chapters:
        if isinstance(ch, dict) and ch.get("title"):
            parts.append(str(ch["title"]))
    return " ".join(parts).strip()


def _count_trigger_hits(lower_text: str, triggers: List[str]) -> int:
    """Count boundary-safe trigger matches so short tokens like 'ai' never false-match substrings."""
    hits = 0
    for trig in triggers:
        clean = str(trig).strip().lower()
        if not clean:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(clean)}(?![a-z0-9])", lower_text):
            hits += 1
    return hits


def resolve_active_presets(
    info: Dict[str, Any],
    preset: str = "auto",
    lexicon_cfg: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Resolve which domain presets are active for a given video and preset setting."""
    cfg = lexicon_cfg if lexicon_cfg is not None else load_lexicon_config()
    merged = get_merged_presets(cfg)

    raw_preset = (preset or "").strip()
    if not raw_preset or raw_preset.lower() == "auto":
        raw_preset = str(cfg.get(_KEY_DEFAULT_PRESET) or "auto").strip()

    lowered = raw_preset.lower()
    if lowered in ("none", "off", "disabled", "neutral"):
        return []

    if lowered != "auto":
        selected: List[str] = []
        for token in re.split(r"[,;\s]+", lowered):
            if token in merged and token not in selected:
                selected.append(token)
        return selected

    lower_corpus = _collect_combined_text(info).lower()
    if not lower_corpus:
        return []

    scored: List[Tuple[int, str]] = []
    for name in _enabled_preset_names(merged, cfg):
        triggers = merged[name].get(_KEY_TRIGGERS) or []
        hits = _count_trigger_hits(lower_corpus, triggers)
        if hits > 0:
            scored.append((hits, name))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in scored]


def _extract_seed_phrases(seed: str) -> List[str]:
    """Extract clean bilingual key phrases from a domain style seed."""
    cleaned = re.sub(r"^(?:Pembahasan|Obrolan)\s+", "", seed.strip(" ."), flags=re.IGNORECASE)
    phrases: List[str] = []
    for part in cleaned.split(","):
        item = re.sub(r"^(?:serta\s+update|serta|dan)\s+", "", part.strip(), flags=re.IGNORECASE).strip()
        if item:
            phrases.append(item)
    return phrases


def _blend_style_seeds(seeds: List[str], max_chars: int = 190) -> str:
    """Interleave key phrases from multiple active seeds into a concise bilingual prompt seed."""
    phrase_lists = [_extract_seed_phrases(s) for s in seeds]
    chosen: List[str] = []
    seen: Set[str] = set()
    cur_len = len("Pembahasan .")

    for group in itertools.zip_longest(*phrase_lists):
        for phrase in group:
            if not phrase:
                continue
            low = phrase.lower()
            if low in seen:
                continue
            added_len = len(phrase) + (2 if chosen else 0)
            if cur_len + added_len > max_chars and chosen:
                return f"Pembahasan {', '.join(chosen)}."
            seen.add(low)
            chosen.append(phrase)
            cur_len += added_len

    return f"Pembahasan {', '.join(chosen)}." if chosen else seeds[0]


def resolve_style_seed(
    lang: Optional[str],
    active_presets: List[str],
    lexicon_cfg: Optional[Dict[str, Any]] = None,
) -> str:
    """Select or blend an Indonesian bilingual style seed matching active presets."""
    if lang != "id":
        return ""
    cfg = lexicon_cfg if lexicon_cfg is not None else load_lexicon_config()
    merged = get_merged_presets(cfg)
    seeds: List[str] = []
    for name in active_presets:
        seed = (merged.get(name) or {}).get(_KEY_STYLE_SEED)
        if isinstance(seed, str) and seed.strip():
            seeds.append(seed.strip())

    if len(seeds) == 1:
        return seeds[0]
    if len(seeds) > 1:
        return _blend_style_seeds(seeds)

    custom_default = cfg.get(_KEY_DEFAULT_SEED)
    if isinstance(custom_default, str) and custom_default.strip():
        return custom_default.strip()
    return DEFAULT_STYLE_SEED_ID


def resolve_language(
    explicit_lang: Optional[str],
    info: Dict[str, Any],
    audio_meta: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Smart language resolution that detects Indonesian content from metadata/markers."""
    if explicit_lang and explicit_lang.strip():
        return explicit_lang.strip().lower()

    if audio_meta:
        fmt_note = str(audio_meta.get("format_note") or "").lower()
        if "indonesian" in fmt_note or "indonesia" in fmt_note:
            return "id"

    text_corpus = _collect_combined_text(info).lower()
    tokens = set(re.findall(r"[a-z]+", text_corpus))
    if tokens.intersection(INDONESIAN_MARKERS):
        return "id"

    info_lang = info.get("language")
    if info_lang:
        code = str(info_lang).split("-")[0].strip().lower()
        if code:
            return code

    return None


def extract_metadata_terms(
    info: Dict[str, Any],
    custom_glossary: str = "",
    max_terms: int = 40,
    preset: str = "auto",
    active_presets: Optional[List[str]] = None,
    lexicon_cfg: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Extract tickers, CamelCase brands, proper nouns, and active preset glossary terms."""
    cfg = lexicon_cfg if lexicon_cfg is not None else load_lexicon_config()
    terms: List[str] = []
    seen: Set[str] = set()

    def add_term(term: str) -> None:
        t = term.strip(" ,.:;!?\"'()[]{}")
        t_lower = t.lower()
        if not t or len(t) < 2 or t_lower in STOP_WORDS:
            return
        if t_lower.startswith(("http://", "https://", "www.")) or "http" in t_lower:
            return
        if t not in seen and t_lower not in seen:
            seen.add(t)
            seen.add(t_lower)
            terms.append(t)

    # 1. Explicit call glossary & lexicon global custom_glossary take highest priority
    if custom_glossary:
        for item in re.split(r"[,;\n]+", custom_glossary):
            add_term(item)

    for item in (cfg.get(_KEY_CUSTOM_GLOSSARY) or []):
        if isinstance(item, str):
            add_term(item)

    # 2. Extract tickers & CamelCase brands from URL-stripped metadata, and proper nouns from title/chapters
    combined_text = re.sub(r"https?://\S+|www\.\S+", " ", _collect_combined_text(info))
    for ticker in re.findall(r"\b[A-Z]{2,6}\b", combined_text):
        add_term(ticker)

    brand_pattern = r"\b(?:[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[a-z]+[A-Z][a-zA-Z0-9]*|[A-Za-z0-9]+\.[a-z]{2,4})\b"
    for brand in re.findall(brand_pattern, combined_text):
        add_term(brand)

    chapter_titles = " ".join(
        str(ch["title"]) for ch in (info.get("chapters") or []) if isinstance(ch, dict) and ch.get("title")
    )
    title_chapters = f"{info.get('title') or ''} {chapter_titles}"
    for pn in re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", title_chapters):
        if pn.lower() not in INDONESIAN_MARKERS:
            add_term(pn)

    # 3. Interleave glossary terms round-robin across active domain presets
    presets_to_use = active_presets if active_presets is not None else resolve_active_presets(info, preset=preset, lexicon_cfg=cfg)
    merged = get_merged_presets(cfg)
    preset_glossaries = [
        list((merged.get(pname) or {}).get(_KEY_GLOSSARY, []))
        for pname in presets_to_use
    ]
    for round_terms in itertools.zip_longest(*preset_glossaries):
        for term in round_terms:
            if term is not None:
                add_term(str(term))

    # 4. Append clean video tags
    for tag in (info.get("tags") or []):
        if isinstance(tag, str) and len(tag.strip()) > 2:
            add_term(tag.strip())

    return terms[:max_terms]


def is_hallucination_segment(seg: Dict[str, Any]) -> bool:
    """Detect boilerplate silence hallucinations or degenerated repetition."""
    text = (seg.get("text") or "").strip()
    clean_text = text.strip(" .!?,:;\"'").lower()
    if not clean_text:
        return True

    if any(pat.search(text) for pat in HALLUCINATION_PATTERNS):
        return True

    no_speech = seg.get("no_speech_prob") or 0.0
    avg_logprob = seg.get("avg_logprob") or 0.0
    if clean_text in {"you", "thank you", "bye", "thanks", "terima kasih"} and (no_speech > 0.4 or avg_logprob < -0.7):
        return True

    words = clean_text.split()
    return len(words) >= 3 and len(set(words)) == 1


def _collect_tail_text(
    prev_segments: Optional[List[Dict[str, Any]]],
    tail_budget: int,
) -> str:
    """Build sanitized previous-chunk tail text fitting within tail_budget characters."""
    if not prev_segments or tail_budget <= 30:
        return ""

    valid_texts: List[str] = []
    for seg in reversed(prev_segments):
        if seg.get("flags") or is_hallucination_segment(seg):
            continue
        seg_text = (seg.get("text") or "").strip()
        if seg_text:
            valid_texts.append(seg_text)
            if len(valid_texts) >= 6:
                break

    if not valid_texts:
        return ""

    valid_texts.reverse()
    full_tail = " ".join(valid_texts)
    if len(full_tail) <= tail_budget:
        return full_tail

    clipped = full_tail[-tail_budget:]
    first_space = clipped.find(" ")
    if first_space != -1 and first_space < 25:
        return clipped[first_space + 1:].strip()
    return clipped.strip()


def build_whisper_prompt(
    title: str,
    channel: str,
    lang: Optional[str],
    terms: List[str],
    prev_segments: Optional[List[Dict[str, Any]]] = None,
    include_tail: bool = True,
    max_chars: int = 600,
    active_presets: Optional[List[str]] = None,
    lexicon_cfg: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a token-budgeted prompt (<= 600 chars) for Whisper Large V3."""
    header_parts = [p.strip() for p in (title, channel) if p and p.strip()]
    header = ". ".join(header_parts)
    if header and not header.endswith("."):
        header += "."

    seed = resolve_style_seed(lang, active_presets or [], lexicon_cfg=lexicon_cfg)
    fixed_prefix = " ".join(p for p in (header, seed) if p)

    glossary_str = ""
    if terms:
        glossary_prefix = "Istilah: "
        available = max_chars - len(fixed_prefix) - len(glossary_prefix) - 3
        full_glossary = f"{glossary_prefix}{', '.join(terms)}."
        if len(fixed_prefix) + 1 + len(full_glossary) <= max_chars:
            glossary_str = full_glossary
        elif available > 20:
            trimmed: List[str] = []
            cur_len = 0
            for t in terms:
                if cur_len + len(t) + 2 > available:
                    break
                trimmed.append(t)
                cur_len += len(t) + 2
            if trimmed:
                glossary_str = f"{glossary_prefix}{', '.join(trimmed)}."

    front_text = " ".join(p for p in (fixed_prefix, glossary_str) if p)[:max_chars]
    tail_text = _collect_tail_text(prev_segments, max_chars - len(front_text) - 1) if include_tail else ""
    prompt = f"{front_text} {tail_text}".strip()
    return prompt[:max_chars]


def _collect_preset_phonetic_rules(
    active_presets: Optional[List[str]],
    lexicon_cfg: Dict[str, Any],
) -> List[Tuple[re.Pattern, str]]:
    """Gather compiled phonetic rules from active (or enabled) presets."""
    merged = get_merged_presets(lexicon_cfg)
    target_names = (
        active_presets
        if active_presets is not None
        else _enabled_preset_names(merged, lexicon_cfg)
    )
    rules: List[Tuple[re.Pattern, str]] = []
    for name in target_names:
        preset_cfg = merged.get(name) or {}
        raw_source = preset_cfg.get(_KEY_PHONETIC)
        is_builtin = name in DOMAIN_PRESETS and raw_source == DOMAIN_PRESETS[name].get(_KEY_PHONETIC)
        rules.extend(_compile_rules_from_source(raw_source, raw_regex=is_builtin))
    return rules


def normalize_code_switch_text(
    text: str,
    custom_rules: Optional[List[Tuple[re.Pattern, str]]] = None,
    active_presets: Optional[List[str]] = None,
    lexicon_cfg: Optional[Dict[str, Any]] = None,
) -> str:
    """Normalize Indonesian-English phonetic collisions via universal, preset, and user rules."""
    if not text:
        return ""

    out = text
    for pattern, replacement in DEFAULT_PHONETIC_RULES:
        out = pattern.sub(replacement, out)

    if custom_rules is not None:
        extra_rules = custom_rules
    else:
        cfg = lexicon_cfg if lexicon_cfg is not None else load_lexicon_config()
        extra_rules = _collect_preset_phonetic_rules(active_presets, cfg) + load_user_lexicon(cfg)

    for pattern, replacement in extra_rules:
        out = pattern.sub(replacement, out)

    return out
