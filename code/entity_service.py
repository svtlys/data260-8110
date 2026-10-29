import uuid
from datetime import datetime, timezone

from kafka_config import PREFIX, TOPIC_RESPONSES

REQUIRED_TEXT = ("address", "landlord_name")
MAX_TEXT = 255
MAX_UNITS = 1000


def validate_listing(data) -> tuple:
    """(clean fields, None) or (None, error message). Rejects missing, empty and invalid values."""
    if not isinstance(data, dict):
        return None, "data must be an object"
    clean = {}
    for field in REQUIRED_TEXT:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"{field} is required and must be a non-empty string"
        if len(value) > MAX_TEXT:
            return None, f"{field} must be at most {MAX_TEXT} characters"
        clean[field] = value.strip()
    units = data.get("available_units")
    if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= MAX_UNITS:
        return None, f"available_units is required and must be an integer from 1 to {MAX_UNITS}"
    clean["available_units"] = units
    code = data.get("listing_code")
    if code is not None:
        if not isinstance(code, str) or not code.strip() or len(code) > 50:
            return None, "listing_code must be a non-empty string of at most 50 characters when given"
        clean["listing_code"] = code.strip()
    return clean, None


def reply_topic(request) -> str:
    """The topic named by reply_to, if it is one of our PREFIX topics; otherwise the default response topic."""
    target = request.get("reply_to") if isinstance(request, dict) else None
    return target if isinstance(target, str) and target.startswith(PREFIX + "_") else TOPIC_RESPONSES


def _reply(correlation_id, body: dict) -> dict:
    return {**body, "correlation_id": correlation_id}


def _create(request: dict, store: dict) -> dict:
    clean, error = validate_listing(request.get("data"))
    if error:
        return {"success": False, "error": error}
    listing_id = str(uuid.uuid4())
    store[listing_id] = {"listing_id": listing_id, **clean, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return {"success": True, "listing_id": listing_id, "message": "Listing created"}


def _get(request: dict, store: dict) -> dict:
    data = request.get("data")
    listing_id = data.get("listing_id") if isinstance(data, dict) else None
    if not isinstance(listing_id, str) or not listing_id.strip():
        return {"success": False, "error": "listing_id is required and must be a non-empty string"}
    if listing_id not in store:
        return {"success": False, "error": "Listing not found"}
    return {"success": True, "listing": dict(store[listing_id])}


def handle_request(request, store: dict) -> dict:
    """Validate one request message and return the response message (a dict that always has correlation_id)."""
    if not isinstance(request, dict):
        return _reply(None, {"success": False, "error": "request must be a JSON object"})
    correlation_id = request.get("correlation_id")
    if not isinstance(correlation_id, str) or not correlation_id.strip():
        return _reply(None, {"success": False, "error": "correlation_id is required"})
    operation = request.get("operation")
    if operation == "CREATE_LISTING":
        return _reply(correlation_id, _create(request, store))
    if operation == "GET_LISTING":
        return _reply(correlation_id, _get(request, store))
    return _reply(correlation_id, {"success": False, "error": "Unknown operation"})