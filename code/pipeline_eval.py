import logging
import threading
import time

from agent_core import decode
from judge import JudgeUnavailable, settings
from kafka_config import PREFIX, TOPIC_DRAFTS, TOPIC_FINAL, TOPIC_TASKS
from tracing import record_span

logger = logging.getLogger("pipeline_eval")
KIND_BY_TOPIC = {TOPIC_TASKS: "plan", TOPIC_DRAFTS: "draft", TOPIC_FINAL: "final"}
# record name, judge metric, which input is judged
PLAN = (("plan_quality", "plan_quality", "plan"), ("writer_helpfulness", "writer_helpfulness", "draft"),
        ("final_helpfulness", "final_helpfulness", "final"), ("draft_under_final_metric", "final_helpfulness", "draft"))
CHANGE_THRESHOLD = 0.25


class MessageCollector:
    """Background consumer that stores the plan/draft/final message of every correlation_id it sees."""

    def __init__(self, consumer) -> None:
        self.consumer, self.by_cid, self.lock, self.stop = consumer, {}, threading.Lock(), threading.Event()

    def _handle(self, msg) -> None:
        body, kind = decode(msg.value), KIND_BY_TOPIC.get(msg.topic)
        if isinstance(body, dict) and body.get("correlation_id") and kind:
            with self.lock:
                self.by_cid.setdefault(body["correlation_id"], {})[kind] = {"body": body, "topic": msg.topic, "partition": msg.partition, "offset": msg.offset}

    def _run(self) -> None:
        while not self.stop.is_set():
            msg = self.consumer.poll(0.5)
            if msg is not None:
                self._handle(msg)

    def start(self) -> "MessageCollector":
        """Let the consumer settle on its start position, then collect in the background."""
        ready = getattr(self.consumer, "ready", None)
        if ready is not None:
            ready.wait(30)
        for _ in range(4):
            msg = self.consumer.poll(0.5)
            if msg is not None:
                self._handle(msg)
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def wait(self, cid: str, timeout: float = 30.0) -> dict:
        """The messages collected for cid; returns early when all three are there, partial after the timeout."""
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                got = dict(self.by_cid.get(cid, {}))
            if len(got) == len(KIND_BY_TOPIC):
                return got
            time.sleep(0.1)
        with self.lock:
            return dict(self.by_cid.get(cid, {}))

    def close(self) -> None:
        self.stop.set()
        self.consumer.close()


def make_collector() -> MessageCollector:
    """Real Kafka collector on new messages only (start it BEFORE sending the requests to evaluate)."""
    import uuid

    from kafka_io import KafkaConsumer

    consumer = KafkaConsumer(f"{PREFIX}_hw10_eval_{uuid.uuid4().hex[:8]}", list(KIND_BY_TOPIC), offset_reset="latest", client_id="hw10-eval")
    return MessageCollector(consumer).start()


def extract_inputs(msgs: dict) -> tuple[dict, list]:
    """(inputs, problems): the texts to judge, and a list of reasons why something cannot be judged (malformed or missing messages)."""
    problems, inputs = [], {"question": None, "plan": None, "draft": None, "final": None, "context": None}
    for kind in KIND_BY_TOPIC.values():
        if kind not in msgs:
            problems.append(f"missing {kind} message")
    plan_body, draft_body, final_body = (msgs.get(k, {}).get("body", {}) for k in ("plan", "draft", "final"))
    inputs["question"] = plan_body.get("question") or draft_body.get("question")
    steps = plan_body.get("plan")
    if isinstance(steps, list) and steps and all(isinstance(s, str) for s in steps):
        inputs["plan"] = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    elif "plan" in msgs:
        problems.append("plan is not a non-empty list of strings")
    for key, body in (("draft", draft_body), ("final", final_body)):
        text = body.get("draft" if key == "draft" else "answer")
        if isinstance(text, str) and text.strip():
            inputs[key] = text.strip()
        elif key in msgs:
            problems.append(f"{key} text is empty or not a string" + (f" (reviewer status={body.get('status')})" if key == "final" else ""))
    ctx = plan_body.get("context") or draft_body.get("context")
    inputs["context"] = [ctx] if isinstance(ctx, str) and ctx else None
    if not inputs["question"]:
        problems.append("no question in the messages")
    return inputs, problems


def improvement(scores: dict, inputs: dict) -> dict | None:
    """Final-vs-draft: both texts judged with the SAME final-answer metric; None when either score is missing."""
    d, f = scores.get("draft_under_final_metric", {}), scores.get("final_helpfulness", {})
    if d.get("status") != "ok" or f.get("status") != "ok":
        return None
    diff, identical = round(f["score"] - d["score"], 2), (inputs["final"] or "").strip() == (inputs["draft"] or "").strip()
    if identical:
        note = "The final answer text is identical to the draft: the Reviewer only approved and forwarded it, so no improvement is possible by construction."
    elif diff > CHANGE_THRESHOLD:
        note = "The final answer scored higher than the draft."
    elif diff < -CHANGE_THRESHOLD:
        note = "The final answer scored LOWER than the draft."
    else:
        note = "No meaningful difference between draft and final answer."
    return {"draft_score": d["score"], "final_score": f["score"], "difference": diff, "identical_text": identical, "interpretation": note}


def skipped(reason: str) -> dict:
    return {"status": "skipped", "score": None, "reason": None, "error": reason}


def score_all(judge, inputs: dict, deadline: float, max_errors: int) -> tuple[dict, list]:
    """Run the four judge calls with a time budget and an error budget. Returns (scores, errors)."""
    scores, errors, consecutive, aborted = {}, [], 0, None
    for name, metric, key in PLAN:
        text = inputs.get(key)
        if aborted or time.time() >= deadline or not text:
            reason = aborted or ("time budget exhausted" if text else f"no {key} text to judge")
            scores[name] = skipped(reason)
            continue
        try:
            res = judge.score(metric, inputs["question"], text, inputs["context"] if key != "plan" else None)
            scores[name] = {"status": "ok", "score": res.score, "reason": res.reason, "raw": res.raw, "metric": metric, "judged": key}
            consecutive = 0
        except JudgeUnavailable as exc:
            aborted = f"judge unavailable: {exc}"
            scores[name] = {"status": "error", "score": None, "reason": None, "error": str(exc)}
            errors.append(str(exc))
        except Exception as exc:
            consecutive += 1
            scores[name] = {"status": "error", "score": None, "reason": None, "error": f"{type(exc).__name__}: {exc}"}
            errors.append(scores[name]["error"])
            if consecutive >= max_errors:
                aborted = "too many consecutive judge errors"
    return scores, errors


def evaluate_trace(trace_id: str, msgs: dict, judge, deadline_s: float = 300.0, max_errors: int = 2) -> dict:
    """Evaluate one request. Always returns a record (with errors listed) and writes an `evaluation` span."""
    start = time.time()
    inputs, problems = extract_inputs(msgs)
    scores, errors = score_all(judge, inputs, start + deadline_s, max_errors)
    ok = sum(1 for s in scores.values() if s["status"] == "ok")
    status = "ok" if ok == len(PLAN) and not problems else ("partial" if ok else "error")
    end = time.time()
    record_span(trace_id, "evaluation", start, end, "ok" if status == "ok" else "error", "; ".join(problems + errors) or None, evaluation_status=status,
                judge_model=settings()["judge_model"])
    return {"trace_id": trace_id, "status": status, "problems": problems, "errors": errors, "inputs": inputs, "scores": scores,
            "improvement": improvement(scores, inputs), "messages": msgs, "judge": settings(),
            "started_at": start, "duration_s": round(end - start, 3)}