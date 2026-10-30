"""Generate an Argon2id hash for ECM_ADMIN_PASSWORD_HASH: python -m app.hashpw"""
import getpass

from argon2 import PasswordHasher

if __name__ == "__main__":
    pw = getpass.getpass("Admin password: ")
    if pw != getpass.getpass("Repeat: "):
        raise SystemExit("Passwords differ")
    if len(pw) < 12:
        raise SystemExit("Use at least 12 characters")
    # Single quotes in .env: the hash contains '$' characters.
    print(PasswordHasher().hash(pw))
