from pymongo import ASCENDING, MongoClient
from pymongo.errors import OperationFailure

import doc_config as cfg

_client = None

LISTING_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["title", "status", "property_type", "available_from",
                     "created_at", "updated_at"],
        "properties": {
            "title": {"bsonType": "string", "minLength": 1, "maxLength": 100},
            "description": {"bsonType": ["string", "null"], "maxLength": 2000},
            "status": {"enum": ["active", "pending", "rented", "withdrawn"]},
            "property_type": {"enum": ["studio", "one_bedroom", "two_bedroom",
                                       "three_plus"]},
            "available_from": {"bsonType": "date"},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(cfg.MONGO_URI,
                              serverSelectionTimeoutMS=cfg.MONGO_TIMEOUT_MS)
    return _client


def get_db():
    return get_client()[cfg.DB_NAME]


def ensure_collection(db=None, name=None, validator=None):
    """Create the collection with a $jsonSchema validator, or update it (collMod)."""
    db = db if db is not None else get_db()
    name = name or cfg.COLLECTION_NAME
    validator = validator or LISTING_VALIDATOR
    if name not in db.list_collection_names():
        db.create_collection(name, validator=validator, validationLevel="strict",
                             validationAction="error")
    else:
        db.command("collMod", name, validator=validator,
                   validationLevel="strict", validationAction="error")
    return db[name]


def listing_collection():
    return get_db()[cfg.COLLECTION_NAME]


def ping() -> bool:
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False