"""Store the Gmail App Password for the reminder email, once.

Run it from store-password.bat (double-click) or from a terminal.

The password goes into Windows Credential Manager -- not into this
repository, not into an environment variable, not into a file. It is never
printed back.

A dialog box is used rather than a console prompt because Ctrl+V does not
paste into a cmd window, and a 16-character password nobody can paste is a
password nobody will set. The console prompt stays as a fallback, and
refuses an empty value: getpass returns "" without complaint where stdin is
not a console, which would otherwise store an empty password silently.
"""
import sys

try:
    import keyring
except ImportError:
    sys.exit("keyring is not installed. Run:  pip install keyring")

SERVICE, ACCOUNT = "india-tenders", "smtp"


def ask_dialog():
    """A real input box: paste works, nothing is echoed. None if unavailable."""
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        pw = simpledialog.askstring(
            "India Tenders reminder",
            "Gmail App Password (16 characters).\n"
            "Paste with Ctrl+V. Spaces are ignored.",
            show="*", parent=root)
        root.destroy()
        return pw if pw is not None else ""
    except Exception:                                     # noqa: BLE001
        return None


def ask_console():
    import getpass
    if not sys.stdin.isatty():
        sys.exit("No console and no dialog available. Run this from a "
                 "terminal window.")
    return getpass.getpass("app password (nothing shows as you type): ")


def main():
    print("Storing the Gmail App Password for tender reminder emails.")
    pw = ask_dialog()
    if pw is None:                       # no GUI on this machine
        print("(no dialog available, falling back to the console)")
        pw = ask_console()

    pw = (pw or "").replace(" ", "").strip()
    if not pw:
        sys.exit("Nothing entered, so nothing was stored.")
    if len(pw) != 16:
        print(f"Note: Gmail app passwords are 16 characters; you gave "
              f"{len(pw)}. Storing it anyway.")

    keyring.set_password(SERVICE, ACCOUNT, pw)
    if (keyring.get_password(SERVICE, ACCOUNT) or "") != pw:
        sys.exit("Stored, but reading it back gave something different. "
                 "Please try again.")

    print(f"Stored: {len(pw)} characters, in Windows Credential Manager "
          f"under '{SERVICE}'.")
    print("Now test it with:  send-reminders.bat")


if __name__ == "__main__":
    main()
