import csv
import json
import sys
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from model_client import ModelClient  # noqa: E402

RUNS_PER_CEILING = 20
CEILINGS = [2, 10]
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7

INPUT_PATH = Path(__file__).resolve().parent / "reports/hw02/cases/schema_input.json"
RAW_DIR = Path(__file__).resolve().parent / "reports/hw02/raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


class PlannerOutput(BaseModel):
    tags: list[str]
    summary: str

    @field_validator("tags")
    @classmethod
    def check_tags(cls, v):
        if len(v) != 3:
            raise ValueError(f"expected exactly 3 tags, got {len(v)}")
        for tag in v:
            if not (3 <= len(tag) <= 30):
                raise ValueError(f"tag '{tag}' must be 3-30 characters, got {len(tag)}")
        return v

    @field_validator("summary")
    @classmethod
    def check_summary(cls, v):
        word_count = len(v.split())
        if word_count > 25:
            raise ValueError(f"summary has {word_count} words, must be at most 25")
        return v


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


def run_planner_until_valid(title: str, content: str, turn_ceiling: int):
    client = ModelClient(model=MODEL_NAME, temperature=TEMPERATURE)
    validation_error = None
    t0 = time.time()

    for attempt in range(1, turn_ceiling + 1):
        feedback_note = ""
        if validation_error:
            feedback_note = (
                f"\nThe previous attempt FAILED schema validation with this error: "
                f"{validation_error}\nYou must fix this and follow the schema exactly: "
                f"exactly 3 tags, each 3-30 characters, summary at most 25 words."
            )

        prompt = f"""You are the Planner agent. Given a title and content, propose exactly 3
short topical tags (each 3-30 characters) and a one-sentence summary of at most 25 words.
Derive the tags and summary ONLY from the given title/content -- do not use any fixed
domain keyword list.{feedback_note}

Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "..."}}

Title: {title}
Content: {content}
"""
        client.add_user_message(prompt)
        response = client.complete()

        try:
            raw = extract_json(response.content)
            validated = PlannerOutput(**raw)
            latency_ms = (time.time() - t0) * 1000
            return {"attempts": attempt, "valid": True, "latency_ms": latency_ms}
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            validation_error = str(e)

    latency_ms = (time.time() - t0) * 1000
    return {"attempts": turn_ceiling, "valid": False, "latency_ms": latency_ms}


if __name__ == "__main__":
    with open(INPUT_PATH) as f:
        case = json.load(f)
    title, content = case["title"], case["content"]

    all_results = []

    for ceiling in CEILINGS:
        print(f"\n=== Running {RUNS_PER_CEILING} runs with turn_ceiling={ceiling} ===\n")
        for i in range(RUNS_PER_CEILING):
            result = run_planner_until_valid(title, content, ceiling)
            result["run"] = i
            result["ceiling"] = ceiling
            all_results.append(result)
            print(f"  ceiling={ceiling} run {i+1}/{RUNS_PER_CEILING}: "
                  f"attempts={result['attempts']} valid={result['valid']} "
                  f"latency={result['latency_ms']:.0f}ms")

    json_path = RAW_DIR / "ceiling_comparison_results.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    csv_path = RAW_DIR / "ceiling_comparison_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ceiling", "run", "attempts", "valid", "latency_ms"])
        writer.writeheader()
        for r in all_results:
            writer.writerow({
                "ceiling": r["ceiling"],
                "run": r["run"],
                "attempts": r["attempts"],
                "valid": r["valid"],
                "latency_ms": round(r["latency_ms"], 1),
            })

    print(f"\nRaw results saved to {json_path} and {csv_path}")

    print("\n=== SUMMARY ===")
    for ceiling in CEILINGS:
        matching = [r for r in all_results if r["ceiling"] == ceiling]
        completed = [r for r in matching if r["valid"]]
        completion_rate = len(completed) / len(matching) * 100
        mean_latency = sum(r["latency_ms"] for r in matching) / len(matching)
        print(f"\n--- Ceiling = {ceiling} ---")
        print(f"Completion rate: {completion_rate:.1f}% ({len(completed)}/{len(matching)})")
        print(f"Mean latency: {mean_latency:.1f} ms")