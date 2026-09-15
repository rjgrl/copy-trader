"""Symbol and text normalization helpers for signal parsing."""

from __future__ import annotations

import re

# Common aliases that providers use instead of broker symbols
SYMBOL_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "XAUUSD": "XAUUSD",
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
