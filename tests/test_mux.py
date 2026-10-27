"""wz/mux.py, the one module that runs tmux: call counting, window-level kill, and the project-folder encoder.

These tests need no tmux: a `tmux` shim first on PATH logs its arguments and answers the few queries the adapter makes.
The kill against a real tmux server (a window linked into a second session) is in test_sessions.py.
"""
import os
import shlex
import stat
from pathlib import Path

import pytest

from wz import mux, sessions


@pytest.fixture
def shim(tmp_path, monkeypatch):
    """A fake tmux. `window` is what display-message answers (empty: exit 1, no such session); `has` is has-session's exit code."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "shim.log"
    cfgf = tmp_path / "shim.cfg"

    def configure(window="@7", has=1):
        cfgf.write_text(f"{window}\n{has}\n")

    configure()
    script = bindir / "tmux"
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
        f"win=$(sed -n 1p {shlex.quote(str(cfgf))}); has=$(sed -n 2p {shlex.quote(str(cfgf))})\n"
        "case \"$1\" in\n"
        "  display-message) [ -n \"$win\" ] && echo \"$win\" && exit 0; exit 1;;\n"
        "  has-session) exit \"$has\";;\n"
        "esac\n"
        "exit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    mux.reset_calls()
    seen = lambda: log.read_text().splitlines() if log.exists() else []
    return configure, seen


def test_every_call_is_counted_in_order_and_reset_clears_it(shim):
    _, seen = shim
    mux.run("has-session", "-t", "=a")
    mux.set_option("a", "@wz_root", "/x")
    mux.send_keys("a", "-x", literal=True)
    assert mux.calls() == [("has-session", "-t", "=a"), ("set-option", "-t", "=a:", "@wz_root", "/x"), ("send-keys", "-t", "=a:", "-l", "-x")]
    assert len(seen()) == 3                                         # what is counted is what ran
    snap = mux.calls()
    mux.reset_calls()
    assert mux.calls() == [] and snap                                # calls() hands out a copy


def test_sessions_goes_through_the_adapter(shim):
    assert sessions.running("wz-p-role") is False                   # the shim's has-session answers 1
    assert mux.calls() == [("has-session", "-t", "=wz-p-role")]
    mux.reset_calls()
    sessions._kill("wz-p-role")                                     # not running: nothing else is asked
    assert mux.calls() == [("has-session", "-t", "=wz-p-role")]


def test_nothing_outside_the_adapter_starts_tmux():
    src = Path(mux.__file__).parent
    offenders = [f"{f.name}:{n}" for f in sorted(src.glob("*.py")) if f.name != "mux.py"
                 for n, line in enumerate(f.read_text().splitlines(), 1) if '["tmux",' in line or 'which("tmux")' in line]
    assert offenders == []


def test_kill_removes_the_window_by_id_wherever_it_is_linked(shim):
    configure, seen = shim
    configure(window="@7", has=1)                                   # the window's gone, and so is the session with it
    mux.kill_role("wz-p-role")
    assert seen() == ["display-message -p -t =wz-p-role: #{window_id}", "kill-window -t @7", "has-session -t =wz-p-role"]


def test_kill_also_closes_a_session_that_has_other_windows_left(shim):
    configure, seen = shim
    configure(window="@7", has=0)
    mux.kill_role("wz-p-role")
    assert seen()[-1] == "kill-session -t =wz-p-role"


def test_kill_of_a_role_that_is_not_there_is_one_query_and_nothing_more(shim):
    configure, seen = shim
    configure(window="")
    mux.kill_role("wz-p-role")
    assert seen() == ["display-message -p -t =wz-p-role: #{window_id}"]


# ---- the folder name Claude keeps a conversation under ---------------------------------------------------------------
@pytest.mark.parametrize("path, folder", [
    ("/work/ann/my_app", "-work-ann-my-app"),
    ("/work/ann/v1.2/app", "-work-ann-v1-2-app"),
    ("/work/ann/my work/a_b.c", "-work-ann-my-work-a-b-c"),
    ("/work/zoë/app", "-work-zo--app"),
    ("/tmp/plain", "-tmp-plain"),
])
def test_project_folder_turns_every_non_alphanumeric_into_a_dash(path, folder):
    assert sessions.project_folder(Path(path)) == folder


def test_a_saved_conversation_is_found_for_a_path_with_underscore_dot_and_space(tmp_path):
    cwd = tmp_path / "my_proj v1.2" / "ap_p"
    cwd.mkdir(parents=True)
    conf = tmp_path / "conf"
    folder = conf / "projects" / sessions.project_folder(cwd)
    folder.mkdir(parents=True)
    (folder / "s.jsonl").write_text('{"customTitle":"wz-p-role"}\n')
    assert sessions._on_disk(str(conf), cwd, "wz-p-role") is True
    assert sessions._on_disk(str(conf), cwd, "wz-p-other") is False
    assert sessions._on_disk(str(conf), cwd.parent, "wz-p-role") is False   # another folder's conversations are not this one's
