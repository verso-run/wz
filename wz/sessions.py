"""Interactive role sessions: one named Claude conversation per role, kept alive in a tmux session.

`wz cli <role>` opens a role's session. The first time, Claude is started with `--name <conversation>`; every time
after that with `--resume <conversation>`, from the same CLAUDE_CONFIG_DIR, so the role keeps its memory across a
closed window, a detach and a reboot. What wz remembers lives in `.wz/sessions/<role>.json`:

    n            the conversation generation: the name is wz-<project>-<role>, then -2, -3 ... after `wz roll`
    launched     Claude was started under this name, so the next start resumes it
    parked       `wz park` was run: `wz start-all` leaves this role alone
    config_dir   the CLAUDE_CONFIG_DIR the conversation was created in ("" = Claude's default)
    sig          a hash of the launch settings, to tell a running session it is out of date

and `.wz/sessions/<role>.state`, written by the launch script: `running`, or `exited <code> <seconds>` when Claude ends. A
start whose Claude ended within 30 s with no saved conversation by that name begins again with `--name`, not `--resume`.

The tmux session is named wz-<project>-<role> and does not change when the conversation is rolled. Everything the role
needs (PATH, WZ_*, CLAUDE_CONFIG_DIR) is set by a small launch script inside the session's own shell, so it does not
depend on what environment an already-running tmux server started with (wz's own variables, PATH and CLAUDE_CONFIG_DIR are
set here; anything else in that environment still reaches the role), and it works on tmux versions that have no
`new-session -e` (older than 3.2). When Claude exits the window becomes a login shell, so the session never vanishes.

`wz say <role> <text>` types a line into a role's live session (see `say`) and only reports it said once Claude's input
box has emptied again.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import charters, light, mux, timers, util

RULE = re.compile(r"^[─-]{20,}")
RESUME_PICKER = re.compile(r"Resume Session|No sessions match|No conversations found", re.I)
LOGIN = re.compile(r"Select login method|Paste code here|Browser didn't open|Opening browser to sign in|Please run /login|Invalid API key")
DIALOG = re.compile(r"Enter to confirm\s*·\s*Esc to cancel|Press\s+Enter\s+to\s+continue|Do you trust|Esc to cancel")


class SessionError(Exception):
    pass


# ---- names and state -----------------------------------------------------------------------------------------------
def tmux_name(cfg, role: str) -> str:
    return f"wz-{timers._slug(cfg)}-{role}"


def state_dir(cfg) -> Path:
    return cfg.state / "sessions"


def load(cfg, role: str) -> dict:
    st = {"n": 1, "launched": False, "parked": False, "config_dir": "", "sig": ""}
    st.update(util.read_json(state_dir(cfg) / f"{role}.json", {}) or {})
    return st


def save(cfg, role: str, st: dict) -> None:
    util.write_json(state_dir(cfg) / f"{role}.json", st)


def conversation(cfg, role: str, st: dict | None = None) -> str:
    n = (st or load(cfg, role))["n"]
    return tmux_name(cfg, role) + (f"-{n}" if n > 1 else "")


# ---- tmux ----------------------------------------------------------------------------------------------------------
def have_tmux() -> bool:
    return mux.have()


def running(name: str) -> bool:
    return mux.has_session(name)


def _kill(name: str, cfg=None, role: str = "") -> None:
    """Stop the role's Claude for good, also when its window is linked into another tmux session (see mux.kill_role).
    Given the role, also forgets its light (the window it was painted on is gone)."""
    if running(name):
        mux.kill_role(name)
    if cfg is not None and role:
        light.clear(str(cfg.root), role)


def capture(name: str) -> str:
    return mux.capture_pane(name)


def classify(text: str) -> str:
    """What a role's pane shows: ready | resume_picker | login | dialog | shell | busy."""
    lines = text.split("\n")
    rules = [i for i, l in enumerate(lines) if RULE.match(l)]
    if len(rules) >= 2 and sum(1 for l in lines[rules[-1] + 1:] if l.strip()) <= 4:
        return "ready"
    flat = re.sub(r"\s+", " ", text)
    if RESUME_PICKER.search(flat):
        return "resume_picker"
    if LOGIN.search(flat):
        return "login"
    if DIALOG.search(flat):
        return "dialog"
    last = [l for l in lines if l.strip()]
    if last and re.search(r"[$#] ?$", last[-1].rstrip() + " ") and "Claude Code v" not in text:
        return "shell"
    return "busy"


def wait_ready(name: str, seconds: float, exited=lambda: False) -> tuple[bool, str]:
    """Poll the pane until Claude's input box has been there on two polls in a row. Never presses a key.
    `exited()` says the launch script saw Claude end (the reliable sign that the window is now a shell)."""
    deadline = time.monotonic() + seconds
    seen, kind, text = 0, "busy", ""
    while time.monotonic() < deadline:
        if not running(name):
            return False, "the window closed before an input box appeared"
        text = capture(name)
        kind = "shell" if exited() else classify(text)
        if kind == "ready":
            seen += 1
            if seen >= 2:
                return True, "ready"
        else:
            seen = 0
            if kind in ("shell", "resume_picker", "login"):
                break
        time.sleep(0.4)
    why = {"shell": "Claude exited and the window is a shell", "login": "Claude is asking you to log in",
           "resume_picker": "Claude could not find the conversation to resume", "dialog": "Claude is showing a question that needs you"
           }.get(kind, f"no input box after {seconds:.0f} s")
    tail = "\n".join([l.rstrip() for l in text.split("\n") if l.strip()][-6:])
    return False, why + (f"\n{tail}" if tail else "")


# ---- the launch plan -----------------------------------------------------------------------------------------------
def _path_dirs(cfg, command0: str) -> list[str]:
    """The directories the pane's PATH starts with: where Claude and wz live now, the usual install places, then PATH."""
    home = Path.home()
    first = []
    for exe in (command0, "wz"):
        found = shutil.which(exe)
        if found:
            first.append(str(Path(found).parent))
    usual = [home / ".local" / "bin", home / ".claude" / "local", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    first += [str(d) for d in usual if d.is_dir()]
    seen, out = set(), []
    for d in first + [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def plan(cfg, role: str) -> dict:
    """Everything a start needs: cwd, env, PATH, the command with --name or --resume, and a signature of the settings.
    The role's charter and the hook settings are made current first, so a hand edit of wz.toml reaches every start."""
    r = cfg.role(role)
    charters.ensure(cfg, role)
    a = cfg.agent()
    st = load(cfg, role)
    name = conversation(cfg, role, st)
    base = shlex.split(a["command"])
    if not base:
        raise SessionError("[agent] command in wz.toml is empty")
    flags = ["--append-system-prompt-file", str(cfg.charter_path(role)), "--settings", str(cfg.role_settings),
             "--permission-mode", a["permission_mode"]]
    if r["model"]:
        flags += ["--model", r["model"]]
    if a.get("pass_effort") and r["effort"]:
        flags += ["--effort", r["effort"]]
    cwd = cfg.store_root(r["store"])
    resume = bool(st["launched"]) and not _never_saved(cfg, role, st, name, cwd)
    convo_flag = ["--resume" if resume else "--name", name]
    env = {"WZ_ROLE": role, "WZ_CONFIG": str(cfg.path), "WZ_HOME": str(cfg.root), "WZ_SCRATCH": str(cfg.scratch(role))}
    acct = cfg.account(r["account"]).get("config_dir") if r["account"] else ""
    cdir = os.path.expanduser(acct) if acct else os.environ.get("CLAUDE_CONFIG_DIR", "")
    note = ""
    if resume and st["config_dir"] != cdir:
        note = (f"{role}: its conversation lives in {st['config_dir'] or 'Claude’s default config folder'}, "
                f"not {cdir or 'Claude’s default config folder'}; resuming from where it lives")
        cdir = st["config_dir"]
    if cdir:
        env["CLAUDE_CONFIG_DIR"] = cdir
    dirs = _path_dirs(cfg, base[0])
    path = os.pathsep.join(dirs)
    exe = shutil.which(base[0], path=path)
    sig_src = json.dumps([base, flags, env, str(cwd)], sort_keys=True)
    for f in (cfg.charter_path(role), cfg.role_settings):
        sig_src += f.read_text() if f.is_file() else ""
    return {"role": role, "name": name, "notice": cfg.mode_notice(), "tmux": tmux_name(cfg, role), "cwd": cwd, "env": env, "path": path,
            "exe": exe, "cmd": base + flags + convo_flag, "resume": resume, "note": note, "config_dir": cdir,
            "sig": hashlib.sha1(sig_src.encode()).hexdigest()[:12]}


def _script(cfg, p: dict) -> Path:
    """The launch script the tmux window runs. A file, so no quoting layer depends on tmux's default shell."""
    q = shlex.quote
    d = state_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    marker = d / f"{p['role']}.state"
    lines = ["#!/bin/sh",
             "# Written by `wz cli` each time it starts this window. Change wz.toml, not this file.",
             f"cd {q(str(p['cwd']))} || {{ printf 'wz: cannot enter %s\\n' {q(str(p['cwd']))}; exec \"${{SHELL:-/bin/sh}}\" -l; }}",
             f"export PATH={q(p['path'])}"]
    lines += [f"export {k}={q(v)}" for k, v in p["env"].items()]
    if "CLAUDE_CONFIG_DIR" not in p["env"]:
        lines.append("unset CLAUDE_CONFIG_DIR")
    lines += ["unset WZ_JOB WZ_WORKTREE",
              f"echo running > {q(str(marker))}",
              "t0=$(date +%s)",
              " ".join(q(c) for c in p["cmd"]),
              "rc=$?",
              " ".join(q(c) for c in [*light.command(), "off"]),          # a dead Claude must not leave its light on
              f"echo \"exited $rc $(( $(date +%s) - t0 ))\" > {q(str(marker))}",
              "printf '\\n[wz] Claude ended (exit %s). Its conversation is saved. This window is a plain shell now.\\n' \"$rc\"",
              f"printf '[wz] To go on, leave it and run:  wz cli {p['role']}\\n'",
              "exec \"${SHELL:-/bin/sh}\" -l", ""]
    marker.write_text("starting\n")          # not the last run's 'exited', which a waiting `start-all` would believe
    path = d / f"{p['role']}.sh"
    path.write_text("\n".join(lines))
    path.chmod(0o755)
    return path


def _marker(cfg, role: str) -> list[str]:
    """What the launch script last wrote: ['running'] or ['exited', <exit code>, <seconds Claude ran>]."""
    try:
        return (state_dir(cfg) / f"{role}.state").read_text().split()
    except OSError:
        return []


def _exited(cfg, role: str) -> bool:
    return _marker(cfg, role)[:1] == ["exited"]


EARLY_S = 30


def project_folder(cwd: Path) -> str:
    """The folder name Claude gives a working directory under <config dir>/projects: every character that is not an ASCII
    letter or digit (a `/`, `.`, `_`, a space, any non-ASCII) becomes `-`."""
    return "".join(c if c.isascii() and c.isalnum() else "-" for c in str(cwd))


def _on_disk(config_dir: str, cwd: Path, name: str) -> bool:
    """Is there a saved conversation titled `name` for this folder? (Claude keeps them in <config dir>/projects/<folder>/*.jsonl.)"""
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    folder = project_folder(cwd)
    needle = f'"customTitle":"{name}"'
    for f in sorted((base / "projects" / folder).glob("*.jsonl")):
        try:
            with open(f, errors="replace") as fh:
                if any(needle in line for line in fh):
                    return True
        except OSError:
            continue
    return False


def _never_saved(cfg, role: str, st: dict, name: str, cwd: Path) -> bool:
    """Claude was started under this name and ended within EARLY_S seconds without saving a conversation (a login, a
    closed dialog, an immediate /exit): `--resume` would find nothing, so the next start must create it again."""
    m = _marker(cfg, role)
    if not st["launched"] or m[:1] != ["exited"] or len(m) < 3 or not m[2].isdigit() or int(m[2]) >= EARLY_S:
        return False
    return not _on_disk(st["config_dir"], cwd, name)


# ---- start, attach, stop -------------------------------------------------------------------------------------------
def _check_owner(cfg, name: str) -> None:
    other = mux.show_option(name, "@wz_root")
    if other and other != str(cfg.root):
        raise SessionError(f"a tmux session called {name} already belongs to another wz workspace ({other}); "
                           "give this project a different name in wz.toml ([project] name)")


def ensure(cfg, role: str, *, restart: bool = False, wait: float = 0.0) -> str:
    """Make sure the role's tmux session exists and runs Claude. Returns 'started', 'running' or 'restarted'."""
    if not have_tmux():
        raise SessionError("tmux is not installed; use `wz cli --no-tmux` to run in this terminal")
    p = plan(cfg, role)
    name = p["tmux"]
    if p["note"]:
        print(f"wz: {p['note']}", file=sys.stderr)
    how = "started"
    if running(name):
        _check_owner(cfg, name)
        if _exited(cfg, role):
            print(f"wz: Claude had ended in {name}; starting it again ({p['name']})")
            _kill(name, cfg, role)
            how = "restarted"
        elif restart:
            _kill(name, cfg, role)
            how = "restarted"
        else:
            if load(cfg, role)["sig"] != p["sig"]:
                print(f"wz: {name} is already running with its earlier settings (wz.toml, the charter or the account changed since). "
                    f"`wz cli {role} --restart` applies them and keeps the conversation.", file=sys.stderr)
            return "running"
    if not p["exe"]:
        raise SessionError(f"`{shlex.split(cfg.agent()['command'])[0]}` (Claude Code) is not on your PATH or in the usual places; "
                           "install it, or set [agent] command in wz.toml")
    cfg.scratch(role).mkdir(parents=True, exist_ok=True)
    announce(p)
    script = _script(cfg, p)
    r = mux.new_session(name, str(p["cwd"]), f"sh {shlex.quote(str(script))}")
    if r.returncode != 0:
        raise SessionError(f"tmux could not start {name}: {(r.stderr or r.stdout).strip()}")
    mux.set_option(name, "@wz_root", str(cfg.root))
    st = load(cfg, role)
    st.update(launched=True, parked=False, config_dir=p["config_dir"], sig=p["sig"])
    save(cfg, role, st)
    if wait:
        ok, why = wait_ready(name, wait, lambda: _exited(cfg, role))
        if not ok:
            raise SessionError(f"{name} is running but not at an input box: {why}")
    else:
        time.sleep(float(os.environ.get("WZ_START_SETTLE", "1.5")))
        if not running(name):
            raise SessionError(f"{name} closed straight after starting")
    return how


def announce(p: dict) -> None:
    """The permission-mode line for the person at the keyboard, when the mode is not one where Claude asks first."""
    if p["notice"]:
        print(p["notice"], file=sys.stderr)


def attach(name: str) -> int:
    if os.environ.get("TMUX"):
        r = mux.switch_client(name)
        if r.returncode == 0:
            return 0
        print(f"wz: could not switch this tmux client ({r.stderr.strip()}); to go there: tmux switch-client -t {name}", file=sys.stderr)
        return 1
    return mux.attach(name)


def open_role(cfg, role: str, *, detach: bool = False, no_tmux: bool = False, restart: bool = False) -> int:
    """`wz cli <role>`."""
    p = plan(cfg, role)
    verb = "resuming" if p["resume"] else "starting"
    if no_tmux or not have_tmux():
        if not no_tmux:
            print("wz: tmux is not installed, so this session ends when you close the window (the conversation is saved).", file=sys.stderr)
        if detach:
            raise SessionError("--detach needs tmux")
        if not p["exe"]:
            raise SessionError(f"`{p['cmd'][0]}` (Claude Code) is not on your PATH or in the usual places")
        announce(p)
        print(f"wz: {role}: {verb} conversation {p['name']}", file=sys.stderr)
        cfg.scratch(role).mkdir(parents=True, exist_ok=True)
        st = load(cfg, role)
        st.update(launched=True, parked=False, config_dir=p["config_dir"])
        save(cfg, role, st)
        env = {**os.environ, **p["env"], "PATH": p["path"]}
        if "CLAUDE_CONFIG_DIR" not in p["env"]:
            env.pop("CLAUDE_CONFIG_DIR", None)
        for k in ("WZ_JOB", "WZ_WORKTREE"):
            env.pop(k, None)
        t0 = time.time()
        rc = subprocess.call(p["cmd"], cwd=str(p["cwd"]), env=env)
        (state_dir(cfg) / f"{role}.state").write_text(f"exited {rc} {int(time.time() - t0)}\n")
        return rc
    how = ensure(cfg, role, restart=restart)
    if how == "running":
        announce(p)                  # ensure() announces a launch; an already-running window is announced here
    if detach:
        print(f"{p['tmux']} {how}, conversation {p['name']}; attach with: wz cli {role}")
        return 0
    print(f"wz: {role}: {'already running,' if how == 'running' else verb} conversation {p['name']} in tmux session {p['tmux']} "
          "(Ctrl-b then d leaves it running)", file=sys.stderr)
    return attach(p["tmux"])


def park(cfg, role: str) -> int:
    cfg.role(role)
    name = tmux_name(cfg, role)
    was = have_tmux() and running(name)
    if was:
        _kill(name, cfg, role)
    light.clear(str(cfg.root), role)
    st = load(cfg, role)
    st["parked"] = True
    save(cfg, role, st)
    print(f"parked {role}" + (f" (closed {name})" if was else " (it was not running)")
        + f"; `wz start-all` leaves it alone. `wz cli {role}` brings it back, resuming {conversation(cfg, role, st)}.")
    return 0


def roll(cfg, role: str) -> int:
    cfg.role(role)
    name = tmux_name(cfg, role)
    if have_tmux():
        _kill(name, cfg, role)
    st = load(cfg, role)
    st.update(n=st["n"] + 1, launched=False, parked=False)
    save(cfg, role, st)
    print(f"{role}: a fresh conversation, {conversation(cfg, role, st)} (the old one is still there to --resume by hand)")
    ensure(cfg, role, wait=_wait_s())
    print(f"started {name}; attach with: wz cli {role}")
    return 0


def _wait_s() -> float:
    return float(os.environ.get("WZ_START_WAIT", "60"))


def start_all(cfg) -> int:
    """After a reboot: every role that had a session and is not parked, detached, one at a time, each confirmed."""
    bad = []
    for role in cfg.roles():
        st = load(cfg, role)
        if not st["launched"] or st["parked"]:
            continue
        try:
            how = ensure(cfg, role, wait=_wait_s())
            print(f"{role}: {'already running' if how == 'running' else how} ({conversation(cfg, role, st)})")
        except SessionError as e:
            bad.append(role)
            print(f"wz start-all: {role}: {e}", file=sys.stderr)
    list_roles(cfg)
    if bad:
        print(f"wz start-all: NOT at an input box: {' '.join(bad)} (open one with `wz cli <role>` to see why)", file=sys.stderr)
        return 1
    return 0


def role_state(cfg, role: str) -> str:
    st = load(cfg, role)
    name = tmux_name(cfg, role)
    if have_tmux() and running(name):
        if _exited(cfg, role):
            return "Claude ended (window is a shell)"
        return {"ready": "running, at the input box", "login": "running, waiting for login", "dialog": "running, waiting at a question",
                "resume_picker": "running, conversation not found", "shell": "running, Claude ended"}.get(classify(capture(name)), "running")
    if st["parked"]:
        return "parked"
    return "stopped (resumes on `wz cli`)" if st["launched"] else "never started"


def list_roles(cfg) -> int:
    rows = [{"role": r, "tmux session": tmux_name(cfg, r), "conversation": conversation(cfg, r), "state": role_state(cfg, r),
             "light": light.current(str(cfg.root), r) or "-"} for r in cfg.roles()]
    w = {c: max(len(c), *(len(x[c]) for x in rows)) for c in rows[0]} if rows else {}
    if not rows:
        print("(no roles)")
        return 0
    print("  ".join(c.ljust(w[c]) for c in w))
    for x in rows:
        print("  ".join(x[c].ljust(w[c]) for c in w))
    return 0


def print_plan(cfg, role: str) -> int:
    p = plan(cfg, role)
    announce(p)
    q = shlex.quote
    print(f"cd {q(str(p['cwd']))}")
    print("env " + " ".join(f"{k}={q(v)}" for k, v in p["env"].items()) + " " + " ".join(q(c) for c in p["cmd"]))
    print(f"# tmux session {p['tmux']}; conversation {p['name']}: "
        + ("resumes it (--resume)" if p["resume"] else "first start, creates it (--name); later starts use --resume"))
    return 0


# ---- say: a line into a role's live session --------------------------------------------------------------------------
# Typing into a session is not delivering. The text is sent, Enter is pressed, and the line counts as said only when the
# input box (between the last two full-width rules of the pane) is empty again. (The obvious version presses Enter once
# and greps the pane for the text; a line Claude folded to "[Pasted text #1 +3 lines]", or an Enter eaten by its paste
# handling, then sits unsent while every report says "said".)
NOBOX = None
QUEUED = re.compile(r"edit queued messages", re.I)

SUBMITTED, STILL_TYPED, NO_BOX, UNCONFIRMED, QUEUED_BY_TURN = "submitted", "still_typed", "no_box", "unconfirmed", "queued"


def pane_input(text: str) -> str | None:
    """What is typed in the input box of this pane text; None when the pane has no box (a dialog, a loading session)."""
    lines = text.split("\n")
    rules = [i for i, l in enumerate(lines) if RULE.match(l)]
    if len(rules) < 2:
        return NOBOX
    box = " ".join(x.strip() for x in lines[rules[-2] + 1:rules[-1]]).strip()
    return re.sub(r"^[\u276f>]\s*", "", box).strip()


def _send(name: str, *keys: str, literal: bool = False) -> None:
    mux.send_keys(name, *keys, literal=literal)


def pane_submit(name: str, text: str) -> str:
    """Type `text` into the session's input box and press Enter. Returns SUBMITTED (box back to what it held before),
    STILL_TYPED (the text is still in the box after every Enter; it is cleared again), NO_BOX (no box to read before
    typing: nothing was sent), UNCONFIRMED (the box vanished after typing, e.g. a dialog opened: sent once, outcome unknown)
    or QUEUED_BY_TURN (Claude is mid-turn and queued it: delivered when the turn ends, so Enter is never repeated)."""
    settle = float(os.environ.get("WZ_SAY_SETTLE", "0.3"))
    wait = float(os.environ.get("WZ_SAY_WAIT", "1.5"))
    _send(name, "C-u")
    time.sleep(settle)
    base = pane_input(capture(name))
    if base is NOBOX:
        return NO_BOX
    queued_before = bool(QUEUED.search(capture(name)))     # a queue that was already there says nothing about our text
    _send(name, text, literal=True)
    time.sleep(settle)
    for _ in range(4):
        _send(name, "Enter")
        time.sleep(wait)
        pane = capture(name)
        cur = pane_input(pane)
        if cur is NOBOX:
            return UNCONFIRMED
        if not queued_before and QUEUED.search(pane):
            return QUEUED_BY_TURN
        if cur == "" or cur == base:
            return SUBMITTED
    _send(name, "C-u")                                      # do not leave an unsent line to be glued onto the next one
    return STILL_TYPED


def note(cfg, role: str, text: str, sender: str = "") -> Path:
    """The role has no live session: the line goes to the top of its STATE.md (the next job reads it; a session reads it on
    start) and never becomes a job (a line that only informs once started a whole job)."""
    f = cfg.role_dir(role) / "STATE.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    old = f.read_text() if f.is_file() else f"# {role} — notes for the next job\n\n"
    who = f" from {sender}" if sender else ""
    f.write_text(f"> **Note{who} {datetime.now().strftime('%Y-%m-%d %H:%M')}:** {text}\n\n{old}")
    return f


def _live(cfg, role: str) -> tuple[bool, str]:
    """Is there a session whose Claude is up (not a shell it fell back to)? And, if not, why."""
    name = tmux_name(cfg, role)
    if not have_tmux():
        return False, "tmux is not installed"
    if not running(name):
        return False, "parked" if load(cfg, role)["parked"] else "no live session"
    if _exited(cfg, role):
        return False, "Claude ended (its window is a shell)"
    return True, ""


def _log_say(cfg, role: str, sender: str, text: str, outcome: str) -> None:
    """One line per `wz say` in .wz/say.jsonl: who, to whom, what became of it (the proof that a lead handed work over)."""
    try:
        util.append_jsonl(cfg.state / "say.jsonl", {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "from": sender or "owner",
                                                    "to": role, "outcome": outcome, "text": text[:300]})
    except OSError:
        pass


def say(cfg, role: str, text: str, sender: str = "") -> int:
    """`wz say <role> <text>`. Exit 0: said (or noted for a role with no live session), 1: the line is not delivered."""
    cfg.role(role)
    text = " ".join(text.split())                           # a newline would press Enter in the middle of the line
    if not text:
        raise SessionError("nothing to say")
    if sender == role:
        raise SessionError("that is your own session")
    if sender and not cfg.is_lead(sender) and not cfg.is_lead(role):
        raise SessionError(f"a role may message the lead ({cfg.lead()}), not another role: put what {role} needs in your report "
                           f"or a ledger row and the lead routes it")
    line = f"[from {sender}] {text}" if sender else text
    name = tmux_name(cfg, role)
    live, why = _live(cfg, role)
    if live:
        kind = classify(capture(name))
        if kind not in ("ready", "busy"):
            live, why = False, {"login": "Claude is at a login screen", "dialog": "Claude is showing a question",
                                "resume_picker": "Claude is at the conversation picker", "shell": "its window is a shell"}[kind]
    if live:
        got = pane_submit(name, line)
        _log_say(cfg, role, sender, text, got)
        if got == SUBMITTED:
            print(f"said to {role} ({name}): its input box emptied")
            return 0
        if got == QUEUED_BY_TURN:
            print(f"said to {role} ({name}): queued, delivered when its turn ends")
            return 0
        if got == STILL_TYPED:
            print(f"wz say: FAILED: the line is still in {role}'s input box after 4 Enters, unsent (cleared again); "
                  f"attach with `wz cli {role}` to look", file=sys.stderr)
            return 1
        if got == UNCONFIRMED:
            print(f"wz say: UNCONFIRMED: the line was typed into {role}'s session but its input box disappeared (a dialog or a "
                  f"restart); `wz cli {role}` to look. Not noted, so it is not sent twice.", file=sys.stderr)
            return 1
        why = "its pane shows no input box (a dialog or a loading session)"
    f = note(cfg, role, text, sender)
    _log_say(cfg, role, sender, text, "noted")
    print(f"{role} has no live session to type into ({why}): nothing was typed. Noted at the top of "
          f"{f.relative_to(cfg.root) if f.is_relative_to(cfg.root) else f}; no job was queued (`wz job add {role} \"<task>\"` starts work)")
    return 0
