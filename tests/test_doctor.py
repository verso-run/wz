"""`wz doctor`: what it says for a clean workspace and for each thing that can be wrong, and that it never writes anything.

Real tmux (private server per test, see test_sessions.py) and a stand-in `claude` whose `auth status` answers from a file,
so the tests never touch a real login.
"""
import os
import shlex
import shutil
import stat
import sys
import time
from pathlib import Path

import pytest
from test_sessions import TUI, cfg, rig  # noqa: F401  (fixtures)

from wz import charters, cli, config, doctor, light, registry, sessions

SECRET = "sk-ant-NOT-A-REAL-TOKEN"


def stand_in(rig, *, login="in", wait=0):
    """A `claude` for the PATH: `auth status` exits 0 (in) or 1 (out) after `wait` seconds and prints a made-up token to both
    streams; anything else starts the tmux-session stand-in. Each CLAUDE_CONFIG_DIR is signed in when it holds a file `in`."""
    p = rig.bindir / "claude"
    p.write_text(f"""#!/bin/sh
if [ "$1" = auth ]; then
  echo {SECRET}; echo {SECRET} >&2
  [ {wait} -gt 0 ] && sleep {wait}
  if [ -n "$CLAUDE_CONFIG_DIR" ]; then [ -f "$CLAUDE_CONFIG_DIR/in" ]; exit $?; fi
  [ "{login}" = in ]; exit $?
fi
exec {shlex.quote(sys.executable)} {shlex.quote(str(TUI))} "$@"
""")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


@pytest.fixture(autouse=True)
def _signed_in_claude(rig):
    """The rig's `claude` starts a session for any arguments, `auth status` included: every test gets one that answers it."""
    stand_in(rig)


def tmux_version(rig, text):
    """A `tmux` first on PATH that answers -V with `text` and passes everything else to the real one."""
    p = rig.bindir / "tmux"
    p.write_text(f"#!/bin/sh\n[ \"$1\" = -V ] && {{ echo {shlex.quote(text)}; exit 0; }}\nexec {shlex.quote(shutil.which('tmux'))} \"$@\"\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


def report(cfg, capsys, *argv):
    """(exit code, {topic: [(level, said, fix)]}, the whole text)."""
    code = cli.main(["--config", str(cfg.path), "doctor", *argv])
    text = capsys.readouterr().out
    return code, text


def set_mode(cfg, mode):
    text = cfg.path.read_text()
    assert 'permission_mode = "default"' in text
    cfg.path.write_text(text.replace('permission_mode = "default"', f'permission_mode = "{mode}"'))


def set_job_mode(cfg, mode):
    import re
    text = cfg.path.read_text()
    assert re.search(r'^job_permission_mode = "[^"]*"', text, re.M)
    cfg.path.write_text(re.sub(r'^job_permission_mode = "[^"]*"', f'job_permission_mode = "{mode}"', text, flags=re.M))


def findings(cfg):
    _, fs = doctor.diagnose(cfg.path)
    out = {}
    for f in fs:
        out.setdefault(f.topic, []).append(f)
    return out


def levels(cfg, topic):
    return [f.level for f in findings(cfg)[topic]]


def snapshot(*roots):
    out = {}
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                out[str(p)] = (p.stat().st_mtime_ns, p.read_bytes())
            else:
                out[str(p)] = None
    return out


# ---- a clean workspace ---------------------------------------------------------------------------------------------
def test_a_clean_workspace_passes_with_every_line_ok(rig, cfg, capsys):
    stand_in(rig)
    code, text = report(cfg, capsys)
    assert code == 0, text
    fs = findings(cfg)
    assert {t: [f.level for f in v] for t, v in fs.items()} == {t: [doctor.OK] for t in
        ("tmux", "claude", "login", "workspace", "workspace list", "hooks", "charters", "lights")} | {"permission mode": [doctor.OK, doctor.OK]}
    assert "everything is in order" in text and "PROBLEM" not in text


def test_it_writes_nothing_even_when_everything_is_wrong(rig, cfg, tmp_path, capsys):
    stand_in(rig, login="out")
    cfg.role_settings.write_text("{}")
    cfg.charter_path("app").write_text("by hand\n")
    (cfg.state / "sessions").mkdir(parents=True, exist_ok=True)
    (cfg.state / "sessions" / "app.light").write_text("work %99\n")
    registry.register(cfg.path, cfg.project)
    before = snapshot(cfg.root, tmp_path / "xdg-config")
    sessions_before = rig.tmux("list-sessions").stdout
    code, text = report(cfg, capsys)
    assert code == 1
    assert snapshot(cfg.root, tmp_path / "xdg-config") == before
    assert rig.tmux("list-sessions").stdout == sessions_before == ""          # no server was started either


def test_the_text_is_plain_words_with_a_fix_under_each_problem(rig, cfg, capsys):
    stand_in(rig, login="out")
    code, text = report(cfg, capsys)
    lines = text.splitlines()
    i = next(n for n, x in enumerate(lines) if "PROBLEM" in x and "login" in x)
    assert "not signed in" in lines[i] and lines[i + 1].strip().startswith("fix: run `claude`, then type /login")
    assert "1 problem, 0 notes" in text


# ---- tmux ----------------------------------------------------------------------------------------------------------
def test_no_tmux_is_a_problem_with_an_install_line(rig, cfg, monkeypatch):
    stand_in(rig)
    monkeypatch.setenv("PATH", str(rig.bindir))                                 # claude yes, tmux no
    (f,) = findings(cfg)["tmux"]
    assert f.level == doctor.PROBLEM and "not installed" in f.said and "brew install tmux" in f.fix and "apt install tmux" in f.fix


@pytest.mark.parametrize("version,level", [("tmux 2.9a", doctor.PROBLEM), ("tmux 3.0a", doctor.OK), ("tmux 3.5a", doctor.OK),
                                           ("tmux next-3.6", doctor.OK), ("tmux 10.1", doctor.OK), ("tmux master", doctor.NOTE)])
def test_tmux_must_be_3_0_or_newer(rig, cfg, version, level):
    tmux_version(rig, version)
    (f,) = findings(cfg)["tmux"]
    assert f.level == level, f.said
    if level == doctor.PROBLEM:
        assert "too old" in f.said and "upgrade" in f.fix


# ---- Claude Code and its login -------------------------------------------------------------------------------------
def test_no_claude_is_a_problem_and_the_login_is_not_asked(rig, cfg, monkeypatch):
    (rig.bindir / "claude").unlink()
    bare = [str(Path(sys.executable).parent)]                                   # no claude anywhere
    monkeypatch.setattr(sessions, "_path_dirs", lambda cfg, command0: bare)
    monkeypatch.setenv("PATH", os.pathsep.join(bare))
    fs = findings(cfg)
    assert [f.level for f in fs["claude"]] == [doctor.PROBLEM] and "install Claude Code" in fs["claude"][0].fix
    assert "login" not in fs


def test_signed_in_and_not_signed_in_come_from_the_exit_code(rig, cfg):
    stand_in(rig, login="in")
    assert levels(cfg, "login") == [doctor.OK]
    stand_in(rig, login="out")
    (f,) = findings(cfg)["login"]
    assert f.level == doctor.PROBLEM and "/login" in f.fix


def test_the_logins_output_is_never_shown_or_kept(rig, cfg, capsys, tmp_path):
    stand_in(rig, login="in")
    code, text = report(cfg, capsys)
    assert SECRET not in text and SECRET not in capsys.readouterr().err
    stand_in(rig, login="out")
    code, text = report(cfg, capsys)
    assert SECRET not in text
    assert not any(SECRET in p.read_text() for p in cfg.root.rglob("*") if p.is_file() and p.stat().st_size < 1e6)


def test_a_login_check_that_hangs_is_a_note_not_a_problem(rig, cfg, monkeypatch):
    stand_in(rig, wait=3)
    monkeypatch.setattr(doctor, "LOGIN_WAIT_S", 0.5)
    t = time.time()
    (f,) = findings(cfg)["login"]
    assert f.level == doctor.NOTE and "could not tell" in f.said and time.time() - t < 2.5


def test_a_command_that_is_not_claude_is_not_asked_who_it_is(rig, tmp_path):
    other = rig.bindir / "my-agent"
    other.write_text("#!/bin/sh\nexit 3\n")
    other.chmod(other.stat().st_mode | stat.S_IXUSR)
    cfg = rig.workspace(name="ws2", project="other", agent_command="my-agent")
    fs = findings(cfg)
    assert fs["claude"][0].level == doctor.OK and fs["login"][0].level == doctor.NOTE and "not checked" in fs["login"][0].said


def test_each_account_a_helper_uses_is_checked_in_its_own_config_folder(rig, cfg, tmp_path):
    stand_in(rig)
    good, bad = tmp_path / "acct-good", tmp_path / "acct-bad"
    for d in (good, bad):
        d.mkdir()
    (good / "in").write_text("")
    text = cfg.path.read_text().replace('model = "sonnet"\naccount = "main"', 'model = "sonnet"\naccount = "work"')
    assert text != cfg.path.read_text()
    cfg.path.write_text(text + f'\n[accounts.work]\nconfig_dir = "{good}"\n')
    # the other helpers have an account with no folder of its own: they use your login, which the stand-in says is signed in
    assert [(f.level, f.said) for f in findings(cfg)["login"]] == [(doctor.OK, "Claude Code is signed in (your login)"),
                                                                  (doctor.OK, "Claude Code is signed in (account 'work')")]
    cfg.path.write_text(text + f'\n[accounts.work]\nconfig_dir = "{bad}"\n')
    own, work = findings(cfg)["login"]
    assert own.level == doctor.OK and work.level == doctor.PROBLEM and f"CLAUDE_CONFIG_DIR={bad} claude" in work.fix


# ---- the workspace and the list of workspaces ----------------------------------------------------------------------
def test_no_workspace_is_one_problem_and_the_machine_checks_still_run(rig, tmp_path, monkeypatch, capsys):
    stand_in(rig)
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    code = cli.main(["doctor"])
    text = capsys.readouterr().out
    assert code == 1
    assert "no workspace here" in text and "wz init" in text
    assert "tmux" in text and "claude" in text
    _, fs = doctor.diagnose()
    assert {f.topic for f in fs} >= {"tmux", "claude", "login", "workspace", "workspace list"}
    assert not {"hooks", "charters", "lights", "permission mode"} & {f.topic for f in fs}


def test_a_wz_toml_that_does_not_load_is_named_not_a_traceback(rig, cfg, capsys):
    set_mode(cfg, "sudo")
    code, text = report(cfg, capsys)
    assert code == 1 and "wz.toml cannot be used" in text and "sudo" in text and "Traceback" not in text


def test_a_workspace_folder_wz_cannot_write_to_is_a_problem(rig, cfg, monkeypatch):
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, mode, **k: False if Path(p) in (cfg.state, cfg.root) else real(p, mode, **k))
    fs = [f for f in findings(cfg)["workspace"] if f.level == doctor.PROBLEM]
    assert fs and "cannot write" in fs[0].said and "chmod" in fs[0].fix


def test_the_workspace_list_reports_what_is_wrong_with_it(rig, cfg, tmp_path):
    (f,) = findings(cfg)["workspace list"]
    assert f.level == doctor.OK and "none yet" in f.said
    p = registry.path()
    p.parent.mkdir(parents=True)
    p.write_text("{ not json")
    (f,) = findings(cfg)["workspace list"]
    assert f.level == doctor.PROBLEM and str(p) in f.said and "mv" in f.fix
    gone = tmp_path / "gone" / "wz.toml"
    p.write_text('{"default": "old", "workspaces": {"old": "%s", "fernhill": "%s"}}' % (gone, cfg.path))
    fs = findings(cfg)["workspace list"]
    assert [f.level for f in fs] == [doctor.NOTE, doctor.NOTE]
    assert fs[0].fix == "`wz workspaces forget old`" and fs[1].fix == "`wz workspaces use fernhill`"
    p.write_text('{"default": "fernhill", "workspaces": {"fernhill": "%s"}}' % cfg.path)
    assert levels(cfg, "workspace list") == [doctor.OK]


# ---- permission mode -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode,level", [("default", doctor.OK), ("plan", doctor.OK), ("acceptEdits", doctor.NOTE),
                                        ("auto", doctor.NOTE), ("bypassPermissions", doctor.NOTE)])
def test_the_permission_mode_in_use_is_named(rig, cfg, mode, level):
    set_mode(cfg, mode)
    f = findings(cfg)["permission mode"][0]
    assert f.level == level and f"windows: '{mode}'" in f.said
    if level == doctor.NOTE:
        assert 'permission_mode = "default"' in f.fix
    if mode == "bypassPermissions":
        assert "does NOT ask" in f.said


def test_the_job_mode_is_named_apart_from_the_window_mode(rig, cfg):
    win, job = findings(cfg)["permission mode"]
    assert win.said.startswith("windows: 'default'") and job.said.startswith("background jobs: 'auto'")   # a default workspace
    assert win.level == doctor.OK and job.level == doctor.OK


def test_a_job_mode_that_does_not_stop_at_anything_is_a_note(rig, cfg):
    set_job_mode(cfg, "bypassPermissions")
    win, job = findings(cfg)["permission mode"]
    assert win.level == doctor.OK and job.level == doctor.NOTE
    assert "background jobs: 'bypassPermissions'" in job.said and "does NOT ask" in job.said
    set_job_mode(cfg, "default")
    job = findings(cfg)["permission mode"][1]
    assert job.level == doctor.OK and "background jobs: 'default'" in job.said and "stops at anything" in job.said


# ---- hooks and charters --------------------------------------------------------------------------------------------
def test_hooks_missing_unreadable_or_older_than_this_wz_are_a_problem(rig, cfg):
    assert levels(cfg, "hooks") == [doctor.OK]
    old = charters.hook_settings()
    del old["hooks"]["PermissionRequest"]                                        # what a wz before the lights wrote
    cfg.role_settings.write_text(__import__("json").dumps(old))
    (f,) = findings(cfg)["hooks"]
    assert f.level == doctor.PROBLEM and "wz charters" in f.fix and "--restart" in f.fix
    cfg.role_settings.write_text("{ torn")
    assert levels(cfg, "hooks") == [doctor.PROBLEM]
    cfg.role_settings.unlink()
    (f,) = findings(cfg)["hooks"]
    assert f.level == doctor.PROBLEM and "does not exist" in f.said and f.fix == "run `wz charters`"


def test_a_charter_that_differs_or_is_missing_is_named_by_role(rig, cfg):
    assert levels(cfg, "charters") == [doctor.OK]
    cfg.charter_path("app").write_text(cfg.charter_path("app").read_text() + "\nmy own rule\n")
    cfg.charter_path("tester").unlink()
    fs = findings(cfg)["charters"]
    assert [f.level for f in fs] == [doctor.PROBLEM, doctor.PROBLEM]
    assert "tester" in fs[0].said and "no CHARTER.md" in fs[0].said
    assert "app" in fs[1].said and "hand edit is lost" in fs[1].fix
    assert "my own rule" in cfg.charter_path("app").read_text()                  # doctor did not rewrite it


def test_a_charter_made_by_wz_charters_passes_again(rig, cfg):
    cfg.charter_path("app").write_text("by hand\n")
    assert levels(cfg, "charters") == [doctor.PROBLEM]
    charters.write_all(cfg)
    assert levels(cfg, "charters") == [doctor.OK]


# ---- lights --------------------------------------------------------------------------------------------------------
def test_a_colour_recorded_for_a_helper_that_is_not_running_is_stale(rig, cfg):
    f = light.light_file(str(cfg.root), "app")
    Path(f).parent.mkdir(parents=True, exist_ok=True)
    Path(f).write_text("work %5\n")
    (x,) = findings(cfg)["lights"]
    assert x.level == doctor.PROBLEM and "app" in x.said and "not running" in x.said and f in x.fix


def test_a_colour_on_the_live_window_is_not_stale_but_one_on_another_pane_is(rig, cfg):
    stand_in(rig)
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    name = sessions.tmux_name(cfg, "mission-ctl")
    pane = rig.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_id}").stdout.strip()
    f = Path(light.light_file(str(cfg.root), "mission-ctl"))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"done {pane}\n")
    assert levels(cfg, "lights") == [doctor.OK]
    f.write_text("done %987\n")
    (x,) = findings(cfg)["lights"]
    assert x.level == doctor.PROBLEM and "different one" in x.said
    f.unlink()
    assert levels(cfg, "lights") == [doctor.OK]


# ---- the command ---------------------------------------------------------------------------------------------------
def test_the_exit_code_is_1_only_for_a_problem(rig, cfg, capsys):
    stand_in(rig)
    set_mode(cfg, "auto")
    code, text = report(cfg, capsys)
    assert code == 1 and "wz.toml changed since" in text                         # the charters still carry the old mode sentence
    charters.write_all(config.load(cfg.path))
    code, text = report(cfg, capsys)
    assert code == 0 and "0 problems, 1 note" in text                            # a note alone does not fail
    cfg.role_settings.unlink()
    assert report(cfg, capsys)[0] == 1


def test_doctor_is_listed_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "doctor" in capsys.readouterr().out


def test_nothing_in_doctor_writes_a_file():
    src = Path(doctor.__file__).read_text()
    for banned in ("write_text", "write_json", "open(", ".mkdir(", "unlink(", "os.remove", "rename(", "charters.ensure", "charters.write_all", "sessions.plan("):
        assert banned not in src, banned
