"""Checksum-validated PII detectors for spoken financial conversations.

Regex alone over-fires on any long digit run (amounts, dates, reference
numbers), so every detector here confirms the candidate with the entity's own
checksum before reporting it. Detectors run on normalized text: spoken digit
groups ("4111 1111 1111 1111", "TR33 0006 ...") are matched with separators
allowed, then stripped before the checksum.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEP = r"[ \-.]?"


@dataclass(frozen=True)
class PIIMatch:
    entity: str
    start: int
    end: int
    value: str


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def tckn_ok(digits: str) -> bool:
    """Turkish national ID (T.C. Kimlik No): 11 digits, two check digits."""
    if len(digits) != 11 or digits[0] == "0":
        return False
    d = [int(c) for c in digits]
    odd = d[0] + d[2] + d[4] + d[6] + d[8]
    even = d[1] + d[3] + d[5] + d[7]
    if (odd * 7 - even) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def iban_ok(iban: str) -> bool:
    """ISO 13616 mod-97 check."""
    s = iban[4:] + iban[:4]
    num = "".join(str(int(c, 36)) for c in s)
    return int(num) % 97 == 1


_CARD = re.compile(r"(?<!\d)(?:\d" + _SEP + r"){12,18}\d(?!\d)")
_TCKN = re.compile(r"(?<!\d)[1-9](?:" + _SEP + r"\d){10}(?!\d)")
# TR IBAN is 26 chars: TR + 2 check digits + 22 digits.
_IBAN_TR = re.compile(r"(?<![A-Za-z0-9])TR\d{2}(?:" + _SEP + r"\d){22}(?!\d)", re.IGNORECASE)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def find_pii(text: str, entities: tuple[str, ...] = ("card", "tckn", "iban_tr")) -> list[PIIMatch]:
    found: list[PIIMatch] = []
    if "iban_tr" in entities:
        for m in _IBAN_TR.finditer(text):
            compact = re.sub(r"[ \-.]", "", m.group()).upper()
            if iban_ok(compact):
                found.append(PIIMatch("iban_tr", m.start(), m.end(), compact))
    taken = [(p.start, p.end) for p in found]

    def free(m: re.Match) -> bool:
        return all(m.end() <= s or m.start() >= e for s, e in taken)

    if "tckn" in entities:
        for m in _TCKN.finditer(text):
            if free(m) and tckn_ok(_digits(m.group())):
                found.append(PIIMatch("tckn", m.start(), m.end(), _digits(m.group())))
        taken = [(p.start, p.end) for p in found]
    if "card" in entities:
        for m in _CARD.finditer(text):
            digits = _digits(m.group())
            if free(m) and 13 <= len(digits) <= 19 and luhn_ok(digits):
                found.append(PIIMatch("card", m.start(), m.end(), digits))
    return sorted(found, key=lambda p: p.start)


def redact(text: str, entities: tuple[str, ...] = ("card", "tckn", "iban_tr")) -> str:
    out, last = [], 0
    for p in find_pii(text, entities):
        out.append(text[last : p.start])
        out.append(f"[{p.entity.upper()}]")
        last = p.end
    out.append(text[last:])
    return "".join(out)
