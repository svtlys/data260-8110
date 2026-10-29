import argparse
import json
import logging
import sys

from client import new_correlation_id
from kafka_config import TOPIC_FINAL, TOPIC_INBOX, setup_logging
from kafka_io import KafkaProducer, collect, ensure_topics
from kafka_config import TOPIC_PARTITIONS

DEFAULT_Q = "What should I check before signing a lease for a one-bedroom apartment in San Jose?"


def main() -> int:
    setup_logging("send_question")
    log = logging.getLogger("send_question")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default=DEFAULT_Q)
    ap.add_argument("--entity", default=None, help="related listing id; used as the partition key downstream")
    ap.add_argument("--timeout", type=float, default=240.0)
    args = ap.parse_args()
    ensure_topics(TOPIC_PARTITIONS)
    cid = new_correlation_id()
    message = {"correlation_id": cid, "question": args.question, **({"entity_id": args.entity} if args.entity else {})}
    part, off = KafkaProducer(client_id="send_question").send(TOPIC_INBOX, message, key=args.entity or cid)
    log.info("SENT      topic=%s partition=%d offset=%d correlation_id=%s", TOPIC_INBOX, part, off, cid)
    final = collect(TOPIC_FINAL, lambda b: b.get("correlation_id") == cid, lambda f: len(f) >= 1, args.timeout)
    if not final:
        log.error("no final message within %.0fs - are planner.py, writer.py and reviewer.py running?", args.timeout)
        return 1
    result = {k: v for k, v in final[0].items() if not k.startswith("_")}
    log.info("FINAL     topic=%s partition=%d offset=%d correlation_id=%s", TOPIC_FINAL, final[0]["_partition"], final[0]["_offset"], cid)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())