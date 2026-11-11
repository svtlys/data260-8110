import json
import logging
import time
import uuid

from cache_config import PREFIX
from kafka_config import TOPIC_FINAL, TOPIC_INBOX
from tracing import record_span

logger = logging.getLogger("agent_adapter")


class PipelineClient:
    """Long-lived client: one consumer on <PREFIX>_final (private group, new messages only), one producer to <PREFIX>_inbox."""

    def __init__(self, timeout: float = 300.0) -> None:
        from kafka_io import KafkaConsumer, KafkaProducer

        self.timeout = timeout
        self.consumer = KafkaConsumer(f"{PREFIX}_hw9_client_{uuid.uuid4().hex[:8]}", [TOPIC_FINAL], offset_reset="latest", client_id="hw9-client")
        self.consumer.ready.wait(30)
        for _ in range(4):  # let the consumer settle on its start position before the first request
            self.consumer.poll(0.5)
        self.producer = KafkaProducer(client_id="hw9-client")

    def ask(self, question: str, context: str | None = None, trace_id: str | None = None, timeout: float | None = None) -> tuple:
        """(answer, approved). trace_id (the correlation_id) is generated when not given. Raises TimeoutError when there is no answer in time."""
        cid = trace_id or str(uuid.uuid4())
        message = {"correlation_id": cid, "question": question, "sent_at": time.time(), **({"context": context} if context else {})}
        self.producer.send(TOPIC_INBOX, message, key=cid)
        logger.info("PIPELINE sent question correlation_id=%s", cid)
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            msg = self.consumer.poll(1.0)
            if msg is None:
                continue
            try:
                body = json.loads(msg.value)
            except ValueError:
                continue
            if body.get("correlation_id") == cid:
                if isinstance(body.get("sent_at"), (int, float)):
                    record_span(cid, "queue_final", body["sent_at"], time.time(), topic=TOPIC_FINAL, partition=msg.partition, offset=msg.offset)
                logger.info("PIPELINE final status=%s correlation_id=%s", body.get("status"), cid)
                return body.get("answer", ""), body.get("status") == "approved"
        raise TimeoutError(f"no final answer for {cid} within {timeout or self.timeout:.0f}s - are planner.py, writer.py, reviewer.py running?")

    def __call__(self, question: str, context: str | None = None, trace_id: str | None = None) -> tuple:
        return self.ask(question, context, trace_id)

    def close(self) -> None:
        self.consumer.close()