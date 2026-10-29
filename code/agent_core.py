import json
import logging
import os
import threading
import time

from kafka_config import MAX_RETRIES, RETRY_BACKOFF_S, STATE_DIR, TOPIC_DEAD_LETTER

CARRY = ("correlation_id", "entity_id", "run_id", "seq", "idx")


class SimulatedCrash(BaseException):
    """Raised by tests to model a process dying mid-work: it must not be caught by the retry logic."""


class SeenStore:
    """Set of completed correlation_ids, appended to a file so a restarted agent still remembers them."""

    def __init__(self, path: str | None = None) -> None:
        self.path, self.ids = path, set()
        if path and os.path.exists(path):
            self.ids = {ln.strip() for ln in open(path, encoding="utf-8") if ln.strip()}

    def __contains__(self, cid) -> bool:
        return cid in self.ids

    def add(self, cid: str) -> None:
        self.ids.add(cid)
        if self.path:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(cid + "\n")


def seen_store_for(agent: str) -> SeenStore:
    return SeenStore(os.path.join(STATE_DIR, f"{agent}_seen.txt"))


def decode(raw: bytes):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def carry(body: dict) -> dict:
    """Fields every stage copies forward unchanged (correlation_id first of all)."""
    return {k: body[k] for k in CARRY if k in body}


def default_key(out: dict) -> str | None:
    """Partition key: the related entity if there is one, otherwise the correlation_id."""
    return out.get("entity_id") or out.get("correlation_id")


def run_with_retries(log: logging.Logger, transform, body, msg, max_retries, backoff: float):
    """(result, None) on success, (None, last error text) when all attempts failed. SimulatedCrash is never caught."""
    attempt, error = 0, ""
    while max_retries is None or attempt < max_retries:
        attempt += 1
        try:
            return transform(body, msg), None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log.info("RETRY    attempt %d/%s failed: %s", attempt, max_retries if max_retries is not None else "unbounded", error)
            time.sleep(backoff)
    return None, error


def send_to_dead_letter(producer, log: logging.Logger, stage: str, msg, body, error: str, attempts: int) -> None:
    record = {"stage": stage, "source_topic": msg.topic, "partition": msg.partition, "offset": msg.offset,
              "correlation_id": body.get("correlation_id") if isinstance(body, dict) else None,
              "error": error, "attempts": attempts, "original": msg.value.decode("utf-8", errors="replace")}
    producer.send(TOPIC_DEAD_LETTER, record, key=record["correlation_id"])
    log.info("DEAD-LETTER correlation_id=%s after %d attempts -> %s (%s)", record["correlation_id"], attempts, TOPIC_DEAD_LETTER, error)


def process_one(name, msg, consumer, producer, out_topic, transform, opts: dict) -> None:
    """Handle one record. Offset handling: commit after success / after dead-lettering, never before (unless commit_early)."""
    log = logging.getLogger(name)
    body = decode(msg.value)
    cid = body.get("correlation_id") if isinstance(body, dict) else None
    log.info("RECEIVED  topic=%s partition=%d offset=%d key=%s correlation_id=%s", msg.topic, msg.partition, msg.offset, msg.key_text(), cid)
    accept = opts.get("accept")
    if accept is not None and not (isinstance(body, dict) and accept(body)):
        consumer.commit(msg)
        return
    seen = opts.get("seen")
    if seen is not None and cid in seen:
        log.info("DUPLICATE correlation_id=%s already completed -> skipped, no new side effect", cid)
        consumer.commit(msg)
        return
    if opts.get("commit_early"):
        consumer.commit(msg)
        log.info("COMMITTED offset %d BEFORE processing (unsafe variant)", msg.offset + 1)
    result, error = run_with_retries(log, transform, body, msg, opts.get("max_retries"), opts.get("backoff", RETRY_BACKOFF_S))
    if error is not None:
        send_to_dead_letter(producer, log, name, msg, body, error, opts["max_retries"])
    elif result is not None:
        key = opts.get("key_fn", default_key)(result)
        part, off = producer.send(out_topic, result, key=key)
        log.info("SENT      topic=%s partition=%d offset=%d key=%s correlation_id=%s", out_topic, part, off, key, cid)
    if seen is not None and cid and error is None:
        seen.add(cid)
    if not opts.get("commit_early"):
        consumer.commit(msg)
        log.info("COMMITTED offset %d (after successful processing)", msg.offset + 1)


def run_agent(name, consumer, producer, out_topic, transform, stop: threading.Event, **opts) -> None:
    """Loop until stop is set. opts: seen, max_retries, backoff, commit_early, accept, key_fn."""
    opts.setdefault("max_retries", MAX_RETRIES)
    logging.getLogger(name).info("Consumer is ready and listening...")
    while not stop.is_set():
        msg = consumer.poll(0.5)
        if msg is not None:
            process_one(name, msg, consumer, producer, out_topic, transform, opts)


def run_main(name: str, group: str, in_topic: str, out_topic: str, transform, accept=None) -> None:
    """Entry point shared by planner.py, writer.py, reviewer.py (environment switches: IDEMPOTENT, COMMIT_EARLY, MAX_RETRIES)."""
    from kafka_config import TOPIC_PARTITIONS, setup_logging
    from kafka_io import KafkaConsumer, KafkaProducer, ensure_topics

    setup_logging(name)
    ensure_topics(TOPIC_PARTITIONS)
    consumer = KafkaConsumer(group, [in_topic], client_id=f"{name}-{os.getpid()}")
    producer = KafkaProducer(client_id=name)
    retries = os.environ.get("MAX_RETRIES")
    opts = {"seen": seen_store_for(name) if os.environ.get("IDEMPOTENT", "1") == "1" else None,
            "commit_early": os.environ.get("COMMIT_EARLY", "0") == "1", "accept": accept,
            "max_retries": (None if retries == "unbounded" else int(retries)) if retries else MAX_RETRIES}
    logging.getLogger(name).info("%s starting: group=%s in=%s out=%s idempotent=%s commit_early=%s max_retries=%s", name, group, in_topic,
                                 out_topic, opts["seen"] is not None, opts["commit_early"], opts["max_retries"])
    try:
        run_agent(name, consumer, producer, out_topic, transform, threading.Event(), **opts)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()