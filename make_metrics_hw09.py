import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, DATA = ROOT / "reports" / "hw09" / "raw", ROOT / "data" / "hw09"
sys.path.insert(0, str(ROOT / "code"))

from cache_config import DOMAIN_ID, LLM_MODEL, PORT_BASE, PREFIX, SEED, SID4, SYNC_EVERY, VERIFY_SEED  # noqa: E402


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
    d = load(RAW / "part2_results.json")
    s = d["summary"]
    rows = [(r["n"], r["kind"], r["is_cached"], "-" if r["similarity"] is None else r["similarity"], r["latency_ms"]) for r in d["queries"]]
    head = (f"Threshold {d['threshold']}. Queries: {s['queries']}, hits: {s['hits']}, **hit rate {s['hit_rate_pct']}%**. "
            f"Average latency: cached **{s['avg_latency_cached_ms']} ms**, not cached **{s['avg_latency_not_cached_ms']} ms**.")
    return head + "\n\n" + table(["#", "Kind", "is_cached", "similarity", "latency (ms)"], rows)


def part3() -> str:
    d = load(RAW / "sweep_table.json")
    rows = [(r["threshold"], f"{r['hit_rate_pct']}%", f"{r['false_hit_rate_pct']}%", r["mean_latency_ms"], f"${r['total_cost']}", ", ".join(r["false_hit_ids"]) or "-")
            for r in d["table"]]
    c = d["costs"]
    sens = ", ".join(f"false-hit ${x['c_false_hit']} -> {x['best_threshold']}" for x in d["sensitivity"])
    text = (f"40 labeled cases. Costs: miss ${c['c_miss']}, hit ${c['c_hit']}, false hit ${c['c_false_hit']}. Miss latency used: {d['miss_latency_ms_from_part2']} ms (measured in Part 2).\n\n"
            + table(["Threshold", "Hit rate", "False-hit rate", "Mean latency (ms)", "Total cost", "False-hit cases"], rows)
            + f"\n\n**Chosen threshold: {d['chosen_threshold']}** (lowest total cost). Sensitivity: {sens}.")
    stale = load(RAW / "stale_demo.json")
    srows = [(i + 1, st["is_cached"], st["stale_invalidated"], st["answer"][:70], st["database_truth"]) for i, st in enumerate(stale)]
    return text + "\n\n### 3.5 Stale answer and invalidation\n\n" + table(["Step", "is_cached", "stale_invalidated", "Answer returned", "Database says"], srows)


def part4() -> str:
    val, var = load(RAW / "validation_report.json"), load(RAW / "variant_results.json")
    vrows = [(r["lesson_id"], r["failure_pattern"], r["failures_before"], r["failures_after"], "KEEP" if r["keep"] else "REMOVE", r["reason"]) for r in val["lessons"]]
    rows = [(r["variant"], r["correct"], r["incorrect"], r["avg_attempts"], r["avg_latency_s"]) for r in var["table"]]
    fails = {n: [x["id"] for x in v["results"] if not x["correct"]] for n, v in var["detail"].items()}
    train = load(RAW / "training_run.json")
    return ("### 4.2 Training\n\n" + f"Training questions: {len(train['results'])}; first-attempt failures: {len(train['failures'])} "
            f"({sum(1 for r in train['results'] if r.get('injected'))} of them injected as a controlled test). Lessons created: {len(train['lessons'])}.\n\n"
            "### 4.3 Validation (validation_data.json, single attempt)\n\n"
            + table(["Lesson", "Pattern", "Failures before", "Failures after", "Decision", "Reason"], vrows)
            + "\n\n### 4.4 Variants on test_data.json\n\n" + table(["Variant", "Correct", "Incorrect", "Average attempts", "Average latency (s)"], rows)
            + "\n\nIncorrect test ids: " + "; ".join(f"{n}: {ids or 'none'}" for n, ids in fails.items()))


def main() -> int:
    parts = [
        f"# METRICS.md - HW9\n\nStudent: Alyssa Gomez | generated {datetime.now().isoformat(timespec='seconds')} from reports/hw09/raw/ (not typed by hand)\n",
        f"## Section 0\n\nSID4 {SID4} | PORT_BASE {PORT_BASE} | PREFIX {PREFIX} | SEED {SEED} | VERIFY_SEED {VERIFY_SEED} | DOMAIN_ID {DOMAIN_ID} (Rental Housing Listings)\n\n"
        f"Hardware: {hardware()}\n\nModel: {LLM_MODEL} via Ollama (temperature 0 for Part 4); embeddings: all-MiniLM-L6-v2 (384-dim)\n",
        f"## Part 1 - Redis view counter\n\nKey `{PREFIX}:views:listing:<id>`; INCR on every access; count written to the database every {SYNC_EVERY} increments (log line \"Synced views to database\").\n",
        "## Part 2 - Semantic cache\n\n" + part2() + "\n",
        "## Part 3 - Threshold sweep, cost model, stale answers\n\n" + part3() + "\n",
        "## Part 4 - Self-improving agents\n\n" + part4() + "\n",
    ]
    path = ROOT / "reports" / "hw09" / "METRICS.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())