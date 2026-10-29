import logging
import os

from agent_core import carry, run_main
from kafka_config import GROUP_WRITER, TOPIC_DRAFTS, TOPIC_TASKS
from llm import write_draft

log = logging.getLogger("writer")


def maybe_crash(cid) -> None:
    """Simulate `kill -9` in the middle of the work: exit once, without committing or sending anything."""
    target, marker = os.environ.get("WRITER_CRASH_ON_CID"), os.environ.get("WRITER_CRASH_MARKER")
    if target and marker and cid == target and not os.path.exists(marker):
        open(marker, "w").close()
        log.info("CRASH     writer dies mid-processing of correlation_id=%s (before sending the draft and before the commit)", cid)
        os._exit(137)


def make_draft(body: dict, msg) -> dict:
    """tasks message -> drafts message. Raises ValueError when the task has no usable plan (a poison message)."""
    plan = body.get("plan") if isinstance(body, dict) else None
    if not isinstance(plan, list) or not plan or not isinstance(body.get("question"), str):
        raise ValueError("task has no valid plan/question")
    maybe_crash(body.get("correlation_id"))
    draft, source = write_draft(body["question"], plan)
    return {**carry(body), "question": body["question"], "plan": plan, "draft": draft, "writer_llm": source,
            "writer_id": os.environ.get("WRITER_ID", "writer")}


def run_filter():
    run_id = os.environ.get("RUN_FILTER")
    return (lambda body: body.get("run_id") == run_id) if run_id else None


if __name__ == "__main__":
    run_main("writer", GROUP_WRITER, TOPIC_TASKS, TOPIC_DRAFTS, make_draft, accept=run_filter())