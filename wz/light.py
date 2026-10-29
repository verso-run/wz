"""Lights: `wz light <work|ask|done|off>` colours the role's own tmux window (amber working, red asking, green done).

Claude Code runs this from hooks on every prompt and every tool, so it is a stand-alone file, run as
`python -I -S <this file> <state>` (see `command()`): about 4 ms when the light is already right, against ~50 ms for
`wz hook guard`, which imports the whole package. It imports nothing of wz at the top; only a call that has to paint loads
wz/mux.py (the one module that runs tmux). Do not add other imports of wz here.

The state is one line in `<workspace>/.wz/sessions/<role>.light`: the state and the tmux pane it was painted on. The same
state on the same pane twice does nothing and starts no tmux. The colour is a tmux *window* option set on the pane's own
window, so it shows in the role's session and in any other session that window is linked into (a hub's tab).

Each call also touches `<workspace>/.wz/sessions/<role>.beat`, whatever the state: the role's beat, which the agent
watchdog (wz/agents.py) reads. The touch is one utime on a file that already exists (about 20 us), and costs no tmux call.

It does nothing, and exits 0, unless WZ_ROLE is set and WZ_JOB is not: a background job shares the hook settings with the
role's chat and must not paint the chat's window. A hook must never fail Claude, so every other problem is also an exit 0.
"""
import os
import sys

STYLES = {"work": "bg=colour178,fg=black", "ask": "bg=colour160,fg=white", "done": "bg=colour28,fg=white"}
STATES = (*STYLES, "off")
OPTION = "window-status-style"


def command() -> list[str]:
    """The argv prefix a hook or launch script uses; append the state."""
    return [sys.executable, "-I", "-S", os.path.abspath(__file__)]


def light_file(home: str, role: str) -> str:
    return os.path.join(home, ".wz", "sessions", f"{role}.light")


def beat_file(home: str, role: str) -> str:
    return os.path.join(home, ".wz", "sessions", f"{role}.beat")


def _beat(home: str, role: str) -> None:
    path = beat_file(home, role)
    try:
        os.utime(path)
    except FileNotFoundError:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a"):
                pass
        except OSError:
            pass
    except OSError:
        pass


def _home(env) -> str:
    if env.get("WZ_HOME"):
        return env["WZ_HOME"]
    return os.path.dirname(env["WZ_CONFIG"]) if env.get("WZ_CONFIG") else ""


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def set_light(state: str, env=os.environ) -> int:
    role, home, pane = env.get("WZ_ROLE", ""), _home(env), env.get("TMUX_PANE", "")
    if state not in STATES or not role or env.get("WZ_JOB") or not home or not pane:
        return 0
    _beat(home, role)
    path = light_file(home, role)
    want = f"{state} {pane}"
    have = _read(path)
    if have == want or (state == "off" and not have):
        return 0
    if not __package__:             # run as a file (`python -I`): the package folder is not on the path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from wz import mux              # imported only here: subprocess and shutil cost more than the rest of a no-change call
    if state == "off":
        # Unset, not "default": the person's own tmux theme comes back. The pane may be gone already; the file goes either way.
        mux.paint_window(pane, OPTION, None)
        try:
            os.unlink(path)
        except OSError:
            pass
        return 0
    if not mux.paint_window(pane, OPTION, STYLES[state]):
        return 0                                    # no such pane (a stale TMUX_PANE): record nothing, so the next call retries
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(want + "\n")
        os.replace(tmp, path)
    except OSError:
        pass
    return 0


def current(home: str, role: str) -> str:
    """The recorded light of a role ('work', 'ask', 'done') or '' when it has none."""
    return _read(light_file(home, role)).split(" ")[0]


def clear(home: str, role: str) -> None:
    """Forget a role's light (its window is being killed, so there is nothing to unpaint)."""
    try:
        os.unlink(light_file(home, role))
    except OSError:
        pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv and not sys.stdin.isatty():
            sys.stdin.read()                        # Claude pipes the event JSON in; take it so the writer never sees a closed pipe
    except (OSError, ValueError):
        pass
    try:
        return set_light(argv[0] if argv else "")
    except Exception:                                # a light is decoration: never fail the hook
        return 0


if __name__ == "__main__":
    sys.exit(main())
