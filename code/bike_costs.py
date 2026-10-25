import math
import re

REQUIRED = ("payg_unlock", "payg_per_min_classic", "member_monthly")
OPTIONAL_DEFAULTS = {"payg_per_min_electric": None, "member_included_min": 0.0,
                     "member_overage_per_min": 0.0, "member_per_min_electric": None}


def clean_params(raw) -> tuple:
    """Return (params, None) or (None, error). Numbers only, never negative."""
    if not isinstance(raw, dict):
        return None, "pricing_parameters must be an object"
    params = {}
    for key in REQUIRED + tuple(OPTIONAL_DEFAULTS):
        value = raw.get(key)
        if value is None and key in REQUIRED:
            return None, f"pricing_parameters is missing {key}"
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                return None, f"{key} must be a non-negative number"
            params[key] = float(value)
    params.setdefault("payg_per_min_electric", params["payg_per_min_classic"])
    params.setdefault("member_included_min", 0.0)
    params.setdefault("member_overage_per_min", 0.0)
    params.setdefault("member_per_min_electric", params["member_overage_per_min"])
    return params, None


def ride_costs(minutes: float, electric: bool, p: dict) -> tuple:
    """(pay-per-use cost, membership residual cost) of one ride."""
    payg = p["payg_unlock"] + minutes * (p["payg_per_min_electric"] if electric else p["payg_per_min_classic"])
    if electric:
        residual = minutes * p["member_per_min_electric"]
    else:
        residual = max(0.0, minutes - p["member_included_min"]) * p["member_overage_per_min"]
    return payg, residual


def count_months(rides: list) -> int:
    """Calendar months from the first to the last ride, inclusive."""
    keys = sorted({r["month"] for r in rides})
    if not keys:
        return 0
    (y1, m1), (y2, m2) = (tuple(map(int, keys[0].split("-"))), tuple(map(int, keys[-1].split("-"))))
    return (y2 - y1) * 12 + (m2 - m1) + 1


def _weekly(rides: list, p: dict) -> list:
    weeks: dict = {}
    for r in rides:
        payg, residual = ride_costs(r["duration_min"], bool(r["is_electric"]), p)
        w = weeks.setdefault(r["week_start"], {"rides": 0, "minutes": 0.0, "payg": 0.0, "residual": 0.0})
        w["rides"] += 1
        w["minutes"] += r["duration_min"]
        w["payg"] += payg
        w["residual"] += residual
    return [{"week_start": k, "rides": v["rides"], "avg_minutes": round(v["minutes"] / v["rides"], 2),
             "payg_spend": round(v["payg"], 2), "member_residual": round(v["residual"], 2)}
            for k, v in sorted(weeks.items())]


def _break_even(monthly: float, savings: float, units: float) -> float | None:
    return round(monthly / (savings / units), 2) if savings > 0 and units > 0 else None


def recompute_costs(rides: list, p: dict) -> dict:
    """Totals, break-even and the weekly table for the trips under parameters p."""
    if not rides:
        return {"error": "there are no rides to cost"}
    pairs = [ride_costs(r["duration_min"], bool(r["is_electric"]), p) for r in rides]
    payg_total = sum(a for a, _ in pairs)
    residual = sum(b for _, b in pairs)
    months = count_months(rides)
    fees = months * p["member_monthly"]
    savings = payg_total - residual
    minutes = sum(r["duration_min"] for r in rides)
    return {
        "rides": len(rides), "months": months, "total_minutes": round(minutes, 1),
        "payg_total": round(payg_total, 2), "member_fees": round(fees, 2),
        "member_residual": round(residual, 2), "member_total": round(fees + residual, 2),
        "cheaper": "membership" if fees + residual < payg_total else "pay_per_use",
        "difference": round(abs(payg_total - fees - residual), 2),
        "actual_rides_per_month": round(len(rides) / months, 2),
        "actual_minutes_per_month": round(minutes / months, 1),
        "break_even_rides_per_month": _break_even(p["member_monthly"], savings / months, len(rides) / months),
        "break_even_minutes_per_month": _break_even(p["member_monthly"], savings / months, minutes / months),
        "weekly": _weekly(rides, p),
    }


def decision_label(cheaper: str) -> str:
    """The two allowed decision strings."""
    return "Buy Monthly Membership" if cheaper == "membership" else "Pay Per Ride/Minute"


RESTRICTED = re.compile(r"student|staff|universit|qualif|resident|eligib|low[- ]income|senior|veteran|employee", re.I)
YEARLY = re.compile(r"year|annual", re.I)
DOLLARS = re.compile(r"\$\s?(\d+(?:\.\d+)?)")


def membership_prices(page_text: str) -> list:
    """Yearly or monthly membership prices on the page as (monthly dollars, line, restricted)."""
    found = []
    for line in (page_text or "").split("\n"):
        for amount in DOLLARS.findall(line):
            if re.search(r"month", line, re.I) and not YEARLY.search(line):
                found.append((float(amount), line.strip(), bool(RESTRICTED.search(line))))
            elif YEARLY.search(line):
                found.append((round(float(amount) / 12, 2), line.strip(), bool(RESTRICTED.search(line))))
    return found


def check_membership_param(value, page_text: str) -> str | None:
    """Problem text when member_monthly is not a general-public price found on the page, else None."""
    general = [(m, line) for m, line, restricted in membership_prices(page_text) if not restricted]
    if not general or not isinstance(value, (int, float)):
        return None
    if any(abs(value - m) <= 0.01 for m, _ in general):
        return None
    listed = "; ".join(f"'{line[:80]}' = ${m:.2f}/month" for m, line in general[:3])
    return (f"member_monthly {value} is not a general-public membership price on the page. General-public prices found "
            f"(yearly price / 12): {listed}. Prices that mention students, staff or qualifying residents must not be used.")