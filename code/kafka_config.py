import logging
import os
import sys

SID4 = "8110"
PORT_BASE = 8000 + (int(SID4) % 900)
PREFIX = "s" + SID4
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
DOMAIN_ID = int(SID4) % 8

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")

TOPIC_REQUESTS = f"{PREFIX}_entity_requests"
TOPIC_RESPONSES = f"{PREFIX}_entity_responses"
TOPIC_INBOX = f"{PREFIX}_inbox"
TOPIC_TASKS = f"{PREFIX}_tasks"
TOPIC_DRAFTS = f"{PREFIX}_drafts"
TOPIC_FINAL = f"{PREFIX}_final"
TOPIC_DEAD_LETTER = f"{PREFIX}_dead_letter"

TOPIC_PARTITIONS = {TOPIC_REQUESTS: 1, TOPIC_RESPONSES: 1, TOPIC_INBOX: 1, TOPIC_TASKS: 2, TOPIC_DRAFTS: 1,
                    TOPIC_FINAL: 1, TOPIC_DEAD_LETTER: 1}

GROUP_SUFFIX = os.environ.get("GROUP_SUFFIX", "")  # lets test runs use private consumer groups
GROUP_ENTITY_WORKER = f"{PREFIX}_entity_worker"
GROUP_PLANNER = f"{PREFIX}_planner{GROUP_SUFFIX}"
GROUP_WRITER = f"{PREFIX}_writer{GROUP_SUFFIX}"
GROUP_REVIEWER = f"{PREFIX}_reviewer{GROUP_SUFFIX}"
STATE_DIR = os.environ.get("STATE_DIR", ".state")

MAX_RETRIES = 3
RETRY_BACKOFF_S = 0.5
SESSION_TIMEOUT_MS = 6000
HEARTBEAT_MS = 2000
RESPONSE_TIMEOUT_S = 15.0
LLM_MODEL = "qwen3:8b"


def setup_logging(component: str, level: int = logging.INFO) -> logging.Logger:
    """One-line log format with millisecond timestamps and the component name, written to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("kafka").setLevel(logging.WARNING)
    return logging.getLogger(component)