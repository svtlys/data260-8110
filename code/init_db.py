import bcrypt
from db import engine, db_session_basede26, Base
from models import Listing, User, Session  # noqa: F401 -- import so Base knows about them

Base.metadata.create_all(bind=engine)
print("Tables created: listings, users, sessions")

db = db_session_basede26()

existing = db.query(User).filter(User.email == "landlord@example.com").first()
if not existing:
    password_hash = bcrypt.hashpw(b"rentals123", bcrypt.gensalt()).decode("utf-8")
    test_user = User(name="Test Landlord", email="landlord@example.com", password_hash=password_hash)
    db.add(test_user)
    db.commit()
    print("Seeded test user: landlord@example.com / rentals123")
else:
    print("Test user already exists.")

db.close()