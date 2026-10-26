"""Hand-steps: the physical actions only a person can do (plug, swap, charge, move a probe), asked for in a file.

An agent that needs one writes a hand-step (`wz hand ask`): what to do, on which resource, why, and the safety limits
that apply. The step is a file under hands/ in the workspace (readable from a phone or a pull request), it raises an
event the lead's `wz next` and the watchdog surface, and the agent waits on it (`wz hand wait`) until a person marks
it done or refused. Agents never mark their own hand-steps done.

Hazardous hardware (a resource with `hazard = true`, e.g. a battery cell, mains, a heater) is attended only: while
[bench.safety] attended_only is true (the default), nothing may act on it unless a person has declared they are at
the bench (`wz hand attend --minutes 90`), and an attendance ends at its expiry. Readings are checked against the
limits in [bench.safety.limits]; a reading outside them stops the run (see bench.py).
"""
from __future__ import annotations

import os
import re
import time

from . import flags
from .util import iso, locked, now, parse_duration, read_json, write_json

STATUSES = ("waiting", "done", "refused", "expired")


class HandError(Exception):
    pass


def _dir(cfg):
    return cfg.root / "hands"


def _attend_path(cfg):
    return cfg.state / "attended.json"


def safety(cfg) -> dict:
    s = {"attended_only": True, "limits": {}}
    s.update(cfg.section("bench").get("safety", {}) or {})
    return s


def person_only(env=None) -> None:
    env = os.environ if env is None else env
    if env.get("WZ_ROLE"):
        raise HandError("only a person at the bench answers a hand-step or declares attendance; agents never do")


# ---- attendance -----------------------------------------------------------------------------------------------------
def attend(cfg, who: str, minutes: float, env=None) -> dict:
    person_only(env)
    if minutes <= 0 or minutes > 12 * 60:
        raise HandError("attendance is between 1 minute and 12 hours")
    t = now()
    rec = {"who": who, "since": iso(t), "until_t": t + minutes * 60, "until": iso(t + minutes * 60)}
    write_json(_attend_path(cfg), rec)
    flags.event(cfg, "owner", "attend", who, f"at the bench until {rec['until']}")
    return rec


def leave(cfg) -> None:
    person_only()
    _attend_path(cfg).unlink(missing_ok=True)
    flags.event(cfg, "owner", "attend", "", "left the bench")


def attended(cfg, t: float | None = None) -> dict | None:
    rec = read_json(_attend_path(cfg))
    t = now() if t is None else t
    if isinstance(rec, dict) and rec.get("until_t", 0) > t:
        return rec
    return None


def require_attended(cfg, resources: list[str], what: str) -> None:
    """Refuse to act on hazardous resources while nobody is at the bench."""
    haz = [n for n in resources if cfg.resources().get(n, {}).get("hazard")]
    if haz and safety(cfg).get("attended_only", True) and not attended(cfg):
        raise HandError(f"{what} touches hazardous {', '.join(haz)}; nobody is attending "
                        "(a person runs `wz hand attend --minutes N` at the bench first). Agents never act on it unattended.")


# ---- the steps ------------------------------------------------------------------------------------------------------
def _next_id(cfg) -> str:
    nums = [int(m.group(1)) for p in _dir(cfg).glob("hand-*.json") if (m := re.match(r"hand-(\d+)\.json$", p.name))]
    return f"hand-{max(nums, default=0) + 1:04d}"


def _render(rec: dict) -> str:
    lines = [f"# {rec['id']}: {rec['text']}", "",
             f"- asked by: {rec['by']}" + (f" (job {rec['job']})" if rec.get("job") else ""),
             f"- at: {rec['asked']}", f"- resource: {rec.get('resource') or '-'}",
             f"- hazardous: {'yes: attended only' if rec.get('hazard') else 'no'}",
             f"- waits until: {rec.get('expires') or 'answered'}", f"- status: **{rec['status']}**"]
    if rec.get("why"):
        lines += ["", "Why: " + rec["why"]]
    if rec.get("limits"):
        lines += ["", "Limits that apply:"] + [f"- {k}: {v[0]} to {v[1]}" for k, v in rec["limits"].items()]
    lines += ["", "Answer at the bench: `wz hand done " + rec["id"] + " --note \"...\"` or `wz hand refuse " + rec["id"] + "`."]
    if rec.get("answered"):
        lines += ["", f"Answered {rec['answered']} by {rec.get('answered_by', '')}: {rec.get('note', '')}"]
    return "\n".join(lines) + "\n"


def save(cfg, rec: dict) -> None:
    write_json(_dir(cfg) / f"{rec['id']}.json", rec)
    (_dir(cfg) / f"{rec['id']}.md").write_text(_render(rec))


def ask(cfg, text: str, by: str = "", job: str | None = None, resource: str | None = None, why: str = "",
        timeout="2h") -> dict:
    if not text.strip():
        raise HandError("a hand-step says what the person must do")
    if resource and resource not in cfg.resources():
        raise HandError(f"unknown resource {resource!r}")
    r = cfg.resources().get(resource or "", {})
    with locked(cfg.state / "hands.lock"):
        t = now()
        to = parse_duration(timeout)
        rec = {"id": _next_id(cfg), "text": text.strip(), "by": by or os.environ.get("WZ_ROLE", "owner"),
               "job": job or os.environ.get("WZ_JOB"), "resource": resource, "why": why, "hazard": bool(r.get("hazard")),
               "limits": safety(cfg).get("limits", {}) if r.get("hazard") else {}, "status": "waiting",
               "asked": iso(t), "asked_t": t, "expires_t": t + to, "expires": iso(t + to)}
        save(cfg, rec)
    flags.event(cfg, rec["by"], "hand", rec["id"], f"{text.strip()}" + (" [hazard: attended only]" if rec["hazard"] else ""))
    return rec


def get(cfg, hid: str) -> dict:
    rec = read_json(_dir(cfg) / f"{hid}.json")
    if not isinstance(rec, dict):
        raise HandError(f"no hand-step {hid}")
    if rec["status"] == "waiting" and rec.get("expires_t") and now() > rec["expires_t"]:
        rec["status"] = "expired"
        save(cfg, rec)
    return rec


def answer(cfg, hid: str, status: str, who: str, note: str = "", env=None) -> dict:
    person_only(env)
    if status not in ("done", "refused"):
        raise HandError("answer done or refused")
    with locked(cfg.state / "hands.lock"):
        rec = get(cfg, hid)
        if rec["status"] != "waiting":
            raise HandError(f"{hid} is {rec['status']}")
        if status == "done" and rec.get("hazard") and safety(cfg).get("attended_only", True) and not attended(cfg):
            raise HandError(f"{hid} is on hazardous hardware: declare attendance first (`wz hand attend`)")
        rec.update(status=status, answered=iso(), answered_by=who, note=note)
        save(cfg, rec)
    flags.event(cfg, "owner", "hand", hid, f"{status}: {note}")
    return rec


def wait(cfg, hid: str, poll_s: float = 2.0, timeout_s: float | None = None) -> dict:
    """Block until the step is answered or expires. Returns the record (status done, refused or expired)."""
    end = None if timeout_s is None else now() + timeout_s
    while True:
        rec = get(cfg, hid)
        if rec["status"] != "waiting":
            return rec
        if end is not None and now() >= end:
            return rec
        time.sleep(poll_s)


def waiting(cfg) -> list[dict]:
    out = []
    for p in sorted(_dir(cfg).glob("hand-*.json")):
        try:
            rec = get(cfg, p.stem)
        except HandError:
            continue
        if rec["status"] == "waiting":
            out.append(rec)
    return out


def all_steps(cfg) -> list[dict]:
    return [get(cfg, p.stem) for p in sorted(_dir(cfg).glob("hand-*.json"))]


# ---- limits ---------------------------------------------------------------------------------------------------------
def out_of_limits(cfg, readings: dict, extra: dict | None = None) -> list[str]:
    """Readings named in [bench.safety.limits] (or `extra`) that fall outside their [low, high]."""
    limits = {**(safety(cfg).get("limits") or {}), **(extra or {})}
    bad = []
    for name, v in readings.items():
        if name in limits and isinstance(v, (int, float)):
            lo, hi = limits[name]
            if not (float(lo) <= float(v) <= float(hi)):
                bad.append(f"{name} = {v} outside {lo}..{hi}")
    return bad
