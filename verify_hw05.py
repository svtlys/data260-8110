import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CODE = ROOT / "code"
REACT = CODE / "web_application_react"
RAW = ROOT / "reports/hw05/raw"
sys.path.insert(0, str(CODE))

SID4 = "8110"
PORT_BASE = 8000 + (int(SID4) % 900)
PREFIX = "s" + SID4
SEED = int(SID4)
VERIFY_SEED = 260000 + int(SID4)
DOMAIN_ID = int(SID4) % 8
LLM_MODEL = "qwen3:8b"
API = f"http://localhost:{PORT_BASE}"
TEST_USER = {"email": "landlord@example.com", "password": "rentals123"}  # seeded test account

checks = []


def check(name, fn):
    try:
        detail, passed = (fn() or ""), True
    except AssertionError as exc:
        detail, passed = str(exc), False
    except Exception as exc:  # a broken environment should fail a check, not crash the script
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

CODE_FILES = [
    "code/main.py", "code/db.py", "code/models.py", "code/schemas.py", "code/api_routes.py",
    "code/migrate_hw05.py", "code/meals_server.py", "code/domain_mcp_server.py",
    "code/domain_tools5.py", "code/resilience.py", "code/part3_experiments.py",
    "code/tool_executor.py", "code/agent.py", "code/run_tests.py", "code/part5_experiments.py",
    "code/web_application_react/src/store/listingsSlice.js",
    "code/web_application_react/src/store/store.js",
    "code/web_application_react/src/components/Home.jsx",
    "code/web_application_react/src/components/CreateRecord.jsx",
    "code/web_application_react/src/components/UpdateRecord.jsx",
    "code/web_application_react/src/components/DeleteRecord.jsx",
]
REPORT_FILES = [
    "reports/hw05/RUN_LOG.txt", "reports/hw05/METRICS.md", "reports/hw05/AI_USE.md",
    "reports/hw05/REFLECTION.md",
    "reports/hw05/raw/mcp_tool_outputs.json", "reports/hw05/raw/retry_demo.json",
    "reports/hw05/raw/fault_injection_results.json", "reports/hw05/raw/fault_injection_results.csv",
    "reports/hw05/raw/fault_injection_summary.json", "reports/hw05/raw/safety_rule_demo.json",
    "reports/hw05/raw/agent_runs.jsonl", "reports/hw05/raw/agent_scenarios_summary.json",
]


def files_exist(paths):
    def run():
        missing = [p for p in paths if not (ROOT / p).is_file() or (ROOT / p).stat().st_size == 0]
        assert not missing, "missing or empty: " + ", ".join(missing)
        return f"{len(paths)} files present"
    return run


def redux_setup():
    package = json.loads((REACT / "package.json").read_text())
    deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    absent = [d for d in ("@reduxjs/toolkit", "react-redux", "axios") if d not in deps]
    assert not absent, "package.json is missing: " + ", ".join(absent)
    text = (REACT / "src/store/listingsSlice.js").read_text()
    thunks = ["fetchListings", "createListing", "updateListing", "deleteListing"]
    missing = [t for t in thunks if f"export const {t}" not in text]
    assert not missing, "slice is missing thunks: " + ", ".join(missing)
    return "Redux Toolkit, react-redux, axios installed; 4 thunks exported"


def no_stdout_prints():
    names = ["meals_server.py", "domain_mcp_server.py", "domain_tools.py", "domain_tools5.py"]
    offenders = []
    for name in names:
        path = CODE / name
        if path.is_file():
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if re.match(r"\s*print\(", line):
                    offenders.append(f"{name}:{number}")
    assert not offenders, "print() found (corrupts the STDIO stream): " + ", ".join(offenders)
    return "no print() calls in the MCP server modules"


# ---------------------------------------------------------------- database check

def schema():
    from sqlalchemy import inspect

    from db import engine

    insp = inspect(engine)
    tables = insp.get_table_names()
    assert "landlords" in tables and "listings" in tables, f"tables found: {sorted(tables)}"

    def columns(table):
        return {c["name"] for c in insp.get_columns(table)}

    def unique_on(table, column):
        indexed = any(i.get("unique") and i["column_names"] == [column] for i in insp.get_indexes(table))
        constrained = any(u["column_names"] == [column] for u in insp.get_unique_constraints(table))
        return indexed or constrained

    need_landlord = {"id", "name", "contact_info", "email", "created_at", "updated_at"}
    need_listing = {"id", "address", "listing_code", "available_units", "landlord_id",
                    "created_at", "updated_at"}
    assert need_landlord <= columns("landlords"), f"landlords lacks {sorted(need_landlord - columns('landlords'))}"
    assert need_listing <= columns("listings"), f"listings lacks {sorted(need_listing - columns('listings'))}"
    assert unique_on("landlords", "email"), "landlords.email is not unique"
    assert unique_on("listings", "listing_code"), "listings.listing_code is not unique"
    has_fk = any(
        fk["constrained_columns"] == ["landlord_id"] and fk["referred_table"] == "landlords"
        for fk in insp.get_foreign_keys("listings")
    )
    assert has_fk, "listings.landlord_id is not a foreign key to landlords"
    return "landlords and listings have the required columns, unique fields and foreign key"


# --------------------------------------------------------------------- FastAPI

def api_up():
    try:
        requests.get(f"{API}/api/me", timeout=3)
        return True
    except requests.RequestException:
        return False


def run_api_checks():
    def responds():
        r = requests.get(f"{API}/api/me", timeout=5)
        assert r.status_code in (200, 401), f"HTTP {r.status_code}"
        return f"HTTP {r.status_code}"

    check(f"FastAPI responds on port {PORT_BASE}", responds)
    session = requests.Session()

    def unauthenticated():
        r = requests.get(f"{API}/api/landlords", timeout=5)
        assert r.status_code == 401, f"HTTP {r.status_code}"

    def login():
        r = session.post(f"{API}/api/login", json=TEST_USER, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert "httponly" in r.headers.get("set-cookie", "").lower(), "cookie is not HttpOnly"
        token = session.cookies.get("session_token", "")
        assert token and "@" not in token, "session cookie is not an opaque token"

    def landlord_list():
        r = session.get(f"{API}/api/landlords", params={"page": 1, "page_size": 2}, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert isinstance(body, list) and len(body) <= 2, "pagination not applied"
        return f"{len(body)} landlord(s) on the page"

    def listing_list():
        r = session.get(f"{API}/api/listings", params={"page": 1, "page_size": 5}, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        rows = r.json()
        assert rows and len(rows) <= 5, "expected between 1 and 5 listings"
        keys = {"id", "address", "landlord_id", "listing_code", "available_units",
                "created_at", "updated_at"}
        assert keys <= set(rows[0]), f"missing keys: {sorted(keys - set(rows[0]))}"

    def invalid_email():
        r = session.post(f"{API}/api/landlords",
                         json={"name": "X", "contact_info": "Y", "email": "not-an-email"}, timeout=10)
        assert r.status_code == 422, f"expected 422, got {r.status_code}"

    def missing_landlord():
        r = session.get(f"{API}/api/landlords/99999999/listings", timeout=10)
        assert r.status_code == 404, f"expected 404, got {r.status_code}"

    def delete_blocked():
        r = session.get(f"{API}/api/landlords", params={"page": 1, "page_size": 100}, timeout=10)
        for landlord in r.json():
            owned = session.get(f"{API}/api/landlords/{landlord['id']}/listings", timeout=10).json()
            if owned:
                d = session.delete(f"{API}/api/landlords/{landlord['id']}", timeout=10)
                assert d.status_code == 409, f"expected 409, got {d.status_code}"
                return f"landlord {landlord['id']} with {len(owned)} listing(s) was protected"
        raise AssertionError("no landlord with listings found to test")

    check("unauthenticated request is rejected (401)", unauthenticated)
    check("login succeeds with an HttpOnly opaque session cookie", login)
    check("landlord list is paginated", landlord_list)
    check("listing list returns the new schema fields", listing_list)
    check("invalid landlord email is rejected (422)", invalid_email)
    check("relationship query for an unknown landlord returns 404", missing_landlord)
    check("deleting a landlord that still has listings is blocked (409)", delete_blocked)
    session.post(f"{API}/api/logout", timeout=5)


# ------------------------------------------------------------------ MCP servers

def envelope_from(result):
    """Pull the {ok, data, error} envelope out of an MCP tool result (object or saved dict)."""
    data = result if isinstance(result, dict) else result.model_dump(mode="json")
    payload = data.get("structuredContent")
    if payload is None:
        for item in data.get("content") or []:
            try:
                payload = json.loads(item.get("text", ""))
                break
            except ValueError:
                continue
    return payload if isinstance(payload, dict) else None


async def probe(script, calls):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[script], cwd=str(CODE),
                                   env=dict(os.environ))
    out = {"tools": [], "calls": []}
    with open(os.devnull, "w") as quiet:
        async with stdio_client(params, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["tools"] = sorted(t.name for t in (await session.list_tools()).tools)
                for name, arguments in calls:
                    result = await session.call_tool(name, arguments)
                    out["calls"].append(result.model_dump(mode="json"))
    return out


def run_probe(script, calls):
    try:
        return asyncio.run(asyncio.wait_for(probe(script, calls), timeout=90))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_mcp_checks():
    meals = run_probe("meals_server.py", [("search_meals_by_name", {"query": "Arrabiata", "limit": 1})])
    domain = run_probe("domain_mcp_server.py", [
        ("search_listings", {"query": "Main", "limit": 1}),
        ("search_listings", {"query": " ", "limit": 5}),
        ("get_listing_detail", {"listing_id": 99999999}),
        ("aggregate_landlord_stats", {"landlord_id": 0}),
    ])

    def usable(probed):
        assert "error" not in probed, probed.get("error")
        return probed

    def meals_tools():
        names = usable(meals)["tools"]
        expected = ["meal_details", "meals_by_ingredient", "random_meal", "search_meals_by_name"]
        assert names == expected, f"tools: {names}"
        return "meals server started and lists 4 tools"

    def meals_call():
        result = usable(meals)["calls"][0]
        assert result["isError"] is False and result["content"], "tool call returned an error or no content"
        return "search_meals_by_name returned a result (needs internet)"

    def domain_tools_listed():
        names = usable(domain)["tools"]
        expected = ["aggregate_landlord_stats", "get_listing_detail", "search_listings"]
        assert names == expected, f"tools: {names}"
        return "domain server started and lists exactly 3 tools"

    def domain_valid_call():
        env = envelope_from(usable(domain)["calls"][0])
        assert env and env["ok"] is True and env["error"] is None, f"envelope: {env}"
        assert env["data"]["count"] >= 1, "search returned no listings"
        return "search_listings returned ok=true with data"

    def domain_rejections():
        for index, label in ((1, "blank query"), (2, "unknown listing"), (3, "landlord id 0")):
            env = envelope_from(usable(domain)["calls"][index])
            assert env and env["ok"] is False and env["data"] is None, f"{label}: {env}"
            assert isinstance(env["error"], str) and env["error"], f"{label}: no error text"
        return "3 invalid calls returned {ok: false, data: null, error: <text>}"

    def saved_inspector_outputs():
        saved = json.loads((RAW / "mcp_tool_outputs.json").read_text())
        server = next(s for s in saved["servers"] if s["server"] == "domain_mcp_server.py")
        assert len(server["calls"]) == 6, f"{len(server['calls'])} saved domain calls"
        for entry in server["calls"]:
            env = envelope_from(entry["result"])
            want = entry["kind"] == "valid"
            assert env and env["ok"] is want, f"{entry['tool']} ({entry['kind']}): {env}"
        return "saved domain outputs: 3 valid ok=true, 3 invalid ok=false"

    check("meals MCP server starts and lists its four tools", meals_tools)
    check("meals MCP server answers a tool call", meals_call)
    check("domain MCP server starts and lists exactly three tools", domain_tools_listed)
    check("domain MCP tool call succeeds with the envelope", domain_valid_call)
    check("domain MCP rejected calls use the envelope", domain_rejections)
    check("saved MCP outputs match the expected valid/invalid pattern", saved_inspector_outputs)


# --------------------------------------------------------- retries and raw data

def fault_data():
    rows = json.loads((RAW / "fault_injection_results.json").read_text())
    assert len(rows) == 150, f"{len(rows)} rows"
    for rate in (0.0, 0.2, 0.5):
        count = sum(1 for r in rows if r["failure_rate"] == rate)
        assert count == 50, f"{count} calls at rate {rate}"
    assert all(r["ok"] for r in rows if r["failure_rate"] == 0.0), "a call failed at 0% injected failures"
    return "150 calls, 50 at each of 0%, 20%, 50%"


def fault_fingerprint():
    rows = json.loads((RAW / "fault_injection_results.json").read_text())
    summary = json.loads((RAW / "fault_injection_summary.json").read_text())
    sequence = "|".join(f"{r['failure_rate']}:{r['call']}:{r['ok']}:{r['attempts']}" for r in rows)
    fingerprint = hashlib.sha256(sequence.encode()).hexdigest()[:16]
    assert summary["verify_seed"] == VERIFY_SEED, f"summary seed {summary['verify_seed']}"
    assert fingerprint == summary["outcome_fingerprint"], "raw rows do not match the recorded fingerprint"
    return f"fingerprint {fingerprint} matches the summary"


def seed_is_reproducible():
    from resilience import FaultInjector, TransientError

    def sequence(rate):
        injector, out = FaultInjector(rate, VERIFY_SEED), []
        for _ in range(200):
            try:
                injector()
                out.append(False)
            except TransientError:
                out.append(True)
        return out

    assert sequence(0.2) == sequence(0.2), "same seed gave different sequences"
    assert not any(sequence(0.0)), "0% rate injected a failure"
    assert all(b for a, b in zip(sequence(0.2), sequence(0.5)) if a), "20% failures are not a subset of 50%"
    return f"seed {VERIFY_SEED} gives identical sequences"


# ----------------------------------------------------- tests, safety rule, agent

def offline_tests():
    proc = subprocess.run([sys.executable, "run_tests.py"], cwd=CODE, capture_output=True,
                          text=True, timeout=300)
    match = re.search(r"(\d+)/(\d+) tests passed", proc.stdout)
    assert match, "no summary line in the test output"
    passed, total = int(match.group(1)), int(match.group(2))
    assert proc.returncode == 0 and passed == total and total >= 8, \
        f"{passed}/{total} passed (exit code {proc.returncode})"
    return f"{passed}/{total} offline tests passed"


def safety_rule():
    from tool_executor import SAFETY_PREFIX, execute_tool

    calls = []

    def fake(query, limit=10, db=None):
        calls.append(query)
        return {"ok": True, "data": {}, "error": None}

    registry = {"search_listings": fake}
    blocked = json.loads(execute_tool("search_listings", {"query": "%"}, registry=registry))
    assert blocked["ok"] is False and blocked["data"] is None, f"blocked call returned {blocked}"
    assert str(blocked["error"]).startswith(SAFETY_PREFIX), "error does not name the safety rule"
    assert calls == [], "the tool ran even though the rule blocked the call"
    allowed = json.loads(execute_tool("search_listings", {"query": "Main"}, registry=registry))
    assert allowed["ok"] is True and calls == ["Main"], "a normal search was not allowed"
    return "wildcard search blocked without running the tool; normal search allowed"


def agent_logs():
    lines = [json.loads(l) for l in (RAW / "agent_runs.jsonl").read_text().splitlines() if l.strip()]
    starts = {l["run_id"]: l for l in lines if l["type"] == "start"}
    stops = [l for l in lines if l["type"] == "stop"]
    allowed = {"final_answer", "safety_block", "max_steps", "model_error", "invalid_input"}
    assert stops, "no stop records"
    assert all(s["stop_reason"] in allowed for s in stops), "unknown stop reason in the log"
    assert all(isinstance(s["steps"], int) and isinstance(s["tool_calls"], int) for s in stops), \
        "steps/tool_calls are not integers"
    scenarios = {s["scenario"] for s in stops if s.get("scenario")}
    assert len(scenarios) >= 4, f"{len(scenarios)} distinct scenarios logged"
    for s in stops:
        if s["stop_reason"] == "max_steps":
            assert s["steps"] == starts[s["run_id"]]["max_steps"], "max_steps run did not use its ceiling"
    summary = json.loads((RAW / "agent_scenarios_summary.json").read_text())
    assert len(summary) >= 4 and all({"stop_reason", "steps", "tool_calls"} <= set(r) for r in summary), \
        "scenario summary is incomplete"
    return f"{len(stops)} runs logged, {len(scenarios)} scenarios, {len(summary)} in the summary"


def ollama_model():
    proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0 and LLM_MODEL in proc.stdout, f"{LLM_MODEL} is not available in Ollama"
    return f"{LLM_MODEL} available"


# ------------------------------------------------------------------------ main

def main():
    server = None
    try:
        check("code and React files present", files_exist(CODE_FILES))
        check("report and raw-data files present", files_exist(REPORT_FILES))
        check("Redux Toolkit client is set up", redux_setup)
        check("MCP server modules never print to stdout", no_stdout_prints)
        check("database schema has the related entity, unique fields and foreign key", schema)

        if not api_up():
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT_BASE)],
                cwd=CODE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                time.sleep(0.5)
                if api_up():
                    break
        run_api_checks()
        run_mcp_checks()

        check("fault-injection raw data has 150 calls, 50 per rate", fault_data)
        check("recorded outcome fingerprint matches the raw rows", fault_fingerprint)
        check("VERIFY_SEED reproduces the same failure sequence", seed_is_reproducible)
        check("offline test suite passes", offline_tests)
        check("safety rule blocks a bulk wildcard search", safety_rule)
        check("agent log covers 4+ scenarios with valid stop reasons", agent_logs)
        check("local Ollama model is available", ollama_model)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    try:
        mcp_version = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        mcp_version = "unknown"
    output = {
        "homework": "HW5",
        "sid4": SID4,
        "commit_hash": git("rev-parse", "HEAD"),
        "model_config": {"llm": LLM_MODEL, "temperature": 0.0, "mcp_sdk_version": mcp_version,
                         "port_base": PORT_BASE, "prefix": PREFIX, "domain_id": DOMAIN_ID},
        "seed": SEED,
        "verify_seed": VERIFY_SEED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c["passed"]),
        "failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    out_path = ROOT / "reports/hw05/verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\n{output['passed']}/{output['total_checks']} checks passed.")
    print(f"Commit hash recorded: {output['commit_hash']}")
    print(f"Results written to {out_path}")
    return 0 if output["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())