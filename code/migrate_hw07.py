import logging
import os
import sys

import bcrypt
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from db import Base, db_session_basede26, engine
from models import User

logger = logging.getLogger("migrate_hw07")
DEMO_USERS = (("reader1", "reader"), ("writer1", "writer"), ("moderator1", "moderator"))


def add_columns(conn: Connection) -> None:
    """Add username and role to users if they are missing, backfilling existing rows."""
    cols = {c["name"] for c in inspect(conn).get_columns("users")}
    if "role" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'reader'"))
        logger.info("added users.role")
    if "username" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(50) NULL"))
        conn.execute(text("UPDATE users SET username = SUBSTRING_INDEX(email, '@', 1) WHERE username IS NULL"))
        conn.execute(text("ALTER TABLE users MODIFY username VARCHAR(50) NOT NULL"))
        conn.execute(text("ALTER TABLE users ADD UNIQUE INDEX uq_users_username (username)"))
        logger.info("added users.username (unique), backfilled from email")
    conn.commit()


def seed_users(password: str) -> None:
    """Create reader1, writer1 and moderator1 if absent; give the old HW4 account the moderator role."""
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with db_session_basede26() as db:
        for username, role in DEMO_USERS:
            if db.query(User).filter(User.username == username).first() is None:
                db.add(User(name=username, email=f"{username}@example.com",
                            username=username, password_hash=hashed, role=role))
                logger.info("created %s (%s)", username, role)
        old = db.query(User).filter(User.username == "landlord").first()
        if old is not None and old.role != "moderator":
            old.role = "moderator"
            logger.info("set landlord role to moderator")
        db.commit()


def main() -> int:
    """Run the migration and seeding; return a process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    password = os.environ.get("HW7_DEMO_PASSWORD", "")
    if len(password) < 8:
        logger.error("Set HW7_DEMO_PASSWORD (8+ characters) before running.")
        return 1
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        add_columns(conn)
    seed_users(password)
    logger.info("done: users table now has username and role")
    return 0


if __name__ == "__main__":
    sys.exit(main())