"""Bilingual (Indonesian-English) Code-Switching Enhancement Module for whis-tube.

Provides:
- Smart language resolution for code-switched Indonesian content.
- Metadata term extraction (tickers, CamelCase brands, chapters).
- Domain glossaries (finance, crypto, tech).
- Token-budgeted prompt builder with hallucination-filtered tail.
- Hallucination segment detector.
- Deterministic phonetic normalizer for Indonesian-English code-switching collisions.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("whis-tube.code_switch")

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

# Concise Indonesian sentence naturally embedding English terms to prime Whisper's decoder
BILINGUAL_STYLE_SEED_ID: str = (
    "Pembahasan market structure, price action, liquidity, support resistance, "
    "risk management, cash flow, public equity, valuation, serta update macroeconomic "
    "The Fed, CPI, FOMC, dan interest rate."
)

DOMAIN_GLOSSARIES: Dict[str, List[str]] = {
    "crypto": [
        "BTC", "ETH", "Solana", "altcoin", "memecoin", "liquidity", "bullish",
        "bearish", "airdrop", "staking", "DEX", "CEX", "smart contract", "pump",
        "dump", "DeFi", "Web3", "tokenomics", "Pump.fun", "LayerZero", "Arbitrum",
        "Sui", "Aptos", "TradingView", "CoinMarketCap",
    ],
    "finance": [
        "IHSG", "The Fed", "FOMC", "CPI", "inflasi", "interest rate", "dividend",
        "yield", "Bursa Efek", "IPO", "market cap", "cash flow", "balance sheet",
        "public equity", "valuation", "reksadana", "obligasi", "BlackRock", "iShares",
        "Goldman Sachs",
    ],
    "tech": [
        "AI", "machine learning", "LLM", "API", "backend", "frontend", "database",
        "cloud", "deployment", "open-source", "framework", "latency", "pipeline",
        "Starlink",
    ],
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
]

# High-frequency Indonesian-English phonetic collisions
DEFAULT_PHONETIC_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bbusai\s+fed\b", re.IGNORECASE), "Bursa Efek"),
    (re.compile(r"\bbursa\s+efed\b", re.IGNORECASE), "Bursa Efek"),
    (re.compile(r"\bbusai\b", re.IGNORECASE), "Bursa Efek"),
    (re.compile(r"\bpam\s*fan\b", re.IGNORECASE), "Pump.fun"),
    (re.compile(r"\bGoldman\s+Sax\b", re.IGNORECASE), "Goldman Sachs"),
    (re.compile(r"\bjp\s+morgen\b", re.IGNORECASE), "JP Morgan"),
    (re.compile(r"\bStarling\b", re.IGNORECASE), "Starlink"),
    (re.compile(r"\b(?:Aalsut|Alshut)\b", re.IGNORECASE), "Alsut"),
    (re.compile(r"\b(?:Aalam\s+Sutera|Alam\s+Sutra)\b", re.IGNORECASE), "Alam Sutera"),
    (re.compile(r"\b(?:Tmothy|Timoti)\b", re.IGNORECASE), "Timothy"),
    (re.compile(r"\bBro\s+Team\b", re.IGNORECASE), "Bro Tim"),
    (re.compile(r"\bpablik\s+ekuiti\b", re.IGNORECASE), "public equity"),
    (re.compile(r"\bvelue\s+investing\b", re.IGNORECASE), "value investing"),
    (re.compile(r"\braning\s+tred\b", re.IGNORECASE), "running trade"),
    (re.compile(r"\bsmart\s+kontrak\b", re.IGNORECASE), "smart contract"),
    (re.compile(r"\bmarket\s+kap\b", re.IGNORECASE), "market cap"),
    (re.compile(r"\b(?:kash|kes)\s+flow\b", re.IGNORECASE), "cash flow"),
    (re.compile(r"\bkat\s+loss\b", re.IGNORECASE), "cut loss"),
    (re.compile(r"\btek\s+profit\b", re.IGNORECASE), "take profit"),
    (re.compile(r"\bblakrok\b", re.IGNORECASE), "BlackRock"),
    (re.compile(r"\bblekrok\b", re.IGNORECASE), "BlackRock"),
    (re.compile(r"\btrading\s*viu\b", re.IGNORECASE), "TradingView"),
    (re.compile(r"\bbitkoin\b", re.IGNORECASE), "Bitcoin"),
    (re.compile(r"\biterium\b", re.IGNORECASE), "Ethereum"),
    (re.compile(r"\bthe\s+fed\b", re.IGNORECASE), "The Fed"),
    (re.compile(r"\bfomce\b", re.IGNORECASE), "FOMC"),
    (re.compile(r"\bsepiai\b", re.IGNORECASE), "CPI"),
]

LEXICON_CONFIG_PATH = pathlib.Path.home() / ".config" / "whis-tube" / "lexicon.json"


def load_user_lexicon() -> List[Tuple[re.Pattern, str]]:
    """Load optional user-defined phonetic replacement rules from JSON config."""
    rules: List[Tuple[re.Pattern, str]] = []
    if LEXICON_CONFIG_PATH.exists():
        try:
            data = json.loads(LEXICON_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for pat, repl in data.items():
                    rules.append((re.compile(rf"\b{re.escape(pat)}\b", re.IGNORECASE), repl))
            elif isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and "pattern" in entry and "replacement" in entry:
                        rules.append((re.compile(rf"\b{entry['pattern']}\b", re.IGNORECASE), entry["replacement"]))
        except Exception as exc:
            logger.warning(f"Failed to read custom lexicon from {LEXICON_CONFIG_PATH}: {exc}")
    return rules


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

    title = info.get("title") or ""
    description = info.get("description") or ""
    tags_str = " ".join(str(t) for t in (info.get("tags") or []) if isinstance(t, str))
    text_corpus = f"{title} {description} {tags_str}".lower()

    # Tokenize corpus into words
    tokens = set(re.findall(r"[a-z]+", text_corpus))

    # Check for Indonesian marker intersections
    marker_matches = tokens.intersection(INDONESIAN_MARKERS)
    if marker_matches:
        # If any strong Indonesian marker is present, treat as Indonesian
        return "id"

    # Fallback to info language if specified
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
) -> List[str]:
    """Extract tickers, CamelCase brands, and chapter/tag keywords from YouTube metadata."""
    terms: List[str] = []
    seen: Set[str] = set()

    def add_term(term: str) -> None:
        t = term.strip(" ,.:;!?\"'()[]{}")
        if not t:
            return
        t_lower = t.lower()
        if t_lower in STOP_WORDS or len(t) < 2:
            return
        if t_lower.startswith(("http://", "https://", "www.")) or "http" in t_lower:
            return
        if t not in seen and t_lower not in seen:
            seen.add(t)
            seen.add(t_lower)
            terms.append(t)

    # 1. Custom user glossary takes first priority
    if custom_glossary:
        for item in re.split(r"[,;\n]+", custom_glossary):
            item_clean = item.strip()
            if item_clean:
                add_term(item_clean)

    title = info.get("title") or ""
    description = info.get("description") or ""
    tags = info.get("tags") or []
    chapters = info.get("chapters") or []

    combined_text = f"{title} {description} " + " ".join(tags)
    for ch in chapters:
        if isinstance(ch, dict) and ch.get("title"):
            combined_text += f" {ch['title']}"

    # 2. Extract uppercase financial / crypto tickers (e.g. BTC, IHSG, ETF, FOMC, CPI)
    ticker_matches = re.findall(r"\b[A-Z]{2,6}\b", combined_text)
    for ticker in ticker_matches:
        if ticker.lower() not in STOP_WORDS:
            add_term(ticker)

    # 3. Extract CamelCase / mixed-case brands, dot-names, and capitalized tech/brand words
    # e.g. BlackRock, iShares, TradingView, Pump.fun, Starlink
    brand_matches = re.findall(r"\b(?:[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[a-z]+[A-Z][a-zA-Z0-9]*|[A-Za-z0-9]+\.[a-z]{2,4})\b", combined_text)
    for brand in brand_matches:
        add_term(brand)

    # Also capture capitalized words in description/title that are not Indonesian markers or stop words
    proper_nouns = re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", combined_text)
    for pn in proper_nouns:
        if pn.lower() not in INDONESIAN_MARKERS and pn.lower() not in STOP_WORDS:
            add_term(pn)

    # 4. Check domain glossaries based on context keywords
    lower_text = combined_text.lower()
    if any(k in lower_text for k in ["crypto", "kripto", "bitcoin", "btc", "altcoin", "memecoin", "trading"]):
        for t in DOMAIN_GLOSSARIES["crypto"]:
            add_term(t)

    if any(k in lower_text for k in ["saham", "ihsg", "market", "fed", "fomc", "cpi", "investor", "keuangan", "finansial"]):
        for t in DOMAIN_GLOSSARIES["finance"]:
            add_term(t)

    if any(k in lower_text for k in ["ai", "tech", "teknologi", "coding", "software", "starlink", "cloud"]):
        for t in DOMAIN_GLOSSARIES["tech"]:
            add_term(t)

    # 5. Extract specific tag terms
    for tag in tags:
        if isinstance(tag, str) and tag.strip():
            clean_tag = tag.strip()
            if clean_tag.lower() not in STOP_WORDS and len(clean_tag) > 2:
                add_term(clean_tag)

    return terms[:max_terms]


def is_hallucination_segment(seg: Dict[str, Any]) -> bool:
    """Detect boilerplate silence hallucinations or degenerated repetition."""
    text = (seg.get("text") or "").strip()
    if not text:
        return True

    clean_text = text.strip(" .!?,:;\"'").lower()

    # Check known boilerplate hallucinations
    for pat in HALLUCINATION_PATTERNS:
        if pat.search(text.strip()):
            return True

    # Common short silence triggers with elevated no_speech_prob
    no_speech = seg.get("no_speech_prob") or 0.0
    avg_logprob = seg.get("avg_logprob") or 0.0

    if clean_text in {"you", "thank you", "bye", "thanks", "terima kasih"} and (no_speech > 0.4 or avg_logprob < -0.7):
        return True

    # Repeated single word phrases
    words = clean_text.split()
    if len(words) >= 3 and len(set(words)) == 1:
        return True

    return False


def build_whisper_prompt(
    title: str,
    channel: str,
    lang: Optional[str],
    terms: List[str],
    prev_segments: Optional[List[Dict[str, Any]]] = None,
    include_tail: bool = True,
    max_chars: int = 600,
) -> str:
    """Build a token-budgeted prompt for Whisper Large V3.

    Budget allocation (<= 600 chars, < 224 tokens):
    1. Base prefix: title & channel.
    2. Style seed: bilingual Indonesian-English seed (if lang is 'id').
    3. Glossary: extracted metadata terms & domain keywords.
    4. Tail: sanitized previous chunk text (filtered against hallucinations & low confidence).
    """
    header_parts = []
    if title:
        header_parts.append(title.strip())
    if channel:
        header_parts.append(channel.strip())
    header = ". ".join(header_parts)
    if header and not header.endswith("."):
        header += "."

    seed = BILINGUAL_STYLE_SEED_ID if lang == "id" else ""

    # Build glossary string
    glossary_str = ""
    if terms:
        glossary_str = "Istilah: " + ", ".join(terms) + "."

    # Candidate high-priority front section
    front_parts = [p for p in [header, seed, glossary_str] if p]
    front_text = " ".join(front_parts)

    # If front_text already exceeds max_chars, prune glossary terms from end
    if len(front_text) > max_chars:
        # Keep header and seed intact
        fixed_prefix = " ".join([p for p in [header, seed] if p])
        available_for_glossary = max_chars - len(fixed_prefix) - 12
        if available_for_glossary > 20 and terms:
            trimmed_terms = []
            cur_len = 0
            for t in terms:
                if cur_len + len(t) + 2 > available_for_glossary:
                    break
                trimmed_terms.append(t)
                cur_len += len(t) + 2
            if trimmed_terms:
                glossary_str = "Istilah: " + ", ".join(trimmed_terms) + "."
                front_text = f"{fixed_prefix} {glossary_str}".strip()
            else:
                front_text = fixed_prefix
        else:
            front_text = fixed_prefix[:max_chars]

    # Calculate remaining character budget for previous-chunk tail
    tail_budget = max_chars - len(front_text) - 1  # 1 for separating space

    tail_text = ""
    if include_tail and prev_segments and tail_budget > 30:
        valid_texts = []
        for s in reversed(prev_segments):
            # Exclude flagged segments
            if s.get("flags"):
                continue
            # Exclude hallucination segments
            if is_hallucination_segment(s):
                continue
            seg_text = (s.get("text") or "").strip()
            if not seg_text:
                continue
            valid_texts.append(seg_text)
            if len(valid_texts) >= 6:
                break

        if valid_texts:
            valid_texts.reverse()
            full_tail = " ".join(valid_texts)
            if len(full_tail) <= tail_budget:
                tail_text = full_tail
            else:
                # Truncate on word boundary
                clipped = full_tail[-tail_budget:]
                first_space = clipped.find(" ")
                if first_space != -1 and first_space < 25:
                    tail_text = clipped[first_space + 1:].strip()
                else:
                    tail_text = clipped.strip()

    prompt = f"{front_text} {tail_text}".strip()
    return prompt[:max_chars]


def normalize_code_switch_text(
    text: str,
    custom_rules: Optional[List[Tuple[re.Pattern, str]]] = None,
) -> str:
    """Normalize common Indonesian-English phonetic collisions via word-boundary rules."""
    if not text:
        return ""

    out = text

    # Apply default phonetic rules
    for pattern, replacement in DEFAULT_PHONETIC_RULES:
        out = pattern.sub(replacement, out)

    # Apply user custom rules
    rules = custom_rules if custom_rules is not None else load_user_lexicon()
    for pattern, replacement in rules:
        out = pattern.sub(replacement, out)

    return out
