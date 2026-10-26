"""Resource leases: bench instruments, devices, test phones, a remote GPU — anything only one job may use at a time.

Resources are declared in wz.toml under [resources.<name>]. A lease is an exclusive flock on
.wz/leases/<name>.lock held by the process that took it, so it ends when that process ends, however it ends.
The lock file itself names the holder (job, pid, since, expires) for `wz lease list`.

Rules a lease enforces:
  never stolen   nothing in wz breaks another holder's lock; a waiter waits or gives up
  expires        `max_hold` (per resource) bounds a `wz lease run`: the command is stopped and the lease released
                 at expiry; a job's lease ends with the job (its timeout); a lease held past its expiry is a
                 watchdog alert, never a takeover
  protected      `protected = true` (an owner's own device): no lease is ever granted, and the guard refuses any
                 shell command that names one of its `ids`
  inherited      a job's own commands see WZ_LEASES_HELD and WZ_LEASE_HOLDER and use the job's leases instead of
                 waiting on their parent
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time

from .util import iso, now, parse_duration, pid_alive, read_json, try_lock, write_json

HELD_ENV = "WZ_LEASES_HELD"
HOLDER_ENV = "WZ_LEASE_HOLDER"


class LeaseError(Exception):
    pass


def _dir(cfg):
    return cfg.state / "leases"


def check_names(cfg, names) -> None:
    unknown = [n for n in names if n not in cfg.resources()]
    if unknown:
        raise LeaseError(f"unknown resource(s) {', '.join(unknown)}; declare them under [resources.*] in wz.toml")
    prot = [n for n in names if cfg.resources()[n].get("protected")]
    if prot:
        raise LeaseError(f"{', '.join(prot)} is protected (the owner's own device); no job may lease or drive it")


def max_hold(cfg, name: str) -> int | None:
    v = cfg.resources().get(name, {}).get("max_hold")
    return parse_duration(v) if v else None


def _holder_file(cfg, name: str):
    return _dir(cfg) / f"{name}.json"


def acquire(cfg, names, holder: str, hold_s: float | None = None) -> list[int] | None:
    """All of `names` or none. Returns the fds to keep open while the lease is held, or None if any is taken.

    The expiry written beside each lock is the shorter of `hold_s` (the caller's own bound, e.g. a job's timeout)
    and the resource's max_hold."""
    check_names(cfg, names)
    fds, taken = [], []
    for n in sorted(set(names)):
        fd = try_lock(_dir(cfg) / f"{n}.lock")
        if fd is None:
            for f, m in zip(fds, taken):
                _holder_file(cfg, m).unlink(missing_ok=True)
                os.close(f)
            return None
        fds.append(fd)
        taken.append(n)
        bounds = [b for b in (hold_s, max_hold(cfg, n)) if b]
        t = now()
        rec = {"resource": n, "holder": holder, "pid": os.getpid(), "since": iso(t), "since_t": t,
               "expires_t": (t + min(bounds)) if bounds else None, "expires": iso(t + min(bounds)) if bounds else ""}
        write_json(_holder_file(cfg, n), rec)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{holder} pid={os.getpid()} since={rec['since']} expires={rec['expires'] or '-'}\n".encode(), 0)
    return fds


def release(cfg, names, fds) -> None:
    for n in names:
        rec = read_json(_holder_file(cfg, n)) or {}
        if rec.get("pid") in (None, os.getpid()):
            _holder_file(cfg, n).unlink(missing_ok=True)
    for f in fds or []:
        try:
            os.close(f)
        except OSError:
            pass


def is_free(cfg, name: str) -> bool:
    fd = try_lock(_dir(cfg) / f"{name}.lock")
    if fd is None:
        return False
    os.close(fd)
    return True


def holder(cfg, name: str) -> dict:
    """Who holds `name` now ({} when free or the holder file is stale)."""
    if is_free(cfg, name):
        return {}
    info = read_json(_holder_file(cfg, name)) or {}
    return info if pid_alive(info.get("pid")) else {}


def inherited(cfg, names, job: str | None = None, env=None) -> list[str]:
    """The subset of `names` this process may use because its job already holds them (WZ_LEASES_HELD)."""
    env = os.environ if env is None else env
    held = {x for x in env.get(HELD_ENV, "").split(",") if x}
    job = job or env.get(HOLDER_ENV) or env.get("WZ_JOB")
    out = []
    for n in names:
        if n in held and job and holder(cfg, n).get("holder") == job:
            out.append(n)
    return out


def overdue(cfg, t: float | None = None) -> list[dict]:
    t = now() if t is None else t
    out = []
    for name in cfg.resources():
        h = holder(cfg, name)
        if h.get("expires_t") and t > h["expires_t"]:
            out.append(h)
    return out


def table(cfg) -> list[dict]:
    rows = []
    for name, r in cfg.resources().items():
        free = is_free(cfg, name)
        info = {} if free else holder(cfg, name)
        rows.append({"resource": name, "kind": r.get("kind", ""), "free": "protected" if r.get("protected") else free,
                     "holder": info.get("holder", "" if free else "?"), "since": info.get("since", ""),
                     "expires": info.get("expires", "")})
    return rows


def run_with(cfg, names, argv: list[str], holder: str, wait_s: float = 0) -> int:
    """`wz lease run <res> -- cmd`: hold the lease for the life of one command, never past the resource's max_hold.

    At expiry the command's own process group gets SIGTERM, then SIGKILL, and the lease is released (exit 124)."""
    reuse = inherited(cfg, names)
    need = [n for n in names if n not in reuse]
    deadline = now() + wait_s
    while True:
        fds = acquire(cfg, need, holder) if need else []
        if fds is not None or now() >= deadline:
            break
        time.sleep(min(1.0, max(0.05, deadline - now())))
    if fds is None:
        raise LeaseError(f"{', '.join(need)} is leased by someone else; see `wz lease list` (leases are never taken over)")
    bounds = [b for b in (max_hold(cfg, n) for n in names) if b]
    try:
        env = dict(os.environ, **{HELD_ENV: ",".join(sorted(set(names) | set(os.environ.get(HELD_ENV, "").split(",")) - {""}))})
        if need:
            env[HOLDER_ENV] = holder
        proc = subprocess.Popen(argv, start_new_session=True, env=env)
        try:
            return proc.wait(timeout=min(bounds) if bounds else None)
        except subprocess.TimeoutExpired:
            for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
                try:
                    os.killpg(proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    proc.wait(timeout=grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
            return 124
    finally:
        release(cfg, need, fds)


def command_names_protected(cfg, command: str) -> str | None:
    """The protected resource whose ids appear in a shell command (the guard refuses it), else None."""
    for name, r in cfg.resources().items():
        if not r.get("protected"):
            continue
        for ident in [str(x) for x in r.get("ids", [])]:
            if ident and re.search(rf"(?<![A-Za-z0-9_-]){re.escape(ident)}(?![A-Za-z0-9_-])", command):
                return name
    return None

