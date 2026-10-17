import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_PATH = ROOT / "AGENT.md"
MEMORY_PATH = ROOT / "MEMORY.md"
MAX_CONTENT_LINES = 40
MAX_AGE = timedelta(hours=24)
NOTES_SECTION = "Resolved contradictions"
DREAM_SECTION = "Learned from conversations"
TS_RE = re.compile(r"<!--\s*last_consolidated:\s*([^\s>]+)\s*-->")
FACT_RE = re.compile(r"^\s*-\s*(?:\[(\d{4}-\d{2}-\d{2})\]\s*)?(.+?)\s*$")


class ConsolidationError(Exception):
    """Raised when consolidation cannot be done safely (the file is left untouched)."""


# ------------------------------------------------------------------ loading
def load_text(path: Path) -> str:
    """Return the file's text, or an empty string if it does not exist."""
    return Path(path).read_text() if Path(path).exists() else ""


def _iter_lines(text: str):
    """Yield (line_no, line, is_comment) with support for multi-line HTML comments."""
    in_comment = False
    for no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if in_comment:
            yield no, line, True
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            if "-->" not in s:
                in_comment = True
            yield no, line, True
            continue
        yield no, line, False


def content_lines(text: str) -> list:
    """Non-empty, non-comment lines (the lines counted by the 40-line rule)."""
    return [ln for _, ln, c in _iter_lines(text) if not c and ln.strip()]


def read_last_consolidated(text: str):
    """Parse '<!-- last_consolidated: ISO -->'; None if missing or invalid."""
    m = TS_RE.search(text)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1)).astimezone()
    except ValueError:
        return None


def needs_consolidation(text: str, now=None):
    """-> (needed, reasons). Needed if >40 content lines or last consolidation >24h ago."""
    now = now or datetime.now().astimezone()
    reasons = []
    n = len(content_lines(text))
    if n > MAX_CONTENT_LINES:
        reasons.append(f"{n} non-empty, non-comment lines (limit {MAX_CONTENT_LINES})")
    ts = read_last_consolidated(text)
    if ts is None:
        reasons.append("no valid last_consolidated timestamp")
    elif now - ts > MAX_AGE:
        hours = (now - ts).total_seconds() / 3600
        reasons.append(f"last consolidated {hours:.1f} h ago (limit 24 h)")
    return bool(reasons), reasons


def build_system_prompt(agent_text: str, memory_text: str) -> str:
    """Combine AGENT.md and MEMORY.md into one system prompt."""
    parts = [agent_text.strip() or "(no AGENT.md found)",
             "---\n# Long-term memory (MEMORY.md)\n"
             "Durable facts learned in earlier conversations. Treat them as true unless "
             "the user corrects them.\n" + (memory_text.strip() or "(memory is empty)")]
    return "\n\n".join(parts)


def load_system_prompt(agent_path=AGENT_PATH, memory_path=MEMORY_PATH) -> str:
    """Load both Markdown files and build the system prompt."""
    return build_system_prompt(load_text(agent_path), load_text(memory_path))


# ------------------------------------------------------------------ parsing
@dataclass
class Fact:
    section: str
    date: str
    text: str
    line_no: int

    def render(self) -> str:
        """The fact as a Markdown bullet."""
        return f"- [{self.date}] {self.text}" if self.date else f"- {self.text}"


def parse_memory(text: str):
    """-> (facts, notes). Facts are '- ' bullets; bullets under 'Resolved contradictions' are notes."""
    facts, notes, section = [], [], "General"
    for no, line, is_comment in _iter_lines(text):
        s = line.strip()
        if is_comment or not s:
            continue
        if s.startswith("## "):
            section = s[3:].strip()
        elif s.startswith("#"):
            continue
        else:
            m = FACT_RE.match(line)
            if not m:
                continue
            if section == NOTES_SECTION:
                notes.append(s)
            else:
                facts.append(Fact(section, m.group(1) or "", m.group(2), no))
    return facts, notes


def _tokens(text: str) -> set:
    t = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    return set(re.findall(r"[a-z0-9]+", t))


def similar(a: str, b: str) -> bool:
    """Duplicate test: same word set, or Jaccard >= 0.8 with identical numbers."""
    ta, tb = _tokens(a), _tokens(b)
    if ta == tb:
        return True
    nums = lambda s: {x for x in s if x.isdigit()}
    if nums(ta) != nums(tb) or not (ta | tb):
        return False
    return len(ta & tb) / len(ta | tb) >= 0.8


def dedupe(facts: list):
    """Merge duplicates. -> (kept, merges) where merges = [(kept_fact, [removed...])]."""
    groups = []
    for f in facts:
        for g in groups:
            if similar(g[0].text, f.text):
                g.append(f)
                break
        else:
            groups.append([f])
    kept, merges = [], []
    for g in groups:
        rep = max(g, key=lambda x: (x.date, -x.line_no))
        first = min(g, key=lambda x: x.line_no)
        merged = Fact(first.section, rep.date, first.text, first.line_no)  # original wording, latest date
        kept.append(merged)
        if len(g) > 1:
            merges.append((merged, g))
    kept.sort(key=lambda x: x.line_no)
    return kept, merges


# ------------------------------------------------------------------ contradictions
def _parse_json(text: str):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))


def detect_contradictions(facts: list, llm, model="qwen3:8b", retries=3) -> list:
    """Ask the model for pairs of fact indexes (0-based) that cannot both be true."""
    numbered = "\n".join(f"{i + 1}. {f.render()[2:]}" for i, f in enumerate(facts))
    prompt = ("Below is a numbered list of facts about ONE user. Find pairs of facts that directly "
              "contradict each other: they give different values for the same thing and cannot "
              "both be true at the same time. Do not list facts that are merely about different "
              "topics.\n\n" + numbered + "\n\nReply with ONLY JSON like "
              '{"contradictions": [[1, 5], [2, 9]]} using the numbers above, or '
              '{"contradictions": []} if there are none.')
    last_err = None
    for _ in range(retries):
        out = llm("You are a careful fact checker.", [{"role": "user", "content": prompt}], model)
        try:
            raw = _parse_json(out["text"])["contradictions"]
            pairs = set()
            for a, b in raw:
                a, b = int(a) - 1, int(b) - 1
                if a != b and 0 <= a < len(facts) and 0 <= b < len(facts):
                    pairs.add((min(a, b), max(a, b)))
            return sorted(pairs)
        except (ValueError, KeyError, TypeError) as e:
            last_err = e
    raise ConsolidationError(f"could not parse contradiction list after {retries} tries: {last_err}")


def _clusters(n: int, pairs: list) -> list:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in pairs:
        parent[find(a)] = find(b)
    groups = {}
    for i in {i for p in pairs for i in p}:
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for g in groups.values()]


# ------------------------------------------------------------------ consolidation
@dataclass
class Result:
    new_text: str
    log_md: str
    lines_before: int
    lines_after: int
    content_before: int
    content_after: int
    facts_before: int
    facts_after: int
    duplicates_merged: int
    contradictions_resolved: int
    needs_review: int
    detected_pairs: list = field(default_factory=list)


def render_memory(facts: list, notes: list, stamp=None) -> str:
    """Write a MEMORY.md from facts (grouped by section) and resolved-contradiction notes."""
    out = []
    if stamp:
        out.append(f"<!-- last_consolidated: {stamp.isoformat(timespec='seconds')} -->")
    out.append("# MEMORY.md")
    order = []
    for f in facts:
        if f.section not in order:
            order.append(f.section)
    for sec in order:
        out += ["", f"## {sec}"] + [f.render() for f in facts if f.section == sec]
    if notes:
        out += ["", f"## {NOTES_SECTION}"] + notes
    return "\n".join(out) + "\n"


def consolidate_text(text: str, llm, now=None, model="qwen3:8b") -> Result:
    """Merge duplicates, resolve contradictions (newest wins, undated -> NEEDS REVIEW), log everything."""
    now = now or datetime.now().astimezone()
    facts, old_notes = parse_memory(text)
    kept, merges = dedupe(facts)
    pairs = detect_contradictions(kept, llm, model) if len(kept) > 1 else []
    notes, log, review = list(old_notes), [], 0
    drop = set()
    for cl in _clusters(len(kept), pairs):
        members = [kept[i] for i in cl]
        dates = [m.date for m in members]
        top = max(dates)
        if all(dates) and dates.count(top) == 1:
            win = next(m for m in members if m.date == top)
            for i in cl:
                if kept[i] is not win:
                    lose = kept[i]
                    drop.add(i)
                    notes.append(f'- Kept "{win.render()[2:]}" over "{lose.render()[2:]}" '
                                 f"(newest date wins: {win.date} > {lose.date})")
                    log.append(f"| resolved | KEPT: {win.render()[2:]} | SUPERSEDED: {lose.render()[2:]} "
                               f"| newest date wins |")
        else:
            review += 1
            for i in cl:
                if "NEEDS REVIEW" not in kept[i].text:
                    kept[i].text += " (NEEDS REVIEW: conflicts with another entry; dates unclear)"
            log.append("| NEEDS REVIEW | " + " ; ".join(m.render()[2:] for m in members) +
                       " | | missing or tied dates; both kept |")
    final = [k for i, k in enumerate(kept) if i not in drop]
    notes = list(dict.fromkeys(notes))
    new_text = render_memory(final, notes, now)
    dup_removed = sum(len(r) - 1 for _, r in merges)
    lines = ["# Consolidation log", "", f"Run at {now.isoformat(timespec='seconds')}", "",
             f"- Facts before: {len(facts)}; after: {len(final)}",
             f"- Duplicates merged away: {dup_removed}", f"- Contradiction pairs detected: {len(pairs)}",
             f"- Resolved: {len(drop)}; needing human review: {review}", "",
             "## Merged duplicates", "", "| kept | all merged lines (original line numbers) |", "|---|---|"]
    for k, group in merges:
        lines.append(f"| {k.render()[2:]} | " +
                     " ; ".join(f"L{r.line_no}: {r.render()[2:]}" for r in group) + " |")
    lines += ["", "## Contradictions", "", "| outcome | winner | loser | rule |", "|---|---|---|---|"]
    lines += log or ["| none | | | |"]
    log_md = "\n".join(lines) + "\n"
    surviving = len(final) + len(drop)
    if surviving != len(kept):
        raise ConsolidationError("internal check failed: a fact was lost without being logged")
    return Result(new_text, log_md, len(text.splitlines()), len(new_text.splitlines()),
                  len(content_lines(text)), len(content_lines(new_text)), len(facts), len(final),
                  dup_removed, len(drop), review, pairs)


def consolidate_file(path=MEMORY_PATH, llm=None, out_path=None, log_path=None, now=None, model="qwen3:8b"):
    """Consolidate a MEMORY.md on disk (backup kept as .bak when overwriting in place)."""
    path = Path(path)
    text = load_text(path)
    res = consolidate_text(text, llm, now, model)
    out = Path(out_path) if out_path else path
    if out == path and path.exists():
        path.with_suffix(path.suffix + ".bak").write_text(text)
    out.write_text(res.new_text)
    Path(log_path or out.with_name(out.stem + "_consolidation_log.md")).write_text(res.log_md)
    return res


# ------------------------------------------------------------------ /dream and /compact
def dream(history: list, memory_text: str, llm, now=None, model="qwen3:8b", max_facts=5):
    """Pick durable facts from recent messages and append them to MEMORY.md text. -> (text, added)."""
    now = now or datetime.now().astimezone()
    recent = history[-20:]
    if not recent:
        return memory_text, []
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    prompt = ("From the conversation below, list durable long-term facts worth remembering about "
              "the user or the project (preferences, constraints, decisions, names, deadlines). "
              "Skip small talk, one-off questions and anything already in memory. At most "
              f"{max_facts} facts, each one short sentence.\n\nAlready in memory:\n"
              f"{memory_text.strip() or '(empty)'}\n\nConversation:\n{transcript}\n\n"
              'Reply with ONLY JSON like {"facts": ["...", "..."]}.')
    out = llm("You extract durable facts.", [{"role": "user", "content": prompt}], model)
    try:
        cand = [str(x).strip() for x in _parse_json(out["text"])["facts"]]
    except (ValueError, KeyError, TypeError):
        return memory_text, []
    facts, notes = parse_memory(memory_text)
    added = []
    for c in cand:
        if 8 <= len(c) <= 200 and not any(similar(c, f.text) for f in facts):
            facts.append(Fact(DREAM_SECTION, now.date().isoformat(), c, 10**6 + len(facts)))
            added.append(c)
    stamp = read_last_consolidated(memory_text)
    return (render_memory(facts, notes, stamp) if added else memory_text), added[:max_facts]


def compact_history(history: list, llm, model="qwen3:8b", keep=4):
    """Replace all but the last `keep` messages with one summary message. -> (new_history, summarized)."""
    if len(history) <= keep + 1:
        return history, False
    old, recent = history[:-keep], history[-keep:]
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in old)
    out = llm("You write concise factual summaries.",
              [{"role": "user", "content": "Summarize this conversation in at most 120 words, "
                "keeping concrete facts, names, numbers and decisions:\n\n" + transcript}], model)
    summary = {"role": "user", "content": "[Summary of earlier conversation] " + out["text"]}
    return [summary] + recent, True


# ------------------------------------------------------------------ CLI
def _main():
    ap = argparse.ArgumentParser(description="MEMORY.md utilities")
    ap.add_argument("cmd", choices=["check", "consolidate"])
    ap.add_argument("--in", dest="inp", default=str(MEMORY_PATH))
    ap.add_argument("--out", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    text = load_text(Path(a.inp))
    need, reasons = needs_consolidation(text)
    print(f"{a.inp}: {len(text.splitlines())} lines, {len(content_lines(text))} non-empty non-comment")
    print("needs consolidation:", need, reasons)
    if a.cmd == "consolidate":
        from memory_llm import call_model
        if a.dry_run:
            res = consolidate_text(text, call_model)
            print(res.log_md)
            return
        res = consolidate_file(Path(a.inp), call_model, a.out, a.log)
        print(f"lines {res.lines_before} -> {res.lines_after}; facts {res.facts_before} -> {res.facts_after}; "
              f"duplicates merged {res.duplicates_merged}; contradictions resolved {res.contradictions_resolved}; "
              f"needs review {res.needs_review}")
        print(res.log_md)


if __name__ == "__main__":
    _main()