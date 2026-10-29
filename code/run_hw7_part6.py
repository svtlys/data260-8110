import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from file_tools import FileTools, confirm_bash  # noqa: E402

logger = logging.getLogger("part6")
RAW = Path(__file__).resolve().parent.parent / "reports" / "hw07" / "raw"
GATE_COMMANDS = [("ls -la", "allow"), ("cat notes.txt", "allow"), ("python -m pytest -q", "allow"),
                 ("rm -rf build", "block"), ("ls && rm -rf /", "block"), ("sudo ls", "block"), ("chmod -R 777 .", "block"),
                 ("dd if=/dev/zero of=/dev/disk2", "block"), ("mkfs.ext4 /dev/sdb1", "block"),
                 ("echo x > /etc/hosts", "block")]
SEED_FILES = {"app.py": "def main():\n    return 1\n", "helpers.py": "def log(x):\n    print('DEBUG', x)\n",
              "config.py": "NAME = 'demo'\n"}


def step(lines: list, title: str, result: dict) -> None:
    """Record one tool call and its result."""
    lines += [f"**{title}**", "```", json.dumps(result, indent=2)[:1500], "```", ""]


def demo(tools: FileTools) -> str:
    """Seed three files, then find the one with DEBUG using glob -> search -> read; then write and edit."""
    out = ["## Integration test: find the file that contains DEBUG", ""]
    for name, content in SEED_FILES.items():
        step(out, f"write_file {name}", tools.write_file(name, content))
    files = tools.glob_files("**/*.py")
    step(out, 'glob_files "**/*.py"', files)
    hits = tools.search_in_files("DEBUG", "*.py")
    step(out, 'search_in_files "DEBUG" in *.py', hits)
    found = hits["data"]["matches"][0]["file"]
    step(out, f"read_file {found}", tools.read_file(found, max_lines=20))
    step(out, f"edit_file {found} (remove the debug print)", tools.edit_file(found, "    print('DEBUG', x)", "    pass"))
    out.append(f"Result: the file containing DEBUG is **{found}**.")
    return "\n".join(out)


def gate(tools: FileTools) -> str:
    """The 10-command safety-gate test. Blocked commands are also sent to bash() to prove nothing runs."""
    tools.write_file("build/canary.txt", "still here")
    out = ["## Safety-gate test (10 commands)", "",
           "| # | Command | Expected | Gate (auto_approve=False) | Gate (auto_approve=True) | Reason |", "|---|---|---|---|---|---|"]
    ok = 0
    for i, (command, expected) in enumerate(GATE_COMMANDS, 1):
        plain, auto = confirm_bash(command), confirm_bash(command, auto_approve=True)
        got = "allow" if plain["allowed"] else "block"
        ok += got == expected and ("allow" if auto["allowed"] else "block") == expected
        out.append(f"| {i} | `{command}` | {expected} | {got} | {'allow' if auto['allowed'] else 'block'} | {plain['reason']} |")
    ran = tools.bash("rm -rf build", auto_approve=True)
    survived = (tools.root / "build" / "canary.txt").exists()
    out += ["", f"{ok}/10 commands behaved as expected.",
            f"`bash('rm -rf build', auto_approve=True)` -> success={ran['success']}, error={ran.get('error')!r}; "
            f"canary file still exists: {survived}."]
    return "\n".join(out)


def main() -> None:
    """Run in a temporary sandbox directory and save the evidence."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="all", choices=["demo", "gate", "all"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    RAW.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="data260_sandbox_") as tmp:
        tools = FileTools(tmp)
        logger.info("sandbox: %s", tmp)
        if args.command in ("demo", "all"):
            text = demo(tools)
            (RAW / "part6_integration.md").write_text(text)
            logger.info("%s\n", text)
        if args.command in ("gate", "all"):
            text = gate(tools)
            (RAW / "part6_safety_gate.md").write_text(text)
            logger.info("%s", text)


if __name__ == "__main__":
    main()