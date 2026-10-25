import json
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw07" / "raw"
NAMES = {"membership": "Scenario A: membership should win (bike_membership_wins.csv)",
         "payperuse": "Scenario B: pay per use should win (bike_payperuse_wins.csv)"}


def money(x) -> str:
    """Dollar string."""
    return "n/a" if x is None else f"${x:,.2f}"


def retry_note(run: dict) -> str:
    """Sentence about the verifier retry, if there was one."""
    first = run.get("first_attempt")
    if not first:
        return "No verifier retry was needed. "
    if first.get("price_problem"):
        return ("The first answer used a membership price that the verifier did not find as a general-public price on the page, "
                "so the agent was asked once more; the numbers above are from the second answer. ")
    chk = first.get("independent_check") or {}
    return (f"The first answer ({(first.get('answer') or {}).get('decision')}) disagreed with the recomputation "
            f"(membership {money(chk.get('member_total'))} vs pay-per-use {money(chk.get('payg_total'))}), so the verifier "
            "sent the computed totals back once and the agent answered again; the numbers above are from the second answer. ")


def paragraph(run: dict) -> str:
    """One scenario paragraph from a saved run."""
    c, m, a = run.get("independent_check"), run["metrics"], run.get("answer") or {}
    if not c:
        return f"The agent stopped with `{m['stop_reason']}` after {m['steps']} steps and gave no usable answer."
    cites = run.get("citations") or []
    flag = f" WARNING, price check still failing: {run['price_problem']}" if run.get("price_problem") else ""
    verified = sum(1 for x in cites if x.get("verified"))
    cheaper = "membership" if c["cheaper"] == "membership" else "pay per use"
    return (
        f"The agent recommended **{a.get('decision')}**. Recomputing the costs in code from the "
        f"{c['rides']} uploaded rides and the prices the agent read from the page gives pay-per-use "
        f"{money(c['payg_total'])} against membership {money(c['member_total'])} "
        f"({money(c['member_fees'])} in fees over {c['months']} months plus {money(c['member_residual'])} in per-ride charges), "
        f"so {cheaper} is cheaper by {money(c['difference'])}. The rider averaged {c['actual_rides_per_month']} rides "
        f"({c['actual_minutes_per_month']} minutes) per month; the break-even is "
        f"{c['break_even_rides_per_month']} rides per month. The agent's decision "
        f"{'agrees' if run['decision_agrees_with_check'] else 'does NOT agree'} with this independent check. "
        f"The run used {m['steps']} steps and {m['tool_calls']} tool calls, took {m['total_time_s']} s and stopped with "
        f"`{m['stop_reason']}`. " + retry_note(run) + f"{verified} of {len(cites)} citations were found verbatim in the saved pricing snapshot "
        f"(SHA-256 {(run.get('snapshot') or {}).get('sha256', 'n/a')})." + flag)


def main() -> None:
    """Print the section."""
    print("## Part 4: Framework Agent (LangGraph ReAct)\n")
    print("**Design.** A LangGraph StateGraph with an agent node (qwen3:8b through ChatOllama, tools bound) and a tools node. "
          "Three tools share one envelope {success, data, error, source, ts}: `csv_sql` (one read-only SELECT over the uploaded "
          "CSV loaded into in-memory SQLite), `policy_retriever` (fetches the pricing page, returns scored passages, saves the "
          "exact text with its SHA-256) and `calculator` (digits and + - * / only, no eval). The model never computes the "
          "final totals: the application recomputes them from the trips and the model's extracted prices.\n")
    print("**Assumptions.** Public trip data is anonymous, so each file is treated as one rider. The pay-per-use file's "
          "dates are re-assigned across about 7 years (times of day and durations are real) because each ride costs at "
          "least about $1.15 against $10 per month. The page lists membership as $120/year, used here as $10/month. "
          "The $10 day pass is ignored.\n")
    for key, title in NAMES.items():
        path = RAW / "bike_runs" / f"{key}.json"
        if not path.exists():
            print(f"### {title}\n(missing: run this scenario first)\n")
            continue
        print(f"### {title}\n")
        print(paragraph(json.loads(path.read_text())) + "\n")
    print("**Screenshots:** see the figures for each scenario (metrics, timeline, decision, cost comparison, citations).")


if __name__ == "__main__":
    sys.exit(main())