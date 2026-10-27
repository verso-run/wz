"""The one config file, wz.toml: project, stores, roles and what they own, rings, accounts, resources, budget.

The directory holding wz.toml is the workspace: the lead's plan, decisions, briefs, ledgers and status live there, and
wz keeps its own state under <workspace>/.wz/. Every other path in the file is relative to the workspace.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import packs, registry

CONFIG_NAME = "wz.toml"
WORKSPACE = "workspace"
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")

# The permission modes wz accepts in [agent] permission_mode (the values `claude --permission-mode` accepts). A typo or
# a value Claude Code does not know is refused on load. SAFE_MODES are the ones where Claude Code asks before it acts;
# every other mode is allowed only when it is written down, and is announced at each `wz cli` and job start.
SAFE_MODES = ("default", "plan")
OTHER_MODES = ("acceptEdits", "auto", "dontAsk", "manual", "bypassPermissions")
DEFAULT_MODE = "default"
# Background jobs (wz job add + serve, timers, --follow) have nobody to answer a prompt, so under `default` they cannot
# write. They get their own mode, `auto`, unless [agent] job_permission_mode says otherwise. `wz cli` windows keep
# [agent] permission_mode.
DEFAULT_JOB_MODE = "auto"


class ConfigError(Exception):
    pass


def locate(start: Path | None = None, *, registered: bool = True) -> tuple[Path | None, str]:
    """Where the workspace is, and how it was found: "env" ($WZ_CONFIG), "here" (a wz.toml at or above `start`, default
    the current folder), "registered" (the per-user default, see registry.py) or "" (nowhere)."""
    env = os.environ.get("WZ_CONFIG")
    if env:
        p = Path(env).expanduser()
        return (p, "env") if p.is_file() else (None, "")
    d = (start or Path.cwd()).resolve()
    for p in (d, *d.parents):
        if (p / CONFIG_NAME).is_file():
            return p / CONFIG_NAME, "here"
    if registered:
        found = registry.default()
        if found:
            return found[1], "registered"
    return None, ""


def find(start: Path | None = None, *, registered: bool = True) -> Path | None:
    """$WZ_CONFIG, else the nearest wz.toml at or above `start`, else the registered default workspace."""
    return locate(start, registered=registered)[0]


def load(path: Path | None = None) -> "Config":
    p = Path(path) if path else find()
    if not p:
        raise ConfigError(f"no {CONFIG_NAME} here or above and no workspace is registered; run `wz init` to create one")
    try:
        data = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{p}: {e}") from None
    cfg = Config(p.resolve(), data)
    errors = cfg.validate()
    if errors:
        raise ConfigError(f"{p}:\n  " + "\n  ".join(errors))
    return cfg


@dataclass
class Config:
    path: Path
    data: dict

    # ---- places -------------------------------------------------------------------------------------------------
    @property
    def root(self) -> Path:
        return self.path.parent

    @property
    def state(self) -> Path:
        return self.root / ".wz"

    @property
    def project(self) -> str:
        return self.data.get("project", {}).get("name", "project")

    def section(self, name: str) -> dict:
        v = self.data.get(name, {})
        return v if isinstance(v, dict) else {}

    def stores(self) -> dict[str, dict]:
        out = {WORKSPACE: {"kind": "folder", "path": "."}}
        for name, s in self.section("stores").items():
            out[name] = {"kind": "folder", **s}
        return out

    def store_root(self, name: str) -> Path:
        s = self.stores().get(name)
        if s is None:
            raise ConfigError(f"unknown store {name!r}")
        return (self.root / s.get("path", ".")).resolve()

    def worktree_root(self, store: str) -> Path:
        return self.state / "worktrees" / store

    def charter_path(self, role: str) -> Path:
        return self.root / "roles" / role / "CHARTER.md"

    def role_dir(self, role: str) -> Path:
        return self.root / "roles" / role

    def scratch(self, role: str) -> Path:
        return self.state / "scratch" / role

    @property
    def role_settings(self) -> Path:
        return self.state / "role-settings.json"

    # ---- roles --------------------------------------------------------------------------------------------------
    def roles(self) -> dict[str, dict]:
        out = {}
        for name, r in self.section("roles").items():
            pack = packs.PACKS.get(r.get("pack", "software"), {})
            owns = r.get("owns")
            if owns is None:
                owns = pack.get("owns", {})
            out[name] = {
                "pack": r.get("pack", "software"),
                "desc": r.get("desc") or pack.get("desc", ""),
                "effort": r.get("effort") or pack.get("effort", "high"),
                "model": r.get("model") or self.section("agent").get("default_model", ""),
                "account": r.get("account", ""),
                "store": r.get("store", WORKSPACE),
                "owns": {k: list(v) for k, v in owns.items()},
                "rules": list(pack.get("rules", [])) + list(r.get("rules", [])),
                "cap": int(r.get("cap", 1)),
                "timeout": r.get("timeout", "45m"),
                "web": r.get("web", False),
            }
        return out

    def role(self, name: str) -> dict:
        r = self.roles().get(name)
        if r is None:
            raise ConfigError(f"unknown role {name!r} (roles: {', '.join(self.roles())})")
        return r

    def lead(self) -> str:
        for name, r in self.roles().items():
            if r["pack"] == packs.LEAD:
                return name
        return packs.DEFAULT_LEAD

    def is_lead(self, role: str | None) -> bool:
        return bool(role) and role == self.lead()

    # ---- other sections -----------------------------------------------------------------------------------------
    def agent(self) -> dict:
        a = {"command": "claude", "permission_mode": DEFAULT_MODE, "job_permission_mode": DEFAULT_JOB_MODE,
             "pass_effort": True, "default_model": ""}
        a.update(self.section("agent"))
        return a

    def permission_mode(self) -> str:
        """The mode of an interactive `wz cli` session."""
        return self.agent()["permission_mode"]

    def job_permission_mode(self) -> str:
        """The mode of a background job."""
        return self.agent()["job_permission_mode"]

    def mode_notice(self, job: bool = False) -> str | None:
        """One line for the person at the keyboard (job=False) or in the job's log (job=True) when the mode is not one where
        Claude Code asks first, else None."""
        if job:
            mode = self.job_permission_mode()
            if mode in SAFE_MODES:
                return None
            return (f"wz: job permission mode is '{mode}' ([agent] job_permission_mode in {self.path}; `wz cli` sessions use "
                    f"permission_mode). {MODE_FACTS.get(mode, '')} Set job_permission_mode to \"default\" to have jobs stop at anything "
                    f"that needs a yes, which a background job cannot get, so it then cannot write.")
        mode = self.permission_mode()
        if mode in SAFE_MODES:
            return None
        return (f"wz: permission mode is '{mode}' ([agent] permission_mode in {self.path}), not 'default'. "
                f"{MODE_FACTS.get(mode, '')} Set it back to \"default\" to be asked first.")

    def account(self, name: str) -> dict:
        return self.section("accounts").get(name, {})

    def resources(self) -> dict[str, dict]:
        return self.section("resources")

    def rings(self) -> dict:
        r = {"order": ["dev", "prod"], "sign": ["prod"]}
        r.update(self.section("rings"))
        return r

    def guard(self) -> dict:
        g = {"secrets": list(DEFAULT_SECRETS), "temp": True, "allow": [], "protected_branches": []}
        g.update(self.section("guard"))
        return g

    # ---- validation ---------------------------------------------------------------------------------------------
    def validate(self) -> list[str]:
        errs = []
        if not self.section("project").get("name"):
            errs.append("[project] name is required")
        stores = self.stores()
        for name, s in stores.items():
            if s.get("kind") not in ("git", "folder"):
                errs.append(f"[stores.{name}] kind must be git or folder")
        for key, fallback in (("permission_mode", DEFAULT_MODE), ("job_permission_mode", DEFAULT_JOB_MODE)):
            mode = self.section("agent").get(key, fallback)
            if mode not in SAFE_MODES + OTHER_MODES:
                errs.append(f"[agent] {key} {mode!r} is not a mode wz supports "
                            f"(use one of: {', '.join(SAFE_MODES + OTHER_MODES)}; the safe ones are {', '.join(SAFE_MODES)})")
        roles = self.section("roles")
        if not roles:
            errs.append("no [roles.*] defined")
        leads = [n for n, r in roles.items() if r.get("pack") == packs.LEAD]
        if len(leads) != 1:
            errs.append(f"exactly one role must use pack = \"lead\" (found {len(leads)})")
        for name, r in roles.items():
            if not _NAME.match(name):
                errs.append(f"role name {name!r}: lowercase letters, digits and dashes, starting with a letter")
            if r.get("pack", "software") not in packs.PACKS:
                errs.append(f"[roles.{name}] unknown pack {r.get('pack')!r} (packs: {', '.join(packs.PACKS)})")
            if r.get("store", WORKSPACE) not in stores:
                errs.append(f"[roles.{name}] store {r.get('store')!r} is not a [stores.*] entry")
            for s in (r.get("owns") or {}):
                if s not in stores:
                    errs.append(f"[roles.{name}.owns] {s!r} is not a store")
            web = r.get("web", False)
            if not (isinstance(web, bool) or (isinstance(web, list) and all(isinstance(x, str) for x in web))):
                errs.append(f"[roles.{name}] web must be true, false, or a list of tool names such as [\"WebSearch\"]")
            acct = r.get("account")
            if acct and acct not in self.section("accounts"):
                errs.append(f"[roles.{name}] account {acct!r} is not an [accounts.*] entry")
        return errs


# What each non-default mode means for the sentences "Claude asks before it acts" and "a background job cannot ask
# permission". wz passes the mode to Claude Code unchanged; this says only what wz can stand behind.
MODE_FACTS = {
    "acceptEdits": "Claude Code accepts file edits without asking; it still asks for other actions, which a background job cannot be asked.",
    "auto": "Claude Code decides for itself what to stop and ask about; wz has not checked what that is, so do not count on being asked.",
    "dontAsk": "Claude Code does not ask; wz has not checked what it then allows, so do not count on being asked.",
    "manual": "wz has only checked the 'default' mode; do not count on 'manual' asking in the same places.",
    "bypassPermissions": "Claude Code does NOT ask before any action, and a background job runs without stopping.",
}

DEFAULT_SECRETS = [
    "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "id_rsa*", "id_ecdsa*", "id_ed25519*",
    ".env", ".env.*", ".netrc", ".pgpass", "*credentials*", "*secret*", "*.token", ".npmrc", ".pypirc",
    ".ssh/**", ".aws/**", ".gnupg/**", ".docker/config.json", ".wz/approvals/pin.json",
]


# ---- writing TOML (the standard library reads it but cannot write it) --------------------------------------------
_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if _BARE.match(k) else json.dumps(k)


def _val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def dumps(data: dict, _prefix: tuple = ()) -> str:
    """Tables of scalars, lists of scalars and nested tables; enough for wz.toml."""
    lines, subs = [], []
    for k, v in data.items():
        if isinstance(v, dict):
            subs.append((k, v))
        elif v is not None:
            lines.append(f"{_key(k)} = {_val(v)}")
    out = []
    if _prefix and (lines or not subs):
        out.append("[" + ".".join(_key(p) for p in _prefix) + "]")
    out.extend(lines)
    text = "\n".join(out)
    for k, v in subs:
        child = dumps(v, _prefix + (k,))
        text = (text + "\n\n" + child) if text else child
    return text if _prefix else text.strip() + "\n"
