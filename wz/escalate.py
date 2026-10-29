"""Escalation: a blocker climbs by severity, from the role to the lead to the owner, and the push rules live here, once.

  P2  the role itself: its own session gets one line (or a note at the top of its STATE.md when it has none live)
  P1  the lead: the same, to the lead
  P0  the owner: one push through the channel in [escalation] push, repeated no faster than push_gap, at most push_max times

A blocker starts at the severity its raiser gives it. If nobody acknowledges it, it rises one level each time `stale_p2` / `stale_p1`
passes at its level (4 h and 1 h by default); P0 does not rise, it repeats. An escalation is never delivered to the agent it is
about: a P1 about the lead goes straight to the owner, because the lead is the one that cannot be asked to fix itself.
A role may raise P2 and P1; P0 is raised by the lead, the owner or the watchdog, and only the owner acknowledges a P0.

    [escalation]
    push = "/path/to/script"      # run with the text on stdin and WZ_PUSH_ID, WZ_PUSH_SEV, WZ_PUSH_TITLE in the environment;
                                  # no shell, so the text is never parsed. Empty: nothing is pushed and the digest says so.
    push_gap = "1h"
    push_max = 3
    stale_p2 = "4h"
    stale_p1 = "1h"

State: .wz/escalations/<id>.json, one file per blocker. Every delivery is also an event (`wz next`).
"""
from __future__ import annotations

import os
import shlex
import subprocess

from . import flags, sessions
from .util import iso, locked, now, parse_duration, read_json, read_jsonl, write_json

SEVERITIES = ("P0", "P1", "P2")
DEFAULTS = {"push": "", "push_gap": "1h", "push_max": 3, "stale_p2": "4h", "stale_p1": "1h"}


class EscalationError(Exception):
    pass


def rules(cfg) -> dict:
    """The push rules, parsed. The only place they are read."""
    r = {**DEFAULTS, **cfg.section("escalation")}
    return {"push": str(r["push"]).strip(), "push_gap": parse_duration(r["push_gap"]), "push_max": int(r["push_max"]),
            "stale": {"P2": parse_duration(r["stale_p2"]), "P1": parse_duration(r["stale_p1"])}}


def problems(cfg) -> list[str]:
    errs = []
    sec = cfg.section("escalation")
    for k in sec:
        if k not in DEFAULTS:
            errs.append(f"[escalation] {k!r} is not a setting (use {', '.join(DEFAULTS)})")
    try:
        rules(cfg)
    except (ValueError, TypeError) as e:
        errs.append(f"[escalation] {e}")
    return errs


def _dir(cfg):
    return cfg.state / "escalations"


def _path(cfg, eid: str):
    return _dir(cfg) / f"{eid}.json"


def get(cfg, eid: str) -> dict:
    e = read_json(_path(cfg, eid))
    if not isinstance(e, dict):
        raise EscalationError(f"no escalation {eid}")
    return e


def all_escalations(cfg) -> list[dict]:
    d = _dir(cfg)
    out = []
    if d.is_dir():
        for f in sorted(d.glob("esc-*.json")):
            e = read_json(f)
            if isinstance(e, dict):
                out.append(e)
    return out


def open_ones(cfg) -> list[dict]:
    return [e for e in all_escalations(cfg) if e["state"] == "open"]


# ---- delivery ------------------------------------------------------------------------------------------------------
def tell(cfg, role: str, line: str, start: bool = False) -> str:
    """One line to a role's session: 'said', 'queued', 'noted' (no live session: it is at the top of the role's STATE.md) or
    'failed: <why>'. `start`: bring the session up first when it is not running."""
    try:
        live, _ = sessions._live(cfg, role)
        if not live and start and sessions.have_tmux():
            try:
                sessions.ensure(cfg, role, wait=sessions._wait_s())
            except sessions.SessionError as e:
                return f"failed: {e}"
            live, _ = sessions._live(cfg, role)
        if not live:
            sessions.note(cfg, role, line)
            return "noted"
        before = len(read_jsonl(cfg.state / "say.jsonl"))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = sessions.say(cfg, role, line)
        said = read_jsonl(cfg.state / "say.jsonl")[before:]
        outcome = said[-1]["outcome"] if said else ""
        if rc != 0:
            return f"failed: {outcome or 'the line was not delivered'}"
        return {"submitted": "said", "queued": "queued", "noted": "noted"}.get(outcome, "said")
    except Exception as e:  # a watchdog must not die on one dead window
        return f"failed: {e.__class__.__name__}: {e}"


def push(cfg, esc: dict) -> str:
    cmd = rules(cfg)["push"]
    if not cmd:
        return "no push channel: [escalation] push is empty"
    title = f"{cfg.project} {esc['sev']}: {esc['text'][:80]}"
    env = {**os.environ, "WZ_PUSH_ID": esc["id"], "WZ_PUSH_SEV": esc["sev"], "WZ_PUSH_TITLE": title}
    try:
        p = subprocess.run(shlex.split(cmd), input=f"{title}\n\n{esc['text']}\n", text=True, capture_output=True, env=env,
                           cwd=str(cfg.root), timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"push failed: {e.__class__.__name__}: {e}"
    return "pushed" if p.returncode == 0 else f"push failed: exit {p.returncode} {p.stderr.strip()[-120:]}"


def recipient(cfg, esc: dict) -> str:
    """Who this severity reaches for this subject: a role name, or 'owner'. Never the subject itself above P2."""
    sev, subject, lead = esc["sev"], esc.get("subject", ""), cfg.lead()
    if sev == "P2":
        return subject if subject in cfg.roles() else lead
    if sev == "P1":
        return "owner" if subject == lead else lead
    return "owner"


def _deliver(cfg, esc: dict, t: float, tell_=None, push_=None) -> None:
    tell_, push_ = tell_ or tell, push_ or push
    who = recipient(cfg, esc)
    if who == "owner":
        if esc["sev"] != "P0":
            esc["sev"] = "P0"                                   # P1 about the lead: the owner is the only one above it
            esc.setdefault("trail", []).append({"at": iso(t), "note": "the lead is the subject, so it goes to the owner"})
        r = rules(cfg)
        if esc["pushes"] >= r["push_max"] or (esc["pushes"] and t - esc["last_push_t"] < r["push_gap"]):
            return
        outcome = push_(cfg, esc)
        esc["pushes"] += 1
        esc["last_push_t"] = t
    else:
        line = f"[wz {esc['sev']} {esc['id']}] {esc['text']}"
        outcome = tell_(cfg, who, line)
    esc["level_t"] = esc.get("level_t") or t
    esc.setdefault("trail", []).append({"at": iso(t), "sev": esc["sev"], "to": who, "outcome": outcome})
    flags.event(cfg, "wz", "escalation", esc["id"], f"{esc['sev']} to {who}: {esc['text']} ({outcome})", sev=esc["sev"], to=who)


def raise_(cfg, text: str, sev: str = "P2", subject: str = "", ref: str = "", by: str = "", key: str = "",
           t: float | None = None, tell_=None, push_=None) -> dict:
    """Open a blocker (or return the open one with the same key) and deliver it at its severity."""
    t = now() if t is None else t
    if sev not in SEVERITIES:
        raise EscalationError(f"severity is one of {', '.join(SEVERITIES)}, not {sev!r}")
    if not text.strip():
        raise EscalationError("an escalation needs the words of the blocker")
    if subject and subject not in cfg.roles():
        raise EscalationError(f"unknown role {subject!r}")
    if by and by != "wz" and not cfg.is_lead(by) and sev == "P0":
        raise EscalationError("a role may raise P2 or P1; P0 pushes the owner and is raised by the lead, the owner or the watchdog")
    with locked(_dir(cfg) / "seq.lock"):
        if key:
            for e in open_ones(cfg):
                if e.get("key") == key:
                    return e
        seq = (read_json(_dir(cfg) / "seq.json") or {"next": 1})["next"]
        write_json(_dir(cfg) / "seq.json", {"next": seq + 1})
        esc = {"id": f"esc-{seq:04d}", "key": key, "sev": sev, "sev0": sev, "subject": subject, "ref": ref, "text": text.strip(),
               "by": by or os.environ.get("WZ_ROLE", "owner"), "created": iso(t), "created_t": t, "level_t": t, "state": "open",
               "pushes": 0, "last_push_t": 0.0, "trail": []}
        _deliver(cfg, esc, t, tell_, push_)
        write_json(_path(cfg, esc["id"]), esc)
    return esc


def tick(cfg, t: float | None = None, tell_=None, push_=None) -> list[dict]:
    """Rise or repeat what nobody has acknowledged. Returns the escalations that moved."""
    t = now() if t is None else t
    r = rules(cfg)
    moved = []
    for esc in open_ones(cfg):
        with locked(_dir(cfg) / "seq.lock"):
            esc = get(cfg, esc["id"])
            if esc["state"] != "open":
                continue
            before = (esc["sev"], esc["pushes"])
            stale = r["stale"].get(esc["sev"])
            if stale and t - esc["level_t"] >= stale:
                esc["sev"] = SEVERITIES[SEVERITIES.index(esc["sev"]) - 1]
                esc["level_t"] = t
                esc.setdefault("trail", []).append({"at": iso(t), "note": f"not acknowledged for {stale // 60} min: rises to {esc['sev']}"})
                _deliver(cfg, esc, t, tell_, push_)
            elif esc["sev"] == "P0":
                _deliver(cfg, esc, t, tell_, push_)
            if (esc["sev"], esc["pushes"]) != before:
                write_json(_path(cfg, esc["id"]), esc)
                moved.append(esc)
    return moved


# ---- acknowledge, resolve ------------------------------------------------------------------------------------------
def ack(cfg, eid: str, by: str = "", note: str = "", env=None) -> dict:
    env = os.environ if env is None else env
    role = env.get("WZ_ROLE", "")
    esc = get(cfg, eid)
    if esc["state"] != "open":
        raise EscalationError(f"{eid} is already {esc['state']}")
    if esc["sev"] == "P0" and role:
        raise EscalationError("a P0 is acknowledged by the owner, from the owner's own shell; it cannot be done inside a role session")
    if role and not cfg.is_lead(role):
        raise EscalationError(f"a role cannot acknowledge an escalation; the lead ({cfg.lead()}) or the owner does")
    esc.update(state="acked", acked=iso(), acked_by=by or role or "owner", ack_note=note)
    write_json(_path(cfg, eid), esc)
    flags.event(cfg, esc["acked_by"], "escalation-ack", eid, note or esc["text"])
    return esc


def resolve(cfg, key: str, why: str = "cleared") -> list[str]:
    """Close the open escalation(s) with this key: the condition went away by itself (the watchdog calls this)."""
    done = []
    for esc in open_ones(cfg):
        if esc.get("key") == key:
            esc.update(state="resolved", resolved=iso(), resolved_why=why)
            write_json(_path(cfg, esc["id"]), esc)
            flags.event(cfg, "wz", "escalation-resolved", esc["id"], why)
            done.append(esc["id"])
    return done


def owner_asks(cfg) -> list[dict]:
    """What the digest puts first: open escalations that are (now) P0."""
    return [e for e in open_ones(cfg) if e["sev"] == "P0"]
