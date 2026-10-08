"""Gives an existing account admin rights. Run from backend/: python -m scripts.make_admin <email>

Meant for hosted databases, which are not seeded with the admin account. Point DATABASE_URL at the
target database for this one command, e.g. in PowerShell:
    $env:DATABASE_URL = "<external database URL>"; python -m scripts.make_admin you@example.com
"""

import sys

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories import user_repo


def make_admin(db: Session, email: str) -> bool:
    """Returns False if no account uses `email`."""
    user = user_repo.get_by_email(db, email)
    if user is None:
        return False
    user.is_admin = True
    db.commit()
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.make_admin <email>")
        return 2
    email = sys.argv[1].strip().lower()
    with SessionLocal() as db:
        if not make_admin(db, email):
            print(f"No account with email {email}. Register on the website first.")
            return 1
    print(f"{email} is now an admin. Log out and log in again to see the Admin page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
