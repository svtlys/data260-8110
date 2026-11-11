import json
import os
import tempfile
import threading
import time

os.environ["LLM_MODE"] = "stub"
os.environ["TRACE_FILE"] = os.path.join(tempfile.mkdtemp(), "spans.jsonl")

from agent_core import run_agent  # noqa: E402
from embedder import HashEmbedder  # noqa: E402
from kafka_config import TOPIC_DEAD_LETTER, TOPIC_DRAFTS, TOPIC_FINAL, TOPIC_INBOX, TOPIC_PARTITIONS, TOPIC_TASKS  # noqa: E402
from kafka_io import InMemoryBroker, InMemoryConsumer, InMemoryProducer  # noqa: E402
from planner import make_plan  # noqa: E402
from reviewer import review  # noqa: E402
from semantic_cache import SemanticCache  # noqa: E402
from tracing import failing_stage, record_span, span, spans_for, trace_path  # noqa: E402
from traced_service import TracedService  # noqa: E402
from vector_store import MemoryVectorStore  # noqa: E402
from writer import make_draft  # noqa: E402

Q = "What should I check before signing a lease?"


def start_pipeline():
    b = InMemoryBroker()
    for topic, parts in TOPIC_PARTITIONS.items():
        b.create_topic(topic, parts)
    stops = []
    for name, group, i, o, fn in (("planner", "gp", TOPIC_INBOX, TOPIC_TASKS, make_plan), ("writer", "gw", TOPIC_TASKS, TOPIC_DRAFTS, make_draft),
                                  ("reviewer", "gr", TOPIC_DRAFTS, TOPIC_FINAL, review)):
        stop, consumer = threading.Event(), InMemoryConsumer(b, group, [i])
        threading.Thread(target=run_agent, args=(name, consumer, InMemoryProducer(b), o, fn, stop), kwargs={"backoff": 0}, daemon=True).start()
        stops.append(stop)
    return b, stops


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.01)
    return cond()


def send(b, cid, question):
    InMemoryProducer(b).send(TOPIC_INBOX, {"correlation_id": cid, "question": question, "sent_at": time.time()}, key=cid)


def test_record_span_fields_and_error_only_when_given():
    ok = record_span("t-a", "planner", 100.0, 100.25)
    bad = record_span("t-a", "writer", 100.25, 100.5, "error", "ValueError: boom", attempts=3)
    assert set(ok) >= {"trace_id", "stage", "start", "end", "duration_ms", "status"} and "error" not in ok and ok["duration_ms"] == 250.0
    assert bad["status"] == "error" and bad["error"] == "ValueError: boom" and bad["attrs"] == {"attempts": 3}
    assert record_span(None, "planner", 1, 2) == {}
    assert [s["stage"] for s in spans_for("t-a")] == ["planner", "writer"]


def test_span_context_manager_records_exception():
    try:
        with span("t-b", "evaluation"):
            raise TimeoutError("judge unavailable")
    except TimeoutError:
        pass
    s = spans_for("t-b")[0]
    assert s["status"] == "error" and s["error"] == "TimeoutError: judge unavailable"


def test_cache_miss_then_hit_have_distinguishable_cache_lookup_spans():
    calls = []

    def agent(question, context, trace_id=None):
        calls.append(trace_id)
        return "an answer long enough to approve", True

    service = TracedService(SemanticCache(MemoryVectorStore(), HashEmbedder(), agent))
    miss, hit = service.ask(Q, trace_id="t-miss"), service.ask(Q, trace_id="t-hit")
    assert calls == ["t-miss"] and miss.trace_id == "t-miss" and hit.is_cached
    sm, sh = spans_for("t-miss"), spans_for("t-hit")
    assert trace_path(sm) == "cache_miss" and trace_path(sh) == "cache_hit"
    assert [s["stage"] for s in sh] == ["request", "cache_lookup"] or {s["stage"] for s in sh} == {"request", "cache_lookup"}
    assert next(s for s in sh if s["stage"] == "cache_lookup")["attrs"]["cache_hit"] is True


def test_pipeline_writes_stage_and_queue_spans_with_the_correlation_id_as_trace_id():
    b, stops = start_pipeline()
    send(b, "t-ok", Q)
    assert wait_for(lambda: sum(len(p) for p in b.logs[TOPIC_FINAL]) == 1)
    time.sleep(0.05)
    spans = spans_for("t-ok")
    stages = [s["stage"] for s in spans]
    assert stages == ["queue_inbox", "planner", "queue_tasks", "writer", "queue_drafts", "reviewer"], stages
    assert all(s["status"] == "ok" and s["duration_ms"] >= 0 for s in spans)
    final = json.loads(b.logs[TOPIC_FINAL][0][0].value)
    assert final["correlation_id"] == "t-ok" and "trace_id" not in final and isinstance(final["sent_at"], float)
    for stop in stops:
        stop.set()


def test_failed_request_records_the_failing_stage_and_error():
    b, stops = start_pipeline()
    send(b, "t-bad", "   ")
    assert wait_for(lambda: sum(len(p) for p in b.logs[TOPIC_DEAD_LETTER]) == 1)
    time.sleep(0.05)
    spans = spans_for("t-bad")
    bad = failing_stage(spans)
    assert bad["stage"] == "planner" and "ValueError: inbox message has no question" in bad["error"] and bad["attrs"]["attempts"] == 3
    assert [s["stage"] for s in spans] == ["queue_inbox", "planner"]
    for stop in stops:
        stop.set()