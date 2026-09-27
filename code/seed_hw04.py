
import random

from db import engine, db_session_basede26, Base
from models import Listing, ListingEvent, User, Session

SEED = 8110
NUM_LISTINGS = 5000
NUM_RELATED = 200

random.seed(SEED)

STREETS = ["Main St", "Oak Ave", "Chablis Cir", "Santa Clara St", "First St", "Almaden Blvd"]
LANDLORDS = ["Felix Realty", "Sunrise Property Mgmt", "Golden Gate Rentals", "Bay Area Homes", "Valley Property Group"]
EVENT_NOTES = ["Maintenance requested", "Lease renewal inquiry", "Inspection scheduled", "Rent payment received", "Noise complaint filed"]

Base.metadata.create_all(bind=engine)
db = db_session_basede26()

existing_count = db.query(Listing).count()
if existing_count >= NUM_LISTINGS:
    print(f"Already have {existing_count} listings, skipping listing seed.")
else:
    print(f"Seeding {NUM_LISTINGS} listings...")
    listings = []
    for i in range(NUM_LISTINGS):
        listings.append(Listing(
            address=f"{random.randint(1, 9999)} {random.choice(STREETS)}, San Jose, CA",
            landlord_name=random.choice(LANDLORDS),
        ))
    db.bulk_save_objects(listings, return_defaults=True)
    db.commit()
    print(f"Seeded {NUM_LISTINGS} listings.")

listing_ids = [row[0] for row in db.query(Listing.id).all()]

existing_related = db.query(ListingEvent).count()
if existing_related >= NUM_RELATED:
    print(f"Already have {existing_related} listing_events, skipping related seed.")
else:
    print(f"Seeding {NUM_RELATED} related rows (listing_events)...")
    events = []
    for i in range(NUM_RELATED):
        events.append(ListingEvent(
            listing_id=random.choice(listing_ids),
            note=random.choice(EVENT_NOTES),
        ))
    db.bulk_save_objects(events)
    db.commit()
    print(f"Seeded {NUM_RELATED} listing_events.")

final_listings = db.query(Listing).count()
final_events = db.query(ListingEvent).count()
print(f"\nFinal counts: {final_listings} listings, {final_events} listing_events")

db.close()