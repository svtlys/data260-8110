import difflib
import logging
import os
import re
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger("file_tools")

DEFAULT_READ_LINES = 200
MAX_READ_LINES = 1000
MAX_FILE_BYTES = 2_000_000
MAX_LINE_CHARS = 200
MAX_WRITE_BYTES = 1_000_000
MAX_GLOB = 200
MAX_MATCHES = 100
MAX_DIFF_LINES = 40
BASH_TIMEOUT_S = 10
MAX_OUTPUT_CHARS = 4000

SAFE_PREFIXES = ("ls", "cat", "head", "tail", "wc", "grep", "pwd", "echo", "date", "which", "python --version",
                 "python3 --version", "python -m pytest", "python3 -m pytest", "pytest", "git status", "git diff", "git log")
WRAPPERS = {"command", "env", "nohup", "time", "exec", "xargs", "nice", "builtin"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
PRIVILEGE = {"sudo", "su", "doas", "pkexec", "runas"}
PERMISSION = {"chmod", "chown", "chgrp", "setfacl", "chattr", "chflags"}
MKFS = {"mke2fs", "newfs", "newfs_hfs", "newfs_msdos", "mkswap", "format"}
DISKUTIL_BAD = {"erasedisk", "erasevolume", "partitiondisk", "reformat", "zerodisk", "randomdisk", "secureerase"}
SYSTEM_ROOTS = {"etc", "usr", "bin", "sbin", "lib", "lib64", "boot", "sys", "proc", "var", "root", "system", "library",
                "applications", "opt", "srv", "private"}
DEVICE_RE = re.compile(r"^/dev/(sd|hd|vd|xvd|nvme|mmcblk|disk|rdisk|loop|mapper|dm-)", re.I)
REDIRECT_RE = re.compile(r"\d*>>?\s*(?!&)(\S+)")
SEPARATORS = re.compile(r"&&|\|\||[;|&\n]")
NOT_SIMPLE_RE = re.compile(r"[`<>\n]|\$\(|(?<!&)&(?!&)")


def _ok(data: dict) -> dict:
    return {"success": True, "data": data}


def _fail(error: str) -> dict:
    logger.warning("tool error: %s", error)
    return {"success": False, "error": error}


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


# ------------------------------------------------------------ the safety gate

def _segments(command: str, depth: int = 0) -> list:
    """Every separately executed part: chained commands, $(...), backticks and the string given to `sh -c`."""
    cleaned = re.sub(r"\d*>&\d*", " ", command)
    parts = SEPARATORS.split(cleaned) + re.findall(r"\$\(([^)]*)\)", cleaned) + re.findall(r"`([^`]*)`", cleaned)
    out = []
    for part in (p.strip() for p in parts if p.strip()):
        out.append(part)
        if depth < 3:
            out += _shell_c_segments(part, depth)
    return out


def _tokens(segment: str) -> list:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _command_tokens(segment: str) -> list:
    """Tokens of one part with env assignments and wrappers (env, nohup, time ...) removed."""
    tokens = _tokens(segment)
    while tokens and (re.fullmatch(r"\w+=\S*", tokens[0]) or os.path.basename(tokens[0]).lower() in WRAPPERS):
        tokens = tokens[1:]
    return tokens


def _shell_c_segments(segment: str, depth: int) -> list:
    tokens = _command_tokens(segment)
    if tokens and os.path.basename(tokens[0]).lower() in SHELLS and "-c" in tokens[1:]:
        index = tokens.index("-c")
        return _segments(tokens[index + 1], depth + 1) if index + 1 < len(tokens) else []
    return []


def _rm_reason(name: str, tokens: list) -> str | None:
    if name == "rm":
        for tok in tokens[1:]:
            if tok == "--recursive" or (tok.startswith("-") and not tok.startswith("--") and "r" in tok.lower()):
                return "recursive deletion"
    if name == "find" and any(t in ("-delete", "-exec", "-execdir", "-ok") for t in tokens):
        return "recursive deletion"
    return "recursive deletion" if name in ("shred", "srm") else None


def _device_reason(name: str, tokens: list, segment: str) -> str | None:
    if name == "dd" and any(t.lower().startswith("of=/dev/") and not t.lower().startswith("of=/dev/null") for t in tokens):
        return "raw device write"
    targets = REDIRECT_RE.findall(segment) + (tokens[1:] if name == "tee" else [])
    if any(DEVICE_RE.match(t.strip("'\"")) for t in targets):
        return "raw device write"
    return None


def _redirect_reason(name: str, tokens: list, segment: str) -> str | None:
    targets = REDIRECT_RE.findall(segment) + [t for t in tokens[1:] if not t.startswith("-")] * (name == "tee")
    for target in (t.strip("'\"") for t in targets):
        parts = [p for p in target.split("/") if p]
        if target in ("/", "/*") or (target.startswith("/") and parts and parts[0].lower() in SYSTEM_ROOTS):
            return "redirection to a root path"
    return None


def _fs_reason(name: str, tokens: list) -> str | None:
    if name.startswith("mkfs") or name in MKFS:
        return "filesystem creation"
    if name == "diskutil" and any(t.lower() in DISKUTIL_BAD for t in tokens[1:]):
        return "filesystem creation"
    return None


def _segment_reason(segment: str) -> str | None:
    tokens = _command_tokens(segment)
    if not tokens:
        return None
    name = os.path.basename(tokens[0]).lower().lstrip("\\")
    if name in PRIVILEGE:
        return "privilege escalation"
    if name in PERMISSION:
        return "permission or ownership change"
    checks = (_rm_reason(name, tokens), _device_reason(name, tokens, segment), _fs_reason(name, tokens),
              _redirect_reason(name, tokens, segment))
    return next((c for c in checks if c), None)


def destructive_reason(command: str) -> str | None:
    """Category of the first destructive part of the command, or None. Independent of SAFE_PREFIXES."""
    if not isinstance(command, str):
        return None
    for segment in _segments(command):
        reason = _segment_reason(segment)
        if reason:
            return reason
    return None


def is_destructive(command: str) -> bool:
    """True when any part of the command is destructive. Such commands always need a human yes."""
    return destructive_reason(command) is not None


def _all_safe(command: str) -> bool:
    if NOT_SIMPLE_RE.search(command):
        return False
    parts = [p.strip() for p in SEPARATORS.split(command) if p.strip()]
    return bool(parts) and all(any(p == s or p.startswith(s + " ") for s in SAFE_PREFIXES) for p in parts)


def confirm_bash(command: str, auto_approve: bool = False, ask=None) -> dict:
    """Decide whether a command may run. Returns {"allowed": bool, "reason": str}. `ask(command, why) -> bool` is the human."""
    if not isinstance(command, str) or not command.strip():
        return {"allowed": False, "reason": "empty command"}
    danger = destructive_reason(command)
    if danger:
        if ask is not None and ask(command, danger):
            return {"allowed": True, "reason": f"destructive ({danger}), confirmed by the user"}
        return {"allowed": False, "reason": f"destructive ({danger}): needs an explicit yes from the user; auto_approve does not apply"}
    if _all_safe(command):
        return {"allowed": True, "reason": "safe prefix"}
    if auto_approve:
        return {"allowed": True, "reason": "not on the safe list, auto-approved"}
    if ask is not None and ask(command, "not on the safe list"):
        return {"allowed": True, "reason": "not on the safe list, confirmed by the user"}
    return {"allowed": False, "reason": "not on the safe list: needs confirmation"}


# ------------------------------------------------------------ the tools

class FileTools:
    """The six tools, bound to one sandbox directory."""

    def __init__(self, root) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, path) -> Path:
        if not isinstance(path, str) or not path.strip() or "\0" in path:
            raise ValueError("path must be a non-empty string")
        candidate = Path(path)
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("path is outside the sandbox")
        return target

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _text(self, path) -> tuple:
        """(target, text, error) for an existing, readable text file inside the sandbox."""
        try:
            target = self._resolve(path)
        except ValueError as exc:
            return None, None, str(exc)
        if not target.is_file():
            return target, None, f"no such file: {path}"
        if target.stat().st_size > MAX_FILE_BYTES:
            return target, None, "file is larger than 2 MB"
        data = target.read_bytes()
        if b"\0" in data[:1024]:
            return target, None, "binary file"
        return target, data.decode("utf-8", errors="replace"), None

    def read_file(self, path: str, max_lines: int = DEFAULT_READ_LINES, offset: int = 0) -> dict:
        """Numbered lines of a text file, at most max_lines, starting after `offset` lines."""
        if not _int_in(max_lines, 1, MAX_READ_LINES) or not _int_in(offset, 0, 10**9):
            return _fail(f"max_lines must be an integer from 1 to {MAX_READ_LINES} and offset a non-negative integer")
        target, text, err = self._text(path)
        if err:
            return _fail(err)
        lines = text.splitlines()
        chunk = [f"{offset + i + 1}: {ln[:MAX_LINE_CHARS * 5]}" for i, ln in enumerate(lines[offset:offset + max_lines])]
        return _ok({"path": self._rel(target), "lines": chunk, "total_lines": len(lines),
                    "truncated": offset + max_lines < len(lines)})

    def write_file(self, path: str, content: str) -> dict:
        """Create or overwrite a text file (parent folders are created)."""
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return _fail("content must be a string of at most 1 MB")
        try:
            target = self._resolve(path)
        except ValueError as exc:
            return _fail(str(exc))
        if target.is_dir():
            return _fail("path is a directory")
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return _ok({"path": self._rel(target), "bytes": len(content.encode("utf-8")), "created": not existed})

    def edit_file(self, path: str, old_text: str, new_text: str) -> dict:
        """Replace exactly one occurrence of old_text. Returns a short unified diff."""
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            return _fail("old_text must be a non-empty string and new_text a string")
        target, text, err = self._text(path)
        if err:
            return _fail(err)
        count = text.count(old_text)
        if count != 1:
            return _fail("old_text was not found" if count == 0 else f"old_text appears {count} times; it must be unique")
        new = text.replace(old_text, new_text, 1)
        target.write_text(new, encoding="utf-8")
        rel = self._rel(target)
        diff = list(difflib.unified_diff(text.splitlines(), new.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="", n=1))
        return _ok({"path": rel, "diff": "\n".join(diff[:MAX_DIFF_LINES]), "diff_truncated": len(diff) > MAX_DIFF_LINES})

    def glob_files(self, pattern: str) -> dict:
        """Files under the sandbox matching a glob pattern such as **/*.py (sorted, at most 200)."""
        if not isinstance(pattern, str) or not pattern.strip() or pattern.startswith("/") or ".." in Path(pattern).parts:
            return _fail("pattern must be a relative glob such as **/*.py")
        found = sorted(self._rel(p) for p in self.root.glob(pattern) if p.is_file() and p.resolve().is_relative_to(self.root))
        return _ok({"files": found[:MAX_GLOB], "count": len(found), "truncated": len(found) > MAX_GLOB})

    def search_in_files(self, pattern: str, file_pattern: str = "*") -> dict:
        """Regex search. Returns file, line number and the line, for files matching file_pattern (at most 100 matches)."""
        if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
            return _fail("pattern must be a regular expression of at most 200 characters")
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return _fail(f"invalid regular expression: {exc}")
        if not isinstance(file_pattern, str) or "/" in file_pattern or ".." in file_pattern:
            return _fail("file_pattern must be a file-name glob such as *.py")
        matches = []
        for path in sorted(self.root.rglob(file_pattern)):
            matches += self._matches_in(path, regex, MAX_MATCHES - len(matches))
            if len(matches) >= MAX_MATCHES:
                break
        return _ok({"matches": matches, "count": len(matches), "truncated": len(matches) >= MAX_MATCHES})

    def _matches_in(self, path: Path, regex, room: int) -> list:
        rel = path.relative_to(self.root)
        if not path.is_file() or any(part.startswith(".") for part in rel.parts) or not path.resolve().is_relative_to(self.root):
            return []
        _, text, err = self._text(str(path))
        if err:
            return []
        hits = [{"file": rel.as_posix(), "line": i, "text": ln[:MAX_LINE_CHARS]}
                for i, ln in enumerate(text.splitlines(), 1) if regex.search(ln)]
        return hits[:room]

    def bash(self, command: str, auto_approve: bool = False, ask=None) -> dict:
        """Run a shell command in the sandbox, but only if confirm_bash allows it."""
        gate = confirm_bash(command, auto_approve, ask)
        if not gate["allowed"]:
            return {"success": False, "error": f"blocked: {gate['reason']}", "gate": gate}
        env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
        try:
            done = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True,
                                  timeout=BASH_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired:
            return _fail(f"command timed out after {BASH_TIMEOUT_S} s")
        return _ok({"exit_code": done.returncode, "stdout": done.stdout[:MAX_OUTPUT_CHARS],
                    "stderr": done.stderr[:MAX_OUTPUT_CHARS], "gate": gate})


TOOL_SPECS = [
    {"name": "read_file", "description": "Read a text file with line numbers.",
     "parameters": {"path": "string", "max_lines": "integer 1-1000 (default 200)", "offset": "integer (default 0)"}},
    {"name": "write_file", "description": "Create or overwrite a text file.",
     "parameters": {"path": "string", "content": "string"}},
    {"name": "edit_file", "description": "Replace one unique piece of text in a file; returns a short diff.",
     "parameters": {"path": "string", "old_text": "string", "new_text": "string"}},
    {"name": "glob_files", "description": "List files matching a glob pattern such as **/*.py.",
     "parameters": {"pattern": "string"}},
    {"name": "search_in_files", "description": "Regex search in files.",
     "parameters": {"pattern": "string", "file_pattern": "string (default *)"}},
    {"name": "bash", "description": "Run a shell command; destructive commands are blocked.",
     "parameters": {"command": "string"}},
]


def dispatch(tools: FileTools, name: str, args: dict) -> dict:
    """Call one tool by name with a dict of arguments. Unknown tools and unexpected arguments are errors, not crashes."""
    allowed = {"read_file": ("path", "max_lines", "offset"), "write_file": ("path", "content"),
               "edit_file": ("path", "old_text", "new_text"), "glob_files": ("pattern",),
               "search_in_files": ("pattern", "file_pattern"), "bash": ("command",)}
    if name not in allowed:
        return _fail(f"unknown tool: {name}")
    if not isinstance(args, dict) or set(args) - set(allowed[name]):
        return _fail(f"{name} accepts only these arguments: {', '.join(allowed[name])}")
    try:
        return getattr(tools, name)(**args)
    except TypeError as exc:  # a required argument is missing
        return _fail(f"bad arguments for {name}: {exc}")