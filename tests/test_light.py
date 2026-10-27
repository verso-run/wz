"""Lights: `wz light` and the hook settings that run it, against a REAL tmux (private server per test) with the stand-in `claude`."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_sessions import _alive, cfg, rig, wait_gone  # noqa: F401  (fixtures)

from wz import charters, light, mux, sessions

LIGHT = Path(light.__file__)
WORK, ASK, DONE = (light.STYLES[k] for k in ("work", "ask", "done"))


def hook_commands(cfg):
    """{(event, matcher): command} for every light hook in the generated settings."""
    out = {}
    for event, entries in json.loads(cfg.role_settings.read_text())["hooks"].items():
        for e in entries:
            for h in e["hooks"]:
                if LIGHT.name in h["command"]:
                    out[(event, e["matcher"])] = h
    return out


def start(rig, cfg, role="mission-ctl"):
    assert rig.wz(cfg, "cli", role, "--detach") == 0
    name = sessions.tmux_name(cfg, role)
    pane = rig.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_id}").stdout.strip()
    assert pane.startswith("%")
    return name, pane


def run_hook(h, cfg, role, pane, *, data="{}", extra=None):
    env = {**os.environ, "WZ_ROLE": role, "WZ_HOME": str(cfg.root), "WZ_CONFIG": str(cfg.path), "TMUX_PANE": pane, **(extra or {})}
    return subprocess.run(h["command"], shell=True, input=data, capture_output=True, text=True, env=env)


def style(rig, pane):
    return rig.tmux("show-options", "-w", "-v", "-t", pane, "window-status-style").stdout.strip()


def test_settings_carry_the_events_and_matchers_of_the_plan(cfg):
    hooks = hook_commands(cfg)
    assert set(hooks) == {("SessionStart", "*"), ("UserPromptSubmit", "*"), ("PreToolUse", "AskUserQuestion|ExitPlanMode"),
                          ("Notification", "permission_prompt|elicitation_dialog"), ("PermissionRequest", "*"),
                          ("PostToolUse", "*"), ("Stop", "*"), ("SessionEnd", "*")}
    state_of = {k: h["command"].rsplit(" ", 1)[1] for k, h in hooks.items()}
    assert state_of == {("SessionStart", "*"): "done", ("UserPromptSubmit", "*"): "work", ("PreToolUse", "AskUserQuestion|ExitPlanMode"): "ask",
                        ("Notification", "permission_prompt|elicitation_dialog"): "ask", ("PermissionRequest", "*"): "ask",
                        ("PostToolUse", "*"): "work",
                        ("Stop", "*"): "done", ("SessionEnd", "*"): "off"}
    assert [k for k, h in hooks.items() if h.get("async")] == [("PostToolUse", "*")]          # only the per-tool one runs in the background
    assert all(f"-I -S {LIGHT}" in h["command"] for h in hooks.values())                   # the small entry, not `wz hook`
    pre = json.loads(cfg.role_settings.read_text())["hooks"]["PreToolUse"]
    assert "hook guard" in pre[0]["hooks"][0]["command"]                                   # the guard is still first and unchanged
    post = json.loads(cfg.role_settings.read_text())["hooks"]["PostToolUse"]
    assert "hook flag" in post[0]["hooks"][0]["command"] and post[0]["matcher"] == "Edit|Write|MultiEdit"


def test_the_events_paint_the_roles_window(rig, cfg):
    name, pane = start(rig, cfg)
    hooks = hook_commands(cfg)
    assert style(rig, pane) == ""
    t0 = time.monotonic()
    r = run_hook(hooks[("UserPromptSubmit", "*")], cfg, "mission-ctl", pane)
    assert r.returncode == 0 and style(rig, pane) == WORK and time.monotonic() - t0 < 1.0     # amber within 1 s of a prompt
    assert run_hook(hooks[("PreToolUse", "AskUserQuestion|ExitPlanMode")], cfg, "mission-ctl", pane).returncode == 0
    assert style(rig, pane) == ASK
    run_hook(hooks[("PostToolUse", "*")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == WORK
    run_hook(hooks[("Notification", "permission_prompt|elicitation_dialog")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == ASK
    run_hook(hooks[("PostToolUse", "*")], cfg, "mission-ctl", pane)
    run_hook(hooks[("PermissionRequest", "*")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == ASK
    run_hook(hooks[("Stop", "*")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == DONE
    assert (cfg.state / "sessions" / "mission-ctl.light").read_text() == f"done {pane}\n"
    run_hook(hooks[("SessionEnd", "*")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == "" and not (cfg.state / "sessions" / "mission-ctl.light").exists()      # off: the tmux theme is back


def test_the_light_is_on_the_window_so_a_second_session_showing_it_sees_it_too(rig, cfg):
    name, pane = start(rig, cfg)
    assert rig.tmux("new-session", "-d", "-s", "hub", "sleep 600").returncode == 0
    assert rig.tmux("link-window", "-d", "-s", f"={name}:0", "-t", "hub:").returncode == 0
    run_hook(hook_commands(cfg)[("Stop", "*")], cfg, "mission-ctl", pane)
    linked = rig.tmux("list-windows", "-t", "hub", "-F", "#{window_id} #{window-status-style}" if False else "#{window_id}").stdout.split()
    win = rig.tmux("display-message", "-p", "-t", pane, "#{window_id}").stdout.strip()
    assert win in linked
    assert rig.tmux("show-options", "-w", "-v", "-t", f"hub:{win}", "window-status-style").stdout.strip() == DONE


def test_the_same_state_twice_is_zero_tmux_calls(rig, cfg, monkeypatch):
    name, pane = start(rig, cfg)
    env = {"WZ_ROLE": "mission-ctl", "WZ_HOME": str(cfg.root), "TMUX_PANE": pane}
    mux.reset_calls()
    assert light.set_light("work", env) == 0
    assert [c[0] for c in mux.calls()] == ["set-option"]
    mux.reset_calls()
    assert light.set_light("work", env) == 0 and mux.calls() == []
    assert light.set_light("ask", env) == 0 and [c[0] for c in mux.calls()] == ["set-option"]
    mux.reset_calls()
    assert light.set_light("ask", env) == 0 and mux.calls() == []


def test_a_repeat_costs_a_few_milliseconds_not_the_whole_package(rig, cfg):
    name, pane = start(rig, cfg)
    h = hook_commands(cfg)[("PostToolUse", "*")]
    run_hook(h, cfg, "mission-ctl", pane)
    argv = [sys.executable, "-I", "-S", str(LIGHT), "work"]
    env = {**os.environ, "WZ_ROLE": "mission-ctl", "WZ_HOME": str(cfg.root), "TMUX_PANE": pane}
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, check=True)
        times.append((time.perf_counter() - t0) * 1000)
    assert style(rig, pane) == WORK
    assert min(times) <= 15, times                  # the plan's budget; the full `wz hook guard` is ~50 ms


def test_a_light_left_over_from_another_pane_does_not_stop_the_new_window_being_painted(rig, cfg):
    name, pane = start(rig, cfg)
    f = cfg.state / "sessions" / "mission-ctl.light"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("done %777\n")                               # a crashed wz, or a restarted tmux server, left this behind
    run_hook(hook_commands(cfg)[("Stop", "*")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == DONE and f.read_text() == f"done {pane}\n"


@pytest.mark.parametrize("env", [{"WZ_ROLE": ""}, {"WZ_JOB": "J-1"}, {"TMUX_PANE": ""}, {"WZ_HOME": "", "WZ_CONFIG": ""}])
def test_no_role_a_job_or_no_pane_means_no_file_and_no_tmux(rig, cfg, env):
    name, pane = start(rig, cfg)
    mux.reset_calls()
    base = {"WZ_ROLE": "mission-ctl", "WZ_HOME": str(cfg.root), "TMUX_PANE": pane}
    assert light.set_light("work", {**base, **env}) == 0
    assert mux.calls() == [] and not (cfg.state / "sessions" / "mission-ctl.light").exists() and style(rig, pane) == ""


def test_a_job_with_the_chat_settings_file_leaves_the_chat_window_alone(rig, cfg):
    name, pane = start(rig, cfg)
    r = run_hook(hook_commands(cfg)[("UserPromptSubmit", "*")], cfg, "mission-ctl", pane, extra={"WZ_JOB": "J-1"})
    assert r.returncode == 0 and style(rig, pane) == "" and not (cfg.state / "sessions" / "mission-ctl.light").exists()


def test_an_unknown_state_or_a_dead_pane_is_exit_0_and_records_nothing(rig, cfg):
    env = {"WZ_ROLE": "mission-ctl", "WZ_HOME": str(cfg.root), "TMUX_PANE": "%9999"}
    assert light.set_light("purple", env) == 0
    assert light.set_light("work", env) == 0
    assert not (cfg.state / "sessions" / "mission-ctl.light").exists()


def test_killing_claude_clears_the_light(rig, cfg):
    name, pane = start(rig, cfg)
    run_hook(hook_commands(cfg)[("UserPromptSubmit", "*")], cfg, "mission-ctl", pane)
    assert style(rig, pane) == WORK
    shell_pid = int(rig.tmux("display-message", "-p", "-t", pane, "#{pane_pid}").stdout)
    kids = [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()
            and Path(f"/proc/{p.name}/stat").read_text().rsplit(")", 1)[1].split()[1] == str(shell_pid)]
    assert kids, "the stand-in claude should be a child of the launch script"
    for k in kids:
        os.kill(k, 9)                                       # kill -9, not a clean exit: no SessionEnd hook runs
    end = time.time() + 8
    while time.time() < end and (style(rig, pane) or (cfg.state / "sessions" / "mission-ctl.light").exists()):
        time.sleep(0.1)
    assert style(rig, pane) == "" and not (cfg.state / "sessions" / "mission-ctl.light").exists()
    assert "Claude ended" in rig.tmux("capture-pane", "-p", "-t", pane).stdout


def test_park_removes_the_file_and_roll_and_restart_forget_it(rig, cfg):
    name, pane = start(rig, cfg)
    f = cfg.state / "sessions" / "mission-ctl.light"
    h = hook_commands(cfg)[("Stop", "*")]
    run_hook(h, cfg, "mission-ctl", pane)
    assert f.exists()
    assert rig.wz(cfg, "park", "mission-ctl") == 0
    assert not f.exists() and not rig.has(name)
    name, pane = start(rig, cfg)
    run_hook(h, cfg, "mission-ctl", pane)
    assert rig.wz(cfg, "cli", "mission-ctl", "--restart", "--detach") == 0
    assert not f.exists()


def test_list_has_a_light_column(rig, cfg, capsys):
    name, pane = start(rig, cfg)
    run_hook(hook_commands(cfg)[("PreToolUse", "AskUserQuestion|ExitPlanMode")], cfg, "mission-ctl", pane)
    capsys.readouterr()
    assert rig.wz(cfg, "list") == 0
    rows = [l.split() for l in capsys.readouterr().out.splitlines()]
    assert rows[0][-1] == "light"
    assert [r[-1] for r in rows[1:] if r[0] == "mission-ctl"] == ["ask"]
    assert {r[-1] for r in rows[1:] if r[0] != "mission-ctl"} == {"-"}


def test_wz_light_subcommand_is_a_no_op_outside_a_role(cfg, monkeypatch):
    from wz import cli
    mux.reset_calls()
    assert cli.main(["--config", str(cfg.path), "light", "work"]) == 0 and mux.calls() == []


def test_an_older_workspace_gets_the_lights_on_its_next_start(cfg):
    full = charters.hook_settings()
    old = {"hooks": {"PreToolUse": full["hooks"]["PreToolUse"][:1], "PostToolUse": full["hooks"]["PostToolUse"][:1]}}
    cfg.role_settings.write_text(json.dumps(old))                  # what wz 0.1.2 wrote
    sessions.plan(cfg, "mission-ctl")                              # what `wz cli` and a job start run first
    assert json.loads(cfg.role_settings.read_text()) == full
    assert ("Stop", "*") in hook_commands(cfg)
