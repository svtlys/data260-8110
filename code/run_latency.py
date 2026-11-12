import csv
import json
import logging
import sys
from pathlib import Path

from cache_config import SID4, setup_logging
from latency_questions import QUESTIONS, SPARES, WARMUP
from tracing import QUEUE_STAGES, read_spans

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw10" / "raw"
PROGRESS, RUN_JSON, REQ_CSV, TABLE_MD = RAW / "latency_progress.json", RAW / "latency_run.json", RAW / "latency_requests.csv", RAW / "latency_table.md"
TARGET, HITS = 50, 10
STAGE_ROWS = (("Cache lookup", "cache_lookup"), ("Planner", "planner"), ("Writer", "writer"), ("Reviewer", "reviewer"),
              ("Queue wait (total)", "queue_total"), ("Evaluation", "evaluation"))


def percentile(values: list, q: float) -> float:
    """Linear-interpolation percentile (q in 0-100), same as numpy's default."""
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def stage_durations(trace_id: str, spans: list) -> dict:
    """Per-request stage durations in ms from the spans of one trace (None for a missing stage)."""
    mine = [s for s in spans if s["trace_id"] == trace_id]

    def dur(stage):
        found = [s["duration_ms"] for s in mine if s["stage"] == stage]
        return sum(found) if found else None

    queues = [dur(q) for q in QUEUE_STAGES]
    row = {"trace_id": trace_id, "cache_lookup": dur("cache_lookup"), "planner": dur("planner"), "writer": dur("writer"), "reviewer": dur("reviewer"),
           "queue_total": sum(q for q in queues if q is not None) if all(q is not None for q in queues) else None,
           "evaluation": dur("evaluation"), "request": dur("request")}
    row["end_to_end"] = None if row["request"] is None else row["request"] + (row["evaluation"] or 0.0)
    return row


def build_table(rows: list) -> list:
    """Table rows: stage, p50, p95, share of end-to-end (sum of the stage / sum of end-to-end over the requests that have it)."""
    out = []
    total_e2e = sum(r["end_to_end"] for r in rows if r["end_to_end"] is not None)
    attributed = 0.0
    for label, key in STAGE_ROWS:
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            out.append({"stage": label, "p50_ms": None, "p95_ms": None, "pct_of_end_to_end": None, "n": 0})
            continue
        attributed += sum(vals)
        out.append({"stage": label, "p50_ms": round(percentile(vals, 50), 1), "p95_ms": round(percentile(vals, 95), 1),
                    "pct_of_end_to_end": round(100.0 * sum(vals) / total_e2e, 1), "n": len(vals)})
    e2e = [r["end_to_end"] for r in rows if r["end_to_end"] is not None]
    out.append({"stage": "Unattributed (client, database lookup, cache write)", "p50_ms": None, "p95_ms": None,
                "pct_of_end_to_end": round(100.0 * (total_e2e - attributed) / total_e2e, 1), "n": len(e2e)})
    out.append({"stage": "End-to-end (cache miss)", "p50_ms": round(percentile(e2e, 50), 1), "p95_ms": round(percentile(e2e, 95), 1),
                "pct_of_end_to_end": 100.0, "n": len(e2e)})
    return out


def table_markdown(table: list) -> str:
    fmt = lambda v: "-" if v is None else v  # noqa: E731
    lines = ["| Stage | p50 (ms) | p95 (ms) | % of cache-miss end-to-end | n |", "|---|---|---|---|---|"]
    lines += [f"| {r['stage']} | {fmt(r['p50_ms'])} | {fmt(r['p95_ms'])} | {fmt(r['pct_of_end_to_end'])} | {r['n']} |" for r in table]
    return "\n".join(lines)


def dominant(table: list) -> dict:
    """The stage row with the largest share of end-to-end latency (the queue total counts as one stage)."""
    return max((r for r in table if r["stage"] in {s for s, _ in STAGE_ROWS} and r["pct_of_end_to_end"] is not None), key=lambda r: r["pct_of_end_to_end"])


def hit_stats(rows: list) -> dict:
    vals = [r["request"] for r in rows if r["request"] is not None]
    return {"n": len(vals), "p50_ms": round(percentile(vals, 50), 1), "p95_ms": round(percentile(vals, 95), 1)} if vals else {"n": 0}


def load_progress() -> dict:
    return json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else {"miss": [], "excluded": [], "failed": [], "hit": [], "warmup": None}


def save_progress(state: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_requests(state: dict, skip_eval: bool) -> None:
    """Send the requests that are still missing (miss requests until TARGET are confirmed, then the cache-hit requests)."""
    from judge import DeepEvalJudge
    from pipeline_eval import evaluate_trace, make_collector
    from traced_service import build_service

    service, store, client = build_service(timeout=120.0)
    collector, judge = make_collector(), (None if skip_eval else DeepEvalJudge())

    def evaluate(trace_id):
        if judge is not None:
            evaluate_trace(trace_id, collector.wait(trace_id, 30), judge)

    if state["warmup"] is None:
        result = service.ask(WARMUP)
        evaluate(result.trace_id)
        state["warmup"] = {"trace_id": result.trace_id, "question": WARMUP, "cached": result.is_cached}
        save_progress(state)
    used = {r["question"] for r in state["miss"] + state["excluded"] + state["failed"]}
    pool = [q for q in QUESTIONS + SPARES if q not in used]
    while len(state["miss"]) < TARGET and pool:
        question = pool.pop(0)
        try:
            result = service.ask(question)
        except Exception as exc:
            state["failed"].append({"question": question, "error": f"{type(exc).__name__}: {exc}"})
        else:
            if result.is_cached:
                state["excluded"].append({"question": question, "trace_id": result.trace_id, "reason": "served from the semantic cache"})
            else:
                evaluate(result.trace_id)
                state["miss"].append({"question": question, "trace_id": result.trace_id})
                print(f"miss request {len(state['miss'])}/{TARGET} ok: {question[:60]}", flush=True)
        save_progress(state)
    for item in state["miss"][:HITS]:
        if len(state["hit"]) >= HITS:
            break
        if item["question"] in {h["question"] for h in state["hit"]}:
            continue
        result = service.ask(item["question"])
        state["hit"].append({"question": item["question"], "trace_id": result.trace_id, "cached": result.is_cached})
        save_progress(state)
    collector.close()
    client.close()


def report(state: dict) -> None:
    spans = read_spans()
    rows = [stage_durations(r["trace_id"], spans) for r in state["miss"]]
    complete = [r for r in rows if r["end_to_end"] is not None and r["cache_lookup"] is not None]
    table = build_table(complete)
    hit_rows = [stage_durations(h["trace_id"], spans) for h in state["hit"] if h["cached"]]
    top = dominant(table)
    lookups = {s["trace_id"]: s.get("attrs", {}).get("cache_hit") for s in spans if s["stage"] == "cache_lookup"}
    confirmed = sum(1 for r in state["miss"] if lookups.get(r["trace_id"]) is False)
    out = {"requests": len(state["miss"]), "confirmed_cache_miss_by_span": confirmed, "excluded_cache_hits": state["excluded"], "failed_requests": state["failed"],
           "warmup": state["warmup"], "table": table, "dominant_stage": top, "cache_hit_latency": hit_stats(hit_rows),
           "trace_ids": [r["trace_id"] for r in state["miss"]]}
    RUN_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    TABLE_MD.write_text(table_markdown(table), encoding="utf-8")
    with open(REQ_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["trace_id"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nstudent: Alyssa Gomez  SID4={SID4}")
    print(f"{len(complete)} complete cache-miss requests; {confirmed}/{len(state['miss'])} confirmed as cache misses by their cache_lookup span; "
          f"{len(state['excluded'])} replaced because they hit the cache; {len(state['failed'])} failed")
    print("\n" + table_markdown(table))
    print(f"\ndominant contributor: {top['stage']} ({top['pct_of_end_to_end']}% of end-to-end)")
    print(f"cache-hit latency (separate metric): {out['cache_hit_latency']}")


def main() -> int:
    setup_logging(logging.WARNING)
    state = load_progress()
    if "--report-only" not in sys.argv:
        run_requests(state, "--skip-eval" in sys.argv)
    report(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())