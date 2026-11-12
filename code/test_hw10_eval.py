import json
import os
import tempfile
import time

os.environ["TRACE_FILE"] = os.path.join(tempfile.mkdtemp(), "spans.jsonl")

from judge import STEPS, JudgeError, JudgeResult, JudgeUnavailable, to_scale  # noqa: E402
from kafka_config import TOPIC_DRAFTS, TOPIC_FINAL, TOPIC_PARTITIONS, TOPIC_TASKS  # noqa: E402
from kafka_io import InMemoryBroker, InMemoryConsumer, InMemoryProducer  # noqa: E402
from label_cases import parse_label, save_labels, load_labels  # noqa: E402
from make_eval_cases import build_cases  # noqa: E402
from pipeline_eval import MessageCollector, evaluate_trace, extract_inputs  # noqa: E402
from tracing import spans_for  # noqa: E402


class FakeJudge:
    def __init__(self, fail_with=None):
        self.calls, self.fail_with = [], fail_with

    def score(self, metric, question, output, context=None):
        self.calls.append(metric)
        if self.fail_with:
            raise self.fail_with
        return JudgeResult(round(min(5.0, 1 + len(output) / 40), 2), f"fake reason for {metric}", 0.5)


def msgs(plan=("check the lease", "ask about fees", "summarize"), draft="Check the lease term, the deposit and the fees before signing.", final=None, status="approved"):
    final = draft if final is None else final
    return {"plan": {"body": {"correlation_id": "c1", "question": "What to check?", "plan": list(plan) if plan is not None else plan}, "topic": TOPIC_TASKS, "partition": 0, "offset": 1},
            "draft": {"body": {"correlation_id": "c1", "question": "What to check?", "draft": draft}, "topic": TOPIC_DRAFTS, "partition": 0, "offset": 1},
            "final": {"body": {"correlation_id": "c1", "status": status, "answer": final}, "topic": TOPIC_FINAL, "partition": 0, "offset": 1}}


def test_scale_mapping_is_1_to_5():
    assert (to_scale(0), to_scale(0.5), to_scale(1)) == (1.0, 3.0, 5.0)


def test_every_metric_has_fixed_evaluation_steps():
    assert set(STEPS) == {"plan_quality", "writer_helpfulness", "final_helpfulness"} and all(len(v) >= 4 for v in STEPS.values())


def test_evaluate_trace_scores_all_four_and_writes_an_evaluation_span():
    judge = FakeJudge()
    rec = evaluate_trace("c1", msgs(), judge)
    assert rec["status"] == "ok" and len(judge.calls) == 4
    assert all(1 <= s["score"] <= 5 for s in rec["scores"].values())
    assert rec["improvement"]["identical_text"] is True and rec["improvement"]["difference"] == 0 and "identical" in rec["improvement"]["interpretation"]
    span = next(s for s in spans_for("c1") if s["stage"] == "evaluation")
    assert span["status"] == "ok" and rec["messages"]["plan"]["offset"] == 1


def test_different_final_text_gets_a_real_difference():
    rec = evaluate_trace("c2", msgs(final="Check the lease term, deposit, fees, pet policy, repair rules and the move-in inspection before you sign anything."), FakeJudge())
    assert rec["improvement"]["identical_text"] is False and rec["improvement"]["difference"] > 0


def test_malformed_plan_is_skipped_but_other_metrics_still_run():
    judge = FakeJudge()
    rec = evaluate_trace("c3", msgs(plan=[]), judge)
    assert rec["scores"]["plan_quality"]["status"] == "skipped" and rec["status"] == "partial" and "plan_quality" not in judge.calls
    assert rec["scores"]["writer_helpfulness"]["status"] == "ok"


def test_missing_messages_and_empty_final_are_reported_not_fatal():
    partial = {"plan": msgs()["plan"]}
    inputs, problems = extract_inputs(partial)
    assert "missing draft message" in problems and "missing final message" in problems and inputs["draft"] is None
    rec = evaluate_trace("c4", msgs(final="", status="rejected"), FakeJudge())
    assert any("reviewer status=rejected" in p for p in rec["problems"]) and rec["scores"]["final_helpfulness"]["status"] == "skipped"


def test_unavailable_judge_stops_after_one_call():
    judge = FakeJudge(JudgeUnavailable("judge model unreachable"))
    rec = evaluate_trace("c5", msgs(), judge)
    assert len(judge.calls) == 1 and rec["status"] == "error" and all(s["status"] != "ok" for s in rec["scores"].values())
    assert next(s for s in spans_for("c5") if s["stage"] == "evaluation")["status"] == "error"


def test_repeated_judge_errors_hit_the_error_budget():
    judge = FakeJudge(JudgeError("bad json"))
    rec = evaluate_trace("c6", msgs(), judge, max_errors=2)
    assert len(judge.calls) == 2 and rec["status"] == "error"


def test_zero_time_budget_makes_no_judge_calls():
    judge = FakeJudge()
    rec = evaluate_trace("c7", msgs(), judge, deadline_s=0)
    assert judge.calls == [] and rec["status"] == "error"


def test_collector_joins_plan_draft_final_by_correlation_id():
    b = InMemoryBroker()
    for topic, parts in TOPIC_PARTITIONS.items():
        b.create_topic(topic, parts)
    collector = MessageCollector(InMemoryConsumer(b, "eval", [TOPIC_TASKS, TOPIC_DRAFTS, TOPIC_FINAL])).start()
    producer = InMemoryProducer(b)
    producer.send(TOPIC_TASKS, {"correlation_id": "x", "question": "q", "plan": ["a"]}, key="x")
    producer.send(TOPIC_DRAFTS, {"correlation_id": "y", "draft": "other request"}, key="y")
    producer.send(TOPIC_DRAFTS, {"correlation_id": "x", "draft": "the draft"}, key="x")
    producer.send(TOPIC_FINAL, {"correlation_id": "x", "status": "approved", "answer": "the draft"}, key="x")
    got = collector.wait("x", timeout=3)
    assert set(got) == {"plan", "draft", "final"} and got["draft"]["body"]["draft"] == "the draft"
    start = time.time()
    assert set(collector.wait("y", timeout=0.3)) == {"draft"} and time.time() - start < 2
    collector.close()


def test_case_set_has_20_cases_with_a_mix_and_no_labels_inside():
    cases = build_cases(lambda q: ["step one", "step two"], lambda q, steps, ctx: f"draft for {q}", lambda q: "address: 1 Main St")
    assert len(cases) == 20 and len({c["case_id"] for c in cases}) == 20
    assert {c["variant"] for c in cases} == {"general", "with_database_facts", "no_facts_available", "off_topic_or_vague", "mismatched_plan"}
    assert all("label" not in c and "score" not in c for c in cases) and sum(1 for c in cases if c["context"]) == 5
    assert json.dumps(cases)


def test_label_parsing_and_csv_roundtrip():
    assert [parse_label(x) for x in ("1", " 5 ", "0", "6", "3.5", "", "x")] == [1, 5, None, None, None, None, None]
    path = os.path.join(tempfile.mkdtemp(), "human_labels.csv")
    from pathlib import Path
    save_labels(Path(path), {"ec01": 4, "ec02": None})
    assert load_labels(Path(path)) == {"ec01": 4, "ec02": None}