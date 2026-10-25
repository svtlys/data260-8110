import argparse
import csv
import io
import json
import logging
import random
import sys
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bike_costs import clean_params, recompute_costs  # noqa: E402
from bike_tools import canonical_columns, parse_dt  # noqa: E402

logger = logging.getLogger("prepare_bike_data")
N_ROWS = 520
SEED = 8110
MARGIN = 0.25
PAYG_MARGIN = 0.10
MAX_WEEKS = 1040
BASE_MONDAY = datetime(2024, 1, 1)
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _open_text(path: Path) -> str:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            return z.read(name).decode("utf-8-sig", errors="replace")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def read_trips(paths: list) -> tuple:
    """(header names, start column, end column, type column or None, enriched rows)."""
    names, rows, start_col, end_col, type_col = None, [], None, None, None
    for path in paths:
        reader = csv.DictReader(io.StringIO(_open_text(Path(path))))
        mapping = canonical_columns(reader.fieldnames)
        inv = {v: k for k, v in mapping.items()}
        names = reader.fieldnames
        start_col, end_col, type_col = inv.get("started_at"), inv.get("ended_at"), inv.get("rideable_type")
        for raw in reader:
            start, end = parse_dt(raw.get(start_col)), parse_dt(raw.get(end_col))
            if start and end and 0 < (end - start).total_seconds() / 60 <= 180:
                electric = type_col is not None and "electric" in str(raw.get(type_col, "")).lower()
                rows.append({"raw": raw, "start": start, "minutes": (end - start).total_seconds() / 60,
                             "electric": electric})
    return names, start_col, end_col, rows


def _ride(row: dict, start: datetime) -> dict:
    return {"duration_min": row["minutes"], "is_electric": int(row["electric"]),
            "week_start": (start - timedelta(days=start.weekday())).strftime("%Y-%m-%d"), "month": start.strftime("%Y-%m")}


def pick_membership(rows: list, rng: random.Random) -> list:
    """N real rides from the busiest calendar month, long rides first."""
    month = Counter(r["start"].strftime("%Y-%m") for r in rows).most_common(1)[0][0]
    pool = [r for r in rows if r["start"].strftime("%Y-%m") == month]
    long_rides = [r for r in pool if r["minutes"] >= 15]
    pool = long_rides if len(long_rides) >= N_ROWS else sorted(pool, key=lambda r: -r["minutes"])[:N_ROWS * 3]
    return sorted(rng.sample(pool, N_ROWS), key=lambda r: r["start"])


def pick_short(rows: list, rng: random.Random) -> list:
    """N short real rides (classic bikes preferred)."""
    short = [r for r in rows if 1 <= r["minutes"] <= 4 and not r["electric"]]
    short = short if len(short) >= N_ROWS else sorted(rows, key=lambda r: r["minutes"])[:N_ROWS * 3]
    return rng.sample(short, N_ROWS)


def redate(sample: list, weeks: int, seed: int) -> list:
    """Same rides, new dates spread over `weeks` weeks. Time of day and duration are unchanged."""
    rng = random.Random(seed)
    out = []
    for row in sample:
        day = BASE_MONDAY + timedelta(days=rng.randrange(weeks * 7))
        start = day.replace(hour=row["start"].hour, minute=row["start"].minute, second=row["start"].second)
        out.append({**row, "start": start})
    return sorted(out, key=lambda r: r["start"])


def find_weeks(sample: list, params: dict) -> tuple:
    """Smallest spread (in weeks) where pay-per-use beats membership by PAYG_MARGIN."""
    for weeks in range(26, MAX_WEEKS + 1, 13):
        dated = redate(sample, weeks, SEED)
        costs = recompute_costs([_ride(r, r["start"]) for r in dated], params)
        if costs["payg_total"] <= (1 - PAYG_MARGIN) * costs["member_total"]:
            return weeks, dated, costs
    raise SystemExit("pay-per-use never wins by 10% within 20 years under these prices; check pricing_params.json")


def write_csv(path: Path, names: list, start_col: str, end_col: str, rows: list) -> None:
    """Write rides back with the original headers; start/end are rewritten from the chosen dates."""
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for r in rows:
            end = r["start"] + timedelta(minutes=r["minutes"])
            writer.writerow({**r["raw"], start_col: r["start"].strftime(TIME_FMT), end_col: end.strftime(TIME_FMT)})


def main() -> None:
    """Build both scenario files."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--out", default="data/bike")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    params, err = clean_params(json.loads(Path(args.params).read_text()))
    if err:
        raise SystemExit(err)
    names, sc, ec, rows = read_trips(args.input)
    rng = random.Random(SEED)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    member_rows = pick_membership(rows, rng)
    member_costs = recompute_costs([_ride(r, r["start"]) for r in member_rows], params)
    if member_costs["member_total"] > (1 - MARGIN) * member_costs["payg_total"]:
        raise SystemExit("membership does not win by 25% on the heavy month; check pricing_params.json")
    weeks, dated, short_costs = find_weeks(pick_short(rows, rng), params)
    write_csv(out / "bike_membership_wins.csv", names, sc, ec, member_rows)
    write_csv(out / "bike_payperuse_wins.csv", names, sc, ec, dated)
    notes = (f"# Scenario files (made by prepare_bike_data.py, seed {SEED})\n\n"
             f"Source: {', '.join(Path(p).name for p in args.input)} ({len(rows)} usable rides).\n\n"
             f"- bike_membership_wins.csv: {N_ROWS} real rides from one month, long rides first; real timestamps.\n"
             f"  Costs with the prices in pricing_params.json: pay per use {member_costs['payg_total']}, "
             f"membership {member_costs['member_total']}.\n"
             f"- bike_payperuse_wins.csv: {N_ROWS} real short rides with DATES RE-ASSIGNED across {weeks} weeks "
             f"(time of day and durations unchanged; {round(weeks / 4.345)} months, which is long because each ride costs at least about $1.15 against $10/month). Costs: pay per use {short_costs['payg_total']}, "
             f"membership {short_costs['member_total']}.\n\n"
             "Public trip data has no rider id, so treating each file as one rider is an assumption.\n")
    (out / "SCENARIOS.md").write_text(notes)
    logger.info("%s", notes)


if __name__ == "__main__":
    main()