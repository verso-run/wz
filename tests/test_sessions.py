"""`wz cli` and the session commands (start-all, park, roll, list) against a REAL tmux with a stand-in `claude`.

Each test runs its own tmux server (TMUX_TMPDIR in a short temp dir), so nothing here touches the tmux you are using.
Skipped when tmux is not installed (a failure when WZ_REQUIRE_TMUX is set, as in CI). tests/fake_claude_tui.py records every start in $WZ_HOME/claude-calls.jsonl.
"""
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from conftest import answers, make_repo

from wz import cli, jobs, registry, sessions, setup_mode

TUI = Path(__file__).resolve().parent / "fake_claude_tui.py"
REAL_TMUX = shutil.which("tmux")


def stop_server(sock) -> list[int]:
    """Kill the tmux server on this socket dir and return the pids of every pane process it had (all gone, or a test fails).

    TMUX is dropped from the environment first: a test that sets it to a made-up socket (as the switch-client one does) would
    otherwise point `kill-server` at that socket and leave the real server, and the stand-in `claude` in its panes, running.
    """
    env = {k: v for k, v in os.environ.items() if k != "TMUX"} | {"TMUX_TMPDIR": str(sock)}
    panes = subprocess.run([REAL_TMUX, "list-panes", "-a", "-F", "#{pane_pid}"], capture_output=True, text=True, env=env)
    pids = [int(x) for x in panes.stdout.split()]
    subprocess.run([REAL_TMUX, "kill-server"], capture_output=True, env=env)
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:                                            # a zombie (not yet reaped by its parent) is gone for our purposes
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:                                 # no /proc (macOS), or it was reaped between the two lines: ask again
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True


def wait_gone(pids, timeout=5) -> list[int]:
    end = time.time() + timeout
    while time.time() < end and any(_alive(p) for p in pids):
        time.sleep(0.05)
    return [p for p in pids if _alive(p)]


class Rig:
    def __init__(self, tmp_path, sock, bindir):
        self.tmp, self.sock, self.bindir = tmp_path, sock, bindir

    def workspace(self, name="ws", project="fernhill", extra_roles=None, agent_command="claude"):
        base = self.tmp / name
        base.mkdir(parents=True, exist_ok=True)
        make_repo(base / "app")
        (base / "office" / "drafts").mkdir(parents=True)
        a = answers(base)
        a["project"] = project
        a["agent_command"] = agent_command
        a["roles"].update(extra_roles or {})
        return setup_mode.apply(a, base / "home dir", git_init=False)

    def wz(self, cfg, *argv):
        return cli.main(["--config", str(cfg.path), *argv])

    def tmux(self, *a):
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        return subprocess.run([REAL_TMUX, *a], capture_output=True, text=True, env=env)

    def has(self, name):
        return self.tmux("has-session", "-t", "=" + name).returncode == 0

    def calls(self, cfg, n=None, timeout=8):
        f = cfg.root / "claude-calls.jsonl"
        end = time.time() + timeout
        while time.time() < end:
            rows = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
            if n is None or len(rows) >= n:
                return rows
            time.sleep(0.1)
        raise AssertionError(f"wanted {n} claude starts, saw {len(rows) if f.exists() else 0}")

    def mode(self, cfg, text):
        (cfg.root / "fake-mode").write_text(text)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    if not REAL_TMUX:
        if os.environ.get("WZ_REQUIRE_TMUX"):       # CI sets this: a missing tmux there must not turn into a silent skip
            pytest.fail("tmux is not installed but WZ_REQUIRE_TMUX is set")
        pytest.skip("tmux is not installed")
    sock = Path(tempfile.mkdtemp(prefix="wzt-"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    claude = bindir / "claude"
    claude.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(TUI))} \"$@\"\n")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("TMUX_TMPDIR", str(sock))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setenv("WZ_START_SETTLE", "0.4")
    monkeypatch.setenv("WZ_START_WAIT", "15")
    monkeypatch.setenv("WZ_SAY_SETTLE", "0.15")
    monkeypatch.setenv("WZ_SAY_WAIT", "0.4")
    r = Rig(tmp_path, sock, bindir)
    yield r
    left = wait_gone(stop_server(sock))
    shutil.rmtree(sock, ignore_errors=True)
    assert not left, f"the test left processes running in its tmux server: {left}"


@pytest.fixture
def cfg(rig):
    return rig.workspace()


def arg(call, flag):
    return call["args"][call["args"].index(flag) + 1]


def test_the_rig_stops_its_server_and_the_stand_in_even_when_the_test_set_TMUX(rig, cfg, monkeypatch):
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    rig.calls(cfg, 1)
    pids = [int(x) for x in rig.tmux("list-panes", "-a", "-F", "#{pane_pid}").stdout.split()]
    assert pids and all(_alive(p) for p in pids)
    monkeypatch.setenv("TMUX", "/tmp/not-a-real-socket,1,0")        # what the switch-client test does, and keeps until it ends
    assert wait_gone(stop_server(rig.sock)) == []
    assert wait_gone(pids) == []                                    # the pane's shell and the stand-in `claude`
    monkeypatch.delenv("TMUX")
    assert rig.tmux("list-sessions").returncode != 0                # no server answers on this socket any more


# ---- first start ---------------------------------------------------------------------------------------------------
def test_first_start_is_named_and_gets_its_environment(rig, cfg):
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    (c,) = rig.calls(cfg, 1)
    assert rig.has("wz-fernhill-mission-ctl")
    assert arg(c, "--name") == "wz-fernhill-mission-ctl" and "--resume" not in c["args"]
    assert c["cwd"] == str(cfg.store_root("workspace"))
    e = c["env"]
    assert (e["WZ_ROLE"], e["WZ_CONFIG"], e["WZ_HOME"]) == ("mission-ctl", str(cfg.path), str(cfg.root))
    assert e["WZ_SCRATCH"] == str(cfg.scratch("mission-ctl")) and e["WZ_JOB"] is None
    assert e["PATH"].split(os.pathsep)[0] == str(rig.bindir)
    assert arg(c, "--append-system-prompt-file") == str(cfg.charter_path("mission-ctl"))


def test_a_quoted_agent_command_reaches_claude_as_the_same_arguments(rig):
    rule = "WebSearch,WebFetch,Bash(python3 tools/qg.py *)"
    cfg = rig.workspace(agent_command=f'claude --allowedTools "{rule}"')
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    (c,) = rig.calls(cfg, 1)
    assert c["args"][c["args"].index("--allowedTools") + 1] == rule          # one argument, quotes gone, not split at the spaces


def test_environment_comes_from_the_shell_not_from_the_server(rig, cfg, monkeypatch):
    # a tmux server that started long before, with another PATH and another Claude account
    env = {**os.environ, "PATH": "/usr/bin:/bin", "CLAUDE_CONFIG_DIR": "/somewhere/else", "WZ_JOB": "J-1"}
    subprocess.run([REAL_TMUX, "new-session", "-d", "-s", "other", "sleep 600"], env=env, check=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(rig.tmp / "acct"))
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    (c,) = rig.calls(cfg, 1)
    assert str(rig.bindir) in c["env"]["PATH"].split(os.pathsep)
    assert c["env"]["CLAUDE_CONFIG_DIR"] == str(rig.tmp / "acct")
    assert c["env"]["WZ_JOB"] is None


def test_no_claude_is_an_error_not_a_vanished_session(rig, cfg, monkeypatch, capsys):
    bare = [str(Path(REAL_TMUX).parent), "/usr/bin", "/bin"]       # tmux itself, but no claude anywhere
    monkeypatch.setenv("PATH", os.pathsep.join(bare))
    monkeypatch.setattr(sessions, "_path_dirs", lambda cfg, command0: bare)
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 1
    assert "Claude Code" in capsys.readouterr().err
    assert not rig.has("wz-fernhill-mission-ctl")


def _wait_exit(cfg, timeout=8):
    f = cfg.state / "sessions" / "mission-ctl.state"
    end = time.time() + timeout
    while time.time() < end:
        if f.exists() and f.read_text().startswith("exited"):
            return f.read_text().split()
        time.sleep(0.1)
    raise AssertionError("claude never ended")


def test_claude_exiting_at_once_leaves_a_shell_and_the_next_cli_starts_it_over(rig, cfg, capsys):
    rig.mode(cfg, "exit")
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    assert _wait_exit(cfg)[:2] == ["exited", "3"]
    assert rig.has("wz-fernhill-mission-ctl")                 # the window is a shell, not gone
    capsys.readouterr()
    rig.wz(cfg, "list")
    assert "Claude ended" in capsys.readouterr().out
    (cfg.root / "fake-mode").unlink()
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    again = rig.calls(cfg, 2)[1]
    # nothing was saved under that name in 30 s, so --resume would find nothing: it is created again
    assert arg(again, "--name") == "wz-fernhill-mission-ctl" and "--resume" not in again["args"]
    assert rig.has("wz-fernhill-mission-ctl")


def test_a_short_run_that_saved_its_conversation_is_resumed(rig, cfg):
    rig.mode(cfg, "exit-saved")
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    _wait_exit(cfg)
    (cfg.root / "fake-mode").unlink()
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    assert arg(rig.calls(cfg, 2)[1], "--resume") == "wz-fernhill-mission-ctl"


# ---- existing sessions ---------------------------------------------------------------------------------------------
def test_running_session_is_reattached_not_started_twice_and_restart_applies_changes(rig, cfg, capsys):
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    rig.calls(cfg, 1)
    capsys.readouterr()
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    assert "running" in capsys.readouterr().out
    assert len(rig.calls(cfg)) == 1
    cfg.charter_path("mission-ctl").write_text(cfg.charter_path("mission-ctl").read_text() + "\nA new rule.\n")
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    assert "--restart" in capsys.readouterr().err and len(rig.calls(cfg)) == 1
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach", "--restart") == 0
    second = rig.calls(cfg, 2)[1]
    assert arg(second, "--resume") == "wz-fernhill-mission-ctl"


def test_a_role_whose_name_starts_a_longer_one_gets_its_own_session(rig):
    extra = {"app-ui": {"pack": "software", "store": "app", "owns": {"app": ["ui/**"]}}}
    cfg = rig.workspace(extra_roles=extra)
    rig.wz(cfg, "cli", "app-ui", "--detach")
    rig.wz(cfg, "cli", "app", "--detach")
    cs = rig.calls(cfg, 2)
    assert sorted(c["env"]["WZ_ROLE"] for c in cs) == ["app", "app-ui"]
    assert rig.has("wz-fernhill-app") and rig.has("wz-fernhill-app-ui")


def test_two_workspaces_with_one_project_name_do_not_share_a_session(rig, cfg, capsys):
    other = rig.workspace(name="ws2")
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    capsys.readouterr()
    assert rig.wz(other, "cli", "mission-ctl", "--detach") == 1
    assert "another wz workspace" in capsys.readouterr().err


def test_project_name_and_paths_with_odd_characters(rig):
    cfg = rig.workspace(name="my work space", project="my.proj: a b")
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    (c,) = rig.calls(cfg, 1)
    assert rig.has("wz-my-proj-a-b-mission-ctl")
    assert " " in c["cwd"] and " " in arg(c, "--append-system-prompt-file")
    assert arg(c, "--name") == "wz-my-proj-a-b-mission-ctl"


# ---- attach, and inside tmux ---------------------------------------------------------------------------------------
def _tmux_logger(rig, monkeypatch):
    """A `tmux` in front of the real one that logs its arguments and answers attach/switch-client itself (no terminal here)."""
    log = rig.tmp / "tmux-calls.log"
    shim = rig.bindir / "tmux"
    shim.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + shlex.quote(str(log)) + "\n"
                    "case \"$1\" in attach-session|switch-client) exit 0;; esac\n"
                    f"exec env -u TMUX {shlex.quote(REAL_TMUX)} \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return lambda: log.read_text().splitlines() if log.exists() else []


def test_outside_tmux_attaches_inside_tmux_switches_client(rig, cfg, monkeypatch):
    seen = _tmux_logger(rig, monkeypatch)
    assert rig.wz(cfg, "cli", "mission-ctl") == 0
    assert "attach-session -t =wz-fernhill-mission-ctl" in seen()
    assert not any(l.startswith("switch-client") for l in seen())
    monkeypatch.setenv("TMUX", "/tmp/not-a-real-socket,1,0")
    assert rig.wz(cfg, "cli", "mission-ctl") == 0
    assert "switch-client -t =wz-fernhill-mission-ctl" in seen()
    assert sum(l.startswith("attach-session") for l in seen()) == 1


# ---- reboot, park, roll, list --------------------------------------------------------------------------------------
def test_start_all_after_a_reboot_resumes_the_same_conversations(rig, cfg, capsys):
    for role in ("mission-ctl", "app", "tester"):
        rig.wz(cfg, "cli", role, "--detach")
    first = rig.calls(cfg, 3)
    names = {c["env"]["WZ_ROLE"]: arg(c, "--name") for c in first}
    assert names == {r: f"wz-fernhill-{r}" for r in ("mission-ctl", "app", "tester")}
    assert rig.wz(cfg, "park", "tester") == 0
    assert not rig.has("wz-fernhill-tester")
    rig.tmux("kill-server")                                 # the reboot
    assert not rig.has("wz-fernhill-mission-ctl")
    capsys.readouterr()
    assert rig.wz(cfg, "start-all") == 0
    again = rig.calls(cfg, 5)[3:]
    assert {c["env"]["WZ_ROLE"]: arg(c, "--resume") for c in again} == {r: names[r] for r in ("mission-ctl", "app")}
    assert all("--name" not in c["args"] for c in again)
    out = capsys.readouterr().out
    assert "parked" in out and "running, at the input box" in out
    assert rig.has("wz-fernhill-mission-ctl") and not rig.has("wz-fernhill-tester")
    # a second start-all finds them running and starts nothing
    assert rig.wz(cfg, "start-all") == 0
    assert len(rig.calls(cfg)) == 5


def test_cli_brings_a_parked_role_back_resuming_its_conversation(rig, cfg):
    rig.wz(cfg, "cli", "app", "--detach")
    rig.wz(cfg, "park", "app")
    assert sessions.load(cfg, "app")["parked"] is True
    rig.wz(cfg, "cli", "app", "--detach")
    c = rig.calls(cfg, 2)[1]
    assert arg(c, "--resume") == "wz-fernhill-app"
    assert sessions.load(cfg, "app")["parked"] is False


def test_roll_bumps_the_name_and_start_all_resumes_the_new_one(rig, cfg):
    rig.wz(cfg, "cli", "app", "--detach")
    assert rig.wz(cfg, "roll", "app") == 0
    c = rig.calls(cfg, 2)[1]
    assert arg(c, "--name") == "wz-fernhill-app-2" and rig.has("wz-fernhill-app")
    rig.tmux("kill-server")
    assert rig.wz(cfg, "start-all") == 0
    assert arg(rig.calls(cfg, 3)[2], "--resume") == "wz-fernhill-app-2"


def test_start_all_reports_a_role_that_is_not_at_an_input_box(rig, cfg, capsys, monkeypatch):
    monkeypatch.setenv("WZ_START_WAIT", "6")
    rig.wz(cfg, "cli", "app", "--detach")
    rig.calls(cfg, 1)
    rig.tmux("kill-server")
    rig.mode(cfg, "login")
    capsys.readouterr()
    assert rig.wz(cfg, "start-all") == 1
    assert "log in" in capsys.readouterr().err


def test_start_all_reports_a_role_whose_claude_ends_at_once(rig, cfg, capsys):
    rig.wz(cfg, "cli", "app", "--detach")
    rig.calls(cfg, 1)
    rig.tmux("kill-server")
    rig.mode(cfg, "exit")
    capsys.readouterr()
    assert rig.wz(cfg, "start-all") == 1
    assert "Claude exited" in capsys.readouterr().err
    assert rig.has("wz-fernhill-app")                       # reported, and the window is still there as a shell


def test_list_shows_each_role(rig, cfg, capsys):
    rig.wz(cfg, "cli", "app", "--detach")
    rig.calls(cfg, 1)
    capsys.readouterr()
    assert rig.wz(cfg, "list") == 0
    out = capsys.readouterr().out
    assert "wz-fernhill-app" in out and "never started" in out
    assert len(out.strip().splitlines()) == 1 + len(cfg.roles())


# ---- --print and --no-tmux -----------------------------------------------------------------------------------------
def test_print_is_pasteable_and_shows_the_conversation(rig, capsys):
    cfg = rig.workspace(name="my work space")
    assert rig.wz(cfg, "cli", "mission-ctl", "--print") == 0
    lines = capsys.readouterr().out.splitlines()
    assert shlex.split(lines[0]) == ["cd", str(cfg.store_root("workspace"))]
    words = shlex.split(lines[1])
    assert words[0] == "env" and "WZ_ROLE=mission-ctl" in words and words[-2:] == ["--name", "wz-fernhill-mission-ctl"]
    assert str(cfg.charter_path("mission-ctl")) in words
    assert not (cfg.state / "sessions").exists() or not sessions.load(cfg, "mission-ctl")["launched"]


def test_no_tmux_runs_here_and_still_resumes(rig, cfg):
    rig.mode(cfg, "exit-saved")
    assert rig.wz(cfg, "cli", "app", "--no-tmux") == 3
    assert rig.wz(cfg, "cli", "app", "--no-tmux") == 3
    a, b = rig.calls(cfg, 2)
    assert arg(a, "--name") == "wz-fernhill-app" and arg(b, "--resume") == "wz-fernhill-app"
    assert not rig.has("wz-fernhill-app")


def test_no_tmux_ending_before_anything_is_saved_starts_over(rig, cfg):
    rig.mode(cfg, "exit")
    rig.wz(cfg, "cli", "app", "--no-tmux")
    rig.wz(cfg, "cli", "app", "--no-tmux")
    a, b = rig.calls(cfg, 2)
    assert arg(a, "--name") == arg(b, "--name") == "wz-fernhill-app"


def test_without_tmux_installed_cli_runs_in_the_terminal(rig, cfg, monkeypatch, capsys):
    rig.mode(cfg, "exit")
    monkeypatch.setattr(sessions, "have_tmux", lambda: False)
    assert rig.wz(cfg, "cli", "app") == 3
    assert "tmux is not installed" in capsys.readouterr().err
    assert rig.wz(cfg, "cli", "app", "--detach") == 1


# ---- reading the pane ----------------------------------------------------------------------------------------------
def test_classify():
    rule = "\u2500" * 40
    assert sessions.classify(f"hi\n{rule}\n\u276f \n{rule}\n  ? for shortcuts") == "ready"
    assert sessions.classify("Select login method:\n 1. Claude account") == "login"
    assert sessions.classify("No conversations found to resume") == "resume_picker"
    assert sessions.classify("Do you trust the files in this folder?\nEsc to cancel") == "dialog"
    assert sessions.classify("[wz] Claude ended\nuser@host:~/ws$ ") == "shell"
    assert sessions.classify("Starting...") == "busy"


# ---- wz say --------------------------------------------------------------------------------------------------------
def said(cfg):
    f = cfg.root / "said.jsonl"
    return [json.loads(x)["text"] for x in f.read_text().splitlines()] if f.exists() else []


def pane_box(rig, cfg, role):
    return sessions.pane_input(sessions.capture(sessions.tmux_name(cfg, role)))


def test_say_types_into_a_live_session_and_confirms_the_box_emptied(rig, cfg, capsys):
    assert rig.wz(cfg, "cli", "app", "--detach") == 0
    capsys.readouterr()
    assert rig.wz(cfg, "say", "app", "please", "check the footer") == 0
    assert said(cfg) == ["please check the footer"]
    assert "input box emptied" in capsys.readouterr().out
    log = [json.loads(x) for x in (cfg.state / "say.jsonl").read_text().splitlines()]
    assert [(r["from"], r["to"], r["outcome"], r["text"]) for r in log] == [("owner", "app", "submitted", "please check the footer")]
    assert pane_box(rig, cfg, "app") == ""


def test_say_from_a_role_says_who_it_is_from_and_collapses_lines(rig, cfg, monkeypatch):
    rig.wz(cfg, "cli", "mission-ctl", "--detach")
    monkeypatch.setenv("WZ_ROLE", "app")
    assert rig.wz(cfg, "say", "mission-ctl", "blocked on a decision\nsee brief 3") == 0
    assert said(cfg) == ["[from app] blocked on a decision see brief 3"]


def test_say_whose_line_is_still_typed_is_a_failure_not_a_report_of_success(rig, cfg, capsys):
    rig.mode(cfg, "stuck")
    rig.wz(cfg, "cli", "app", "--detach")
    capsys.readouterr()
    assert rig.wz(cfg, "say", "app", "hello") == 1
    err = capsys.readouterr()
    assert "FAILED" in err.err and "still in app's input box" in err.err and "said to" not in err.out
    assert said(cfg) == []
    assert pane_box(rig, cfg, "app") == ""          # cleared, so it is not glued onto the next line


def test_say_to_a_session_in_the_middle_of_a_turn_is_queued_not_retried(rig, cfg, capsys):
    rig.mode(cfg, "queued")
    rig.wz(cfg, "cli", "app", "--detach")
    capsys.readouterr()
    assert rig.wz(cfg, "say", "app", "hello") == 0
    assert "queued" in capsys.readouterr().out
    assert said(cfg) == ["hello"]                   # one copy: Enter was not pressed again


def test_say_to_a_role_with_no_session_writes_a_note_and_queues_no_job(rig, cfg, capsys):
    state = cfg.role_dir("app") / "STATE.md"
    before = state.read_text()
    assert rig.wz(cfg, "say", "app", "the spec changed: see brief 4") == 0
    out = capsys.readouterr().out
    assert "no live session" in out and "nothing was typed" in out and "no job was queued" in out
    assert json.loads((cfg.state / "say.jsonl").read_text().splitlines()[-1])["outcome"] == "noted"
    top = state.read_text().split("\n\n")[0]
    assert top.startswith("> **Note ") and top.endswith("the spec changed: see brief 4")
    assert state.read_text().endswith(before)
    assert jobs.all_jobs(cfg) == []
    assert not rig.has(sessions.tmux_name(cfg, "app")) and said(cfg) == []


def test_say_to_a_parked_role_is_a_note(rig, cfg, capsys):
    rig.wz(cfg, "cli", "app", "--detach")
    rig.wz(cfg, "park", "app")
    capsys.readouterr()
    assert rig.wz(cfg, "say", "app", "later") == 0
    assert "parked" in capsys.readouterr().out
    assert "later" in (cfg.role_dir("app") / "STATE.md").read_text().split("\n\n")[0]


def test_say_never_types_into_the_shell_a_finished_claude_leaves_behind(rig, cfg, capsys):
    rig.mode(cfg, "exit")
    rig.wz(cfg, "cli", "app", "--detach")
    time.sleep(1.0)
    trap = rig.tmp / "pwned"
    assert rig.wz(cfg, "say", "app", f"touch {trap}") == 0
    time.sleep(0.8)
    assert not trap.exists()
    assert "Claude ended" in capsys.readouterr().out
    assert f"touch {trap}" in (cfg.role_dir("app") / "STATE.md").read_text()


def test_say_to_a_session_at_a_login_screen_types_nothing_and_notes_it(rig, cfg, capsys):
    rig.mode(cfg, "login")
    sessions.ensure(cfg, "app")
    time.sleep(0.5)
    capsys.readouterr()
    assert rig.wz(cfg, "say", "app", "hello") == 0
    assert "login" in capsys.readouterr().out
    assert "hello" in (cfg.role_dir("app") / "STATE.md").read_text()


def test_a_role_may_message_the_lead_but_not_another_role(rig, cfg, monkeypatch, capsys):
    rig.wz(cfg, "cli", "writer", "--detach")
    monkeypatch.setenv("WZ_ROLE", "app")
    assert rig.wz(cfg, "say", "writer", "hi") == 1
    assert "not another role" in capsys.readouterr().err
    assert said(cfg) == []
    assert rig.wz(cfg, "say", "app", "me") == 1            # not itself
    monkeypatch.setenv("WZ_ROLE", "mission-ctl")
    assert rig.wz(cfg, "say", "writer", "from the lead") == 0
    assert said(cfg) == ["[from mission-ctl] from the lead"]


def test_say_unknown_role_and_empty_text(rig, cfg, capsys):
    assert rig.wz(cfg, "say", "ghost", "x") == 1
    assert "unknown role" in capsys.readouterr().err
    assert rig.wz(cfg, "say", "app", " \n ") == 1


# ---- the workspace list: every command works from any folder ---------------------------------------------------------
def init_registered(rig, name="ws", project="fernhill", **kw):
    """A workspace made the way a person makes one: `wz init --answers`, which registers it."""
    base = rig.tmp / name
    base.mkdir(parents=True, exist_ok=True)
    make_repo(base / "app")
    (base / "office" / "drafts").mkdir(parents=True)
    a = answers(base)
    a["project"], a["agent_command"] = project, "claude"
    f = base / "answers.json"
    f.write_text(json.dumps(a))
    assert cli.main(["init", "--answers", str(f), "--dir", str(base / "home dir"), "--no-git"]) == 0
    return config_load(base / "home dir" / "wz.toml")


def config_load(path):
    from wz import config
    return config.load(path)


def test_init_registers_the_workspace_as_the_default(rig, capsys):
    cfg = init_registered(rig)
    reg = registry.load()
    assert reg["default"] == "fernhill" and reg["workspaces"] == {"fernhill": str(cfg.path)}
    assert "registered workspace 'fernhill' (the default" in capsys.readouterr().out


def test_cli_from_another_folder_and_from_home_resumes_the_same_named_conversation(rig, monkeypatch, capsys):
    cfg = init_registered(rig)
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("setup mode started"))
    monkeypatch.setattr(setup_mode, "launch_setup", boom)
    elsewhere = rig.tmp / "somewhere" / "else"
    elsewhere.mkdir(parents=True)
    home = Path(os.environ["HOME"])
    home.mkdir(parents=True, exist_ok=True)
    name = sessions.tmux_name(cfg, "mission-ctl")
    seen = []
    for folder in (elsewhere, home, Path("/tmp"), cfg.root):
        monkeypatch.chdir(folder)
        assert cli.main(["cli", "mission-ctl", "--detach"]) == 0
        calls = rig.calls(cfg, n=len(seen) + 1)
        seen.append(calls[-1])
        sessions._kill(name)
        time.sleep(0.3)
    assert [arg(c, "--name" if i == 0 else "--resume") for i, c in enumerate(seen)] == ["wz-fernhill-mission-ctl"] * 4
    assert all(c["cwd"] == str(cfg.root) for c in seen)             # always from the role's own folder
    assert "workspace fernhill" in capsys.readouterr().err


def test_a_role_with_its_own_folder_resumes_from_that_folder_wherever_you_are(rig, monkeypatch):
    cfg = init_registered(rig)
    monkeypatch.chdir("/tmp")
    assert cli.main(["cli", "app", "--detach"]) == 0
    sessions._kill(sessions.tmux_name(cfg, "app"))
    time.sleep(0.3)
    monkeypatch.chdir(Path(os.environ["HOME"]).parent)
    assert cli.main(["cli", "app", "--detach"]) == 0
    first, second = rig.calls(cfg, n=2)
    assert first["cwd"] == second["cwd"] == str(cfg.store_root("app"))
    assert arg(second, "--resume") == arg(first, "--name") == "wz-fernhill-app"


def _pane_pids(rig, name):
    return [int(x) for x in rig.tmux("list-panes", "-t", "=" + name, "-F", "#{pane_pid}").stdout.split()]


def _link_into_hub(rig, name):
    """A second tmux session ("hub") that shows the role's own window as a tab, the way a hub of roles would."""
    assert rig.tmux("new-session", "-d", "-s", "hub", "sleep 600").returncode == 0
    r = rig.tmux("link-window", "-d", "-s", f"={name}:", "-t", "hub:")
    assert r.returncode == 0, r.stderr
    assert len(rig.tmux("list-windows", "-t", "=hub", "-F", "#{window_id}").stdout.split()) == 2


def test_park_stops_claude_even_when_the_role_window_is_linked_into_another_session(rig, cfg):
    name = sessions.tmux_name(cfg, "mission-ctl")
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    rig.calls(cfg, 1)
    pids = _pane_pids(rig, name)
    assert pids and all(_alive(p) for p in pids)
    _link_into_hub(rig, name)
    assert rig.wz(cfg, "park", "mission-ctl") == 0
    assert wait_gone(pids) == []                                    # the launch shell and the stand-in `claude`
    assert not rig.has(name)
    assert len(rig.tmux("list-windows", "-t", "=hub", "-F", "#{window_id}").stdout.split()) == 1   # the tab is gone, the hub is not
    assert rig.has("hub")


def test_plain_kill_session_would_have_left_claude_running_in_the_linked_window(rig, cfg):
    """The control for the test above: it only proves the fix if the old call really does leave the process behind."""
    name = sessions.tmux_name(cfg, "mission-ctl")
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    rig.calls(cfg, 1)
    pids = _pane_pids(rig, name)
    _link_into_hub(rig, name)
    rig.tmux("kill-session", "-t", "=" + name)
    assert not rig.has(name)
    assert [p for p in pids if _alive(p)], "this tmux stops a linked window with its session; the kill-window fix is not needed here"


def test_roll_and_restart_replace_a_linked_window_without_orphans(rig, cfg):
    name = sessions.tmux_name(cfg, "mission-ctl")
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    rig.calls(cfg, 1)
    old = _pane_pids(rig, name)
    _link_into_hub(rig, name)
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach", "--restart") == 0
    assert wait_gone(old) == []
    assert rig.has(name)
    assert len(rig.tmux("list-windows", "-t", "=hub", "-F", "#{window_id}").stdout.split()) == 1


def test_session_calls_are_counted_by_the_adapter(rig, cfg):
    name = sessions.tmux_name(cfg, "mission-ctl")
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    sessions.mux.reset_calls()
    assert sessions.running(name) is True
    assert sessions.mux.calls() == [("has-session", "-t", "=" + name)]
    sessions.mux.reset_calls()
    sessions.capture(name)
    assert sessions.mux.calls() == [("capture-pane", "-p", "-t", f"={name}:")]


def test_say_list_park_roll_and_start_all_work_from_any_folder(rig, monkeypatch, capsys):
    cfg = init_registered(rig)
    monkeypatch.chdir("/tmp")
    assert cli.main(["cli", "app", "--detach"]) == 0
    capsys.readouterr()
    assert cli.main(["say", "app", "from afar"]) == 0
    assert said(cfg) == ["from afar"]
    assert cli.main(["list"]) == 0 and "wz-fernhill-app" in capsys.readouterr().out
    assert cli.main(["park", "app"]) == 0
    assert cli.main(["start-all"]) == 0
    assert cli.main(["roll", "writer"]) == 0
    assert rig.has(sessions.tmux_name(cfg, "writer"))


def test_no_workspace_registered_means_setup_mode_for_the_lead_only(rig, monkeypatch, tmp_path, capsys):
    started = []
    monkeypatch.setattr(setup_mode, "launch_setup", lambda d, simple=False: started.append(Path(d)) or 0)
    elsewhere = tmp_path / "empty"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert cli.main(["cli", "mission-ctl"]) == 0 and started == [elsewhere.resolve()]
    with pytest.raises(SystemExit) as e:
        cli.main(["cli", "app"])
    assert "run `wz init` first" in str(e.value)


def test_a_workspace_found_from_the_current_folder_is_remembered_once(rig, monkeypatch):
    cfg = rig.workspace()                              # made by apply(), as a wz 0.1.1 workspace was: not registered
    assert registry.load()["workspaces"] == {}
    monkeypatch.chdir(cfg.root)
    assert cli.main(["cli", "app", "--detach"]) == 0
    assert registry.load() == {"default": "fernhill", "workspaces": {"fernhill": str(cfg.path)}}
    monkeypatch.chdir("/tmp")
    assert cli.main(["list"]) == 0


def test_several_workspaces_pick_with_ws_and_list_them(rig, monkeypatch, capsys):
    one = init_registered(rig, "one", "alpha")
    two = init_registered(rig, "two", "beta")
    assert registry.load()["default"] == "beta"        # the one you just made
    monkeypatch.chdir("/tmp")
    capsys.readouterr()
    assert cli.main(["cli", "app", "--detach"]) == 0
    assert (two.root / "claude-calls.jsonl").exists() and not (one.root / "claude-calls.jsonl").exists()
    assert "from the registered default; others: alpha (--ws NAME)" in capsys.readouterr().err
    assert cli.main(["--ws", "alpha", "cli", "app", "--detach"]) == 0
    assert (one.root / "claude-calls.jsonl").exists()
    assert cli.main(["say", "app", "x", "--ws", "alpha"]) == 0       # also after the command
    assert said(one) == ["x"] and said(two) == []
    capsys.readouterr()
    assert cli.main(["workspaces"]) == 0
    out = capsys.readouterr().out
    assert "alpha" in out and "beta *" in out
    assert cli.main(["workspaces", "use", "alpha"]) == 0 and registry.load()["default"] == "alpha"
    assert cli.main(["--ws", "ghost", "list"]) == 1
    assert "no workspace called 'ghost'" in capsys.readouterr().err
    assert cli.main(["workspaces", "forget", "beta"]) == 0 and list(registry.load()["workspaces"]) == ["alpha"]


def test_two_projects_with_one_name_get_two_registry_names(rig):
    a = init_registered(rig, "one", "same")
    b = init_registered(rig, "two", "same")
    assert registry.load()["workspaces"] == {"same": str(a.path), "same-2": str(b.path)}


def test_a_default_whose_folder_is_gone_is_not_used(rig, monkeypatch, capsys):
    cfg = init_registered(rig)
    shutil.rmtree(cfg.root)
    monkeypatch.chdir("/tmp")
    assert registry.default() is None
    assert cli.main(["--ws", "fernhill", "list"]) == 1
    assert "is gone" in capsys.readouterr().err
