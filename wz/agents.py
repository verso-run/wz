"""One status per agent: working, idle, stalled or zombie, from a beat and from progress, with a nudge or a handoff.

An agent is a role's chat session (a tmux window running Claude) or a running background job.

  working   alive and making progress
  idle      a session that is up and waiting at its input box (a job is never idle: it is working or it is not)
  stalled   alive, but nothing has moved: a turn open with no tool call for `stall_minutes`; a session waiting on a person
            (login, question, permission) for as long; a job with no output for `job_stall_minutes`; a job that has used
            `warn_at` of its time limit and written no report
  zombie    should be alive and is not, or is there twice: Claude ended and its window is a shell; two windows run one role;
            a job whose supervisor is gone; a role running more jobs than its cap; a job that hit its time limit and left no report

Beat: every hook of a role's session touches `.wz/sessions/<role>.beat` (wz/light.py). Progress: the light the hooks
set, the pane (wz/sessions.py:classify), a job's output log (worker.activity) and the report events a job writes.

What happens to a stalled or zombie agent, in `tick` (the watchdog timer runs it):
  nudge     a stalled session gets a line typed into it, up to `nudges` times, `nudge_minutes` apart
  handoff   a P1 escalation (wz/escalate.py) to the lead: at once for a zombie or a stalled job, after the last nudge for a
            session. For the lead itself the handoff goes to the owner, since the lead cannot be asked to fix itself.
An escalation is closed again when the agent is back to working or idle. Nothing is killed, restarted or cancelled here.

    [watchdog]
    stall_minutes = 45        # a session's open turn / question with no sign of life
    job_stall_minutes = 20    # a running job's output log not growing
    nudge_minutes = 15
    nudges = 2
    warn_at = 0.9             # fraction of a job's time limit after which "no report yet" is a stall
    agent_window_hours = 24   # how long a dead job is listed
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import escalate, flags, hub, jobs, mux, sessions, worker
from .util import iso, now, pid_alive, read_json, write_json

STATUSES = ("working", "idle", "stalled", "zombie")
GRACE_S = 300
DEFAULTS = {"stall_minutes": 45, "job_stall_minutes": 20, "nudge_minutes": 15, "nudges": 2, "warn_at": 0.9, "agent_window_hours": 24}
SETTINGS = set(DEFAULTS)


def settings(cfg) -> dict:
    s = {**DEFAULTS, **{k: v for k, v in cfg.section("watchdog").items() if k in SETTINGS}}
    return {"stall_s": float(s["stall_minutes"]) * 60, "job_stall_s": float(s["job_stall_minutes"]) * 60,
            "nudge_s": float(s["nudge_minutes"]) * 60, "nudges": int(s["nudges"]), "warn_at": float(s["warn_at"]),
            "window_s": float(s["agent_window_hours"]) * 3600}


# ---- what is observed -------------------------------------------------------------------------------------------------
@dataclass
class Seen:
    """What was observed of one role's chat session."""
    windows: list = field(default_factory=list)       # tmux window ids that run this role (a linked hub tab is the same id)
    exited: bool = False                              # the launch script saw Claude end
    kind: str = "busy"                                # sessions.classify of the pane
    beat_age: float | None = None                     # seconds since the last hook; None = no beat file (older hooks)
    light: str = ""                                   # work | ask | done | '' (the light file)


class TmuxProbe:
    """The real observer: tmux plus the files the hooks keep."""

    def windows(self, cfg) -> dict[str, list[str]]:
        if not mux.have():
            return {}
        ours = {s["name"] for s in mux.list_sessions() if s["root"] == str(cfg.root)
                or (not s["root"] and any(s["name"] == sessions.tmux_name(cfg, r) for r in cfg.roles()))}
        found: dict[str, list[str]] = {}
        for w in mux.list_windows():
            if w["session"] in ours and w["name"] in cfg.roles() and not w["hub"] and w["id"] not in found.setdefault(w["name"], []):
                found[w["name"]].append(w["id"])
        return found

    def pane_kind(self, cfg, role: str) -> str:
        return sessions.classify(sessions.capture(sessions.tmux_name(cfg, role)))


def _beat_age(cfg, role: str, t: float) -> float | None:
    try:
        return max(0.0, t - (sessions.state_dir(cfg) / f"{role}.beat").stat().st_mtime)
    except OSError:
        return None


def observe(cfg, t: float, probe=None) -> dict[str, Seen]:
    probe = probe or TmuxProbe()
    wins = probe.windows(cfg)
    out = {}
    for role in cfg.roles():
        ids = wins.get(role, [])
        if not ids:
            continue
        from . import light
        out[role] = Seen(windows=ids, exited=sessions._exited(cfg, role), kind=probe.pane_kind(cfg, role),
                         beat_age=_beat_age(cfg, role, t), light=light.current(str(cfg.root), role))
    return out


# ---- the judgement (pure) -----------------------------------------------------------------------------------------------
def judge_session(s: Seen, th: dict, waiting_s: float = 0.0) -> tuple[str, str]:
    """(status, reason) for one session. `waiting_s`: how long the pane has already shown a question or login that needs a person."""
    if len(s.windows) > 1:
        return "zombie", f"duplicate: {len(s.windows)} windows run this role ({', '.join(s.windows)}); one of them is stale"
    if s.exited or s.kind == "shell":
        return "zombie", "Claude ended; the window is a plain shell (`wz cli <role> --restart`)"
    if s.kind in ("login", "dialog", "resume_picker"):
        what = {"login": "a login screen", "dialog": "a question", "resume_picker": "the conversation picker"}[s.kind]
        if waiting_s >= th["stall_s"]:
            return "stalled", f"at {what} for {int(waiting_s / 60)} min; it needs a person"
        return "working", f"at {what}, {int(waiting_s / 60)} min"
    stale = s.beat_age is not None and s.beat_age >= th["stall_s"]
    if s.light in ("work", "ask"):          # Claude's input box is on screen mid-turn too, so the light says what the pane cannot
        if stale:
            what = "waiting on a person" if s.light == "ask" else "a turn open"
            return "stalled", f"{what}, no sign of life for {int(s.beat_age / 60)} min"
        return "working", ("asking a person" if s.light == "ask" else "turn in progress") + \
            ("" if s.beat_age is None else f", last sign of life {int(s.beat_age)} s ago")
    if s.kind == "busy" and not s.light:    # no light file (older hooks, or the pane shows no input box): only the beat is left
        if stale:
            return "stalled", f"no input box and no sign of life for {int(s.beat_age / 60)} min"
        return "working", "no input box on screen; state unknown"
    return "idle", "at the input box"


def judge_job(cfg, j: dict, t: float, th: dict, reported: set, running_by_role: dict) -> tuple[str, str] | None:
    """(status, reason) for a job, or None when it is not an agent to show (finished, or dead for a known reason)."""
    if j["status"] == "running":
        sup, claimed = j.get("supervisor_pid"), j.get("claimed")
        if not sup:
            from .util import parse_iso
            c = parse_iso(claimed)
            if c is not None and t - c > GRACE_S:
                return "zombie", "claimed but its supervisor never started"
            return "working", "starting"
        if not pid_alive(sup):
            return "zombie", "its supervisor process is gone"
        role_jobs = running_by_role.get(j["role"], [])
        cap = int(cfg.role(j["role"])["cap"]) if j["role"] in cfg.roles() else 1
        if len(role_jobs) > cap and j["id"] in [x["id"] for x in role_jobs[cap:]]:
            return "zombie", f"duplicate: {len(role_jobs)} {j['role']} jobs run, the cap is {cap}"
        started = j.get("started_t") or t
        elapsed = t - started
        limit = j["timeout_s"]
        if j["id"] not in reported and elapsed >= limit * th["warn_at"]:
            return "stalled", f"{int(elapsed / 60)} of {limit // 60} min used and no report written"
        age, _size = worker.activity(cfg, j)
        quiet = age if age is not None else elapsed
        if quiet >= th["job_stall_s"]:
            return "stalled", f"no output for {int(quiet / 60)} min"
        return "working", f"{int(elapsed / 60)} of {limit // 60} min used, last output {int(quiet)} s ago" if age is not None else \
            f"{int(elapsed / 60)} of {limit // 60} min used, no output yet"
    if (j["status"] == "failed" and j.get("timed_out") and j["id"] not in reported and not j.get("reminted_as")
            and t - j.get("finished_t", 0) <= th["window_s"]):
        return "zombie", f"hit its {j['timeout_s'] // 60} min limit and left no report (`wz job remint {j['id']}`)"
    return None


def reports_by_job(cfg) -> set:
    return {e.get("job") for e in flags.events(cfg) if e.get("kind") == "report" and e.get("job")}


def table(cfg, t: float | None = None, probe=None, every: list | None = None) -> list[dict]:
    """Every agent with its status and why: [{key, kind, role, status, reason, since}]. Read-only."""
    t = now() if t is None else t
    th = settings(cfg)
    prev = (read_json(cfg.state / "agents.json") or {}).get("agents", {})
    every = jobs.all_jobs(cfg) if every is None else every
    rows = []
    seen = observe(cfg, t, probe)
    for role, s in seen.items():
        key = f"session:{role}"
        raw = s.kind if s.kind in ("login", "dialog", "resume_picker") else ""
        waiting = 0.0
        if raw and prev.get(key, {}).get("raw") == raw:
            waiting = t - prev[key].get("raw_since", t)
        status, reason = judge_session(s, th, waiting)
        rows.append({"key": key, "kind": "session", "role": role, "status": status, "reason": reason, "raw": raw})
    reported = reports_by_job(cfg)
    running: dict[str, list] = {}
    for j in sorted((j for j in every if j["status"] == "running"), key=lambda j: j.get("started_t") or 0):
        running.setdefault(j["role"], []).append(j)
    for j in every:
        v = judge_job(cfg, j, t, th, reported, running)
        if v:
            rows.append({"key": f"job:{j['id']}", "kind": "job", "role": j["role"], "status": v[0], "reason": v[1], "raw": ""})
    for r in rows:
        p = prev.get(r["key"], {})
        r["since"] = p.get("since", t) if p.get("status") == r["status"] else t
        if r["raw"]:
            r["raw_since"] = p.get("raw_since", t) if p.get("raw") == r["raw"] else t
    return rows


# ---- acting ---------------------------------------------------------------------------------------------------------------
def tick(cfg, t: float | None = None, probe=None, every: list | None = None, tell_=None, push_=None) -> list[dict]:
    """Table, then the nudge and the handoff, then remember it (.wz/agents.json) and show it on the hub. Returns the rows."""
    t = now() if t is None else t
    th = settings(cfg)
    rows = table(cfg, t, probe, every)
    prev = (read_json(cfg.state / "agents.json") or {}).get("agents", {})
    keep = {}
    for r in rows:
        p = prev.get(r["key"], {}) if prev.get(r["key"], {}).get("status") == r["status"] else {}
        r["nudges"], r["last_nudge_t"] = p.get("nudges", 0), p.get("last_nudge_t", 0.0)
        if r["status"] in ("stalled", "zombie"):
            _act(cfg, r, t, th, tell_, push_)
        else:
            escalate.resolve(cfg, f"agent:{r['key']}", f"{r['key']} is {r['status']} again")
        keep[r["key"]] = {k: r[k] for k in ("status", "reason", "since", "raw", "raw_since", "nudges", "last_nudge_t") if k in r}
    for key in set(prev) - set(keep):
        escalate.resolve(cfg, f"agent:{key}", f"{key} is gone")
    write_json(cfg.state / "agents.json", {"at": iso(t), "agents": keep})
    paint_hub(cfg, rows)
    return rows


def _act(cfg, r: dict, t: float, th: dict, tell_, push_) -> None:
    tell_ = tell_ or escalate.tell
    key, role = f"agent:{r['key']}", r["role"]
    handoff = r["kind"] == "job" or r["status"] == "zombie"        # a job or a dead window cannot read a nudge
    if r["kind"] == "session" and r["status"] == "stalled":
        if r["nudges"] < th["nudges"]:
            if t - r["last_nudge_t"] >= th["nudge_s"]:
                out = tell_(cfg, role, f"[wz watchdog] no progress for a while: {r['reason']}. Say what you are blocked on, or carry on; "
                                       "if you need the owner, write it in your report.")
                r["nudges"] += 1
                r["last_nudge_t"] = t
                flags.event(cfg, "wz", "nudge", r["key"], f"nudge {r['nudges']} of {th['nudges']} to {role}: {out}")
            return
        handoff = t - r["last_nudge_t"] >= th["nudge_s"]
    if handoff:
        sev = "P1"
        escalate.raise_(cfg, f"{r['key']} is {r['status']}: {r['reason']}", sev=sev, subject=role, ref=r["key"], by="wz", key=key,
                        t=t, tell_=tell_, push_=push_)


def alerts(rows: list[dict], skip: set = frozenset()) -> list[dict]:
    """The stalled and zombie agents as watchdog alerts (kind STALLED / ZOMBIE). `skip`: refs an older alert already names."""
    return [{"kind": r["status"].upper(), "ref": r["key"], "role": r["role"], "text": r["reason"]}
            for r in rows if r["status"] in ("stalled", "zombie") and r["key"].split(":", 1)[1] not in skip]


def paint_hub(cfg, rows: list[dict]) -> None:
    """The hub's status bar names every agent that is not working or idle ('' clears it). One tmux call per hub session."""
    if not mux.have():
        return
    bad = [r for r in rows if r["status"] in ("stalled", "zombie")]
    text = " ".join(f"{r['role'] if r['kind'] == 'session' else r['key'].split(':', 1)[1]}:{r['status'].upper()}" for r in bad)
    hub.paint(cfg, f" ! {text} " if text else "")


def lines(rows: list[dict]) -> list[str]:
    """The digest's Agents section: the table, worst first."""
    order = {s: i for i, s in enumerate(("zombie", "stalled", "working", "idle"))}
    out = ["| agent | status | why |", "|---|---|---|"]
    for r in sorted(rows, key=lambda r: (order[r["status"]], r["key"])):
        out.append(f"| {r['key']} | {r['status']} | {r['reason'][:120]} |")
    return out
