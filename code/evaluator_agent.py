import re

from lessons import classify_question

ABSTAIN = ("not provided", "not listed", "no information", "does not provide", "doesn't provide", "does not say", "does not mention",
           "not mentioned", "don't have", "do not have", "cannot", "can't", "not available", "unknown", "not specified", "not stated")
NEGATION = ("no ", "not ", "n't", "pet-free", "without", "prohibited", "none")
PREV_MARKERS = ("was", "previous", "previously", "formerly", "reduced", "from", "old", "originally", "before")


def numbers(text: str) -> set[int]:
    """All integers in the text (commas in thousands removed)."""
    return {int(m.replace(",", "")) for m in re.findall(r"\d[\d,]*", text) if m.replace(",", "")}


def _has_word(text: str, words: tuple) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _ok() -> dict:
    return {"verdict": "PASS", "pattern": None, "explanation": "Answer matches the reference data.", "feedback": ""}


def _fail(pattern: str, explanation: str, feedback: str) -> dict:
    return {"verdict": "REVISE", "pattern": pattern, "explanation": explanation, "feedback": feedback}


def _negated(text: str, token: str) -> bool:
    before = rf"(no|not|n't|without)\W+(?:\w+\W+){{0,3}}{token}"
    after = rf"{token}\W+(?:\w+\W+){{0,3}}(not|prohibited|n't|forbidden|disallowed)"
    return bool(re.search(before, text) or re.search(after, text))


class Evaluator:
    """Deterministic rule-based Evaluator Agent; the reference dataset is its only source of truth."""

    def __init__(self, reference: dict) -> None:
        self.reference = reference

    def evaluate(self, item: dict, answer: str) -> dict:
        """Return {verdict, pattern, explanation, feedback} for one answer."""
        ref = self.reference[item["listing_id"]]
        category = classify_question(item["question"])
        rule = {"rent": self._rent, "move_in": self._move_in, "pets": self._pets, "utilities": self._utilities, "out_of_scope": self._oos}.get(category)
        return rule(ref, answer.lower()) if rule else _fail("unknown_category", "Question type not supported.", "Rephrase the answer.")

    def _rent(self, ref: dict, text: str) -> dict:
        cur, prev, nums = ref["current_rent"], ref["previous_rent"], numbers(text)
        if cur not in nums:
            if prev and prev in nums:
                return _fail("stale_price", "Answer gives the old price instead of the current rent.",
                             f"The listing's CURRENT rent is ${cur:,}/month; ${prev:,} is the previous price. State ${cur:,} as the rent.")
            return _fail("missing_value", "Answer does not state the monthly rent.", f"State the monthly rent. The current rent is ${cur:,}/month.")
        if prev and prev in nums and not _has_word(text, PREV_MARKERS):
            return _fail("stale_price", "Answer mixes the old and current price without saying which is current.",
                         f"Say that the current rent is ${cur:,}/month and that ${prev:,} was the previous price.")
        return _ok()

    def _move_in(self, ref: dict, text: str) -> dict:
        total, nums = ref["move_in_total"], numbers(text)
        if total in nums:
            return _ok()
        stale = ref["previous_rent"] and ref["previous_rent"] + ref["security_deposit"] in nums
        fb = f"Move-in total = current rent ${ref['current_rent']:,} + security deposit ${ref['security_deposit']:,} = ${total:,}. State ${total:,}."
        if stale:
            return _fail("stale_price", "Move-in total was computed with the old rent.", fb)
        return _fail("wrong_total", "Move-in total is missing or wrong.", fb)

    def _pets(self, ref: dict, text: str) -> dict:
        if ref["no_pets"]:
            if any(n in text for n in NEGATION) and "pet" in text:
                return _ok()
            return _fail("pet_restriction_omitted", "Answer does not say that no pets are allowed.", "The building is pet-free: say clearly that no pets are allowed.")
        missing = [p for p in ref["pets_allowed"] if p not in text]
        missing += [f"restriction on {p}" for p in ref["pets_not_allowed"] if p not in text or not _negated(text, p)]
        if ref["pet_fee"] and ref["pet_fee"] not in numbers(text):
            missing.append(f"pet fee ${ref['pet_fee']}")
        if not missing:
            return _ok()
        allowed, banned = " and ".join(ref["pets_allowed"]), " and ".join(ref["pets_not_allowed"]) or "none"
        return _fail("pet_restriction_omitted", f"Answer is incomplete: missing {', '.join(missing)}.",
                     f"Allowed: {allowed}; NOT allowed: {banned}; pet fee: ${ref['pet_fee']}. Mention all of these.")

    def _utilities(self, ref: dict, text: str) -> dict:
        missing = [u for u in ref["utilities_included"] if u not in text]
        if not missing:
            return _ok()
        return _fail("utilities_incomplete", f"Answer omits included utilities: {', '.join(missing)}.",
                     f"Included utilities are: {', '.join(ref['utilities_included'])}. List all of them.")

    def _oos(self, ref: dict, text: str) -> dict:
        if any(m in text for m in ABSTAIN):
            return _ok()
        return _fail("unsupported_answer", "The listing does not contain this information, but the answer gives a value.",
                     "The ad does not say. Reply that the listing does not provide this information; do not guess.")