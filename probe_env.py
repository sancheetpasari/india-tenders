"""Log which interpreter and Chromium a run actually resolves.

Gujarat and Bihar drive Chromium through Playwright. They fail under Task
Scheduler with "BrowserType.launch: Executable doesn't exist" while the very
same command succeeds in an interactive shell on the same machine -- same
registered interpreter, same browser present on disk. The scheduled context is
resolving something different and the error is truncated in the run log before
it reaches the path.

refresh-tenders.bat runs this first, so every run records what it saw and the
next failure explains itself instead of needing to be reproduced.
"""
from __future__ import annotations

import os
import sys


def main():
    print(f"env: python={sys.executable}")
    for var in ("PLAYWRIGHT_BROWSERS_PATH", "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        print(f"env: {var}={os.environ.get(var, '<unset>')}")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
            print(f"env: chromium={path}")
            print(f"env: chromium_exists={os.path.exists(path)}")
    except Exception as exc:                               # noqa: BLE001
        print(f"env: chromium probe failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
