import json
import logging
import subprocess
import sys

from client import build_request, make_client, new_correlation_id
from kafka_config import PORT_BASE, PREFIX, SEED, SID4, TOPIC_REQUESTS, TOPIC_RESPONSES, setup_logging

logger = logging.getLogger("demo")
SAMPLE = {"address": "123 Market St, San Jose, CA 95113", "available_units": 3, "listing_code": "SJ-0042", "landlord_name": "Bayview Rentals"}


def worker_lines(correlation_id: str) -> list:
    """The worker's RECEIVED / PROCESSED / REPLIED lines for this correlation_id (docker logs); [] if docker is unavailable."""
    try:
        out = subprocess.run(["docker", "logs", f"{PREFIX}-worker"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln for ln in (out.stdout + out.stderr).splitlines() if correlation_id in ln]


def show_exchange(title: str, request: dict, response: dict) -> None:
    logger.info("=== %s ===", title)
    logger.info("REQUEST  %s", json.dumps(request))
    for line in worker_lines(request["correlation_id"]):
        logger.info("WORKER LOG  %s", line)
    logger.info("RESPONSE %s", json.dumps(response))


def main() -> int:
    setup_logging("demo")
    logger.info("HW8 demo | name=Alyssa Gomez SID4=%s PORT_BASE=%d PREFIX=%s SEED=%d | topics: %s -> %s",
                SID4, PORT_BASE, PREFIX, SEED, TOPIC_REQUESTS, TOPIC_RESPONSES)
    client = make_client("demo")
    correlation_id = new_correlation_id()                                   # step 1
    logger.info("Step 1: created correlation_id=%s", correlation_id)
    create_req = build_request("CREATE_LISTING", SAMPLE, correlation_id)    # steps 2-3 (client logs CLIENT SENT)
    create_resp = client.request(create_req)                                # steps 4-6 (worker + client logs)
    show_exchange("CREATE_LISTING", create_req, create_resp)
    if not create_resp.get("success"):
        logger.error("CREATE failed: %s", create_resp)
        return 1
    listing_id = create_resp["listing_id"]                                  # step 7
    logger.info("Step 7: extracted listing_id=%s", listing_id)
    get_cid = new_correlation_id()   # each request gets its own id (a reused id would be treated as a duplicate replay)
    get_req = build_request("GET_LISTING", {"listing_id": listing_id}, get_cid)          # step 8
    get_resp = client.request(get_req)                                      # step 9
    show_exchange("GET_LISTING", get_req, get_resp)
    logger.info("Step 10: retrieved listing = %s", json.dumps(get_resp.get("listing")))
    preserved = create_resp["correlation_id"] == correlation_id and get_resp["correlation_id"] == get_cid
    logger.info("Step 10: correlation_id preserved (CREATE and GET each echoed unchanged) = %s", preserved)
    client.stop()
    return 0 if preserved and get_resp.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())