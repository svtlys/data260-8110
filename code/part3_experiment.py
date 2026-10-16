"""HW6 Part 3 experiments: memory cost/quality trade-offs.

  python part3_experiments.py sweep          # policy=full, SHORT_TERM_N = 4, 12, 30
  python part3_experiments.py policies       # policy=fifo at N=4,12,30 + policy=summary at N=4
  python part3_experiments.py one 12 full    # a single run
  python part3_experiments.py report         # writes reports/hw06/METRICS.md + summary.json
  add --force to redo a finished run;  --offline for a no-model dry run (tests only)
"""
import argparse
import csv
import json
import statistics as st
import sys
import time
from pathlib import Path

import yaml

import memory_service as ms
from hw6_script import CONVERSATION
from memory_config import MemoryConfig

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROBES_PATH = HERE / "memory_probes.yaml"
PRICE_IN, PRICE_OUT, N_CONVOS = 1.0, 5.0, 10_000      # $ per 1M tokens, conversations


def score_probe(reply, probe):
    r = reply.lower().replace("’", "'")
    hit = sum(any(a.lower() in r for a in g) for g in probe["must_include"])
    frac = hit / len(probe["must_include"])
    return 1 + round(4 * frac), hit, len(probe["must_include"])


def build_service(offline, raw_dir, cfg):
    if offline:
        from memory_embed import HashEmbedder
        from memory_fakes import FakeStore
        store, emb = FakeStore(), HashEmbedder()

        def llm(system, messages, model="x"):      # echoes its memory context (no recursion)
            last = messages[-1]["content"]
            if "summary" in last[:60].lower() or "profile" in last[:60].lower():
                body = "SUMMARY of: " + last[:80]
            else:       # memory notes + only the USER messages still in the window
                body = system[len(ms.PRIMER):] + " | " + " ".join(
                    m["content"] for m in messages if m["role"] == "user")
            return {"text": body[:1500], "prompt_tokens": ms.est_tokens(system) +
                    sum(ms.est_tokens(m["content"]) for m in messages),
                    "completion_tokens": 20, "latency_ms": 5.0}
        return ms.MemoryService(store, emb, llm, cfg, log_path=raw_dir / "token_log.csv", log=False)
    import doc_mongo
    from memory_embed import Embedder
    from memory_llm import call_model
    from memory_store import MongoStore, ensure_memory_collections
    if not doc_mongo.ping():
        sys.exit("MongoDB is not running: brew services start mongodb-community@8.0")
    ensure_memory_collections()
    return ms.MemoryService(MongoStore(), Embedder(), call_model, cfg,
                            log_path=raw_dir / "token_log.csv")


def purge_log(path, run_id):
    if not path.exists():
        return
    rows = list(csv.DictReader(open(path)))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ms.LOG_FIELDS)
        w.writeheader()
        w.writerows(r for r in rows if r["run_id"] != run_id)


def mean(xs):
    return round(st.mean(xs), 1) if xs else 0.0


def run_one(n, policy, raw_dir, offline=False, force=False):
    run_id = f"{policy}_N{n}"
    out = raw_dir / f"run_{run_id}.json"
    if out.exists() and not force:
        print(f"[skip] {run_id} already done (use --force)")
        return json.load(open(out))
    cfg = MemoryConfig(short_term_n=n, policy=policy)
    svc = build_service(offline, raw_dir, cfg)
    if not offline:
        purge_log(raw_dir / "token_log.csv", run_id)
    user, session = f"exp-{run_id}", f"sess-{run_id}"
    svc.store.delete_user(user)
    probes = yaml.safe_load(open(PROBES_PATH))["probes"]
    print(f"\n=== RUN {run_id}: {len(CONVERSATION)} turns, {len(probes)} probes ===", flush=True)
    t_start, turns = time.time(), []
    for i, msg in enumerate(CONVERSATION, 1):
        r = svc.chat(user, msg, session, cfg=cfg, run_id=run_id, turn=i)
        u = r["usage"]
        turns.append({"turn": i, "user": msg, "reply": r["reply"],
                      "prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"],
                      "components": u["components"], "latency_ms": u["latency_ms"],
                      "window_msgs": r["memory_used"]["short_term_messages"],
                      "facts_recalled": len(r["memory_used"]["episodic_facts"]),
                      "maintenance_ms": (r["maintenance"] or {}).get("latency_ms", 0)})
        print(f"  turn {i:2d}/30  prompt={u['prompt_tokens']:5d}  out={u['completion_tokens']:4d}  "
              f"{u['latency_ms']/1000:5.1f}s  elapsed={time.time()-t_start:5.0f}s", flush=True)
    results = []
    for p in probes:
        r = svc.chat(user, p["question"], session, persist=False, cfg=cfg, run_id=run_id, kind="probe")
        score, hit, need = score_probe(r["reply"], p)
        results.append({"id": p["id"], "question": p["question"], "criteria": p["criteria"],
                        "reply": r["reply"], "groups_hit": hit, "groups_needed": need, "score": score,
                        "prompt_tokens": r["usage"]["prompt_tokens"],
                        "latency_ms": r["usage"]["latency_ms"],
                        "facts_recalled": [f["fact"] for f in r["memory_used"]["episodic_facts"]]})
        print(f"  probe {p['id']}: score {score}  -> {r['reply'][:90]!r}", flush=True)
    rows = [x for x in svc.rows if x["run_id"] == run_id]
    chat = [x for x in rows if x["kind"] == "chat"]
    maint = [x for x in rows if x["kind"] in ("summarize", "lifetime")]
    comp = {k: mean([float(x[k + "_tokens"]) for x in chat])
            for k in ("primer", "longterm", "episodic", "window", "user")}
    summary = {
        "run_id": run_id, "policy": policy, "short_term_n": n,
        "mean_prompt_tokens": mean([x["prompt_tokens"] for x in chat]),
        "mean_completion_tokens": mean([x["completion_tokens"] for x in chat]),
        "mean_latency_ms": mean([x["latency_ms"] for x in chat]),
        "mean_probe_score": mean([p["score"] for p in results]),
        "mean_component_tokens": comp,
        "maintenance_calls": len(maint),
        "maintenance_prompt_tokens": sum(x["prompt_tokens"] for x in maint),
        "maintenance_completion_tokens": sum(x["completion_tokens"] for x in maint),
        "maintenance_latency_ms": round(sum(x["latency_ms"] for x in maint), 1),
        "conv_input_tokens": sum(x["prompt_tokens"] for x in chat + maint),
        "conv_output_tokens": sum(x["completion_tokens"] for x in chat + maint),
        "wall_seconds": round(time.time() - t_start)}
    json.dump({"summary": summary, "turns": turns, "probes": results}, open(out, "w"), indent=2)
    print(f"  -> saved {out.name}; mean prompt {summary['mean_prompt_tokens']}, "
          f"latency {summary['mean_latency_ms']:.0f}ms, probe score {summary['mean_probe_score']}")
    return {"summary": summary, "turns": turns, "probes": results}


def load_runs(raw_dir):
    runs = [json.load(open(p))["summary"] for p in sorted(raw_dir.glob("run_*.json"))]
    for s in runs:
        s["cost_10k"] = round(N_CONVOS * (s["conv_input_tokens"] / 1e6 * PRICE_IN +
                                          s["conv_output_tokens"] / 1e6 * PRICE_OUT), 2)
    return runs


def write_report(raw_dir, metrics_path):
    runs = load_runs(raw_dir)
    if not runs:
        sys.exit("no run_*.json files yet")
    json.dump(runs, open(raw_dir / "summary.json", "w"), indent=2)
    full = sorted([r for r in runs if r["policy"] == "full"], key=lambda r: r["short_term_n"])
    L = ["# METRICS - HW6 Part 3 (SID4 8110, SEED 8110)", "",
         "Model: qwen3:8b via Ollama, temperature 0, thinking disabled (`/no_think`). "
         "SHORT_TERM_N counts messages (user + assistant). 30 scripted user messages, then 5 probes "
         "(`memory_probes.yaml`). Token counts are Ollama's real prompt/completion counts; per-component "
         "counts split the real prompt count in proportion to characters.", "",
         "## Table 1 - SHORT_TERM_N sweep (policy = full: window + summaries + episodic facts)", "",
         "| SHORT_TERM_N | mean prompt tokens | mean completion tokens | mean latency (ms) | mean probe score (1-5) |",
         "|---|---|---|---|---|"]
    L += [f"| {r['short_term_n']} | {r['mean_prompt_tokens']} | {r['mean_completion_tokens']} | "
          f"{r['mean_latency_ms']:.0f} | {r['mean_probe_score']} |" for r in full]
    L += ["", "## Table 2 - eviction / compression policy comparison", "",
          "fifo = sliding window only (old messages evicted and lost); summary = evicted messages are "
          "compressed into session + lifetime summaries; full = summaries + episodic facts retrieved by cosine.", "",
          "| policy | N | mean prompt tokens | mean latency (ms) | mean probe score | maintenance calls | maintenance tokens (in/out) |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted(runs, key=lambda r: (r["short_term_n"], r["policy"])):
        L.append(f"| {r['policy']} | {r['short_term_n']} | {r['mean_prompt_tokens']} | {r['mean_latency_ms']:.0f} | "
                 f"{r['mean_probe_score']} | {r['maintenance_calls']} | "
                 f"{r['maintenance_prompt_tokens']}/{r['maintenance_completion_tokens']} |")
    L += ["", "## Table 3 - mean prompt tokens by component (per chat turn)", "",
          "| run | primer | long-term summary | episodic facts | short-term window | user msg |", "|---|---|---|---|---|---|"]
    for r in sorted(runs, key=lambda r: (r["short_term_n"], r["policy"])):
        c = r["mean_component_tokens"]
        L.append(f"| {r['run_id']} | {c['primer']} | {c['longterm']} | {c['episodic']} | {c['window']} | {c['user']} |")
    best = max(runs, key=lambda r: (r["mean_probe_score"], -r["cost_10k"]))
    worst = min(runs, key=lambda r: (r["mean_probe_score"], -r["cost_10k"]))
    L += ["", f"## Table 4 - cost of {N_CONVOS:,} 30-turn conversations at ${PRICE_IN}/M input, ${PRICE_OUT}/M output", "",
          "Tokens per conversation include chat turns plus summarisation calls (probes excluded). "
          "This is a hypothetical price; the local model costs nothing.", "",
          "| run | input tokens / conv | output tokens / conv | cost for 10,000 convs | probe score |", "|---|---|---|---|---|"]
    for r in sorted(runs, key=lambda r: r["cost_10k"]):
        tag = " (best quality)" if r is best else " (worst quality)" if r is worst else ""
        L.append(f"| {r['run_id']}{tag} | {r['conv_input_tokens']} | {r['conv_output_tokens']} | "
                 f"${r['cost_10k']:,.2f} | {r['mean_probe_score']} |")
    L += ["", "## Analysis", "", "_(write 3-5 sentences after reading the tables: what N is the best "
          "quality-per-dollar, what the summaries/facts buy you at small N, and what the "
          "maintenance calls cost.)_", ""]
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text("\n".join(L))
    print("\n".join(L))
    print(f"\nwrote {metrics_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sweep", "policies", "one", "report"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--raw-dir", default=str(ROOT / "reports" / "hw06" / "raw"))
    ap.add_argument("--metrics", default=str(ROOT / "reports" / "hw06" / "METRICS.md"))
    a = ap.parse_args()
    raw = Path(a.raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    if a.cmd == "sweep":
        for n in (4, 12, 30):
            run_one(n, "full", raw, a.offline, a.force)
    elif a.cmd == "policies":
        for n in (4, 12, 30):
            run_one(n, "fifo", raw, a.offline, a.force)
        run_one(4, "summary", raw, a.offline, a.force)
    elif a.cmd == "one":
        run_one(int(a.args[0]), a.args[1], raw, a.offline, a.force)
    else:
        write_report(raw, Path(a.metrics))