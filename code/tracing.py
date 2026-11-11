import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("tracing")
_LOCK = threading.Lock()

# Order in which a request passes the stages (used to sort spans that start at the same instant).
STAGES = ("request", "cache_lookup", "queue_inbox", "planner", "queue_tasks", "writer", "queue_drafts", "reviewer", "queue_final", "evaluation")
QUEUE_STAGES = tuple(s for s in STAGES if s.startswith("queue_"))


def span_path() -> Path:
    """Span file; TRACE_FILE overrides it (tests)."""
    return Path(os.environ.get("TRACE_FILE") or ROOT / "reports" / "hw10" / "traces" / "spans.jsonl")


def iso(ts: float) -> str:
    """Epoch seconds -> ISO-8601 UTC with milliseconds."""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def record_span(trace_id, stage: str, start_ts: float, end_ts: float, status: str = "ok", error=None, **attrs) -> dict:
    """Append one span; returns it ({} when there is no trace_id). Several processes may append to the same file."""
    if not trace_id:
        return {}
    rec = {"trace_id": trace_id, "stage": stage, "start": iso(start_ts), "end": iso(end_ts), "start_ts": round(start_ts, 6),
           "end_ts": round(end_ts, 6), "duration_ms": round((end_ts - start_ts) * 1000.0, 2), "status": status}
    if error:
        rec["error"] = str(error)
    attrs = {k: v for k, v in attrs.items() if v is not None}
    if attrs:
        rec["attrs"] = attrs
    try:
        path = span_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.warning("could not write span for %s/%s: %s", trace_id, stage, exc)
    return rec


@contextmanager
def span(trace_id, stage: str, **attrs):
    """Time a block; an exception inside it is recorded as status=error and re-raised."""
    start = time.time()
    try:
        yield
    except Exception as exc:
        record_span(trace_id, stage, start, time.time(), "error", f"{type(exc).__name__}: {exc}", **attrs)
        raise
    record_span(trace_id, stage, start, time.time(), **attrs)


def read_spans(path: Path | None = None) -> list[dict]:
    """All spans in the file (bad lines are skipped)."""
    path = path or span_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _order(sp: dict) -> tuple:
    return sp["start_ts"], STAGES.index(sp["stage"]) if sp["stage"] in STAGES else len(STAGES)


def spans_for(trace_id: str, path: Path | None = None) -> list[dict]:
    """Spans of one trace in stage order."""
    return sorted((s for s in read_spans(path) if s["trace_id"] == trace_id), key=_order)


def failing_stage(spans: list[dict]) -> dict | None:
    """The first stage (by start time) whose status is error, ignoring the overall 'request' span."""
    errors = [s for s in spans if s["status"] == "error" and s["stage"] != "request"]
    return min(errors, key=_order) if errors else None


def trace_path(spans: list[dict]) -> str:
    """'cache_hit' / 'cache_miss' (from the cache_lookup span) or 'unknown'."""
    for s in spans:
        if s["stage"] == "cache_lookup":
            return s.get("attrs", {}).get("path", "unknown")
    return "unknown"


def format_trace(spans: list[dict]) -> str:
    """Plain-text table of one trace (used by the scripts and the screenshots)."""
    lines = [f"{'stage':<13} {'start (UTC)':<13} {'end (UTC)':<13} {'duration':>11}  status  error"]
    for s in spans:
        lines.append(f"{s['stage']:<13} {s['start'][11:23]:<13} {s['end'][11:23]:<13} {s['duration_ms']:>8.1f} ms  {s['status']:<6}  {s.get('error', '')}")
    return "\n".join(lines)