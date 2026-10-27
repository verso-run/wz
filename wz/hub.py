"""`wz hub`: one terminal with a tab per live role.

The hub is a tmux session of its own, `wzhub-<project>`, whose windows are the roles' own windows *linked* in (tmux
`link-window`): there is no second tmux client and no second prefix key, and a window option set on the role's window (the
lights, rung 2) shows in the role's own status bar and in its tab here. Nothing is copied: `wz hub kill` unlinks the tabs
(closes the hub session) and every role keeps running; `wz park` kills the role's window, which also removes its tab.

Tabs: the roles that have a tmux session and are not parked, the lead first and the rest in wz.toml order, minus the
roles hidden with `wz hub hide <role>` (kept in `.wz/hub.json`), at most MAX_TABS. Tab N is window index N (1..9), so
Ctrl-b N is the Nth role. Index 0 is only a placeholder that holds the hub open while it has no tabs.

A second terminal gets a grouped session (`wzhub-<project>-2`, `-3`, ...): the same tabs, its own current tab, removed
by tmux when its terminal closes (`destroy-unattached`). `wz hub` reattaches the primary hub when no client is on it.

`.wz/hub.log` has one line per build, reattach, hide/show, kill and ended attach.
"""
from __future__ import annotations

import os
import re
import shlex
import time
from datetime import datetime

from . import mux, sessions, timers, util

MAX_TABS = 9
BASE = 1                                    # window index of the first tab; index 0 is the placeholder
PLACEHOLDER_TEXT = "wz hub: no role has a live session yet. Start one with: wz cli <role>"


class HubError(Exception):
    pass


# ---- names, state, log ---------------------------------------------------------------------------------------------
def hub_name(cfg, n: int = 1) -> str:
    """`wzhub-` and not `wz-`: a role called hub must not collide with the hub of the same project."""
    return f"wzhub-{timers._slug(cfg)}" + (f"-{n}" if n > 1 else "")


def _state_file(cfg):
    return cfg.state / "hub.json"


def hidden(cfg) -> list[str]:
    h = util.read_json(_state_file(cfg), {}) or {}
    return [r for r in h.get("hidden", []) if isinstance(r, str)]


def _save_hidden(cfg, roles: list[str]) -> None:
    util.write_json(_state_file(cfg), {"hidden": roles})


def log(cfg, event: str, detail: str = "") -> None:
    try:
        cfg.state.mkdir(parents=True, exist_ok=True)
        with open(cfg.state / "hub.log", "a") as f:
            f.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')}  {event}  {detail}\n")
    except OSError:
        pass


def _mine(cfg, listing: list[dict]) -> list[dict]:
    """The hub sessions of this workspace, primary first. The owner marker decides, not the name: project `a-2` and the
    second hub of project `a` would otherwise look alike."""
    base = hub_name(cfg)
    pat = re.compile(re.escape(base) + r"(-(\d+))?$")
    found = []
    for s in listing:
        m = pat.match(s["name"])
        if m and s["root"] == str(cfg.root):
            found.append((int(m.group(2) or 1), s))
    return [s for _, s in sorted(found, key=lambda x: x[0])]


def in_hub(cfg) -> str:
    """The name of this workspace's hub session this process is running in, or ''."""
    if not os.environ.get("TMUX"):
        return ""
    cur = mux.current_session()
    return cur if cur and any(h["name"] == cur for h in _mine(cfg, mux.list_sessions())) else ""


# ---- what the tabs should be ---------------------------------------------------------------------------------------
def order(cfg) -> list[str]:
    lead = cfg.lead()
    roles = list(cfg.roles())
    return ([lead] if lead in roles else []) + [r for r in roles if r != lead]


def wanted(cfg, sess: list[dict], wins: list[dict]) -> tuple[list[dict], list[str]]:
    """[{role, session, window, name}] for the tabs, in order, and the roles that were live but did not fit (cap)."""
    live = {s["name"] for s in sess if s["root"] in ("", str(cfg.root))}
    skip = set(hidden(cfg))
    own: dict[str, dict] = {}
    for w in sorted(wins, key=lambda w: w["index"]):
        own.setdefault(w["session"], w)
    tabs, extra = [], []
    for role in order(cfg):
        name = sessions.tmux_name(cfg, role)
        if role in skip or name not in live or sessions.load(cfg, role)["parked"] or name not in own:
            continue
        (tabs if len(tabs) < MAX_TABS else extra).append({"role": role, "session": name, "window": own[name]["id"], "name": own[name]["name"]})
    return tabs, extra


def _style(cfg, name: str, *, secondary: bool, then: tuple = ()) -> None:
    """Session options only (window options are shared with the roles' own sessions and are not touched here), in one tmux call;
    `then` is another command to run in the same call."""
    cmds = [("set-option", "-t", f"={name}:", "@wz_root", str(cfg.root)),
            ("set-option", "-t", f"={name}:", "base-index", str(BASE)),
            ("set-option", "-t", f"={name}:", "renumber-windows", "off"),         # tab N stays window N while sync works by index
            ("set-option", "-t", f"={name}:", "status-left", f" wz {cfg.project} "),
            ("set-option", "-t", f"={name}:", "status-left-length", "40"),
            ("set-option", "-t", f"={name}:", "status-left-style", "bg=colour238,fg=colour255,bold")]
    if secondary:                                    # tmux would destroy the session at once if this were set before a client arrives
        for hook in ("client-attached", "client-session-changed"):
            cmds.append(("set-hook", "-t", f"={name}:", hook, f"set-option -t ={name}: destroy-unattached on"))
    cmds += [c for c in then]
    args: list[str] = []
    for c in cmds:
        args += (list(c) if not args else [";", *c])
    mux.run(*args)


def _hub_tabs(wins: list[dict], hub: str) -> list[dict]:
    return sorted((w for w in wins if w["session"] == hub and not w["hub"]), key=lambda w: w["index"])


def sync(cfg, hub: str, sess: list[dict] | None = None, wins: list[dict] | None = None) -> dict:
    """Make the hub's tabs the wanted ones, touching nothing that is already right. Returns what changed."""
    sess = mux.list_sessions() if sess is None else sess
    wins = mux.list_windows() if wins is None else wins
    tabs, extra = wanted(cfg, sess, wins)
    have = _hub_tabs(wins, hub)
    placeholder = [w for w in wins if w["session"] == hub and w["hub"]]
    active = next((w["id"] for w in wins if w["session"] == hub and w["active"]), "")
    k = 0
    while k < len(tabs) and k < len(have) and have[k]["id"] == tabs[k]["window"] and have[k]["index"] == BASE + k:
        k += 1
    changed = {"added": [t["role"] for t in tabs[k:]], "removed": len(have) - k, "extra": [t["role"] for t in extra]}
    if (not tabs or have[k:]) and not placeholder:      # a session with no window left is destroyed: hold it open while tabs move
        mux.run("new-window", "-d", "-t", f"={hub}:0", "-n", "wz", "sh", "-c", f"printf '%s\\n' {shlex.quote(PLACEHOLDER_TEXT)}; exec sleep 31536000")
        mux.run("set-option", "-w", "-t", f"={hub}:0", "@wz_hub", "1")
    for w in have[k:]:
        mux.run("unlink-window", "-t", f"={hub}:{w['index']}")        # never -k: tmux refuses if this is the window's last link
    for p, t in enumerate(tabs[k:], start=k):
        if t["name"] != t["role"]:
            mux.run("rename-window", "-t", f"={t['session']}:", t["role"])
        r = mux.run("link-window", "-d", "-s", f"={t['session']}:", "-t", f"={hub}:{BASE + p}")
        if r.returncode != 0:
            changed["added"].remove(t["role"])
    if tabs and (placeholder or have[k:]):
        mux.run("kill-window", "-t", f"={hub}:0")
    if tabs and (not have or changed["removed"] or changed["added"]):
        keep = next((i for i, t in enumerate(tabs) if t["window"] == active), 0)
        mux.run("select-window", "-t", f"={hub}:{BASE + keep}")
    return changed


# ---- open ----------------------------------------------------------------------------------------------------------
def prepare(cfg) -> tuple[str, str]:
    """Make a hub ready for one more terminal and say which session it should attach to: ('<name>', 'build'|'reattach'|'second').
    All the tmux work is here; attaching is the caller's."""
    if not mux.have():
        raise HubError("tmux is not installed, and the hub is made of tmux windows")
    t0, n0 = time.monotonic(), len(mux.calls())
    sess, wins = mux.list_sessions(), mux.list_windows()
    mine = _mine(cfg, sess)
    primary = hub_name(cfg)
    for h in [h for h in mine if h["name"] != primary and h["attached"] == 0]:       # a spare view whose terminal went away
        mux.run("kill-session", "-t", f"={h['name']}")
        mine.remove(h)
    if not mine and any(s["name"] == primary for s in sess):
        raise HubError(f"a tmux session called {primary} already belongs to another wz workspace; give this project a different name "
                       "in wz.toml ([project] name)")
    if not mine:
        first = mux.run("new-session", "-d", "-P", "-F", "#{window_index}", "-s", primary, "-n", "wz", "-x", "200", "-y", "50",
                        "sh", "-c", f"printf '%s\\n' {shlex.quote(PLACEHOLDER_TEXT)}; exec sleep 31536000")
        if first.returncode != 0:
            raise HubError(f"tmux could not start {primary}: {(first.stderr or first.stdout).strip()}")
        at = first.stdout.strip()
        hold = [("set-option", "-w", "-t", f"={primary}:{at}", "@wz_hub", "1")]
        if at != "0":                                # a tmux.conf with base-index 1 puts the first window at 1, where tab 1 goes
            hold.append(("move-window", "-s", f"={primary}:{at}", "-t", f"={primary}:0"))
        _style(cfg, primary, secondary=False, then=tuple(hold))
        wins = wins + [{"session": primary, "index": 0, "id": "", "name": "wz", "active": True, "hub": True}]
        how, target = "build", primary
    else:
        free = [h for h in mine if h["attached"] == 0]
        if free:
            how, target = "reattach", free[0]["name"]
        else:
            used = {h["name"] for h in mine}
            n = next(i for i in range(2, 100) if hub_name(cfg, i) not in used)
            target = hub_name(cfg, n)
            r = mux.run("new-session", "-d", "-t", f"={mine[0]['name']}", "-s", target)
            if r.returncode != 0:
                raise HubError(f"tmux could not start a second hub window group: {(r.stderr or r.stdout).strip()}")
            _style(cfg, target, secondary=True)
            how = "second"
    ch = sync(cfg, mine[0]["name"] if mine else primary, sess, wins)
    dt = time.monotonic() - t0
    tabs = len(wanted(cfg, sess, wins)[0])
    log(cfg, how, f"{target}: {tabs} tabs ({len(ch['added'])} linked, {ch['removed']} unlinked), {len(mux.calls()) - n0} tmux calls, {dt:.2f} s")
    if ch["extra"]:
        print(f"wz hub: only {MAX_TABS} tabs; not shown: {', '.join(ch['extra'])} (`wz hub hide <role>` makes room)")
    return target, how


def open_hub(cfg) -> int:
    """`wz hub`."""
    inside = in_hub(cfg)
    if inside:
        ch = sync(cfg, inside)
        log(cfg, "inside", f"already in {inside}; {len(ch['added'])} linked, {ch['removed']} unlinked")
        print(f"wz hub: you are in the hub already ({inside}); its tabs are up to date. Ctrl-b then a number picks a role.")
        return 0
    target, how = prepare(cfg)
    if os.environ.get("TMUX"):
        r = mux.switch_client(target)
        if r.returncode != 0:
            print(f"wz hub: could not switch this tmux client ({r.stderr.strip()}); to go there: tmux switch-client -t {target}")
            return 1
        return 0
    rc = mux.attach(target)
    left = _mine(cfg, mux.list_sessions())
    log(cfg, "attach-ended", f"{target} rc={rc}; hub {'still up' if left else 'gone'}")
    return rc


def kill(cfg) -> int:
    """`wz hub kill`: close the hub (every terminal on it); the roles keep running."""
    mine = _mine(cfg, mux.list_sessions())
    if not mine:
        print("wz hub: no hub is running")
        return 0
    for h in reversed(mine):
        mux.run("kill-session", "-t", f"={h['name']}")
    sess = mux.list_sessions()
    alive = [r for r in order(cfg) if sessions.tmux_name(cfg, r) in {s["name"] for s in sess}]
    log(cfg, "kill", f"{len(mine)} hub session(s) closed; {len(alive)} role session(s) still up")
    print(f"closed the hub ({len(mine)} session{'s' if len(mine) != 1 else ''}); the roles keep running"
          + (f": {', '.join(alive)}" if alive else ""))
    return 0


def _resync(cfg) -> None:
    sess = mux.list_sessions()
    mine = _mine(cfg, sess)
    if mine:
        sync(cfg, mine[0]["name"], sess)


def relink(cfg) -> None:
    """After a role starts, restarts or parks: bring a live hub's tabs up to date. No hub, one tmux call. Never raises."""
    try:
        _resync(cfg)
    except Exception:
        pass


def hide(cfg, role: str) -> int:
    cfg.role(role)
    h = hidden(cfg)
    if role not in h:
        _save_hidden(cfg, h + [role])
    log(cfg, "hide", role)
    _resync(cfg)
    print(f"{role} is hidden from the hub (it keeps running; `wz hub show {role}` brings the tab back)")
    return 0


def show(cfg, role: str) -> int:
    cfg.role(role)
    h = hidden(cfg)
    _save_hidden(cfg, [r for r in h if r != role])
    log(cfg, "show", role)
    _resync(cfg)
    name = sessions.tmux_name(cfg, role)
    if not (mux.have() and sessions.running(name)):
        print(f"{role} is no longer hidden, but it has no live session: it gets a tab once `wz cli {role}` has started it")
    else:
        print(f"{role} shows in the hub")
    return 0


def focus(cfg, role: str) -> bool:
    """Inside the hub, `wz cli <role>` goes to the role's tab instead of leaving the hub. False when the role has no tab."""
    hub = in_hub(cfg)
    if not hub:
        return False
    name = sessions.tmux_name(cfg, role)
    wins = mux.list_windows()
    mine = {w["id"] for w in wins if w["session"] == name}
    for w in _hub_tabs(wins, hub):
        if w["id"] in mine:
            return mux.run("select-window", "-t", f"={hub}:{w['index']}").returncode == 0
    return False
