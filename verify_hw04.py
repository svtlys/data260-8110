import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent

SID4 = "8110"
SEED = 8110
VERIFY_SEED = 268110
PORT_BASE = 8010
LLM_MODEL = "qwen3:8b"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
API = f"http://localhost:{PORT_BASE}"

checks = []


def check(name, condition, detail=""):
    checks.append({"check": name, "passed": bool(condition), "detail": detail})
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def get_commit_hash():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def load_json(rel_path):
    path = ROOT / rel_path
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- files
required_files = [
    "code/db.py",
    "code/models.py",
    "code/init_db.py",
    "code/api_routes.py",
    "code/seed_hw04.py",
    "code/query_counter.py",
    "code/measure_n1.py",
    "code/rag.py",
    "code/web_application_react/src/App.jsx",
    "code/web_application_react/src/components/Login.jsx",
    "code/web_application_react/src/components/Home.jsx",
    "code/web_application_react/src/components/CreateRecord.jsx",
    "code/web_application_react/src/components/UpdateRecord.jsx",
    "code/web_application_react/src/components/DeleteRecord.jsx",
    "reports/hw04/RUN_LOG.txt",
    "reports/hw04/METRICS.md",
    "reports/hw04/AI_USE.md",
    "reports/hw04/raw/n1_measurement_results.json",
    "reports/hw04/raw/n1_measurement_results.csv",
    "reports/hw04/raw/rag_comparison_results.json",
    "reports/hw04/raw/rag_topk_sweep_results.json",
    "reports/hw04/raw/rag_evaluation_table.csv",
    "reports/hw04/raw/rag_console_output.txt",
]
for rel in required_files:
    path = ROOT / rel
    check(f"file exists and non-empty: {rel}", path.exists() and path.stat().st_size > 0)

# ------------------------------------------------- static naming checks
db_py = ROOT / "code/db.py"
if db_py.exists():
    text = db_py.read_text()
    check("connection variable is named db_session_basede26", "db_session_basede26" in text)
    check("database name is s8110_rel", "s8110_rel" in text)

corpus_docs = [p for p in (ROOT / "corpus").glob("*.txt") if p.name != "tiny_shakespeare.txt"]
check("RAG corpus has at least 5 documents", len(corpus_docs) >= 5, f"found {len(corpus_docs)}")

# ------------------------------------------------ live API behavior
session = requests.Session()
try:
    r = session.get(f"{API}/api/me", timeout=5)
    check(f"FastAPI responds on port {PORT_BASE}", r.status_code in (200, 401), f"HTTP {r.status_code}")
    api_up = True
except Exception as e:
    check(f"FastAPI responds on port {PORT_BASE}", False, str(e))
    api_up = False

if api_up:
    r = requests.get(f"{API}/api/listings", timeout=10)
    check("listings endpoint rejects unauthenticated requests", r.status_code == 401, f"HTTP {r.status_code}")

    r = session.post(
        f"{API}/api/login",
        json={"email": "landlord@example.com", "password": "rentals123"},
        timeout=10,
    )
    check("login with valid credentials succeeds", r.status_code == 200, f"HTTP {r.status_code}")
    set_cookie = r.headers.get("set-cookie", "")
    check("session cookie is HttpOnly", "httponly" in set_cookie.lower())
    token = session.cookies.get("session_token", "")
    check(
        "session cookie is an opaque token (no user data)",
        len(token) > 0 and "@" not in token and "landlord" not in token.lower(),
        f"token length {len(token)}",
    )

    r = session.get(f"{API}/api/me", timeout=5)
    check("session cookie authenticates /api/me", r.status_code == 200, f"HTTP {r.status_code}")

    r = session.get(f"{API}/api/listings", timeout=30)
    listing_count = len(r.json()) if r.status_code == 200 else 0
    check("seeded data present (at least 5000 listings)", listing_count >= 5000, f"{listing_count} listings")

    naive = session.get(f"{API}/api/listings-naive", params={"page": 1, "page_size": 10}, timeout=30)
    fixed = session.get(f"{API}/api/listings-fixed", params={"page": 1, "page_size": 10}, timeout=30)
    check("naive list endpoint returns data", naive.status_code == 200 and len(naive.json().get("data", [])) == 10)
    check("fixed list endpoint returns data", fixed.status_code == 200 and len(fixed.json().get("data", [])) == 10)
    if naive.status_code == 200 and fixed.status_code == 200:
        n, f_ = naive.json(), fixed.json()
        check(
            "naive and fixed return the same listing ids",
            [x["id"] for x in n["data"]] == [x["id"] for x in f_["data"]],
        )
        check(
            "naive issues page_size+1 queries, fixed issues 1",
            n["sql_query_count"] == 11 and f_["sql_query_count"] == 1,
            f"naive={n['sql_query_count']} fixed={f_['sql_query_count']}",
        )

    session.post(f"{API}/api/logout", timeout=5)
    r = session.get(f"{API}/api/me", timeout=5)
    check("logged-out session cannot be reused", r.status_code == 401, f"HTTP {r.status_code}")

# --------------------------------------------- raw N+1 measurement data
n1 = load_json("reports/hw04/raw/n1_measurement_results.json")
if n1 is not None:
    check("N+1 raw data has 180 measured requests", len(n1) == 180, f"found {len(n1)}")
    combos_ok = all(
        sum(1 for row in n1 if row["page_size"] == size and row["version"] == version) == 30
        for size in (10, 50, 200)
        for version in ("naive", "fixed")
    )
    check("N+1 raw data has 30 requests per page size and version", combos_ok)
    counts_ok = all(
        row["sql_query_count"] == (row["page_size"] + 1 if row["version"] == "naive" else 1)
        for row in n1
    )
    check("recorded query counts are page_size+1 (naive) and 1 (fixed)", counts_ok)

# ------------------------------------------------------ RAG raw data
rag = load_json("reports/hw04/raw/rag_comparison_results.json")
if rag is not None:
    check("RAG results cover six questions", [q["question_id"] for q in rag] == [f"Q{i}" for i in range(1, 7)])
    check(
        "every question has an answer for all three configurations",
        all(q["no_rag_answer"].strip() and q["basic_rag_answer"].strip() and q["context_rag_answer"].strip() for q in rag),
    )
    refusals = [q for q in rag if q["question_id"] in ("Q5", "Q6")]
    check(
        "context-engineered RAG refused Q5 and Q6 (assignment-mandated refusal wording)",
        len(refusals) == 2 and all("cannot answer" in q["context_rag_answer"].lower() for q in refusals),
    )

sweep = load_json("reports/hw04/raw/rag_topk_sweep_results.json")
if sweep is not None:
    check("top_k sweep covers k = 1, 3, 5", [s["k"] for s in sweep] == [1, 3, 5])

# ------------------------------------------------------------- Ollama
try:
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    check(f"Ollama reachable with {LLM_MODEL} pulled", result.returncode == 0 and LLM_MODEL in result.stdout)
except Exception as e:
    check(f"Ollama reachable with {LLM_MODEL} pulled", False, str(e))

# ------------------------------------------------------------- output
output = {
    "homework": "HW4",
    "sid4": SID4,
    "commit_hash": get_commit_hash(),
    "model_config": {
        "llm": LLM_MODEL,
        "embedding_model": EMBED_MODEL,
        "chunk_size": 500,
        "chunk_overlap": 50,
        "port_base": PORT_BASE,
    },
    "seed": SEED,
    "verify_seed": VERIFY_SEED,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "total_checks": len(checks),
    "passed": sum(1 for c in checks if c["passed"]),
    "failed": sum(1 for c in checks if not c["passed"]),
    "checks": checks,
}

out_path = ROOT / "reports/hw04/verification.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as fp:
    json.dump(output, fp, indent=2)

print(f"\n{output['passed']}/{output['total_checks']} checks passed.")
print(f"Commit hash recorded: {output['commit_hash']}")
print(f"Results written to {out_path}")