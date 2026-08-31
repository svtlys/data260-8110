
"""
Run with:
    python verify_hw01.py
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
checks = []


def check(name, condition, detail=""):
    checks.append({"check": name, "passed": bool(condition), "detail": detail})
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {('- ' + detail) if detail else ''}")


# 1. Required files exist
required_files = [
    "DOMAIN_SCHEMA.md",
    "AGENT.md",
    "README.md",
    "code/web_application/index.html",
    "code/web_application/app.js",
    "code/Dockerfile",
    "code/agents_demo.py",
    "code/hw1_client.py",
    "src/model_client.py",
    "run_experiment.py",
    "reports/hw01/RUN_LOG.txt",
    "reports/hw01/METRICS.md",
    "reports/hw01/AI_USE.md",
    "reports/hw01/cases/nondeterminism_input.json",
]
for f in required_files:
    path = ROOT / f
    exists_and_nonempty = path.exists() and path.stat().st_size > 0
    check(f"file exists and non-empty: {f}", exists_and_nonempty)

# 2. Raw non-determinism results exist
raw_json = ROOT / "reports/hw01/raw/nondeterminism_results.json"
raw_csv = ROOT / "reports/hw01/raw/nondeterminism_results.csv"
check("non-determinism raw JSON exists", raw_json.exists() and raw_json.stat().st_size > 0)
check("non-determinism raw CSV exists", raw_csv.exists() and raw_csv.stat().st_size > 0)

if raw_json.exists():
    with open(raw_json) as fp:
        data = json.load(fp)
    check("raw results contain 40 runs", len(data) == 40, f"found {len(data)}")

# 3. Docker image builds (optional -- can be slow, so just check Dockerfile is valid-looking)
dockerfile = ROOT / "code/Dockerfile"
if dockerfile.exists():
    content = dockerfile.read_text()
    check("Dockerfile has FROM instruction", "FROM" in content)
    check("Dockerfile exposes a port", "EXPOSE" in content)

# 4. Ollama is reachable
try:
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    ollama_ok = result.returncode == 0 and "qwen3:8b" in result.stdout
    check("Ollama reachable and qwen3:8b pulled", ollama_ok, result.stdout.strip()[:200])
except Exception as e:
    check("Ollama reachable and qwen3:8b pulled", False, str(e))

# Write results
output = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "total_checks": len(checks),
    "passed": sum(1 for c in checks if c["passed"]),
    "failed": sum(1 for c in checks if not c["passed"]),
    "checks": checks,
}

out_path = ROOT / "reports/hw01/verification.json"
with open(out_path, "w") as fp:
    json.dump(output, fp, indent=2)

print(f"\n{output['passed']}/{output['total_checks']} checks passed.")
print(f"Results written to {out_path}")