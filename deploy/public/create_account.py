"""Offline account provisioning: stop the PUBLIC service first.

python deploy/public/create_account.py --runtime /absolute/runtime --username doctor
Passwords are read from the terminal without echo, never from CLI arguments.
"""
import argparse
import fcntl
import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    if not args.runtime.is_absolute() or args.runtime == Path("/"):
        parser.error("Supply the explicit absolute public runtime directory")
    from web.auth import USERNAME_RE, MIN_PASSWORD_LENGTH
    if not USERNAME_RE.fullmatch(args.username):
        parser.error("Username must be 3-64 letters, digits, dots, dashes or underscores")
    if not sys.stdin.isatty():
        parser.error("Run in an interactive terminal so the password stays out of scripts and logs")
    args.runtime.mkdir(parents=True, exist_ok=True)
    with (args.runtime / ".public-server.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Stop the public service before provisioning accounts")
        password = getpass.getpass("New password: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            parser.error(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters")
        if password != getpass.getpass("Repeat password: "):
            parser.error("Passwords do not match")
        from werkzeug.security import generate_password_hash
        from web.workspace_store import WorkspaceStore, WorkspaceError
        store = WorkspaceStore(args.runtime)
        try:
            store.create_user(args.username, generate_password_hash(password))
        except WorkspaceError:
            parser.error("Account could not be created; it may already exist")
        print("Account created. No password printed and no clinical task started.")


if __name__ == "__main__":
    main()
