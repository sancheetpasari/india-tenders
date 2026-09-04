"""Find the bid deadline inside a tender PDF.

Departmental sites publish a notice as a PDF and list only the date it was
uploaded. The deadline is in the prose -- "submitted on or before 07.09.2026
at 13:00 hours" -- so read it out of there, or the tender arrives with no
countdown and cannot drive a reminder.

Deliberately conservative: a wrong deadline is worse than none. A date only
counts when a submission phrase points at it, the two are close together in
the text, and the result is in the future.

    python deadline.py <pdf-url-or-path>     # show what it finds
"""
from __future__ import annotations

import io
import re
import sys
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

# "07.09.2026", "7/9/26", "07-09-2026"
NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})\b")
# "07 September 2026", "7th Sep, 2026"
WORDED = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*[- ]?\s*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(\d{4})\b",
    re.I)

# Phrases that actually introduce a deadline. "opening" is excluded on
# purpose: the opening date is usually the same day and an hour or two later,
# and quoting it as the deadline would send someone to a closed tender.
CUE = re.compile(
    r"(on or before|last date(?: and time)?(?: of)?|due date|closing date"
    r"|last day|to be submitted|shall be submitted|should be submitted"
    r"|submission of (?:bid|tender|proposal)s?|receipt of (?:bid|tender|proposal)s?"
    r"|bid submission|tender submission|upto|up to|till)", re.I)

TIME = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*(?:hours|hrs|hr)?\s*(am|pm)?\b", re.I)

MAX_GAP = 140          # characters between the cue and the date
MAX_AHEAD = 400        # days: anything further out is a misread


def _mk(day, mon, year, hh=None, mi=None):
    if year < 100:
        year += 2000
    try:
        return datetime(year, mon, day, hh or 0, mi or 0, tzinfo=IST)
    except ValueError:
        return None


def _dates(text):
    """Every plausible date, as (position, datetime)."""
    out = []
    for m in NUMERIC.finditer(text):
        d, mo, y = (int(g) for g in m.groups())
        # dd/mm and mm/dd are ambiguous; Indian notices are dd/mm, and a
        # value above 12 in the first field settles it either way
        if mo > 12 and d <= 12:
            d, mo = mo, d
        dt = _mk(d, mo, y)
        if dt:
            out.append((m.start(), m.end(), dt))
    for m in WORDED.finditer(text):
        d, mon, y = m.group(1), m.group(2).lower()[:3], m.group(3)
        dt = _mk(int(d), MONTHS[mon], int(y))
        if dt:
            out.append((m.start(), m.end(), dt))
    return sorted(out)


def find_deadline(text, now=None):
    """'07-Sep-2026 01:00 PM', or '' when nothing is convincing."""
    now = now or datetime.now(IST)
    text = re.sub(r"\s+", " ", text or "")
    if not text:
        return ""

    best = None
    for cue in CUE.finditer(text):
        for start, end, dt in _dates(text):
            gap = start - cue.end()
            if gap < 0 or gap > MAX_GAP:
                continue
            if dt < now - timedelta(days=1) or dt > now + timedelta(days=MAX_AHEAD):
                continue
            # a time immediately after the date belongs to it
            tail = text[end:end + 40]
            tm = TIME.search(tail)
            if tm:
                hh, mi, ap = int(tm.group(1)), int(tm.group(2)), tm.group(3)
                if ap:
                    hh = hh % 12 + (12 if ap.lower() == "pm" else 0)
                if 0 <= hh <= 23:
                    dt = dt.replace(hour=hh, minute=mi)
            # earliest qualifying deadline wins: a notice often quotes the
            # submission date and then a later opening or validity date
            if best is None or dt < best:
                best = dt
            break
    if not best:
        return ""
    if best.hour == 0 and best.minute == 0:
        best = best.replace(hour=17)          # unstated time: assume close of day
    return best.strftime("%d-%b-%Y %I:%M %p")


def text_from_pdf(data, max_pages=4):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        rd = PdfReader(io.BytesIO(data))
        return " ".join((p.extract_text() or "") for p in rd.pages[:max_pages])
    except Exception:                                     # noqa: BLE001
        return ""                                          # scanned or broken


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    if src.startswith("http"):
        import requests, urllib3
        urllib3.disable_warnings()
        data = requests.get(src, timeout=40, verify=False,
                            headers={"User-Agent": "Mozilla/5.0"}).content
    else:
        data = open(src, "rb").read()
    text = text_from_pdf(data)
    print(f"{len(text)} characters of text")
    print("deadline:", find_deadline(text) or "(not found)")


if __name__ == "__main__":
    main()
