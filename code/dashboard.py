from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import dashboard_data as dd

st.set_page_config(page_title="HW10 Operations Dashboard - Alyssa Gomez", layout="wide")
st.markdown("""<style>
[data-testid="stMetric"] {background: #ffffff; border: 1px solid #a5d0f3; border-left: 6px solid #1c7ed6; border-radius: 10px; padding: 12px 14px;}
[data-testid="stMetric"] * {color: #0b2545 !important;}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {background: #d9ecfb !important;}
.stApp, .stApp p, .stApp li, .stApp label, .stApp span, .stApp [data-testid="stCaptionContainer"] {color: #0b2545;}
h1, h2, h3 {color: #0b4f9c !important;}
[data-testid="stTable"] table {background: #ffffff; color: #0b2545; border: 1px solid #a5d0f3;}
[data-testid="stTable"] th {background: #bfdcf5 !important; color: #0b2545 !important;}
[data-testid="stTable"] td {background: #ffffff !important; color: #0b2545 !important;}
[data-testid="stAlert"] * {color: #0b2545 !important;}
[data-testid="stSidebar"] {background: #bfdcf5 !important;}
[data-testid="stSidebar"] {border-right: 2px solid #a5d0f3;}
</style>""", unsafe_allow_html=True)
BLUES = ["#1c7ed6", "#74b9ef", "#0b4f9c"]


def show_table(df: pd.DataFrame) -> None:
    """White HTML table (readable in any Streamlit theme)."""
    st.table(df.style.hide(axis="index"))


def show_chart(chart) -> None:
    """Altair chart on a white background with dark axis text."""
    st.altair_chart(chart.configure(background="#ffffff").configure_axis(labelColor="#0b2545", titleColor="#0b2545").configure_legend(labelColor="#0b2545", titleColor="#0b2545"), theme=None)


def mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_data(show_spinner=False)
def cached_spans(path: str, modified: float) -> list:
    """Parsed span file; re-read only when the file changes."""
    return dd.read_spans(Path(path))


@st.cache_data(show_spinner=False)
def cached_json(path: str, modified: float):
    return dd.load_json(Path(path))


@st.cache_data(show_spinner=False)
def cached_csv(path: str, modified: float) -> list:
    return dd.load_csv(Path(path))


@st.cache_resource(show_spinner=False)
def span_index(path: str, modified: float) -> dict:
    """trace_id -> its spans (built once per file version, shared by all sessions)."""
    index = {}
    for span in cached_spans(path, modified):
        index.setdefault(span["trace_id"], []).append(span)
    return index


def spans_now() -> tuple:
    path = dd.sources()["spans"]
    return str(path), mtime(path)


def show_stat(label: str, value, note: str) -> None:
    st.metric(label, "n/a" if value is None else value)
    st.caption(note)


def page_summary() -> None:
    st.header("Summary")
    window = st.sidebar.selectbox("Time window", list(dd.WINDOWS))
    path, modified = spans_now()
    s = dd.summary(cached_spans(path, modified), dd.WINDOWS[window])
    span_range = f"{s['first_request']} to {s['last_request']} UTC" if s["requests"] else "no requests in this window"
    where = f"Window: {window} ({span_range}). Source: `{Path(path).name}` `request` spans (own tracing, Part 4)."
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        show_stat("Requests", s["requests"], where)
    with c2:
        show_stat("Semantic-cache hit rate", None if s["hit_rate_pct"] is None else f"{s['hit_rate_pct']}%",
                  f"{s['hits']} hits vs {s['misses']} misses. Window: {window}. Source: `cache_lookup` spans (`path` attribute: cache_hit / cache_miss).")
    with c3:
        show_stat("Error rate", None if s["error_rate_pct"] is None else f"{s['error_rate_pct']}%",
                  f"{s['errors']} of {s['requests']} requests ended in an error. Window: {window}. Source: `request` span status.")
    with c4:
        miss = s["latency_cache_miss"]
        show_stat("End-to-end latency, cache miss (p50)", None if miss["p50_ms"] is None else f"{miss['p50_ms']} ms",
                  f"p95 {miss['p95_ms']} ms over {miss['n']} successful miss requests. Window: {window}. Source: `request` span duration.")
    left, right = st.columns(2)
    with left:
        st.subheader("Cache Hits vs Cache Misses")
        show_chart(alt.Chart(pd.DataFrame({"path": ["cache hit", "cache miss"], "requests": [s["hits"], s["misses"]]})).mark_bar(color="#1c7ed6").encode(x=alt.X("path:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("requests:Q", title="requests"), tooltip=["path", "requests"]).properties(height=260))
    with right:
        st.subheader("Latency by Path (Cache Hit Kept Separate)")
        rows = [{"path": "cache hit", **s["latency_cache_hit"]}, {"path": "cache miss", **s["latency_cache_miss"]}, {"path": "all successful", **s["latency_all"]}]
        show_table(pd.DataFrame(rows))
        st.caption(f"Source: `request` span durations, successful requests only. Window: {window}.")
    if s["errors_by_stage"]:
        st.subheader("Errors by Stage")
        show_table(pd.DataFrame([{"stage": k, "errors": v} for k, v in s["errors_by_stage"].items()]))
    latency = cached_json(str(dd.sources()["latency"]), mtime(dd.sources()["latency"]))
    st.subheader("Stage latency, 50 Cache-Miss Requests (Part 4.3)")
    if latency:
        show_table(pd.DataFrame(latency["table"]))
        st.caption(f"Source: `latency_run.json` (saved {dd.file_age(dd.sources()['latency'])}), {latency['requests']} cache-miss requests, warm-up excluded. "
                   f"Dominant: {latency['dominant_stage']['stage']}. Cache-hit latency (separate): {latency['cache_hit_latency']}")
    else:
        st.info("Run `python run_latency.py` to fill this table.")


def page_evaluation() -> None:
    st.header("Evaluation")
    src = dd.sources()
    records = cached_json(str(src["evaluation"]), mtime(src["evaluation"]))
    validation = cached_json(str(src["validation"]), mtime(src["validation"]))
    rows = dd.eval_rows(records)
    st.subheader("Part 2 - Planner / Writer / Reviewer scores by case")
    st.caption(f"Source: `evaluation_results.json` (saved {dd.file_age(src['evaluation'])}); judge: local model via DeepEval GEval, scale 1-5.")
    if not rows:
        st.info("Run `python run_evaluation.py` first.")
    else:
        table = pd.DataFrame(rows)
        show_table(table[["case", "question", "planner_plan_quality", "writer_helpfulness", "final_answer_helpfulness", "draft_score", "final_score", "difference", "identical_text", "trace_id"]])
        long = pd.DataFrame([{"case": f"case {r['case']}", "stage": stage, "score": r[key]} for r in rows
                             for stage, key in (("Planner", "planner_plan_quality"), ("Writer", "writer_helpfulness"), ("Final answer", "final_answer_helpfulness"))])
        show_chart(alt.Chart(long).mark_bar().encode(x=alt.X("stage:N", title=None), y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 5])), color=alt.Color("stage:N", scale=alt.Scale(range=BLUES), legend=None),
                                                          column=alt.Column("case:N", title=None)).properties(width=70, height=200))
        means = dd.stage_means(rows)
        show_table(pd.DataFrame([{"stage": k, "mean score": v} for k, v in means.items()]))
        st.subheader("Final-vs-draft improvement")
        show_table(table[["case", "draft_score", "final_score", "difference", "interpretation"]])
        for rec, row in zip(records, rows):
            with st.expander(f"Case {row['case']}: {row['question']}"):
                st.write("**Plan**")
                st.text(rec["inputs"]["plan"])
                st.write("**Draft**")
                st.write(rec["inputs"]["draft"])
                st.write("**Final answer**")
                st.write(rec["inputs"]["final"])
                for name, item in rec["scores"].items():
                    st.caption(f"{name}: {item.get('score')} - {item.get('reason') or item.get('error')}")
    st.subheader("Part 3 - Judge validation against my human labels")
    cases = cached_csv(str(src["validation_cases"]), mtime(src["validation_cases"]))
    if not validation:
        st.info("Run `python run_judge_validation.py` first.")
    else:
        a, r = validation["stats"]["agreement_run1"], validation["stats"]["repeatability"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Spearman correlation", a["spearman_rho"])
        c2.metric("Mean absolute difference", a["mean_abs_difference"])
        c3.metric("Cases whose score changed", f"{r['cases_with_any_change']} / {validation['stats']['n_cases']}")
        c4.metric("Mean / max change", f"{r['mean_abs_change']} / {r['max_abs_change']}")
        st.caption(f"Source: `judge_validation.json` and `judge_validation_cases.csv` (saved {dd.file_age(src['validation'])}); {r['runs']} runs on the same 20 drafts, same settings.")
        if cases:
            df = pd.DataFrame(cases)
            for col in ("human_label", "judge_run1", "judge_run2", "judge_run3"):
                df[col] = pd.to_numeric(df[col])
            points = alt.Chart(df).mark_circle(size=90, opacity=0.6).encode(x=alt.X("human_label:Q", scale=alt.Scale(domain=[0.5, 5.5]), title="human label"),
                                                                          y=alt.Y("judge_run1:Q", scale=alt.Scale(domain=[0.5, 5.5]), title="judge score (run 1)"), tooltip=["case_id", "variant"])
            diagonal = alt.Chart(pd.DataFrame({"x": [1, 5], "y": [1, 5]})).mark_line(strokeDash=[4, 4]).encode(x="x:Q", y="y:Q")
            show_chart(points + diagonal)
            show_table(df.drop(columns=["reason_run1"]))
    st.subheader("Interpretation")
    for line in dd.interpretation(rows, validation):
        st.write("- " + line)


def page_trace() -> None:
    st.header("Trace lookup")
    path, modified = spans_now()
    index, spans = span_index(path, modified), cached_spans(path, modified)
    examples = dd.example_traces()
    pick = st.selectbox("Required examples", ["(none)"] + list(examples))
    trace_id = st.text_input("trace_id", value=examples.get(pick, "")).strip()
    with st.expander("Recent traces"):
        show_table(pd.DataFrame(dd.recent_traces(spans)))
    if not trace_id:
        st.info("Enter a trace_id (the HW8 correlation_id) or pick one of the three required examples.")
        return
    view = dd.trace_view(index.get(trace_id, []))
    if not view["rows"]:
        st.warning(f"No spans found for trace_id {trace_id}")
        return
    if view["path"] == "cache_hit":
        st.success(f"CACHE HIT path: answered from the semantic cache in {view['total_ms']} ms. Stages not run: {', '.join(dd.HIT_SKIPPED)}.")
    elif view["path"] == "cache_miss":
        st.info(f"CACHE MISS path: full agent path through Kafka. Total request time {view['total_ms']} ms.")
    if view["failing"]:
        st.error(f"FAILED at stage `{view['failing']['stage']}`: {view['failing']['error']}")
    df = pd.DataFrame(view["rows"])
    df.insert(0, "path", view["path"])
    show_table(df[["stage", "start", "end", "duration_ms", "status", "error", "path"]])
    st.caption("Times are UTC. Source: spans for this trace_id in the span file, in stage order.")
    order = list(df["stage"])
    show_chart(alt.Chart(df).mark_bar().encode(x=alt.X("offset_start_ms:Q", title="ms from request start"), x2="offset_end_ms:Q",
                                                    y=alt.Y("stage:N", sort=order), color=alt.Color("status:N", scale=alt.Scale(domain=["ok", "error"], range=["#1c7ed6", "#d62828"])),
                                                    tooltip=["stage", "duration_ms", "status", "error"]).properties(height=260))


st.sidebar.markdown("**Alyssa Gomez** - SID 8110 - PREFIX `s8110`")
st.sidebar.caption("HW10 operations dashboard: summary, evaluation, trace lookup")
choice = st.sidebar.radio("Page", ["Summary", "Evaluation", "Trace lookup"])
st.title("HW10 Operations Dashboard - Alyssa Gomez")
{"Summary": page_summary, "Evaluation": page_evaluation, "Trace lookup": page_trace}[choice]()