"""
make_hw7_docs.py - assemble reports/hw07/RUN_LOG.txt and METRICS.md from the files the HW7 runs produced.

Nothing is invented: every number is copied from a file on disk (or says "(not found)").
Run from the repo root:   python make_hw7_docs.py
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HW = ROOT / "reports" / "hw07"
RAW = HW / "raw"
sys.path.insert(0, str(ROOT / "code"))


def read(path: Path) -> str:
    """File text, or a visible placeholder."""
    return path.read_text().rstrip() if path.is_file() else f"(not found: {path.relative_to(ROOT)})"


def jsonl(path: Path) -> list:
    """Rows of a JSON-lines file, [] if missing."""
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def git_timeline() -> str:
    out = subprocess.run(["git", "log", "--date=iso", "--format=%h  %ad  %s", "-n", "60"], capture_output=True, text=True, cwd=ROOT)
    tags = subprocess.run(["git", "tag", "--list", "hw*"], capture_output=True, text=True, cwd=ROOT).stdout.split()
    return (out.stdout.strip() or "(no git history)") + "\n\ntags: " + (", ".join(tags) or "(none yet)")


def inventory() -> str:
    lines = [f"{'file':<62}{'bytes':>10}  sha256 (first 12)"]
    for path in sorted(p for p in RAW.rglob("*") if p.is_file()):
        lines.append(f"{str(path.relative_to(ROOT)):<62}{path.stat().st_size:>10}  {hashlib.sha256(path.read_bytes()).hexdigest()[:12]}")
    return "\n".join(lines)


def agent_run_summary() -> str:
    stops = [r for r in jsonl(RAW / "agent_runs.jsonl") if r.get("type") == "stop"]
    counts: dict = {}
    for r in stops:
        counts[(r.get("scenario"), r.get("stop_reason"))] = counts.get((r.get("scenario"), r.get("stop_reason")), 0) + 1
    lines = [f"{len(stops)} logged runs in agent_runs.jsonl", f"{'scenario':<28}{'stop_reason':<16}runs"]
    lines += [f"{str(s):<28}{str(r):<16}{n}" for (s, r), n in sorted(counts.items(), key=str)]
    stamps = sorted(r["ts"] for r in stops if r.get("ts"))
    return "\n".join(lines + ([f"first stop {stamps[0]}  last stop {stamps[-1]}"] if stamps else []))


def bike_runs() -> list:
    out = []
    for label in ("membership", "payperuse"):
        path = RAW / "bike_runs" / f"{label}.json"
        if path.is_file():
            out.append(json.loads(path.read_text()))
    return out


def bike_timeline() -> str:
    lines = []
    for run in bike_runs():
        lines.append(f"--- {run['label']} ---")
        for i, e in enumerate(run["timeline"], 1):
            lines.append(f"{i:>2}. [{e['t']:>6}s] {e['kind']:<12}{e.get('tool') or ''}")
        m = run["metrics"]
        lines.append(f"steps {m['steps']}, tool calls {m['tool_calls']}, {m['total_time_s']} s, stop {m['stop_reason']}, "
                     f"verifier retries {m.get('retries', 0)}")
    return "\n".join(lines) or "(no bike runs found)"


def bike_metrics_table() -> str:
    rows = ["| Scenario | Decision | Recomputed cheaper | Agrees | Steps | Tool calls | Time (s) | Stop | Verifier retries | Citations verified |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for run in bike_runs():
        m, c = run["metrics"], run.get("independent_check") or {}
        cites = run.get("citations") or []
        rows.append(f"| {run['label']} | {(run.get('answer') or {}).get('decision')} | {c.get('cheaper')} | "
                    f"{run.get('decision_agrees_with_check')} | {m['steps']} | {m['tool_calls']} | {m['total_time_s']} | "
                    f"{m['stop_reason']} | {m.get('retries', 0)} | {sum(1 for x in cites if x.get('verified'))}/{len(cites)} |")
    return "\n".join(rows)


def injection_table() -> str:
    from security_eval import summarize
    rows = jsonl(RAW / "part5_results.jsonl")
    return summarize(rows) if rows else "(no part5_results.jsonl)"


def verification_summary() -> str:
    path = HW / "verification.json"
    if not path.is_file():
        return "(verification.json not written yet; run verify_hw07.py)"
    data = json.loads(path.read_text())
    lines = [f"{data['passed']}/{data['total_checks']} checks passed at commit {data['commit_hash']} ({data['timestamp']})"]
    return "\n".join(lines + [f"[{'PASS' if c['passed'] else 'FAIL'}] {c['check']}" for c in data["checks"]])


def console_captures() -> str:
    files = sorted((HW / "console").glob("*.txt")) if (HW / "console").is_dir() else []
    return "\n\n".join(f"--- {f.name} ---\n{f.read_text().rstrip()}" for f in files) or "(no captures saved)"


def run_log() -> str:
    bar = "=" * 78
    sections = [("1. Git commit timeline", git_timeline()), ("2. Raw evidence files", inventory()),
                ("3. Agent loop runs (Parts 2 and 3) by stop reason", agent_run_summary()),
                ("4. Part 2 reliability (21 attempts)", read(RAW / "part2_reliability_table.md")),
                ("5. Part 2 reliability, injected faults", read(RAW / "part2_reliability_table_injected.md")),
                ("6. Part 3 Reflexion comparison", read(RAW / "part3_comparison.md")),
                ("7. Part 4 bike-share agent: timelines", bike_timeline()),
                ("8. Part 5 injection results", injection_table()),
                ("9. Part 6 integration test", read(RAW / "part6_integration.md")),
                ("10. Part 6 safety-gate test", read(RAW / "part6_safety_gate.md")),
                ("11. verification.json summary", verification_summary()),
                ("12. Console captures", console_captures())]
    return "\n".join(f"\n{bar}\n{title}\n{bar}\n{body}" for title, body in sections).lstrip() + "\n"


def metrics() -> str:
    parts = ["# HW7 Metrics", "", "All numbers are copied from files in `reports/hw07/raw/`.", "",
             "## Part 2: tool-call reliability (natural run)", read(RAW / "part2_reliability_table.md"), "",
             "## Part 2: tool-call reliability (seeded fault injection)", read(RAW / "part2_reliability_table_injected.md"), "",
             "## Part 3: original loop vs bounded Reflexion", read(RAW / "part3_comparison.md"), "",
             "## Part 4: bike-share agent", bike_metrics_table(), "",
             "## Part 5: prompt injection (verifier retry off)", injection_table(), "",
             "## Part 6: safety gate", read(RAW / "part6_safety_gate.md"), "",
             "## Verification", "```", verification_summary(), "```", ""]
    return "\n".join(parts)


def main() -> None:
    """Write both files."""
    HW.mkdir(parents=True, exist_ok=True)
    (HW / "RUN_LOG.txt").write_text(run_log())
    (HW / "METRICS.md").write_text(metrics())
    print(f"wrote {HW / 'RUN_LOG.txt'} and {HW / 'METRICS.md'}")


if __name__ == "__main__":
    main()