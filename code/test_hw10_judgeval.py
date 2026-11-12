import os
import tempfile
from pathlib import Path

import run_judge_validation as rjv


def rows(pairs):
    return [{"case_id": f"c{i}", "human": h, "runs": list(r)} for i, (h, r) in enumerate(pairs)]


def test_perfect_agreement_and_zero_difference():
    a = rjv.agreement([1, 2, 3, 4, 5], [1.0, 2.0, 3.0, 4.0, 5.0])
    assert a["spearman_rho"] == 1.0 and a["mean_abs_difference"] == 0.0


def test_inverted_ranking_gives_minus_one_and_constant_scores_are_undefined():
    assert rjv.agreement([1, 2, 3, 4], [4, 3, 2, 1])["spearman_rho"] == -1.0
    constant = rjv.agreement([1, 2, 3, 4], [3, 3, 3, 3])
    assert constant["spearman_rho"] is None and constant["mean_abs_difference"] == 1.0


def test_mean_absolute_difference_and_signed_bias():
    a = rjv.agreement([5, 3, 1], [4, 3, 3])
    assert a["mean_abs_difference"] == 1.0 and a["mean_signed_difference_judge_minus_human"] == 0.3333


def test_repeatability_identical_runs_never_change():
    r = rjv.repeatability([[4.0, 4.0, 4.0], [2.0, 2.0, 2.0]])
    assert r["cases_with_any_change"] == 0 and r["mean_abs_change"] == 0 and r["max_abs_change"] == 0 and r["pairwise_comparisons"] == 6


def test_repeatability_counts_changed_cases_and_sizes():
    r = rjv.repeatability([[4.0, 4.0, 4.0], [2.0, 3.0, 2.0], [5.0, 3.0, 5.0], [1.0, 1.0, 1.0]])
    assert r["cases_with_any_change"] == 2 and r["pct_cases_with_any_change"] == 50.0
    assert r["max_abs_change"] == 2.0 and r["pairs_that_differ"] == 4 and r["mean_abs_change"] == round((0 + 1 + 1 + 0 + 2 + 2 + 0) / 12, 4)


def test_rounding_hides_small_changes():
    runs = [[3.6, 3.8, 3.7]]
    assert rjv.repeatability(runs)["cases_with_any_change"] == 1 and rjv.repeatability(runs, rounded=True)["cases_with_any_change"] == 0


def test_csv_roundtrip_recomputes_the_same_statistics():
    data = rows([(5, (4.5, 4.5, 4.75)), (3, (3.0, 3.0, 3.0)), (1, (2.0, 1.75, 2.0)), (4, (4.0, 4.5, 4.0))])
    before = rjv.compute_stats(data)
    tmp = Path(tempfile.mkdtemp())
    rjv.CSV_PATH, rjv.RAW = tmp / "judge_validation_cases.csv", tmp
    raw = [{"case_id": r["case_id"], "variant": "general", "human_label": r["human"], "runs": r["runs"], "reasons": ["why"]} for r in data]
    rjv.write_cases_csv(raw)
    assert rjv.compute_stats(rjv.read_cases_csv(rjv.CSV_PATH)) == before and os.path.exists(rjv.CSV_PATH)


def test_cases_with_a_failed_call_are_left_out_of_the_statistics():
    tmp = Path(tempfile.mkdtemp())
    rjv.CSV_PATH, rjv.RAW = tmp / "c.csv", tmp
    raw = [{"case_id": "a", "variant": "g", "human_label": 4, "runs": [4.0, 4.0, 4.0], "reasons": ["x"]},
           {"case_id": "b", "variant": "g", "human_label": 2, "runs": [2.0, None, 2.0], "reasons": ["x"]}]
    rjv.write_cases_csv(raw)
    assert [r["case_id"] for r in rjv.read_cases_csv(rjv.CSV_PATH)] == ["a"]