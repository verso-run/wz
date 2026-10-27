"""The only place wz runs tmux. Every other module asks this one, so there is one argv per action and one count of calls.

`CALLS` records the arguments of every tmux process started here, in order. A test that must prove "this path made no
tmux call" (a hook that runs on every tool, say) reads it with `calls()` after `reset_calls()`.

A role's tmux session holds one window, the one running its launch script. A window can also be linked into a second
session (a hub that shows several roles as tabs); `kill-session` on the role then leaves that window, and Claude in it,
alive in the other session. `kill_role` therefore kills the window, which removes it from every session it is linked into.
"""
from __future__ import annotations

import shutil
import subprocess

CALLS: list[tuple[str, ...]] = []


def calls() -> list[tuple[str, ...]]:
    return list(CALLS)


def reset_calls() -> None:
    CALLS.clear()


def have() -> bool:
    return shutil.which("tmux") is not None


def version() -> str:
    """`tmux -V` ('tmux 3.4'), or '' when tmux is not installed or does not answer."""
    try:
        r = run("-V")
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def run(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    CALLS.append(args)
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)


def call(*args: str) -> int:
    """tmux with the terminal attached (nothing captured): an attach waits here until the client detaches."""
    CALLS.append(args)
    return subprocess.call(["tmux", *args])


def _session(name: str) -> str:
    """Exact match: a bare `-t guide` would also hit a session called guide-writer."""
    return f"={name}"


def has_session(name: str) -> bool:
    return run("has-session", "-t", _session(name)).returncode == 0


def new_session(name: str, cwd: str, command: str, window: str = "") -> subprocess.CompletedProcess:
    """`window` names the window (a hub tab shows it); a named window is not renamed by tmux after the command starts."""
    return run("new-session", "-d", "-s", name, *(["-n", window] if window else []), "-c", cwd, "-x", "200", "-y", "50", command)


def kill_role(name: str) -> None:
    """Stop the role's Claude: kill its window (wherever it is linked), then the session if anything of it is left."""
    wid = run("display-message", "-p", "-t", f"{_session(name)}:", "#{window_id}")
    if wid.returncode != 0:
        return
    window = wid.stdout.strip()
    if window.startswith("@"):
        run("kill-window", "-t", window)
    if has_session(name):
        run("kill-session", "-t", _session(name))


def panes(name: str) -> list[str]:
    """The pane ids (like %12) of the role's window; empty when it has no session."""
    r = run("list-panes", "-t", f"{_session(name)}:", "-F", "#{pane_id}")
    return r.stdout.split() if r.returncode == 0 else []


def capture_pane(name: str) -> str:
    r = run("capture-pane", "-p", "-t", f"{_session(name)}:")
    return r.stdout if r.returncode == 0 else ""


def send_keys(name: str, *keys: str, literal: bool = False) -> None:
    run("send-keys", "-t", f"{_session(name)}:", *(["-l"] if literal else []), *keys)


def show_option(name: str, option: str) -> str:
    return run("show-options", "-v", "-t", f"{_session(name)}:", option).stdout.strip()


def set_option(name: str, option: str, value: str) -> None:
    run("set-option", "-t", f"{_session(name)}:", option, value)


def switch_client(name: str) -> subprocess.CompletedProcess:
    return run("switch-client", "-t", _session(name))


def attach(name: str) -> int:
    return call("attach-session", "-t", _session(name))


def current_session() -> str:
    """The tmux session of the terminal this process runs in ('' when not inside tmux)."""
    r = run("display-message", "-p", "#{session_name}")
    return r.stdout.strip() if r.returncode == 0 else ""


SEP = "\t"


def list_sessions() -> list[dict]:
    """Every session: name, number of attached clients, and the wz workspace that owns it ('' when none)."""
    r = run("list-sessions", "-F", SEP.join(["#{session_name}", "#{session_attached}", "#{@wz_root}"]))
    out = []
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        name, attached, root = (line.split(SEP) + ["", ""])[:3]
        out.append({"name": name, "attached": int(attached or 0), "root": root})
    return out


def list_windows() -> list[dict]:
    """Every window of every session (one entry per link, so a linked window appears once per session it is in)."""
    r = run("list-windows", "-a", "-F", SEP.join(["#{session_name}", "#{window_index}", "#{window_id}", "#{window_name}",
                                                  "#{window_active}", "#{@wz_hub}"]))
    out = []
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        f = (line.split(SEP) + [""] * 6)[:6]
        out.append({"session": f[0], "index": int(f[1]), "id": f[2], "name": f[3], "active": f[4] == "1", "hub": f[5] == "1"})
    return out


CURRENT = {"window-status-style": ("window-status-current-style", ",underscore")}


def paint_window(pane: str, option: str, value: str | None) -> bool:
    """Set (or, with None, unset) a window option on the window that holds `pane` (an id like %12, from $TMUX_PANE).
    False when tmux refused it (no such pane). A linked window shows the option in every session it is linked into.
    A status style also goes on the window's *current* style (underlined), in the same tmux call: a tab that is the current
    one would otherwise show the user's own current-tab colours and hide the light."""
    def one(opt: str, v: str | None) -> list[str]:
        return ["set-option", "-w", *(["-u"] if v is None else []), "-t", pane, opt, *([v] if v is not None else [])]
    args = one(option, value)
    if option in CURRENT:
        cur, extra = CURRENT[option]
        args += [";", *one(cur, None if value is None else value + extra)]
    return run(*args).returncode == 0
