import json
import re
from collections import Counter
from pathlib import Path

from agent_loop import MALFORMED, TEXT, UNKNOWN

LOST = "lost_multistep_chain"
CODE_RE = re.compile(r"\b[A-Z]{2}-\d{4,6}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ADDR_RE = re.compile(r"\b\d{2,5} (?:[A-Z][A-Za-z]+ ){1,2}(?:St|Ave|Blvd|Cir|Dr|Rd|Way|Ln|Ct|Pl|Ter|Pkwy|Loop)\b")
NOT_FOUND_WORDS = ["not found", "does not exist", "doesn't exist", "no listing", "could not find",
                   "couldn't find", "cannot find", "can't find", "unable to find", "no such"]


# ---------------------------------------------------------------- building cases

def _search(rows: list, term: str, limit: int = 10) -> list:
    return [r for r in rows if term.lower() in r["address"].lower()][:limit]


def _candidate_terms(rows: list) -> list:
    """Address words, ordered so that terms with about 6 matches come first."""
    words = Counter(w for r in rows for w in set(re.findall(r"[a-z]{4,}", r["address"].lower())))
    return sorted(words, key=lambda w: (abs(words[w] - 6), w))


def _pick_owner(rows: list, found: list, names: dict):
    for row in found:
        lid = row["landlord_id"]
        if lid and names.get(lid) and sum(1 for r in rows if r["landlord_id"] == lid) >= 2:
            return lid
    return None


def _street(row: dict) -> str:
    """The street part of an address, e.g. "7490 First St" (listing codes are mostly empty in the data)."""
    return row["address"].split(",")[0].strip()


def _try_term(rows: list, names: dict, term: str, strict: bool):
    found = _search(rows, term)
    if len(found) < 2:
        return None
    if strict and found[0]["landlord_id"] not in names:
        return None
    owner = _pick_owner(rows, found, names)
    return None if owner is None else {"term": term, "found": found, "owner": owner}


def _names_group(rows: list, names: dict) -> list:
    return [[names[r["landlord_id"]]] for r in rows if r["landlord_id"] in names]


def _case_a(ctx: dict, names: dict) -> dict:
    first = ctx["found"][0]
    return {
        "id": "A", "title": "search, then detail of the first result",
        "prompt": (f'Search the listings for "{ctx["term"]}", then look up the full details of the first '
                   "result. Tell me its address, how many units are available and its landlord's name if it has one."),
        "required": [{"tool": "search_listings"},
                     {"tool": "get_listing_detail", "inputs": {"listing_id": first["id"]}}],
        "answer_groups": [[_street(first)]] + _names_group([first], names),
    }


def _case_b(ctx: dict, rows: list) -> dict:
    owner = ctx["owner"]
    mine = [r for r in rows if r["landlord_id"] == owner]
    examples = [_street(r) for r in ctx["found"] if r["landlord_id"] == owner]
    return {
        "id": "B", "title": "aggregate, then one supporting example",
        "prompt": (f"How many listings does landlord {owner} have in total, and how many available units "
                   f'do they have across all of them? Then search the listings for "{ctx["term"]}" and name '
                   f"one listing from the results that belongs to landlord {owner}."),
        "required": [{"tool": "aggregate_landlord_stats", "inputs": {"landlord_id": owner}},
                     {"tool": "search_listings"}],
        "answer_groups": [[str(len(mine))], [str(sum(r["available_units"] for r in mine))], examples],
    }


def _case_c(ctx: dict, names: dict) -> dict:
    one, two = ctx["found"][0], ctx["found"][1]
    return {
        "id": "C", "title": "compare two listings (search plus two detail lookups)",
        "prompt": (f'Search the listings for "{ctx["term"]}", then look up the full details of each of the '
                   "first two results and compare them: give the address and available units of each, say which "
                   "has more units (or whether they are equal), and name each landlord."),
        "required": [{"tool": "search_listings"},
                     {"tool": "get_listing_detail", "inputs": {"listing_id": one["id"]}},
                     {"tool": "get_listing_detail", "inputs": {"listing_id": two["id"]}}],
        "answer_groups": [[_street(one)], [_street(two)]] + _names_group([one, two], names),
    }


def _case_e(rows: list) -> dict:
    bad_id = max(r["id"] for r in rows) + 1_000_000
    return {
        "id": "E", "title": "nonexistent listing id (error recovery)",
        "prompt": f"Show me the full details of listing {bad_id}.",
        "required": [{"tool": "get_listing_detail", "inputs": {"listing_id": bad_id}}],
        "answer_groups": [NOT_FOUND_WORDS],
    }


def build_cases_from_rows(rows: list, names: dict, seed: int = 8110) -> dict:
    """Build cases A, B, C and E from listing rows ({id, address, listing_code, available_units,
    landlord_id}) and a {landlord_id: name} dict. Raises ValueError when the data cannot support them."""
    for strict in (True, False):
        for term in _candidate_terms(rows):
            ctx = _try_term(rows, names, term, strict)
            if ctx:
                return {"seed": seed, "term": term,
                        "cases": [_case_a(ctx, names), _case_b(ctx, rows), _case_c(ctx, names)],
                        "recovery": _case_e(rows)}
    raise ValueError("no search term gives 2+ results that include a landlord with 2+ listings")


def load_cases(path) -> dict:
    """Read the saved fixed cases."""
    return json.loads(Path(path).read_text())


# ------------------------------------------------------------------ the verifier

def _call_matches(item: dict, call: dict) -> bool:
    if call["tool"] != item["tool"] or call["rejected"]:
        return False
    return all(str(call["inputs"].get(k)) == str(v) for k, v in item.get("inputs", {}).items())


def _check_required(required: list, trace: list) -> list:
    reasons = []
    for item in required:
        if not any(_call_matches(item, call) for call in trace):
            reasons.append(f"missing_call:{item['tool']}{item.get('inputs', '')}")
    names = [c["tool"] for c in trace if not c["rejected"]]
    if "search_listings" in names and "get_listing_detail" in names:
        first_detail = names.index("get_listing_detail")
        if any(item["tool"] == "search_listings" for item in required) and first_detail < names.index("search_listings"):
            reasons.append("wrong_order:detail_before_search")
    return reasons


def _check_answer(groups: list, answer) -> list:
    if not answer:
        return ["no_final_answer"]
    text = answer.lower()
    return [f"answer_missing:{group[0]}" for group in groups if not any(g.lower() in text for g in group)]


def check_case(case: dict, run: dict) -> dict:
    """Deterministic verdict for one run: {"passed": bool, "reasons": [...]}."""
    reasons = _check_required(case["required"], run["trace"])
    chain_ok = not reasons
    reasons += _check_answer(case["answer_groups"], run.get("final_answer"))
    if run["stop_reason"] != "final_answer":
        reasons.append(f"stop_reason:{run['stop_reason']}")
    return {"passed": not reasons, "reasons": reasons, "chain_ok": chain_ok}


def unsupported_claims(run: dict) -> list:
    """Listing codes, e-mail addresses or street addresses in the final answer that no tool result contains."""
    observed = " ".join(json.dumps(call["result"]) for call in run["trace"])
    answer = run.get("final_answer") or ""
    claims = set(CODE_RE.findall(answer)) | set(EMAIL_RE.findall(answer)) | set(ADDR_RE.findall(answer))
    return sorted(c for c in claims if c not in observed)


# ------------------------------------------------- reliability bookkeeping

def call_slots(run: dict, tools_required: bool = True) -> list:
    """One slot per attempted tool call: did the first reply work, and did it work after the reprompt?"""
    slots: list = []
    for event in run["events"]:
        if event["kind"] == "final":
            continue
        ok = event["kind"] == "ok_call"
        if event["after_repair"] and slots:
            slots[-1]["after_ok"] = ok
        else:
            slots.append({"first_kind": event["kind"], "first_ok": ok, "after_ok": ok})
    if tools_required and run["tool_calls"] == 0 and run.get("final_answer"):
        slots.append({"first_kind": TEXT, "first_ok": False, "after_ok": False})
    return slots


def failure_types(run: dict, check: dict, slots: list) -> list:
    """Failure classes seen in one attempt (before the repair path), plus the lost-chain class."""
    kinds = sorted({s["first_kind"] for s in slots if not s["first_ok"]})
    lost = run["tool_calls"] >= 1 and (not check["chain_ok"] or run["stop_reason"] == "max_steps")
    return kinds + ([LOST] if lost else [])


def make_attempt_record(index: int, case: dict, run: dict) -> dict:
    """The raw per-attempt record saved in reports/hw07/raw/."""
    check = check_case(case, run)
    slots = call_slots(run)
    summary = {k: v for k, v in run.items() if k not in ("trace", "events")}
    return {
        "attempt": index, "case": case["id"], "run": summary, "check": check, "slots": slots,
        "failure_types": failure_types(run, check, slots), "unsupported_claims": unsupported_claims(run),
        "trace": [{"tool": c["tool"], "inputs": c["inputs"], "ok": c["ok"], "rejected": c["rejected"]}
                  for c in run["trace"]],
    }


def _rate(count: int, total: int) -> float:
    return round(100 * count / total, 1) if total else 0.0


def summarize_reliability(attempts: list) -> dict:
    """Well-formed call rate before/after the repair path, and failures by class."""
    slots = [s for a in attempts for s in a["slots"]]
    before = Counter(s["first_kind"] for s in slots if not s["first_ok"])
    after = Counter(s["first_kind"] for s in slots if not s["after_ok"])
    lost = sum(1 for a in attempts if LOST in a["failure_types"])
    return {
        "attempts": len(attempts), "call_slots": len(slots),
        "well_formed_before_repair": sum(s["first_ok"] for s in slots),
        "well_formed_after_repair": sum(s["after_ok"] for s in slots),
        "rate_before_repair_pct": _rate(sum(s["first_ok"] for s in slots), len(slots)),
        "rate_after_repair_pct": _rate(sum(s["after_ok"] for s in slots), len(slots)),
        "failures_before_repair": {MALFORMED: before[MALFORMED], UNKNOWN: before[UNKNOWN],
                                   TEXT: before[TEXT], LOST: lost},
        "failures_after_repair": {MALFORMED: after[MALFORMED], UNKNOWN: after[UNKNOWN],
                                  TEXT: after[TEXT], LOST: lost},
        "verifier_passed": sum(1 for a in attempts if a["check"]["passed"]),
        "mean_tool_calls": round(sum(a["run"]["tool_calls"] for a in attempts) / max(len(attempts), 1), 2),
    }


def reliability_table(summary: dict) -> str:
    """Markdown table for the report."""
    b, a = summary["failures_before_repair"], summary["failures_after_repair"]
    rows = [
        ("Tool-use attempts (runs)", summary["attempts"], summary["attempts"]),
        ("Tool calls attempted", summary["call_slots"], summary["call_slots"]),
        ("Well-formed calls", summary["well_formed_before_repair"], summary["well_formed_after_repair"]),
        ("Well-formed rate", f"{summary['rate_before_repair_pct']}%", f"{summary['rate_after_repair_pct']}%"),
        ("Failure: malformed arguments", b[MALFORMED], a[MALFORMED]),
        ("Failure: unknown tool", b[UNKNOWN], a[UNKNOWN]),
        ("Failure: text when a tool was required", b[TEXT], a[TEXT]),
        ("Failure: lost multi-step chain", b[LOST], a[LOST]),
    ]
    lines = ["| Measure | Before repair | After repair |", "|---|---|---|"]
    return "\n".join(lines + [f"| {name} | {x} | {y} |" for name, x, y in rows])