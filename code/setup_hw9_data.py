import sys

from db import db_session_basede26, engine
from listing_records import DEMO_LISTINGS, RecordRepo


def main() -> int:
    repo = RecordRepo(db_session_basede26)
    inserted = repo.ensure_demo_listings()
    print(f"demo listings ready: {len(DEMO_LISTINGS)} ({inserted} newly inserted) in {engine.url.database}")
    for code, *_ in DEMO_LISTINGS:
        rec = repo.get_by_code(code)
        print(f"  {code}: {rec['available_units']} unit(s), {rec['landlord_name']}, {rec['address']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())