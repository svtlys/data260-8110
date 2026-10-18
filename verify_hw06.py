import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CODE = ROOT / "code"
HW = ROOT / "reports" / "hw06"
RAW = HW / "raw"
sys.path.insert(0, str(CODE))

SID4 = "8110"
PORT_BASE = 8000 + (int(SID4) % 900)
PREFIX = "s" + SID4
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
DOMAIN_ID = int(SID4) % 8
LLM_MODEL = "qwen3:8b"
API = f"http://localhost:{PORT_BASE}"
DB_NAME = f"{PREFIX}_doc"

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


# ------------------------------------------------------------------ file checks

def files_exist(paths):
    def run():
        missing = [p for p in paths if not (ROOT / p).is_file() or (ROOT / p).stat().st_size == 0]
        assert not missing, "missing or empty: " + ", ".join(missing)
        return f"{len(paths)} files present"
    return run


CODE_FILES = [
    "code/hw6_main.py", "code/doc_config.py", "code/doc_mongo.py", "code/doc_schemas.py",
    "code/doc_routes.py", "code/memory_config.py", "code/memory_embed.py", "code/memory_llm.py",
    "code/memory_store.py", "code/memory_service.py", "code/memory_routes.py",
    "code/memory_probes.yaml", "code/file_memory.py", "code/file_memory_chat.py",
    "code/agent_check.py", "code/make_memory_fixture.py", "AGENT.md", "MEMORY.md",
]
REPORT_FILES = [
    "reports/hw06/RUN_LOG.txt", "reports/hw06/METRICS.md", "reports/hw06/AI_USE.md",
    "reports/hw06/raw/token_log.csv", "reports/hw06/raw/summary.json",
    "reports/hw06/raw/agent_md_verification.json",
    "reports/hw06/memory/MEMORY_original.md", "reports/hw06/memory/MEMORY_consolidated.md",
    "reports/hw06/memory/consolidation_log.md",
]


def eviction_data():
    cands = list(RAW.glob("eviction_compression_comparison.*"))
    assert cands, "no eviction_compression_comparison file in raw/"
    return cands[0].name


def token_data():
    lines = (RAW / "token_log.csv").read_text().splitlines()
    assert len(lines) > 30, f"only {len(lines)} lines in token_log.csv"
    header = lines[0].split(",")
    need = {"prompt_tokens", "completion_tokens", "latency_ms", "short_term_n", "policy"}
    assert need <= set(header), "token_log.csv is missing columns: " + ", ".join(sorted(need - set(header)))
    runs = list(RAW.glob("run_*.json"))
    assert runs, "no run_*.json files in raw/"
    return f"{len(lines) - 1} logged calls, {len(runs)} run files"


def probes_file():
    import yaml
    text = (CODE / "memory_probes.yaml").read_text()
    data = yaml.safe_load(text)
    probes = data["probes"] if isinstance(data, dict) and "probes" in data else data
    assert len(probes) >= 5, f"{len(probes)} probes found, need 5"
    return f"{len(probes)} probes"


# ------------------------------------------------------------------ file memory checks

def agent_md():
    text = (ROOT / "AGENT.md").read_text()
    sections, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = 0
        elif current and re.match(r"-\s*\[[A-Z]\d+\]", line.strip()):
            sections[current] += 1
    total = sum(sections.values())
    cats = [k for k, v in sections.items() if v]
    assert total >= 5, f"{total} instructions, need at least 5"
    assert len(cats) >= 3, f"{len(cats)} categories, need at least 3"
    return f"{total} instructions in {len(cats)} categories"


def memory_files():
    import file_memory as fm
    original = (HW / "memory" / "MEMORY_original.md").read_text()
    consolidated = (HW / "memory" / "MEMORY_consolidated.md").read_text()
    n_orig = len(original.splitlines())
    n_cons = len([ln for ln in consolidated.splitlines()])
    assert n_orig == 55, f"original has {n_orig} lines, expected 55"
    assert n_cons < 40, f"consolidated has {n_cons} lines, expected fewer than 40"
    needed, reasons = fm.needs_consolidation(original)
    assert needed, "the 55-line original did not trigger consolidation"
    return f"{n_orig} -> {n_cons} lines; trigger fired: {reasons[0]}"


def system_prompt():
    import file_memory as fm
    prompt = fm.load_system_prompt()
    assert "AGENT.md" in prompt or "[C1]" in prompt, "AGENT.md text is not in the system prompt"
    assert "MEMORY" in prompt.upper(), "MEMORY.md text is not in the system prompt"
    return f"{len(prompt)} characters"


def offline_tests():
    for name in ("test_memory.py", "test_file_memory.py"):
        out = subprocess.run([sys.executable, name], cwd=CODE, capture_output=True, text=True, timeout=300)
        assert out.returncode == 0, f"{name} failed: " + (out.stdout + out.stderr)[-300:]
    return "test_memory.py and test_file_memory.py pass"


# ------------------------------------------------------------------ live checks

def api_up():
    try:
        return requests.get(f"{API}/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


def health():
    r = requests.get(f"{API}/health", timeout=5)
    assert r.status_code == 200, f"/health returned {r.status_code}"
    body = r.json()
    assert body.get("status") == "ok", f"unexpected body {body}"
    assert body.get("mongo") in (True, "ok"), f"MongoDB not reachable: {body}"
    return f"port {PORT_BASE}, db {body.get('db')}"


def collections():
    from pymongo import MongoClient
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)[DB_NAME]
    names = set(db.list_collection_names())
    need = {"listing_docs", "messages", "summaries", "episodes"}
    assert need <= names, "missing collections: " + ", ".join(sorted(need - names))
    opts = db.command("listCollections", filter={"name": "listing_docs"})["cursor"]["firstBatch"][0]
    assert "$jsonSchema" in opts.get("options", {}).get("validator", {}), "listing_docs has no $jsonSchema validator"
    return f"{DB_NAME}: " + ", ".join(sorted(need)) + "; validator present"


def crud_and_validation():
    base = f"{API}/api/listing-docs"
    good = {"title": "verify_hw06 temp listing", "property_type": "studio", "available_from": "2026-12-01"}
    r = requests.post(base, json=good, timeout=10)
    assert r.status_code == 201, f"create returned {r.status_code}"
    doc_id = r.json()["id"]
    try:
        assert requests.get(f"{base}/{doc_id}", timeout=10).status_code == 200, "read failed"
        u = requests.put(f"{base}/{doc_id}", json={"status": "pending"}, timeout=10)
        assert u.status_code == 200 and u.json()["status"] == "pending", "update failed"
        bad = requests.post(base, json={"title": "", "property_type": "castle", "available_from": "nope"}, timeout=10)
        assert bad.status_code == 422, f"invalid body returned {bad.status_code}, expected 422"
        wrong = requests.post(base, data="x", headers={"Content-Type": "text/plain"}, timeout=10)
        assert wrong.status_code == 415, f"non-JSON content type returned {wrong.status_code}, expected 415"
    finally:
        requests.delete(f"{base}/{doc_id}", timeout=10)
    assert requests.get(f"{base}/{doc_id}", timeout=10).status_code == 404, "deleted document still readable"
    return "create 201, read 200, update 200, invalid 422, non-JSON 415, delete then 404"


def cors():
    r = requests.options(f"{API}/api/listing-docs", timeout=5, headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" in {k.lower() for k in r.headers}, "no CORS header returned"
    return "CORS header present"


def ollama_model():
    tags = requests.get("http://localhost:11434/api/tags", timeout=5).json()
    names = [m.get("name", "") for m in tags.get("models", [])]
    assert any(n.startswith(LLM_MODEL) for n in names), f"{LLM_MODEL} not found in Ollama: {names}"
    return f"{LLM_MODEL} available"


def chat_reply():
    body = {"user_id": "verify_hw06", "message": "Hello, please reply with one short sentence.", "persist": False}
    r = requests.post(f"{API}/api/chat", json=body, timeout=300)
    assert r.status_code == 200, f"POST /api/chat returned {r.status_code}: {r.text[:200]}"
    out = r.json()
    assert isinstance(out.get("reply"), str) and out["reply"].strip(), "empty reply"
    assert out.get("session_id"), "no session_id returned"
    usage = out.get("usage", {})
    assert usage.get("prompt_tokens", 0) > 0 and usage.get("completion_tokens", 0) > 0, f"no token counts: {usage}"
    assert usage.get("latency_ms", 0) > 0, "no latency recorded"
    return f"reply of {len(out['reply'])} chars; {usage['prompt_tokens']} prompt / {usage['completion_tokens']} completion tokens"


def memory_endpoints():
    m = requests.get(f"{API}/api/memory/verify_hw06", timeout=10)
    a = requests.get(f"{API}/api/aggregate/verify_hw06", timeout=10)
    assert m.status_code == 200, f"/api/memory returned {m.status_code}"
    assert a.status_code == 200, f"/api/aggregate returned {a.status_code}"
    return "GET /api/memory and GET /api/aggregate return 200"


def main():
    server = None
    try:
        check("code, AGENT.md and MEMORY.md files present", files_exist(CODE_FILES))
        check("report, raw-data and memory files present", files_exist(REPORT_FILES))
        check("token log has per-call token and latency data", token_data)
        check("eviction/compression comparison data present", eviction_data)
        check("memory_probes.yaml has 5 probes", probes_file)
        check("AGENT.md has 5+ instructions in 3+ categories", agent_md)
        check("AGENT.md and MEMORY.md are in the system prompt", system_prompt)
        check("55-line original triggers consolidation; result is under 40 lines", memory_files)
        check("offline test suites pass", offline_tests)

        if not api_up():
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "hw6_main:app", "--port", str(PORT_BASE)],
                cwd=CODE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                time.sleep(0.5)
                if api_up():
                    break
        check("FastAPI responds on PORT_BASE and MongoDB is reachable", health)
        check("MongoDB collections exist and listing_docs has a validator", collections)
        check("document CRUD works; invalid data gives 422; non-JSON gives 415", crud_and_validation)
        check("CORS headers are returned", cors)
        check("local Ollama model is available", ollama_model)
        check("POST /api/chat returns a reply with token counts", chat_reply)
        check("memory and aggregate endpoints respond", memory_endpoints)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    output = {
        "homework": "HW6",
        "sid4": SID4,
        "commit_hash": git("rev-parse", "HEAD"),
        "model_config": {"llm": LLM_MODEL, "reasoning": False, "port_base": PORT_BASE,
                         "prefix": PREFIX, "domain_id": DOMAIN_ID, "database": DB_NAME},
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