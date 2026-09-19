import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent

SID4 = "8110"
SEED = 8110
VERIFY_SEED = 268110
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
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


# --- Required files exist and are non-empty ---
required_files = [
    "code/auth.py",
    "code/templates/home.html",
    "code/templates/login.html",
    "code/templates/dashboard.html",
    "chunking_comparison.py",
    "generate_manifest.py",
    "reports/hw03/RUN_LOG.txt",
    "reports/hw03/METRICS.md",
    "reports/hw03/AI_USE.md",
    "reports/hw03/SOURCES.md",
    "reports/hw03/CORPUS_MANIFEST.json",
    "reports/hw03/cases/questions.yaml",
    "reports/hw03/raw/chunking_comparison_results.json",
    "reports/hw03/raw/chunking_comparison_results.csv",
    "reports/hw03/raw/chunk_stats.json",
]
for f in required_files:
    path = ROOT / f
    exists_and_nonempty = path.exists() and path.stat().st_size > 0
    check(f"file exists and non-empty: {f}", exists_and_nonempty)

# --- Corpus manifest hashes actually match the files on disk ---
manifest_path = ROOT / "reports/hw03/CORPUS_MANIFEST.json"
if manifest_path.exists():
    import hashlib
    with open(manifest_path) as f:
        manifest = json.load(f)
    all_match = True
    for entry in manifest:
        filepath = ROOT / "corpus" / entry["filename"]
        if not filepath.exists():
            all_match = False
            continue
        actual_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
        if actual_hash != entry["sha256"]:
            all_match = False
    check("CORPUS_MANIFEST.json hashes match files on disk", all_match)

# --- Does the FastAPI backend respond on PORT_BASE? (behavioral, not text match) ---
try:
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://localhost:{PORT_BASE}/"],
        capture_output=True, text=True, timeout=5,
    )
    status_code = result.stdout.strip()
    check(
        f"FastAPI app responds on port {PORT_BASE}",
        status_code == "200",
        f"got HTTP {status_code} (start with: uvicorn main:app --port {PORT_BASE}, from code/)",
    )
except Exception as e:
    check(f"FastAPI app responds on port {PORT_BASE}", False, str(e))

# --- Login flow works end to end (behavioral: does it succeed, not exact text) ---
try:
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         "-X", "POST", f"http://localhost:{PORT_BASE}/login",
         "-d", "username=landlord&password=rentals123"],
        capture_output=True, text=True, timeout=5,
    )
    status_code = result.stdout.strip()
    check("Login with valid credentials redirects (302)", status_code == "302", f"got HTTP {status_code}")
except Exception as e:
    check("Login with valid credentials redirects (302)", False, str(e))

# --- Does the chunking comparison raw output contain results for all 3 techniques? ---
raw_path = ROOT / "reports/hw03/raw/chunking_comparison_results.json"
if raw_path.exists():
    with open(raw_path) as f:
        raw_data = json.load(f)
    techniques_found = set(row["technique"] for row in raw_data)
    expected = {"Token", "Semantic", "SentenceWindow"}
    check(
        "All 3 chunking techniques present in raw results",
        expected.issubset(techniques_found),
        f"found: {techniques_found}",
    )
    check("Raw results non-empty (retrieval did not hang/fail silently)", len(raw_data) > 0, f"{len(raw_data)} rows")

# --- Questions.yaml has exactly 5 questions with at least 2 single-source ---
questions_path = ROOT / "reports/hw03/cases/questions.yaml"
if questions_path.exists():
    import yaml
    with open(questions_path) as f:
        qdata = yaml.safe_load(f)
    qlist = qdata.get("questions", [])
    check("questions.yaml has exactly 5 questions", len(qlist) == 5, f"found {len(qlist)}")
    single_source_count = sum(1 for q in qlist if q.get("single_source"))
    check("At least 2 questions marked single_source", single_source_count >= 2, f"found {single_source_count}")

# --- Assemble and write output ---
output = {
    "homework": "HW3",
    "sid4": SID4,
    "commit_hash": get_commit_hash(),
    "model_config": {"embedding_model": MODEL_NAME, "port_base": PORT_BASE},
    "seed": SEED,
    "verify_seed": VERIFY_SEED,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "total_checks": len(checks),
    "passed": sum(1 for c in checks if c["passed"]),
    "failed": sum(1 for c in checks if not c["passed"]),
    "checks": checks,
}

out_path = ROOT / "reports/hw03/verification.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as fp:
    json.dump(output, fp, indent=2)

print(f"\n{output['passed']}/{output['total_checks']} checks passed.")
print(f"Commit hash recorded: {output['commit_hash']}")
print(f"Results written to {out_path}")