import os

PORT_BASE = 8010
PREFIX = "s8110"

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", f"{PREFIX}_doc")
COLLECTION_NAME = "listing_docs"
MONGO_TIMEOUT_MS = 2000

CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")