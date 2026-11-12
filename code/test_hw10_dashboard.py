import dashboard_data as dd

NOW = 1_000_000.0


def iso(ts):
    return "2026-11-11T10:00:%06.3fZ" % (ts % 60)


def span(trace, stage, start, dur_ms, status="ok", error=None, **attrs):
    s = {"trace_id": trace, "stage": stage, "start": iso(start), "end": iso(start + dur_ms / 1000), "start_ts": start, "end_ts": start + dur_ms / 1000,
         "duration_ms": dur_ms, "status": status, "attrs": attrs}
    if error:
        s["error"] = error
    return s


def make_spans():
    out = []
    out += [span("hit1", "request", NOW - 10, 20), span("hit1", "cache_lookup", NOW - 10, 15, path="cache_hit")]
    for i, d in enumerate((1000, 2000, 3000)):
        t = f"miss{i}"
        out += [span(t, "request", NOW - 100 - i, d), span(t, "cache_lookup", NOW - 100 - i, 10, path="cache_miss"), span(t, "planner", NOW - 99 - i, 300)]
    out += [span("bad", "request", NOW - 50, 500, status="error", error="boom"), span("bad", "cache_lookup", NOW - 50, 10, path="cache_miss"),
            span("bad", "writer", NOW - 49, 400, status="error", error="writer timeout")]
    out += [span("old", "request", NOW - 90000, 700), span("old", "cache_lookup", NOW - 90000, 10, path="cache_miss")]
    return out


def test_summary_all():
    s = dd.summary(make_spans(), None, now=NOW)
    assert s["requests"] == 6 and s["hits"] == 1 and s["misses"] == 5
    assert s["hit_rate_pct"] == round(100 / 6, 1)
    assert s["errors"] == 1 and s["error_rate_pct"] == round(100 / 6, 1)
    assert s["errors_by_stage"] == {"writer": 1}
    assert s["latency_cache_hit"]["n"] == 1 and s["latency_cache_hit"]["p50_ms"] == 20
    assert s["latency_cache_miss"]["n"] == 4  # error request excluded


def test_summary_window_filters_old():
    s = dd.summary(make_spans(), 86400, now=NOW)
    assert s["requests"] == 5 and s["misses"] == 4


def test_summary_empty():
    s = dd.summary([], 3600, now=NOW)
    assert s["requests"] == 0 and s["hit_rate_pct"] is None and s["error_rate_pct"] is None and s["latency_cache_miss"]["p50_ms"] is None


def test_latency_percentiles():
    st = dd.latency_stats([1000, 2000, 3000])
    assert st["p50_ms"] == 2000 and st["p95_ms"] == 2900 and st["mean_ms"] == 2000


def test_trace_view_miss_and_failed():
    spans = [s for s in make_spans() if s["trace_id"] == "bad"]
    v = dd.trace_view(spans)
    assert [r["stage"] for r in v["rows"]] == ["request", "cache_lookup", "writer"]
    assert v["path"] == "cache_miss" and v["failing"]["stage"] == "writer" and v["failing"]["error"] == "writer timeout"
    assert v["rows"][0]["offset_start_ms"] == 0 and v["total_ms"] == 500
    hit = dd.trace_view([s for s in make_spans() if s["trace_id"] == "hit1"])
    assert hit["path"] == "cache_hit" and hit["failing"] is None
    assert dd.trace_view([])["rows"] == []


def test_recent_traces_order():
    r = dd.recent_traces(make_spans(), limit=2)
    assert [x["trace_id"] for x in r] == ["hit1", "bad"] and r[0]["path"] == "cache_hit"


def rec(plan, writer, final, draft, diff, ident):
    return {"trace_id": "t", "question": "q", "inputs": {"question": "q"}, "status": "ok", "duration_s": 20.0,
            "scores": {"plan_quality": {"score": plan}, "writer_helpfulness": {"score": writer}, "final_helpfulness": {"score": final}},
            "improvement": {"draft_score": draft, "final_score": final, "difference": diff, "identical_text": ident, "interpretation": "x"}}


def test_eval_rows_means_interpretation():
    rows = dd.eval_rows([rec(5, 5, 5, 5, 0.0, True), rec(4, 5, 5, 5, 0.0, True)])
    assert len(rows) == 2 and rows[1]["planner_plan_quality"] == 4
    m = dd.stage_means(rows)
    assert m["Planner (plan quality)"] == 4.5
    text = " ".join(dd.interpretation(rows, {"stats": {"agreement_run1": {"spearman_rho": -0.14, "mean_abs_difference": 1.1, "mean_signed_difference_judge_minus_human": 0.86}}}))
    assert "did NOT improve" in text and "-0.14" in text
    assert dd.eval_rows(None) == [] and "run_evaluation" in dd.interpretation([], None)[0]