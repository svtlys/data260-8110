import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent

SID4 = "8110"
SEED = 8110
VERIFY_SEED = 268110
MODEL_NAME = "qwen3:8b"
PORT_BASE = 8010

checks = []


def check(name, condition, detail=""):
    checks.append({"check": name, "passed": bool(condition), "detail": detail})
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {('- ' + detail) if detail else ''}")


def get_commit_hash():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


required_files = [
    "code/web_application/index.html",
    "code/web_application/app.js",
    "code/main.py",
    "code/agent_graph.py",
    "src/model_client.py",
    "run_schema_experiment.py",
    "run_ceiling_experiment.py",
    "run_adversarial_experiment.py",
    "reports/hw02/RUN_LOG.txt",
    "reports/hw02/METRICS.md",
    "reports/hw02/AI_USE.md",
    "reports/hw02/cases/schema_input.json",
    "reports/hw02/cases/adversarial_input.json",
]
for f in required_files:
    path = ROOT / f
    exists_and_nonempty = path.exists() and path.stat().st_size > 0
    check(f"file exists and non-empty: {f}", exists_and_nonempty)


try:
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         f"http://localhost:{PORT_BASE}/listings"],
        capture_output=True, text=True, timeout=5,
    )
    status_code = result.stdout.strip()
    check(
        f"FastAPI backend responds on port {PORT_BASE}",
        status_code == "200",
        f"got HTTP {status_code} (start the server with: uvicorn main:app --port {PORT_BASE}, from code/)",
    )
except Exception as e:
    check(f"FastAPI backend responds on port {PORT_BASE}", False, str(e))

try:
    result = subprocess.run(
        [sys.executable, "agent_graph.py"],
        capture_output=True, text=True, timeout=300, cwd=ROOT / "code",
    )
    finished = result.returncode == 0
    produced_final_state = "FINAL STATE" in result.stdout
    check("LangGraph script finishes (does not hang)", finished, f"return code {result.returncode}")
    check("LangGraph script produces a final state", produced_final_state)
except subprocess.TimeoutExpired:
    check("LangGraph script finishes (does not hang)", False, "timed out after 300s")
except Exception as e:
    check("LangGraph script finishes (does not hang)", False, str(e))

raw_checks = [
    ("reports/hw02/raw/schema_validation_results.json", 30),
    ("reports/hw02/raw/ceiling_comparison_results.json", 40),
    ("reports/hw02/raw/adversarial_results.json", 5),
]
for rel_path, expected_count in raw_checks:
    path = ROOT / rel_path
    if path.exists():
        with open(path) as fp:
            data = json.load(fp)
        check(f"{rel_path} has {expected_count} runs", len(data) == expected_count, f"found {len(data)}")
    else:
        check(f"{rel_path} exists", False, "file not found")

try:
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    ollama_ok = result.returncode == 0 and MODEL_NAME in result.stdout
    check(f"Ollama reachable and {MODEL_NAME} pulled", ollama_ok, result.stdout.strip()[:200])
except Exception as e:
    check(f"Ollama reachable and {MODEL_NAME} pulled", False, str(e))

output = {
    "homework": "HW2",
    "sid4": SID4,
    "commit_hash": get_commit_hash(),
    "model_config": {"model": MODEL_NAME, "port_base": PORT_BASE},
    "seed": SEED,
    "verify_seed": VERIFY_SEED,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "total_checks": len(checks),
    "passed": sum(1 for c in checks if c["passed"]),
    "failed": sum(1 for c in checks if not c["passed"]),
    "checks": checks,
}

out_path = ROOT / "reports/hw02/verification.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as fp:
    json.dump(output, fp, indent=2)

print(f"\n{output['passed']}/{output['total_checks']} checks passed.")
print(f"Commit hash recorded: {output['commit_hash']}")
print(f"Results written to {out_path}")