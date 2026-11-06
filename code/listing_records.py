import hashlib
import re

CODE_RE = re.compile(r"\bS8110-A\d{2}\b", re.IGNORECASE)

DEMO_LISTINGS = [
    ("S8110-A01", "450 Maple Ave, San Jose, CA", 3, "Bayview Rentals"),
    ("S8110-A02", "88 Oak Street, Oakland, CA", 1, "Greenfield Properties"),
    ("S8110-A03", "1200 Pine Blvd, Fremont, CA", 5, "Bayview Rentals"),
    ("S8110-A04", "77 Cedar Court, Palo Alto, CA", 0, "Summit Property Group"),
    ("S8110-A05", "301 Elm Drive, Sunnyvale, CA", 2, "Greenfield Properties"),
    ("S8110-A06", "15 Birch Lane, San Mateo, CA", 4, "Summit Property Group"),
    ("S8110-A07", "902 Willow Way, Mountain View, CA", 1, "Greenfield Properties"),
    ("S8110-A08", "56 Spruce Street, Santa Clara, CA", 6, "Bayview Rentals"),
    ("S8110-A09", "210 Redwood Road, Redwood City, CA", 2, "Summit Property Group"),
    ("S8110-A10", "34 Aspen Place, Milpitas, CA", 1, "Greenfield Properties"),
]
NO_RECORD = "none"


def extract_listing_code(text: str) -> str | None:
    """The listing code mentioned in a question (e.g. 'S8110-A01'), upper-cased, or None."""
    match = CODE_RE.search(text or "")
    return match.group(0).upper() if match else None


def record_version(rec: dict | None) -> str:
    """Data-version marker: short hash of the fields a cached answer can depend on."""
    if rec is None:
        return NO_RECORD
    raw = f"{rec['address']}|{rec['available_units']}|{rec['landlord_name']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def record_context(rec: dict) -> str:
    """Facts handed to the HW8 Writer so its answer is grounded in the database row."""
    return (f"Listing {rec['listing_code']}: address={rec['address']}; available_units={rec['available_units']}; "
            f"landlord={rec['landlord_name']}. A listing with 0 available units is not currently available.")


def attribute_of(question: str) -> str | None:
    q = question.lower()
    for words, name in ((("landlord", "manages", "owns", "owner"), "landlord"), (("address", "located", "where"), "address"),
                        (("how many", "units", "vacanc"), "units"), (("available", "rent"), "available")):
        if any(w in q for w in words):
            return name
    return None


def ground_truth(question: str, rec: dict | None) -> str:
    """Deterministic correct answer straight from the database row (used to label and check results)."""
    attr = attribute_of(question)
    if rec is None or attr is None:
        return "(no database record applies to this question)"
    code = rec["listing_code"]
    if attr == "landlord":
        return f"The landlord of {code} is {rec['landlord_name']}."
    if attr == "address":
        return f"{code} is at {rec['address']}."
    if attr == "units":
        return f"{code} has {rec['available_units']} unit(s) available."
    return f"{code} is {'currently available' if rec['available_units'] > 0 else 'not currently available'} ({rec['available_units']} unit(s))."


class RecordRepo:
    """SQL access to `listings` through a SQLAlchemy session factory."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def get_by_code(self, code: str) -> dict | None:
        from sqlalchemy import text

        with self.session_factory() as session:
            row = session.execute(text("SELECT address, available_units, landlord_name, listing_code FROM listings WHERE listing_code = :c"),
                                  {"c": code}).first()
        return None if row is None else {"address": row[0], "available_units": int(row[1]), "landlord_name": row[2], "listing_code": row[3]}

    def version(self, code: str) -> str:
        return record_version(self.get_by_code(code))

    def set_units(self, code: str, units: int) -> None:
        from sqlalchemy import text

        with self.session_factory() as session:
            session.execute(text("UPDATE listings SET available_units = :u WHERE listing_code = :c"), {"u": units, "c": code})
            session.commit()

    def ensure_demo_listings(self) -> int:
        """Insert any missing demo listing; reset existing ones to the standard values. Returns how many were inserted."""
        from sqlalchemy import text

        inserted = 0
        with self.session_factory() as session:
            for code, address, units, landlord in DEMO_LISTINGS:
                exists = session.execute(text("SELECT id FROM listings WHERE listing_code = :c"), {"c": code}).first()
                if exists is None:
                    session.execute(text("INSERT INTO listings (address, listing_code, available_units, landlord_name, created_at, updated_at) "
                                         "VALUES (:a, :c, :u, :l, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                                    {"a": address, "c": code, "u": units, "l": landlord})
                    inserted += 1
                else:
                    session.execute(text("UPDATE listings SET address=:a, available_units=:u, landlord_name=:l WHERE listing_code=:c"),
                                    {"a": address, "c": code, "u": units, "l": landlord})
            session.commit()
        return inserted