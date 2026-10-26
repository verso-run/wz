"""The feature flag inventory: every flag registered, default off, checked in CI (`wz flags check`).

The registry is a TOML file ([release] flag_registry, default flags.toml in the workspace), one table per flag:

  [flag.export_csv]
  owner = "app"
  default = false
  why = "CSV export on the history page"
  # release_default = true, decision = "D-14"   <- only a recorded decision may ship a flag on

[release] flag_sources lists globs (relative to the workspace) to search, and flag_pattern a regex whose first group
is a flag name as the code uses it (default: flag("name") or flag('name')). The check fails when the code uses a flag
the registry lacks, or a registered flag defaults on without a release_default and a decision row naming it.
A registered flag the code no longer uses is a warning: delete it once the code is gone.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

DEFAULT_PATTERN = r"""flag\(\s*["']([A-Za-z0-9_.-]+)["']"""


def registry_path(cfg) -> Path:
    return cfg.root / cfg.section("release").get("flag_registry", "flags.toml")


def load_registry(cfg) -> dict:
    p = registry_path(cfg)
    if not p.is_file():
        return {}
    return tomllib.loads(p.read_text()).get("flag", {})


def used_flags(cfg) -> dict[str, list[str]]:
    rel = cfg.section("release")
    rx = re.compile(rel.get("flag_pattern", DEFAULT_PATTERN))
    out: dict[str, list[str]] = {}
    for g in rel.get("flag_sources", []):
        for p in sorted(cfg.root.glob(g)):
            if not p.is_file():
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for m in rx.finditer(line):
                    out.setdefault(m.group(1), []).append(f"{p.relative_to(cfg.root)}:{n}")
    return out


def check(cfg) -> tuple[list[str], list[str]]:
    """(errors, warnings)."""
    reg, used = load_registry(cfg), used_flags(cfg)
    decisions = (cfg.root / "DECISIONS.md").read_text() if (cfg.root / "DECISIONS.md").exists() else ""
    errors, warnings = [], []
    for name, where in sorted(used.items()):
        if name not in reg:
            errors.append(f"{name}: used at {where[0]} but not registered in {registry_path(cfg).name}")
    for name, f in sorted(reg.items()):
        if not f.get("owner"):
            errors.append(f"{name}: no owner")
        if f.get("default", False) is not False:
            if not f.get("release_default"):
                errors.append(f"{name}: defaults on; new behaviour ships off unless a decision names it the release default")
            elif not (f.get("decision") and re.search(rf"^\| {re.escape(str(f['decision']))} \|", decisions, re.M)):
                errors.append(f"{name}: release_default needs decision = \"D-n\" naming a row in DECISIONS.md")
        if name not in used:
            warnings.append(f"{name}: registered but not used in the sources; remove it once the code is gone")
    return errors, warnings
