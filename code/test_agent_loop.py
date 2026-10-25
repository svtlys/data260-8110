"""Offline tests for agent_loop.py and agent_cases.py (no model, no database)."""

import json

from agent_cases import (
    build_cases_from_rows, call_slots, check_case, make_attempt_record, summarize_reliability,
    unsupported_claims,
)
from agent_loop import MAX_FAILED_REPAIRS, FaultInjectingModel, MockModel, classify_tool_error, run_agent

ROWS = [
    {"id": 1, "address": "10 Oak Street", "listing_code": "SJ-1001", "available_units": 2, "landlord_id": 1},
    {"id": 2, "address": "22 Oak Avenue", "listing_code": "SJ-1002", "available_units": 5, "landlord_id": 1},
    {"id": 3, "address": "5 Elm Street", "listing_code": "SJ-1003", "available_units": 1, "landlord_id": 2},
]
NAMES = {1: "Ann Owner", 2: "Bob Owner"}


def _ok(data):
    return {"ok": True, "data": data, "error": None}


def fake_registry(rows=ROWS):
    """Three fake tools over ROWS with the same names and signatures as the real ones."""

    def search_listings(query, limit=10):
        hits = [r for r in rows if query.lower() in r["address"].lower()][:limit]
        return _ok({"count": len(hits), "results": hits})

    def get_listing_detail(listing_id):
        for r in rows:
            if r["id"] == listing_id:
                return _ok({**r, "landlord": {"name": NAMES.get(r["landlord_id"])}})
        return {"ok": False, "data": None, "error": f"listing {listing_id} not found"}

    def aggregate_landlord_stats(landlord_id):
        mine = [r for r in rows if r["landlord_id"] == landlord_id]
        return _ok({"landlord_id": landlord_id, "listing_count": len(mine),
                    "total_available_units": sum(r["available_units"] for r in mine)})

    return {"search_listings": search_listings, "get_listing_detail": get_listing_detail,
            "aggregate_landlord_stats": aggregate_landlord_stats}


def call(tool, **inputs):
    return json.dumps({"action": "call_tool", "tool": tool, "inputs": inputs})


def final(text):
    return json.dumps({"action": "final", "answer": text})


def run(replies, **kw):
    model = MockModel(replies)
    result = run_agent("question", model=model, registry=fake_registry(), log_path=None, **kw)
    return result, model


def test_two_step_run_appends_tool_role_messages():
    result, model = run([call("search_listings", query="Oak"), call("get_listing_detail", listing_id=1),
                         final("SJ-1001")])
    assert result["stop_reason"] == "final_answer" and result["tool_calls"] == 2
    roles = [m["role"] for m in model.seen[-1]]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert model.seen[-1][3]["name"] == "search_listings"


def test_unknown_tool_is_reprompted_once_then_recovers():
    result, model = run([call("drop_table", x=1), call("search_listings", query="Oak"), final("done")])
    assert result["stop_reason"] == "final_answer" and result["failed_repairs"] == 0
    assert "unknown tool" in model.seen[1][-1]["content"]
    assert call_slots(result) == [{"first_kind": "unknown_tool", "first_ok": False, "after_ok": True}]


def test_repair_slot_counts_as_well_formed_after_repair():
    result, _ = run([call("get_listing_detail", id=1), call("get_listing_detail", listing_id=1),
                     final("ok")])
    slots = call_slots(result)
    assert slots == [{"first_kind": "malformed_arguments", "first_ok": False, "after_ok": True}]


def test_failed_repairs_stop_the_run_cleanly():
    result, model = run(["not json at all"])
    assert result["stop_reason"] == "repair_failed"
    assert result["failed_repairs"] == MAX_FAILED_REPAIRS
    assert model.calls == 2 * MAX_FAILED_REPAIRS


def test_step_ceiling_stops_a_loop():
    result, _ = run([call("search_listings", query="Oak")], max_steps=3)
    assert result["stop_reason"] == "max_steps" and result["tool_calls"] == 3


def test_nonexistent_id_gives_useful_message_and_no_crash():
    result, _ = run([call("get_listing_detail", listing_id=999), final("Listing 999 was not found.")])
    assert result["stop_reason"] == "final_answer"
    assert "not found" in result["trace"][0]["result"]["error"]
    assert classify_tool_error(result["trace"][0]["result"]["error"]) is None


def test_cases_are_built_from_data_and_verifier_passes_a_correct_run():
    cases = build_cases_from_rows(ROWS, NAMES)
    by_id = {c["id"]: c for c in cases["cases"]}
    assert set(by_id) == {"A", "B", "C"} and len(by_id["C"]["required"]) == 3
    good, _ = run([call("search_listings", query=cases["term"]), call("get_listing_detail", listing_id=1),
                   final("Listing SJ-1001 at 10 Oak Street, landlord Ann Owner.")])
    assert check_case(by_id["A"], good)["passed"]


def test_verifier_rejects_a_lost_chain_and_flags_unsupported_codes():
    cases = build_cases_from_rows(ROWS, NAMES)
    case_a = cases["cases"][0]
    short, _ = run([call("search_listings", query=cases["term"]), final("It is SJ-9999.")])
    check = check_case(case_a, short)
    assert not check["passed"] and not check["chain_ok"]
    assert unsupported_claims(short) == ["SJ-9999"]
    record = make_attempt_record(0, case_a, short)
    assert "lost_multistep_chain" in record["failure_types"]


def test_text_instead_of_tool_is_classified_and_summarized():
    cases = build_cases_from_rows(ROWS, NAMES)
    direct, _ = run([final("SJ-1001")])
    record = make_attempt_record(0, cases["cases"][0], direct)
    assert "text_instead_of_tool" in record["failure_types"]
    summary = summarize_reliability([record])
    assert summary["failures_after_repair"]["text_instead_of_tool"] == 1
    assert summary["rate_before_repair_pct"] == 0.0


def test_empty_input_is_invalid_not_a_crash():
    result = run_agent("   ", model=MockModel("x"), registry=fake_registry(), log_path=None)
    assert result["stop_reason"] == "invalid_input" and result["tool_calls"] == 0


def test_fault_injection_is_repaired_and_counted():
    inner = MockModel([call("get_listing_detail", listing_id=1)] * 3 + [final("done")])
    model = FaultInjectingModel(inner, rate=1.0, seed=3)
    result = run_agent("q", model=model, registry=fake_registry(), log_path=None)
    assert model.injected and result["failed_repairs"] >= 1
    kinds = {e["kind"] for e in result["events"]}
    assert kinds & {"unknown_tool", "malformed_arguments", "text_instead_of_tool"}


def test_fault_injection_rate_zero_changes_nothing():
    inner = MockModel([call("search_listings", query="Oak"), final("ok")])
    model = FaultInjectingModel(inner, rate=0.0, seed=1)
    result = run_agent("q", model=model, registry=fake_registry(), log_path=None)
    assert model.injected == [] and result["tool_calls"] == 1