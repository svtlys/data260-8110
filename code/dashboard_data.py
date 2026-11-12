import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from run_latency import percentile
from tracing import STAGES, read_spans, span_path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "reports" / "hw10" / "raw"
WINDOWS = {"All data in the span file": None, "Last 1 hour": 3600, "Last 24 hours": 86400, "Last 7 days": 7 * 86400}
HIT_SKIPPED = ["queue_inbox", "planner", "queue_tasks", "writer", "queue_drafts", "reviewer", "queue_final", "evaluation"]


def load_json(path: Path):
    """Parsed JSON file, or None when it does not exist yet."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_csv(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def hhmmss(iso: str) -> str:
    return iso[11:23]


def trace_paths(spans: list) -> dict:
    """trace_id -> 'cache_hit' / 'cache_miss', taken from its cache_lookup span."""
    return {s["trace_id"]: s.get("attrs", {}).get("path", "unknown") for s in spans if s["stage"] == "cache_lookup"}


def latency_stats(values: list) -> dict:
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "mean_ms": None}
    return {"n": len(values), "p50_ms": round(percentile(values, 50), 1), "p95_ms": round(percentile(values, 95), 1), "mean_ms": round(sum(values) / len(values), 1)}


def summary(spans: list, window_s: float | None, now: float | None = None) -> dict:
    """Part 1.1 numbers over the `request` spans inside the time window (start of the request counts)."""
    now = time.time() if now is None else now
    paths = trace_paths(spans)
    reqs = [s for s in spans if s["stage"] == "request" and (window_s is None or s["start_ts"] >= now - window_s)]
    ids = {r["trace_id"] for r in reqs}
    hits = [r for r in reqs if paths.get(r["trace_id"]) == "cache_hit"]
    misses = [r for r in reqs if paths.get(r["trace_id"]) == "cache_miss"]
    errors = [r for r in reqs if r["status"] == "error"]
    by_stage = {}
    for s in spans:
        if s["status"] == "error" and s["stage"] != "request" and s["trace_id"] in ids:
            by_stage[s["stage"]] = by_stage.get(s["stage"], 0) + 1
    ok = lambda rs: [r["duration_ms"] for r in rs if r["status"] == "ok"]  # noqa: E731
    cacheable = len(hits) + len(misses)
    return {"requests": len(reqs), "hits": len(hits), "misses": len(misses), "unknown_path": len(reqs) - cacheable,
            "hit_rate_pct": round(100.0 * len(hits) / cacheable, 1) if cacheable else None,
            "errors": len(errors), "error_rate_pct": round(100.0 * len(errors) / len(reqs), 1) if reqs else None, "errors_by_stage": by_stage,
            "latency_cache_hit": latency_stats(ok(hits)), "latency_cache_miss": latency_stats(ok(misses)), "latency_all": latency_stats(ok(reqs)),
            "first_request": min((r["start"] for r in reqs), default=None), "last_request": max((r["start"] for r in reqs), default=None)}


def eval_rows(records: list | None) -> list:
    """One row per evaluated request (Part 2): scores by pipeline stage and the final-vs-draft improvement."""
    rows = []
    for i, rec in enumerate(records or [], 1):
        sc, imp = rec["scores"], rec.get("improvement") or {}
        rows.append({"case": i, "trace_id": rec["trace_id"], "question": rec.get("question") or rec["inputs"]["question"], "status": rec["status"],
                     "planner_plan_quality": sc["plan_quality"]["score"], "writer_helpfulness": sc["writer_helpfulness"]["score"],
                     "final_answer_helpfulness": sc["final_helpfulness"]["score"], "draft_score": imp.get("draft_score"), "final_score": imp.get("final_score"),
                     "difference": imp.get("difference"), "identical_text": imp.get("identical_text"), "interpretation": imp.get("interpretation"),
                     "evaluation_seconds": rec.get("duration_s")})
    return rows


def stage_means(rows: list) -> dict:
    """Mean score per pipeline stage (Planner / Writer / Reviewer-final) over the evaluated cases."""
    def mean(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None
    return {"Planner (plan quality)": mean("planner_plan_quality"), "Writer (helpfulness)": mean("writer_helpfulness"),
            "Reviewer / final answer (helpfulness)": mean("final_answer_helpfulness")}


def interpretation(rows: list, validation: dict | None) -> list:
    """Short reading of the Part 2 scores, built from the loaded numbers."""
    if not rows:
        return ["No evaluation results yet - run run_evaluation.py."]
    n, ident = len(rows), sum(1 for r in rows if r["identical_text"])
    diffs = [r["difference"] for r in rows if r["difference"] is not None]
    means = stage_means(rows)
    out = [f"{n} requests evaluated. Mean scores: " + "; ".join(f"{k} {v}" for k, v in means.items()) + "."]
    if diffs and all(d == 0 for d in diffs):
        out.append(f"The final answer did NOT improve on the draft in any case (difference 0.0 for all {len(diffs)}); the final text was identical to the draft in {ident} of {n} cases.")
    elif diffs:
        out.append(f"Final minus draft: mean {round(sum(diffs) / len(diffs), 2)}, min {min(diffs)}, max {max(diffs)}; the final text equals the draft in {ident} of {n} cases.")
    if ident:
        out.append("Why: the Reviewer only checks length and cleanliness and forwards the draft unchanged, so it acts as a gate and adds no quality; the chain cannot beat the Writer alone.")
    out.append("Coordination: each stage passed correct information to the next (the Writer followed the plan; listing answers used the database facts); the weak point is that no stage revises the answer.")
    if validation:
        a = validation["stats"]["agreement_run1"]
        out.append(f"Caution: the judge agreed poorly with my human labels (Spearman {a['spearman_rho']}, mean absolute difference {a['mean_abs_difference']}, bias {a['mean_signed_difference_judge_minus_human']:+}), so these scores are weak evidence.")
    return out


def trace_view(spans: list) -> dict:
    """Rows for the trace page, in stage order, with offsets from the trace start (for the timeline chart)."""
    ordered = sorted(spans, key=lambda s: (s["start_ts"], STAGES.index(s["stage"]) if s["stage"] in STAGES else len(STAGES)))
    if not ordered:
        return {"rows": [], "path": None, "failing": None, "total_ms": None}
    t0 = min(s["start_ts"] for s in ordered)
    rows = [{"stage": s["stage"], "start": hhmmss(s["start"]), "end": hhmmss(s["end"]), "duration_ms": s["duration_ms"], "status": s["status"],
             "error": s.get("error", ""), "offset_start_ms": round((s["start_ts"] - t0) * 1000, 1), "offset_end_ms": round((s["end_ts"] - t0) * 1000, 1),
             "details": json.dumps(s.get("attrs", {}))} for s in ordered]
    bad = [r for r in rows if r["status"] == "error" and r["stage"] != "request"]
    path = next((s.get("attrs", {}).get("path") for s in ordered if s["stage"] == "cache_lookup"), None)
    request = next((s for s in ordered if s["stage"] == "request"), None)
    return {"rows": rows, "path": path, "failing": bad[0] if bad else None, "total_ms": request["duration_ms"] if request else None}


def recent_traces(spans: list, limit: int = 15) -> list:
    """Most recent traces (by request span): trace_id, path, status, duration."""
    paths = trace_paths(spans)
    reqs = sorted((s for s in spans if s["stage"] == "request"), key=lambda s: s["start_ts"], reverse=True)[:limit]
    return [{"trace_id": r["trace_id"], "path": paths.get(r["trace_id"], "unknown"), "status": r["status"], "duration_ms": r["duration_ms"], "start": hhmmss(r["start"])} for r in reqs]


def example_traces() -> dict:
    """The three required traces (cache hit / cache miss / failed) saved by run_trace_examples.py: label -> trace_id."""
    data = load_json(RAW / "trace_examples.json") or {}
    labels = {"cache_hit": "Cache HIT example", "cache_miss": "Cache MISS example (full agent path)", "failed": "FAILED example"}
    return {labels[k]: v["trace_id"] for k, v in data.items() if k in labels}


def file_age(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if path.exists() else "missing"


def sources() -> dict:
    """Data sources shown on the pages."""
    return {"spans": span_path(), "evaluation": RAW / "evaluation_results.json", "validation": RAW / "judge_validation.json",
            "validation_cases": RAW / "judge_validation_cases.csv", "latency": RAW / "latency_run.json"}


def all_spans() -> list:
    return read_spans(span_path())