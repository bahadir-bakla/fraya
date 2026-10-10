"""Read slot values out of spoken (ASR) text, in Turkish and English.

Voice input is not typed input: numbers arrive as words ("üç bin beş yüz"),
diacritics get lost in ASR ("bes bin"), and callers correct themselves
mid-sentence ("üç bin, yok pardon beş bin"). Full-Duplex-Bench v3 reports
self-correction as a shared failure of current voice agents, and in finance it
means a tool call with the wrong amount. ``parse_amount(..., strategy=
"last_corrected")`` takes the value after the last correction marker;
``"first"`` reproduces the naive behaviour for simulation.
"""

from __future__ import annotations

import re

_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


def fold(text: str) -> str:
    """Lowercase and drop Turkish diacritics, the way a noisy ASR transcript looks."""
    return re.sub(r"\s+", " ", text.replace("İ", "i").replace("I", "ı").lower().translate(_ASCII)).strip()


_UNITS = {
    "sifir": 0, "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
    "on": 10, "yirmi": 20, "otuz": 30, "kirk": 40, "elli": 50, "altmis": 60, "yetmis": 70, "seksen": 80, "doksan": 90,
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"yuz": 100, "hundred": 100, "bin": 1000, "thousand": 1000, "milyon": 1_000_000, "million": 1_000_000}
_CORRECTION = re.compile(
    r"\b(yok|pardon|hayir|yani|aslinda|duzeltiyorum|degil|no wait|sorry|i mean|actually|make that|rather)\b"
)
_NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z]+")


def _digits_value(tok: str) -> float:
    # "12.450" / "12,450" are thousands groups; "2,5" / "2.5" with 1-2 trailing digits is a decimal.
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok):
        return float(re.sub(r"[.,]", "", tok))
    return float(tok.replace(",", "."))


def numbers(text: str) -> list[tuple[int, float]]:
    """All numbers in the text as (position, value), digits and number words alike.

    "üç bin beş yüz" -> 3500, "5 bin" -> 5000, "12.450 TL" -> 12450.
    """
    s = fold(text)
    out: list[tuple[int, float]] = []
    total = current = 0.0
    start = -1
    seen = False

    def close() -> None:
        nonlocal total, current, start, seen
        if seen:
            out.append((start, total + current))
        total = current = 0.0
        start, seen = -1, False

    for m in _NUM_TOKEN.finditer(s):
        tok = m.group()
        if tok[0].isdigit():
            if len(re.findall(r"[.,]", tok)) > 1 and not re.fullmatch(r"\d{1,3}([.,]\d{3})+", tok):
                close()  # "12.03.1985" is a date, not an amount
                continue
            if seen and (current or total):  # "12 15", "five thousand, 6000" are two numbers
                close()
            if not seen:
                start = m.start()
            current += _digits_value(tok)
            seen = True
        elif tok in _UNITS:
            if seen and current and _UNITS[tok] >= 10 and current % 100 != 0 and current < 10:
                close()
            if not seen:
                start = m.start()
            current += _UNITS[tok]
            seen = True
        elif tok in _SCALES:
            if not seen:
                start, seen, current = m.start(), True, 1.0  # "bin" alone is 1000
            scale = _SCALES[tok]
            if scale == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale
                current = 0
        elif tok in ("tl", "lira", "try", "usd", "dollars", "euro", "and", "ve"):
            continue
        else:
            close()
    close()
    return out


def parse_amount(text: str, strategy: str = "last_corrected") -> float | None:
    nums = numbers(text)
    if not nums:
        return None
    if strategy == "first":
        return nums[0][1]
    s = fold(text)
    marks = [m.end() for m in _CORRECTION.finditer(s)]
    if marks:
        after = [v for pos, v in nums if pos >= marks[-1]]
        if after:
            return after[0]
    return nums[0][1]


_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8, "eylul": 9,
    "ekim": 10, "kasim": 11, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def dates(text: str) -> list[tuple[int, str]]:
    """Every date said, with its position: '20 ekim, yok pardon 25 ekim' -> [(0, '20.10'), (17, '25.10')]."""
    s, out, taken = fold(text), [], []
    month_rx = "|".join(_MONTHS)
    pats = [
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: f"{int(m.group(3)):02d}.{int(m.group(2)):02d}.{m.group(1)}"),
        (r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b",
         lambda m: f"{int(m.group(1)):02d}.{int(m.group(2)):02d}" + (f".{m.group(3)}" if m.group(3) else "")),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_rx})[a-z]*\b(?:\s+(\d{{4}}))?",
         lambda m: f"{int(m.group(1)):02d}.{_MONTHS[m.group(2)]:02d}" + (f".{m.group(3)}" if m.group(3) else "")),
        (rf"\b({month_rx})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?",
         lambda m: f"{int(m.group(2)):02d}.{_MONTHS[m.group(1)]:02d}" + (f".{m.group(3)}" if m.group(3) else "")),
        (r"\bayin (\d{1,2})", lambda m: f"{int(m.group(1)):02d}"),
    ]
    for rx, val in pats:
        for m in re.finditer(rx, s):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((m.start(), val(m)))
    return sorted(out)


def parse_date_corrected(text: str) -> str | None:
    """The date the caller means: the first one after their last self-correction, else the first one."""
    ds = dates(text)
    if not ds:
        return None
    marks = [m.end() for m in _CORRECTION.finditer(fold(text))]
    after = [v for pos, v in ds if marks and pos >= marks[-1]]
    return after[0] if after else ds[0][1]


def parse_date(text: str) -> str | None:
    """'12 mart 1985', '12.03.1985', '1985-03-12', 'ayın 15'i' -> 'DD.MM[.YYYY]'."""
    s = fold(text)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        return f"{int(m.group(3)):02d}.{int(m.group(2)):02d}.{m.group(1)}"
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b", s)
    if m:
        d = f"{int(m.group(1)):02d}.{int(m.group(2)):02d}"
        return d + (f".{m.group(3)}" if m.group(3) else "")
    month_rx = "|".join(_MONTHS)
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_rx})\b(?:\s+(\d{{4}}))?", s)
    if m:
        d = f"{int(m.group(1)):02d}.{_MONTHS[m.group(2)]:02d}"
        return d + (f".{m.group(3)}" if m.group(3) else "")
    m = re.search(rf"\b({month_rx})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", s)
    if m:
        d = f"{int(m.group(2)):02d}.{_MONTHS[m.group(1)]:02d}"
        return d + (f".{m.group(3)}" if m.group(3) else "")
    m = re.search(r"\bayin (\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):02d}"
    return None


def parse_digits(text: str, n: int) -> str | None:
    """A run of exactly ``n`` digits, spoken as digits or digit words ('bir iki üç dört')."""
    s = fold(text)
    m = re.search(rf"(?<!\d)(\d(?:[ \-]?\d){{{n - 1}}})(?!\d)", s)
    if m:
        return re.sub(r"\D", "", m.group(1))
    words = [str(_UNITS[w]) for w in re.findall(r"[a-z]+", s) if w in _UNITS and _UNITS[w] < 10]
    if len(words) >= n:
        return "".join(words[-n:])
    return None


_YES = re.compile(r"\b(evet|dogru|aynen|tamam|olur|onayliyorum|yes|correct|right|yep|confirm)\b")
_NO = re.compile(r"\b(hayir|yanlis|degil|yok|no|wrong|incorrect|nope)\b")


def parse_yes_no(text: str) -> bool | None:
    s = fold(text)
    no, yes = _NO.search(s), _YES.search(s)
    if no and (not yes or no.start() < yes.start()):
        return False
    if yes:
        return True
    return None


def parse_slot(kind: str, text: str, strategy: str = "last_corrected"):
    if kind == "amount":
        return parse_amount(text, strategy)
    if kind == "date":
        return parse_date(text) if strategy == "first" else parse_date_corrected(text)
    if kind.startswith("digits"):
        return parse_digits(text, int(kind[6:] or 4))
    if kind == "yesno":
        return parse_yes_no(text)
    return text.strip() or None
