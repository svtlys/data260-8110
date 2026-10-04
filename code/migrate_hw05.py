from sqlalchemy import inspect, text

from db import engine, Base
from models import Landlord, Listing, ListingEvent, User, Session  # noqa: F401

inspector = inspect(engine)

Base.metadata.create_all(bind=engine)
print("Ensured all tables exist (created 'landlords' if missing).")

existing_columns = {col["name"] for col in inspector.get_columns("listings")}
print(f"Existing listings columns: {sorted(existing_columns)}")

alterations = [
    ("listing_code", "ALTER TABLE listings ADD COLUMN listing_code VARCHAR(50) UNIQUE"),
    ("available_units", "ALTER TABLE listings ADD COLUMN available_units INT NOT NULL DEFAULT 1"),
    ("landlord_id", "ALTER TABLE listings ADD COLUMN landlord_id INT"),
    ("created_at", "ALTER TABLE listings ADD COLUMN created_at DATETIME"),
    ("updated_at", "ALTER TABLE listings ADD COLUMN updated_at DATETIME"),
]

with engine.connect() as conn:
    for column_name, ddl in alterations:
        if column_name in existing_columns:
            print(f"  skip: {column_name} already exists")
            continue
        conn.execute(text(ddl))
        conn.commit()
        print(f"  added: {column_name}")

    
    fk_check = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = 'listings'
          AND CONSTRAINT_NAME = 'fk_listings_landlord_id'
    """)).scalar()
    if fk_check == 0:
        conn.execute(text("""
            ALTER TABLE listings
            ADD CONSTRAINT fk_listings_landlord_id
            FOREIGN KEY (landlord_id) REFERENCES landlords(id)
        """))
        conn.commit()
        print("  added: fk_listings_landlord_id constraint")
    else:
        print("  skip: fk_listings_landlord_id constraint already exists")

print("\nMigration complete.")

final_columns = {col["name"] for col in inspect(engine).get_columns("listings")}
print(f"Final listings columns: {sorted(final_columns)}")