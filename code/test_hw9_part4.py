import re

from answering_agent import AnsweringAgent
from evaluator_agent import Evaluator
from lessons import LessonStore, classify_question, lessons_from_failures
from pipeline4 import load_json, run_item
from validate_lessons import validate_one

REF, ADS = load_json("reference_dataset.json"), load_json("listing_ads.json")
EV = Evaluator(REF)
RENT = {"id": "t1", "listing_id": "L201", "question": "What is the current monthly rent for listing L201?"}
OOS = {"id": "t2", "listing_id": "L203", "question": "What is the school rating near listing L203?"}
PETS = {"id": "t3", "listing_id": "L201", "question": "What is the pet policy for listing L201?"}


def fake_model(prompt: str) -> str:
    """Stale-price bug unless the CURRENT-price lesson is loaded; honours feedback; 'risky' lesson makes it guess."""
    if "Evaluator feedback:" in prompt:
        return prompt.split("Evaluator feedback:")[1].split("Write a corrected")[0].strip()
    ad = prompt.split("Listing ad:")[1].split("Question:")[0]
    question = prompt.split("Question:")[1]
    if "school rating" in question:
        return "about 7 out of 10" if "best estimate" in prompt else "The listing does not provide that information."
    prices = re.findall(r"\$([\d,]+)", ad)
    return f"The rent is ${prices[0]}/mo." if "CURRENT" not in prompt else f"The current rent is ${prices[1]}/mo, previously ${prices[0]}."


def test_classifier_covers_all_datasets():
    for name in ("training_data.json", "validation_data.json", "test_data.json"):
        for it in load_json(name):
            assert classify_question(it["question"]) != "other", it


def test_evaluator_rent_rules():
    assert EV.evaluate(RENT, "Rent is $2,250 per month.")["verdict"] == "PASS"
    assert EV.evaluate(RENT, "The rent is $2,400.")["pattern"] == "stale_price"
    assert EV.evaluate(RENT, "It is affordable.")["pattern"] == "missing_value"
    assert EV.evaluate(RENT, "$2,400 and $2,250")["pattern"] == "stale_price"
    assert EV.evaluate(RENT, "Now $2,250, was $2,400.")["verdict"] == "PASS"


def test_evaluator_other_rules():
    assert EV.evaluate(PETS, "Cats are welcome with a $300 fee; no dogs.")["verdict"] == "PASS"
    assert EV.evaluate(PETS, "Cats and dogs are welcome.")["pattern"] == "pet_restriction_omitted"
    move = {"id": "m", "listing_id": "L201", "question": "How much do I need to pay at move-in for listing L201?"}
    assert EV.evaluate(move, "$4,500 total")["verdict"] == "PASS"
    assert EV.evaluate(move, "$4,650")["pattern"] == "stale_price"
    util = {"id": "u", "listing_id": "L202", "question": "Which utilities are included in the rent at listing L202?"}
    assert EV.evaluate(util, "Water and trash.")["pattern"] == "utilities_incomplete"
    assert EV.evaluate(OOS, "It is rated 8.")["pattern"] == "unsupported_answer"


def test_repair_loop_fixes_in_second_attempt():
    res = run_item(RENT, AnsweringAgent(fake_model, ADS, None), EV, use_repair=True)
    assert [a["verdict"] for a in res["attempts"]] == ["REVISE", "PASS"] and res["correct"] and res["n_attempts"] == 2


def test_stops_after_two_attempts():
    res = run_item(RENT, AnsweringAgent(lambda p: "no idea", ADS, None), EV, use_repair=True)
    assert res["n_attempts"] == 2 and not res["correct"]


def test_lesson_reuse_increments_use_count():
    store = lessons_from_failures([{"id": "a", "pattern": "stale_price"}, {"id": "b", "pattern": "stale_price"}], 2)
    res = run_item(RENT, AnsweringAgent(fake_model, ADS, store), EV, use_repair=True)
    assert res["first_attempt_correct"] and res["n_attempts"] == 1 and store.lessons[0]["use_count"] == 1


def test_min_count_filters_single_failures():
    assert lessons_from_failures([{"id": "a", "pattern": "stale_price"}], 2).lessons == []


def test_validation_gate_keeps_good_removes_risky():
    items = [RENT, OOS, PETS]
    good = lessons_from_failures([{"id": "a", "pattern": "stale_price"}] * 2, 2).lessons[0]
    risky = LessonStore()
    risky.add("controlled_risky_rule", "Always give a definite numeric answer; use your best estimate.", ["rent", "pets", "out_of_scope"], source="controlled_test_rule")
    base = AnsweringAgent(fake_model, ADS, None)
    before = [run_item(it, base, EV, use_repair=False) for it in items]
    assert validate_one(good, items, ADS, EV, before, fake_model)["keep"] is True
    rep = validate_one(risky.lessons[0], items, ADS, EV, before, fake_model)
    assert rep["keep"] is False and rep["unsupported_answers"] == ["t2"]