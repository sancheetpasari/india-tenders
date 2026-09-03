"""Rebuild the shareable single-file page from the latest tenders.json.

Run automatically after each scrape (see refresh-tenders.bat), so
`share/tender-registry.html` always reflects the most recent data and
publishing it is a single step.

    python build_artifact.py

Output is pure ASCII and self-contained: no external data, no CDN. Fonts come
from Google Fonts, the one host the artifact CSP allows.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "share", "tender-registry.template.html")
OUT = os.path.join(HERE, "share", "tender-registry.html")
SRC = os.path.join(HERE, "tenders.json")

TITLE_MAX = 170
HARD_CAP  = 16_000_000          # artifact hosting limit
CAP_BYTES = 15_000_000          # aim under it, so a slow week of growth
                                # does not suddenly fail the nightly build
BS = chr(92)


from send_reminders import mark_key


def trim(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "..."


MONTHS_I = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def closing_within(t, days, now):
    """True if this tender closes inside `days` of now.

    Rows with no published closing date (ONGC) can't be placed on the
    timeline, so a windowed build drops them.
    """
    import re as _re
    from datetime import timedelta
    m = _re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", t.get("closing") or "")
    if not m:
        return False
    from datetime import datetime
    try:
        d = datetime(int(m.group(3)), MONTHS_I[m.group(2)], int(m.group(1)))
    except (ValueError, KeyError):
        return False
    return now - timedelta(days=1) <= d <= now + timedelta(days=days)


def _doc_id(t):
    """Numeric id for a GeM bid document, so the shared page can deep-link it.

    Storing the id alone rather than the whole URL keeps ~40,000 GeM rows to a
    few hundred KB instead of a few MB.
    """
    u = t.get("detail_url") or ""
    m = re.search(r"/showbidDocument/(\d+)", u)
    return m.group(1) if m else ""


def marked_keys():
    """Keys of the tenders marked "I intend to bid", if any were saved.

    Off unless --with-marks is passed. This page gets published to a public
    URL, and a star against a tender tells anyone reading it which contracts
    you intend to bid for.
    """
    if "--with-marks" not in sys.argv:
        return set()
    try:
        with open(os.path.join(HERE, "interested.json"), encoding="utf-8") as f:
            return set(json.load(f).get("marks", {}))
    except (OSError, ValueError):
        return set()


SP_RE = re.compile(r"[?&]sp=([^&]+)")


def _link(t):
    """What the shared page needs to reach this tender.

    GePNIC deep links are all the same URL with a different 25-character sp
    token, so store the token and rebuild the rest in the browser: 55,000
    rows cost ~1.4 MB instead of ~11 MB. Everything else keeps its own URL.
    GeM is already covered by _doc_id.
    """
    u = t.get("detail_url") or ""
    if not u or "showbidDocument" in u:
        return ""
    m = SP_RE.search(u)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return u


def build_payload(data, rows_override=None):
    rows_in = rows_override if rows_override is not None else data["tenders"]
    states = sorted({t.get("state", "") for t in rows_in})
    orgs = sorted({t.get("organisation", "") for t in rows_in})
    si = {s: i for i, s in enumerate(states)}
    oi = {o: i for i, o in enumerate(orgs)}
    # one portal entry URL per state. Per-tender deep links are session-scoped
    # on GePNIC and would add ~6 MB, so the state name links to its portal and
    # the tender ID is shown for searching there.
    portals = [""] * len(states)
    for t in rows_in:
        i = si[t.get("state", "")]
        if not portals[i] and t.get("portal"):
            portals[i] = t["portal"]
    # column arrays + interned state/department strings: ~183 bytes a tender
    rows = [[si[t.get("state", "")], oi.get(t.get("organisation", ""), 0),
             t.get("tender_id", ""), trim(t.get("title", ""), TITLE_MAX),
             t.get("published", ""), t.get("closing", ""), t.get("ecv") or "",
             t.get("region", ""), t.get("sector", ""), _doc_id(t), _link(t)]
            for t in rows_in]
    # row indices rather than a flag per row: marks number in the tens, rows
    # in the hundreds of thousands
    keys = marked_keys()
    marked = [i for i, t in enumerate(rows_in)
              if mark_key(t) in keys] if keys else []
    return {"generated_at": data["generated_at"], "window": data["window_days"],
            "states": states, "portals": portals, "orgs": orgs, "rows": rows,
            "marked": marked}


def render(tpl, payload):
    """Embed the payload gzipped + base64.

    Raw JSON for the full dataset is ~21 MB, over the 16 MB page limit, which
    used to force the shared copy down to a 7-day window. Gzip takes it to
    ~5 MB (~6.6 MB once base64-encoded), so the whole dataset fits and the
    shared page matches the local dashboard. The page inflates it with
    DecompressionStream, which every current browser has.

    base64 is [A-Za-z0-9+/=] only, so nothing in it can close the script tag.
    """
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    packed = base64.b64encode(gzip.compress(raw.encode("utf-8"), 9)).decode("ascii")
    out = tpl.replace("__PAYLOAD__", packed)
    return out, len(out.encode("utf-8"))


def main():
    if not os.path.exists(SRC):
        sys.exit("tenders.json not found -- run scraper.py first.")
    if not os.path.exists(TEMPLATE):
        sys.exit(f"template missing: {TEMPLATE}")

    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("partial"):
        print("note: tenders.json is from a run still in progress; building anyway")

    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    if "__PAYLOAD__" not in tpl:
        sys.exit("template has no __PAYLOAD__ placeholder")

    from datetime import datetime
    now = datetime.now()
    total = len(data["tenders"])

    # Try the whole dataset; if the page would blow the hosting cap, narrow the
    # closing window step by step until it fits, and record what was applied so
    # the page can say so rather than quietly under-reporting.
    payload = build_payload(data)
    out, size = render(tpl, payload)
    applied = None
    if size > CAP_BYTES:
        for days in (14, 10, 7, 5, 4, 3, 2):
            subset = [t for t in data["tenders"] if closing_within(t, days, now)]
            if not subset:
                continue
            payload = build_payload(data, subset)
            payload["window"] = days
            payload["capped_from"] = total
            out, size = render(tpl, payload)
            print(f"  trying {days:>2}-day window: {len(subset):,} tenders -> {size / 1e6:.1f} MB")
            if size <= CAP_BYTES:
                applied = days
                break
        else:
            sys.exit(f"even a 2-day window is {size / 1e6:.1f} MB, over the cap -- "
                     f"lower TITLE_MAX or drop a source")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, OUT)

    print(f"built {OUT}")
    print(f"  {len(payload['rows']):,} tenders | {len(payload['states'])} states | "
          f"{len(payload['orgs']):,} departments")
    print(f"  snapshot {payload['generated_at']} | {size / 1e6:.2f} MB "
          f"({(HARD_CAP - size) / 1e6:.1f} MB under the {HARD_CAP // 10**6} MB limit)")
    if applied:
        print(f"  NOTE: capped to a {applied}-day closing window to fit the 16 MB limit "
              f"({total - len(payload['rows']):,} of {total:,} tenders omitted; "
              f"the local dashboard still has all of them)")


if __name__ == "__main__":
    main()
