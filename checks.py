"""Cheap repo-wide sanity checks. Run before committing, and in CI.

    python checks.py

One check, learned the hard way and repeatedly: a stray control character in
a source file. Writing a regex through a shell heredoc can collapse "\\b" into
an actual backspace byte (0x08). Python compiles it happily, the pattern then
silently matches nothing, and the only symptom is a filter that quietly stops
filtering. It has happened four times; it should not happen a fifth.
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {".git", "__pycache__", ".cache", "_upload", "node_modules", "seed"}
EXTS = {".py", ".html", ".yml", ".yaml", ".json", ".md", ".css", ".js"}
ALLOWED = {"\t", "\n", "\r"}


def offenders():
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in EXTS:
                continue
            path = os.path.join(root, fn)
            try:
                text = io.open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for i, ch in enumerate(text):
                if ord(ch) < 32 and ch not in ALLOWED:
                    line = text.count("\n", 0, i) + 1
                    yield os.path.relpath(path, HERE), line, hex(ord(ch))
                    break


def main():
    bad = list(offenders())
    for path, line, code in bad:
        print(f"  {path}:{line}  control character {code}")
    if bad:
        print(f"\n{len(bad)} file(s) contain a control character. A regex "
              f"escape has almost certainly been mangled.")
        return 1
    print("no control characters in any source file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
