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


def new_session(name: str, cwd: str, command: str) -> subprocess.CompletedProcess:
    return run("new-session", "-d", "-s", name, "-c", cwd, "-x", "200", "-y", "50", command)


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
