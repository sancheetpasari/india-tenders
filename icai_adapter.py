"""CA-firm tenders from ICAI's Tender Monitoring Directorate.

Concurrent audits, statutory audits, internal audit engagements -- the core
of sector 1 -- are largely issued by bodies that never touch GePNIC:
co-operative and gramin banks, development authorities, boards, societies.
The Tripura State Co-operative Bank's concurrent audit was the case that
showed it; the Tripura portal carries no bank at all.

ICAI indexes exactly this work at tmdicai.org, nationally. The listing is
public HTML and so are the notice PDFs, so the deadline can be read out of
the document the way dept_adapters does it.

    python icai_adapter.py            # scrape and print what it finds
    python icai_adapter.py --pages 30 # look further back
"""
from __future__ import annotations

import concurrent.futures as cf
import html as htmllib
import json
import os
import re
import sys
from datetime import datetime, timedelta

import urllib3

import deadline as DL
import sector

urllib3.disable_warnings()

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "icai_deadlines.json")
STATE = "CA tenders (ICAI)"
BASE = "https://tmdicai.org"

ENTRY = re.compile(
    r'<article class="entry entry-single">.*?<h5[^>]*><strong>(.*?)</strong></h5>.*?'
    r'<p class="mb-1"><strong>(.*?)</strong></p>\s*<p>(.*?)</p>.*?'
    r'href="(count1\.php\?pdf_id=[^"]+)"', re.S)
POSTED = re.compile(r"([A-Z][a-z]{2}),\s*(\d{1,2}),\s*(\d{4})")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

# The heading reads "Entity, City, State". Only the tail is a place we know.
STATES = [
    "Andaman & Nicobar", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jammu & Kashmir", "Jharkhand", "Karnataka", "Kerala",
    "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
]
ALIAS = {"orissa": "Odisha", "pondicherry": "Puducherry", "new delhi": "Delhi",
         "jammu and kashmir": "Jammu & Kashmir", "andaman and nicobar": "Andaman & Nicobar",
         "uttaranchal": "Uttarakhand", "tamilnadu": "Tamil Nadu"}


def session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (compatible; tender-registry/1.0)"
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=2, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))))
    return s


def clean(x):
    # unescape twice: these headings arrive double-encoded, so one pass
    # leaves "&amp;" sitting in the middle of an organisation name
    x = htmllib.unescape(htmllib.unescape(re.sub(r"<[^>]+>", "", x)))
    return re.sub(r"\s+", " ", x).strip()


def place_of(heading):
    """The state at the end of 'Entity, City, State', or ''."""
    tail = [p.strip() for p in heading.split(",")][-1].lower()
    if tail in ALIAS:
        return ALIAS[tail]
    for s in STATES:
        if tail == s.lower():
            return s
    return ""


def posted_on(text):
    m = POSTED.search(text)
    if not m:
        return None
    mon, day, year = m.groups()
    try:
        return datetime(int(year), MONTHS[mon], int(day))
    except (KeyError, ValueError):
        return None


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.replace(tmp, CACHE)


def fetch_page(s, n):
    url = f"{BASE}/archive.php" + ("" if n == 1 else f"?pagess={n}")
    try:
        h = s.get(url, timeout=30, verify=False).text
    except Exception:                                     # noqa: BLE001
        return []
    out = []
    for heading, date, desc, href in ENTRY.findall(h):
        out.append((clean(heading), clean(date), clean(desc),
                    f"{BASE}/{href.lstrip('/')}"))
    return out


def deadline_for(s, url, cache, budget):
    """(deadline, is_gem). Cached, because the PDF costs a request."""
    if url in cache:
        v = cache[url]
        return (v, False) if isinstance(v, str) else (v.get("d", ""), v.get("gem", False))
    if budget["left"] <= 0:
        return "", False
    budget["left"] -= 1
    got, is_gem = "", False
    try:
        r = s.get(url, timeout=45, verify=False)
        # r.content, not a capped read off r.raw: these links redirect, and a
        # truncated body makes pypdf fail with "EOF marker not found" -- which
        # looks exactly like a PDF with no deadline in it.
        if (r.status_code == 200
                and "pdf" in (r.headers.get("Content-Type") or "").lower()
                and len(r.content) <= 12_000_000):
            text = DL.text_from_pdf(r.content)
            # A GeM bid document. Four fifths of this index is GeM, listed on
            # or after the day it closes -- and we already hold GeM directly,
            # scraped live with real deadlines. Keeping these would add
            # thousands of duplicates, most of them already expired.
            is_gem = "Bid End Date" in text
            got = DL.find_deadline(text)
    except Exception:                                     # noqa: BLE001
        return "", False                                   # retry next run
    cache[url] = {"d": got, "gem": is_gem}
    return got, is_gem


def scrape(pages=14, days=45, max_pdfs=150, workers=6):
    """Recent CA-firm tenders from the ICAI index."""
    s = session()
    cache = load_cache()
    cutoff = datetime.now() - timedelta(days=days)
    seen, entries = set(), []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(lambda n: fetch_page(s, n), range(1, pages + 1)):
            for heading, date, desc, url in got:
                if url in seen:
                    continue
                seen.add(url)
                entries.append((heading, date, desc, url))

    budget = {"left": max_pdfs}
    rows = []
    for heading, date, desc, url in entries:
        when = posted_on(date)
        if when and when < cutoff:        # long closed; do not fetch the PDF
            continue
        closing, is_gem = deadline_for(s, url, cache, budget)
        # What this source is for: issuers that reach no other feed --
        # co-operative banks, boards, societies. Skip GeM duplicates, and
        # anything with no deadline that is too old to still be open.
        if is_gem:
            continue
        if not closing and when and when < datetime.now() - timedelta(days=21):
            continue
        t = {"state": STATE, "region": place_of(heading), "sector": "",
             "tender_id": "", "ref_no": "", "title": desc or heading,
             "organisation": heading, "opening": "", "corrigendum": "", "ecv": "",
             "published": when.strftime("%d-%b-%Y") if when else "",
             "closing": closing, "portal": f"{BASE}/archive.php",
             "detail_url": url}
        t["sector"] = sector.tag(t) or "ca"   # the whole index is CA work
        rows.append(t)
    save_cache(cache)
    dated = sum(1 for r in rows if r["closing"])
    note = (f"{len(rows)} CA-firm tenders from {len(entries)} indexed, "
            f"{dated} with a deadline read from the PDF")
    return STATE, rows, note


def main():
    pages = 20
    if "--pages" in sys.argv:
        pages = int(sys.argv[sys.argv.index("--pages") + 1])
    state, rows, note = scrape(pages=pages)
    print(note)
    for r in sorted(rows, key=lambda x: x["closing"] or "z")[:25]:
        print(f"  {r['closing'] or '(no deadline)':<22} {r['region'][:14]:<16} "
              f"{r['organisation'][:40]:<42} {r['title'][:44]}")


if __name__ == "__main__":
    main()
