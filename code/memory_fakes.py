from datetime import datetime, timedelta, timezone

from memory_llm import est_tokens


class FakeStore:
    def __init__(self):
        self.msgs, self.sums, self.eps, self._t = [], [], [], datetime(2026, 10, 15, tzinfo=timezone.utc)

    def _now(self):
        self._t += timedelta(seconds=30)
        return self._t

    def add_message(self, user_id, session_id, role, content):
        self.msgs.append(dict(user_id=user_id, session_id=session_id, role=role,
                              content=content, created_at=self._now()))

    def recent_messages(self, u, s, n):
        m = [x for x in self.msgs if x["user_id"] == u and x["session_id"] == s]
        return m[-n:] if n > 0 else []

    def recent_user_messages(self, u, n):
        return [x for x in self.msgs if x["user_id"] == u][-n:]

    def count_messages(self, u, s, role):
        return sum(1 for x in self.msgs if x["user_id"] == u and x["session_id"] == s and x["role"] == role)

    def add_summary(self, u, s, kind, content, user_msgs_covered=0):
        self.sums.append(dict(user_id=u, session_id=s, kind=kind, content=content,
                              user_msgs_covered=user_msgs_covered, created_at=self._now()))

    def latest_summary(self, u, kind, session_id=None):
        c = [x for x in self.sums if x["user_id"] == u and x["kind"] == kind
             and (session_id is None or x["session_id"] == session_id)]
        return c[-1] if c else None

    def recent_summaries(self, u, n):
        return [x for x in self.sums if x["user_id"] == u][::-1][:n]

    def add_episode(self, u, fact, embedding, source_session):
        self.eps.append(dict(user_id=u, fact=fact, embedding=embedding, created_at=self._now()))

    def all_episodes(self, u):
        return [x for x in self.eps if x["user_id"] == u]

    def recent_episodes(self, u, n):
        return self.all_episodes(u)[::-1][:n]

    def daily_counts(self, u):
        d = {}
        for x in self.msgs:
            if x["user_id"] == u:
                r = d.setdefault(x["created_at"].strftime("%Y-%m-%d"), {"user": 0, "assistant": 0})
                r[x["role"]] += 1
        return [dict(date=k, total=v["user"] + v["assistant"], **v) for k, v in sorted(d.items())]

    def delete_user(self, u):
        self.msgs = [x for x in self.msgs if x["user_id"] != u]
        self.sums = [x for x in self.sums if x["user_id"] != u]
        self.eps = [x for x in self.eps if x["user_id"] != u]


def fake_llm(system, messages, model="fake"):
    last = messages[-1]["content"]
    text = "SUMMARY: " + last[:60] if "summary" in last.lower()[:40] or "profile" in last.lower()[:40] \
        else "Noted. (system had %d chars)" % len(system)
    pt = est_tokens(system) + sum(est_tokens(m["content"]) for m in messages)
    return {"text": text, "prompt_tokens": pt, "completion_tokens": est_tokens(text), "latency_ms": 1.0}