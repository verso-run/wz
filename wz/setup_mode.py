"""First launch: `wz init` (or `wz cli mission-ctl` with no wz.toml) starts the lead in setup mode.

The lead interviews the user (project, workflows, repositories or stores, roles, resources, accounts, how they sign),
writes the answers file, and `wz init --answers` turns it into wz.toml, the workspace files, charters and hooks.
Then it offers the timers and runs one example job end to end. Without Claude Code, `wz init --plain` asks the same
questions at the terminal.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

from . import charters, config, packs, records
from .records import TEMPLATES
from .worker import wz_argv

ANSWERS_EXAMPLE = {
    "project": "fernhill",
    "description": "A greenhouse controller: web dashboard, controller firmware, a bench, and the paperwork.",
    "workflows": ["software", "firmware", "hardware", "admin"],
    "stores": {
        "app": {"kind": "git", "path": "../fernhill-app", "main": "main", "integration": "integration",
                "checks": ["python3 -m pytest -q"]},
        "firmware": {"kind": "git", "path": "../fernhill-fw", "main": "main", "integration": "integration",
                     "checks": ["make test"]},
        "office": {"kind": "folder", "path": "../fernhill-office"},
    },
    "roles": {},
    "resources": {"bench-psu": {"kind": "instrument", "note": "bench power supply"},
                  "board-a": {"kind": "device", "note": "controller board on the bench"}},
    "accounts": {"main": {"config_dir": "", "daily_usd": 40}},
    "budget_usd": 40,
    "sign": "pin",
    "digest_time": "08:00",
    "lead_model": "",
}


SIMPLE_EXAMPLE = {
    "project": "home-paperwork",
    "description": "Letters, forms and plans for the house.",
    "workflows": ["admin"],
    "stores": {"office": {"kind": "folder", "path": "files"}},
    "roles": {},
    "accounts": {"main": {"config_dir": "", "daily_usd": 5}},
    "budget_usd": 5,
    "permission_mode": "default",
    "job_permission_mode": "auto",
    "sign": "pin",
    "digest_time": "08:00",
}


class SetupError(Exception):
    pass


def _default_store(stores: dict, pack: str, role: str) -> str:
    if role in stores:
        return role
    want = "folder" if pack == "admin" else "git"
    for name, s in stores.items():
        if s.get("kind", "folder") == want:
            return name
    return config.WORKSPACE


PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions")
JOB_MODES = ("default", "acceptEdits", "plan", "auto", "bypassPermissions")  # background jobs: `auto` is their default


def answers_to_config(a: dict, simple: bool = False) -> dict:
    name = str(a.get("project") or "").strip()
    if not name:
        raise SetupError("the answers need a project name")
    mode = a.get("permission_mode") or config.DEFAULT_MODE
    if mode not in PERMISSION_MODES:
        raise SetupError(f"permission_mode must be one of {', '.join(PERMISSION_MODES)}")
    job_mode = a.get("job_permission_mode") or config.DEFAULT_JOB_MODE
    if job_mode not in JOB_MODES:
        raise SetupError(f"job_permission_mode must be one of {', '.join(JOB_MODES)}")
    if simple:
        if mode == "bypassPermissions" or job_mode == "bypassPermissions":
            raise SetupError("the simple setup never turns Claude Code's questions off: permission_mode and job_permission_mode "
                             "cannot be bypassPermissions")
        if a.get("budget_usd") is None:
            raise SetupError("the simple setup needs a daily spend cap (budget_usd) chosen by the person")
    workflows = [w for w in a.get("workflows", ["software"]) if w in packs.WORKFLOWS] or ["software"]
    stores = {k: dict(v) for k, v in (a.get("stores") or {}).items()}
    accounts = {k: dict(v) for k, v in (a.get("accounts") or {}).items()}
    first_acct = next(iter(accounts), "")
    roles = {k: dict(v) for k, v in (a.get("roles") or {}).items()}
    if not roles:
        for w in workflows:
            for role, pack in packs.WORKFLOWS[w].items():
                store = _default_store(stores, pack, role)
                owns = ["**"] if store != config.WORKSPACE else [f"{role}/**"]
                if pack == "tester":
                    owns = ["tests/**"] if store != config.WORKSPACE else [f"{role}/**"]
                roles[role] = {"pack": pack, "store": store, "owns": {store: owns}}
    lead = next((r for r, v in roles.items() if v.get("pack") == packs.LEAD), None)
    if lead is None:
        roles = {packs.DEFAULT_LEAD: {"pack": packs.LEAD, "store": config.WORKSPACE}, **roles}
        lead = packs.DEFAULT_LEAD
    if a.get("lead_model"):
        roles[lead]["model"] = a["lead_model"]
    for r in roles.values():
        if first_acct and not r.get("account"):
            r["account"] = first_acct
    data = {
        "project": {"name": name, "description": a.get("description", ""), "workflows": workflows,
                    "digest_time": a.get("digest_time", "08:00")},
        "agent": {"command": a.get("agent_command", "claude"), "permission_mode": mode, "job_permission_mode": job_mode,
                  "pass_effort": True},
        "owner": {"sign": a.get("sign", "pin")},
        "rings": {"order": ["dev", "prod"], "sign": ["prod"]},
        "watchdog": {"queued_hours": 6, "sign_hours": 24},
    }
    if a.get("budget_usd") is not None:
        data["budget"] = {"daily_usd": float(a["budget_usd"])}
    if stores:
        data["stores"] = stores
    if accounts:
        data["accounts"] = accounts
    if a.get("guard"):
        data["guard"] = dict(a["guard"])
    if a.get("resources"):
        data["resources"] = {k: dict(v) for k, v in a["resources"].items()}
    data["roles"] = roles
    return data


def apply(answers: dict, d: Path, force: bool = False, git_init: bool = True, simple: bool = False) -> "config.Config":
    d = Path(d).resolve()
    d.mkdir(parents=True, exist_ok=True)
    target = d / config.CONFIG_NAME
    if target.exists() and not force:
        raise SetupError(f"{target} exists; pass --force to replace it")
    data = answers_to_config(answers, simple=simple)
    text = config.dumps(data)
    probe = config.Config(target, tomllib.loads(text))
    errs = probe.validate()
    if errs:
        raise SetupError("the answers do not make a valid config:\n  " + "\n  ".join(errs))
    target.write_text("# wz config: one file for the project, its stores, roles, accounts and budgets.\n"
                      "# Edit it, then run `wz charters`.\n\n" + text)
    for name, s in data.get("stores", {}).items():
        if s.get("kind") == "folder" and simple:
            (d / s["path"]).mkdir(parents=True, exist_ok=True)
        elif s.get("kind") == "git" and not (d / s["path"]).resolve().exists():
            print(f"note: store {name} path {s['path']} does not exist yet")
    if not (d / "PLAN.md").exists():
        (d / "PLAN.md").write_text((TEMPLATES / "plan.md").read_text().replace("{project}", data["project"]["name"])
                                   .replace("{description}", data["project"].get("description", "")))
    gi = d / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if ".wz/" not in lines:
        gi.write_text("\n".join(lines + [".wz/"]) + "\n")
    cfg = config.load(target)
    records.init_files(cfg)
    if simple:
        charters.simple_marker(cfg).parent.mkdir(parents=True, exist_ok=True)
        charters.simple_marker(cfg).write_text("made with `wz init --simple`\n")
    charters.write_all(cfg)
    if git_init and shutil.which("git"):
        inside = subprocess.run(["git", "-C", str(d), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if inside.returncode != 0:
            subprocess.run(["git", "-C", str(d), "init", "-q"], check=False)
    return cfg


def interview_plain(ask=input, say=print) -> dict:
    """The setup questions at a terminal prompt, for machines without Claude Code."""
    def q(text, default=""):
        v = ask(f"{text}" + (f" [{default}]" if default else "") + ": ").strip()
        return v or default

    say("wz setup. Short answers; Enter keeps the default.")
    a: dict = {"project": q("Project name", Path.cwd().name), "description": q("One line on what it is")}
    wf = q("Workflows (any of software, firmware, hardware, admin)", "software")
    a["workflows"] = [w.strip() for w in wf.replace(",", " ").split() if w.strip()]
    a["stores"] = {}
    while True:
        name = q("A repository or store name (Enter when done)")
        if not name:
            break
        kind = q(f"  {name}: kind (git or folder)", "git")
        s = {"kind": kind, "path": q(f"  {name}: path, relative to this folder", f"../{name}")}
        if kind == "git":
            s["main"] = q(f"  {name}: main branch", "main")
            s["integration"] = q(f"  {name}: integration branch", "integration")
            checks = q(f"  {name}: check command that must pass before a merge (Enter for none)")
            s["checks"] = [checks] if checks else []
        a["stores"][name] = s
    if any(w in a["workflows"] for w in ("hardware", "firmware")):
        a["resources"] = {}
        while True:
            name = q("An instrument or device to lease (Enter when done)")
            if not name:
                break
            a["resources"][name] = {"kind": q(f"  {name}: kind", "device"), "note": q(f"  {name}: note")}
    acct = q("Claude config dir for jobs (Enter for your default login)")
    usd = q("Daily budget in USD", "40")
    a["accounts"] = {"main": {"config_dir": acct, "daily_usd": float(usd)}}
    a["budget_usd"] = float(usd)
    a["digest_time"] = q("Digest time (HH:MM)", "08:00")
    a["sign"] = "pin"
    say("You will set your signing PIN yourself with `wz sign set-pin`; no agent ever sees it.")
    return a


def setup_charter(d: Path, simple: bool = False) -> str:
    wz = " ".join(wz_argv())
    return (TEMPLATES / ("setup-simple-charter.md" if simple else "setup-charter.md")).read_text().replace("{dir}", str(d)).replace("{wz}", wz).replace(
        "{example}", json.dumps(SIMPLE_EXAMPLE if simple else ANSWERS_EXAMPLE, indent=2))


def write_setup_charter(d: Path, simple: bool = False) -> Path:
    p = Path(d).resolve() / ".wz" / "setup" / "CHARTER.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(setup_charter(Path(d).resolve(), simple))
    return p


def launch_setup(d: Path, simple: bool = False) -> int:
    """Start Claude Code as mission-ctl in setup mode in this terminal."""
    d = Path(d).resolve()
    claude = shutil.which("claude")
    if not claude:
        raise SetupError("Claude Code (`claude`) is not on PATH; install it, or run `wz init --plain`")
    p = write_setup_charter(d, simple)
    env = dict(os.environ, WZ_SETUP="1")
    env.pop("WZ_ROLE", None)
    return subprocess.call([claude, "--append-system-prompt-file", str(p),
                            "Start the wz setup interview. Ask your first question."], cwd=str(d), env=env)


EXAMPLE_TASK = ("First job (setup check): read your charter and notes, list the paths you own in each store, "
                "and confirm the store you work in exists. Write one line to your STATE.md saying setup works. "
                "Change nothing else. Declare done with the files you read as evidence.")


def example_role(cfg) -> str:
    for name in cfg.roles():
        if not cfg.is_lead(name):
            return name
    return cfg.lead()
