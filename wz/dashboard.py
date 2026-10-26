"""A status dashboard: one static HTML page from the same files `wz status` reads. No server, no script.

`wz status --html status/dashboard.html` writes it; the watchdog timer can regenerate it. Open it locally or publish
it wherever the owner reads. It shows roles and their queues, running jobs, waiting hand-steps, leases, open holds,
signs pending, today's spend and the last bench runs.
"""
from __future__ import annotations

import html

from . import approvals, bench, budget, hands, jobs, leases, release, watchdog, worker
from .util import iso


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "<p class=none>none</p>"
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def render(cfg) -> str:
    every = jobs.all_jobs(cfg)
    roles = []
    for role, r in cfg.roles().items():
        mine = [j for j in every if j["role"] == role]
        roles.append({"role": role, "pack": r["pack"], "running": sum(j["status"] == "running" for j in mine),
                      "queued": sum(j["status"] == "queued" for j in mine), "halted": worker.halted(cfg, role) or ""})
    running = [{"id": j["id"], "role": j["role"], "task": j["task"][:80], "since": j.get("started", "")}
               for j in every if j["status"] == "running"]
    hs = [{"id": h["id"], "what": h["text"], "resource": h.get("resource") or "", "hazard": "yes" if h["hazard"] else ""}
          for h in hands.waiting(cfg)]
    holds = [{"id": h["id"], "level": h["level"], "ref": h["ref"], "text": h["text"], "expires": h["expires"]}
             for h in release.open_holds(cfg)]
    signs = [{"id": s["id"], "what": s["what"]} for s in approvals.pending(cfg)]
    runs = [{"run": r["run"], "verdict": r["verdict"], "commit": r["commit"][:12], "finished": r.get("finished", "")}
            for r in bench.all_runs(cfg)[-10:]]
    alerts = watchdog.check(cfg, apply=False)
    sections = [
        ("Roles", _table(roles, ["role", "pack", "running", "queued", "halted"])),
        ("Running", _table(running, ["id", "role", "task", "since"])),
        ("Hand-steps waiting", _table(hs, ["id", "what", "resource", "hazard"])),
        ("Leases", _table(leases.table(cfg), ["resource", "kind", "free", "holder", "expires"])),
        ("Open holds", _table(holds, ["id", "level", "ref", "text", "expires"])),
        ("Signs pending", _table(signs, ["id", "what"])),
        ("Alerts", _table(alerts, ["kind", "ref", "text"])),
        ("Bench runs", _table(runs, ["run", "verdict", "commit", "finished"])),
    ]
    spent = budget.spent(cfg)
    cap = cfg.section("budget").get("daily_usd")
    body = "".join(f"<h2>{t}</h2>{s}" for t, s in sections)
    return (f"<!doctype html><meta charset=utf-8><title>{html.escape(cfg.project)} status</title>"
            "<style>body{font:14px system-ui,sans-serif;margin:2em;max-width:70em}table{border-collapse:collapse}"
            "td,th{border-bottom:1px solid #ccc;padding:.25em .6em;text-align:left}.none{color:#777}</style>"
            f"<h1>{html.escape(cfg.project)}</h1><p>Generated {iso()} · spent today {spent:.2f}"
            f"{f' of {float(cap):.2f}' if cap else ''} USD</p>{body}")
