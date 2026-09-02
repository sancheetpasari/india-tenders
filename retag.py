"""Re-apply sector tags to the existing dataset, without re-scraping.

Run after editing sector.py:   python retag.py
"""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scraper, sector

def main():
    HERE = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(HERE, "tenders.json")
    with open(src, encoding="utf-8") as f:
        d = json.load(f)

    n = 0
    for t in d["tenders"]:
        t["sector"] = sector.tag(t)
        if t["sector"]:
            n += 1

    scraper.write_outputs(d["tenders"],
                          {"generated_at": d["generated_at"], "window": d["window_days"],
                           "sources": d["sources"], "unsupported": d.get("unsupported", {})},
                          HERE, partial=d.get("partial", False))
    print(f"tagged {n:,} of {len(d['tenders']):,} tenders as CA-sector work")


if __name__ == "__main__":
    main()
