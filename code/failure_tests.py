import csv
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

os.environ.setdefault("LLM_MODE", "stub")

from agent_core import SeenStore, SimulatedCrash, carry, run_agent  # noqa: E402
from kafka_config import (BOOTSTRAP, MAX_RETRIES, PREFIX, TOPIC_DEAD_LETTER, TOPIC_DRAFTS, TOPIC_PARTITIONS, TOPIC_TASKS,  # noqa: E402
                          VERIFY_SEED, setup_logging)
from kafka_io import KafkaConsumer, KafkaProducer, collect, committed_offsets, ensure_topics  # noqa: E402
from writer import make_draft  # noqa: E402

log = logging.getLogger("tests")
CODE_DIR = Path(__file__).resolve().parent
RAW_DIR = Path(os.environ.get("RAW_DIR", CODE_DIR.parent / "reports" / "hw08" / "raw"))
ENTITIES = ["LST-1", "LST-2", "LST-4", "LST-5"]   # crc32 % 2 puts LST-1/LST-2 on partition 0 and LST-4/LST-5 on partition 1


def new_run(kind: str) -> str:
    return f"{kind}-{uuid.uuid4().hex[:6]}"


def make_task(run_id: str, cid: str, **extra) -> dict:
    return {"correlation_id": cid, "run_id": run_id, "question": "Is the unit still available?", "plan": ["check", "answer"], **extra}


def save_raw(name: str, data) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


class Agent:
    """A Writer-like consumer thread (same consume/process/commit loop as writer.py)."""

    def __init__(self, name, group, transform, run_id, **opts) -> None:
        self.name, self.stop = name, threading.Event()
        self.consumer = KafkaConsumer(group, [TOPIC_TASKS], client_id=name)
        producer = KafkaProducer(client_id=name)
        opts.setdefault("backoff", 0.3)
        opts["accept"] = lambda b: b.get("run_id") == run_id
        self.thread = threading.Thread(target=self._run, args=(producer, transform, opts), daemon=True)
        self.thread.start()
        self.consumer.ready.wait(30)

    def _run(self, producer, transform, opts) -> None:
        try:
            run_agent(self.name, self.consumer, producer, TOPIC_DRAFTS, transform, self.stop, **opts)
        except SimulatedCrash:
            pass

    def close(self) -> None:
        self.stop.set()
        self.thread.join(5)
        self.consumer.close()


class CountingWriter:
    """Stub writer that counts how many times the work was actually done."""

    def __init__(self, name: str = "writer") -> None:
        self.name, self.calls = name, []

    def __call__(self, body, msg):
        self.calls.append(body["correlation_id"])
        return {**carry(body), "draft": f"draft for {body['correlation_id']}", "writer_id": self.name}


def drafts_for(run_id: str, want: int, timeout: float) -> list:
    return collect(TOPIC_DRAFTS, lambda b: b.get("run_id") == run_id, lambda f: len(f) >= want, timeout)


# ------------------------------------------------------------------ I. duplicate delivery

def scenario_duplicate(idempotent: bool) -> dict:
    run, cid = new_run("dup"), f"dup-{uuid.uuid4().hex[:8]}"
    writer = CountingWriter("writer-dup")
    agent = Agent("writer-dup", f"{PREFIX}_dup_{run}", writer, run, seen=SeenStore() if idempotent else None)
    producer = KafkaProducer()
    for attempt in (1, 2):
        part, off = producer.send(TOPIC_TASKS, make_task(run, cid), key=cid)
        log.info("REPLAY    send #%d of the SAME task correlation_id=%s -> partition=%d offset=%d", attempt, cid, part, off)
    drafts = drafts_for(run, 2, 8)
    agent.close()
    result = {"scenario": "duplicate", "idempotent": idempotent, "correlation_id": cid, "sent": 2,
              "times_work_done": len(writer.calls), "drafts_on_topic": len(drafts)}
    log.info("RESULT    %s", json.dumps(result))
    return result


# ------------------------------------------------------------------ III. poison message

def scenario_poison(bounded: bool) -> dict:
    run = new_run("poison")
    failures, blocked = [], threading.Event()

    def writer(body, msg):
        if blocked.is_set():
            raise SimulatedCrash()
        try:
            return make_draft(body, msg)
        except ValueError:
            failures.append(time.time())
            raise

    agent = Agent("writer-poison", f"{PREFIX}_poison_{run}", writer, run, max_retries=MAX_RETRIES if bounded else None)
    producer, bad = KafkaProducer(), f"poison-{uuid.uuid4().hex[:8]}"
    producer.send(TOPIC_TASKS, {"correlation_id": bad, "run_id": run, "question": "x", "plan": "NOT-A-LIST"}, key=bad)
    good = [f"good-{i}-{uuid.uuid4().hex[:6]}" for i in (1, 2)]
    for cid in good:
        producer.send(TOPIC_TASKS, make_task(run, cid), key=cid)
    log.info("SENT      1 poison message %s followed by 2 good messages", bad)
    drafts = drafts_for(run, 2, 12 if not bounded else 20)
    dead = collect(TOPIC_DEAD_LETTER, lambda b: b.get("correlation_id") == bad, lambda f: len(f) >= 1, 6 if bounded else 3)
    blocked.set()
    agent.close()
    result = {"scenario": "poison", "bounded_retries": bounded, "max_retries": MAX_RETRIES if bounded else "unbounded",
              "failed_attempts": len(failures), "dead_letter_messages": len(dead), "good_expected": 2, "good_processed": len(drafts),
              "dead_letter_attempts": dead[0].get("attempts") if dead else None}
    log.info("RESULT    %s", json.dumps(result))
    return result


# ------------------------------------------------------------------ II. consumer death

def spawn_writer(env: dict, log_path: Path):
    handle = open(log_path, "w", encoding="utf-8")
    return subprocess.Popen([sys.executable, "writer.py"], env=env, cwd=CODE_DIR, stdout=handle, stderr=subprocess.STDOUT)


def interesting(path: Path, cid: str) -> list:
    keys = ("CRASH", "COMMITTED", "starting", "Consumer is ready")
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if cid in ln or any(k in ln for k in keys)]


def wait_committed(group: str, partition: int, target: int, timeout: float = 10) -> int | None:
    deadline, value = time.time() + timeout, None
    while time.time() < deadline:
        value = committed_offsets(group, TOPIC_TASKS).get(partition)
        if value is not None and value >= target:
            break
        time.sleep(1)
    return value


def scenario_crash(commit_early: bool) -> dict:
    run, cid = new_run("crash"), f"crash-{uuid.uuid4().hex[:8]}"
    tmp = Path(tempfile.mkdtemp(prefix="hw8crash_"))
    suffix = f"_{run}"
    env = {**os.environ, "LLM_MODE": "stub", "GROUP_SUFFIX": suffix, "RUN_FILTER": run, "WRITER_CRASH_ON_CID": cid,
           "WRITER_CRASH_MARKER": str(tmp / "crashed"), "STATE_DIR": str(tmp), "COMMIT_EARLY": "1" if commit_early else "0",
           "WRITER_ID": "writer-A", "KAFKA_BOOTSTRAP": BOOTSTRAP, "PYTHONUNBUFFERED": "1"}
    group = f"{PREFIX}_writer{suffix}"
    part, off = KafkaProducer().send(TOPIC_TASKS, make_task(run, cid), key=cid)
    log.info("SENT      task correlation_id=%s partition=%d offset=%d (commit_early=%s)", cid, part, off, commit_early)
    first = spawn_writer(env, tmp / "run1.log")
    try:
        code = first.wait(timeout=90)
    except subprocess.TimeoutExpired:
        first.kill()
        code = None
    after_crash = committed_offsets(group, TOPIC_TASKS).get(part)
    log.info("CRASHED   writer exit code=%s | committed offset after crash=%s (message offset=%d)", code, after_crash, off)
    second = spawn_writer(env, tmp / "run2.log")
    drafts = drafts_for(run, 1, 15 if commit_early else 60)
    after_restart = wait_committed(group, part, off + 1) if drafts else committed_offsets(group, TOPIC_TASKS).get(part)
    second.terminate()
    second.wait(10)
    result = {"scenario": "consumer_killed", "commit_early": commit_early, "correlation_id": cid, "partition": part, "message_offset": off,
              "exit_code_run1": code, "committed_after_crash": after_crash, "committed_after_restart": after_restart,
              "draft_after_restart": len(drafts), "run1_log": interesting(tmp / "run1.log", cid), "run2_log": interesting(tmp / "run2.log", cid)}
    log.info("RESULT    %s", json.dumps({k: v for k, v in result.items() if not k.endswith("_log")}))
    return result


# ------------------------------------------------------------------ IV. ordering

def generate_messages(run_id: str, n: int = 20) -> list:
    """The same n related messages every time: entity choice, per-entity sequence number, work time and (unkeyed) partition."""
    rng, seq, out = random.Random(VERIFY_SEED), {e: 0 for e in ENTITIES}, []
    for idx in range(1, n + 1):
        entity = rng.choice(ENTITIES)
        seq[entity] += 1
        out.append({"correlation_id": f"{run_id}-m{idx:02d}", "run_id": run_id, "idx": idx, "entity_id": entity, "seq": seq[entity],
                    "work_ms": int(rng.uniform(50, 350)), "spread_partition": rng.randrange(2),
                    "question": f"Update #{seq[entity]} about {entity}", "plan": ["apply update"]})
    return out


class Recorder:
    """Writer stand-in that takes work_ms to 'work' and records when and where each message finished."""

    def __init__(self, name: str, events: list) -> None:
        self.name, self.events = name, events

    def __call__(self, body, msg):
        time.sleep(body["work_ms"] / 1000)
        self.events.append({"done_ts": round(time.time(), 3), "writer": self.name, "partition": msg.partition, "offset": msg.offset,
                            "entity": body["entity_id"], "seq": body["seq"], "idx": body["idx"], "work_ms": body["work_ms"]})
        logging.getLogger(self.name).info("PROCESSED idx=%02d entity=%s seq=%d partition=%d", body["idx"], body["entity_id"], body["seq"], msg.partition)
        return {**carry(body), "draft": "ok", "writer_id": self.name}


def wait_balanced(agents: list, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(a.consumer.assigned for a in agents) and sum(len(a.consumer.assigned) for a in agents) == 2:
            break
        time.sleep(0.5)
    time.sleep(1)


def analyse(events: list) -> dict:
    """Per entity: partitions used, processing order of seq numbers, and whether that order is ascending."""
    ordered, per = sorted(events, key=lambda e: e["done_ts"]), {}
    for ev in ordered:
        row = per.setdefault(ev["entity"], {"partitions": set(), "seq_in_processing_order": []})
        row["partitions"].add(ev["partition"])
        row["seq_in_processing_order"].append(ev["seq"])
    for row in per.values():
        row["partitions"] = sorted(row["partitions"])
        row["in_order"] = row["seq_in_processing_order"] == sorted(row["seq_in_processing_order"])
    return per


def write_csv(name: str, events: list) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_DIR / f"{name}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["order", "done_ts", "writer", "partition", "offset", "entity", "seq", "idx", "work_ms"])
        writer.writeheader()
        for order, ev in enumerate(sorted(events, key=lambda e: e["done_ts"]), 1):
            writer.writerow({"order": order, **ev})


def scenario_ordering(keyed: bool) -> dict:
    run = new_run("order")
    events: list = []
    group = f"{PREFIX}_order_{run}"
    agents = [Agent(n, group, Recorder(n, events), run) for n in ("writer-1", "writer-2")]
    wait_balanced(agents)
    assignment = {a.name: a.consumer.assigned for a in agents}
    log.info("ASSIGNMENT %s", json.dumps(assignment))
    producer, sent = KafkaProducer(), []
    for m in generate_messages(run):
        part, off = producer.send(TOPIC_TASKS, m, key=m["entity_id"] if keyed else None, partition=None if keyed else m["spread_partition"])
        sent.append({"idx": m["idx"], "entity": m["entity_id"], "seq": m["seq"], "sent_partition": part, "sent_offset": off})
    log.info("SENT      20 messages (VERIFY_SEED=%d) keyed=%s", VERIFY_SEED, keyed)
    deadline = time.time() + 60
    while len(events) < 20 and time.time() < deadline:
        time.sleep(0.5)
    for a in agents:
        a.close()
    per = analyse(events)
    name = "ordering_keyed" if keyed else "ordering_unkeyed"
    write_csv(name, events)
    result = {"scenario": "ordering", "keyed": keyed, "verify_seed": VERIFY_SEED, "processed": len(events), "assignment": assignment,
              "per_entity": per, "all_entities_in_one_partition": all(len(r["partitions"]) == 1 for r in per.values()),
              "all_entities_in_order": all(r["in_order"] for r in per.values()), "sent": sent}
    log.info("RESULT    %s", json.dumps({k: v for k, v in result.items() if k not in ("sent", "assignment")}))
    return result


# ------------------------------------------------------------------ CLI

def run_pair(label: str, before, after) -> None:
    for tag, fn in (("before", before), ("after", after)):
        log.info("=== %s : %s fix ===", label, tag.upper())
        save_raw(f"{label}_{tag}", fn())


def main(argv: list) -> int:
    setup_logging("tests")
    ensure_topics(TOPIC_PARTITIONS)
    which = argv[1] if len(argv) > 1 else "all"
    plan = {"dup": ("duplicate", lambda: scenario_duplicate(False), lambda: scenario_duplicate(True)),
            "crash": ("consumer_killed", lambda: scenario_crash(True), lambda: scenario_crash(False)),
            "poison": ("poison", lambda: scenario_poison(False), lambda: scenario_poison(True)),
            "ordering": ("ordering", lambda: scenario_ordering(False), lambda: scenario_ordering(True))}
    for key, (label, before, after) in plan.items():
        if which in (key, "all"):
            run_pair(label, before, after)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))