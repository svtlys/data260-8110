import csv
import math
import re
import secrets
from datetime import datetime
from pathlib import Path

from memory_config import DEFAULT, POLICIES, MemoryConfig
from memory_embed import cosine_top_k
from memory_llm import NO_THINK, REPO_ROOT, est_tokens

PRIMER = ("You are a friendly rental-housing assistant. Reply in at most 3 short sentences. "
          "Use the memory notes below when they are relevant. If the answer is not in the "
          "notes or the conversation, say you don't know instead of guessing.")

TOKEN_LOG = REPO_ROOT / "reports" / "hw06" / "raw" / "token_log.csv"
LOG_FIELDS = ["ts", "run_id", "user_id", "session_id", "kind", "policy", "short_term_n",
              "turn", "prompt_tokens", "completion_tokens", "primer_tokens",
              "longterm_tokens", "episodic_tokens", "window_tokens", "user_tokens",
              "latency_ms"]

_FIRST_PERSON = re.compile(r"\b(i|i'm|i'd|i've|i'll|my|we|our|we're)\b", re.I)


def new_session_id():
    return f"sess-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def extract_fact_candidates(text: str):
    """Rule-based episodic extraction: first-person statements, not questions."""
    out = []
    for s in re.split(r"(?<=[.!])\s+|\n", text):
        s = s.strip()
        if len(s) >= 15 and not s.endswith("?") and _FIRST_PERSON.search(s):
            out.append(s)
    return out


def apportion(total_tokens: int, chars: dict) -> dict:
    """Split the real prompt-token count over components in proportion to characters."""
    s = sum(chars.values()) or 1
    return {k: round(total_tokens * v / s) for k, v in chars.items()}


class MemoryService:
    def __init__(self, store, embedder, llm, cfg: MemoryConfig = DEFAULT,
                 log_path=TOKEN_LOG, log=True):
        self.store, self.embedder, self.llm, self.cfg = store, embedder, llm, cfg
        self.log_path, self.log_enabled, self.rows = Path(log_path), log, []

    # ---------- logging ----------
    def _log(self, **row):
        row["ts"] = datetime.now().isoformat(timespec="seconds")
        row = {k: row.get(k, "") for k in LOG_FIELDS}
        self.rows.append(row)
        if not self.log_enabled:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.log_path.exists()
        with open(self.log_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)

    # ---------- retrieval ----------
    def retrieve_facts(self, user_id, query, cfg):
        eps = self.store.all_episodes(user_id)
        hits = cosine_top_k(self.embedder.embed(query), eps, cfg.top_k, cfg.min_score)
        return [{"fact": it["fact"], "score": round(s, 3)} for s, it in hits]

    def _remember_facts(self, user_id, session_id, message):
        eps = None
        for cand in extract_fact_candidates(message):
            vec = self.embedder.embed(cand)
            if eps is None:
                eps = self.store.all_episodes(user_id)
            if cosine_top_k(vec, eps, 1, 0.92):        # near-duplicate -> skip
                continue
            self.store.add_episode(user_id, cand, vec, session_id)
            eps.append({"fact": cand, "embedding": vec})

    # ---------- summarisation ----------
    def _maybe_summarize(self, user_id, session_id, cfg, run_id, turn):
        n_user = self.store.count_messages(user_id, session_id, "user")
        if n_user == 0 or n_user % cfg.summarize_every:
            return None
        prev = self.store.latest_summary(user_id, "session", session_id)
        covered = prev.get("user_msgs_covered", 0) if prev else 0
        msgs = self.store.recent_messages(user_id, session_id, (n_user - covered) * 2)
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
        prompt = ("Update the running summary of this conversation in at most 120 words. "
                  "Keep concrete facts: numbers, names, dates, preferences, decisions.\n\n"
                  f"Previous summary: {prev['content'] if prev else '(none)'}\n\n"
                  f"New messages:\n{transcript}\n\nUpdated summary:")
        out = self.llm("You write concise factual summaries.",
                       [{"role": "user", "content": prompt + NO_THINK}], cfg.model)
        self.store.add_summary(user_id, session_id, "session", out["text"], n_user)
        self._log(run_id=run_id, user_id=user_id, session_id=session_id, kind="summarize",
                  policy=cfg.policy, short_term_n=cfg.short_term_n, turn=turn,
                  prompt_tokens=out["prompt_tokens"], completion_tokens=out["completion_tokens"],
                  latency_ms=out["latency_ms"])
        # condense into the lifetime summary
        life = self.store.latest_summary(user_id, "lifetime")
        prompt = ("Merge into ONE profile of this user in at most 100 words. Keep durable facts "
                  "and preferences; drop small talk.\n\n"
                  f"Existing profile: {life['content'] if life else '(none)'}\n\n"
                  f"Latest session summary: {out['text']}\n\nMerged profile:")
        out2 = self.llm("You write concise factual summaries.",
                        [{"role": "user", "content": prompt + NO_THINK}], cfg.model)
        self.store.add_summary(user_id, "*", "lifetime", out2["text"], 0)
        self._log(run_id=run_id, user_id=user_id, session_id=session_id, kind="lifetime",
                  policy=cfg.policy, short_term_n=cfg.short_term_n, turn=turn,
                  prompt_tokens=out2["prompt_tokens"], completion_tokens=out2["completion_tokens"],
                  latency_ms=out2["latency_ms"])
        return {"session_summary_updated": True, "lifetime_summary_updated": True,
                "latency_ms": round(out["latency_ms"] + out2["latency_ms"], 1)}

    # ---------- main entry ----------
    def chat(self, user_id, message, session_id=None, persist=True, cfg=None,
             run_id="", turn=None, kind=None):
        cfg = cfg or self.cfg
        use_sum, use_epi = POLICIES[cfg.policy]
        session_id = session_id or new_session_id()

        window = self.store.recent_messages(user_id, session_id, cfg.short_term_n)
        sess = life = None
        if use_sum:
            s = self.store.latest_summary(user_id, "session", session_id)
            l = self.store.latest_summary(user_id, "lifetime")
            sess, life = (s["content"] if s else None), (l["content"] if l else None)
        facts = self.retrieve_facts(user_id, message, cfg) if use_epi else []

        if persist:
            self.store.add_message(user_id, session_id, "user", message)

        longterm = ""
        if life:
            longterm += f"\nLong-term summary of this user: {life}"
        if sess:
            longterm += f"\nSummary of this session so far: {sess}"
        episodic = ""
        if facts:
            episodic = "\nRelevant facts the user told you earlier:\n" + \
                       "\n".join(f"- {f['fact']}" for f in facts)
        system = PRIMER + longterm + episodic
        msgs = [{"role": m["role"], "content": m["content"]} for m in window]
        msgs.append({"role": "user", "content": message + NO_THINK})

        out = self.llm(system, msgs, cfg.model)
        reply = out["text"]

        comp = apportion(out["prompt_tokens"], {
            "primer": len(PRIMER), "longterm": len(longterm), "episodic": len(episodic),
            "window": sum(len(m["content"]) for m in window), "user": len(message)})
        self._log(run_id=run_id, user_id=user_id, session_id=session_id,
                  kind=kind or ("chat" if persist else "probe"), policy=cfg.policy,
                  short_term_n=cfg.short_term_n, turn=turn,
                  prompt_tokens=out["prompt_tokens"], completion_tokens=out["completion_tokens"],
                  primer_tokens=comp["primer"], longterm_tokens=comp["longterm"],
                  episodic_tokens=comp["episodic"], window_tokens=comp["window"],
                  user_tokens=comp["user"], latency_ms=out["latency_ms"])

        maintenance = None
        if persist:
            self.store.add_message(user_id, session_id, "assistant", reply)
            if use_epi:
                self._remember_facts(user_id, session_id, message)
            if use_sum:
                maintenance = self._maybe_summarize(user_id, session_id, cfg, run_id, turn)

        return {
            "reply": reply, "session_id": session_id,
            "memory_used": {
                "policy": cfg.policy, "short_term_n": cfg.short_term_n,
                "short_term_messages": len(window),
                "session_summary": sess, "lifetime_summary": life,
                "episodic_facts": facts},
            "usage": {"prompt_tokens": out["prompt_tokens"],
                      "completion_tokens": out["completion_tokens"],
                      "components": comp, "latency_ms": out["latency_ms"]},
            "maintenance": maintenance}

    # ---------- read-only views ----------
    def memory_view(self, user_id, cfg=None):
        cfg = cfg or self.cfg
        msgs = self.store.recent_user_messages(user_id, cfg.view_messages)
        s, l = self.store.latest_summary(user_id, "session"), self.store.latest_summary(user_id, "lifetime")
        facts = self.store.recent_episodes(user_id, cfg.view_facts)
        return {
            "user_id": user_id,
            "recent_messages": [{"session_id": m["session_id"], "role": m["role"],
                                 "content": m["content"], "created_at": m["created_at"].isoformat()}
                                for m in msgs],
            "session_summary": s["content"] if s else None,
            "lifetime_summary": l["content"] if l else None,
            "episodic_facts": [{"fact": f["fact"], "created_at": f["created_at"].isoformat()}
                               for f in facts]}

    def aggregate(self, user_id, n_summaries=5):
        return {"user_id": user_id, "daily_counts": self.store.daily_counts(user_id),
                "recent_summaries": [{"kind": s["kind"], "session_id": s["session_id"],
                                      "content": s["content"], "created_at": s["created_at"].isoformat()}
                                     for s in self.store.recent_summaries(user_id, n_summaries)]}