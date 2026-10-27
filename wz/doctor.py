"""`wz doctor`: is this machine and this workspace ready for wz, said in plain words, with a one-line fix for each problem.

It only looks. It writes nothing (no file, no charter, no registry entry), starts no session and reads no credential: whether
Claude Code is logged in is asked of `claude auth status` itself and only its exit code is used (its output is thrown away).
Every check runs on its own, so one broken thing does not hide the others; a workspace that cannot be found or loaded is one
finding, and the checks that need no workspace (tmux, Claude, the registry) still run.

A finding is "ok", "note" (worth knowing, exit code stays 0) or "problem" (exit code 1) with an optional fix line.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from . import charters, config, light, mux, registry, sessions

OK, NOTE, PROBLEM = "ok", "note", "problem"
MIN_TMUX = (3, 0)
LOGIN_WAIT_S = 10
INSTALL_CLAUDE = "https://code.claude.com/docs/en/quickstart"
PLAIN_MODES = {"default": "Claude Code asks you before it acts", "plan": "Claude Code only plans; it changes nothing"}


class Finding:
    def __init__(self, level: str, topic: str, said: str, fix: str = ""):
        self.level, self.topic, self.said, self.fix = level, topic, said, fix


# ---- the machine ---------------------------------------------------------------------------------------------------
def check_tmux() -> list[Finding]:
    v = mux.version()
    if not v:
        return [Finding(PROBLEM, "tmux", "tmux is not installed, so a helper closes with its Terminal window and there is no hub, "
                        "no colours and no `wz list` state",
                        "install it (Mac: `brew install tmux`; Ubuntu or Debian: `sudo apt install tmux`), then run `wz doctor` again")]
    m = re.search(r"(\d+)\.(\d+)", v)
    if not m:
        return [Finding(NOTE, "tmux", f"`{v}` is installed, but wz cannot read its version number; wz needs 3.0 or newer")]
    if (int(m[1]), int(m[2])) < MIN_TMUX:
        return [Finding(PROBLEM, "tmux", f"{v} is too old (wz needs 3.0 or newer)", "update it: `brew upgrade tmux` or `sudo apt install --only-upgrade tmux`")]
    return [Finding(OK, "tmux", f"{v} is installed")]


def agent_command(cfg) -> list[str]:
    try:
        return shlex.split(cfg.agent()["command"]) if cfg else ["claude"]
    except ValueError:
        return []


def claude_dirs(cfg) -> list[tuple[str, str]]:
    """(what to call it, CLAUDE_CONFIG_DIR or '') for every Claude login the helpers will use: each account a helper names,
    and your own login when any helper names none."""
    if not cfg:
        return [("your login", os.environ.get("CLAUDE_CONFIG_DIR", ""))]
    out, own = [], False
    for _role, r in cfg.roles().items():
        acct = r.get("account")
        d = os.path.expanduser(cfg.account(acct).get("config_dir") or "") if acct else ""
        if acct and d:
            if (f"account '{acct}'", d) not in out:
                out.append((f"account '{acct}'", d))
        else:
            own = True
    if own or not out:
        out.insert(0, ("your login", os.environ.get("CLAUDE_CONFIG_DIR", "")))
    return out


def logged_in(exe: str, config_dir: str) -> bool | None:
    """True/False from `claude auth status`'s exit code (0 = signed in); None when it could not be asked. Output is discarded."""
    env = dict(os.environ)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    try:
        r = subprocess.run([exe, "auth", "status"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env=env, timeout=LOGIN_WAIT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode == 0


def check_claude(cfg) -> list[Finding]:
    base = agent_command(cfg)
    if not base:
        return [Finding(PROBLEM, "claude", "[agent] command in wz.toml is empty", "put the command that starts Claude Code there (normally `claude`)")]
    exe = shutil.which(base[0], path=os.pathsep.join(sessions._path_dirs(cfg, base[0])))
    if not exe:
        return [Finding(PROBLEM, "claude", f"`{base[0]}` (Claude Code) was not found on this computer",
                        f"install Claude Code ({INSTALL_CLAUDE}), or set [agent] command in wz.toml to where it lives")]
    out = [Finding(OK, "claude", f"`{base[0]}` is at {exe}")]
    if Path(exe).name != "claude":
        return out + [Finding(NOTE, "login", f"not checked: the agent command is `{base[0]}`, not `claude`")]
    for label, d in claude_dirs(cfg):
        state = logged_in(exe, d)
        where = f"CLAUDE_CONFIG_DIR={shlex.quote(d)} " if d else ""
        if state:
            out.append(Finding(OK, "login", f"Claude Code is signed in ({label})"))
        elif state is None:
            out.append(Finding(NOTE, "login", f"could not tell whether Claude Code is signed in ({label}): `claude auth status` gave no answer in {LOGIN_WAIT_S} s"))
        else:
            out.append(Finding(PROBLEM, "login", f"Claude Code is not signed in ({label})", f"run `{where}claude`, then type /login and finish signing in"))
    return out


# ---- the workspace -------------------------------------------------------------------------------------------------
def load_workspace(path: Path | None) -> tuple["config.Config | None", list[Finding]]:
    """The workspace and the finding about it. Looks the way every command does (WZ_CONFIG, the nearest wz.toml, the default)."""
    how = ""
    if path is None:
        path, how = config.locate()
    if path is None:
        return None, [Finding(PROBLEM, "workspace", "no workspace here: no wz.toml in this folder or above it, and none is registered",
                              "`cd` into your workspace folder, or run `wz init` to make one (`wz workspaces` lists the ones wz knows)")]
    try:
        cfg = config.load(path)
    except config.ConfigError as e:
        return None, [Finding(PROBLEM, "workspace", f"wz.toml cannot be used: {e}", f"correct {path} as the message says, then run `wz doctor` again")]
    except OSError as e:
        return None, [Finding(PROBLEM, "workspace", f"cannot read {path}: {e.strerror or e}", f"make it readable: `chmod u+r {shlex.quote(str(path))}`")]
    n = len(cfg.roles())
    out = [Finding(OK, "workspace", f"{cfg.project}: {path} ({n} helper{'s' if n != 1 else ''})" + (" - found through your default workspace" if how == "registered" else ""))]
    folder = cfg.state if cfg.state.exists() else cfg.root
    if not os.access(folder, os.W_OK | os.X_OK):
        out.append(Finding(PROBLEM, "workspace", f"wz cannot write to {folder}", f"give yourself access: `chmod u+rwx {shlex.quote(str(folder))}`"))
    return cfg, out


def check_registry() -> list[Finding]:
    p = registry.path()
    if not p.exists():
        return [Finding(OK, "workspace list", "none yet (fine while you run wz from inside the workspace folder)")]
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("workspaces", {}), dict):
            raise ValueError("not a list of workspaces")
    except (OSError, ValueError) as e:
        return [Finding(PROBLEM, "workspace list", f"{p} cannot be read ({e})",
                        f"move it away (`mv {shlex.quote(str(p))} {shlex.quote(str(p) + '.old')}`); `wz init` or `wz workspaces use` registers the workspace again")]
    ws = data.get("workspaces", {})
    gone = [n for n, f in ws.items() if not Path(str(f)).is_file()]
    out = [Finding(NOTE, "workspace list", f"'{n}' was at {ws[n]}, which is gone", f"`wz workspaces forget {n}`") for n in gone]
    default = data.get("default") or ""
    if ws and (default not in ws or default in gone):
        live = next((n for n in ws if n not in gone), "")
        out.append(Finding(NOTE, "workspace list", f"the default workspace {default!r} is not usable" if default else "no default workspace is set",
                           f"`wz workspaces use {live}`" if live else "run `wz init` in your workspace folder"))
    return out or [Finding(OK, "workspace list", f"{len(ws)} registered" + (f", default '{default}'" if default else ""))]


def check_mode(cfg) -> list[Finding]:
    mode, job = cfg.permission_mode(), cfg.job_permission_mode()
    out = [Finding(OK, "permission mode", f"windows: '{mode}': {PLAIN_MODES[mode]}")] if mode in PLAIN_MODES else [
        Finding(NOTE, "permission mode", f"windows: '{mode}' ([agent] permission_mode): {config.MODE_FACTS.get(mode, '')}",
                "to be asked first again, write permission_mode = \"default\" under [agent] in wz.toml")]
    if job in PLAIN_MODES:
        out.append(Finding(OK, "permission mode", f"background jobs: '{job}': a job cannot be asked, so it stops at anything "
                           "that needs a yes and cannot write"))
    else:
        out.append(Finding(OK if job == "auto" else NOTE, "permission mode",
                           f"background jobs: '{job}' ([agent] job_permission_mode): {config.MODE_FACTS.get(job, '')}"))
    return out


def check_hooks(cfg) -> list[Finding]:
    p = cfg.role_settings
    if not p.is_file():
        return [Finding(PROBLEM, "hooks", f"the guard and the colours are not in place: {p} does not exist", "run `wz charters`")]
    try:
        have = json.loads(p.read_text())
    except (OSError, ValueError):
        have = None
    if have != charters.hook_settings():
        return [Finding(PROBLEM, "hooks", f"{p.name} is not what this wz writes (an older wz wrote it, or wz moved); helpers started now would "
                        "miss newer hooks", "run `wz charters`, then `wz cli <helper> --restart` for a helper that is already open")]
    return [Finding(OK, "hooks", "the guard and colour hooks are in place and current")]


def check_charters(cfg) -> list[Finding]:
    missing, changed = [], []
    for role in cfg.roles():
        p = cfg.charter_path(role)
        if not p.is_file():
            missing.append(role)
        elif p.read_text() != charters.render(cfg, role):
            changed.append(role)
    out = []
    if missing:
        out.append(Finding(PROBLEM, "charters", f"no CHARTER.md yet for: {', '.join(missing)}", "run `wz charters`"))
    if changed:
        out.append(Finding(PROBLEM, "charters", f"the CHARTER.md of {', '.join(changed)} is not what wz.toml makes (edited by hand, or wz.toml changed since)",
                           "if wz.toml is right, `wz charters` rewrites them (a hand edit is lost: move it into wz.toml first)"))
    return out or [Finding(OK, "charters", "every helper's charter matches wz.toml")]


def check_lights(cfg) -> list[Finding]:
    """A light file is stale when its helper has no live window, or the pane it recorded is not in that window any more."""
    folder = sessions.state_dir(cfg)
    files = sorted(folder.glob("*.light")) if folder.is_dir() else []
    out = []
    for f in files:
        role = f.name[:-len(".light")]
        pane = light._read(str(f)).split(" ")[-1]
        name = sessions.tmux_name(cfg, role)
        live = mux.have() and sessions.running(name)
        if live and pane in mux.panes(name):
            continue
        why = "the helper is not running" if not live else "the helper's window is a different one now"
        out.append(Finding(PROBLEM, "lights", f"{role} still has a colour recorded, but {why}",
                           f"delete the file `{f}` (nothing else needs to change)"))
    return out or [Finding(OK, "lights", "no stale colours" if files else "no colours recorded")]


# ---- the report ----------------------------------------------------------------------------------------------------
def diagnose(path: Path | None = None) -> tuple[str, list[Finding]]:
    cfg, found = load_workspace(path)
    results = [check_tmux(), check_claude(cfg), found]
    results.append(check_registry())
    if cfg:
        for check in (check_mode, check_hooks, check_charters, check_lights):
            try:
                results.append(check(cfg))
            except Exception as e:                                  # one broken check must not hide the rest
                results.append([Finding(NOTE, check.__name__[len("check_"):], f"could not be checked ({type(e).__name__}: {e})")])
    return (cfg.project if cfg else ""), [x for group in results for x in group]


def render(project: str, findings: list[Finding]) -> str:
    tag = {OK: "ok     ", NOTE: "note   ", PROBLEM: "PROBLEM"}
    w = max((len(f.topic) for f in findings), default=0)
    lines = [f"wz doctor{' - ' + project if project else ''}", ""]
    for f in findings:
        lines.append(f"  {tag[f.level]}  {f.topic.ljust(w)}  {f.said}")
        if f.fix:
            lines.append(f"  {' ' * 7}  {' ' * w}  fix: {f.fix}")
    n, k = sum(f.level == PROBLEM for f in findings), sum(f.level == NOTE for f in findings)
    lines += ["", ("everything is in order" if not n and not k else f"{n} problem{'s' if n != 1 else ''}, {k} note{'s' if k != 1 else ''}") +
              ("" if not n else "; fix them in the order shown, then run `wz doctor` again")]
    return "\n".join(lines)


def run(path: Path | None = None) -> int:
    project, findings = diagnose(path)
    print(render(project, findings))
    return 1 if any(f.level == PROBLEM for f in findings) else 0
