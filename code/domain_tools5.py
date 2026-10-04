import logging

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from db import db_session_basede26
from models import Landlord, Listing
from resilience import INTERACTIVE_POLICY, call_with_retry

logger = logging.getLogger("domain_tools")

MAX_QUERY_LENGTH = 100
MIN_LIMIT, MAX_LIMIT = 1, 50

_retry_policy = INTERACTIVE_POLICY
_fault_hook = None 


def set_retry_policy(policy) -> None:
    global _retry_policy
    _retry_policy = policy


def set_fault_hook(hook) -> None:
    """Install (or clear, with None) a fault injector for experiments and tests."""
    global _fault_hook
    _fault_hook = hook


def _envelope(ok: bool, data=None, error=None) -> dict:
    return {"ok": ok, "data": data, "error": error}


def success(data) -> dict:
    return _envelope(True, data=data)


def failure(message: str) -> dict:
    logger.warning("tool call rejected: %s", message)
    return _envelope(False, error=message)


def _as_int(value, name: str, minimum: int = 1, maximum: int | None = None):
    """Return (int, None) on success or (None, error message). Accepts ints and
    digit strings (an LLM often sends "5"); rejects bools, floats, and others."""
    if isinstance(value, bool):
        return None, f"{name} must be an integer"
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        number = int(value.strip())
    else:
        return None, f"{name} must be an integer"
    if number < minimum:
        return None, f"{name} must be >= {minimum}"
    if maximum is not None and number > maximum:
        return None, f"{name} must be <= {maximum}"
    return number, None


def _run(db, work):
    owns_session = db is None
    session = None
    try:
        session = db_session_basede26() if owns_session else db

        def attempt():
            if _fault_hook is not None:
                _fault_hook()
            try:
                return work(session)
            except SQLAlchemyError:
                session.rollback()  
                raise

        outcome = call_with_retry(attempt, _retry_policy)
        if outcome.ok:
            return outcome.value
        return failure(f"storage unavailable: {outcome.error}")
    except SQLAlchemyError as exc:
        logger.error("database error: %s", exc)
        return failure("database error: the lookup could not be completed")
    finally:
        if owns_session and session is not None:
            session.close()


def search_listings(query, limit=10, db=None) -> dict:
    """Search listings whose address contains `query` (case-insensitive)."""
    if not isinstance(query, str) or not query.strip():
        return failure("query must be a non-empty string")
    query = query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        return failure(f"query must be at most {MAX_QUERY_LENGTH} characters")
    limit, error = _as_int(limit, "limit", MIN_LIMIT, MAX_LIMIT)
    if error:
        return failure(error)

    def work(session):
        rows = (
            session.query(Listing)
            .filter(Listing.address.ilike(f"%{query}%"))
            .order_by(Listing.id)
            .limit(limit)
            .all()
        )
        results = [
            {
                "id": r.id,
                "address": r.address,
                "listing_code": r.listing_code,
                "available_units": r.available_units,
                "landlord_id": r.landlord_id,
            }
            for r in rows
        ]
        return success({"count": len(results), "results": results})

    return _run(db, work)


def get_listing_detail(listing_id, db=None) -> dict:
    """Return one listing, including its landlord if it has one."""
    listing_id, error = _as_int(listing_id, "listing_id", 1)
    if error:
        return failure(error)

    def work(session):
        listing = session.query(Listing).filter(Listing.id == listing_id).first()
        if listing is None:
            return failure(f"listing {listing_id} not found")
        landlord = None
        if listing.landlord_id is not None:
            owner = session.query(Landlord).filter(Landlord.id == listing.landlord_id).first()
            if owner is not None:
                landlord = {"id": owner.id, "name": owner.name, "email": owner.email}
        return success(
            {
                "id": listing.id,
                "address": listing.address,
                "listing_code": listing.listing_code,
                "available_units": listing.available_units,
                "landlord": landlord,
            }
        )

    return _run(db, work)


def aggregate_landlord_stats(landlord_id, db=None) -> dict:
    """Aggregate: listing count and available-unit totals for one landlord."""
    landlord_id, error = _as_int(landlord_id, "landlord_id", 1)
    if error:
        return failure(error)

    def work(session):
        landlord = session.query(Landlord).filter(Landlord.id == landlord_id).first()
        if landlord is None:
            return failure(f"landlord {landlord_id} not found")
        count, total, average = (
            session.query(
                func.count(Listing.id),
                func.coalesce(func.sum(Listing.available_units), 0),
                func.coalesce(func.avg(Listing.available_units), 0),
            )
            .filter(Listing.landlord_id == landlord_id)
            .one()
        )
        return success(
            {
                "landlord_id": landlord.id,
                "landlord_name": landlord.name,
                "listing_count": int(count),
                "total_available_units": int(total),
                "average_available_units": round(float(average), 2),
            }
        )

    return _run(db, work)