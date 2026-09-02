"""Playwright-driven adapters for portals that refuse plain HTTP clients.

Two states need a real browser engine:

* **Gujarat** (nProcure) encrypts its DataTables request body and its tender
  endpoint is replay-protected -- it answers the page's own script once and
  404s on any repeat, even from inside the same browser. Driving the table's
  own pagination is the only way through.
* **Bihar** (EPSV2Web) is an Angular app whose REST API rejects non-browser
  callers with "Expected Fishing or Hacking attack". The loaded page keeps the
  full tender list in its Angular scope, so we read it from there.

Karnataka is deliberately absent: its tender search sits behind a captcha, and
this project does not attempt captcha bypass.

Requires:  pip install playwright && python -m playwright install chromium
Adapters return the same dict shape as scraper.py / adapters.py.
"""
from __future__ import annotations

import re
import time

from adapters import MONTHS, clean

BROWSER_STATES = ["Gujarat", "Bihar"]


def _available():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _dmy_to_gepnic(s):
    """'22-09-2026 16:00:00' -> '22-Sep-2026 04:00 PM'.

    Everything else in the dataset is 12-hour with AM/PM, and the dashboard's
    date parser expects that, so convert rather than pass 24-hour through.
    """
    s = clean(s)
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", s)
    if not m:
        return s
    d, mo, y, hh, mm = m.groups()
    try:
        name = MONTHS[int(mo) - 1]
    except (ValueError, IndexError):
        return s
    if hh is None:
        return f"{d}-{name}-{y}"
    h24 = int(hh)
    ampm = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return f"{d}-{name}-{y} {h12:02d}:{mm} {ampm}"


def _epoch_to_gepnic(ms):
    """Bihar returns epoch milliseconds (IST)."""
    if not ms:
        return ""
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromtimestamp(int(ms) / 1000, timezone(timedelta(hours=5, minutes=30)))
    except (ValueError, OSError, OverflowError):
        return ""
    return f"{dt.day:02d}-{MONTHS[dt.month - 1]}-{dt.year} {dt.strftime('%I:%M %p')}"


# ---------------------------------------------------------------------- Gujarat

_GJ_ROWS_JS = """() => [...document.querySelectorAll('#DataTables_Table_0 tbody tr')]
    .map(tr => [...tr.children].map(td => td.innerText))"""


def _parse_gj_row(cells):
    if len(cells) < 2:
        return None
    ref, blob = clean(cells[0]), cells[1] or ""

    tid = re.search(r"Tender\s*Id\s*:\s*(\d+)", blob)
    if not tid:
        return None
    dept = clean(blob[:tid.start()])
    work = re.search(r"Name\s*Of\s*Work\s*:\s*(.+?)(?:\n\s*\n|Estimated Contract Value)", blob, re.S)
    ecv = re.search(r"Estimated Contract Value\s*:\s*([\d.,]+)", blob)
    close = re.search(r"Last Date\s*&?\s*Time For Submission\s*:\s*([\d\-/: ]+)", blob)

    return {
        "state": "Gujarat",
        "region": "Gujarat",
        "portal": "https://tender.nprocure.com/",
        "tender_id": tid.group(1),
        "ref_no": ref,
        "title": clean(work.group(1)) if work else "",
        "published": "",
        "closing": _dmy_to_gepnic(close.group(1)) if close else "",
        "opening": "",
        "organisation": dept,
        "org_chain": [p.strip() for p in dept.split("-") if p.strip()],
        "corrigendum": "",
        "detail_url": "https://tender.nprocure.com/",
        "ecv": (ecv.group(1).replace(",", "") if ecv else ""),
    }


def scrape_gujarat(state="Gujarat", headless=True, max_pages=60, timeout=120000,
                   deadline_s=900):
    from playwright.sync_api import sync_playwright

    out, seen, pages = [], set(), 0
    t_end = (time.time() + deadline_s) if deadline_s else None
    hit = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(ignore_https_errors=True)
        try:
            page.goto("https://tender.nprocure.com/", wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_selector("#DataTables_Table_0 tbody tr", timeout=timeout)
            page.wait_for_timeout(2500)

            # widen the page size so we walk 24 pages instead of 359
            try:
                page.select_option("select[name$=_length]", "150")
                page.wait_for_timeout(6000)
            except Exception:                                  # noqa: BLE001
                pass

            while pages < max_pages:
                if t_end and time.time() > t_end:
                    hit = True
                    break
                pages += 1
                for cells in page.evaluate(_GJ_ROWS_JS):
                    rec = _parse_gj_row(cells)
                    if rec and rec["tender_id"] not in seen:
                        seen.add(rec["tender_id"])
                        out.append(rec)
                nxt = page.query_selector("#DataTables_Table_0_next:not(.disabled) a, "
                                          "li.paginate_button.next:not(.disabled)")
                if not nxt:
                    break
                before = page.evaluate(_GJ_ROWS_JS)
                nxt.click()
                # wait for the table body to actually change
                for _ in range(40):
                    page.wait_for_timeout(500)
                    if page.evaluate(_GJ_ROWS_JS) != before:
                        break
                else:
                    break
        finally:
            browser.close()
    return state, out, (f"{len(out)} tenders via browser, {pages} pages"
                        + (" [DEADLINE HIT - partial]" if hit else ""))


# ------------------------------------------------------------------------ Bihar

_BIHAR_JS = """() => {
  let sc = null;
  document.querySelectorAll('[ng-controller]').forEach(el => {
    if (el.getAttribute('ng-controller') === 'openareaTenderList')
      sc = angular.element(el).scope();
  });
  if (!sc) return null;
  const orgs = {};
  (sc.orgList || []).forEach(o => { orgs[o.organizationId] = o.organizationName; });
  return { tenders: sc.allTenderList || [], orgs };
}"""


def scrape_bihar(state="Bihar", headless=True, timeout=150000):
    from playwright.sync_api import sync_playwright

    url = "https://eproc2.bihar.gov.in/EPSV2Web/openarea/tenderListingPage.action#latestTenders"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(ignore_https_errors=True)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout)
            data = None
            for _ in range(20):                    # Angular fills the scope async
                page.wait_for_timeout(1500)
                data = page.evaluate(_BIHAR_JS)
                if data and data.get("tenders"):
                    break
        finally:
            browser.close()

    if not data or not data.get("tenders"):
        return state, [], "Angular scope empty"

    orgs = data["orgs"]
    out, seen = [], set()
    for t in data["tenders"]:
        tid = str(t.get("currentOrgTenderId") or t.get("currenttenderid") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        dept = orgs.get(str(t.get("currentdeptid"))) or orgs.get(t.get("currentdeptid")) or ""
        out.append({
            "state": state,
            "region": state,
            "portal": "https://eproc2.bihar.gov.in/EPSV2Web/openarea/tenderListingPage.action",
            "tender_id": tid,
            "ref_no": clean(t.get("currenttenderrefno")),
            "title": clean(t.get("currentdescription")),
            "published": _epoch_to_gepnic(t.get("currentTenderPublishDate")),
            "closing": _epoch_to_gepnic(t.get("currentbidEndDate")),
            "opening": _epoch_to_gepnic(t.get("currentbidOpenDate")),
            "organisation": clean(dept),
            "org_chain": [clean(dept)] if dept else [],
            "corrigendum": "",
            "detail_url": "https://eproc2.bihar.gov.in/EPSV2Web/openarea/tenderListingPage.action",
            "ecv": str(t.get("currentpacamt") or ""),
        })
    return state, out, f"{len(out)} tenders via browser (Angular scope)"


# --------------------------------------------------------------------- registry

BROWSER_CUSTOM = {
    "Gujarat": scrape_gujarat,
    "Bihar":   scrape_bihar,
}


def scrape_browser(state, headless=True, deadline_s=900):
    if not _available():
        return state, [], "playwright not installed (pip install playwright)"
    try:
        fn = BROWSER_CUSTOM[state]
        if state == "Gujarat":
            return fn(state, headless=headless, deadline_s=deadline_s)
        return fn(state, headless=headless)
    except Exception as e:                                     # noqa: BLE001
        return state, [], f"ERROR {type(e).__name__}: {str(e)[:70]}"
