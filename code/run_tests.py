import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import MockModel, run_agent  # noqa: E402
from tool_executor import SAFETY_PREFIX, execute_tool  # noqa: E402

TESTS = []


def test(needs_db: bool = False):
    def register(fn):
        fn.needs_db = needs_db
        TESTS.append(fn)
        return fn

    return register


def call(name, inputs, **kwargs) -> dict:
    """Call execute_tool and check the envelope shape every time."""
    raw = execute_tool(name, inputs, **kwargs)
    assert isinstance(raw, str), "execute_tool must return a JSON string"
    envelope = json.loads(raw)
    assert set(envelope) == {"ok", "data", "error"}, f"unexpected keys: {sorted(envelope)}"
    return envelope


def make_db() -> SimpleNamespace:
    """A fresh in-memory SQLite database with the real models and three listings."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db import Base
    from models import Landlord, Listing

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    landlord = Landlord(name="Felix Realty", contact_info="555-0100", email="felix@example.com")
    session.add(landlord)
    session.flush()
    listings = [
        Listing(address="100 Main St, San Jose, CA", available_units=2, landlord_id=landlord.id),
        Listing(address="200 Oak Ave, San Jose, CA", available_units=4, landlord_id=landlord.id),
        Listing(address="300 Main St, Santa Clara, CA", available_units=1, landlord_id=None),
    ]
    session.add_all(listings)
    session.commit()
    return SimpleNamespace(
        session=session, landlord_id=landlord.id, listing_ids=[l.id for l in listings]
    )


def fake_search(query, limit=10, db=None):
    return {"ok": True, "data": {"echo": query, "limit": limit}, "error": None}


def fake_raises(x, db=None):
    raise RuntimeError("boom")


def fake_malformed(x, db=None):
    return "this is not an envelope"


FAKE_REGISTRY = {
    "fake_search": fake_search,
    "fake_raises": fake_raises,
    "fake_malformed": fake_malformed,
}


@test()
def test_unknown_tool_is_rejected():
    """[fake tools] an unknown tool name returns ok=false and lists the real tools"""
    result = call("delete_everything", {}, registry=FAKE_REGISTRY)
    assert result["ok"] is False and result["data"] is None
    assert "unknown tool" in result["error"]


@test()
def test_inputs_must_be_an_object():
    """[fake tools] inputs that are not a JSON object are rejected, not crashed on"""
    for bad in (None, ["x"], "query=main", 5):
        result = call("fake_search", bad, registry=FAKE_REGISTRY)
        assert result["ok"] is False, f"{bad!r} should be rejected"
        assert "JSON object" in result["error"]


@test()
def test_unexpected_and_reserved_inputs_are_rejected():
    """[fake tools] unknown argument names and the reserved 'db' argument are rejected"""
    result = call("fake_search", {"query": "x", "bogus": 1}, registry=FAKE_REGISTRY)
    assert result["ok"] is False and "unexpected input(s): bogus" in result["error"]
    result = call("fake_search", {"query": "x", "db": "hack"}, registry=FAKE_REGISTRY)
    assert result["ok"] is False and "'db' is not an allowed input" in result["error"]


@test()
def test_missing_required_input_is_rejected():
    """[fake tools] a missing required argument is rejected with its name"""
    result = call("fake_search", {"limit": 3}, registry=FAKE_REGISTRY)
    assert result["ok"] is False and "missing required input(s): query" in result["error"]


@test()
def test_tool_crash_becomes_a_clean_error():
    """[fake tools] a tool that raises does not crash execute_tool"""
    result = call("fake_raises", {"x": 1}, registry=FAKE_REGISTRY)
    assert result["ok"] is False
    assert "internal error" in result["error"] and "RuntimeError" in result["error"]


@test()
def test_malformed_tool_result_becomes_a_clean_error():
    """[fake tools] a tool that returns something other than an envelope is rejected"""
    result = call("fake_malformed", {"x": 1}, registry=FAKE_REGISTRY)
    assert result["ok"] is False and "invalid result" in result["error"]


@test()
def test_valid_call_returns_the_envelope_as_a_json_string():
    """[fake tools] a valid call returns a JSON string {ok: true, data, error: null}"""
    raw = execute_tool("fake_search", {"query": "Main"}, registry=FAKE_REGISTRY)
    assert isinstance(raw, str)
    assert json.loads(raw) == {"ok": True, "data": {"echo": "Main", "limit": 10}, "error": None}


@test(needs_db=True)
def test_search_listings_valid():
    """[real tools] search_listings finds matching addresses, case-insensitively"""
    fx = make_db()
    result = call("search_listings", {"query": "main", "limit": 5}, db=fx.session)
    assert result["ok"] is True and result["error"] is None
    assert result["data"]["count"] == 2
    assert all("Main St" in r["address"] for r in result["data"]["results"])


@test(needs_db=True)
def test_search_listings_blank_query_rejected():
    """[real tools] search_listings rejects a blank query (Part 3 rejected call 1)"""
    fx = make_db()
    result = call("search_listings", {"query": " ", "limit": 5}, db=fx.session)
    assert result["ok"] is False and result["data"] is None
    assert result["error"] == "query must be a non-empty string"


@test(needs_db=True)
def test_get_listing_detail_valid():
    """[real tools] get_listing_detail returns the listing and its landlord"""
    fx = make_db()
    result = call("get_listing_detail", {"listing_id": fx.listing_ids[0]}, db=fx.session)
    assert result["ok"] is True
    assert result["data"]["id"] == fx.listing_ids[0]
    assert result["data"]["landlord"]["name"] == "Felix Realty"


@test(needs_db=True)
def test_get_listing_detail_not_found_rejected():
    """[real tools] get_listing_detail reports an unknown id (Part 3 rejected call 2)"""
    fx = make_db()
    result = call("get_listing_detail", {"listing_id": 99999999}, db=fx.session)
    assert result["ok"] is False and result["data"] is None
    assert result["error"] == "listing 99999999 not found"


@test(needs_db=True)
def test_aggregate_landlord_stats_valid():
    """[real tools] aggregate_landlord_stats counts listings and sums units"""
    fx = make_db()
    result = call("aggregate_landlord_stats", {"landlord_id": fx.landlord_id}, db=fx.session)
    assert result["ok"] is True
    assert result["data"]["listing_count"] == 2
    assert result["data"]["total_available_units"] == 6
    assert result["data"]["average_available_units"] == 3.0


@test(needs_db=True)
def test_aggregate_landlord_stats_zero_id_rejected():
    """[real tools] aggregate_landlord_stats rejects id 0 (Part 3 rejected call 3)"""
    fx = make_db()
    result = call("aggregate_landlord_stats", {"landlord_id": 0}, db=fx.session)
    assert result["ok"] is False and result["data"] is None
    assert result["error"] == "landlord_id must be >= 1"


@test(needs_db=True)
def test_transient_storage_failure_is_retried():
    """[real tools] one injected storage failure is retried and the call still succeeds"""
    import domain_tools5
    from resilience import ScriptedFaults

    fx = make_db()
    faults = ScriptedFaults([True])
    domain_tools5.set_fault_hook(faults)
    try:
        result = call("get_listing_detail", {"listing_id": fx.listing_ids[0]}, db=fx.session)
    finally:
        domain_tools5.set_fault_hook(None)
    assert result["ok"] is True
    assert faults.attempts == 2, f"expected 2 attempts, got {faults.attempts}"


@test()
def test_safety_rule_blocks_wildcard_search():
    """[safety] a wildcard-only search is blocked before the tool runs; a normal search is allowed"""
    calls = []

    def tracked_search(query, limit=10, db=None):
        calls.append(query)
        return {"ok": True, "data": {"count": 0, "results": []}, "error": None}

    registry = {"search_listings": tracked_search}

    blocked = call("search_listings", {"query": "%"}, registry=registry)
    assert blocked["ok"] is False and blocked["data"] is None
    assert blocked["error"].startswith(SAFETY_PREFIX), blocked["error"]
    assert calls == [], "the tool must not run when the safety rule blocks the call"

    allowed = call("search_listings", {"query": "Main"}, registry=registry)
    assert allowed["ok"] is True and calls == ["Main"]


@test()
def test_agent_stops_at_max_steps():
    """[agent] run_agent with a MockModel that never finishes stops at max_steps"""
    model = MockModel('{"action": "call_tool", "tool": "fake_search", "inputs": {"query": "x"}}')
    with tempfile.TemporaryDirectory() as folder:
        log_path = Path(folder) / "runs.jsonl"
        result = run_agent("find x", model=model, max_steps=3,
                           registry=FAKE_REGISTRY, log_path=log_path)
        records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert result["stop_reason"] == "max_steps"
    assert result["steps"] == 3 and result["tool_calls"] == 3 and model.calls == 3
    assert records[-1]["type"] == "stop" and records[-1]["stop_reason"] == "max_steps"


def run(include_db_tests: bool = True) -> int:
    logging.disable(logging.CRITICAL)  # keep the PASS/FAIL output readable
    selected = [t for t in TESTS if include_db_tests or not t.needs_db]
    passed = 0
    for t in selected:
        description = (t.__doc__ or t.__name__).strip()
        try:
            t()
            print(f"PASS  {t.__name__}\n        {description}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL  {t.__name__}\n        {description}\n        assertion failed: {exc}")
        except Exception as exc:  # a setup problem, not a failed assertion
            print(f"FAIL  {t.__name__}\n        {description}\n        {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(selected)} tests passed")
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    sys.exit(run(include_db_tests="--no-db" not in sys.argv))