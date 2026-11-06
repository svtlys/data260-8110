C_MISS = 0.01
C_HIT = 0.0001
C_FALSE_HIT = 5.00


def total_cost(hits: int, false_hits: int, misses: int, c_miss: float = C_MISS, c_hit: float = C_HIT, c_false_hit: float = C_FALSE_HIT) -> float:
    """Dollar cost of one threshold's results over the test set."""
    return round(misses * c_miss + (hits - false_hits) * c_hit + false_hits * (c_hit + c_false_hit), 4)


def choose_threshold(rows: list, **costs) -> dict:
    """rows: [{'threshold', 'hits', 'false_hits', 'misses'}]. Lowest total cost wins; ties go to the HIGHER threshold (safer)."""
    scored = [{**r, "total_cost": total_cost(r["hits"], r["false_hits"], r["misses"], **costs)} for r in rows]
    return min(scored, key=lambda r: (r["total_cost"], -r["threshold"]))


def sensitivity(rows: list, false_hit_costs=(0.5, 5.0, 50.0, 500.0)) -> list:
    """Which threshold would be chosen if a false hit cost something else (the miss cost stays fixed)."""
    return [{"c_false_hit": c, "best_threshold": choose_threshold(rows, c_false_hit=c)["threshold"]} for c in false_hit_costs]