"""Assemble the best available baseline and write it to tenders.json.

Candidates:
  published.json.gz  what the cloud page currently serves
  local.json.gz      uploaded by a machine that can reach the blocked portals
  committed.json.gz  the one-off seed in the repo

Picking "whichever file is newest overall" is wrong. The cloud publishes after
the laptop uploads, so the published copy is almost always the newer file --
yet for GeM, Andhra Pradesh, Chhattisgarh and Gujarat it only ever holds a
relayed copy that the cloud can never refresh, while the laptop upload holds
those same sources freshly scraped.

So: take the newest file as the base, then for any source the base is only
carrying forward ("stale"), overlay a candidate that actually scraped it.
Freshness is judged per source, not per file.
"""
import gzip
import json
import os
import re
from datetime import datetime, timedelta

MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def stamp(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", s or "")
    if m:
        return datetime(*(int(g) for g in m.groups()))
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}):(\d{2})", s or "")
    if m:
        return datetime(int(m.group(3)), MON[m.group(2)], int(m.group(1)),
                        int(m.group(4)), int(m.group(5)))
    return datetime.min


SITES = re.compile(r"(\d+)\s+of\s+(\d+)\s+\S+.*?bodies")


def covered(note):
    """How many of a multi-site source's sites a run actually read.

    Sources that read one portal say nothing of the sort; they return 1 so a
    straight comparison never fires on them and the stale rule still governs.
    """
    m = SITES.search(note or "")
    return int(m.group(1)) if m else 1


def load(name, label):
    if not os.path.exists(name):
        return None
    try:
        d = json.loads(gzip.open(name, "rb").read().decode("utf-8"))
    except Exception as e:                                    # noqa: BLE001
        print(f"  {label:<16} unreadable ({type(e).__name__})")
        return None
    print(f"  {label:<16} {d.get('count', 0):>8,} tenders  {d.get('generated_at')}")
    return {"label": label, "when": stamp(d.get("generated_at", "")), "data": d}


cands = [c for c in (load("local.json.gz", "local upload"),
                     load("published.json.gz", "last publish"),
                     load("committed.json.gz", "committed seed")) if c]

if not cands:
    print("no baseline available - starting clean")
    raise SystemExit(0)

base = max(cands, key=lambda c: c["when"])
d = base["data"]
print(f"=> base: {base['label']} ({d['count']:,} tenders)")

# which sources is the base merely carrying forward?
stale = {s["state"] for s in d.get("sources", []) if s.get("status") == "stale"}
by_state = {}
for t in d.get("tenders", []):
    by_state.setdefault(t.get("state", ""), []).append(t)
srcs = {s["state"]: s for s in d.get("sources", [])}

adopted = []
for c in sorted(cands, key=lambda c: -c["when"].timestamp()):
    if c is base:
        continue
    other = {s["state"]: s for s in c["data"].get("sources", [])}
    rows = {}
    for t in c["data"].get("tenders", []):
        rows.setdefault(t.get("state", ""), []).append(t)
    for st, s in other.items():
        # only adopt a source this candidate genuinely scraped, to replace one
        # the base is only relaying -- and only if it is actually newer, so a
        # stale upload can never overwrite a more recent relay
        # Compare scrape times only when both sides carry one. Falling back to
        # the file timestamps would reintroduce the very bug this avoids: the
        # publish is the newer *file* while holding the older *source*.
        mine, theirs = s.get("scraped_at"), srcs.get(st, {}).get("scraped_at")
        newer = not (mine and theirs) or stamp(mine) > stamp(theirs)

        # A source that reads many sites can half-succeed. The runner reached
        # 3 of 11 banks and marked the source "ok", which hid the laptop's 4
        # of 11 -- tscb.bank.in refuses GitHub's IPs, so the one tender that
        # mattered was in the laptop's copy and nowhere else. "ok" is not the
        # question; how much of the source each side actually got is.
        wider = covered(s.get("note")) > covered(srcs.get(st, {}).get("note"))

        # A wider copy is worth having even when it is the older one. The
        # sites the cloud cannot reach it will never reach, so waiting for a
        # fresher cloud run does not recover them -- but a copy left behind
        # for days should not win either, hence the day's grace.
        day = timedelta(days=1, hours=12)
        recent_enough = (not (mine and theirs)
                         or stamp(mine) > stamp(theirs) - day)

        if s.get("status") == "ok" and s.get("count") \
                and ((st in stale and newer) or (wider and recent_enough)):
            by_state[st] = rows.get(st, [])
            srcs[st] = dict(s)
            when = s.get("scraped_at") or c["data"].get("generated_at")
            srcs[st]["scraped_at"] = when
            srcs[st]["note"] = (f"{s.get('note', '')} "
                                f"(from {c['label']}, {when})").strip()
            stale.discard(st)
            adopted.append(f"{st} <- {c['label']}")

if adopted:
    d["tenders"] = [t for rows in by_state.values() for t in rows]
    d["sources"] = list(srcs.values())
    d["count"] = len(d["tenders"])
    print("   adopted fresher sources: " + ", ".join(adopted))

with open("tenders.json", "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
print(f"=> baseline written: {d['count']:,} tenders")
