import json
import logging
import sys
from pathlib import Path

from cache_config import SID4, setup_logging
from tracing import failing_stage, format_trace, read_spans, spans_for, trace_path
from traced_service import build_service

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw10" / "raw"
QUESTION = "Who is the landlord for listing S8110-A07?"
BLANK = "   "  # a malformed request: it passes the cache (no match) and fails in the Planner
FAIL_TIMEOUT_S = 25.0


def show(label: str, trace_id: str) -> dict:
    """Print one trace and return its summary for the evidence file."""
    spans = spans_for(trace_id)
    print(f"\n=== {label}: trace_id={trace_id}  path={trace_path(spans)} ===")
    print(format_trace(spans))
    bad = failing_stage(spans)
    if bad:
        print(f"--> failing stage: {bad['stage']}   error: {bad['error']}")
    return {"trace_id": trace_id, "path": trace_path(spans), "failing_stage": bad["stage"] if bad else None,
            "error": bad["error"] if bad else None, "spans": spans}


def main() -> int:
    setup_logging(logging.INFO)
    service, store, client = build_service()
    print(f"student: Alyssa Gomez  SID4={SID4}  cleared {store.clear()} old cache entries")
    out = {}
    miss = service.ask(QUESTION)
    out["cache_miss"] = show("CACHE MISS (full agent path)", miss.trace_id)
    hit = service.ask(QUESTION)
    out["cache_hit"] = show("CACHE HIT", hit.trace_id)
    try:
        service.cache.agent_fn = lambda q, c, trace_id=None: client.ask(q, c, trace_id, timeout=FAIL_TIMEOUT_S)
        service.ask(BLANK)
    except TimeoutError as exc:
        print(f"\nrequest failed as expected: {exc}")
    failed_id = next(s["trace_id"] for s in reversed(read_spans()) if s["stage"] == "request" and s["status"] == "error")
    out["failed"] = show("FAILED REQUEST", failed_id)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "trace_examples.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nsaved reports/hw10/raw/trace_examples.json")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())