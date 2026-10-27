"""The per-user list of workspaces, so `wz cli <role>` works from any folder.

`wz init` records the workspace in <config dir>/wz/workspaces.json (the config dir is $XDG_CONFIG_HOME, else ~/.config):

    {"default": "fernhill", "workspaces": {"fernhill": "~/wz-work/wz.toml", ...}}

A workspace is named after its project. `config.find` falls back to the default when no wz.toml is at or above the
current folder; `--ws NAME` picks another. Nothing here is secret and nothing is read by a role's own session: a role
always has $WZ_CONFIG.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import util


class RegistryError(Exception):
    pass


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "wz" / "workspaces.json"


def load() -> dict:
    data = util.read_json(path(), {}) or {}
    ws = data.get("workspaces")
    return {"default": data.get("default") or "", "workspaces": dict(ws) if isinstance(ws, dict) else {}}


def _save(data: dict) -> None:
    util.write_json(path(), data)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "workspace"


def names() -> list[str]:
    return list(load()["workspaces"])


def lookup(name: str) -> Path:
    reg = load()
    p = reg["workspaces"].get(name)
    if p is None:
        have = ", ".join(reg["workspaces"]) or "none"
        raise RegistryError(f"no workspace called {name!r} (registered: {have}); `wz workspaces` lists them")
    if not Path(p).is_file():
        raise RegistryError(f"workspace {name!r} was at {p}, which is gone; `wz workspaces forget {name}` removes it")
    return Path(p)


def default() -> tuple[str, Path] | None:
    """The default workspace as (name, wz.toml path), or None when none is registered or its file is gone."""
    reg = load()
    name = reg["default"]
    if name not in reg["workspaces"]:
        name = next((n for n, p in reg["workspaces"].items() if Path(p).is_file()), "")
    p = reg["workspaces"].get(name)
    if p and Path(p).is_file():
        return name, Path(p)
    return None


def name_of(config_path: Path) -> str | None:
    target = str(Path(config_path).resolve())
    for n, p in load()["workspaces"].items():
        if p == target:
            return n
    return None


def register(config_path: Path, project: str, *, make_default: bool | None = None) -> tuple[str, bool]:
    """Record a workspace. Returns (its name, whether it is now the default). The first workspace is the default;
    a later one is not unless `make_default` says so (`wz init` passes True: you just made it)."""
    target = str(Path(config_path).resolve())
    reg = load()
    name = name_of(config_path)
    if name is None:
        base = _slug(project)
        name, n = base, 1
        while name in reg["workspaces"] and Path(reg["workspaces"][name]).is_file():
            n += 1
            name = f"{base}-{n}"
        reg["workspaces"][name] = target
    first = not reg["default"] or reg["default"] not in reg["workspaces"] or not Path(reg["workspaces"][reg["default"]]).is_file()
    if make_default or (make_default is None and first):
        reg["default"] = name
    _save(reg)
    return name, reg["default"] == name


def use(name: str) -> None:
    lookup(name)
    reg = load()
    reg["default"] = name
    _save(reg)


def forget(name: str) -> None:
    reg = load()
    if name not in reg["workspaces"]:
        raise RegistryError(f"no workspace called {name!r}")
    del reg["workspaces"][name]
    if reg["default"] == name:
        reg["default"] = next(iter(reg["workspaces"]), "")
    _save(reg)
