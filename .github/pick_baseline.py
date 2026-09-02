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
from datetime import datetime

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
        # the base is only relaying
        if st in stale and s.get("status") == "ok" and s.get("count"):
            by_state[st] = rows.get(st, [])
            srcs[st] = dict(s)
            srcs[st]["note"] = (f"{s.get('note', '')} (from {c['label']}, "
                                f"{c['data'].get('generated_at')})").strip()
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
