"""The watchdog: nothing queued, running or asked may sit forever unseen.

  LOST       a running job whose supervisor process is gone: marked failed
  OVERDUE    a running job past its timeout plus a grace period
  STUCK      a queued job waiting longer than [watchdog] queued_hours, with the reason it waits
  ORPHANED   a queued job whose dependency ended blocked, failed or cancelled (it will never start)
  IDLE       a role with nothing queued or running but open items in roles/<role>/BACKLOG.md
  UNSIGNED   a sign request pending longer than [watchdog] sign_hours
  HAND       a hand-step waiting for a person (every one is shown until it is answered or expires)
  LEASE      a lease held past its expiry (shown, never taken over)
  HOLD       a hold that expired without being cleared (it no longer blocks; the lead decides if it should)

Alerts go to .wz/watchdog.json; a new alert is also an event, so it reaches the lead through `wz next`.
"""
from __future__ import annotations

import re

from . import approvals, flags, hands, jobs, leases, release
from .util import iso, now, parse_iso, pid_alive, read_json, write_json

GRACE_S = 300


def check(cfg, t: float | None = None, apply: bool = True) -> list[dict]:
    t = now() if t is None else t
    wd = cfg.section("watchdog")
    queued_s = float(wd.get("queued_hours", 6)) * 3600
    sign_s = float(wd.get("sign_hours", 24)) * 3600
    alerts = []
    every = jobs.all_jobs(cfg)
    by_id = {j["id"]: j for j in every}
    for j in every:
        if j["status"] == "running":
            sup = j.get("supervisor_pid")
            claimed = parse_iso(j.get("claimed"))
            never_started = not sup and claimed is not None and t - claimed > GRACE_S
            if never_started or (sup and not pid_alive(sup)):
                alerts.append({"kind": "LOST", "ref": j["id"], "role": j["role"], "text": "supervisor gone or never started; marked failed"})
                if apply:
                    jobs.set_status(cfg, j["id"], "failed", "supervisor process gone (watchdog)")
            elif j.get("started_t") and t - j["started_t"] > j["timeout_s"] + GRACE_S:
                alerts.append({"kind": "OVERDUE", "ref": j["id"], "role": j["role"],
                               "text": f"running {int((t - j['started_t']) / 60)} min, timeout {j['timeout_s'] // 60} min"})
        elif j["status"] == "queued":
            dep = by_id.get(j.get("after") or "")
            if dep and dep["status"] in ("blocked", "failed", "cancelled"):
                alerts.append({"kind": "ORPHANED", "ref": j["id"], "role": j["role"],
                               "text": f"depends on {dep['id']}, which ended {dep['status']}"})
            elif t - j.get("created_t", t) > queued_s:
                why = jobs.wait_reason(cfg, j, by_id) or "ready, but not served (is the serve timer installed?)"
                alerts.append({"kind": "STUCK", "ref": j["id"], "role": j["role"],
                               "text": f"queued {int((t - j['created_t']) / 3600)} h: {why}"})
    for role in cfg.roles():
        if cfg.is_lead(role):
            continue
        if any(j["role"] == role and j["status"] in ("queued", "running") for j in every):
            continue
        bl = cfg.role_dir(role) / "BACKLOG.md"
        if bl.is_file():
            n = len(re.findall(r"^\s*- \[ \]", bl.read_text(), re.M))
            if n:
                alerts.append({"kind": "IDLE", "ref": role, "role": role, "text": f"nothing queued; {n} open backlog item(s)"})
    for r in approvals.pending(cfg):
        created = parse_iso(r.get("created"))
        if created and t - created > sign_s:
            alerts.append({"kind": "UNSIGNED", "ref": r["id"], "role": r.get("by", ""),
                           "text": f"waiting {int((t - created) / 3600)} h: {r['what']}"})
    for h in hands.waiting(cfg):
        alerts.append({"kind": "HAND", "ref": h["id"], "role": h["by"],
                       "text": f"{h['text']} (asked {h['asked']}" + (", hazardous: attended only)" if h["hazard"] else ")")})
    for lz in leases.overdue(cfg, t):
        alerts.append({"kind": "LEASE", "ref": lz["resource"], "role": "",
                       "text": f"held by {lz['holder']} past its expiry {lz['expires']}"})
    for h in release.holds(cfg, t):
        if h["state"] == "expired" and h["level"] != "NOTE":
            alerts.append({"kind": "HOLD", "ref": h["id"], "role": h.get("by", ""),
                           "text": f"{h['level']} on {h['ref']} expired {h['expires']} uncleared: {h['text']}"})
    if apply:
        prev = {(a["kind"], a["ref"]) for a in (read_json(cfg.state / "watchdog.json") or {}).get("alerts", [])}
        for a in alerts:
            if (a["kind"], a["ref"]) not in prev:
                flags.event(cfg, a["role"], "alert", a["ref"], f"{a['kind']} {a['text']}")
        write_json(cfg.state / "watchdog.json", {"at": iso(t), "alerts": alerts})
    return alerts
