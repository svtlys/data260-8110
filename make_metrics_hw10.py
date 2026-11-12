import csv
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "reports" / "hw10" / "raw"
sys.path.insert(0, str(ROOT / "code"))

from cache_config import DOMAIN_ID, PORT_BASE, PREFIX, SEED, SID4, VERIFY_SEED  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sh(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def hardware() -> str:
    chip = sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor() or platform.machine()
    mem = sh(["sysctl", "-n", "hw.memsize"])
    gb = f", {int(mem) / 2**30:.0f} GB RAM" if mem.isdigit() else ""
    return f"{chip}{gb}, macOS {platform.mac_ver()[0] or platform.platform()}, Python {platform.python_version()}"


def table(headers: list, rows: list) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def part2() -> str:
    rows = [(i, r["question"], r["scores"]["plan_quality"]["score"], r["scores"]["writer_helpfulness"]["score"], r["scores"]["final_helpfulness"]["score"],
             r["improvement"]["difference"], r.get("duration_s")) for i, r in enumerate(load(RAW / "evaluation_results.json"), 1)]
    return table(["#", "Question", "Plan quality", "Writer helpfulness", "Final helpfulness", "Final minus draft", "Evaluation time (s)"], rows)


def part3() -> str:
    d = load(RAW / "judge_validation.json")
    a, r, j = d["stats"]["agreement_run1"], d["stats"]["repeatability"], d["judge"]
    stats = table(["Metric", "Value"], [("Spearman rho (judge vs human, run 1)", a["spearman_rho"]), ("p-value", a["spearman_p"]),
                                        ("Mean absolute difference", a["mean_abs_difference"]), ("Signed bias (judge - human)", a["mean_signed_difference_judge_minus_human"]),
                                        ("Cases whose score changed across 3 runs", f"{r['cases_with_any_change']} / {d['stats']['n_cases']}"),
                                        ("Mean / max absolute change", f"{r['mean_abs_change']} / {r['max_abs_change']}")])
    rows = [(c["case_id"], c["variant"], c["human_label"], c["judge_run1"], c["judge_run2"], c["judge_run3"])
            for c in csv.DictReader(open(RAW / "judge_validation_cases.csv", encoding="utf-8"))]
    return (f"Judge: {j['framework']} {j['deepeval_version']}, model {j['judge_model']}, temperature {j['temperature']}, seed {j['seed']}, timeout {j['timeout_s']} s.\n\n"
            + stats + "\n\n" + table(["Case", "Variant", "Human", "Judge run 1", "Run 2", "Run 3"], rows))


def part4() -> str:
    d = load(RAW / "latency_run.json")
    rows = [(t["stage"], "-" if t["p50_ms"] is None else t["p50_ms"], "-" if t["p95_ms"] is None else t["p95_ms"],
             "-" if t["pct_of_end_to_end"] is None else t["pct_of_end_to_end"], t["n"]) for t in d["table"]]
    ex = load(RAW / "trace_examples.json")
    traces = table(["Example", "trace_id", "Path", "Failing stage"], [(k, v["trace_id"], v["path"], v["failing_stage"] or "-") for k, v in ex.items()])
    return (f"{d['requests']} requests, {d['confirmed_cache_miss_by_span']} confirmed cache misses by their cache_lookup span, {len(d['failed_requests'])} failed.\n\n"
            + table(["Stage", "p50 (ms)", "p95 (ms)", "% of cache-miss end-to-end", "n"], rows)
            + f"\n\nDominant contributor: **{d['dominant_stage']['stage']}** ({d['dominant_stage']['pct_of_end_to_end']}%). Cache-hit latency (separate metric): {d['cache_hit_latency']}.\n\n"
            + "### Required traces\n\n" + traces)


def main() -> int:
    text = f"""# METRICS.md - HW10

Student: Alyssa Gomez | SID4 {SID4} | PORT_BASE {PORT_BASE} | PREFIX {PREFIX} | SEED {SEED} | VERIFY_SEED {VERIFY_SEED} | DOMAIN_ID {DOMAIN_ID}

Hardware: {hardware()}
Local model: qwen3:8b through Ollama (agents and judge)

Every number below is read from the files in `reports/hw10/raw/`.

## Part 2 - evaluator results (end-to-end questions)

{part2()}

## Part 3 - judge validation

{part3()}

## Part 4 - tracing and latency

{part4()}
"""
    path = ROOT / "reports" / "hw10" / "METRICS.md"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())