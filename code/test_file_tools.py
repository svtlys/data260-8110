import file_tools as ft

GATE_CASES = [  # (command, expected allowed with auto_approve=False, expected allowed with auto_approve=True)
    ("ls -la", True, True),
    ("cat notes.txt", True, True),
    ("python -m pytest -q", True, True),
    ("rm -rf build", False, False),
    ("ls && rm -rf /", False, False),
    ("sudo ls", False, False),
    ("chmod -R 777 .", False, False),
    ("dd if=/dev/zero of=/dev/disk2", False, False),
    ("mkfs.ext4 /dev/sdb1", False, False),
    ("echo x > /etc/hosts", False, False),
]


def _tools(tmp_path) -> ft.FileTools:
    return ft.FileTools(tmp_path)


def test_read_file_numbers_lines_and_honours_max_lines(tmp_path) -> None:
    tools = _tools(tmp_path)
    tools.write_file("a.txt", "\n".join(f"line {i}" for i in range(1, 51)))
    out = tools.read_file("a.txt", max_lines=5)
    assert out["data"]["lines"][0] == "1: line 1" and len(out["data"]["lines"]) == 5
    assert out["data"]["truncated"] and out["data"]["total_lines"] == 50
    assert tools.read_file("a.txt", max_lines=5, offset=48)["data"]["lines"][-1] == "50: line 50"
    assert not tools.read_file("a.txt", max_lines=0)["success"]
    assert not tools.read_file("missing.txt")["success"]


def test_read_file_refuses_binary_and_paths_outside_the_sandbox(tmp_path) -> None:
    tools = _tools(tmp_path / "box")
    (tmp_path / "box").mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    (tmp_path / "box" / "bin.dat").write_bytes(b"\x00\x01\x02")
    assert not tools.read_file("bin.dat")["success"]
    assert not tools.read_file("../secret.txt")["success"]
    assert not tools.read_file(str(tmp_path / "secret.txt"))["success"]
    (tmp_path / "box" / "link").symlink_to(tmp_path / "secret.txt")
    assert not tools.read_file("link")["success"]


def test_write_file_creates_overwrites_and_stays_inside(tmp_path) -> None:
    tools = _tools(tmp_path)
    first = tools.write_file("pkg/mod.py", "x = 1\n")
    assert first["data"]["created"] and (tmp_path / "pkg" / "mod.py").read_text() == "x = 1\n"
    assert not tools.write_file("pkg/mod.py", "x = 2\n")["data"]["created"]
    assert not tools.write_file("../escape.txt", "no")["success"]
    assert not tools.write_file("pkg", "no")["success"]
    assert not (tmp_path.parent / "escape.txt").exists()


def test_edit_file_replaces_one_occurrence_and_shows_a_short_diff(tmp_path) -> None:
    tools = _tools(tmp_path)
    tools.write_file("a.py", "a = 1\nb = 2\nc = 3\n")
    out = tools.edit_file("a.py", "b = 2", "b = 20")
    assert out["success"] and "-b = 2" in out["data"]["diff"] and "+b = 20" in out["data"]["diff"]
    assert (tmp_path / "a.py").read_text() == "a = 1\nb = 20\nc = 3\n"
    assert not tools.edit_file("a.py", "zzz", "y")["success"]
    tools.write_file("dup.py", "x\nx\n")
    assert "2 times" in tools.edit_file("dup.py", "x", "y")["error"]
    assert (tmp_path / "dup.py").read_text() == "x\nx\n"


def test_glob_and_search_with_file_pattern(tmp_path) -> None:
    tools = _tools(tmp_path)
    tools.write_file("src/a.py", "print('hi')\n")
    tools.write_file("src/b.txt", "DEBUG in a text file\n")
    tools.write_file("src/deep/c.py", "x = 1  # DEBUG\n")
    assert tools.glob_files("**/*.py")["data"]["files"] == ["src/a.py", "src/deep/c.py"]
    assert not tools.glob_files("/etc/*")["success"] and not tools.glob_files("../*")["success"]
    hits = tools.search_in_files("DEBUG", "*.py")["data"]["matches"]
    assert [(h["file"], h["line"]) for h in hits] == [("src/deep/c.py", 1)]
    assert len(tools.search_in_files("DEBUG")["data"]["matches"]) == 2
    assert not tools.search_in_files("(")["success"]
    assert not tools.search_in_files("x", "../*.py")["success"]


def test_safety_gate_ten_commands(tmp_path) -> None:
    for command, plain, auto in GATE_CASES:
        assert ft.confirm_bash(command)["allowed"] is plain, command
        assert ft.confirm_bash(command, auto_approve=True)["allowed"] is auto, command
        assert ft.confirm_bash(command)["reason"]


def test_blocked_command_never_runs_and_allowed_command_does(tmp_path) -> None:
    tools = _tools(tmp_path)
    tools.write_file("build/keep.txt", "keep")
    blocked = tools.bash("rm -rf build", auto_approve=True)
    assert not blocked["success"] and "recursive deletion" in blocked["error"]
    assert (tmp_path / "build" / "keep.txt").exists()
    ran = tools.bash("ls build")
    assert ran["success"] and "keep.txt" in ran["data"]["stdout"]


def test_destructive_commands_need_a_human_even_with_safe_prefixes_and_auto_approve() -> None:
    hidden = ["ls; rm -rf /", "cat a.txt && sudo reboot", "echo hi | sudo tee /etc/x", "ls $(rm -rf x)", "bash -c 'rm -rf /'",
              "\\rm -rf x", "/bin/rm -fr x", "env FOO=1 rm -r x", "find . -delete", "echo x >/dev/sda", "diskutil eraseDisk JHFS+ X disk2",
              "grep foo . ; chown root a"]
    for command in hidden:
        assert ft.is_destructive(command), command
        assert not ft.confirm_bash(command, auto_approve=True)["allowed"], command
    assert ft.confirm_bash("rm -rf x", ask=lambda c, why: True)["allowed"]
    assert not ft.confirm_bash("rm -rf x", ask=lambda c, why: False)["allowed"]


def test_gate_does_not_block_harmless_commands() -> None:
    for command in ["rm --force x", "grep -rn DEBUG .", "echo hi > out.txt", "ls 2>&1", "echo x > /dev/null", "git status"]:
        assert not ft.is_destructive(command), command
    assert not ft.confirm_bash("make build")["allowed"] and ft.confirm_bash("make build", auto_approve=True)["allowed"]
    assert not ft.confirm_bash("")["allowed"]


def test_dispatch_rejects_unknown_tools_and_bad_arguments(tmp_path) -> None:
    tools = _tools(tmp_path)
    assert not ft.dispatch(tools, "delete_everything", {})["success"]
    assert not ft.dispatch(tools, "read_file", {"path": "a", "evil": 1})["success"]
    assert not ft.dispatch(tools, "read_file", {})["success"]
    assert ft.dispatch(tools, "write_file", {"path": "a.txt", "content": "hi"})["success"]


def test_integration_find_the_file_with_debug(tmp_path) -> None:
    tools = _tools(tmp_path)
    tools.write_file("app.py", "def main():\n    return 1\n")
    tools.write_file("helpers.py", "def log(x):\n    print('DEBUG', x)\n")
    tools.write_file("config.py", "NAME = 'demo'\n")
    files = tools.glob_files("**/*.py")["data"]["files"]
    assert files == ["app.py", "config.py", "helpers.py"]
    hits = tools.search_in_files("DEBUG", "*.py")["data"]["matches"]
    assert [h["file"] for h in hits] == ["helpers.py"]
    content = tools.read_file(hits[0]["file"])["data"]["lines"]
    assert any("DEBUG" in line for line in content)