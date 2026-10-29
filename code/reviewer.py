from agent_core import carry, run_main
from kafka_config import GROUP_REVIEWER, TOPIC_DRAFTS, TOPIC_FINAL

MIN_LEN = 40


def review(body: dict, msg) -> dict | None:
    """drafts message -> final message {status, answer, correlation_id}. Messages from Part 3 test runs (run_id) are skipped."""
    if "run_id" in body:
        return None
    draft = body.get("draft")
    ok = isinstance(draft, str) and len(draft.strip()) >= MIN_LEN and "<think>" not in draft
    return {**carry(body), "status": "approved" if ok else "rejected", "answer": draft if ok else "",
            "reviewer_note": "draft passes length and cleanliness checks" if ok else "draft too short or contains reasoning tags"}


if __name__ == "__main__":
    run_main("reviewer", GROUP_REVIEWER, TOPIC_DRAFTS, TOPIC_FINAL, review)