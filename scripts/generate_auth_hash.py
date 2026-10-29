"""Generate a password verifier for the AUTH_PASSWORD_HASH secret."""
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.auth import hash_password


def main() -> None:
    password = getpass("Dashboard password (minimum 12 characters): ")
    confirmation = getpass("Confirm dashboard password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match.")
    try:
        print(hash_password(password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
