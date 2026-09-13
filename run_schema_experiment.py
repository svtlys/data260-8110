import csv
import json
import sys
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from model_client import ModelClient  # noqa: E402

TURN_CEILING = 10
NUM_RUNS = 30
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7

INPUT_PATH = Path(__file__).resolve().parent/ "reports/hw02/cases/schema_input.json"
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


def run_planner_until_valid(title: str, content: str, turn_ceiling: int = TURN_CEILING):
    """
    Calls the Planner repeatedly, feeding back validation errors, until it
    produces valid output or hits turn_ceiling attempts.

    Returns a dict with: attempts, valid (bool), latency_ms, final_output.
    """
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
            return {
                "attempts": attempt,
                "valid": True,
                "latency_ms": latency_ms,
                "final_output": validated.model_dump(),
            }
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            validation_error = str(e)

    latency_ms = (time.time() - t0) * 1000
    return {
        "attempts": turn_ceiling,
        "valid": False,
        "latency_ms": latency_ms,
        "final_output": None,
    }


def classify(result: dict) -> str:
    if not result["valid"]:
        return "abandoned_at_ceiling"
    if result["attempts"] == 1:
        return "valid_first_attempt"
    if result["attempts"] == 2:
        return "valid_after_1_retry"
    return "valid_after_2plus_retries"


if __name__ == "__main__":
    with open(INPUT_PATH) as f:
        case = json.load(f)
    title, content = case["title"], case["content"]

    all_results = []
    print(f"=== Running {NUM_RUNS} runs (turn_ceiling={TURN_CEILING}) ===\n")

    for i in range(NUM_RUNS):
        result = run_planner_until_valid(title, content)
        category = classify(result)
        result["run"] = i
        result["category"] = category
        all_results.append(result)
        print(f"run {i+1}/{NUM_RUNS}: attempts={result['attempts']} "
              f"valid={result['valid']} category={category} "
              f"latency={result['latency_ms']:.0f}ms")

    # Save raw results
    json_path = RAW_DIR / "schema_validation_results.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    csv_path = RAW_DIR / "schema_validation_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["run", "attempts", "valid", "category", "latency_ms"])
        writer.writeheader()
        for r in all_results:
            writer.writerow({
                "run": r["run"],
                "attempts": r["attempts"],
                "valid": r["valid"],
                "category": r["category"],
                "latency_ms": round(r["latency_ms"], 1),
            })

    print(f"\nRaw results saved to {json_path} and {csv_path}")

    # Summary table
    categories = ["valid_first_attempt", "valid_after_1_retry", "valid_after_2plus_retries", "abandoned_at_ceiling"]
    print("\n=== SUMMARY (30 runs) ===")
    print(f"{'Outcome':<28} {'Count':<8} {'Mean latency (ms)':<20}")
    for cat in categories:
        matching = [r for r in all_results if r["category"] == cat]
        count = len(matching)
        mean_latency = sum(r["latency_ms"] for r in matching) / count if count > 0 else 0
        print(f"{cat:<28} {count:<8} {mean_latency:<20.1f}")