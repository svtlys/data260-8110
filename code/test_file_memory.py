import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import agent_check as ac
import file_memory as fm
from file_memory_chat import ChatSession
from make_memory_fixture import L as FIXTURE

GOOD = '''
import re
def parse_rent(text: str) -> int:
    """Convert a rent string like '$2,400/mo' to dollars per month."""
    m = re.search(r"(\\d[\\d,]*)", text)
    if not m:
        raise ValueError(f"cannot parse rent: {text!r}")
    return int(m.group(1).replace(",", ""))

def test_dollar_sign():
    assert parse_rent("$2,400/mo") == 2400

def test_plain():
    assert parse_rent("2400 per month") == 2400

def test_error():
    import pytest
    with pytest.raises(ValueError):
        parse_rent("call us")
'''
BAD = '''
def parseRent(text):
    print(text)
    password = "hunter2"
    try:
        return eval(text)
    except:
        return 0
'''
TOPICS = ["rent budget", "neighborhood", "Prefers answers", "Pet policy"]


def stub_llm(system, messages, model="x"):
    p = messages[-1]["content"]
    if "contradict each other" in p:
        items = re.findall(r"^(\d+)\. (.*)$", p, re.M)
        pairs = []
        for t in TOPICS:
            ids = [int(i) for i, txt in items if t in txt]
            if len(ids) == 2:
                pairs.append(ids)
        return {"text": "```json\n" + json.dumps({"contradictions": pairs}) + "\n```"}
    if "durable long-term facts" in p:
        return {"text": json.dumps({"facts": ["Alex wants a balcony.", "Alex owns two cats named Miso and Pickles."]})}
    if "Summarize this conversation" in p:
        return {"text": "Alex is apartment hunting."}
    if "Write a Python function" in p:
        return {"text": "```python\n" + GOOD + "\n```"}
    return {"text": "ok"}


def main():
    now = datetime.now().astimezone()
    # --- consolidation triggers
    fresh = f"<!-- last_consolidated: {now.isoformat()} -->\n# M\n- a\n"
    assert fm.needs_consolidation(fresh, now) == (False, [])
    old = f"<!-- last_consolidated: {(now - timedelta(hours=25)).isoformat()} -->\n- a\n"
    assert fm.needs_consolidation(old, now)[0]
    many = fresh + "".join(f"- fact {i}\n" for i in range(41))
    assert any("non-empty" in r for r in fm.needs_consolidation(many, now)[1])
    assert fm.needs_consolidation("- a\n", now)[0]                      # no timestamp
    cm = "<!-- last_consolidated: " + now.isoformat() + " -->\n<!--\nmulti\nline\n-->\n- a\n"
    assert len(fm.content_lines(cm)) == 1                               # comments not counted
    sp = fm.build_system_prompt("AGENT TEXT", "MEMORY TEXT")
    assert "AGENT TEXT" in sp and "MEMORY TEXT" in sp
    print("trigger + prompt tests passed")

    # --- 55-line fixture
    assert len(FIXTURE) == 55
    text = "\n".join(FIXTURE) + "\n"
    need, reasons = fm.needs_consolidation(text, now)
    assert need and len(reasons) == 2, reasons
    facts, _ = fm.parse_memory(text)
    kept, merges = fm.dedupe(facts)
    print(f"fixture: {len(text.splitlines())} lines, {len(facts)} facts -> {len(kept)} after dedupe, "
          f"{len(merges)} duplicated facts")
    assert len(merges) >= 3
    res = fm.consolidate_text(text, stub_llm, now)
    print(f"consolidated: {res.lines_before} -> {res.lines_after} lines; facts {res.facts_before} -> "
          f"{res.facts_after}; dup merged {res.duplicates_merged}; contradictions {res.contradictions_resolved}")
    assert res.lines_after < 40 and res.contradictions_resolved == 4 and res.needs_review == 0
    assert not fm.needs_consolidation(res.new_text, now)[0]
    # nothing silently deleted: every original fact is kept, merged (logged) or superseded (logged)
    for f in facts:
        assert f.text in res.new_text or f.text in res.log_md, f.text
    for loser in ("2,400", "Willow Glen", "bullet points", "must allow cats"):
        assert loser in res.new_text and loser in res.log_md          # visible in file + log
    assert "no pets are needed" in res.new_text.split("## Housing search")[1].split("## Working")[0] \
        or "no pets are needed" in res.new_text
    again = fm.consolidate_text(res.new_text, stub_llm, now)
    assert again.facts_after == res.facts_after and again.duplicates_merged == 0
    print("fixture tests passed (note: newest-wins keeps the 'no pets needed' hypothetical)")

    # --- undated conflict -> NEEDS REVIEW
    r2 = fm.consolidate_text("# M\n## Housing search\n- Maximum rent budget is $2,400 per month.\n"
                             "- Maximum rent budget is $2,900 per month.\n", stub_llm, now)
    assert r2.needs_review == 1 and r2.facts_after == 2 and "NEEDS REVIEW" in r2.new_text
    # malformed model output -> error, file untouched
    try:
        fm.consolidate_text(text, lambda s, m, mo="x": {"text": "not json"}, now)
        raise AssertionError("expected ConsolidationError")
    except fm.ConsolidationError:
        pass
    print("review + failure tests passed")

    # --- chat commands
    tmp = Path(tempfile.mkdtemp())
    (tmp / "AGENT.md").write_text("AGENT")
    mem = tmp / "MEMORY.md"
    mem.write_text(text)
    s = ChatSession(stub_llm, tmp / "AGENT.md", mem)
    assert "/compact" in s.handle("/help") and "/dream" in s.handle("/help")
    assert "needs consolidation: yes" in s.handle("/memory")
    for i in range(6):
        s.handle(f"message {i}")                  # first one triggers auto-consolidation
    assert "ok" in s.handle("hello") and len(s.history) == 14
    assert fm.needs_consolidation(mem.read_text())[0] is False
    d = s.handle("/dream")
    assert "balcony" in d and "Miso" not in d     # duplicate fact not re-added
    mem.write_text(text)
    out = s.handle("/compact")
    print(out)
    assert "14 -> 5" in out and "55 -> " in out and "lines" in out
    print("chat command tests passed")

    # --- AGENT.md compliance checker
    assert all(c["passed"] for c in ac.check_code(GOOD))
    failed = [c["rule"][:2] for c in ac.check_code(BAD) if not c["passed"]]
    assert set(failed) >= {"C1", "C2", "C3", "C4", "X1", "N1", "N2"}, failed
    v = ac.verify(stub_llm)
    assert v["passed"] and len(v["attempts"]) == 1
    print("agent_check tests passed; pytest run:", v["attempts"][0]["tests"]["detail"][-40:].strip())
    shutil.rmtree(tmp)
    print("ALL PART 4 OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()