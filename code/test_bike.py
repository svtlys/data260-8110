import sqlite3
import tempfile
from pathlib import Path

import bike_costs
import bike_tools as bt

CSV = """ride_id,rideable_type,started_at,ended_at
r1,classic_bike,2024-01-02 08:00:00,2024-01-02 08:10:00
r2,electric_bike,2024-01-09 09:00:00,2024-01-09 09:20:00
r3,classic_bike,2024-02-03 10:00:00,2024-02-03 10:30:00
bad,classic_bike,not a date,2024-02-03 10:30:00
"""
PAGE = "<html><body><h1>Pricing</h1><p>" + "Single ride costs 1.00 unlock plus 0.20 per minute. " * 6 + \
       "</p><p>Monthly membership costs 15.00 per month with 30 free minutes per ride.</p></body></html>"
PARAMS = {"payg_unlock": 1.0, "payg_per_min_classic": 0.2, "member_monthly": 15.0}


def _conn() -> sqlite3.Connection:
    conn, _ = bt.load_trips(CSV)
    return conn


def test_load_trips_skips_bad_rows() -> None:
    conn, report = bt.load_trips(CSV)
    assert conn.execute("select count(*) from trips").fetchone()[0] == 3
    assert report["rows_loaded"] == 3


def test_select_works_and_envelope() -> None:
    out = bt.csv_sql("SELECT count(*) AS n FROM trips", _conn())
    assert out["success"] and out["data"]["rows"][0]["n"] == 3


def test_blocks_writes_ddl_multi_statement() -> None:
    conn = _conn()
    for sql in ("DELETE FROM trips", "DROP TABLE trips", "UPDATE trips SET month='x'",
                "INSERT INTO trips(ride_id) VALUES('z')", "SELECT 1; DROP TABLE trips",
                "PRAGMA writable_schema=1", "ATTACH DATABASE 'x.db' AS x", "SELECT 1 /* hi */"):
        out = bt.csv_sql(sql, conn)
        assert not out["success"], sql
    assert conn.execute("select count(*) from trips").fetchone()[0] == 3


def test_unenforced_mode_allows_delete() -> None:
    conn = _conn()
    assert bt.csv_sql("DELETE FROM trips", conn, enforce=False)["success"]
    assert conn.execute("select count(*) from trips").fetchone()[0] == 0


def test_calculator_whitelist_and_no_eval() -> None:
    assert bt.calculator("1 + 2 * 3")["data"]["value"] == 7.0
    for bad in ("__import__('os')", "2**9999", "1/0", "abc", "", "(1+"):
        assert not bt.calculator(bad)["success"], bad


def test_policy_retriever_local_fetcher_and_cache() -> None:
    cache: dict = {}
    calls = []

    def fetcher(url):
        calls.append(url)
        return PAGE, url

    out = bt.policy_retriever("https://example.test/p", "monthly membership price", cache=cache, fetcher=fetcher)
    assert out["success"] and out["data"]["passages"]
    bt.policy_retriever("https://example.test/p", "unlock", cache=cache, fetcher=fetcher)
    assert len(calls) == 1


def test_policy_retriever_rejects_bad_input_and_file_outside_roots() -> None:
    assert not bt.policy_retriever("ftp://x", "q", cache={})["success"]
    assert not bt.policy_retriever("https://x", "", cache={}, fetcher=lambda u: (PAGE, u))["success"]
    with tempfile.TemporaryDirectory() as tmp:
        out = bt.policy_retriever("file:///etc/passwd", "root", cache={}, allowed_roots=(tmp,))
        assert not out["success"]


def test_snapshot_hash_matches_file() -> None:
    import hashlib
    cache: dict = {}
    bt.policy_retriever("https://example.test/p", "price", cache=cache, fetcher=lambda u: (PAGE, u))
    with tempfile.TemporaryDirectory() as tmp:
        meta = bt.save_snapshot(cache["https://example.test/p"], tmp, "t")
        digest = hashlib.sha256((Path(tmp) / meta["text_file"]).read_bytes()).hexdigest()
        assert digest == meta["sha256"]


def test_costs_and_decision() -> None:
    rides = bt.read_rides(_conn())
    p, err = bike_costs.clean_params(PARAMS)
    assert err is None
    out = bike_costs.recompute_costs(rides, p)
    assert out["months"] == 2 and out["member_fees"] == 30.0
    assert round(out["payg_total"], 2) == round(3 * 1.0 + 0.2 * (10 + 20 + 30), 2)
    assert out["cheaper"] == "pay_per_use"
    assert bike_costs.decision_label("membership") == "Buy Monthly Membership"


def test_clean_params_rejects_bad_values() -> None:
    assert bike_costs.clean_params({"payg_unlock": 1})[1]
    assert bike_costs.clean_params({**PARAMS, "member_monthly": -1})[1]
    assert bike_costs.clean_params({**PARAMS, "member_monthly": "15"})[1]


def test_membership_price_check_rejects_restricted_price() -> None:
    page = "$120/year\nUniversity students and staff: annual membership for just $25.\n$5 annual memberships for qualifying residents."
    assert bike_costs.check_membership_param(10.0, page) is None
    assert "not a general-public" in bike_costs.check_membership_param(2.08, page)
    assert bike_costs.check_membership_param(10.0, "no prices here") is None