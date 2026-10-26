"""Commit unlocks. A role may commit, tag or push only while it holds an unlock.

A job carries its own unlock (written when the job starts, removed when it ends), so a job's commits on its own
branch need no word. A chat session gets one from the lead: `wz unlock <role> [--hours N]`.
"""
from __future__ import annotations

from .util import now, read_json, write_json


def path(cfg, role: str):
    return cfg.state / "unlocks" / f"{role}.json"


def grant(cfg, role: str, job: str | None = None, hours: float = 4.0, by: str = "") -> dict:
    rec = {"role": role, "job": job, "until": now() + hours * 3600, "by": by}
    write_json(path(cfg, role), rec)
    return rec


def has(cfg, role: str, job: str | None = None) -> bool:
    rec = read_json(path(cfg, role))
    if not isinstance(rec, dict) or rec.get("until", 0) < now():
        return False
    return rec.get("job") in (None, job)


def revoke(cfg, role: str, job: str | None = None) -> bool:
    """Remove the role's unlock; when `job` is given only if that job holds it."""
    p = path(cfg, role)
    rec = read_json(p)
    if not isinstance(rec, dict):
        return False
    if job is not None and rec.get("job") != job:
        return False
    p.unlink(missing_ok=True)
    return True
