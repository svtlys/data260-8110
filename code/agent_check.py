import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import file_memory as fm

RAW = fm.ROOT / "reports" / "hw06" / "raw"
TASK = ("Write a Python function parse_rent(text) that converts rent strings such as '$2,400/mo' "
        "or '2400 per month' into an integer number of dollars per month, and raises ValueError "
        "for anything it cannot parse. Reply with one Python code block containing the function "
        "and its tests.")
SAFE_IMPORTS = {"re", "typing", "decimal", "math", "pytest", "logging", "dataclasses",
                "collections", "functools", "itertools", "string", "__future__"}
SECRET_NAMES = re.compile(r"(password|passwd|secret|token|api_?key)", re.I)


def extract_code(reply: str) -> str:
    """Join all fenced code blocks in the reply ('' if none)."""
    return "\n\n".join(re.findall(r"```(?:python|py)?\s*\n(.*?)```", reply, re.S))


def _funcs(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _calls(node, names):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in names]


def check_code(code: str) -> list:
    """Return [{'rule', 'passed', 'detail'}] for AGENT.md rules C1-C4, X1, N1, N2."""
    tree = ast.parse(code)
    funcs = _funcs(tree)
    prod = [f for f in funcs if not f.name.startswith("test_")]
    tests = [f for f in funcs if f.name.startswith("test_")]
    res = []

    def add(rule, ok, detail):
        res.append({"rule": rule, "passed": bool(ok), "detail": detail})

    bad = [f.name for f in prod if f.returns is None or any(
        a.annotation is None for a in f.args.args + f.args.kwonlyargs if a.arg not in ("self", "cls"))]
    add("C1 type hints on all parameters and return values", prod and not bad,
        f"missing in: {bad}" if bad else f"{len(prod)} function(s) checked")
    nodoc = [f.name for f in prod if not ast.get_docstring(f)]
    add("C2 docstring on every non-test function", prod and not nodoc,
        f"missing in: {nodoc}" if nodoc else "all present")
    badname = [f.name for f in funcs if not re.fullmatch(r"[a-z_][a-z0-9_]*", f.name)]
    long = [f"{f.name}({f.end_lineno - f.lineno + 1} lines)" for f in prod
            if f.end_lineno - f.lineno + 1 > 30]
    add("C3 snake_case names, functions <= 30 lines", not badname and not long,
        f"bad names: {badname}; too long: {long}" if badname or long else "ok")
    prints = [f.name for f in prod if _calls(f, {"print"})]
    add("C4 no print() in non-test functions", not prints,
        f"print() in: {prints}" if prints else "none found")
    good_tests = [t.name for t in tests if any(isinstance(n, ast.Assert) for n in ast.walk(t))
                  or "raises" in ast.dump(t)]
    add("X1 at least three test_ functions with assertions", len(good_tests) >= 3,
        f"{len(good_tests)} found: {good_tests}")
    secrets = [n.targets[0].id for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and isinstance(n.targets[0], ast.Name) and SECRET_NAMES.search(n.targets[0].id)
               and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
    add("N1 no hard-coded secrets", not secrets, f"found: {secrets}" if secrets else "none found")
    evals = [c.func.id for c in _calls(tree, {"eval", "exec"})]
    bare = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is None]
    add("N2 no eval/exec and no bare except", not evals and not bare,
        f"eval/exec: {evals}; bare except: {len(bare)}" if evals or bare else "none found")
    return res


def run_tests(code: str) -> dict:
    """Run the generated tests with pytest in a temp dir (only if imports are on the safe list)."""
    tree = ast.parse(code)
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    if mods - SAFE_IMPORTS:
        return {"ran": False, "detail": f"skipped: imports outside safe list: {sorted(mods - SAFE_IMPORTS)}"}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "test_generated.py").write_text(code)
        try:
            p = subprocess.run([sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                "test_generated.py"], cwd=d, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return {"ran": True, "passed": False, "detail": "timeout"}
    if "No module named pytest" in p.stderr + p.stdout:
        return {"ran": False, "detail": "pytest not installed (pip install pytest)"}
    return {"ran": True, "passed": p.returncode == 0, "detail": (p.stdout + p.stderr).strip()[-600:]}


def verify(llm, attempts: int = 3, model: str = "qwen3:8b", task: str = TASK) -> dict:
    """Generate the function, check it, and feed violations back until it passes (max attempts)."""
    system = fm.load_system_prompt()
    msgs = [{"role": "user", "content": task}]
    log = []
    for i in range(1, attempts + 1):
        reply = llm(system, msgs, model)["text"]
        code = extract_code(reply)
        if not code:
            checks, ok, tests = [], False, {"ran": False, "detail": "no code block"}
        else:
            try:
                checks = check_code(code)
                ok = all(c["passed"] for c in checks)
                tests = run_tests(code) if ok else {"ran": False, "detail": "static checks failed"}
            except SyntaxError as e:
                checks, ok, tests = [], False, {"ran": False, "detail": f"syntax error: {e}"}
        log.append({"attempt": i, "code": code, "checks": checks, "all_rules_passed": ok, "tests": tests})
        if ok:
            break
        failed = [c["rule"] + " - " + c["detail"] for c in checks if not c["passed"]] or ["no valid code block"]
        msgs += [{"role": "assistant", "content": reply},
                 {"role": "user", "content": "Your code broke these AGENT.md rules; fix them and "
                  "reply with the full corrected code block:\n- " + "\n- ".join(failed)}]
    return {"task": task, "attempts": log, "passed": log[-1]["all_rules_passed"]}


def main():
    from memory_llm import call_model
    out = verify(call_model)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "agent_md_verification.json").write_text(json.dumps(out, indent=2))
    last = out["attempts"][-1]
    (RAW / "generated_parse_rent.py").write_text(last["code"] + "\n")
    for a in out["attempts"]:
        print(f"\n=== attempt {a['attempt']}: {'PASS' if a['all_rules_passed'] else 'FAIL'} ===")
        for c in a["checks"]:
            print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['rule']}: {c['detail']}")
        print("  pytest:", a["tests"].get("detail", ""))
    print("\n--- final generated code ---\n" + last["code"])
    print("\nOVERALL:", "PASS" if out["passed"] else "FAIL")


if __name__ == "__main__":
    main()