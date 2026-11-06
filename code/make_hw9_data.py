import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "hw09"

# id: (current_rent, previous_rent or None, deposit, pets_allowed, pets_not_allowed, pet_fee or None, utilities_included, tenant_pays)
FACTS = {
    "L201": (2250, 2400, 2250, ["cats"], ["dogs"], 300, ["water", "trash"], ["electricity", "internet"]),
    "L202": (3100, 3350, 3100, ["dogs"], ["cats"], 400, ["water", "trash", "internet"], ["electricity"]),
    "L203": (1950, None, 1500, [], ["pets"], None, ["water", "sewer", "trash"], ["electricity", "gas"]),
    "L204": (2675, 2800, 2675, ["cats", "dogs"], [], 500, ["water", "trash"], ["electricity", "gas", "internet"]),
    "L205": (2400, 2550, 2400, ["cats"], ["dogs"], 250, ["water"], ["electricity", "gas", "internet", "trash"]),
    "L206": (1800, None, 1800, ["dogs"], ["cats"], 350, ["water", "trash", "gas"], ["electricity"]),
    "L207": (3500, 3700, 3500, [], ["pets"], None, ["water", "trash", "internet"], ["electricity", "gas"]),
    "L208": (2150, 2290, 2000, ["cats"], ["dogs"], 200, ["water", "trash"], ["electricity"]),
    "L209": (2950, None, 2950, ["cats", "dogs"], [], 300, ["water", "sewer", "trash", "electricity"], ["internet"]),
    "L210": (1725, 1850, 1725, ["cats"], ["dogs"], 150, ["trash"], ["water", "electricity", "gas", "internet"]),
    "L211": (2825, 2975, 2825, [], ["pets"], None, ["water", "trash"], ["electricity", "internet"]),
    "L212": (2050, None, 2050, ["dogs"], ["cats"], 275, ["water", "trash", "sewer"], ["electricity", "gas"]),
}
HOODS = ["near Diridon Station", "in Willow Glen", "close to Santana Row", "by Lake Merritt", "in downtown Sunnyvale", "near Caltrain in Mountain View"]


def price_sentence(i: int, cur: int, prev: int | None) -> str:
    if prev is None:
        return f"Rent: ${cur:,}/month."
    styles = [f"Was ${prev:,}/mo - now ${cur:,}/mo!", f"Price reduced from ${prev:,} to ${cur:,} per month.", f"NEW LOW PRICE ${cur:,}/month (previously ${prev:,})."]
    return styles[i % 3]


def pet_sentence(allowed: list, not_allowed: list, fee: int | None) -> str:
    if not allowed:
        return "Pet-free building: no pets allowed."
    parts = [f"{' and '.join(allowed).capitalize()} welcome"]
    parts.append(f"(one-time ${fee} pet fee)" if fee else "")
    text = " ".join(p for p in parts if p) + "."
    if not_allowed:
        text += f" No {' or '.join(not_allowed)}."
    return "Pet-friendly building! " + text


def ad_text(i: int, code: str, facts: tuple) -> str:
    cur, prev, dep, allowed, not_allowed, fee, util, tenant = facts
    return (f"Bright apartment {HOODS[i % len(HOODS)]}. {price_sentence(i, cur, prev)} Security deposit ${dep:,}. "
            f"{pet_sentence(allowed, not_allowed, fee)} {', '.join(util).capitalize()} included; tenant pays {' and '.join(tenant)}. "
            f"12-month lease, available soon.")


def reference() -> dict:
    out = {}
    for code, (cur, prev, dep, allowed, not_allowed, fee, util, tenant) in FACTS.items():
        out[code] = {"listing_id": code, "current_rent": cur, "previous_rent": prev, "security_deposit": dep,
                     "move_in_total": cur + dep, "pets_allowed": allowed, "pets_not_allowed": not_allowed, "no_pets": not allowed,
                     "pet_fee": fee, "utilities_included": util, "tenant_pays": tenant}
    return out


def q(i: int, prefix: str, listing: str, text: str) -> dict:
    return {"id": f"{prefix}{i:02d}", "listing_id": listing, "question": text.replace("{L}", listing)}


TRAIN = [
    ("L201", "What is the current monthly rent for listing {L}?"), ("L202", "How much is rent per month at listing {L} right now?"),
    ("L205", "What is the monthly rent for listing {L} at the moment?"),
    ("L201", "What is the pet policy for listing {L}?"), ("L203", "Which pets are allowed at listing {L}, and are there any pet fees?"),
    ("L208", "Does listing {L} allow pets? Please include any fees or restrictions."),
    ("L205", "Which utilities are included in the rent at listing {L}?"), ("L207", "What utilities does the landlord pay at listing {L}?"),
    ("L204", "How much do I need to pay at move-in for listing {L} (first month's rent plus the security deposit)?"),
    ("L210", "What is the total due at move-in for listing {L}: first month's rent plus the security deposit?"),
    ("L203", "What is the school rating near listing {L}?"), ("L206", "Is the neighborhood around listing {L} safe at night?"),
]
VALID = [
    ("L203", "What is the current monthly rent for listing {L}?"), ("L204", "How much is rent per month at listing {L} right now?"),
    ("L207", "What is the monthly rent for listing {L} at the moment?"),
    ("L202", "What is the pet policy for listing {L}?"), ("L204", "Which pets are allowed at listing {L}, and are there any pet fees?"),
    ("L210", "Does listing {L} allow pets? Please include any fees or restrictions."),
    ("L201", "Which utilities are included in the rent at listing {L}?"), ("L208", "What utilities does the landlord pay at listing {L}?"),
    ("L201", "How much do I need to pay at move-in for listing {L} (first month's rent plus the security deposit)?"),
    ("L202", "What is the total due at move-in for listing {L}: first month's rent plus the security deposit?"),
    ("L209", "What is the walk score for listing {L}?"), ("L212", "How far is the nearest bus stop from listing {L}?"),
]
TEST = [
    ("L208", "What is the current monthly rent for listing {L}?"), ("L209", "How much is rent per month at listing {L} right now?"),
    ("L210", "What is the monthly rent for listing {L} at the moment?"), ("L211", "What is the current monthly rent for listing {L}?"),
    ("L212", "How much is rent per month at listing {L} right now?"),
    ("L205", "What is the pet policy for listing {L}?"), ("L206", "Which pets are allowed at listing {L}, and are there any pet fees?"),
    ("L207", "Does listing {L} allow pets? Please include any fees or restrictions."), ("L209", "What is the pet policy for listing {L}?"),
    ("L211", "Which pets are allowed at listing {L}, and are there any pet fees?"),
    ("L202", "Which utilities are included in the rent at listing {L}?"), ("L203", "What utilities does the landlord pay at listing {L}?"),
    ("L204", "Which utilities are included in the rent at listing {L}?"),
    ("L203", "How much do I need to pay at move-in for listing {L} (first month's rent plus the security deposit)?"),
    ("L205", "What is the total due at move-in for listing {L}: first month's rent plus the security deposit?"),
    ("L206", "How much do I need to pay at move-in for listing {L} (first month's rent plus the security deposit)?"),
    ("L208", "What is the total due at move-in for listing {L}: first month's rent plus the security deposit?"),
    ("L201", "What is the school rating near listing {L}?"), ("L205", "Is the neighborhood around listing {L} safe at night?"),
    ("L208", "What is the walk score for listing {L}?"),
]


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "reference_dataset.json").write_text(json.dumps(reference(), indent=2), encoding="utf-8")
    (DATA / "listing_ads.json").write_text(json.dumps({c: ad_text(i, c, f) for i, (c, f) in enumerate(FACTS.items())}, indent=2), encoding="utf-8")
    for name, prefix, rows in (("training_data.json", "tr", TRAIN), ("validation_data.json", "va", VALID), ("test_data.json", "te", TEST)):
        (DATA / name).write_text(json.dumps([q(i, prefix, lid, t) for i, (lid, t) in enumerate(rows, 1)], indent=2), encoding="utf-8")
    print(f"wrote datasets to {DATA}")


if __name__ == "__main__":
    main()