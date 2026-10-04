import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CODE_DIR = Path(__file__).resolve().parent
OUT_PATH = CODE_DIR.parent / "reports/hw05/raw/mcp_tool_outputs.json"

MEALS_CALLS = [
    ("search_meals_by_name", {"query": "Arrabiata", "limit": 5}, "valid"),
    ("meals_by_ingredient", {"ingredient": "chicken", "limit": 12}, "valid"),
    ("meal_details", {"id": "52772"}, "valid"),
    ("random_meal", {}, "valid"),
]

DOMAIN_CALLS = [
    ("search_listings", {"query": "Main", "limit": 5}, "valid"),
    ("search_listings", {"query": " ", "limit": 5}, "invalid"),
    ("get_listing_detail", {"listing_id": 7}, "valid"),
    ("get_listing_detail", {"listing_id": 99999999}, "invalid"),
    ("aggregate_landlord_stats", {"landlord_id": 1}, "valid"),
    ("aggregate_landlord_stats", {"landlord_id": 0}, "invalid"),
]


def _summarize(result) -> str:
    """Short status for the console: the tool's own {ok, ...} envelope if it has one."""
    if result.isError:
        return "TOOL ERROR"
    payload = result.structuredContent
    if payload is None and result.content:
        try:
            payload = json.loads(result.content[0].text)
        except (ValueError, AttributeError):
            payload = None
    if isinstance(payload, dict) and "ok" in payload:
        return f"envelope ok={payload['ok']}"
    return "returned data"


async def run_server(script: str, calls: list) -> dict:
    # env must be passed explicitly: the SDK otherwise gives the child process
    # only a small default environment, which would drop MYSQL_ROOT_PASSWORD.
    params = StdioServerParameters(
        command=sys.executable,
        args=[script],
        cwd=str(CODE_DIR),
        env=dict(os.environ),
    )
    record = {"server": script, "tools_listed": [], "calls": []}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            record["tools_listed"] = [tool.name for tool in listed.tools]
            for name, arguments, kind in calls:
                entry = {"tool": name, "kind": kind, "input": arguments}
                try:
                    result = await session.call_tool(name, arguments)
                    entry["result"] = result.model_dump(mode="json")
                except Exception as exc:  # keep going so one failure doesn't hide the rest
                    entry["exception"] = f"{type(exc).__name__}: {exc}"
                record["calls"].append(entry)
                if "exception" in entry:
                    status = "EXCEPTION"
                else:
                    status = _summarize(result)
                print(f"  {name:28s} {kind:8s} -> {status}")
    return record


async def main():
    output = {
        "note": "Scripted replay of the MCP Inspector test inputs (not Inspector's own export). "
                "random_meal returns a different meal on each run.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "servers": [],
    }
    for script, calls in (("meals_server.py", MEALS_CALLS), ("domain_mcp_server.py", DOMAIN_CALLS)):
        print(f"\n{script}")
        output["servers"].append(await run_server(script, calls))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nSaved {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())