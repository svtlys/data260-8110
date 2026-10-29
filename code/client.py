import logging
import threading
import time
import uuid

from kafka_config import PREFIX, RESPONSE_TIMEOUT_S, TOPIC_REQUESTS, TOPIC_RESPONSES
from kafka_io import encode

logger = logging.getLogger("client")


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def build_request(operation: str, data: dict, correlation_id: str | None = None) -> dict:
    """The request message schema: correlation_id, reply_to, operation, data."""
    return {"correlation_id": correlation_id or new_correlation_id(), "reply_to": TOPIC_RESPONSES,
            "operation": operation, "data": data}


class RequestClient:
    """Sends requests and waits for the response with the same correlation_id."""

    def __init__(self, producer, consumer) -> None:
        self.producer, self.consumer = producer, consumer
        self._pending: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self.consumer.ready.wait(30)

    def stop(self) -> None:
        """Stop listening and leave the consumer group, so a later client in the same group gets the partition."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(3)
        self.consumer.close()

    def _listen(self) -> None:
        import json

        while not self._stop.is_set():
            msg = self.consumer.poll(0.5)
            if msg is None:
                continue
            try:
                body = json.loads(msg.value)
            except ValueError:
                continue
            cid = body.get("correlation_id") if isinstance(body, dict) else None
            with self._lock:
                slot = self._pending.get(cid)
            if slot is not None:
                logger.info("CLIENT RECEIVED topic=%s partition=%d offset=%d correlation_id=%s success=%s",
                            msg.topic, msg.partition, msg.offset, cid, body.get("success"))
                slot["response"] = body
                slot["event"].set()

    def request(self, request: dict, timeout: float = RESPONSE_TIMEOUT_S) -> dict:
        """Publish the request unchanged and block until the matching response arrives (or TimeoutError)."""
        cid = request["correlation_id"]
        slot = {"event": threading.Event(), "response": None}
        with self._lock:
            self._pending[cid] = slot
        part, off = self.producer.send(TOPIC_REQUESTS, request, key=None)
        logger.info("CLIENT SENT     topic=%s partition=%d offset=%d correlation_id=%s operation=%s",
                    TOPIC_REQUESTS, part, off, cid, request["operation"])
        if not slot["event"].wait(timeout):
            with self._lock:
                self._pending.pop(cid, None)
            raise TimeoutError(f"no response for correlation_id={cid} within {timeout}s")
        with self._lock:
            self._pending.pop(cid, None)
        return slot["response"]


def make_client(group_suffix: str | None = None) -> RequestClient:
    """Real-Kafka client: its own unique group, reading only new responses."""
    from kafka_io import KafkaConsumer, KafkaProducer

    group = f"{PREFIX}_client_{group_suffix or uuid.uuid4().hex[:8]}"
    consumer = KafkaConsumer(group, [TOPIC_RESPONSES], offset_reset="latest", client_id="client")
    client = RequestClient(KafkaProducer(client_id="client"), consumer)
    client.start()
    time.sleep(0.5)
    return client


__all__ = ["RequestClient", "build_request", "new_correlation_id", "make_client", "encode"]