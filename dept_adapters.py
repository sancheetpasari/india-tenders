"""Tenders published on departmental websites rather than a procurement portal.

Not every government tender reaches GePNIC or GeM. Assam's departments and
corporations post notices as PDFs on their own sites -- the Assam Startup
accelerator RFP, AIDC's works notices -- and nothing on an e-procurement
portal knows they exist. This reads those pages.

It is a different kind of source and behaves differently:

* the listing gives a reference, an upload date and a PDF, never a deadline,
  so the deadline is read out of the PDF itself (see deadline.py) and is
  found about two thirds of the time
* pages are hand-authored inside a CMS, so the markup varies per site and a
  tolerant parser is the only workable approach
* a site that yields nothing recognisable is dropped rather than guessed at

Deadlines are cached by URL, so a PDF is fetched once and not on every run.

    python dept_adapters.py            # scrape and print what it finds
    python dept_adapters.py --probe    # re-check which sites still work
"""
from __future__ import annotations

import concurrent.futures as cf
import html as htmllib
import io
import logging
import json
import os
import re
import sys
from datetime import datetime, timedelta

import urllib3

import deadline as DL
import sector

urllib3.disable_warnings()
# pypdf narrates every malformed object it meets; these files are full of
# them and the commentary drowns the scrape log.
logging.getLogger('pypdf').setLevel(logging.ERROR)

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "deadlines.json")
STATE = "Assam (departments)"

# Discovered by probing all 196 bodies listed at assam.gov.in/departments-list
# for a tenders page. Re-check with --probe; sites come and go.
SITES = [
    ("Assam Industrial Development Corporation", "aidcltd.assam.gov.in", "/resource/tenders-0"),
    ("Assam Agricultural Marketing Board", "aasc.assam.gov.in", "/resource/tenders-0"),
    ("Directorate of Handloom & Textiles", "dht.assam.gov.in", "/resource/tenders-0"),
    ("Assam Energy Development Agency", "aeda.assam.gov.in", "/documents/tenders"),
    ("Directorate of Art & Culture", "art.assam.gov.in", "/resource/tenders"),
    ("Assam State Transport Corporation", "astc.assam.gov.in", "/resource/tenders"),
    ("Assam Science Technology & Environment Council", "astec.assam.gov.in", "/documents/tenders"),
    ("Directorate of Dairy Development", "dairy.assam.gov.in", "/resource/tenders-0"),
    ("Directorate of Tourism", "directortourism.assam.gov.in", "/resource/tenders-0"),
    ("Directorate of Medical Education", "dme.assam.gov.in", "/resource/tenders-0"),
    ("Department of Science & Technology", "dst.assam.gov.in", "/documents/tenders"),
    ("Directorate of Sports & Youth Welfare", "dsyw.assam.gov.in", "/documents/tenders"),
    ("Guwahati Biotech Park", "gbp.assam.gov.in", "/documents/tenders"),
    ("Handloom & Textiles Society", "hts.assam.gov.in", "/resource/tenders"),
    ("Directorate of Industries & Commerce", "industries.assam.gov.in", "/resource/tenders"),
    ("Industries & Commerce Department", "industriescom.assam.gov.in", "/resource/tenders-0"),
    ("Guwahati Planetarium", "planetariumguwahati.assam.gov.in", "/documents/tenders"),
    ("Panchayat & Rural Development", "pnrd.assam.gov.in", "/documents/tenders"),
    ("Power Department", "power.assam.gov.in", "/resource/tenders-0"),
    ("PWD Building & NH", "pwdbnh.assam.gov.in", "/resource/tenders"),
    ("RUSA Assam", "rusa.assam.gov.in", "/resource/tenders"),
    ("State Agriculture Academy", "saa.assam.gov.in", "/documents/tenders"),
    ("Directorate of Sericulture", "sericulture.assam.gov.in", "/resource/tenders"),
    ("Assam Skill Development Mission", "skill.assam.gov.in", "/resource/tenders"),
    ("Tea Tribes Welfare", "tea.assam.gov.in", "/resource/tenders-0"),
    ("Assam Tourism", "tourism.assam.gov.in", "/resource/tenders"),
    ("Transformation & Development", "transdev.assam.gov.in", "/resource/tenders"),
    ("Assam Innovation & Startup Foundation", "startup.assam.gov.in", "/?page_id=5686"),
    # AIIDC's own documents section renders nothing at all -- tenders,
    # notifications and office orders alike, with or without a browser, and an
    # old detail URL 404s. Its tenders reach GePNIC instead, where the
    # dashboard already has them. Kept here so that the day it starts posting
    # to its own site again, it is picked up without anyone noticing it had to be.
    ("Assam Industrial Infrastructure Development Corporation",
     "aiidc.assam.gov.in", "/documents/tenders-9"),
]

NOTICE = re.compile(
    r"\b(tender|nit\b|snit|rfp|rfq|eoi|expression of interest|quotation"
    r"|notice inviting|invitation|bid|empanel|auction|corrigendum)", re.I)
PDF = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
TAGS = re.compile(r"<[^>]+>")


def session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (compatible; tender-registry/1.0)"
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=2, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))))
    return s


def _text(html):
    return re.sub(r"\s+", " ", htmllib.unescape(TAGS.sub(" ", html))).strip()


def parse_listing(html, base):
    """(title, pdf url, uploaded) for every tender-looking entry.

    Handles the two shapes these pages take: a hand-made table where the
    reference and date sit in the row above the title, and a plain list.
    """
    out, prev = [], ""
    for chunk in ROW.findall(html):
        m = PDF.search(chunk)
        if not m:
            prev = chunk
            continue
        cells = [_text(c) for c in CELL.findall(chunk)]
        title = max(cells, key=len) if cells else ""
        head = _text(prev)
        d = ISO.search(head) or ISO.search(_text(chunk))
        ref = head.split("Uploaded")[0].strip(" :|") if head else ""
        out.append((title, m.group(1), d.group(0) if d else "", ref))
        prev = chunk

    if not out:                                   # list-shaped page
        for chunk in ITEM.findall(html):
            m = PDF.search(chunk)
            if not m:
                continue
            t = _text(chunk)
            d = ISO.search(t)
            out.append((t, m.group(1), d.group(0) if d else "", ""))

    seen, keep = set(), []
    for title, url, up, ref in out:
        if not url.startswith("http"):
            url = base.rstrip("/") + "/" + url.lstrip("/")
        title = htmllib.unescape(title)
        # a title shorter than this is a label like "NIT", not a tender; and a
        # tenders page also carries approvals, scheme lists and stray uploads
        if url in seen or len(title) < 18 or not NOTICE.search(title):
            continue
        seen.add(url)
        keep.append((title, url, up, ref))
    return keep


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


def deadline_for(s, url, cache):
    """Deadline from the PDF, fetched once and remembered."""
    if url in cache:
        return cache[url]
    got = ""
    try:
        r = s.get(url, timeout=45, verify=False, stream=True)
        if r.status_code == 200:
            data = r.raw.read(6_000_000, decode_content=True)
            got = DL.find_deadline(DL.text_from_pdf(data))
    except Exception:                                     # noqa: BLE001
        return ""                                          # retry next run
    cache[url] = got
    return got


def scrape_site(s, name, host, path, cache, since, recent, budget):
    base = f"https://{host}"
    try:
        r = s.get(base + path, timeout=30, verify=False)
        if r.status_code != 200:
            return name, [], f"HTTP {r.status_code}"
        entries = parse_listing(r.text, base)
    except Exception as e:                                # noqa: BLE001
        return name, [], f"ERROR {type(e).__name__}"

    rows = []
    for title, url, up, ref in entries:
        if up and up < since:            # long closed; do not fetch the PDF
            continue
        # A cold cache means hundreds of PDFs. Cached lookups are free;
        # new ones are rationed so one run cannot stall the whole scrape.
        if url in cache or budget["left"] > 0:
            if url not in cache:
                budget["left"] -= 1
            closing = deadline_for(s, url, cache)
        else:
            closing = ""
        pub = ""
        if up:
            try:
                pub = datetime.strptime(up, "%Y-%m-%d").strftime("%d-%b-%Y")
            except ValueError:
                pub = ""
        t = {"state": STATE, "region": "Assam", "sector": "",
             "tender_id": ref[:60], "ref_no": ref[:60], "title": title,
             "organisation": name, "published": pub, "closing": closing,
             "opening": "", "corrigendum": "", "ecv": "",
             "portal": base + path, "detail_url": url}
        t["sector"] = sector.tag(t)
        # Keep what could still be bid for: a deadline in the future, or no
        # deadline but posted recently enough to be live. Without this the
        # dashboard fills with notices that closed months ago.
        if not closing and (not up or up < recent):
            continue
        rows.append(t)
    return name, rows, f"{len(rows)} from {len(entries)} listed"


def scrape(days=120, workers=6, max_pdfs=200):
    """Every Assam departmental tender uploaded in the last `days` days."""
    s = session()
    cache = load_cache()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    rows, notes = [], []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        budget = {"left": max_pdfs}
        futs = [ex.submit(scrape_site, s, n, h, p, cache, since, recent, budget)
                for n, h, p in SITES]
        for f in cf.as_completed(futs):
            name, got, note = f.result()
            rows.extend(got)
            notes.append(f"{name}: {note}")
    save_cache(cache)
    dated = sum(1 for r in rows if r["closing"])
    live = len({r["organisation"] for r in rows})
    note = (f"{len(rows)} notices from {live} of {len(SITES)} Assam bodies, "
            f"{dated} with a deadline read from the PDF")
    return STATE, rows, note


def main():
    if "--probe" in sys.argv:
        s = session()
        for name, host, path in SITES:
            try:
                r = s.get(f"https://{host}{path}", timeout=20, verify=False)
                n = len(parse_listing(r.text, f"https://{host}"))
                print(f"  {host:<38} {n:>4} entries")
            except Exception as e:                        # noqa: BLE001
                print(f"  {host:<38} ERROR {type(e).__name__}")
        return
    state, rows, note = scrape()
    print(note)
    for r in sorted(rows, key=lambda x: x["closing"] or "z")[:25]:
        print(f"  {r['closing'] or '(no deadline)':<22} {r['organisation'][:28]:<30} "
              f"{r['title'][:52]}")


if __name__ == "__main__":
    main()
