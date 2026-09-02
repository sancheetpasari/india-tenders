"""Choose the newest available baseline and write it to tenders.json.

Candidates, in no particular order:
  published.json.gz  what the cloud page currently serves
  local.json.gz      uploaded by a machine that can reach the blocked portals
  committed.json.gz  the one-off seed in the repo

Newest wins, judged by generated_at. Writing nothing is fine -- the scraper
simply starts clean.
"""
import gzip, json, os, re
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


best = None
for name, label in (("local.json.gz", "local upload"),
                    ("published.json.gz", "last publish"),
                    ("committed.json.gz", "committed seed")):
    if not os.path.exists(name):
        continue
    try:
        d = json.loads(gzip.open(name, "rb").read().decode("utf-8"))
    except Exception as e:                                    # noqa: BLE001
        print(f"  {label:<16} unreadable ({type(e).__name__})")
        continue
    when = stamp(d.get("generated_at", ""))
    print(f"  {label:<16} {d.get('count', 0):>8,} tenders  {d.get('generated_at')}")
    if best is None or when > best[0]:
        best = (when, name, label, d)

if best is None:
    print("no baseline available - starting clean")
else:
    _, name, label, d = best
    with open("tenders.json", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    print(f"=> using the {label}: {d['count']:,} tenders from {d['generated_at']}")
