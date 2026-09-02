"""Scrape active tenders from Indian state e-procurement portals (GePNIC).

Source page: <portal>/<ctx>/app?page=FrontEndListTendersbyDate
This is the "Tenders by Closing Date" listing -- the only substantial
tender listing on GePNIC that is not gated behind a captcha. We POST the
Tapestry form to switch the window to "Closing within 14 days", then walk
the pager.

States on non-GePNIC platforms (Andhra Pradesh, Telangana, Chhattisgarh) are
handled by adapters.py and merged into the same output.

Usage:
    python scraper.py                     # 14-day window, all portals
    python scraper.py --window 7
    python scraper.py --states Maharashtra "Tamil Nadu"
    python scraper.py --max-pages 5       # quick smoke run
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import html
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

import adapters
import browser_adapters
import portals
import sector

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
IST = timezone(timedelta(hours=5, minutes=30))

PAGE = "FrontEndListTendersbyDate"
TENDER_ID_RE = re.compile(r"(\d{4}_[A-Za-z0-9]+_\d+_\d+)")
DATE_RE = re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}")

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


# --------------------------------------------------------------------------- parsing

def _cells(row_html):
    return [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row_html)]


def parse_rows(page_html, state, host, ctx):
    """Extract tender rows from a listing page."""
    body = re.sub(r"(?is)<script.*?</script>", "", page_html)
    out = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", body):
        c = _cells(row)
        if len(c) < 6 or not re.match(r"^\d+\.?$", c[0]) or not DATE_RE.search(c[1]):
            continue

        title_cell = c[4]
        tid = TENDER_ID_RE.search(title_cell)
        tender_id = tid.group(1) if tid else ""

        # "[Title] [Ref No][Tender ID]"  -- title may itself contain brackets
        title, ref_no = title_cell, ""
        groups = re.findall(r"\[([^\[\]]*)\]", title_cell)
        if groups:
            if tender_id and groups[-1].strip() == tender_id:
                ref_no = groups[-2].strip() if len(groups) >= 2 else ""
                cut = title_cell.rfind("[" + (ref_no or tender_id))
                title = title_cell[:cut].strip() if cut > 0 else groups[0]
            else:
                title = groups[0]
        title = title.strip().strip("[]").strip()

        org_chain = [p.strip() for p in c[5].split("||") if p.strip()]
        # detail link (session-scoped on GePNIC, kept for convenience)
        href = re.search(r'href="([^"]*DirectLink[^"]*)"', row)

        out.append({
            "state": state,
            # a state portal's tenders are, by definition, that state's
            "region": "" if state in portals.CENTRAL_SOURCES else state,
            "portal": f"https://{host}/{ctx}/app",
            "tender_id": tender_id,
            "ref_no": ref_no,
            "title": title,
            "published": c[1],
            "closing": c[2],
            "opening": c[3],
            "organisation": org_chain[0] if org_chain else "",
            "org_chain": org_chain,
            "corrigendum": c[6].strip() if len(c) > 6 and c[6].strip() not in ("", "&nbsp") else "",
            "detail_url": (f"https://{host}{html.unescape(href.group(1))}" if href else ""),
        })
    return out


def parse_form(page_html, form_id="ListTendersbyDate"):
    soup = BeautifulSoup(page_html, "html.parser")
    form = soup.find("form", id=form_id)
    if form is None:
        return None, None
    pairs = []
    for inp in form.find_all(["input", "textarea"]):
        name = inp.get("name")
        if name:
            pairs.append((name, inp.get("value", "") or ""))
    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        pairs.append((name, opt.get("value", "") if opt else ""))
    return pairs, form.get("action")


# --------------------------------------------------------------------------- fetching

def _walk_once(s, get, post, state, host, ctx, base, entry, window, max_pages,
               timeout, conc, t_end=None):
    """One full walk of the pager. Returns (rows, total_pages) or (None, reason)."""
    r = get(entry)
    pairs, action = parse_form(r.text)
    if pairs is None:
        return None, f"no form (HTTP {r.status_code})"

    pairs = [(k, v) for k, v in pairs if k not in ("submitmode", "submitname")]
    pairs += [("submitmode", ""), ("submitname", portals.WINDOWS[window])]
    try:
        r2 = post(f"https://{host}{action}", pairs, entry)
    except Exception as e:                             # noqa: BLE001
        return None, f"POST failed: {type(e).__name__}"

    rows = parse_rows(r2.text, state, host, ctx)
    last = re.findall(r'linkLast[^"]*sp=(\d+)', r2.text)
    total_pages = int(last[0]) if last else 1
    if max_pages:
        total_pages = min(total_pages, max_pages)

    def fetch_page(pg):
        # past the deadline the remaining pages drain instantly instead of
        # each waiting out its own timeout
        if t_end and time.time() > t_end:
            return []
        url = (f"{base}?component=%24TablePages.linkPage&page={PAGE}"
               f"&service=direct&session=T&sp=A{PAGE}%2Ctable&sp={pg}")
        try:
            return parse_rows(get(url, headers={"Referer": entry}).text, state, host, ctx)
        except Exception:                              # noqa: BLE001
            return []

    if total_pages > 1:
        with cf.ThreadPoolExecutor(conc) as ex:
            for chunk in ex.map(fetch_page, range(2, total_pages + 1)):
                rows.extend(chunk)
    return rows, total_pages


def scrape_portal(state, host, ctx, window="14", max_pages=None,
                  timeout=150, retries=2, passes=5, conc=3, deadline_s=900):
    """Scrape one portal.

    GePNIC sorts this listing by closing date with no stable tiebreaker, so
    rows sharing a closing time shuffle between pages on every request: a
    single walk of the pager both repeats some tenders and misses others
    (~75% coverage). We therefore walk it several times with a fresh session
    and union the results, stopping once a pass stops finding anything new.

    `deadline_s` caps how long one portal may take. A portal having a slow day
    used to hold up the whole run -- UP once took 95 minutes when its server
    slowed 8x. Past the deadline we keep whatever has been collected and stop,
    which costs a little coverage instead of the entire run.
    """
    base = f"https://{host}/{ctx}/app"
    entry = f"{base}?page={PAGE}&service=page"
    t0 = time.time()
    t_end = (t0 + deadline_s) if deadline_s else None
    union, total_pages, npass, timed_out = {}, 0, 0, False

    for npass in range(1, passes + 1):
        if t_end and time.time() > t_end:
            timed_out = True
            npass -= 1
            break
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        s.verify = False

        def get(url, **kw):
            last = None
            for attempt in range(retries + 1):
                try:
                    return s.get(url, timeout=timeout, **kw)
                except Exception as e:                 # noqa: BLE001
                    last = e
                    time.sleep(1.5 * (attempt + 1))
            raise last

        def post(url, pairs, referer):
            """Retry the filter POST -- one dropped connection must not cost a whole state."""
            last = None
            for attempt in range(retries + 1):
                try:
                    return s.post(url, data=pairs, timeout=timeout,
                                  headers={"Referer": referer})
                except Exception as e:                 # noqa: BLE001
                    last = e
                    time.sleep(1.5 * (attempt + 1))
            raise last

        try:
            rows, info = _walk_once(s, get, post, state, host, ctx, base, entry,
                                    window, max_pages, timeout, conc, t_end)
        except Exception as e:                         # noqa: BLE001
            if union:
                break
            return state, [], f"ERROR {type(e).__name__}: {str(e)[:60]}"
        if rows is None:
            return state, [], info
        total_pages = max(total_pages, info)

        before = len(union)
        for t in rows:
            union.setdefault(t["tender_id"] or (t["title"], t["closing"]), t)
        if not union:
            return state, [], "no tenders in window"
        # converged once a whole pass adds essentially nothing
        if npass > 1 and len(union) - before < max(3, 0.005 * len(union)):
            break
        if t_end and time.time() > t_end:
            timed_out = True
            break

    tenders = list(union.values())
    est = total_pages * 10
    cov = f", ~{min(100, round(100 * len(tenders) / est))}% of ~{est}" if est > 10 else ""
    note = (f"{len(tenders)} tenders / {total_pages} pages / {npass} passes"
            f"{cov} in {time.time() - t0:.0f}s"
            + (" [DEADLINE HIT - partial]" if timed_out else ""))
    return state, tenders, note


# --------------------------------------------------------------------------- output

COLS = ["state", "region", "sector", "tender_id", "ref_no", "title", "organisation",
        "published", "closing", "opening", "corrigendum", "ecv", "portal", "detail_url"]


def _replace(tmp, final):
    """Swap a finished temp file into place so readers never see a half-written one."""
    os.replace(tmp, final)


def write_outputs(tenders, meta, outdir=".", partial=False):
    """Write tenders.json / .csv / .db.

    Called after every portal finishes, not just at the end, so a slow portal
    can no longer hold the other 30-odd hostage. Each file is written to a
    temp path and swapped in atomically -- the dashboard may fetch
    tenders.json at any moment and must never get a truncated file.
    """
    # tag here rather than at scrape time, so rows carried over from a previous
    # run pick up any edit to sector.py on the very next write
    for t in tenders:
        t["sector"] = sector.tag(t)

    payload = {"generated_at": meta["generated_at"], "window_days": meta["window"],
               "sources": meta["sources"], "unsupported": meta["unsupported"],
               "partial": partial, "count": len(tenders), "tenders": tenders}
    with open(f"{outdir}/tenders.json.tmp", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    _replace(f"{outdir}/tenders.json.tmp", f"{outdir}/tenders.json")

    with open(f"{outdir}/tenders.csv.tmp", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(tenders)
    _replace(f"{outdir}/tenders.csv.tmp", f"{outdir}/tenders.csv")

    dbtmp = f"{outdir}/tenders.db.tmp"
    if os.path.exists(dbtmp):
        os.remove(dbtmp)
    con = sqlite3.connect(dbtmp)
    con.execute("DROP TABLE IF EXISTS tenders")
    con.execute("""CREATE TABLE tenders (state TEXT, region TEXT, sector TEXT,
                   tender_id TEXT, ref_no TEXT, title TEXT, organisation TEXT,
                   published TEXT, closing TEXT, opening TEXT, corrigendum TEXT,
                   ecv TEXT, portal TEXT, detail_url TEXT)""")
    con.executemany("INSERT INTO tenders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(t.get(c, "") for c in COLS) for t in tenders])
    con.execute("CREATE INDEX idx_state ON tenders(state)")
    con.execute("CREATE INDEX idx_region ON tenders(region)")
    con.execute("CREATE INDEX idx_sector ON tenders(sector)")
    con.commit()
    con.close()
    _replace(dbtmp, f"{outdir}/tenders.db")

    # Small poll target. The dashboard checks this every 30s and only pulls the
    # ~33 MB tenders.json when generated_at actually changes.
    status = {"generated_at": meta["generated_at"], "count": len(tenders),
              "partial": partial,
              # sources holding data, not just those refreshed this run
              "portals_done": len([x for x in meta["sources"] if x.get("count")]),
              "portals_fresh": len([x for x in meta["sources"] if x["status"] == "ok"])}
    with open(f"{outdir}/status.json.tmp", "w", encoding="utf-8") as f:
        json.dump(status, f)
    _replace(f"{outdir}/status.json.tmp", f"{outdir}/status.json")


class RunLock:
    """Stop two scrapes running at once.

    With scheduled runs at 00:00 and 12:00 plus manual ones, overlapping
    scrapes would double the load on every portal and interleave their writes.
    A stale lock (crashed run) older than 3 h is ignored.
    """

    def __init__(self, outdir, max_age=3 * 3600):
        self.path = os.path.join(outdir, ".scrape.lock")
        self.max_age = max_age
        self.held = False

    def __enter__(self):
        if os.path.exists(self.path):
            age = time.time() - os.path.getmtime(self.path)
            if age < self.max_age:
                raise RuntimeError(
                    f"another scrape started {age / 60:.0f} min ago "
                    f"(delete {self.path} if that is wrong)")
            log(f"ignoring stale lock ({age / 3600:.1f} h old)")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass


def load_baseline(outdir):
    """Previous run's tenders, grouped by state.

    Mid-run writes merge fresh results *over* this, so a refresh never shows
    less than what was already there -- and an aborted run (machine sleeps,
    process killed) can't leave a truncated dataset behind.
    """
    try:
        with open(f"{outdir}/tenders.json", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:                                  # noqa: BLE001
        return {}, None, {}          # first run: no baseline to carry forward
    by_state = {}
    for t in prev.get("tenders", []):
        by_state.setdefault(t.get("state", ""), []).append(t)
    prev_sources = {x.get("state"): x for x in prev.get("sources", [])}
    return by_state, prev.get("generated_at"), prev_sources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", choices=["today", "7", "14"], default="14")
    ap.add_argument("--states", nargs="*", help="limit to these states")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8, help="portals in parallel")
    ap.add_argument("--passes", type=int, default=5,
                    help="max walks per portal; more = better coverage (see scrape_portal)")
    ap.add_argument("--conc", type=int, default=3, help="requests in flight per portal")
    ap.add_argument("--deadline", type=int, default=900,
                    help="max seconds per GePNIC portal before keeping partial "
                         "results and moving on (0 = no limit)")
    ap.add_argument("--no-browser", action="store_true",
                    help="skip the Playwright-driven states (Gujarat, Bihar)")
    ap.add_argument("--no-custom", action="store_true",
                    help="skip the non-GePNIC states handled by adapters.py")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    targets = [(s, h, c) for s, h, c in portals.active_portals()
               if not args.states or s in args.states]
    custom = [s for s in portals.CUSTOM_SUPPORTED
              if (not args.states or s in args.states) and not args.no_custom]
    browser = [s for s in portals.BROWSER_SUPPORTED
               if (not args.states or s in args.states)
               and not args.no_custom and not args.no_browser]
    log(f"Scraping {len(targets)} GePNIC portals (window={args.window} days, "
        f"up to {args.passes} passes) + {len(custom)} custom-platform states"
        f" + {len(browser)} browser-driven states\n")

    expected = [s for s, _, _ in targets] + custom + browser
    baseline, baseline_at, prev_sources = load_baseline(args.outdir)
    if baseline:
        log(f"carrying forward {sum(len(v) for v in baseline.values()):,} tenders "
            f"from {baseline_at} until each state is re-scraped\n")

    fresh, sources = {}, []
    t0 = time.time()
    done, last_write = 0, 0.0


    def carried_sources(carried):
        """Source rows for states whose data we kept rather than re-scraped."""
        out = []
        failed = {x["state"]: x.get("note", "") for x in sources if not x.get("count")}
        for st_ in carried:
            why = failed.get(st_, "")
            note = f"kept from {baseline_at}"
            if why:
                note += f"; this run: {why[:80]}"
            out.append({"state": st_, "count": len(baseline[st_]), "status": "stale",
                        "note": note})
        for st_, rows_ in baseline.items():          # not part of this run at all
            if st_ not in expected and st_ not in carried:
                prev = prev_sources.get(st_, {})
                out.append({"state": st_, "count": len(rows_), "status": "stale",
                            "note": prev.get("note") or f"kept from {baseline_at}"})
        # A source that legitimately returned zero has no rows to carry, so it
        # would silently drop off the coverage list after a partial run. Keep
        # its entry: "checked, empty" is information, absence is not.
        seen_ = {x["state"] for x in out} | set(expected)
        for st_, prev in prev_sources.items():
            if st_ not in seen_ and not prev.get("count"):
                out.append({"state": st_, "count": 0, "status": prev.get("status", "empty"),
                            "note": prev.get("note") or f"kept from {baseline_at}"})
        return out

    def merged_rows():
        """Fresh data where we have it, previous run's data everywhere else."""
        out, carried = [], []
        for st_ in expected:
            if fresh.get(st_):
                out.extend(fresh[st_])
            elif baseline.get(st_):
                out.extend(baseline[st_])
                carried.append(st_)
        for st_, rows_ in baseline.items():            # states no longer scraped
            if st_ not in expected:
                out.extend(rows_)
        return out, carried
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(scrape_portal, s, h, c, args.window, args.max_pages,
                          passes=args.passes, conc=args.conc,
                          deadline_s=args.deadline): s
                for s, h, c in targets}
        futs.update({ex.submit(adapters.scrape_custom, s): s for s in custom})
        futs.update({ex.submit(browser_adapters.scrape_browser, s,
                               deadline_s=args.deadline): s for s in browser})
        for fut in cf.as_completed(futs):
            state = futs[fut]
            try:
                st, rows, note = fut.result()
            except Exception as e:                     # noqa: BLE001
                st, rows, note = state, [], f"ERROR {type(e).__name__}: {e}"
            status = "ok" if rows else "empty"
            sources.append({"state": st, "count": len(rows), "status": status, "note": note})
            fresh[st] = rows
            log(f"  {'OK ' if rows else '-- '} {st:<22} {note}")

            # publish what we have so far; a straggler no longer blocks the rest
            done += 1
            if done == len(futs) or time.time() - last_write > 20:
                rows_out, carried = merged_rows()
                cs = carried_sources(carried)
                dropped = {x["state"] for x in cs}
                srcs = [x for x in sources
                        if x.get("count") or x["state"] not in dropped] + cs
                write_outputs(rows_out,
                              {"generated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
                               "window": args.window,
                               "sources": sorted(srcs, key=lambda x: -x["count"]),
                               "unsupported": portals.UNSUPPORTED},
                              args.outdir, partial=(done < len(futs)))
                last_write = time.time()

    # A state that failed this run keeps its previous data rather than vanishing.
    all_t, carried = merged_rows()
    cs = carried_sources(carried)
    dropped = {x["state"] for x in cs}
    sources = [x for x in sources if x.get("count") or x["state"] not in dropped] + cs
    sources.sort(key=lambda x: -x["count"])
    meta = {"generated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "window": args.window, "sources": sources,
            "unsupported": portals.UNSUPPORTED}
    write_outputs(all_t, meta, args.outdir)

    ok = sum(1 for s in sources if s["status"] == "ok")
    if carried:
        log(f"\n  note: kept previous data for {len(carried)} state(s): {', '.join(carried)}")
    log(f"\n{len(all_t):,} tenders from {ok}/{len(targets) + len(custom) + len(browser)} "
        f"portals in {time.time() - t0:.0f}s")
    log(f"Wrote tenders.json / tenders.csv / tenders.db in {args.outdir}")


if __name__ == "__main__":
    _outdir = "."
    if "--outdir" in sys.argv:
        _outdir = sys.argv[sys.argv.index("--outdir") + 1]
    try:
        with RunLock(_outdir):
            main()
    except RuntimeError as e:
        # a scheduled run firing while another is still going just steps aside
        log(f"skipped: {e}")
