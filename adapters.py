"""Adapters for state portals that do NOT run NIC's GePNIC platform.

Each adapter returns tenders in the same dict shape scraper.py produces, so
the dashboard and the CSV/SQLite exports need no special-casing:

    state portal tender_id ref_no title published closing opening
    organisation org_chain corrigendum detail_url [ecv]

`ecv` (estimated contract value) is extra -- some of these platforms publish
it and GePNIC does not.
"""
from __future__ import annotations

import base64
import json
import re
import time

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def to_gepnic_date(s):
    """'08/09/2026 04:00 PM' -> '08-Sep-2026 04:00 PM' (dashboard's format)."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", str(s)).strip()
    m = re.match(r"(\d{2})[/-](\d{2})[/-](\d{4})(?:\s+(.+))?$", s)
    if not m:
        return s
    d, mo, y, rest = m.groups()
    try:
        name = MONTHS[int(mo) - 1]
    except (ValueError, IndexError):
        return s
    return f"{d}-{name}-{y}" + (f" {rest.strip()}" if rest else "")


def session(retries=3, backoff=1.5):
    """A requests session that retries transient network faults.

    Government portals drop connections under load, and a single
    ConnectionReset used to cost a whole source for the run -- ONGC vanished
    from one refresh exactly that way. urllib3 retries connect/read/status
    failures on both GET and POST here; every request in this file is a read,
    so replaying one is safe.
    """
    from requests.adapters import HTTPAdapter
    try:
        from urllib3.util.retry import Retry
    except ImportError:                                    # pragma: no cover
        from requests.packages.urllib3.util.retry import Retry

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.verify = False
    policy = Retry(total=retries, connect=retries, read=retries, status=retries,
                   backoff_factor=backoff,
                   status_forcelist=(429, 500, 502, 503, 504),
                   allowed_methods=frozenset(["GET", "POST"]))
    adapter = HTTPAdapter(max_retries=policy, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def clean(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(x or ""))).replace("\xa0", " ").strip()


# --------------------------------------------------------------- AP / Telangana

# Both states run the same platform. Its DataTables endpoint returns every
# current tender as JSON; the "encryption" fields are literal placeholders.
_APTS_QS = (
    "nTenderID=&nDepartmentID=&subDeptId=&ddlDistrict=&ddlMandal=&biddingType="
    "&sProcurementType=&mECVValue1=&mECVValue2=&dtBidClosingselect=&dtBidClosing1="
    "&dtBidClosing2=&dtTenderOpening1=&dtTenderOpening2=&hdnSearch4=&hdnSearch="
    "&hdncorrigendumsDetails=&hdncorrigendumsDetails1=&hdnnoSearch="
    "&hdncorrigendumsDetails2=&hdnadvsearch=&hdnPreviousPage=&hdnIndentID="
    "&hdnTenderCategory=&hdnProcurementID=&hdnType=current"
    "&hdnPreviousPge=TenderDetailsHome.html&hdnFromStatus="
    "&typeOfWorkFromConsolidation=&popUPRequestParameter=&selectedCircleDivison="
    "&selectedDepartmentID=&selectedProcurementType=&selectedTypeofWork=&aid="
    "&hdnEncryptNames=hdnEncryptNames&hdnEncryptValues=hdnEncryptValues"
    "&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
    "&iDisplayStart={start}&iDisplayLength={length}"
    + "".join(f"&mDataProp_{i}={i}&bSortable_{i}=true" for i in range(9))
    + "&iSortCol_0=5&sSortDir_0=desc&iSortingCols=1&_={ts}"
)


def _decode_json(text):
    """AP base64-wraps the JSON body; Telangana returns it plain."""
    t = text.strip()
    if t.startswith("{"):
        return json.loads(t)
    return json.loads(base64.b64decode(t).decode("utf-8", "replace"))


def scrape_apts(state, host, page=2000, timeout=180):
    base = f"https://{host}"
    s = session()

    r = s.post(f"{base}/login.html", timeout=60)
    form = BeautifulSoup(r.text, "html.parser").find("form")
    if form is None:
        return state, [], "login page has no form"
    data = {i.get("name"): (i.get("value") or "")
            for i in form.find_all("input") if i.get("name")}
    data["hdnType"] = "current"
    s.post(f"{base}/TenderDetailsHome.html", data=data, timeout=timeout,
           headers={"Referer": f"{base}/login.html"})

    hdrs = {"Referer": f"{base}/TenderDetailsHome.html",
            "X-Requested-With": "XMLHttpRequest"}
    rows, start = [], 0
    while True:
        qs = _APTS_QS.format(start=start, length=page, ts=int(time.time() * 1000))
        resp = s.get(f"{base}/TenderDetailsHomeJson.html?{qs}", timeout=timeout, headers=hdrs)
        batch = _decode_json(resp.text).get("aaData") or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
        if start > 100000:                      # runaway guard
            break

    out, seen = [], set()
    for row in rows:
        c = [clean(x) for x in row]
        if len(c) < 8 or not re.match(r"^\d+$", c[1] or ""):
            continue
        tid = c[1]
        if tid in seen:
            continue
        seen.add(tid)
        # last cell is the Action column; closing date sits just before it
        closing = to_gepnic_date(c[-2])
        out.append({
            "state": state,
            "region": state,
            "portal": f"{base}/TenderDetailsHome.html",
            "tender_id": tid,
            "ref_no": c[2],
            "title": c[4],
            "published": to_gepnic_date(c[6]),
            "closing": closing,
            "opening": "",
            "organisation": c[0],
            "org_chain": [p.strip() for p in c[0].split("-") if p.strip()],
            "corrigendum": "",
            "detail_url": f"{base}/TenderDetailsHome.html",
            "ecv": re.sub(r"[^\d.]", "", c[5]) if c[5] else "",
        })
    return state, out, f"{len(out)} tenders via DataTables JSON"


# ------------------------------------------------------------------ Chhattisgarh

def scrape_cg(state, host, timeout=300):
    """CHIPS CHEPS portal.

    The landing page ships an empty tender table; posting its hidden `loadForm`
    with loadAlldata=Y re-renders the page with every open tender inline.
    Rows are grouped under single-cell organisation header rows.
    """
    base = f"https://{host}/CHEPS"
    s = session()

    r = s.get(f"{base}/security/getSignInAction.do", timeout=timeout)
    form = BeautifulSoup(r.text, "html.parser").find("form", id="loadForm")
    if form is None:
        return state, [], "loadForm not found"
    data = {i["name"]: (i.get("value") or "")
            for i in form.find_all("input") if i.get("name")}
    data["loadAlldata"] = "Y"
    r2 = s.post(f"{base}/security/getSignInAction.do", data=data, timeout=timeout,
                headers={"Referer": f"{base}/security/getSignInAction.do"})

    soup = BeautifulSoup(r2.text, "html.parser")
    cands = [t for t in soup.find_all("table")
             if "SR NO" in t.get_text(" ", strip=True).upper()[:400]]
    if not cands:
        return state, [], "no tender table"
    table = max(cands, key=lambda x: len(x.find_all("tr")))

    out, org, seen = [], "", set()
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        cells = [clean(td.get_text(" ", strip=True)) for td in tds]
        nonempty = [c for c in cells if c]
        # a lone cell is an organisation heading for the rows that follow
        if len(nonempty) == 1 and len(cells) == 1:
            org = nonempty[0]
            continue
        if len(cells) < 6 or not re.match(r"^\d+$", cells[0] or ""):
            continue
        tid = cells[1]
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append({
            "state": state,
            "region": state,
            "portal": f"{base}/security/getSignInAction.do",
            "tender_id": tid,
            "ref_no": "",   # CHEPS has no separate reference number
            "title": cells[4],
            "published": to_gepnic_date_iso(cells[2]),
            "closing": to_gepnic_date_iso(cells[3]),
            "opening": "",
            "organisation": org,
            "org_chain": [org] if org else [],
            "corrigendum": "Yes" if (len(cells) > 6 and cells[6].upper() == "YES") else "",
            "detail_url": f"{base}/security/getSignInAction.do",
            "ecv": cells[5] if cells[5] and cells[5].upper() != "NA" else "",
        })
    return state, out, f"{len(out)} tenders via loadAlldata"


def to_gepnic_date_iso(s):
    """'2026-09-03 5:00:00 PM' -> '03-Sep-2026 05:00 PM'."""
    s = clean(s)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AP]M)?", s, re.I)
    if not m:
        return s
    y, mo, d, hh, mm, ap = m.groups()
    try:
        name = MONTHS[int(mo) - 1]
    except (ValueError, IndexError):
        return s
    tail = f" {int(hh):02d}:{mm}" + (f" {ap.upper()}" if ap else "")
    return f"{d}-{name}-{y}{tail}"


# ---------------------------------------------------------------------- GeM

# Government e-Marketplace. Not a tender portal -- a marketplace whose public
# "all bids" listing is backed by a Solr-style JSON API. robots.txt permits it
# (only /resources/ and some bank-guarantee endpoints are disallowed).
GEM_BASE = "https://bidplus.gem.gov.in"
_GEM_PAGE = 10                      # server-side; a "size" param is ignored


def _gem_dt(s):
    """'2026-09-02T10:00:00Z' -> '02-Sep-2026 10:00 AM'.

    The Z is a red herring: GeM stamps local (IST) times and labels them Z.
    The site renders 10:00:00Z as 10:00 AM, so treat it as wall-clock and do
    NOT shift by the UTC offset.
    """
    s = clean(s)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", s)
    if not m:
        return s
    y, mo, d, hh, mm = m.groups()
    try:
        name = MONTHS[int(mo) - 1]
    except (ValueError, IndexError):
        return s
    h24 = int(hh)
    ampm = "AM" if h24 < 12 else "PM"
    return f"{d}-{name}-{y} {h24 % 12 or 12:02d}:{mm} {ampm}"


def _gem_first(doc, key):
    v = doc.get(key)
    if isinstance(v, list):
        v = v[0] if v else ""
    return clean(v)


# GeM state names are upper-case and use a few of their own spellings.
GEM_STATE_FIX = {
    "ANDAMAN & NICOBAR": "Andaman & Nicobar", "JAMMU & KASHMIR": "Jammu & Kashmir",
    "DADRA & NAGAR HAVELI": "DNH & Daman Diu", "DAMAN & DIU": "DNH & Daman Diu",
    "NCT OF DELHI": "Delhi", "DELHI": "Delhi", "PONDICHERRY": "Puducherry",
    "ORISSA": "Odisha", "UTTARANCHAL": "Uttarakhand",
}


def _gem_state(name):
    n = clean(name).upper()
    if n in GEM_STATE_FIX:
        return GEM_STATE_FIX[n]
    return " ".join(w.capitalize() if w not in ("&",) else "&" for w in n.split())


def scrape_gem(state="GeM", host=GEM_BASE, timeout=90, conc=4,
               deadline_s=2400, max_pages=None):
    """Every ongoing GeM bid, tagged with its consignee state.

    The flat /all-bids feed carries no location at all. The advanced search
    does: `searchType=con` + `state_name_con=<STATE>` returns the bids being
    delivered to that state. Sweeping the 37 states costs about the same as
    the flat sweep (~4,450 pages vs ~4,668) and yields a `region` on every row,
    which is what makes "show me Assam across all sources" possible.

    Bids with no consignee state (~5%) are not reachable this way and are
    therefore not collected.
    """
    import concurrent.futures as cf
    import time as _t

    s = session()
    page = s.get(f"{host}/advance-search", timeout=timeout)
    m = re.search(r"csrf_bd_gem_nk'\s*:\s*'([0-9a-f]{16,})", page.text)
    token = m.group(1) if m else s.cookies.get("csrf_gem_cookie", "")
    if not token:
        return state, [], "no CSRF token on /advance-search"

    hdr = {"Referer": f"{host}/advance-search", "X-Requested-With": "XMLHttpRequest",
           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}

    try:
        states = [x["state_name"] for x in
                  s.post(f"{host}/state-list-adv", data={"csrf_bd_gem_nk": token},
                         timeout=timeout, headers=hdr).json()["data"]]
    except Exception as e:                                 # noqa: BLE001
        return state, [], f"state list failed: {type(e).__name__}"

    def query(st_name, pg):
        payload = {"searchType": "con", "state_name_con": st_name, "city_name_con": "",
                   "bidEndFromCon": "", "bidEndToCon": "", "page": pg}
        try:
            r = s.post(f"{host}/search-bids", timeout=timeout, headers=hdr,
                       data={"payload": json.dumps(payload), "csrf_bd_gem_nk": token})
            return r.json()["response"]["response"]
        except Exception:                                  # noqa: BLE001
            return None

    t_end = (_t.time() + deadline_s) if deadline_s else None
    by_bid, jobs = {}, []

    def absorb(docs, region):
        for d in docs or []:
            bid = _gem_first(d, "b_bid_number")
            if not bid:
                continue
            rec = by_bid.get(bid)
            if rec is None:
                by_bid[bid] = {"doc": d, "regions": {region}}
            else:
                rec["regions"].add(region)

    for st_name in states:
        first = query(st_name, 1)
        if not first:
            continue
        region = _gem_state(st_name)
        absorb(first.get("docs"), region)
        pages = max(1, -(-int(first.get("numFound") or 0) // _GEM_PAGE))
        if max_pages:
            pages = min(pages, max_pages)
        jobs += [(st_name, region, pg) for pg in range(2, pages + 1)]

    def worker(job):
        st_name, region, pg = job
        if t_end and _t.time() > t_end:
            return None
        r = query(st_name, pg)
        return (r.get("docs") if r else None), region

    if jobs:
        with cf.ThreadPoolExecutor(conc) as ex:
            for got in ex.map(worker, jobs):
                if got:
                    absorb(got[0], got[1])

    out = []
    for bid, rec in by_bid.items():
        d = rec["doc"]
        ministry = _gem_first(d, "ba_official_details_minName")
        dept = _gem_first(d, "ba_official_details_deptName")
        org = " - ".join(x for x in (ministry, dept) if x)
        qty = _gem_first(d, "b_total_quantity")
        # GeM links each bid number to its own bid document:
        #   /showbidDocument/<b_id>  -> the PDF for that exact bid.
        # The bid *number* is not usable in a URL and ?searchBid= is ignored,
        # so the numeric b_id is the only way to deep-link a GeM bid.
        doc_id = _gem_first(d, "b_id")
        detail = (f"{host}/showbidDocument/{doc_id}" if doc_id.isdigit()
                  else f"{host}/all-bids")
        out.append({
            "state": state,
            "region": ", ".join(sorted(rec["regions"])),
            "portal": f"{host}/all-bids",
            "tender_id": bid,
            "ref_no": "",
            "title": _gem_first(d, "b_category_name") + (f" (qty {qty})" if qty else ""),
            "published": _gem_dt(_gem_first(d, "final_start_date_sort")),
            "closing": _gem_dt(_gem_first(d, "final_end_date_sort")),
            "opening": "",
            "organisation": org,
            "org_chain": [x for x in (ministry, dept) if x],
            "corrigendum": "",
            "detail_url": detail,
            "ecv": "",
        })
    hit = " [DEADLINE HIT - partial]" if (t_end and _t.time() > t_end) else ""
    multi = sum(1 for r in by_bid.values() if len(r["regions"]) > 1)
    return state, out, (f"{len(out)} bids across {len(states)} states "
                        f"({multi:,} multi-state){hit}")


# ---------------------------------------------------------------------- ONGC

def scrape_ongc(state="ONGC", host="tenders.ongc.co.in", timeout=90):
    """ONGC's public "Current NITs" list (a Liferay portlet).

    Small and shallow: ~15 rows, no pagination, and crucially **no bid closing
    date** -- the portal only publishes an upload date. Those rows therefore
    carry no "time left" and are excluded from closing-window filters. Several
    entries are themselves GeM bid numbers, so they overlap with the GeM feed.
    """
    base = f"https://{host}"
    s = session()

    home = s.get(f"{base}/", timeout=timeout)
    # the portlet URL carries a per-session Liferay p_auth token
    m = re.search(r'href="([^"]*tender-currentNIT[^"]*)"', home.text.replace("&amp;", "&"))
    if not m:
        return state, [], "Current NITs link not found"
    url = m.group(1)
    if url.startswith("/"):
        url = base + url
    r = s.get(url, timeout=timeout, headers={"Referer": base + "/"})

    body = re.sub(r"(?is)<script.*?</script>", "", r.text)
    out, seen = [], set()
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", body):
        c = [clean(x) for x in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        if len(c) < 5 or not c[0] or c[0].lower() == "tender number":
            continue
        tid = c[0].replace(" ", "")          # portal inserts stray spaces in GEM ids
        if tid in seen:
            continue
        seen.add(tid)
        out.append({
            "state": state,
            "region": "",          # ONGC lists a city, not a state
            "portal": f"{base}/",
            "tender_id": tid,
            "ref_no": "",
            "title": c[1],
            "published": to_gepnic_date_iso(c[4]),
            "closing": "",                    # not published on this listing
            "opening": "",
            "organisation": f"ONGC - {c[3]}" if c[3] else "ONGC",
            "org_chain": ["ONGC"] + ([c[3]] if c[3] else []),
            "corrigendum": "",
            "detail_url": f"{base}/",
            "ecv": "",
        })
    return state, out, f"{len(out)} NITs (no closing dates published)"


# --------------------------------------------------------------------- registry

CUSTOM = {
    "Andhra Pradesh": (scrape_apts, "tender.apeprocurement.gov.in"),
    "Telangana":      (scrape_apts, "tender.telangana.gov.in"),
    "Chhattisgarh":   (scrape_cg,   "eproc.cgstate.gov.in"),
    "GeM":            (scrape_gem,  GEM_BASE),
    "ONGC":           (scrape_ongc, "tenders.ongc.co.in"),
}


def scrape_custom(state, timeout=180):
    fn, host = CUSTOM[state]
    return fn(state, host, timeout=timeout)
