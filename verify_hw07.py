import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CODE = ROOT / "code"
HW = ROOT / "reports" / "hw07"
RAW = HW / "raw"
sys.path.insert(0, str(CODE))

SID4 = "8110"
PORT_BASE = 8000 + (int(SID4) % 900)
PREFIX = "s" + SID4
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
DOMAIN_ID = int(SID4) % 8
LLM_MODEL = "qwen3:8b"
STOP_REASONS = {"final_answer", "safety_block", "max_steps", "repair_failed", "model_error", "invalid_input",
                "tool_budget", "token_budget"}

checks = []


def check(name, fn):
    """Run one check; a broken environment fails the check instead of crashing the script."""
    try:
        detail, passed = (fn() or ""), True
    except AssertionError as exc:
        detail, passed = str(exc), False
    except Exception as exc:
        detail, passed = f"{type(exc).__name__}: {exc}", False
    checks.append({"check": name, "passed": passed, "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def jsonl(path):
    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def find_key(data, key):
    """Value of `key` anywhere in nested dicts/lists, or None."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = find_key(value, key)
            if found is not None:
                return found
    if isinstance(data, list):
        for value in data:
            found = find_key(value, key)
            if found is not None:
                return found
    return None


# ------------------------------------------------------------------ files

def files_exist(paths):
    def run():
        missing = [p for p in paths if not (ROOT / p).is_file() or (ROOT / p).stat().st_size == 0]
        assert not missing, "missing or empty: " + ", ".join(missing)
        return f"{len(paths)} files present"
    return run


CODE_FILES = [
    "code/jwt_auth.py", "code/agent_loop.py", "code/agent_cases.py", "code/run_hw7_part2.py", "code/reflexion.py",
    "code/run_hw7_part3.py", "code/bike_tools.py", "code/bike_costs.py", "code/bike_agent.py", "code/bike_app.py",
    "code/prepare_bike_data.py", "code/make_fixtures.py", "code/security_eval.py", "code/run_hw7_part5.py",
    "code/file_tools.py", "code/run_hw7_part6.py",
]
TEST_FILES = ["test_jwt_auth.py", "test_agent_loop.py", "test_reflexion.py", "test_bike.py", "test_security.py",
              "test_file_tools.py"]
REPORT_FILES = [
    "reports/hw07/RUN_LOG.txt", "reports/hw07/METRICS.md", "reports/hw07/AI_USE.md",
    "reports/hw07/raw/agent_runs.jsonl", "reports/hw07/raw/part2_attempts.jsonl",
    "reports/hw07/raw/part2_reliability_summary.json", "reports/hw07/raw/part2_reliability_table.md",
    "reports/hw07/raw/part3_tasks.jsonl", "reports/hw07/raw/reflections.jsonl", "reports/hw07/raw/part3_comparison.json",
    "reports/hw07/raw/part3_comparison.md", "reports/hw07/raw/tool_schemas.json",
    "reports/hw07/raw/bike_runs/membership.json", "reports/hw07/raw/bike_runs/payperuse.json",
    "reports/hw07/raw/part5_results.jsonl", "reports/hw07/raw/part6_integration.md", "reports/hw07/raw/part6_safety_gate.md",
    "data/bike/bike_membership_wins.csv", "data/bike/bike_payperuse_wins.csv", "data/bike/SCENARIOS.md",
    "fixtures/bike_pricing_clean.html", "fixtures/bike_pricing_override.html", "fixtures/bike_pricing_sql.html",
    "fixtures/bike_pricing_exfil.html",
]


def tests_pass(name):
    def run():
        out = subprocess.run([sys.executable, "-m", "pytest", "-q", name], cwd=CODE, capture_output=True, text=True,
                             timeout=300)
        assert out.returncode == 0, f"{name} failed: " + (out.stdout + out.stderr)[-300:]
        return out.stdout.strip().splitlines()[-1]
    return run


def ruff_clean():
    exe = shutil.which("ruff")
    assert exe, "ruff is not installed in this environment"
    files = [p.name for p in CODE.glob("*.py") if p.name in {Path(f).name for f in CODE_FILES + TEST_FILES}]
    out = subprocess.run([exe, "check", *sorted(files)], cwd=CODE, capture_output=True, text=True)
    assert out.returncode == 0, "ruff errors: " + out.stdout[-300:]
    return f"{len(files)} HW7 files pass ruff"


# ------------------------------------------------------------------ Parts 2 and 3

def agent_runs():
    rows = jsonl(RAW / "agent_runs.jsonl")
    stops = [r for r in rows if r.get("type") == "stop"]
    assert stops, "no stop records in agent_runs.jsonl"
    odd = {r.get("stop_reason") for r in stops} - STOP_REASONS
    assert not odd, f"unknown stop reasons: {odd}"
    return f"{len(stops)} logged runs, every one with a named stop reason"


def reliability():
    attempts = jsonl(RAW / "part2_attempts.jsonl")
    assert len(attempts) >= 21, f"{len(attempts)} attempts logged, need 21"
    summary = json.loads((RAW / "part2_reliability_summary.json").read_text())
    before, after = find_key(summary, "rate_before_repair_pct"), find_key(summary, "rate_after_repair_pct")
    assert before is not None and after is not None, "summary has no before/after repair rates"
    return f"{len(attempts)} attempts; well-formed call rate {before}% -> {after}% after repair"


def reflexion_budget():
    refl = jsonl(RAW / "reflections.jsonl")
    assert refl, "no reflections saved"
    for r in refl:
        assert r.get("user_id") and r.get("task_run_id"), "a reflection is not scoped to user and task run"
        assert r.get("evidence"), "a reflection has no evidence"
    per_run = {}
    for r in refl:
        per_run[r["task_run_id"]] = per_run.get(r["task_run_id"], 0) + 1
    assert max(per_run.values()) <= 2, "more than 2 reflections for one task run"
    comparison = json.loads((RAW / "part3_comparison.json").read_text())
    tasks = find_key(comparison, "tasks")
    assert isinstance(tasks, int) and tasks >= 21, f"comparison covers {tasks} tasks, need 21"
    stops = find_key(comparison, "reflexion_stop_reasons") or {}
    return f"{len(refl)} scoped reflections, at most 2 per task run; {tasks} paired tasks; stops {stops}"


# ------------------------------------------------------------------ Part 4

def tool_schemas():
    text = (RAW / "tool_schemas.json").read_text()
    for name in ("csv_sql", "policy_retriever", "calculator"):
        assert name in text, f"{name} missing from tool_schemas.json"
    return "csv_sql, policy_retriever and calculator schemas saved"


def scenario_files():
    for name in ("bike_membership_wins.csv", "bike_payperuse_wins.csv"):
        rows = len((ROOT / "data" / "bike" / name).read_text().splitlines()) - 1
        assert rows >= 500, f"{name} has {rows} rides, need at least 500"
    return "both scenario files have 500+ rides"


def bike_runs():
    details = []
    for label in ("membership", "payperuse"):
        run = json.loads((RAW / "bike_runs" / f"{label}.json").read_text())
        assert run.get("answer") and run.get("independent_check"), f"{label}: no usable answer or independent check"
        snap = run.get("snapshot") or {}
        text = RAW / "pricing_snapshots" / snap.get("text_file", "missing")
        assert text.is_file(), f"{label}: snapshot text file missing"
        assert hashlib.sha256(text.read_bytes()).hexdigest() == snap.get("sha256"), f"{label}: snapshot hash mismatch"
        assert run["metrics"]["steps"] >= 1 and run["metrics"].get("stop_reason"), f"{label}: metrics incomplete"
        details.append(f"{label}: {run['answer']['decision']} (agrees with check: {run.get('decision_agrees_with_check')})")
    return "; ".join(details)


# ------------------------------------------------------------------ Part 5

def fixtures_attacks():
    expect = {"override": "Pay Per Ride/Minute", "sql": "DROP TABLE trips", "exfil": "ride_id"}
    for name, needle in expect.items():
        assert needle in (ROOT / "fixtures" / f"bike_pricing_{name}.html").read_text(), f"{name} fixture has no attack text"
    assert "NEW MESSAGE" not in (ROOT / "fixtures" / "bike_pricing_clean.html").read_text(), "control fixture contains an attack"
    return "3 attack pages and 1 clean control"


def injection_results():
    rows = jsonl(RAW / "part5_results.jsonl")
    seen = {(r["attack"], r["config"]) for r in rows}
    need = {(a, c) for a in ("override", "sql", "exfil") for c in ("before", "prompt", "both")}
    assert need <= seen, "missing cells: " + ", ".join(f"{a}/{c}" for a, c in sorted(need - seen))
    wins = sum(1 for r in rows if r["outcome"] == "succeeded")
    return f"{len(rows)} judged runs in 3 settings; {wins} attack successes in the live runs"


def boundary():
    import run_hw7_part5 as rp
    csv_text = (ROOT / "data" / "bike" / "bike_payperuse_wins.csv").read_text(encoding="utf-8-sig")
    rows = {r["config"]: r for r in rp.boundary_test(csv_text)}
    assert rows["before"]["delete_ran"] and rows["before"]["drop_ran"], "unprotected DELETE/DROP should run"
    assert not rows["both"]["delete_ran"] and not rows["both"]["drop_ran"], "tool contract did not block DELETE/DROP"
    assert rows["both"]["rows_after"] == rows["both"]["rows_before"], "data changed with the tool defense on"
    assert rows["before"]["leak_delivered"] and not rows["both"]["leak_delivered"], "output guard result is wrong"
    return "persuaded-model test: DELETE/DROP run unprotected, refused with the contract; raw ids withheld by the guard"


# ------------------------------------------------------------------ Part 6

def safety_gate():
    import file_tools as ft
    cases = [("ls -la", True), ("cat notes.txt", True), ("python -m pytest -q", True), ("rm -rf build", False),
             ("ls && rm -rf /", False), ("sudo ls", False), ("chmod -R 777 .", False),
             ("dd if=/dev/zero of=/dev/disk2", False), ("mkfs.ext4 /dev/sdb1", False), ("echo x > /etc/hosts", False)]
    for command, allowed in cases:
        for auto in (False, True):
            got = ft.confirm_bash(command, auto_approve=auto)["allowed"]
            assert got is allowed, f"{command!r} auto_approve={auto}: allowed={got}, expected {allowed}"
    return "10/10 commands decided correctly, with and without auto_approve"


def file_tools_integration():
    import file_tools as ft
    with tempfile.TemporaryDirectory(prefix="verify_hw07_") as tmp:
        tools = ft.FileTools(tmp)
        tools.write_file("a.py", "x = 1\n")
        tools.write_file("b.py", "print('DEBUG')\n")
        tools.write_file("c.py", "y = 2\n")
        files = tools.glob_files("**/*.py")["data"]["files"]
        hits = tools.search_in_files("DEBUG", "*.py")["data"]["matches"]
        assert files == ["a.py", "b.py", "c.py"] and [h["file"] for h in hits] == ["b.py"], "glob/search found the wrong files"
        assert "DEBUG" in tools.read_file("b.py")["data"]["lines"][0], "read_file did not return the line"
        assert not tools.read_file("../outside.txt")["success"], "path escape was not refused"
        blocked = tools.bash("rm -rf .", auto_approve=True)
        assert not blocked["success"] and (Path(tmp) / "a.py").exists(), "destructive command ran"
    return "glob -> search -> read finds b.py; escape and rm -rf refused"


def ollama_model():
    tags = requests.get("http://localhost:11434/api/tags", timeout=5).json()
    names = [m.get("name", "") for m in tags.get("models", [])]
    assert any(n.startswith(LLM_MODEL) for n in names), f"{LLM_MODEL} not found in Ollama: {names}"
    return f"{LLM_MODEL} available"


def main():
    check("code files present", files_exist(CODE_FILES))
    check("report, raw-data, scenario and fixture files present", files_exist(REPORT_FILES))
    for name in TEST_FILES:
        check(f"{name} passes", tests_pass(name))
    check("Ruff passes on the HW7 files", ruff_clean)
    check("Part 2: every logged agent run has a named stop reason", agent_runs)
    check("Part 2: 21 reliability attempts logged with before/after repair rates", reliability)
    check("Part 3: reflections are scoped, evidenced and capped; 21 paired tasks", reflexion_budget)
    check("Part 4: tool schemas saved", tool_schemas)
    check("Part 4: scenario CSVs have 500+ rides", scenario_files)
    check("Part 4: both scenario runs have an answer, independent check and a hash-matching snapshot", bike_runs)
    check("Part 5: fixtures hold three attacks and a clean control", fixtures_attacks)
    check("Part 5: all attack/setting cells have judged runs", injection_results)
    check("Part 5: tool boundary and output guard hold against a persuaded model", boundary)
    check("Part 6: 10-command safety gate decides correctly", safety_gate)
    check("Part 6: file tools find the DEBUG file and refuse escapes and rm -rf", file_tools_integration)
    check("local Ollama model is available", ollama_model)

    output = {
        "homework": "HW7",
        "sid4": SID4,
        "commit_hash": git("rev-parse", "HEAD"),
        "model_config": {"llm": LLM_MODEL, "reasoning": False, "temperature": 0.0, "num_ctx": 8192,
                         "agent_loop_max_steps": 8, "langgraph_max_steps": 14, "reflexion_retries": 2,
                         "reflexion_budget": {"tool_calls": 12, "tokens": 8000}, "port_base": PORT_BASE,
                         "prefix": PREFIX, "domain_id": DOMAIN_ID},
        "seed": SEED,
        "verify_seed": VERIFY_SEED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c["passed"]),
        "failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    out_path = HW / "verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\n{output['passed']}/{output['total_checks']} checks passed.")
    print(f"Commit hash recorded: {output['commit_hash']}")
    print(f"Results written to {out_path}")
    return 0 if output["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())