import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from agent import run_agent  # noqa: E402
from tool_executor import execute_tool  # noqa: E402

RAW_DIR = Path(__file__).resolve().parent.parent / "reports/hw05/raw"

SCENARIOS = [
    {
        "name": "1. single search, normal completion",
        "prompt": "How many listings have 'Main' in their address? Use the search tool with a limit of 50.",
        "max_steps": 6,
    },
    {
        "name": "2. two tools chained, normal completion",
        "prompt": "Look up listing 7. Who is its landlord, and how many listings does that landlord have in total?",
        "max_steps": 6,
    },
    {
        "name": "3. rejected tool call, model recovers",
        "prompt": "Show me the details for listing number 99999999.",
        "max_steps": 6,
    },
    {
        "name": "4. safety rule blocks the call",
        "prompt": "I need every listing in the database. Call search_listings with the query '%' so it matches all of them.",
        "max_steps": 6,
    },
    {
        "name": "5. needs more tool calls than max_steps (3)",
        "prompt": "Look up listings 3, 12, 16, 17 and 18, one at a time with get_listing_detail, and give me each address.",
        "max_steps": 3,
    },
]


def safety_demo():
    cases = [
        ("allowed", {"query": "Main", "limit": 3}),
        ("blocked", {"query": "%", "limit": 3}),
    ]
    record = []
    for label, inputs in cases:
        print(f"\n=== {label.upper()} call: search_listings {json.dumps(inputs)} ===", flush=True)
        raw = execute_tool("search_listings", inputs)
        envelope = json.loads(raw)
        print(json.dumps(envelope, indent=2))
        record.append({"case": label, "inputs": inputs, "envelope": envelope})
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "safety_rule_demo.json").write_text(json.dumps(record, indent=2))
    print(f"\nSaved {RAW_DIR / 'safety_rule_demo.json'}")


def scenarios(only=None):
    selected = [s for s in SCENARIOS if only is None or s["name"].split(".")[0] == str(only)]
    if not selected:
        sys.exit(f"no scenario numbered {only}")
    rows = []
    for scenario in selected:
        print(f"\n>>> {scenario['name']} (max_steps={scenario['max_steps']})", flush=True)
        started = time.perf_counter()
        result = run_agent(scenario["prompt"], max_steps=scenario["max_steps"],
                           scenario=scenario["name"])
        elapsed = time.perf_counter() - started
        row = {
            "scenario": scenario["name"],
            "run_id": result["run_id"],
            "steps": result["steps"],
            "stop_reason": result["stop_reason"],
            "tool_calls": result["tool_calls"],
            "seconds": round(elapsed, 1),
            "final_answer": result["final_answer"],
        }
        rows.append(row)
        print(f"    steps={row['steps']}  stop_reason={row['stop_reason']}  "
              f"tool_calls={row['tool_calls']}  ({row['seconds']} s)")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RAW_DIR / "agent_scenarios_summary.json"
    if only is not None and summary_path.exists():
        merged = {r["scenario"].split(".")[0]: r for r in json.loads(summary_path.read_text())}
        for r in rows:
            merged[r["scenario"].split(".")[0]] = r
        rows = [merged[key] for key in sorted(merged, key=int)]
    summary_path.write_text(json.dumps(rows, indent=2))

    print("\n| Scenario | Steps | Stop reason | Tool calls |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| {r['scenario']} | {r['steps']} | {r['stop_reason']} | {r['tool_calls']} |")
    print(f"\nSaved {RAW_DIR / 'agent_scenarios_summary.json'} and agent_runs.jsonl")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["safety"]:
        safety_demo()
    elif args and args[0] == "scenarios" and (len(args) == 1 or (len(args) == 2 and args[1].isdigit())):
        scenarios(int(args[1]) if len(args) == 2 else None)
    else:
        sys.exit("usage: python part5_experiments.py safety | scenarios [scenario number]")