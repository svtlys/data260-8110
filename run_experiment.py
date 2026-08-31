"""
run_experiment.py

Runs the Planner -> Reviewer -> Finalizer pipeline 20x at temperature 0.7
and 20x at temperature 0.0 (40 runs total) on a single fixed input, to
measure run-to-run non-determinism.

Reads input from: reports/hw01/cases/nondeterminism_input.json
Writes raw results to: reports/hw01/raw/nondeterminism_results.json
                        reports/hw01/raw/nondeterminism_results.csv

Run with:
    python run_experiment.py
"""

import csv
import json
import time
from collections import Counter
from pathlib import Path

from langchain_ollama import ChatOllama

MODEL_NAME = "qwen3:8b"
RUNS_PER_TEMP = 20
TEMPERATURES = [0.7, 0.0]

INPUT_PATH = Path("reports/hw01/cases/nondeterminism_input.json")
RAW_DIR = Path("reports/hw01/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output:\n{text}")
    return json.loads(text[start:end + 1])


def planner(llm, title: str, content: str) -> dict:
    prompt = f"""You are the Planner agent. Given a title and content, propose exactly 3
short topical tags and a one-sentence summary of at most 25 words.
Derive the tags and summary ONLY from the given title/content below -- do not
assume any fixed domain or use predetermined keyword lists.

Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "..."}}

Title: {title}
Content: {content}
"""
    resp = llm.invoke(prompt)
    return extract_json(resp.content)


def reviewer(llm, draft: dict, title: str, content: str) -> dict:
    prompt = f"""You are the Reviewer agent. Review the draft JSON below for accuracy and
relevance to the source title/content. If the tags or summary are inaccurate,
too generic, or exceed 25 words, fix them. Otherwise keep them as-is.

Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "..."}}

Draft: {json.dumps(draft)}
Title: {title}
Content: {content}
"""
    resp = llm.invoke(prompt)
    return extract_json(resp.content)


def run_pipeline_once(title: str, content: str, temperature: float) -> dict:
    llm = ChatOllama(model=MODEL_NAME, temperature=temperature)
    t0 = time.time()
    draft = planner(llm, title, content)
    reviewed = reviewer(llm, draft, title, content)
    latency_ms = (time.time() - t0) * 1000
    return {"tags": reviewed["tags"], "summary": reviewed["summary"], "latency_ms": latency_ms}


def percentile(values, p):
    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def summarize(results_for_temp):
    tag_sets = [frozenset(r["tags"]) for r in results_for_temp]
    distinct_tag_sets = len(set(tag_sets))

    tag_counter = Counter()
    for r in results_for_temp:
        for t in r["tags"]:
            tag_counter[t] += 1

    n = len(results_for_temp)
    tags_in_all = sorted([t for t, c in tag_counter.items() if c == n])
    tags_in_exactly_one = sorted([t for t, c in tag_counter.items() if c == 1])

    latencies = [r["latency_ms"] for r in results_for_temp]
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)

    return {
        "distinct_tag_sets": distinct_tag_sets,
        "tags_in_all_runs": tags_in_all,
        "tags_in_exactly_one_run": tags_in_exactly_one,
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "latency_p99_ms": round(p99, 1),
    }


if __name__ == "__main__":
    with open(INPUT_PATH) as f:
        case = json.load(f)
    title, content = case["title"], case["content"]

    all_results = []
    summaries = {}

    for temp in TEMPERATURES:
        print(f"\n=== Running {RUNS_PER_TEMP} runs at temperature={temp} ===")
        results_for_temp = []
        for i in range(RUNS_PER_TEMP):
            r = run_pipeline_once(title, content, temp)
            r["run"] = i
            r["temperature"] = temp
            results_for_temp.append(r)
            all_results.append(r)
            print(f"  run {i+1}/{RUNS_PER_TEMP}: tags={r['tags']} latency={r['latency_ms']:.0f}ms")

        summaries[temp] = summarize(results_for_temp)

    # Save raw results
    json_path = RAW_DIR / "nondeterminism_results.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    csv_path = RAW_DIR / "nondeterminism_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["run", "temperature", "tags", "summary", "latency_ms"])
        writer.writeheader()
        for r in all_results:
            writer.writerow({
                "run": r["run"],
                "temperature": r["temperature"],
                "tags": "|".join(r["tags"]),
                "summary": r["summary"],
                "latency_ms": round(r["latency_ms"], 1),
            })

    print(f"\nRaw results saved to {json_path} and {csv_path}")

    print("\n=== SUMMARY ===")
    for temp in TEMPERATURES:
        print(f"\n--- Temperature {temp} ---")
        print(json.dumps(summaries[temp], indent=2))