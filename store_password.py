"""Store the Gmail App Password for the reminder email, once.

Run it from store-password.bat (double-click) or from a terminal window.
The password goes into Windows Credential Manager -- not into this
repository, not into an environment variable, not into a file. Nothing is
echoed as you type and nothing is printed back.

Why a console matters: getpass reads from the terminal, and where stdin is
not a console it silently returns an empty string. That stores an empty
password and everything then fails with "missing: password", so this
refuses to store an empty one.
"""
import sys

try:
    import keyring
except ImportError:
    sys.exit("keyring is not installed. Run:  pip install keyring")

import getpass

SERVICE, ACCOUNT = "india-tenders", "smtp"


def main():
    print()
    print("Gmail App Password for the tender reminder email")
    print("------------------------------------------------")
    print("16 characters. Spaces are fine, they get stripped.")
    print("Nothing appears as you type -- that is expected.")
    print()

    if not sys.stdin.isatty():
        sys.exit("This needs a real console window. Double-click "
                 "store-password.bat, or run it in PowerShell.")

    pw = getpass.getpass("app password: ").replace(" ", "").strip()
    if not pw:
        sys.exit("Nothing entered, so nothing was stored.")
    if len(pw) != 16:
        print(f"\nNote: Gmail app passwords are 16 characters; you gave "
              f"{len(pw)}. Storing it anyway.")

    keyring.set_password(SERVICE, ACCOUNT, pw)

    check = keyring.get_password(SERVICE, ACCOUNT) or ""
    if check == pw:
        print(f"\nStored. {len(check)} characters, in Windows Credential "
              f"Manager under '{SERVICE}'.")
        print("Test it with:  send-reminders.bat")
    else:
        sys.exit("\nStored, but reading it back gave something different. "
                 "Try again.")


if __name__ == "__main__":
    main()
