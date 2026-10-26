"""Timers: systemd user units on Linux, launchd agents on macOS.

  serve     every minute     start ready jobs (quick; each job runs in its own supervisor)
  merge     every 5 minutes  integrate finished branches
  watchdog  every 10 minutes surface lost, overdue, stuck and idle work
  digest    daily            compose the owner's digest at [project] digest_time
  nightly   daily            queue the [[nightly]] jobs at [project] nightly_time (default 02:30)

`wz install timers --dry-run --root <dir>` writes the unit files under <dir> and prints the commands it would run,
without touching the machine's real timers.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

from .worker import wz_argv

JOBS = [
    ("serve", ["serve", "--quiet"], 60),
    ("merge", ["merge", "--quiet"], 300),
    ("watchdog", ["watchdog", "--quiet"], 600),
    ("digest", ["digest"], None),
    ("nightly", ["nightly"], None),
]


def platform_name() -> str:
    return "macos" if sys.platform == "darwin" else "linux"


def _slug(cfg) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", cfg.project.lower()).strip("-") or "project"


def _digest_time(cfg, name: str = "digest") -> tuple[int, int]:
    key, default = ("nightly_time", "02:30") if name == "nightly" else ("digest_time", "08:00")
    h, m = str(cfg.section("project").get(key, default)).split(":")
    return int(h), int(m)


def linux_units(cfg) -> dict[str, str]:
    slug, argv = _slug(cfg), wz_argv()
    path_env = os.environ.get("PATH", "/usr/bin:/bin")
    out = {}
    for name, args, every in JOBS:
        unit = f"wz-{slug}-{name}"
        cmd = " ".join(_sd_quote(a) for a in argv + ["--config", str(cfg.path)] + args)
        out[f"{unit}.service"] = (
            f"[Unit]\nDescription=wz {cfg.project} {name}\n\n[Service]\nType=oneshot\nWorkingDirectory={cfg.root}\n"
            f"Environment={_sd_quote('PATH=' + path_env)}\nEnvironment={_sd_quote('WZ_CONFIG=' + str(cfg.path))}\n"
            # serve starts supervisors in their own sessions; KillMode=process lets them outlive this oneshot
            f"KillMode=process\nExecStart={cmd}\n")
        if every:
            timer = f"OnBootSec=2min\nOnUnitActiveSec={every}s\n"
        else:
            h, m = _digest_time(cfg, name)
            timer = f"OnCalendar=*-*-* {h:02d}:{m:02d}:00\nPersistent=true\n"
        out[f"{unit}.timer"] = (f"[Unit]\nDescription=wz {cfg.project} {name} timer\n\n[Timer]\n{timer}\n"
                                f"[Install]\nWantedBy=timers.target\n")
    return out


def _sd_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"' if re.search(r"[\s\"'\\]", s) else s


def macos_plists(cfg) -> dict[str, bytes]:
    slug, argv = _slug(cfg), wz_argv()
    logs = cfg.state / "logs"
    out = {}
    for name, args, every in JOBS:
        label = f"org.wz.{slug}.{name}"
        d = {
            "Label": label,
            "ProgramArguments": argv + ["--config", str(cfg.path)] + args,
            "WorkingDirectory": str(cfg.root),
            "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "WZ_CONFIG": str(cfg.path)},
            "StandardOutPath": str(logs / f"timer-{name}.log"),
            "StandardErrorPath": str(logs / f"timer-{name}.log"),
            "AbandonProcessGroup": True,
        }
        if every:
            d["StartInterval"] = every
        else:
            h, m = _digest_time(cfg, name)
            d["StartCalendarInterval"] = {"Hour": h, "Minute": m}
        out[f"{label}.plist"] = plistlib.dumps(d)
    return out


def plan(cfg, platform: str | None = None, home: Path | None = None) -> tuple[dict[Path, bytes], list[list[str]]]:
    platform = platform or platform_name()
    home = Path(home) if home else Path.home()
    if platform == "linux":
        d = home / ".config" / "systemd" / "user"
        files = {d / n: s.encode() for n, s in linux_units(cfg).items()}
        cmds = [["systemctl", "--user", "daemon-reload"]]
        cmds += [["systemctl", "--user", "enable", "--now", p.name] for p in files if p.suffix == ".timer"]
    elif platform == "macos":
        d = home / "Library" / "LaunchAgents"
        files = {d / n: b for n, b in macos_plists(cfg).items()}
        uid = str(os.getuid())
        cmds = [["launchctl", "bootstrap", f"gui/{uid}", str(p)] for p in files]
    else:
        raise ValueError(f"unknown platform {platform!r} (linux or macos)")
    return files, cmds


def install(cfg, platform: str | None = None, home: Path | None = None, dry_run: bool = False, say=print) -> list[Path]:
    files, cmds = plan(cfg, platform, home)
    if dry_run and home is None:
        for p in files:
            say(f"would write {p}")
    else:
        for p, b in files.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
            say(f"wrote {p}")
    (cfg.state / "logs").mkdir(parents=True, exist_ok=True)
    for c in cmds:
        if dry_run:
            say("would run: " + " ".join(c))
        else:
            subprocess.run(c, check=False)
    return list(files)


def uninstall(cfg, platform: str | None = None, home: Path | None = None, dry_run: bool = False, say=print) -> None:
    platform = platform or platform_name()
    files, _ = plan(cfg, platform, home)
    for p in files:
        if platform == "linux" and p.suffix == ".timer":
            c = ["systemctl", "--user", "disable", "--now", p.name]
        elif platform == "macos":
            c = ["launchctl", "bootout", f"gui/{os.getuid()}", str(p)]
        else:
            c = None
        if c:
            say(("would run: " if dry_run else "") + " ".join(c))
            if not dry_run:
                subprocess.run(c, check=False)
        if not dry_run:
            p.unlink(missing_ok=True)
