"""`wz hub` against a REAL tmux (private server per test) with the stand-in `claude`: tabs, reattach, second terminal, kill, park.

A "terminal" is a tmux client on a pty (Client below). The wall-clock numbers of the plan (build, reattach) are call counts here
and loose time limits: absolute milliseconds differ too much between a laptop and a CI machine; the measured times are in the
pull request.
"""
import fcntl
import os
import pty
import select
import shlex
import signal
import struct
import sys
import termios
import time
from pathlib import Path

import pytest
from test_sessions import _alive, _pane_pids, cfg, rig, wait_gone  # noqa: F401  (fixtures)

from wz import hub, light, mux, sessions

ROOT = Path(__file__).resolve().parent.parent
EXTRA = {"qa": {"pack": "tester", "store": "app", "owns": {"app": ["qa/**"]}},
         "ops": {"pack": "admin", "store": "office", "owns": {"office": ["ops/**"]}}}       # with the 5 of the rig: 7 roles


class Client:
    """A tmux client attached on a pty, as a terminal window would be. `close()` is the terminal being closed."""

    def __init__(self, rig, session):
        env = {k: v for k, v in os.environ.items() if k != "TMUX"} | {"TERM": "xterm-256color"}
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("tmux", ["tmux", "attach-session", "-t", "=" + session], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 160, 0, 0))
        self.out = b""
        self.rig = rig
        end = time.time() + 5
        while time.time() < end and self.session() != session:
            time.sleep(0.05)
        assert self.session() == session, "the client never attached"

    def session(self):
        """The session this client is on ('' while it is not attached)."""
        for line in self.rig.tmux("list-clients", "-F", "#{client_pid} #{client_session}").stdout.splitlines():
            pid, _, sess = line.partition(" ")
            if pid == str(self.pid):
                return sess
        return ""

    def drain(self, seconds=0.6):
        end = time.time() + seconds
        while time.time() < end:
            if select.select([self.fd], [], [], 0.1)[0]:
                try:
                    self.out += os.read(self.fd, 65536)
                except OSError:
                    break
        return self.out

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


@pytest.fixture
def clients():
    made = []
    yield made
    for c in made:
        c.close()


def start_roles(rig, cfg, roles):
    for r in roles:
        assert rig.wz(cfg, "cli", r, "--detach") == 0


def tabs(rig, hub_session):
    """[(index, window name)] of the hub's tabs, placeholder excluded."""
    out = rig.tmux("list-windows", "-t", "=" + hub_session, "-F", "#{window_index} #{window_name} #{@wz_hub}").stdout.splitlines()
    return [(int(a), b) for a, b, *c in (x.split(" ") for x in out) if not (c and c[0] == "1")]


def placeholders(rig, hub_session):
    return rig.tmux("list-windows", "-t", "=" + hub_session, "-F", "#{@wz_hub}").stdout.split().count("1")


@pytest.fixture
def cfg7(rig):
    return rig.workspace(extra_roles=EXTRA)


ALL7 = ["mission-ctl", "app", "tester", "writer", "bench", "qa", "ops"]


def test_the_hub_builds_with_a_tab_per_live_role_lead_first_in_wz_toml_order(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ["bench", "app", "mission-ctl", "ops", "tester", "writer"])         # started in a different order
    mux.reset_calls()
    t0 = time.monotonic()
    name, how = hub.prepare(cfg)
    took = time.monotonic() - t0
    assert (name, how) == (hub.hub_name(cfg), "build")
    assert tabs(rig, name) == [(1, "mission-ctl"), (2, "app"), (3, "tester"), (4, "writer"), (5, "bench"), (6, "ops")]
    assert placeholders(rig, name) == 0                                    # it only holds the hub open while there are no tabs
    assert len(mux.calls()) <= 6 + 7, mux.calls()             # one link each; two listings, create, style, kill placeholder, select
    assert took < 3
    assert (cfg.state / "hub.log").read_text().count("build") == 1
    assert rig.wz(cfg, "list") == 0                                         # the roles are untouched


def test_a_role_that_is_not_running_or_is_parked_has_no_tab(rig, cfg7, capsys):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester"])
    assert rig.wz(cfg, "park", "tester") == 0
    name, _ = hub.prepare(cfg)
    assert [t[1] for t in tabs(rig, name)] == ["mission-ctl", "app"]


def test_reattach_changes_nothing_and_costs_two_tmux_calls(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ALL7[:6])
    name, _ = hub.prepare(cfg)
    before = rig.tmux("list-windows", "-t", "=" + name, "-F", "#{window_index} #{window_id}").stdout
    mux.reset_calls()
    t0 = time.monotonic()
    again, how = hub.prepare(cfg)
    took = time.monotonic() - t0
    assert (again, how) == (name, "reattach")
    assert [c[0] for c in mux.calls()] == ["list-sessions", "list-windows"]      # nothing to link, unlink or select
    assert rig.tmux("list-windows", "-t", "=" + name, "-F", "#{window_index} #{window_id}").stdout == before
    assert took < 1
    assert "reattach" in (cfg.state / "hub.log").read_text()


def test_the_tab_cap_leaves_the_rest_out_and_says_so(rig, cfg7, monkeypatch, capsys):
    cfg = cfg7
    monkeypatch.setattr(hub, "MAX_TABS", 4)                                  # the cap is the constant; 4 roles are enough to prove it
    start_roles(rig, cfg, ALL7[:6])
    name, _ = hub.prepare(cfg)
    assert [t[1] for t in tabs(rig, name)] == ["mission-ctl", "app", "tester", "writer"]
    assert "not shown: bench" in capsys.readouterr().out                    # qa is not running; only bench is over the cap
    assert ROOT.joinpath("wz", "hub.py").read_text().count("MAX_TABS = 9") == 1


def test_hide_and_show_change_the_tabs_and_the_roles_keep_running(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester"])
    name, _ = hub.prepare(cfg)
    pids = _pane_pids(rig, sessions.tmux_name(cfg, "app"))
    assert rig.wz(cfg, "hub", "hide", "app") == 0
    assert tabs(rig, name) == [(1, "mission-ctl"), (2, "tester")]            # renumbered: no gap
    assert all(_alive(p) for p in pids) and rig.has(sessions.tmux_name(cfg, "app"))
    assert hub.hidden(cfg) == ["app"]
    assert rig.wz(cfg, "hub", "show", "app") == 0
    assert tabs(rig, name) == [(1, "mission-ctl"), (2, "app"), (3, "tester")]
    assert hub.hidden(cfg) == []
    with pytest.raises(SystemExit):
        rig.wz(cfg, "hub", "hide")
    with pytest.raises(SystemExit):
        rig.wz(cfg, "hub", "hide", "nobody")


def test_hiding_with_no_hub_running_is_remembered_for_the_next_one(rig, cfg7, capsys):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app"])
    assert rig.wz(cfg, "hub", "hide", "app") == 0
    name, how = hub.prepare(cfg)
    assert how == "build" and tabs(rig, name) == [(1, "mission-ctl")]


def test_hide_everything_leaves_the_placeholder_not_a_dead_hub(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app"])
    name, _ = hub.prepare(cfg)
    rig.wz(cfg, "hub", "hide", "mission-ctl")
    rig.wz(cfg, "hub", "hide", "app")
    assert rig.has(name) and tabs(rig, name) == [] and placeholders(rig, name) == 1
    rig.wz(cfg, "hub", "show", "app")
    assert tabs(rig, name) == [(1, "app")] and placeholders(rig, name) == 0


def test_a_hub_with_no_live_role_opens_on_the_placeholder_and_gets_tabs_when_roles_start(rig, cfg7):
    cfg = cfg7
    name, how = hub.prepare(cfg)
    assert how == "build" and tabs(rig, name) == [] and placeholders(rig, name) == 1
    assert "wz cli <role>" in rig.tmux("capture-pane", "-p", "-t", f"={name}:0").stdout
    start_roles(rig, cfg, ["app"])                                          # ensure() links the new window into the live hub
    assert tabs(rig, name) == [(1, "app")] and placeholders(rig, name) == 0


def test_hub_kill_closes_the_hub_and_every_role_keeps_running(rig, cfg7, capsys):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester"])
    pids = [p for r in ("mission-ctl", "app", "tester") for p in _pane_pids(rig, sessions.tmux_name(cfg, r))]
    name, _ = hub.prepare(cfg)
    assert rig.wz(cfg, "hub", "kill") == 0
    assert not rig.has(name)
    assert all(_alive(p) for p in pids)
    assert all(rig.has(sessions.tmux_name(cfg, r)) for r in ("mission-ctl", "app", "tester"))
    out = capsys.readouterr().out
    assert "the roles keep running" in out and "app" in out
    assert rig.wz(cfg, "hub", "kill") == 0 and "no hub is running" in capsys.readouterr().out
    again, how = hub.prepare(cfg)                                           # and a new hub shows the same roles
    assert how == "build" and len(tabs(rig, again)) == 3


def test_park_removes_the_tab_and_the_process_and_closes_the_gap(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester", "writer"])
    name, _ = hub.prepare(cfg)
    pids = _pane_pids(rig, sessions.tmux_name(cfg, "app"))
    assert rig.wz(cfg, "park", "app") == 0
    assert wait_gone(pids) == []
    assert tabs(rig, name) == [(1, "mission-ctl"), (2, "tester"), (3, "writer")]
    assert rig.has(name)


def test_restart_and_roll_put_the_new_window_back_in_its_place(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester"])
    name, _ = hub.prepare(cfg)
    old = _pane_pids(rig, sessions.tmux_name(cfg, "app"))
    assert rig.wz(cfg, "cli", "app", "--detach", "--restart") == 0
    assert wait_gone(old) == []
    assert tabs(rig, name) == [(1, "mission-ctl"), (2, "app"), (3, "tester")]
    assert rig.wz(cfg, "roll", "app") == 0
    assert tabs(rig, name) == [(1, "mission-ctl"), (2, "app"), (3, "tester")]


def test_a_window_started_before_the_hub_existed_gets_the_role_name_as_its_tab_name(rig, cfg7):
    cfg = cfg7
    start_roles(rig, cfg, ["app"])
    n = sessions.tmux_name(cfg, "app")
    rig.tmux("rename-window", "-t", f"={n}:", "node")                       # what a session from before this version would show
    name, _ = hub.prepare(cfg)
    assert tabs(rig, name) == [(1, "app")]


def test_a_second_terminal_has_its_own_current_tab_and_going_away_leaves_the_hub(rig, cfg7, clients):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester"])
    name, how = hub.prepare(cfg)
    first = Client(rig, name)
    clients.append(first)
    second_name, how = hub.prepare(cfg)
    assert how == "second" and second_name == hub.hub_name(cfg, 2) and second_name != name
    second = Client(rig, second_name)
    clients.append(second)
    rig.tmux("select-window", "-t", f"={name}:3")
    rig.tmux("select-window", "-t", f"={second_name}:2")
    cur = lambda s: rig.tmux("display-message", "-p", "-t", "=" + s + ":", "#{window_name}").stdout.strip()
    assert (cur(name), cur(second_name)) == ("tester", "app")                 # one set of tabs, two current tabs
    assert tabs(rig, second_name) == tabs(rig, name)
    third_name, how = hub.prepare(cfg)
    assert (how, third_name) == ("second", hub.hub_name(cfg, 3))
    second.close()
    deadline = time.time() + 5
    while rig.has(second_name) and time.time() < deadline:
        time.sleep(0.05)
    assert not rig.has(second_name) and rig.has(name)                       # the extra view is gone, the hub and its tabs are not
    rig.tmux("kill-session", "-t", "=" + third_name)
    assert len(tabs(rig, name)) == 3


def test_closing_the_terminal_then_wz_hub_reattaches_the_same_hub(rig, cfg7, clients):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app"])
    name, _ = hub.prepare(cfg)
    c = Client(rig, name)
    rig.tmux("select-window", "-t", f"={name}:2")
    wid = rig.tmux("display-message", "-p", "-t", "=" + name + ":", "#{window_id}").stdout
    assert wid.startswith("@")
    c.close()
    deadline = time.time() + 5
    while rig.tmux("list-clients", "-t", "=" + name).stdout.strip() and time.time() < deadline:
        time.sleep(0.05)
    again, how = hub.prepare(cfg)
    assert (again, how) == (name, "reattach")
    assert rig.tmux("display-message", "-p", "-t", "=" + name + ":", "#{window_id}").stdout == wid          # still on the tab it was on


def test_from_inside_tmux_wz_hub_switches_this_client_and_wz_cli_selects_the_tab(rig, cfg7, clients, monkeypatch):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app", "tester"])
    assert rig.tmux("new-session", "-d", "-s", "outer", "-x", "160", "-y", "30").returncode == 0
    c = Client(rig, "outer")
    clients.append(c)
    pane = rig.tmux("display-message", "-p", "-t", "=outer:", "#{pane_id}").stdout.strip()
    cmd = f"cd / && PYTHONPATH={shlex.quote(str(ROOT))} {sys.executable} -m wz --config {shlex.quote(str(cfg.path))} "
    rig.tmux("send-keys", "-t", pane, cmd + "hub", "Enter")
    name = hub.hub_name(cfg)
    deadline = time.time() + 8
    while c.session() != name and time.time() < deadline:
        time.sleep(0.1)
    assert c.session() == name, rig.tmux("capture-pane", "-p", "-t", pane).stdout            # the terminal moved to the hub: no nested tmux
    # a command run from a role's pane inside the hub: `wz cli tester` goes to the tester tab instead of leaving the hub
    lead = rig.tmux("display-message", "-p", "-t", f"={name}:1", "#{pane_id}").stdout.strip()
    sock, pid, sid = rig.tmux("display-message", "-p", "-t", lead, "#{socket_path},#{pid},#{session_id}").stdout.strip().split(",")
    monkeypatch.setenv("TMUX", f"{sock},{pid},{sid.lstrip('$')}")
    monkeypatch.setenv("TMUX_PANE", lead)
    assert hub.in_hub(cfg) == name
    assert sessions.attach(sessions.tmux_name(cfg, "tester"), cfg, "tester") == 0
    assert c.session() == name
    assert rig.tmux("display-message", "-p", "-t", "=" + name + ":", "#{window_name}").stdout.strip() == "tester"
    assert hub.focus(cfg, "writer") is False                                # no live session, no tab: the caller falls back to switch-client


def test_a_light_shows_on_the_tab_even_when_it_is_the_current_one(rig, cfg7, clients):
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app"])
    name, _ = hub.prepare(cfg)
    lead_pane = rig.tmux("display-message", "-p", "-t", f"={sessions.tmux_name(cfg, 'mission-ctl')}:", "#{pane_id}").stdout.strip()
    app_pane = rig.tmux("display-message", "-p", "-t", f"={sessions.tmux_name(cfg, 'app')}:", "#{pane_id}").stdout.strip()
    rig.tmux("set-option", "-g", "window-status-current-style", "bg=colour39,fg=colour234")      # a user's own current-tab colours
    assert mux.paint_window(lead_pane, light.OPTION, light.STYLES["work"])                           # lead = current tab 1
    assert mux.paint_window(app_pane, light.OPTION, light.STYLES["ask"])                             # app = tab 2
    c = Client(rig, name)
    clients.append(c)
    rig.tmux("select-window", "-t", f"={name}:1")
    out = c.drain(1.0).decode("latin-1")
    amber, red = "48;5;178", "48;5;160"
    assert amber in out and red in out
    i = out.rindex("1:mission-ctl")
    assert amber in out[max(0, i - 120):i], "the current tab did not show its light"                 # and not the user's blue (39)
    assert "48;5;39m 1:mission-ctl" not in out


def test_the_log_says_whether_the_hub_survived_the_end_of_an_attach(rig, cfg7, clients):
    """`wz hub` itself in a terminal (a pty): detach leaves the hub up; killing the hub under the client says gone."""
    cfg = cfg7
    start_roles(rig, cfg, ["mission-ctl", "app"])
    name = hub.hub_name(cfg)
    env = {k: v for k, v in os.environ.items() if k != "TMUX"} | {"TERM": "xterm-256color", "PYTHONPATH": str(ROOT)}
    argv = [sys.executable, "-m", "wz", "--config", str(cfg.path), "hub"]

    def terminal():
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir("/")
            os.execvpe(argv[0], argv, env)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 160, 0, 0))
        end = time.time() + 8
        while time.time() < end and not rig.tmux("list-clients", "-t", "=" + name).stdout.strip():
            select.select([fd], [], [], 0.1)
            try:
                os.read(fd, 65536) if select.select([fd], [], [], 0)[0] else None
            except OSError:
                break
        assert rig.tmux("list-clients", "-t", "=" + name).stdout.strip(), "wz hub did not attach"
        return pid, fd

    def finish(pid, fd):
        end = time.time() + 8
        while time.time() < end:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    os.read(fd, 65536)
                except OSError:
                    break
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done:
                break
        os.close(fd)

    pid, fd = terminal()
    os.write(fd, b"\x02d")                                                  # Ctrl-b d
    finish(pid, fd)
    assert rig.has(name)
    pid, fd = terminal()                                                    # the same hub again
    rig.tmux("kill-session", "-t", "=" + name)
    finish(pid, fd)
    lines = (cfg.state / "hub.log").read_text().splitlines()
    kinds = [x.split("  ")[1] for x in lines]
    assert kinds == ["build", "attach-ended", "reattach", "attach-ended"], lines
    assert "hub still up" in lines[1] and "hub gone" in lines[3]


def test_hub_names_cannot_collide_with_a_role_or_another_workspace(rig, cfg7):
    cfg = cfg7
    assert hub.hub_name(cfg) != sessions.tmux_name(cfg, "hub")
    assert rig.tmux("new-session", "-d", "-s", hub.hub_name(cfg), "sleep 600").returncode == 0     # someone else's session with that name
    with pytest.raises(hub.HubError):
        hub.prepare(cfg)
