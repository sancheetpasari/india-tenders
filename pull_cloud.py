"""Take the cloud's published dataset as this machine's starting point.

The laptop cannot finish a full 43-source scrape. It sleeps: Modern Standby
puts it out after a few idle minutes and the run dies part way through, at any
hour, whatever the schedule. Twenty-five minutes unattended is simply not
available on this machine.

It does not need to do that work anyway. GitHub Actions already scrapes 39 of
the 43 sources twice a day. Only four refuse its runners -- GeM, Gujarat,
Andhra Pradesh and Chhattisgarh -- and those are the laptop's whole job, about
fourteen minutes, which does fit in a waking window.

So: pull the published dataset, let the scraper merge four freshly scraped
sources over it, and push those four back. The cloud does the long work; the
laptop does the part only it can.

Refuses to overwrite newer local data, so running this after a local scrape
cannot throw that scrape away.

    python pull_cloud.py
"""
from __future__ import annotations

import gzip
import io
import json
import os
import re
import sys
from datetime import datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "tenders.json")
URL = ("https://sancheetpasari.github.io/india-tenders/tenders.json.gz")
STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})")


def when(d):
    m = STAMP.match(str(d.get("generated_at") or ""))
    return datetime(*(int(g) for g in m.groups())) if m else datetime.min


def main():
    try:
        r = requests.get(URL, timeout=180)
        r.raise_for_status()
        cloud = json.loads(gzip.decompress(r.content).decode("utf-8"))
    except Exception as e:                                # noqa: BLE001
        print(f"could not fetch the published dataset ({type(e).__name__}); "
              "keeping what is on disk")
        return 0

    if os.path.exists(DEST):
        try:
            with io.open(DEST, encoding="utf-8") as f:
                local = json.load(f)
        except (OSError, ValueError):
            local = {}
        if local and when(local) >= when(cloud) and not local.get("partial"):
            print(f"local data ({local.get('generated_at')}) is not older than "
                  f"the cloud's ({cloud.get('generated_at')}); keeping it")
            return 0

    fresh = sum(1 for s in cloud.get("sources", []) if s.get("status") == "ok")
    tmp = DEST + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(cloud, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DEST)
    print(f"pulled {cloud['count']:,} tenders from {cloud['generated_at']}, "
          f"{fresh} sources freshly scraped by the cloud")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
