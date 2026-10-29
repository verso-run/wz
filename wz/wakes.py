"""Scheduled wakes: a session that must speak at a set time is woken by wz, not by a timer the session made for itself.

A wake is declared in wz.toml, approved once by the owner, and run by the wake timer (`wz wake tick`, every minute):

    [[wake]]
    id    = "lead-digest"          # lowercase letters, digits, dashes; unique
    role  = "mission-ctl"          # whose session is woken (the lead, usually)
    at    = "07:15"                # local time
    days  = ["mon", "tue", "wed", "thu", "fri"]    # optional; every day when omitted
    text  = "Compose the daily digest and send the owner the three asks."
    start = false                  # optional: bring the session up first when it is not running
    late  = "3h"                   # optional: a wake found later than this after its time is MISSED, not fired

Approval is a sign (wz/approvals.py): `wz wake request` files one request per declaration, the owner signs it with the PIN
(`wz sign approve <id>`), and a wake runs only while a sign exists for the digest of its CURRENT declaration. Changing the
role, time, days, text or start in wz.toml makes the old sign stop matching, and the wake waits for a new one. A role
cannot sign, so it cannot grant itself a wake. The firing is one line typed into the session (the same delivery as
`wz say`), recorded in `.wz/wakes.json` and as an event; the wake timer needs no resident process.

One occurrence is handled once: fired, or missed (the machine was off or the timer stopped past `late`), never both.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from . import approvals, escalate, flags
from .util import iso, now, parse_duration, parse_iso, read_json, write_json

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_AT = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DEFAULT_LATE = "3h"
KEYS = {"id", "role", "at", "days", "text", "start", "late"}


def declared(cfg) -> list[dict]:
    """The wakes as written, normalised (days always a list, start a bool, late in seconds)."""
    out = []
    for w in cfg.data.get("wake", []) or []:
        if not isinstance(w, dict):
            continue
        out.append({"id": str(w.get("id", "")), "role": str(w.get("role", "")), "at": str(w.get("at", "")),
                    "days": [str(d).lower() for d in (w.get("days") or DAYS)], "text": str(w.get("text", "")).strip(),
                    "start": bool(w.get("start", False)), "late": str(w.get("late", DEFAULT_LATE))})
    return out


def problems(cfg) -> list[str]:
    errs, seen = [], set()
    raw = cfg.data.get("wake", [])
    if raw and not isinstance(raw, list):
        return ["[[wake]] must be an array of tables"]
    for i, w in enumerate(raw or [], 1):
        if not isinstance(w, dict):
            errs.append(f"[[wake]] #{i} is not a table")
            continue
        wid = w.get("id", "")
        name = f"[[wake]] {wid or '#' + str(i)}"
        for k in w:
            if k not in KEYS:
                errs.append(f"{name}: {k!r} is not a setting (use {', '.join(sorted(KEYS))})")
        if not isinstance(wid, str) or not _ID.match(wid):
            errs.append(f"{name}: id must be lowercase letters, digits and dashes, starting with a letter")
        elif wid in seen:
            errs.append(f"{name}: id appears twice")
        seen.add(wid)
        if w.get("role") not in cfg.roles():
            errs.append(f"{name}: role {w.get('role')!r} is not a [roles.*] entry")
        if not _AT.match(str(w.get("at", ""))):
            errs.append(f"{name}: at must be a local time like \"07:15\"")
        days = w.get("days", list(DAYS))
        if not (isinstance(days, list) and days and all(str(d).lower() in DAYS for d in days)):
            errs.append(f"{name}: days must be a list of {', '.join(DAYS)}")
        if not str(w.get("text", "")).strip():
            errs.append(f"{name}: text is required (the line typed into the session)")
        try:
            parse_duration(w.get("late", DEFAULT_LATE))
        except ValueError as e:
            errs.append(f"{name}: late: {e}")
    return errs


def wake_digest(w: dict) -> str:
    body = {k: w[k] for k in ("id", "role", "at", "days", "text", "start")}
    body["days"] = sorted(body["days"], key=DAYS.index)
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


# ---- approval ------------------------------------------------------------------------------------------------------
def _requests(cfg, w: dict) -> list[dict]:
    wd = wake_digest(w)
    return [r for r in approvals.all_requests(cfg) if (r.get("action") or {}).get("type") == "wake"
            and r["action"].get("wake_digest") == wd and r["action"].get("id") == w["id"]]


def approval(cfg, w: dict) -> str:
    """'approved' (a sign for this exact declaration), 'pending' (asked, not signed), 'denied' or 'none' (never asked)."""
    return _approval(cfg, w)[0]


def _approval(cfg, w: dict) -> tuple[str, float]:
    """(state, the time of the sign when approved). An occurrence before the sign is not owed: a wake is not 'missed' for
    a time that passed while it was still waiting for the owner."""
    state = "none"
    for r in _requests(cfg, w):
        if r["status"] in ("signed", "done"):
            rec = read_json(approvals._d(cfg) / "signed" / f"{r['id']}.json") or {}
            if rec.get("digest") == approvals.digest(r) == r.get("digest"):
                return "approved", parse_iso(rec.get("at")) or 0.0
        elif r["status"] == "denied":
            state = "denied" if state == "none" else state
        else:
            state = "pending"
    return state, 0.0


def request(cfg, w: dict) -> dict | None:
    """Ask the owner to approve this declaration, once: nothing is filed if a request for it is pending, signed or denied."""
    if _requests(cfg, w):
        return None
    action = {"type": "wake", "id": w["id"], "wake_digest": wake_digest(w), "role": w["role"], "at": w["at"],
              "days": w["days"], "text": w["text"], "start": w["start"]}
    when = "every day" if len(w["days"]) == 7 else "on " + ", ".join(w["days"])
    return approvals.request(cfg, f"Approve wake {w['id']}: wz types \"{w['text'][:100]}\" into {w['role']} at {w['at']} {when}",
                             action=action, why="a scheduled wake is run by wz itself; it needs the owner's sign once", by="wz")


def request_missing(cfg) -> list[str]:
    return [r["id"] for w in declared(cfg) if approval(cfg, w) == "none" and (r := request(cfg, w))]


# ---- when -----------------------------------------------------------------------------------------------------------
def last_occurrence(w: dict, t: float) -> float | None:
    """The most recent scheduled time at or before `t` on one of the wake's days (looking back a week), local time."""
    h, m = (int(x) for x in w["at"].split(":"))
    now_d = dt.datetime.fromtimestamp(t)
    for back in range(8):
        d = now_d.date() - dt.timedelta(days=back)
        if DAYS[d.weekday()] not in w["days"]:
            continue
        occ = dt.datetime.combine(d, dt.time(h, m)).timestamp()
        if occ <= t:
            return occ
    return None


def next_occurrence(w: dict, t: float) -> float | None:
    h, m = (int(x) for x in w["at"].split(":"))
    d0 = dt.datetime.fromtimestamp(t).date()
    for ahead in range(8):
        d = d0 + dt.timedelta(days=ahead)
        occ = dt.datetime.combine(d, dt.time(h, m)).timestamp()
        if DAYS[d.weekday()] in w["days"] and occ > t:
            return occ
    return None


def _state(cfg) -> dict:
    return read_json(cfg.state / "wakes.json") or {}


# ---- run ------------------------------------------------------------------------------------------------------------
def tick(cfg, t: float | None = None, tell_=None, dry_run: bool = False) -> list[dict]:
    """Fire each approved wake whose latest occurrence is due and unhandled; mark one found past `late` as missed.
    Returns [{id, role, at, outcome}], outcome 'said' / 'queued' / 'noted' / 'failed: ...' / 'missed' / 'unapproved'."""
    t = now() if t is None else t
    tell_ = tell_ or escalate.tell
    st = _state(cfg)
    out = []
    for w in declared(cfg):
        occ = last_occurrence(w, t)
        if occ is None or st.get(w["id"], {}).get("occurrence", 0) >= occ:
            continue
        ap, signed_t = _approval(cfg, w)
        if ap != "approved":
            if not dry_run and ap == "none":
                request(cfg, w)
            out.append({"id": w["id"], "role": w["role"], "at": iso(occ), "outcome": "unapproved"})
            continue
        if occ < signed_t:                                     # it passed before the owner signed: not owed, not missed
            continue
        late = t - occ > parse_duration(w["late"])
        if dry_run:
            out.append({"id": w["id"], "role": w["role"], "at": iso(occ), "outcome": "missed" if late else "due"})
            continue
        if late:
            outcome = "missed"
            flags.event(cfg, "wz", "wake-missed", w["id"], f"{w['id']} for {w['role']} was due {iso(occ)} and found {int((t - occ) / 60)} min late; not fired")
            escalate.raise_(cfg, f"wake {w['id']} ({w['role']} at {w['at']}) was missed: due {iso(occ)}, found {int((t - occ) / 60)} min late "
                                 "(the machine was off, or the wake timer is not running: `wz doctor`)",
                            sev="P2", subject=w["role"], ref=w["id"], by="wz", key=f"wake-missed:{w['id']}:{int(occ)}", t=t)
        else:
            outcome = tell_(cfg, w["role"], f"[wz wake {w['id']}] {w['text']}", start=w["start"])
            flags.event(cfg, "wz", "wake", w["id"], f"{w['id']} -> {w['role']}: {outcome}")
        st[w["id"]] = {"occurrence": occ, "at": iso(t), "outcome": outcome}
        write_json(cfg.state / "wakes.json", st)
        out.append({"id": w["id"], "role": w["role"], "at": iso(occ), "outcome": outcome})
    return out


def table(cfg, t: float | None = None) -> list[dict]:
    t = now() if t is None else t
    st = _state(cfg)
    rows = []
    for w in declared(cfg):
        nxt = next_occurrence(w, t)
        last = st.get(w["id"], {})
        rows.append({"id": w["id"], "role": w["role"], "at": w["at"], "days": "daily" if len(w["days"]) == 7 else ",".join(w["days"]),
                     "approval": approval(cfg, w), "next": iso(nxt) if nxt else "-",
                     "last": f"{last.get('outcome')} {last.get('at')}" if last else "-"})
    return rows


# ---- watchdog -------------------------------------------------------------------------------------------------------
def alerts(cfg, t: float | None = None) -> list[dict]:
    """WAKE alerts for the watchdog: a lead with a session and no approved wake, a declared wake nobody signed, a missed one."""
    from . import sessions
    t = now() if t is None else t
    out, ws = [], declared(cfg)
    st = _state(cfg)
    approved_roles = set()
    for w in ws:
        ap, signed_t = _approval(cfg, w)
        if ap == "approved":
            approved_roles.add(w["role"])
            occ = last_occurrence(w, t)
            if occ is not None and occ >= signed_t and st.get(w["id"], {}).get("occurrence", 0) < occ and t - occ > parse_duration(w["late"]):
                out.append({"kind": "WAKE", "ref": w["id"], "role": w["role"],
                            "text": f"missed: due {iso(occ)} and never fired (is the wake timer installed? `wz install timers`)"})
        elif ap == "denied":
            out.append({"kind": "WAKE", "ref": w["id"], "role": w["role"], "text": "the owner denied this wake; it will not run"})
        else:
            out.append({"kind": "WAKE", "ref": w["id"], "role": w["role"],
                        "text": "declared but not approved; waits for the owner's sign (`wz sign list`)"})
    lead = cfg.lead()
    if lead in cfg.roles() and lead not in approved_roles and sessions.load(cfg, lead)["launched"]:
        out.append({"kind": "WAKE", "ref": lead, "role": lead,
                    "text": "the lead has no approved wake: it speaks only when someone opens it. Declare a [[wake]] "
                            "(for example at 07:15), `wz wake request`, and sign it"})
    return out
