"""Regex-based detection of sensitive financial and proper-name entities."""

from __future__ import annotations

import re
import unicodedata
from typing import TypedDict


class SensitiveEntity(TypedDict):
    """A unique sensitive value returned to the frontend."""

    text: str
    category: str
    occurrences: int


_HSPACE = r"[ \t\u00a0\u202f]"
_NUMBER_PATTERN = rf"(?:[+\-−]{_HSPACE}*)?(?:\d{{1,3}}(?:(?:[,.]|{_HSPACE}+)\d{{3}})+|\d+)(?:[,.](?:\d{{1,2}}|[-−]))?"
_CURRENCY_PATTERN = r"(?:USD|EUR|GBP|HUF|CHF|CAD|AUD|JPY|Ft|dollars?|euros?|pounds?|forints?|[$€£])"

FINANCIAL_AMOUNT_REGEX = re.compile(
    rf"""
    (?<![\w.,])
    (?:
        {_CURRENCY_PATTERN}{_HSPACE}*{_NUMBER_PATTERN}(?!\d|[.,]\d)
        |
        {_NUMBER_PATTERN}{_HSPACE}*{_CURRENCY_PATTERN}
    )
    (?!\w)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_UPPER = "A-ZÁÉÍÓÖŐÚÜŰÀÂÄÃÅÆÇÈÊËÌÎÏÑÒÔÕØÙÛÝŸ"
_LOWER = "a-záéíóöőúüűàâäãåæçèêëìîïñòôõøùûýÿ"
_WORD = rf"(?:[{_UPPER}][{_LOWER}]+(?:[-’'][{_UPPER}{_LOWER}][{_LOWER}]+)*|[{_UPPER}]{{2,}}|[{_UPPER}]\.)"
CAPITALIZED_ENTITY_REGEX = re.compile(
    rf"(?<!\w)(?:(?:[Dd]r|[Pp]rof|ifj|id)\.{_HSPACE}+)?{_WORD}(?:{_HSPACE}+{_WORD}){{0,5}}\.?(?!\w)"
)
LABELLED_ENTITY_REGEX = re.compile(
    rf"(?im)^{_HSPACE}*(?:Név|Ügyfél|Kapcsolattartó|Megrendelő|Cégnév|Cég|Szállító|Város|Település|Székhely)"
    rf"(?:{_HSPACE}*[:=–-]{_HSPACE}*|{_HSPACE}+)(?P<value>[^\r\n;]+)"
)
COMPANY_REGEX = re.compile(
    rf"(?m)^{_HSPACE}*(?P<value>[{_UPPER}][\w’'&.-]*(?:{_HSPACE}+[\w’'&.-]+){{0,7}}{_HSPACE}+(?:Kft|Zrt|Nyrt|Bt|Kkt|GmbH|Ltd|Inc)\.?(?!\w))"
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
        "Név", "Cég", "Cím", "Város", "Helység", "Dátum", "Összeg", "Összesen", "Fizetendő",
        "Ft", "HUF", "EUR", "USD", "GBP", "CHF", "Kft", "Kft.", "Zrt", "Zrt.", "Bt", "Bt.", "Dr", "Dr.", "Prof", "Prof.",
    }
)


def _clean_match(value: str) -> str:
    """Collapse internal whitespace and trim punctuation-adjacent spacing."""

    return " ".join(unicodedata.normalize("NFC", value).split()).strip()


def _is_plausible_capitalized_entity(value: str) -> bool:
    """Filter common document labels from broad proper-name candidates."""

    words = value.split()
    if words and words[0].casefold().rstrip(".") in {"dr", "prof", "ifj", "id"}:
        words = words[1:]
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
    text = unicodedata.normalize("NFC", text)

    matches: list[tuple[int, str, str]] = []
    covered: list[tuple[int, int]] = []

    for pattern in (LABELLED_ENTITY_REGEX, COMPANY_REGEX):
        for match in pattern.finditer(text):
            start, end = match.span("value")
            candidate = _clean_match(match.group("value")).strip(" ,;")
            if not candidate or len(candidate) > 256 or any(a <= start and end <= b for a, b in covered):
                continue
            matches.append((start, candidate, "name_or_city"))
            covered.append(match.span())

    for match in FINANCIAL_AMOUNT_REGEX.finditer(text):
        matches.append((match.start(), _clean_match(match.group(0)), "amount"))

    for match in CAPITALIZED_ENTITY_REGEX.finditer(text):
        if any(a <= match.start() and match.end() <= b for a, b in covered):
            continue
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

