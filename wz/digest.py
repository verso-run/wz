"""The daily sync and digest.

status/SYNC-<date>.md is the lead's working file for the day (`wz sync` creates it from the template): what runs
today, what changed, the asks, and the lead's own errors. `wz digest` composes status/DIGEST-<date>.md, the one
message the owner reads each morning: at most three asks first, then what finished, what waits, spend and pending
signs, and the lead's errors copied from the sync file.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import approvals, budget, jobs, watchdog
from .records import TEMPLATES, cell
from .util import now, today

MAX_ASKS = 3


def sync(cfg, day: str | None = None) -> Path:
    day = day or today()
    p = cfg.root / "status" / f"SYNC-{day}.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        text = (TEMPLATES / "sync.md").read_text().replace("{date}", day).replace("{project}", cfg.project)
        p.write_text(text.replace("{lead}", cfg.lead()))
    return p


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def compose(cfg, day: str | None = None, window_h: float = 24) -> str:
    day = day or today()
    t0 = now() - window_h * 3600
    every = jobs.all_jobs(cfg)
    finished = [j for j in every if j.get("finished_t", 0) >= t0]
    asks = []
    for j in jobs.queue_order(finished):
        for a in (j.get("result") or {}).get("owner_asks") or []:
            asks.append((a if isinstance(a, str) else a.get("what", str(a)), j["id"]))
    signs = approvals.pending(cfg)
    for r in signs:
        asks.append((f"Sign {r['id']}: {r['what']} (approval page or `wz sign approve {r['id']}`)", r["id"]))
    sync_text = (cfg.root / "status" / f"SYNC-{day}.md")
    sync_text = sync_text.read_text() if sync_text.exists() else ""
    lines = [f"# Digest {day} — {cfg.project}", ""]
    lines += ["## Asks", ""]
    if asks:
        for i, (a, ref) in enumerate(asks[:MAX_ASKS], 1):
            lines.append(f"{i}. {a} ({ref})")
        if len(asks) > MAX_ASKS:
            lines.append(f"\n{len(asks) - MAX_ASKS} more ask(s) wait in the reports; the lead holds them until these clear.")
    else:
        lines.append("Nothing needs you today.")
    runs_today = _section(sync_text, "What runs today")
    if runs_today:
        lines += ["", "## What runs today", "", runs_today]
    lines += ["", f"## Finished in the last {int(window_h)} h", ""]
    if finished:
        lines += ["| job | role | status | result | cost USD |", "|---|---|---|---|---|"]
        for j in sorted(finished, key=lambda j: j.get("finished_t", 0)):
            r = j.get("result") or {}
            lines.append(f"| {j['id']} | {j['role']} | {j['status']} | {cell(r.get('result') or r.get('block_reason') or '')[:140]} "
                         f"| {j.get('cost_usd', 0):.2f} |")
    else:
        lines.append("Nothing finished.")
    alerts = watchdog.check(cfg, apply=False)
    queued = [j for j in every if j["status"] in ("queued", "held", "running")]
    lines += ["", "## Waiting", "", f"{sum(j['status'] == 'running' for j in queued)} running, "
              f"{sum(j['status'] == 'queued' for j in queued)} queued, {sum(j['status'] == 'held' for j in queued)} held."]
    for a in alerts:
        lines.append(f"- {a['kind']} {a['ref']}: {a['text']}")
    lines += ["", "## Spend today", "", "| account | spent USD | cap USD |", "|---|---|---|"]
    for b in budget.table(cfg, day):
        lines.append(f"| {b['account']} | {b['spent']:.2f} | {b['cap'] if b['cap'] is not None else '-'} |")
    errors = _section(sync_text, "My errors")
    lines += ["", "## The lead's own errors", "", errors or "(the lead has not written this section in today's sync file)"]
    return "\n".join(lines) + "\n"


def write(cfg, day: str | None = None) -> Path:
    day = day or today()
    p = cfg.root / "status" / f"DIGEST-{day}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(compose(cfg, day))
    return p
