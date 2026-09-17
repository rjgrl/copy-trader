"""Symbol and text normalization helpers for signal parsing.

Preserves the original Telegram message elsewhere; these helpers only
produce a parse-friendly copy.
"""

from __future__ import annotations

import re
import unicodedata

# Common aliases that providers use instead of broker symbols
SYMBOL_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "XAGUSD": "XAGUSD",
    "BTC": "BTCUSD",
    "BITCOIN": "BTCUSD",
    "NAS100": "NAS100",
    "US100": "NAS100",
    "NASDAQ": "NAS100",
    "US30": "US30",
    "DOW": "US30",
    "DJ30": "US30",
}

# Markdown / decorative noise
_MARKDOWN_RE = re.compile(r"[*_`~|]+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)
_SEPARATOR_RE = re.compile(r"[═━─\-–—_]{3,}")
_DASH_RE = re.compile(r"[–—−]")

# Label canonicalization (order matters — longer phrases first)
_LABEL_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bTAKE\s*PROFITS?\b", re.I), "TP"),
    (re.compile(r"\bTAKEPROFIT\b", re.I), "TP"),
    (re.compile(r"\bTARGETS?\b", re.I), "TP"),
    (re.compile(r"\bSTOP\s*LOSS\b", re.I), "SL"),
    (re.compile(r"\bSTOPLOSS\b", re.I), "SL"),
    (re.compile(r"\bSTOP\b(?=\s*[:=]?\s*\d)", re.I), "SL"),
]

# Symbol forms before stripping separators
_SYMBOL_FORMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bXAU\s*/\s*USD\b", re.I), "XAUUSD"),
    (re.compile(r"\bXAU\s+USD\b", re.I), "XAUUSD"),
    (re.compile(r"\bXAG\s*/\s*USD\b", re.I), "XAGUSD"),
]

_DISCLAIMER_START = re.compile(
    r"(?i)\b("
    r"disclaimer|"
    r"this is a reference|"
    r"educational purposes|"
    r"not\s+(?:financial\s+)?advice|"
    r"we are not responsible|"
    r"trade smart|"
    r"risk\s+warning"
    r")\b"
)


def normalize_symbol(raw: str) -> str:
    """Uppercase, strip separators, apply known aliases."""
    cleaned = raw.strip().upper()
    cleaned = cleaned.replace("/", "").replace("-", "").replace(" ", "")
    return SYMBOL_ALIASES.get(cleaned, cleaned)


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace and unify line endings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line.strip())


def parse_float(token: str) -> float | None:
    """Parse a price token that may use commas as thousand/decimal separators."""
    if token is None:
        return None
    cleaned = token.strip().replace(" ", "")
    if not cleaned:
        return None
    # European style: 1.234,56 → 1234.56
    if re.match(r"^\d{1,3}(\.\d{3})+,\d+$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_floats(text: str) -> list[float]:
    """Extract all numeric price-like values from a string."""
    pattern = re.compile(r"[-+]?\d[\d.,]*")
    results: list[float] = []
    for match in pattern.finditer(text):
        value = parse_float(match.group(0))
        if value is not None:
            results.append(value)
    return results


def prepare_message_for_parse(raw: str) -> tuple[str, list[str]]:
    """Return (normalized_text, notes) for parsing. Does not mutate the original."""
    notes: list[str] = []
    if not raw:
        return "", ["Empty message"]

    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _DASH_RE.sub("-", text)

    if _MARKDOWN_RE.search(text):
        text = _MARKDOWN_RE.sub("", text)
        notes.append("Stripped markdown formatting")

    if _EMOJI_RE.search(text):
        text = _EMOJI_RE.sub(" ", text)
        notes.append("Removed decorative emojis")

    if _SEPARATOR_RE.search(text):
        text = _SEPARATOR_RE.sub("\n", text)
        notes.append("Removed decorative separators")

    for pattern, repl in _SYMBOL_FORMS:
        if pattern.search(text):
            text = pattern.sub(repl, text)
            notes.append(f"Normalized symbol form → {repl}")

    for pattern, repl in _LABEL_SUBS:
        if pattern.search(text):
            text = pattern.sub(repl, text)
            notes.append(f"Normalized label → {repl}")

    # Soft-truncate obvious disclaimer blocks (keep structured signal above)
    disc = _DISCLAIMER_START.search(text)
    if disc and disc.start() > 40:
        text = text[: disc.start()].rstrip()
        notes.append("Ignored trailing disclaimer section")

    text = normalize_whitespace(text)
    return text, notes
