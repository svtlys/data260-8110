import json
import sys

from kafka_config import TOPIC_DRAFTS, TOPIC_FINAL, TOPIC_INBOX, TOPIC_TASKS
from kafka_io import collect


def main(cid: str) -> int:
    for topic in (TOPIC_INBOX, TOPIC_TASKS, TOPIC_DRAFTS, TOPIC_FINAL):
        found = collect(topic, lambda b: b.get("correlation_id") == cid, lambda f: len(f) >= 1, 10)
        if not found:
            print(f"{topic}: (nothing found)")
            continue
        body = {k: (v if k not in ("draft", "answer") else str(v)[:80] + "...") for k, v in found[0].items() if not k.startswith("_")}
        print(f"{topic} partition={found[0]['_partition']} offset={found[0]['_offset']}  {json.dumps(body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))