"""Admin commands: python -m app.cli create-user EMAIL NAME  |  reset-password EMAIL"""

import secrets
import sys

from sqlalchemy import select

from app import auth
from app.db import session_scope
from app.models import User


def main() -> None:
    cmd, *args = sys.argv[1:] or ["help"]
    password = secrets.token_urlsafe(12)
    with session_scope() as s:
        if cmd == "create-user" and len(args) >= 1:
            user = auth.create_user(s, args[0], " ".join(args[1:]) or args[0].split("@")[0], password)
        elif cmd == "reset-password" and len(args) == 1:
            user = s.scalar(select(User).where(User.email == args[0].strip().lower()))
            if not user:
                sys.exit("No such user.")
            user.password_hash = auth.hash_password(password)
        else:
            sys.exit(__doc__)
    print(f"{user.email}  password: {password}  (change it in Settings)")


if __name__ == "__main__":
    main()
