import json
import logging
import os
import threading

from entity_service import handle_request, reply_topic
from kafka_config import GROUP_ENTITY_WORKER, TOPIC_PARTITIONS, TOPIC_REQUESTS, setup_logging

logger = logging.getLogger("worker")


def decode(raw: bytes):
    """JSON bytes -> object, or None when the bytes are not valid JSON."""
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def process(msg, store: dict, seen: dict, producer, idempotent: bool) -> dict:
    """Handle one request record and publish the response. Returns the response dict."""
    request = decode(msg.value)
    cid = request.get("correlation_id") if isinstance(request, dict) else None
    op = request.get("operation") if isinstance(request, dict) else None
    logger.info("RECEIVED  topic=%s partition=%d offset=%d correlation_id=%s operation=%s", msg.topic, msg.partition, msg.offset, cid, op)
    if idempotent and cid in seen:
        response = seen[cid]
        logger.info("DUPLICATE correlation_id=%s already processed -> replaying cached response, no new side effect", cid)
    else:
        response = handle_request(request, store)
        if idempotent and cid:
            seen[cid] = response
        logger.info("PROCESSED correlation_id=%s success=%s %s", cid, response["success"],
                    response.get("listing_id") or response.get("error") or "")
    target = reply_topic(request)
    producer.send(target, response, key=response.get("correlation_id"))
    logger.info("REPLIED   topic=%s correlation_id=%s success=%s", target, response["correlation_id"], response["success"])
    return response


def run_worker(consumer, producer, store: dict, seen: dict, stop: threading.Event, idempotent: bool = True) -> None:
    """Poll -> process -> send response -> commit. A crash before commit means the record is redelivered."""
    logger.info("Consumer is ready and listening...")
    while not stop.is_set():
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        process(msg, store, seen, producer, idempotent)
        consumer.commit(msg)


def main() -> None:
    from kafka_io import KafkaConsumer, KafkaProducer, ensure_topics

    setup_logging("worker")
    ensure_topics(TOPIC_PARTITIONS)
    consumer = KafkaConsumer(GROUP_ENTITY_WORKER, [TOPIC_REQUESTS], client_id="entity-worker")
    producer = KafkaProducer(client_id="entity-worker")
    idempotent = os.environ.get("IDEMPOTENT", "1") == "1"
    logger.info("Worker starting (idempotent=%s)", idempotent)
    try:
        run_worker(consumer, producer, {}, {}, threading.Event(), idempotent)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


if __name__ == "__main__":
    main()