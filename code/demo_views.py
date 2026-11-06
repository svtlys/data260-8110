import logging
import sys

import redis

from cache_config import REDIS_URL, SID4, setup_logging
from listing_cache import ListingCache, SqlViewsRepo

DEMO_CODE = "S8110-VIEWS-DEMO"


class _Echo(logging.Handler):
    """Print the 'Synced' log line as the checkmark line the assignment shows."""

    def emit(self, record: logging.LogRecord) -> None:
        if "Synced views to database" in record.getMessage():
            print("✓ Synced views to database")


def get_or_create_listing(session_factory) -> int:
    from models import Listing

    with session_factory() as session:
        row = session.query(Listing).filter(Listing.listing_code == DEMO_CODE).first()
        if row is None:
            row = Listing(address="123 Market St, San Jose, CA", listing_code=DEMO_CODE, available_units=1, landlord_name="Views Demo")
            session.add(row)
            session.commit()
            session.refresh(row)
        return int(row.id)


def main() -> int:
    setup_logging(logging.WARNING)
    from db import db_session_basede26, engine

    repo = SqlViewsRepo(engine, db_session_basede26)
    if repo.ensure_column():
        print("(added column listings.views)")
    listing_id = get_or_create_listing(db_session_basede26)
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    cache = ListingCache(client, repo)
    client.delete(cache.views_key(listing_id))
    repo.save_views(listing_id, 0)
    logging.getLogger("listing_cache").setLevel(logging.INFO)
    logging.getLogger("listing_cache").addHandler(_Echo())
    print(f"student: Alyssa Gomez  SID4={SID4}  key={cache.views_key(listing_id)}\n=== Testing Counter ===\n")
    for n in range(1, 26):
        total = cache.increment_listing_views(listing_id)
        print(f"Access #{n}: Total = {total}")
    print(f"\nRedis count = {client.get(cache.views_key(listing_id))} | database listings.views = {repo.get_views(listing_id)} (last synced at access #20)")
    return 0


if __name__ == "__main__":
    sys.exit(main())