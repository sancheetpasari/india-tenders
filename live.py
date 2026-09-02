"""Run the dashboard as a live service: serve it AND keep refreshing the data.

    python live.py --serve-only    # serve only; Task Scheduler does the refreshing
    python live.py --at 00:00      # refresh every night at midnight
    python live.py                 # refresh every 2 h, serve on :8777
    python live.py --interval 60   # every 60 minutes
    python live.py --no-initial    # don't scrape at startup, use existing data
    python live.py --quick 20      # extra fast 7-day pass every 20 minutes

Why not continuously? A full sweep hits 30-odd government portals with a few
thousand requests and takes 15-30 minutes. Re-running it back-to-back would
hammer public infrastructure for almost no benefit -- tenders are published
over hours, not seconds. Two hours is a courteous default; --quick gives you a
much cheaper 7-day sweep in between for time-critical work.

The scraper writes atomically and publishes each portal as it lands, so the
dashboard is always readable, even mid-refresh.
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

_state = {"running": False, "last": None, "last_quick": None}


def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_scrape(label, extra_args):
    """Run scraper.py as a subprocess so a crash can never kill the server."""
    if _state["running"]:
        _log(f"{label}: skipped, a refresh is already running")
        return
    _state["running"] = True
    t0 = time.time()
    _log(f"{label}: starting")
    try:
        proc = subprocess.run([sys.executable, "scraper.py"] + extra_args,
                              cwd=HERE, capture_output=True, text=True, timeout=7200)
        tail = [l for l in (proc.stdout or "").strip().splitlines() if l.strip()][-1:]
        _log(f"{label}: done in {time.time() - t0:.0f}s — {tail[0] if tail else 'no output'}")
        if proc.returncode != 0:
            _log(f"{label}: exit {proc.returncode}; stderr: {(proc.stderr or '')[:200]}")
    except subprocess.TimeoutExpired:
        _log(f"{label}: timed out after 2 h")
    except Exception as e:                                   # noqa: BLE001
        _log(f"{label}: ERROR {type(e).__name__}: {e}")
    finally:
        _state["running"] = False


def _parse_times(spec):
    """'00:00' or '00:00,12:30' -> [(0,0), (12,30)]."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        hh, _, mm = part.partition(":")
        out.append((int(hh), int(mm or 0)))
    return sorted(set(out))


def _next_run(times, after=None):
    """Next datetime matching any of `times`, strictly after `after`."""
    from datetime import timedelta
    now = after or datetime.now()
    best = None
    for day in (0, 1):
        for hh, mm in times:
            cand = (now + timedelta(days=day)).replace(
                hour=hh, minute=mm, second=0, microsecond=0)
            if cand > now and (best is None or cand < best):
                best = cand
    return best


def scheduler(interval_min, quick_min, initial, deadline, extra, at_times=None):
    base = ["--deadline", str(deadline)] + extra
    if initial:
        run_scrape("full refresh", base)

    if at_times:
        # Clock-based: refresh at fixed times of day (e.g. midnight).
        nxt = _next_run(at_times)
        _log(f"next full refresh at {nxt:%Y-%m-%d %H:%M}")
        while True:
            time.sleep(20)
            if datetime.now() >= nxt:
                run_scrape("scheduled refresh", base)
                nxt = _next_run(at_times)
                _log(f"next full refresh at {nxt:%Y-%m-%d %H:%M}")
        return

    _state["last"] = time.time()
    _state["last_quick"] = time.time()
    while True:
        time.sleep(20)
        now = time.time()
        if now - _state["last"] >= interval_min * 60:
            run_scrape("full refresh", base)
            _state["last"] = now = time.time()
            _state["last_quick"] = now
        elif quick_min and now - _state["last_quick"] >= quick_min * 60:
            # cheap sweep: 7-day window, single pass, GePNIC only
            run_scrape("quick refresh",
                       base + ["--window", "7", "--passes", "1", "--no-browser"])
            _state["last_quick"] = time.time()


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--lan", action="store_true",
                    help="also serve on the local network, so a phone or another "
                         "machine on the same Wi-Fi can open the dashboard. Anyone "
                         "on that network can then read it -- fine at home, think "
                         "twice on public Wi-Fi.")
    ap.add_argument("--interval", type=int, default=120,
                    help="minutes between full refreshes (default 120)")
    ap.add_argument("--at", default=None,
                    help="refresh daily at these clock times, e.g. 00:00 or 00:00,12:00 "
                         "(overrides --interval)")
    ap.add_argument("--quick", type=int, default=0,
                    help="minutes between cheap 7-day passes (0 = off)")
    ap.add_argument("--deadline", type=int, default=900,
                    help="per-portal deadline in seconds, passed to scraper.py")
    ap.add_argument("--serve-only", action="store_true",
                    help="just serve the dashboard; something else (e.g. Windows Task "
                         "Scheduler) does the refreshing")
    ap.add_argument("--no-initial", action="store_true",
                    help="skip the refresh at startup")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    args, extra = ap.parse_known_args()

    at_times = _parse_times(args.at) if args.at else None
    if not args.serve_only:
        threading.Thread(target=scheduler, daemon=True,
                         args=(args.interval, args.quick, not args.no_initial,
                               args.deadline, extra, at_times)).start()

    socketserver.TCPServer.allow_reuse_address = True
    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    with socketserver.TCPServer((bind, args.port), Handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/dashboard.html"
        _log(f"Dashboard live at {url}")
        if args.lan:
            import socket
            try:
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                probe.connect(("8.8.8.8", 80))
                lan_ip = probe.getsockname()[0]
                probe.close()
            except Exception:                              # noqa: BLE001
                lan_ip = "<this machine's IP>"
            _log(f"On your network:  http://{lan_ip}:{args.port}/dashboard.html")
        if args.serve_only:
            _log("Serve-only: refreshing is handled elsewhere "
                 "(Windows Task Scheduler). Ctrl+C to stop.")
        elif at_times:
            _log("Refreshing daily at " + ", ".join(f"{h:02d}:{m:02d}" for h, m in at_times)
                 + ". Ctrl+C to stop.")
        else:
            _log(f"Full refresh every {args.interval} min"
                 + (f", quick pass every {args.quick} min" if args.quick else "")
                 + ". Ctrl+C to stop.")
        if not args.no_open:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            _log("stopped")


if __name__ == "__main__":
    main()
