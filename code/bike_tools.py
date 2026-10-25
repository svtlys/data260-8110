import argparse
import ast
import csv
import hashlib
import html
import io
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger("bike_tools")

SOURCE_NAME = "uploaded.csv"
MAX_ROWS = 50
MAX_SQL_CHARS = 2000
MAX_PAGE_BYTES = 2_000_000
MIN_PAGE_CHARS = 200
DEFAULT_K, MAX_K = 5, 10
MAX_EXPR_CHARS = 200
MAX_PROGRESS_CALLS = 300
USER_AGENT = "data260-hw7-course-agent/1.0 (student project; read-only)"

START_ALIASES = ("started_at", "start_date", "start_time", "starttime", "start")
END_ALIASES = ("ended_at", "end_date", "end_time", "stoptime", "stop_time", "end", "stop")
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum|reindex|truncate|"
    r"load_extension|readfile|writefile|into)\b", re.I)
ALLOWED_ACTIONS = (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION)
EXPR_RE = re.compile(r"[0-9+\-*/().\s]+")


# ------------------------------------------------------------ schemas

class CsvSqlArgs(BaseModel):
    """Arguments for csv_sql."""

    sql: str = Field(description="One read-only SELECT over the table named trips")


class PolicyArgs(BaseModel):
    """Arguments for policy_retriever."""

    url: str = Field(description="The pricing page URL")
    query: str = Field(description="What to look for, e.g. 'unlock fee per minute membership price'")
    k: int | None = Field(default=None, description="How many passages to return (1-10, default 5)")


class CalcArgs(BaseModel):
    """Arguments for calculator."""

    expression: str = Field(description="Arithmetic using digits and + - * / ( ) . only")
    units: str | None = Field(default=None, description="Optional unit label to echo back, e.g. USD")


TOOL_SPECS = {
    "csv_sql": {
        "description": "Run one read-only SELECT over the uploaded trips (table trips).",
        "input_schema": CsvSqlArgs.model_json_schema(),
        "output": {"rows": "Array<object>", "row_count": "number", "source": SOURCE_NAME},
    },
    "policy_retriever": {
        "description": "Fetch the pricing page and return short quotable passages that match the query.",
        "input_schema": PolicyArgs.model_json_schema(),
        "output": {"passages": "Array<{text: string, source: string, score: number}>"},
    },
    "calculator": {
        "description": "Safe arithmetic. Whitelist ^[0-9+\\-*/().\\s]+$, no eval.",
        "input_schema": CalcArgs.model_json_schema(),
        "output": {"value": "number", "units": "string?"},
    },
}


# ------------------------------------------------------------ envelope

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ok(data, source: str | None = None) -> dict:
    """Success envelope."""
    out = {"success": True, "data": data, "ts": _ts()}
    return {**out, "source": source} if source else out


def fail(error: str, source: str | None = None) -> dict:
    """Failure envelope. Tools return this instead of raising."""
    logger.warning("tool error: %s", error)
    out = {"success": False, "error": error, "ts": _ts()}
    return {**out, "source": source} if source else out


# ------------------------------------------------------------ loading the CSV

def parse_dt(value) -> datetime | None:
    """Parse the timestamp formats seen in public bike-share files. Returns a naive datetime or None."""
    text = str(value or "").strip()
    for candidate in (text, text.replace("Z", "")):
        try:
            return datetime.fromisoformat(candidate).replace(tzinfo=None)
        except ValueError:
            pass
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _col(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_") or "col"
    return cleaned if not cleaned[0].isdigit() else "c_" + cleaned


def canonical_columns(fieldnames: list) -> dict:
    """Map each CSV header to a safe SQL column name; start/end headers become started_at / ended_at."""
    mapping, used = {}, set()
    for header in fieldnames:
        name = _col(header)
        name = "started_at" if name in START_ALIASES else "ended_at" if name in END_ALIASES else name
        while name in used:
            name += "_x"
        used.add(name)
        mapping[header] = name
    return mapping


def _week_start(moment: datetime) -> str:
    return (moment - timedelta(days=moment.weekday())).strftime("%Y-%m-%d")


def _derived(row: dict, rideable: str | None):
    """Return (derived columns, skip reason) for one trip row."""
    start, end = parse_dt(row.get("started_at")), parse_dt(row.get("ended_at"))
    if start is None or end is None:
        return None, "bad_timestamp"
    minutes = (end - start).total_seconds() / 60
    if minutes <= 0 or minutes > 1440:
        return None, "duration_not_between_0_and_24h"
    electric = 0
    if rideable is not None:
        electric = int(any(w in str(row.get(rideable, "")).lower() for w in ("electric", "ebike", "e-bike", "e_bike")))
    return [round(minutes, 2), start.strftime("%Y-%m-%d"), _week_start(start), start.strftime("%Y-%m"), electric], None


def load_trips(text: str):
    """Load CSV text into an in-memory SQLite table named trips. Returns (connection, load_report)."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("the CSV has no header row")
    mapping = canonical_columns(reader.fieldnames)
    cols = list(mapping.values())
    if "started_at" not in cols or "ended_at" not in cols:
        raise ValueError("the CSV needs a start time and an end time column (started_at / ended_at)")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    extra = ["duration_min", "started_date", "week_start", "month", "is_electric"]
    conn.execute(f"CREATE TABLE trips ({', '.join(c + ' TEXT' for c in cols)}, duration_min REAL, "
                 "started_date TEXT, week_start TEXT, month TEXT, is_electric INTEGER)")
    skipped, rows = {}, []
    for raw in reader:
        row = {mapping[k]: v for k, v in raw.items() if k in mapping}
        derived, reason = _derived(row, "rideable_type" if "rideable_type" in cols else None)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        rows.append([row.get(c) for c in cols] + derived)
    marks = ", ".join("?" * (len(cols) + len(extra)))
    conn.executemany(f"INSERT INTO trips VALUES ({marks})", rows)
    conn.commit()
    return conn, _load_report(conn, cols + extra, skipped)


def _load_report(conn, columns: list, skipped: dict) -> dict:
    n, first, last, electric, months = conn.execute(
        "SELECT COUNT(*), MIN(started_at), MAX(started_at), SUM(is_electric), COUNT(DISTINCT month) FROM trips").fetchone()
    return {"rows_loaded": n, "rows_skipped": skipped, "columns": columns, "first_start": first,
            "last_start": last, "electric_rides": electric or 0, "distinct_months": months,
            "has_rideable_type": "rideable_type" in columns, "has_member_type": "member_casual" in columns}


def read_rides(conn) -> list:
    """All rides as small dicts for the cost calculation (trusted code path, not a model tool)."""
    cur = conn.execute("SELECT duration_min, is_electric, week_start, month FROM trips ORDER BY started_at")
    return [dict(zip(("duration_min", "is_electric", "week_start", "month"), r)) for r in cur.fetchall()]


# ------------------------------------------------------------ csv_sql

def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validate_select(sql) -> str | None:
    """Return an error message unless sql is exactly one read-only SELECT."""
    if not isinstance(sql, str) or not sql.strip():
        return "sql must be a non-empty string"
    if len(sql) > MAX_SQL_CHARS:
        return f"sql must be at most {MAX_SQL_CHARS} characters"
    text = sql.strip().rstrip(";").strip()
    bare = _strip_literals(text)
    if ";" in bare:
        return "only a single statement is allowed"
    if "--" in bare or "/*" in bare:
        return "comments are not allowed"
    if not re.match(r"(?is)^select\b", text):
        return "only SELECT statements are allowed"
    found = FORBIDDEN_SQL.search(bare)
    return f"forbidden keyword: {found.group(1).lower()}" if found else None


def _authorizer(action, *_):
    return sqlite3.SQLITE_OK if action in ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


class _Guard:
    """Context manager that makes a connection read-only (authorizer + query_only + work limit)."""

    def __init__(self, conn) -> None:
        self.conn, self.calls = conn, 0

    def _tick(self) -> int:
        self.calls += 1
        return 1 if self.calls > MAX_PROGRESS_CALLS else 0

    def __enter__(self):
        self.conn.execute("PRAGMA query_only = ON")
        self.conn.set_authorizer(_authorizer)
        self.conn.set_progress_handler(self._tick, 10000)
        return self

    def __exit__(self, *_exc):
        self.conn.set_authorizer(None)
        self.conn.set_progress_handler(None, 0)
        self.conn.execute("PRAGMA query_only = OFF")
        return False


def _run_unguarded(conn, sql: str) -> list:
    """What a naive tool does: run whatever it is given. Used only for the Part 5 'before' results."""
    try:
        cur = conn.execute(sql)
    except sqlite3.ProgrammingError:  # several statements in one string
        conn.executescript(sql)
        return []
    rows = cur.fetchmany(MAX_ROWS)
    conn.commit()
    return [dict(zip([d[0] for d in cur.description or []], r)) for r in rows]


def _run_guarded(conn, sql: str) -> list:
    with _Guard(conn):
        cur = conn.execute(sql)
        names = [d[0] for d in cur.description or []]
        return [dict(zip(names, r)) for r in cur.fetchmany(MAX_ROWS)]


def csv_sql(sql, conn, enforce: bool = True) -> dict:
    """Run one read-only SELECT over the uploaded trips."""
    if enforce:
        problem = validate_select(sql)
        if problem:
            return fail(f"blocked by the read-only SELECT contract: {problem}", SOURCE_NAME)
    try:
        rows = (_run_guarded if enforce else _run_unguarded)(conn, sql)
    except sqlite3.Error as exc:
        return fail(f"sql error: {exc}", SOURCE_NAME)
    return ok({"rows": rows, "row_count": len(rows), "source": SOURCE_NAME,
               "truncated_at": MAX_ROWS if len(rows) >= MAX_ROWS else None}, SOURCE_NAME)


# ------------------------------------------------------------ policy_retriever

def html_to_text(raw: str) -> str:
    """Visible text of an HTML page, one block per line."""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|table|ul|ol)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in text.split("\n"))
    return "\n".join(ln for ln in lines if ln)


def default_fetcher(url: str, allowed_roots=()) -> tuple:
    """Fetch a page. Returns (html, final_url). http(s) anywhere; file:// only inside allowed_roots."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).resolve()
        if not any(path.is_relative_to(Path(r).resolve()) for r in allowed_roots):
            raise ValueError("file:// URLs are only allowed inside the fixtures and snapshot folders")
        return path.read_text(errors="replace"), url
    import requests

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, allow_redirects=True, stream=True)
    resp.raise_for_status()
    body = resp.raw.read(MAX_PAGE_BYTES + 1, decode_content=True)
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("the page is larger than 2 MB")
    return body.decode(resp.encoding or "utf-8", errors="replace"), resp.url


def split_passages(text: str) -> list:
    """Short quotable pieces: sentences and short lines, 20-400 characters."""
    lines = text.split("\n")
    pieces = []
    for i, line in enumerate(lines):
        pieces += [p.strip() for p in re.split(r"(?<=[.!?])\s+", line)]
        if "$" in line and len(line) < 40:  # a bare price such as "$120/year": keep its neighbouring lines
            pieces.append(" | ".join(lines[max(0, i - 2):i + 2]))
    return [p[:400] for p in pieces if 20 <= len(p)]


def score_passage(passage: str, query_words: set) -> float:
    """Keyword overlap, plus a bonus for prices and minutes. Higher = more relevant."""
    words = set(re.findall(r"[a-z]{3,}", passage.lower()))
    bonus = (1.0 if re.search(r"\$\s?\d", passage) else 0) + (0.5 if re.search(r"\bmin(ute)?s?\b", passage, re.I) else 0)
    return round((len(words & query_words) + bonus) / (len(query_words) + 1.5), 3)


def _fetch_into_cache(url: str, cache: dict, fetcher, allowed_roots) -> dict:
    if url in cache:
        return cache[url]
    raw, final_url = fetcher(url) if fetcher else default_fetcher(url, allowed_roots)
    text = html_to_text(raw)
    cache[url] = {"url": url, "final_url": final_url, "captured_at": _ts(), "text": text,
                  "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return cache[url]


def policy_retriever(url, query, k=None, *, cache: dict, fetcher=None, allowed_roots=()) -> dict:
    """Fetch the pricing page (once per run) and return the k most relevant passages."""
    if not isinstance(url, str) or urlparse(url).scheme not in ("http", "https", "file"):
        return fail("url must be an http(s) URL")
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return fail("query must be a non-empty string of at most 200 characters")
    k = DEFAULT_K if k is None else k
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        return fail(f"k must be an integer from 1 to {MAX_K}")
    try:
        entry = _fetch_into_cache(url, cache, fetcher, allowed_roots)
    except Exception as exc:  # network errors, bad file paths, HTTP errors
        return fail(f"could not fetch the page: {type(exc).__name__}: {exc}", url)
    if len(entry["text"]) < MIN_PAGE_CHARS:
        return fail(f"the page gave only {len(entry['text'])} characters of text (it may need JavaScript)", url)
    words = set(re.findall(r"[a-z]{3,}", query.lower()))
    ranked = sorted(((score_passage(p, words), p) for p in split_passages(entry["text"])), reverse=True)
    passages = [{"text": p, "source": entry["final_url"], "score": s} for s, p in ranked[:k] if s > 0]
    snapshot = {key: entry[key] for key in ("url", "final_url", "captured_at", "sha256")}
    return ok({"passages": passages, "snapshot": snapshot}, entry["final_url"])


def save_snapshot(entry: dict, directory, label: str) -> dict:
    """Write the exact text used (so its SHA-256 can be re-checked) plus a small JSON record."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    text_path, meta_path = folder / f"{label}_pricing_snapshot.txt", folder / f"{label}_pricing_snapshot.json"
    text_path.write_text(entry["text"], encoding="utf-8")
    meta = {k: entry[k] for k in ("url", "final_url", "captured_at", "sha256")} | {"chars": len(entry["text"]),
                                                                                  "text_file": text_path.name}
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


# ------------------------------------------------------------ calculator

_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b}
_UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calculator(expression, units=None) -> dict:
    """Safe arithmetic: whitelist check, then a tiny AST walker. No eval."""
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPR_CHARS:
        return fail(f"expression must be a non-empty string of at most {MAX_EXPR_CHARS} characters")
    if not EXPR_RE.fullmatch(expression):
        return fail("expression may only contain digits and + - * / ( ) . and spaces")
    try:
        value = float(_eval(ast.parse(expression.strip(), mode="eval")))
    except ZeroDivisionError:
        return fail("division by zero")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return fail("expression is not valid arithmetic")
    if value != value or value in (float("inf"), float("-inf")):
        return fail("result is not a finite number")
    data = {"value": round(value, 6)}
    return ok({**data, "units": units} if units else data)


# ------------------------------------------------------------ small CLI

def main() -> None:
    """python bike_tools.py schemas | check-url URL"""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("command", choices=["schemas", "check-url"])
    parser.add_argument("url", nargs="?")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.command == "schemas":
        sys.stdout.write(json.dumps(TOOL_SPECS, indent=2) + "\n")
        return
    result = policy_retriever(args.url or "", "unlock fee per minute membership price included minutes", 8, cache={})
    sys.stdout.write(json.dumps(result, indent=2)[:6000] + "\n")


if __name__ == "__main__":
    main()