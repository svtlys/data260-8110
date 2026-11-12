import latency_questions as lq
import run_latency as rl
from tracing import QUEUE_STAGES


def span(trace, stage, dur, start=0.0):
    return {"trace_id": trace, "stage": stage, "duration_ms": dur, "start_ts": start, "status": "ok"}


def full_trace(trace, planner=1000.0, writer=500.0):
    spans = [span(trace, "cache_lookup", 100.0), span(trace, "planner", planner), span(trace, "writer", writer), span(trace, "reviewer", 1.0), span(trace, "evaluation", 800.0)]
    spans += [span(trace, q, 50.0) for q in QUEUE_STAGES]
    return spans + [span(trace, "request", 100.0 + planner + writer + 1.0 + 200.0 + 30.0)]


def test_percentile_matches_the_linear_definition():
    assert rl.percentile([1, 2, 3, 4], 50) == 2.5 and rl.percentile([10], 95) == 10 and rl.percentile(list(range(1, 101)), 95) == 95.05


def test_stage_durations_sum_the_four_queue_hops_and_add_evaluation_to_end_to_end():
    row = rl.stage_durations("t", full_trace("t"))
    assert row["queue_total"] == 200.0 and row["end_to_end"] == row["request"] + 800.0 and row["planner"] == 1000.0


def test_missing_queue_span_makes_the_total_unknown_rather_than_wrong():
    spans = [s for s in full_trace("t") if s["stage"] != "queue_tasks"]
    assert rl.stage_durations("t", spans)["queue_total"] is None


def test_table_shares_sum_to_100_with_unattributed_and_find_the_dominant_stage():
    spans = []
    for i in range(20):
        spans += full_trace(f"t{i}", planner=1000.0 + i * 10)
    rows = [rl.stage_durations(f"t{i}", spans) for i in range(20)]
    table = rl.build_table(rows)
    shares = [r["pct_of_end_to_end"] for r in table if r["stage"] != "End-to-end (cache miss)"]
    assert abs(sum(shares) - 100.0) < 0.2
    assert rl.dominant(table)["stage"] == "Planner" and "| Planner |" in rl.table_markdown(table)
    assert table[-1]["stage"] == "End-to-end (cache miss)" and table[-1]["p95_ms"] >= table[-1]["p50_ms"]


def test_question_lists_are_big_enough_and_unique():
    allq = lq.QUESTIONS + lq.SPARES + [lq.WARMUP]
    assert len(lq.QUESTIONS) == 50 and len(lq.SPARES) == 10 and len(set(allq)) == len(allq)
    assert not any("S8110-" in q for q in allq)


def test_hit_stats_use_the_request_span():
    assert rl.hit_stats([{"request": 300.0}, {"request": 100.0}])["p50_ms"] == 200.0