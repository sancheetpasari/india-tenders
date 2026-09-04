"""Email a digest of the tenders marked "I intend to bid".

    python send_reminders.py --dry-run     # print it, send nothing
    python send_reminders.py               # send

Reads interested.json (written by the dashboard) and tenders.json for the
current deadline of each marked tender -- a corrigendum can move a closing
date after it was marked, and being reminded of the old one is worse than
not being reminded at all. A tender that has since dropped out of the
dataset still appears, using the details saved when it was marked.

Nothing marked, or nothing still open? No email. A daily message that says
"nothing" trains you to ignore it.

Credentials come from the environment, never from the repo:

    SMTP_HOST   default smtp.gmail.com
    SMTP_PORT   default 587
    SMTP_USER   the sending mailbox
    SMTP_PASS   a Gmail App Password, not the account password
    MAIL_TO     recipient; defaults to SMTP_USER
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate

IST = timezone(timedelta(hours=5, minutes=30))
HERE = os.path.dirname(os.path.abspath(__file__))

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

CLOSING_RE = re.compile(
    r"(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+(\d{1,2}):(\d{2})\s*([AaPp])[Mm]")


def parse_closing(s):
    """'03-Sep-2026 10:00 AM' -> datetime, or None."""
    m = CLOSING_RE.match((s or "").strip())
    if not m:
        return None
    day, mon, year, hh, mm, ap = m.groups()
    mon_n = MONTHS.get(mon.lower())
    if not mon_n:
        return None
    hh = int(hh) % 12 + (12 if ap.lower() == "p" else 0)
    try:
        return datetime(int(year), mon_n, int(day), hh, int(mm), tzinfo=IST)
    except ValueError:
        return None


def mark_key(t):
    """Must match markKey() in dashboard.html."""
    return "{}|{}".format(t.get("state") or "",
                          t.get("tender_id") or t.get("ref_no")
                          or t.get("detail_url") or t.get("title") or "")


def load_json(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def human(delta):
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins} min"
    if mins < 48 * 60:
        return f"{mins // 60} h"
    return f"{mins // 1440} days"


def collect(marks, tenders, now):
    """Marked tenders still open, soonest deadline first."""
    live = {mark_key(t): t for t in tenders}
    rows, closed = [], 0
    for key, m in marks.items():
        t = live.get(key)
        closing = (t or {}).get("closing") or m.get("closing") or ""
        when = parse_closing(closing)
        if when and when < now:
            closed += 1
            continue
        rows.append({
            "title": (t or {}).get("title") or m.get("title") or "(untitled)",
            "state": (t or {}).get("state") or m.get("state") or "",
            "org": (t or {}).get("organisation") or m.get("organisation") or "",
            "closing": closing or "date not published",
            "when": when,
            "left": human(when - now) if when else "",
            "url": ((t or {}).get("detail_url") or m.get("detail_url")
                    or (t or {}).get("portal") or m.get("portal") or ""),
            "gone": t is None,
        })
    rows.sort(key=lambda r: r["when"] or datetime.max.replace(tzinfo=IST))
    return rows, closed


def render(rows, closed, now):
    urgent = [r for r in rows if r["when"] and r["when"] - now <= timedelta(hours=48)]
    head = f"{len(rows)} tender{'s' if len(rows) != 1 else ''} you marked"
    if urgent:
        head += f", {len(urgent)} closing within 48 hours"

    text = [head, "=" * len(head), ""]
    for r in rows:
        flag = "  << CLOSING SOON" if r in urgent else ""
        text.append(f"{r['closing']}   ({r['left']} left){flag}")
        text.append(f"  {r['title']}")
        text.append(f"  {r['state']} - {r['org']}")
        if r["url"]:
            text.append(f"  {r['url']}")
        if r["gone"]:
            text.append("  (no longer listed on the portal; details as saved)")
        text.append("")
    if closed:
        text.append(f"{closed} marked tender(s) have now closed and are not listed.")
    text.append("")
    text.append(f"Generated {now.strftime('%Y-%m-%d %H:%M IST')} from your India Tender Registry.")

    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    tr = []
    for r in rows:
        hot = r in urgent
        colour = "#b00020" if hot else "#333"
        weight = "700" if hot else "400"
        link = (f'<a href="{esc(r["url"])}" style="color:#0645ad;text-decoration:none">'
                f'{esc(r["title"])}</a>') if r["url"] else esc(r["title"])
        note = ('<div style="color:#888;font-size:12px">no longer listed on the '
                'portal; details as saved</div>') if r["gone"] else ""
        tr.append(
            f'<tr>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;'
            f'white-space:nowrap;color:{colour};font-weight:{weight}">'
            f'{esc(r["closing"])}<div style="font-weight:400;color:#888;'
            f'font-size:12px">{esc(r["left"])} left</div></td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee">{link}{note}'
            f'<div style="color:#666;font-size:12px">{esc(r["state"])}'
            f'{" &middot; " + esc(r["org"]) if r["org"] else ""}</div></td>'
            f'</tr>')

    html = (
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:760px">'
        f'<h2 style="margin:0 0 4px">{esc(head)}</h2>'
        f'<div style="color:#666;font-size:13px;margin-bottom:16px">'
        f'{now.strftime("%A, %d %B %Y")} &middot; sorted by deadline</div>'
        '<table style="border-collapse:collapse;width:100%;font-size:14px">'
        + "".join(tr) + '</table>'
        + (f'<p style="color:#888;font-size:13px">{closed} marked tender(s) have '
           f'now closed and are not listed.</p>' if closed else '')
        + '<p style="color:#888;font-size:12px;margin-top:20px">'
          'From your India Tender Registry. Untick a tender in the dashboard '
          'to stop being reminded about it.</p></div>')

    subject = f"Tender reminders: {len(rows)} open"
    if urgent:
        subject += f", {len(urgent)} closing within 48 h"
    return subject, "\n".join(text), html


def smtp_password(user):
    """The app password, from the environment or Windows Credential Manager.

    In Actions it arrives as a secret. On the laptop there is nowhere safe to
    put it in the repository, so it lives in the OS credential store and never
    touches a file. Set it once with:

        python -c "import keyring,getpass; keyring.set_password(
            'india-tenders', 'smtp', getpass.getpass('app password: '))"
    """
    pwd = os.environ.get("SMTP_PASS")
    if pwd:
        return pwd
    try:
        import keyring
        return keyring.get_password("india-tenders", "smtp") or ""
    except Exception:                                     # noqa: BLE001
        return ""


def send(subject, text, html, dry_run):
    user = os.environ.get("SMTP_USER")
    pwd = smtp_password(user)
    to = os.environ.get("MAIL_TO") or user
    if dry_run:
        print(f"Subject: {subject}\nTo: {to or '(MAIL_TO unset)'}\n")
        print(text)
        return False
    if not any((user, pwd, os.environ.get("MAIL_TO"))):
        # never configured -- say so once a day rather than failing red
        print("SMTP is not configured, so no mail was sent. Set the SMTP_USER, "
              "SMTP_PASS and MAIL_TO secrets to turn reminders on.")
        return False
    if not (user and pwd and to):
        sys.exit("SMTP is only half configured: SMTP_USER, SMTP_PASS and "
                 "MAIL_TO must all be set")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("MAIL_FROM") or user
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "587")
    with smtplib.SMTP(host, port, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(user, pwd)
        smtp.send_message(msg)
    print(f"sent to {to}: {subject}")
    return True


def announce_sent():
    """Tell the cloud fallback that today is handled.

    GitHub's scheduler runs this repository's crons hours late and sometimes
    not at all, so the laptop sends the digest and the workflow is only a
    fallback for days the laptop is off. It reads this repository variable
    and stands down if the date is today, which is what stops two emails
    landing on the same morning.

    GITHUB_TOKEN cannot write variables, so only the laptop sets it.
    """
    gh = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
    if not os.path.exists(gh):
        print("note: GitHub CLI not found; the cloud fallback may send a second copy")
        return
    today = datetime.now(IST).strftime("%Y-%m-%d")
    p = subprocess.run([gh, "variable", "set", "LAST_REMINDER_SENT", "--body", today],
                       capture_output=True, text=True)
    print(f"marked {today} as sent" if p.returncode == 0
          else f"note: could not set LAST_REMINDER_SENT: {p.stderr.strip()[:120]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marks", default=os.path.join(HERE, "interested.json"))
    ap.add_argument("--data", default=os.path.join(HERE, "tenders.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--announce", action="store_true",
                    help="after sending, record today against the repository "
                         "so the cloud fallback does not send a second copy")
    args = ap.parse_args()

    try:
        marks = (load_json(args.marks) or {}).get("marks", {})
    except (OSError, ValueError):
        marks = {}
    if not marks:
        print("nothing marked interested; no email")
        return 0

    try:
        tenders = load_json(args.data).get("tenders", [])
    except (OSError, ValueError) as e:
        print(f"note: could not read {args.data} ({type(e).__name__}); "
              "using the details saved when each was marked")
        tenders = []

    now = datetime.now(IST)
    rows, closed = collect(marks, tenders, now)
    if not rows:
        print(f"all {closed} marked tender(s) have closed; no email")
        return 0

    subject, text, html = render(rows, closed, now)
    sent = send(subject, text, html, args.dry_run)
    if sent and args.announce:
        announce_sent()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
