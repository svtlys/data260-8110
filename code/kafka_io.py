import json
import logging
import threading
import time
import zlib
from dataclasses import dataclass

from kafka_config import BOOTSTRAP, HEARTBEAT_MS, SESSION_TIMEOUT_MS

logger = logging.getLogger("kafka_io")


@dataclass
class Msg:
    """One Kafka record as the application sees it."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes

    def key_text(self) -> str | None:
        return self.key.decode("utf-8", errors="replace") if self.key is not None else None


def encode(value) -> bytes:
    """dict -> JSON bytes (bytes pass through unchanged, so tests can send malformed payloads)."""
    return value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode("utf-8")


# ------------------------------------------------------------------ real Kafka

class KafkaProducer:
    """Synchronous producer: send() returns (partition, offset) once the broker has acknowledged the record."""

    def __init__(self, bootstrap: str = BOOTSTRAP, random_partitioner: bool = False, client_id: str = "hw8-producer") -> None:
        from confluent_kafka import Producer

        config = {"bootstrap.servers": bootstrap, "client.id": client_id, "acks": "all", "enable.idempotence": True}
        if random_partitioner:
            config["partitioner"] = "random"  # records without a key go to a random partition
        self._producer = Producer(config)

    def send(self, topic: str, value, key: str | None = None, partition: int | None = None) -> tuple:
        from confluent_kafka import KafkaException

        result = {}

        def done(err, msg) -> None:
            result["err"], result["pos"] = err, (msg.partition(), msg.offset()) if msg is not None else None

        extra = {} if partition is None else {"partition": partition}
        self._producer.produce(topic, value=encode(value), key=key.encode("utf-8") if key is not None else None,
                               on_delivery=done, **extra)
        self._producer.flush(15)
        if result.get("err") or "pos" not in result:
            raise KafkaException(result.get("err") or "delivery was not confirmed")
        return result["pos"]


class KafkaConsumer:
    """Group consumer with manual commits. `ready` is set when partitions have been assigned."""

    def __init__(self, group: str, topics: list, bootstrap: str = BOOTSTRAP, offset_reset: str = "earliest",
                 client_id: str = "hw8-consumer") -> None:
        from confluent_kafka import Consumer

        self.ready = threading.Event()
        self.assigned: list = []
        self._consumer = Consumer({
            "bootstrap.servers": bootstrap, "group.id": group, "client.id": client_id, "enable.auto.commit": False,
            "auto.offset.reset": offset_reset, "session.timeout.ms": SESSION_TIMEOUT_MS,
            "heartbeat.interval.ms": HEARTBEAT_MS, "max.poll.interval.ms": 300000})
        self._consumer.subscribe(topics, on_assign=self._on_assign, on_revoke=self._on_revoke)

    def _on_assign(self, consumer, partitions) -> None:
        self.assigned = [(p.topic, p.partition) for p in partitions]
        logger.info("ASSIGNED partitions %s", self.assigned)
        self.ready.set()

    def _on_revoke(self, consumer, partitions) -> None:
        self.ready.clear()

    def poll(self, timeout: float = 1.0) -> Msg | None:
        from confluent_kafka import KafkaError, KafkaException

        raw = self._consumer.poll(timeout)
        if raw is None:
            return None
        if raw.error():
            if raw.error().code() == KafkaError._PARTITION_EOF:
                return None
            raise KafkaException(raw.error())
        return Msg(raw.topic(), raw.partition(), raw.offset(), raw.key(), raw.value())

    def commit(self, msg: Msg) -> None:
        from confluent_kafka import TopicPartition

        self._consumer.commit(offsets=[TopicPartition(msg.topic, msg.partition, msg.offset + 1)], asynchronous=False)

    def close(self) -> None:
        self._consumer.close()


def wait_for_broker(bootstrap: str = BOOTSTRAP, timeout: float = 60.0):
    """Block until the broker answers; returns an AdminClient."""
    from confluent_kafka.admin import AdminClient

    admin, deadline = AdminClient({"bootstrap.servers": bootstrap}), time.time() + timeout
    while True:
        try:
            admin.list_topics(timeout=3)
            return admin
        except Exception as exc:
            if time.time() > deadline:
                raise RuntimeError(f"Kafka is not reachable at {bootstrap}: {exc}") from exc
            time.sleep(1)


def ensure_topics(specs: dict, bootstrap: str = BOOTSTRAP) -> dict:
    """Create the topics that do not exist yet. specs = {name: partitions}. Returns {name: 'created'|'exists'}."""
    from confluent_kafka.admin import NewTopic

    admin = wait_for_broker(bootstrap)
    existing = set(admin.list_topics(timeout=10).topics)
    todo = [NewTopic(n, num_partitions=p, replication_factor=1) for n, p in specs.items() if n not in existing]
    for name, future in admin.create_topics(todo).items() if todo else []:
        try:
            future.result()
        except Exception as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise
    return {n: ("exists" if n in existing else "created") for n in specs}


def partition_counts(bootstrap: str = BOOTSTRAP) -> dict:
    """{topic: number of partitions} for every topic on the broker."""
    admin = wait_for_broker(bootstrap)
    return {n: len(t.partitions) for n, t in admin.list_topics(timeout=10).topics.items()}


def committed_offsets(group: str, topic: str, bootstrap: str = BOOTSTRAP) -> dict:
    """{partition: committed offset or None} for a consumer group (the next offset it will read)."""
    from confluent_kafka import Consumer, TopicPartition

    n = partition_counts(bootstrap)[topic]
    probe = Consumer({"bootstrap.servers": bootstrap, "group.id": group, "enable.auto.commit": False})
    found = probe.committed([TopicPartition(topic, p) for p in range(n)], timeout=10)
    probe.close()
    return {tp.partition: (tp.offset if tp.offset >= 0 else None) for tp in found}


def collect(topic: str, predicate, done, timeout: float, bootstrap: str = BOOTSTRAP) -> list:
    """Read a topic from the start with a throw-away group; return parsed JSON bodies that satisfy predicate.
    Stops early when done(list) is true, otherwise after timeout seconds."""
    import uuid

    consumer = KafkaConsumer(f"collect_{uuid.uuid4().hex[:8]}", [topic], bootstrap, client_id="collector")
    consumer.ready.wait(15)
    found, deadline = [], time.time() + timeout
    while time.time() < deadline and not done(found):
        msg = consumer.poll(0.5)
        if msg is None:
            continue
        try:
            body = json.loads(msg.value)
        except ValueError:
            continue
        if predicate(body):
            found.append({**body, "_partition": msg.partition, "_offset": msg.offset})
    consumer.close()
    return found


# ------------------------------------------------------------------ in-memory stand-in (offline tests)

class InMemoryBroker:
    """Partitioned logs, consumer groups with range assignment, and committed offsets. No network."""

    def __init__(self) -> None:
        self.logs: dict = {}
        self.committed: dict = {}
        self.members: dict = {}
        self._rr: dict = {}

    def create_topic(self, name: str, partitions: int = 1) -> None:
        self.logs.setdefault(name, [[] for _ in range(partitions)])

    def append(self, topic: str, value: bytes, key: bytes | None, partition: int | None = None) -> tuple:
        logs = self.logs.setdefault(topic, [[]])
        if partition is None:
            if key is not None:
                partition = zlib.crc32(key) % len(logs)
            else:
                partition = self._rr[topic] = (self._rr.get(topic, -1) + 1) % len(logs)
        offset = len(logs[partition])
        logs[partition].append(Msg(topic, partition, offset, key, value))
        return partition, offset


class InMemoryProducer:
    """Same send() as KafkaProducer."""

    def __init__(self, broker: InMemoryBroker) -> None:
        self.broker = broker

    def send(self, topic: str, value, key: str | None = None, partition: int | None = None) -> tuple:
        return self.broker.append(topic, encode(value), key.encode("utf-8") if key is not None else None, partition)


class InMemoryConsumer:
    """Same poll()/commit() as KafkaConsumer. kill() leaves the group without committing (a crashed process)."""

    def __init__(self, broker: InMemoryBroker, group: str, topics: list, offset_reset: str = "earliest") -> None:
        self.broker, self.group, self.topics, self.reset = broker, group, topics, offset_reset
        self.ready, self.assigned, self.alive = threading.Event(), [], True
        self.position: dict = {}
        broker.members.setdefault(group, []).append(self)
        for member in broker.members[group]:
            member.rebalance()

    def rebalance(self) -> None:
        members = [m for m in self.broker.members[self.group] if m.alive]
        index = members.index(self) if self in members else 0
        self.assigned = [(t, p) for t in self.topics for p in range(len(self.broker.logs.get(t, [[]]))) if p % max(len(members), 1) == index]
        self.position = {}
        for t, p in self.assigned:
            end = len(self.broker.logs[t][p])
            default = end if self.reset == "latest" else 0
            self.position[(t, p)] = self.broker.committed.get((self.group, t, p), default)
        self.ready.set()

    def poll(self, timeout: float = 0.0) -> Msg | None:
        for (t, p), pos in sorted(self.position.items()):
            if pos < len(self.broker.logs[t][p]):
                self.position[(t, p)] = pos + 1
                return self.broker.logs[t][p][pos]
        return None

    def commit(self, msg: Msg) -> None:
        self.broker.committed[(self.group, msg.topic, msg.partition)] = msg.offset + 1

    def kill(self) -> None:
        self.alive = False
        for member in self.broker.members[self.group]:
            if member.alive:
                member.rebalance()

    def close(self) -> None:
        self.kill()