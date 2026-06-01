"""Parsing helpers for Amazon's "bought in past month" sales signal.

Amazon (and therefore the Rainforest API ``recent_sales`` field) reports recent
sales as fuzzy strings such as:

    "50+ bought in past month"
    "1K+ bought in past month"
    "10K+ bought in past month"
    "2K+ bought in past month"

These functions turn those strings into a comparable integer floor (the "+"
means "at least this many"), so callers can apply a numeric threshold.
"""

from __future__ import annotations

import re

# Multipliers for the shorthand suffixes Amazon uses on the badge.
_SUFFIX_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
}

# e.g. "10K+", "50+", "1.5K+ bought in past month"
_SALES_RE = re.compile(
    r"(?P<num>\d[\d,]*\.?\d*)\s*(?P<suffix>[kKmM])?\s*\+?",
)


def parse_recent_sales(value) -> int | None:
    """Return the integer floor of a recent-sales string, or ``None``.

    ``None`` means "no recent-sales signal was present", which is distinct from
    ``0`` (a real, parsed value). Numeric inputs are returned as ``int`` as-is.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None

    text = value.strip().lower()
    if not text:
        return None

    match = _SALES_RE.search(text)
    if not match:
        return None

    raw_number = match.group("num").replace(",", "")
    try:
        number = float(raw_number)
    except ValueError:
        return None

    suffix = match.group("suffix")
    if suffix:
        number *= _SUFFIX_MULTIPLIERS[suffix.lower()]

    return int(number)


def meets_sales_threshold(value, minimum: int) -> bool:
    """True if the parsed recent sales is >= ``minimum``.

    Unknown/unparseable values never pass the threshold.
    """
    parsed = parse_recent_sales(value)
    return parsed is not None and parsed >= minimum
