from pathlib import Path

import file_memory as fm

HELP = """Commands:
  /memory   show MEMORY.md and whether it needs consolidation
  /compact  consolidate MEMORY.md and compress the chat history (prints message counts before/after)
  /dream    pick durable long-term facts from the recent conversation and add them to MEMORY.md
  /help     show this help
  /exit     quit
Anything else is sent to the model with AGENT.md + MEMORY.md in the system prompt.
Consolidation also runs automatically when MEMORY.md has >40 non-empty non-comment lines
or was last consolidated more than 24 hours ago."""


class ChatSession:
    """Holds the history and runs one input line at a time (testable without input())."""

    def __init__(self, llm, agent_path=fm.AGENT_PATH, memory_path=fm.MEMORY_PATH, model="qwen3:8b", auto=True):
        self.llm, self.model, self.auto = llm, model, auto
        self.agent_path, self.memory_path = Path(agent_path), Path(memory_path)
        self.history, self.auto_failed = [], False

    def maybe_auto_consolidate(self):
        """Run consolidation if a trigger fires; returns a status string or ''."""
        if self.auto_failed or not self.auto:
            return ""
        text = fm.load_text(self.memory_path)
        need, reasons = fm.needs_consolidation(text)
        if not need:
            return ""
        try:
            res = fm.consolidate_file(self.memory_path, self.llm, model=self.model)
        except fm.ConsolidationError as e:
            self.auto_failed = True
            return f"[auto-consolidation failed, MEMORY.md left unchanged: {e}]"
        return (f"[auto-consolidation: {'; '.join(reasons)}]\n"
                f"[MEMORY.md {res.lines_before} -> {res.lines_after} lines]")

    def cmd_memory(self):
        text = fm.load_text(self.memory_path)
        need, reasons = fm.needs_consolidation(text)
        ts = fm.read_last_consolidated(text)
        head = (f"=== {self.memory_path.name}: {len(text.splitlines())} lines, "
                f"{len(fm.content_lines(text))} non-empty non-comment, last consolidated "
                f"{ts.isoformat(timespec='seconds') if ts else 'never'}; "
                f"needs consolidation: {'yes - ' + '; '.join(reasons) if need else 'no'} ===")
        return head + "\n" + (text or "(empty)")

    def cmd_compact(self):
        text = fm.load_text(self.memory_path)
        msgs_before = len(self.history)
        try:
            res = fm.consolidate_file(self.memory_path, self.llm, model=self.model)
        except fm.ConsolidationError as e:
            return f"/compact failed, MEMORY.md left unchanged: {e}"
        self.history, summarized = fm.compact_history(self.history, self.llm, self.model)
        return (f"/compact done\n"
                f"  conversation messages: {msgs_before} -> {len(self.history)}"
                f"{'' if summarized else ' (too short to compress)'}\n"
                f"  MEMORY.md lines:       {res.lines_before} -> {res.lines_after}\n"
                f"  MEMORY.md facts:       {res.facts_before} -> {res.facts_after}\n"
                f"  duplicates merged: {res.duplicates_merged}, contradictions resolved: "
                f"{res.contradictions_resolved}, needing review: {res.needs_review}")

    def cmd_dream(self):
        text = fm.load_text(self.memory_path)
        new_text, added = fm.dream(self.history, text, self.llm, model=self.model)
        if not added:
            return "/dream: nothing new worth adding to MEMORY.md"
        self.memory_path.write_text(new_text)
        return "/dream added to MEMORY.md:\n" + "\n".join(f"  + {a}" for a in added)

    def handle(self, line: str) -> str:
        """Process one line of input and return what to print."""
        line = line.strip()
        if line == "/help":
            return HELP
        if line == "/memory":
            return self.cmd_memory()
        if line == "/compact":
            return self.cmd_compact()
        if line == "/dream":
            return self.cmd_dream()
        if not line:
            return ""
        notice = self.maybe_auto_consolidate()
        system = fm.load_system_prompt(self.agent_path, self.memory_path)
        msgs = self.history + [{"role": "user", "content": line}]
        reply = self.llm(system, msgs, self.model)["text"]
        self.history += [{"role": "user", "content": line}, {"role": "assistant", "content": reply}]
        return (notice + "\n" if notice else "") + reply


def main():
    import sys
    from memory_llm import call_model
    s = ChatSession(call_model, auto="--no-auto" not in sys.argv)
    print("File-memory chat. Type /help for commands."
          + ("" if s.auto else "  (auto-consolidation OFF)"))
    first = s.maybe_auto_consolidate()
    if first:
        print(first)
    while True:
        try:
            line = input("You: ")
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() == "/exit":
            break
        out = s.handle(line)
        if out:
            print(out + "\n")


if __name__ == "__main__":
    main()