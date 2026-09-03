"""Send this machine's scrape up to GitHub so the cloud page can use it.

Four sources refuse GitHub's runner IPs -- GeM outright, plus Andhra Pradesh,
Chhattisgarh and Gujarat. This laptop can reach them, so after a local scrape
we upload the dataset and the next cloud run merges it in.

The upload goes to a GitHub *release asset*, replaced in place, not a commit:
8 MB twice a day would add half a gigabyte of git history a month.

    python push_to_cloud.py                # dataset + the bid list
    python push_to_cloud.py --marks-only   # just the bid list, in a second

Needs the GitHub CLI, already authenticated (`gh auth status`).
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "tenders.json")
UPLOAD_DIR = os.path.join(HERE, "_upload")
TMP = os.path.join(UPLOAD_DIR, "tenders.json.gz")
TAG = "local-data"
TITLE = "Latest local scrape"

GH_CANDIDATES = [
    shutil.which("gh"),
    r"C:\Program Files\GitHub CLI\gh.exe",
    r"C:\Program Files (x86)\GitHub CLI\gh.exe",
]


def gh_path():
    for c in GH_CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("GitHub CLI not found. Install it, then run: gh auth login")


def run(gh, *args, check=True):
    p = subprocess.run([gh, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed:\n{p.stderr.strip()}")
    return p


def push_marks(gh):
    """Send the bid list to the reminder job -- as a repository secret.

    Not as a release asset: this repository is public and so are its assets,
    and which contracts you intend to bid for is not something to publish.
    Secrets are encrypted at rest, masked in logs, and readable only by the
    workflow. GitHub caps one at 48 KB, so keep the payload lean.
    """
    path = os.path.join(HERE, "interested.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        marks = json.load(f).get("marks", {})
    if not marks:
        return

    lean = {k: {f: str(v.get(f) or "")[:200] for f in
                ("title", "state", "organisation", "closing", "detail_url")}
            for k, v in marks.items()}
    body = json.dumps({"marks": lean}, ensure_ascii=False, separators=(",", ":"))
    if len(body.encode()) > 40000:
        print(f"   {len(marks)} marks exceed the 48 KB secret limit "
              f"({len(body.encode()):,} bytes); reminders will use the last "
              "list that fit. Untick a few you are no longer chasing.")
        return

    p = subprocess.run([gh, "secret", "set", "INTERESTED_MARKS"],
                       input=body, capture_output=True, text=True)
    if p.returncode != 0:
        print(f"   could not update the bid list: {p.stderr.strip()[:160]}")
    else:
        print(f"   marked interested  {len(marks):>5}  (kept private)")


def main():
    gh = gh_path()
    if run(gh, "auth", "status", check=False).returncode != 0:
        sys.exit("Not logged in. Run:  gh auth login")

    # Marks change between scrapes. Syncing them alone takes a second, where a
    # full run re-uploads 8 MB, so a tender ticked this afternoon can reach
    # tomorrow's reminder without waiting for midnight.
    if "--marks-only" in sys.argv:
        push_marks(gh)
        return

    if not os.path.exists(SRC):
        sys.exit("tenders.json not found -- run scraper.py first.")

    with open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    if d.get("partial"):
        sys.exit("that scrape is still running; not uploading a partial dataset")

    # Only worth uploading if we actually hold the sources the cloud cannot get.
    blocked = {"GeM", "Andhra Pradesh", "Chhattisgarh", "Gujarat"}
    have = {s["state"]: s["count"] for s in d["sources"]
            if s["state"] in blocked and s["count"]}
    if not have:
        sys.exit("this dataset has none of the cloud-blocked sources; nothing to add")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    raw = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(TMP, "wb", compresslevel=9) as f:
        f.write(raw)
    size = os.path.getsize(TMP) / 1e6

    print(f"uploading {d['count']:,} tenders ({d['generated_at']}), {size:.1f} MB")
    for k, v in sorted(have.items(), key=lambda x: -x[1]):
        print(f"   {k:<18}{v:>7,}")

    # create the release once; thereafter just replace the asset
    if run(gh, "release", "view", TAG, check=False).returncode != 0:
        run(gh, "release", "create", TAG, "--title", TITLE, "--notes",
            "Most recent scrape from a machine that can reach GeM, Andhra "
            "Pradesh, Chhattisgarh and Gujarat. Replaced automatically; "
            "not part of the git history.")
        print(f"created release '{TAG}'")

    run(gh, "release", "upload", TAG, TMP, "--clobber")

    push_marks(gh)
    os.remove(TMP)
    os.rmdir(UPLOAD_DIR)
    print(f"done -- the next cloud refresh will merge this in")


if __name__ == "__main__":
    main()
