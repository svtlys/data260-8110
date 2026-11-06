import logging
import os
import sys

SID4 = "8110"
PORT_BASE = 8000 + (int(SID4) % 900)
PREFIX = "s" + SID4
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
DOMAIN_ID = int(SID4) % 8

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SYNC_EVERY = 10
LLM_MODEL = "qwen3:8b"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
DEFAULT_THRESHOLD = 0.85


def setup_logging(level: int = logging.INFO) -> None:
    """Timestamped one-line logs on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)