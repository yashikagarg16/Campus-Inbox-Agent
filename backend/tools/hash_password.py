"""Print a password hash for ADMIN_PASSWORD_HASH (the password itself is never stored).

    python -m tools.hash_password
"""

from getpass import getpass

from app.auth import hash_password


def main() -> None:
    password = getpass("Password: ")
    if len(password) < 10:
        raise SystemExit("Use at least 10 characters.")
    if getpass("Again: ") != password:
        raise SystemExit("Passwords didn't match.")
    print(hash_password(password))


if __name__ == "__main__":
    main()
