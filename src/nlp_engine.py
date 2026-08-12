"""Regex-based detection of sensitive financial and proper-name entities."""

from __future__ import annotations

import re
from typing import TypedDict


class SensitiveEntity(TypedDict):
    """A unique sensitive value returned to the frontend."""

    text: str
    category: str
    occurrences: int


_NUMBER_PATTERN = r"(?:\d{1,3}(?:[,\.\s]\d{3})+|\d+)(?:[,.]\d{2})?"
_CURRENCY_PATTERN = r"(?:USD|EUR|GBP|HUF|CHF|CAD|AUD|JPY|Ft|dollars?|euros?|pounds?|forints?)"

FINANCIAL_AMOUNT_REGEX = re.compile(
    rf"""
    (?<!\w)
    (?:
        {_CURRENCY_PATTERN}\s*{_NUMBER_PATTERN}
        |
        [\$\u20ac\u00a3]\s*{_NUMBER_PATTERN}
        |
        {_NUMBER_PATTERN}\s*{_CURRENCY_PATTERN}
    )
    (?!\w)
    """,
    re.IGNORECASE | re.VERBOSE,
)

CAPITALIZED_ENTITY_REGEX = re.compile(
    r"\b[A-Z][a-z]{2,}(?:[-'][A-Z][a-z]{2,})?"
    r"(?:\s+[A-Z][a-z]{1,}(?:[-'][A-Z][a-z]{1,})?){0,3}\b"
)

_CAPITALIZED_STOP_WORDS = frozenset(
    {
        "Amount",
        "Balance",
        "Bill",
        "Date",
        "Dear",
        "Document",
        "From",
        "Invoice",
        "Page",
        "Payment",
        "Receipt",
        "Reference",
        "Statement",
        "Subject",
        "Subtotal",
        "The",
        "This",
        "To",
        "Total",
    }
)


def _clean_match(value: str) -> str:
    """Collapse internal whitespace and trim punctuation-adjacent spacing."""

    return " ".join(value.split()).strip()


def _is_plausible_capitalized_entity(value: str) -> bool:
    """Filter common document labels from broad proper-name candidates."""

    words = value.split()
    if not words or words[0] in _CAPITALIZED_STOP_WORDS:
        return False
    return any(word not in _CAPITALIZED_STOP_WORDS for word in words)


def find_sensitive_entities(text: str) -> list[SensitiveEntity]:
    """Find financial amounts and capitalized potential names or cities.

    The detector is intentionally conservative about classification: regex can
    identify candidates, but a user must approve every value before redaction.
    Duplicate values are combined case-insensitively and include an occurrence
    count for review in the frontend.

    Args:
        text: Text extracted from a native PDF or produced by local OCR.

    Returns:
        A list of unique entities in their first-seen document order.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    matches: list[tuple[int, str, str]] = []

    for match in FINANCIAL_AMOUNT_REGEX.finditer(text):
        matches.append((match.start(), _clean_match(match.group(0)), "amount"))

    for match in CAPITALIZED_ENTITY_REGEX.finditer(text):
        candidate = _clean_match(match.group(0))
        if _is_plausible_capitalized_entity(candidate):
            matches.append((match.start(), candidate, "name_or_city"))

    matches.sort(key=lambda item: item[0])

    unique_entities: dict[tuple[str, str], SensitiveEntity] = {}
    for _, entity_text, category in matches:
        key = (category, entity_text.casefold())
        if key in unique_entities:
            unique_entities[key]["occurrences"] += 1
            continue
        unique_entities[key] = {
            "text": entity_text,
            "category": category,
            "occurrences": 1,
        }

    return list(unique_entities.values())
