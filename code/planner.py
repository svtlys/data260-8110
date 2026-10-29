from agent_core import carry, run_main
from kafka_config import GROUP_PLANNER, TOPIC_INBOX, TOPIC_TASKS
from llm import plan_steps


def make_plan(body: dict, msg) -> dict:
    """inbox message -> tasks message. Raises ValueError for a message without a question."""
    question = body.get("question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not question.strip():
        raise ValueError("inbox message has no question")
    steps, source = plan_steps(question)
    return {**carry(body), "question": question, "plan": steps, "planner_llm": source}


if __name__ == "__main__":
    run_main("planner", GROUP_PLANNER, TOPIC_INBOX, TOPIC_TASKS, make_plan)