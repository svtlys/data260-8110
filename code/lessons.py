import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OOS_WORDS = ("school rating", "safe at night", "walk score", "bus stop")
ALL_CATEGORIES = ["rent", "pets", "utilities", "move_in", "out_of_scope"]

# failure pattern -> (categories the lesson applies to, correction text injected into the Answering Agent prompt)
TEMPLATES = {
    "stale_price": (["rent", "move_in"], "When the ad shows an old price and a new price (for example 'was $X, now $Y'), use the CURRENT (new) price. Mention the old price only as the previous price. For move-in costs use the current rent."),
    "missing_value": (["rent"], "Always state the exact monthly rent in dollars from the ad."),
    "wrong_total": (["move_in"], "For move-in cost, add the first month's CURRENT rent and the security deposit, and state the sum in dollars together with both parts."),
    "pet_restriction_omitted": (["pets"], "For pet questions list every pet type that is allowed, every pet type that is NOT allowed (say 'no dogs' etc.), and any pet fee. If the ad says pet-free, say that no pets are allowed."),
    "utilities_incomplete": (["utilities"], "List EVERY utility the ad says is included in the rent. Do not list utilities the tenant pays."),
    "unsupported_answer": (["out_of_scope"], "If the ad does not contain the requested information, reply exactly that the listing does not provide that information. Never guess or invent a value."),
}
# Deliberately harmful lesson used only to test the validation gate (source = controlled_test_rule).
RISKY_CORRECTION = "Always give a definite numeric answer, even if the listing does not say; use your best estimate."


def classify_question(question: str) -> str:
    """Return the question category (rent, pets, utilities, move_in, out_of_scope, other)."""
    q = question.lower()
    if any(w in q for w in OOS_WORDS):
        return "out_of_scope"
    if "move-in" in q or "total due" in q:
        return "move_in"
    if "pet" in q:
        return "pets"
    if "utilit" in q:
        return "utilities"
    return "rent" if "rent" in q else "other"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LessonStore:
    """A list of lessons (lesson_id, failure_pattern, correction, created_at, use_count + applies_to/source)."""

    def __init__(self, lessons: list[dict] | None = None) -> None:
        self.lessons: list[dict] = lessons or []

    @classmethod
    def load(cls, path: Path) -> "LessonStore":
        """Load lessons from a JSON file (empty store when the file is missing)."""
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else cls()

    def save(self, path: Path) -> None:
        """Write lessons to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.lessons, indent=2), encoding="utf-8")

    def add(self, pattern: str, correction: str, applies_to: list[str], source: str = "training_failures", **extra) -> dict | None:
        """Add a lesson unless one for the same pattern already exists."""
        if any(les["failure_pattern"] == pattern for les in self.lessons):
            return None
        lesson = {"lesson_id": f"lesson_{len(self.lessons) + 1:03d}", "failure_pattern": pattern, "correction": correction,
                  "created_at": _now(), "use_count": 0, "applies_to": applies_to, "source": source, **extra}
        self.lessons.append(lesson)
        return lesson

    def relevant(self, category: str) -> list[dict]:
        """Lessons that apply to a question category."""
        return [les for les in self.lessons if category in les["applies_to"]]

    def mark_used(self, lesson_ids: list[str]) -> None:
        """Increase use_count for the lessons that were put into a prompt."""
        for les in self.lessons:
            if les["lesson_id"] in lesson_ids:
                les["use_count"] += 1

    def copy(self) -> "LessonStore":
        """Independent in-memory copy (variant runs must not change the saved file)."""
        return LessonStore(copy.deepcopy(self.lessons))

    def without(self, lesson_id: str) -> "LessonStore":
        """Copy of the store without one lesson."""
        return LessonStore([copy.deepcopy(les) for les in self.lessons if les["lesson_id"] != lesson_id])


def lessons_from_failures(failures: list[dict], min_count: int = 2) -> LessonStore:
    """Create one lesson per failure pattern that occurred at least min_count times."""
    counts = Counter(f["pattern"] for f in failures)
    store = LessonStore()
    for pattern, n in counts.items():
        if n >= min_count and pattern in TEMPLATES:
            applies, text = TEMPLATES[pattern]
            ids = [f["id"] for f in failures if f["pattern"] == pattern]
            store.add(pattern, text, applies, evidence_count=n, evidence_ids=ids)
    return store