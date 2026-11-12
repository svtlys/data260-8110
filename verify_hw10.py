import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODE, DATA, RAW = ROOT / "code", ROOT / "data" / "hw10", ROOT / "reports" / "hw10" / "raw"
SPANS = ROOT / "reports" / "hw10" / "traces" / "spans.jsonl"
sys.path.insert(0, str(CODE))

from cache_config import DOMAIN_ID, PORT_BASE, PREFIX, SEED, SID4, VERIFY_SEED  # noqa: E402
from tracing import STAGES  # noqa: E402

RESULTS: list = []
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TABLE_STAGES = ["Cache lookup", "Planner", "Writer", "Reviewer", "Queue wait (total)", "Evaluation"]


class Skip(Exception):
    """Raised by a check that cannot run in this environment."""


def code_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(CODE.glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def check(name: str, fn) -> None:
    started = time.time()
    try:
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
    except Skip as exc:
        status, detail = "SKIP", str(exc)
    except Exception as exc:  # a crashing check is a failed check
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"name": name, "status": status, "detail": detail, "seconds": round(time.time() - started, 1)})
    print(f"{status:<5} {name} - {detail}", flush=True)


def jload(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"missing {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_spans() -> list:
    if not SPANS.exists():
        raise FileNotFoundError(f"missing {SPANS.relative_to(ROOT)}")
    return [json.loads(line) for line in SPANS.read_text(encoding="utf-8").splitlines() if line.strip()]


def first_commit_time(pattern: str):
    log = subprocess.run(["git", "log", "--format=%ct", "--", f":(glob){pattern}"], cwd=ROOT, capture_output=True, text=True)
    if log.returncode != 0:
        raise Skip("git not available")
    stamps = [int(x) for x in log.stdout.split()]
    return min(stamps) if stamps else None


# ---------------- Section 0 / unit tests ----------------
def c_section0():
    want = {"SID4": "8110", "PORT_BASE": 8010, "PREFIX": "s8110", "SEED": 8110, "VERIFY_SEED": 268110, "DOMAIN_ID": 6}
    got = {"SID4": SID4, "PORT_BASE": PORT_BASE, "PREFIX": PREFIX, "SEED": SEED, "VERIFY_SEED": VERIFY_SEED, "DOMAIN_ID": DOMAIN_ID}
    return got == want, f"{got}"


def c_unit_tests():
    files = ["test_hw10_tracing.py", "test_hw10_eval.py", "test_hw10_judgeval.py", "test_hw10_latency.py", "test_hw10_dashboard.py"]
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=CODE, capture_output=True, text=True, timeout=600)
    lines = (proc.stdout.strip() or proc.stderr.strip()).splitlines()
    return proc.returncode == 0, f"offline tests (tracing, evaluator, judge validation, latency, dashboard): {lines[-1] if lines else 'no output'}"


# ---------------- Part 4: spans ----------------
def c_span_format():
    spans = read_spans()
    need = {"trace_id", "stage", "start", "end", "start_ts", "end_ts", "duration_ms", "status"}  # attrs is only written when a span has extra attributes
    bad = [s for s in spans if not need <= set(s) or s["stage"] not in STAGES or s["status"] not in ("ok", "error")
           or (s["status"] == "error") != bool(s.get("error")) or abs((s["end_ts"] - s["start_ts"]) * 1000 - s["duration_ms"]) > 1.5]
    stages = sorted({s["stage"] for s in spans})
    ok = bool(spans) and not bad and {"request", "cache_lookup", "planner", "writer", "reviewer", "evaluation"} <= set(stages)
    return ok, f"{len(spans)} spans, {len({s['trace_id'] for s in spans})} traces, stages {stages}, malformed spans: {len(bad)}"


def c_three_traces():
    data, spans = jload(RAW / "trace_examples.json"), read_spans()
    by_trace: dict = {}
    for s in spans:
        by_trace.setdefault(s["trace_id"], []).append(s)

    def stages(key):
        return {s["stage"] for s in by_trace.get(data[key]["trace_id"], [])}

    hit, miss, failed = stages("cache_hit"), stages("cache_miss"), stages("failed")
    ids = [data[k]["trace_id"] for k in ("cache_hit", "cache_miss", "failed")]
    ok = (all(UUID.match(i) for i in ids) and len(set(ids)) == 3
          and data["cache_hit"]["path"] == "cache_hit" and not hit & {"planner", "writer", "reviewer"} and "cache_lookup" in hit
          and data["cache_miss"]["path"] == "cache_miss" and {"cache_lookup", "planner", "writer", "reviewer", "request"} <= miss
          and data["failed"]["failing_stage"] and data["failed"]["error"] and "request" in failed)
    return ok, f"hit {sorted(hit)}; miss {sorted(miss)}; failed at '{data['failed']['failing_stage']}' ({data['failed']['error'][:60]})"


# ---------------- Part 2: evaluator ----------------
def c_evaluation():
    records = jload(RAW / "evaluation_results.json")
    spans = read_spans()
    eval_traces = {s["trace_id"] for s in spans if s["stage"] == "evaluation"}
    good = all(set(r["scores"]) >= {"plan_quality", "writer_helpfulness", "final_helpfulness"}
               and all(r["scores"][k]["score"] is None or 1 <= r["scores"][k]["score"] <= 5 for k in ("plan_quality", "writer_helpfulness", "final_helpfulness"))
               and r["trace_id"] in eval_traces and r.get("improvement") for r in records)
    diffs = [r["improvement"]["difference"] for r in records if r["improvement"].get("difference") is not None]
    return len(records) >= 1 and good, f"{len(records)} end-to-end evaluations, scores in 1-5, each has an evaluation span; final-minus-draft differences: {diffs}"


# ---------------- Part 3: judge validation ----------------
def c_cases_and_labels():
    cases, labels = jload(DATA / "eval_cases.json"), list(csv.DictReader(open(DATA / "human_labels.csv", encoding="utf-8")))
    ids = [c["case_id"] for c in cases]
    fields = all({"case_id", "question", "plan", "draft", "variant"} <= set(c) for c in cases)
    ok = len(cases) == 20 and len(set(ids)) == 20 and fields and [r["case_id"] for r in labels] == ids and all(r["human_label"] in ("1", "2", "3", "4", "5") for r in labels)
    spread = sorted({r["human_label"] for r in labels})
    return ok, f"20 frozen drafts, 20 hand labels (labels used: {spread})"


def c_labels_committed_first():
    first = first_commit_time("**/human_labels.csv")
    if first is None:
        return False, "human_labels.csv is not committed yet"
    produced = (RAW / "judge_validation_cases.csv").stat().st_mtime
    when = datetime.fromtimestamp(first, timezone.utc).isoformat(timespec="seconds")
    return first <= produced, f"human_labels.csv first committed {when}, judge scores written {datetime.fromtimestamp(produced, timezone.utc).isoformat(timespec='seconds')}"


def c_judge_stats():
    from scipy.stats import spearmanr

    saved = jload(RAW / "judge_validation.json")
    rows = list(csv.DictReader(open(RAW / "judge_validation_cases.csv", encoding="utf-8")))
    human = [float(r["human_label"]) for r in rows]
    runs = [[float(r[f"judge_run{k}"]) for r in rows] for k in (1, 2, 3)]
    rho = round(float(spearmanr(human, runs[0])[0]), 4)
    mad = round(sum(abs(j - h) for j, h in zip(runs[0], human)) / len(rows), 1)
    changed = sum(1 for i in range(len(rows)) if len({runs[k][i] for k in range(3)}) > 1)
    s = saved["stats"]
    ok = (len(rows) == 20 and abs(rho - s["agreement_run1"]["spearman_rho"]) < 1e-3 and abs(mad - s["agreement_run1"]["mean_abs_difference"]) < 0.051
          and changed == s["repeatability"]["cases_with_any_change"] and s["repeatability"]["runs"] == 3)
    return ok, f"recomputed from CSV: Spearman {rho}, mean abs difference {mad}, cases changed across 3 runs {changed}/20 (all match saved statistics)"


# ---------------- Part 4.3: latency ----------------
def c_latency():
    from run_latency import percentile

    data = jload(RAW / "latency_run.json")
    rows = list(csv.DictReader(open(RAW / "latency_requests.csv", encoding="utf-8")))
    table = {r["stage"]: r for r in data["table"]}
    spans = read_spans()
    lookups = {s["trace_id"]: s.get("attrs", {}).get("cache_hit") for s in spans if s["stage"] == "cache_lookup"}
    misses = all(lookups.get(i) is False for i in data["trace_ids"])
    e2e = [float(r["end_to_end"]) for r in rows if r["end_to_end"]]
    p50 = round(percentile(e2e, 50), 1)
    shares = sum(r["pct_of_end_to_end"] or 0 for r in data["table"] if r["stage"] in TABLE_STAGES + ["Unattributed (client, database lookup, cache write)"])
    ok = (data["requests"] == 50 and data["confirmed_cache_miss_by_span"] == 50 and misses and not data["failed_requests"]
          and all(s in table for s in TABLE_STAGES) and abs(p50 - table["End-to-end (cache miss)"]["p50_ms"]) < 0.11 and abs(shares - 100) < 0.6
          and data["dominant_stage"]["stage"] in TABLE_STAGES and data["cache_hit_latency"]["n"] >= 1)
    return ok, (f"50 confirmed cache misses; recomputed end-to-end p50 {p50} ms; shares sum to {round(shares, 1)}%; "
                f"dominant {data['dominant_stage']['stage']} ({data['dominant_stage']['pct_of_end_to_end']}%); cache-hit latency kept separate (n={data['cache_hit_latency']['n']})")


def c_dashboard_files():
    names = ["dashboard.py", "dashboard_data.py"]
    text = (CODE / "dashboard.py").read_text(encoding="utf-8")
    ok = all((CODE / n).exists() for n in names) and "st.cache_resource" in text and "st.cache_data" in text
    return ok, "dashboard.py and dashboard_data.py present; uses st.cache_data and st.cache_resource (screenshots are in the report)"


def main() -> int:
    before = code_hash()
    print(f"HW10 verification - Alyssa Gomez, SID4={SID4}, PREFIX={PREFIX}\n")
    for name, fn in (("section 0 values", c_section0), ("offline unit tests", c_unit_tests),
                     ("part 4.1: span format and stages", c_span_format), ("part 4.2: three required traces", c_three_traces),
                     ("part 2: evaluation results", c_evaluation), ("part 3.1: 20 frozen drafts and hand labels", c_cases_and_labels),
                     ("part 3.1: labels committed before judge scores", c_labels_committed_first), ("part 3.2/3.3: judge statistics recomputed", c_judge_stats),
                     ("part 4.3: 50-request latency table", c_latency), ("part 1: dashboard files", c_dashboard_files)):
        check(name, fn)
    after = code_hash()
    check("application code unchanged by verification", lambda: (before == after, f"sha256 {after[:16]}..."))
    counts = {s: sum(r["status"] == s for r in RESULTS) for s in ("PASS", "FAIL", "SKIP")}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    out = {"student": "Alyssa Gomez", "sid4": SID4, "prefix": PREFIX, "seed": SEED, "verify_seed": VERIFY_SEED, "git_commit": commit,
           "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code_sha256": after, "summary": counts, "checks": RESULTS}
    path = ROOT / "reports" / "hw10" / "verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped -> {path.relative_to(ROOT)}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())