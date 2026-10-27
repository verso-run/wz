"""Keeping the queue honest: backlog refill from the ledgers, focus and prune, nightly jobs.

  refill   every open defect or follow-up row naming a role lands once in roles/<role>/BACKLOG.md as `- [ ] ID: text`
           (deduplicated by ledger id; nothing is removed or reordered). The watchdog's IDLE alert then shows a role
           with open backlog and nothing queued.
  prune    duplicates (same role, task word overlap >= [focus] jaccard, default 0.6) are cancelled, keeping the
           higher priority; holds older than [focus] hold_days are cancelled; queued jobs at or above
           [focus] min_priority that match none of [focus] patterns are held as drift. Report by default; --apply acts.
           Running jobs are never touched.
  nightly  [[nightly]] entries (role, task, optional priority/timeout/lease) are queued once per day by the nightly
           timer; a second call the same day queues nothing.
"""
from __future__ import annotations

import re

from . import jobs, records
from .util import now, parse_iso, read_json, today, write_json

_CLOSED = re.compile(r"(?i)^(closed|done|fixed|shipped|won't|wont|superseded|withdrawn|resolved)")


def _rows(path):
    if not path.is_file():
        return []
    lines = path.read_text().splitlines()
    head = None
    out = []
    for line in lines:
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if head is None:
            head = cells
            continue
        if len(cells) == len(head):
            out.append(dict(zip(head, cells)))
    return out


def refill(cfg, dry_run: bool = False) -> dict[str, list[str]]:
    added: dict[str, list[str]] = {}
    for name, (fname, _prefix, cols, _doc) in records.LEDGERS.items():
        text_col = {"defects": "what", "followups": "task"}.get(name)
        if not text_col:
            continue
        for row in _rows(cfg.root / "ledgers" / fname):
            role, rid = row.get("role", ""), row.get("id", "")
            if role not in cfg.roles() or _CLOSED.match(row.get("status", "")):
                continue
            bl = cfg.role_dir(role) / "BACKLOG.md"
            have = bl.read_text() if bl.is_file() else f"# {role} — backlog\n\n"
            if re.search(rf"\b{re.escape(rid)}\b", have):
                continue
            added.setdefault(role, []).append(rid)
            if not dry_run:
                bl.parent.mkdir(parents=True, exist_ok=True)
                bl.write_text(have.rstrip("\n") + f"\n- [ ] {rid}: {row.get(text_col, '')}\n")
    return added


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def jaccard(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def prune(cfg, apply: bool = False, t: float | None = None) -> list[dict]:
    t = now() if t is None else t
    f = cfg.section("focus")
    thr = float(f.get("jaccard", 0.6))
    hold_days = float(f.get("hold_days", 7))
    pats = [re.compile(p, re.I) for p in f.get("patterns", [])]
    min_p = int(f.get("min_priority", 50))
    # an owner's open gate is theirs to pass or cancel: prune never drops it, however long it has waited
    live = [j for j in jobs.all_jobs(cfg) if j["status"] in ("queued", "held") and not jobs.open_gate(j)]
    acts, gone = [], set()
    ordered = jobs.queue_order(live)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b["id"] in gone or a["id"] in gone or a["role"] != b["role"]:
                continue
            if jaccard(a["task"], b["task"]) >= thr:
                acts.append({"action": "cancel", "job": b["id"], "why": f"duplicate of {a['id']}"})
                gone.add(b["id"])
    for j in live:
        if j["id"] in gone:
            continue
        if j["status"] == "held":
            held_at = max([parse_iso(n.split(" ", 1)[0]) or 0 for n in j.get("notes", []) if " held" in n] or [j.get("created_t", t)])
            if t - held_at > hold_days * 86400:
                acts.append({"action": "cancel", "job": j["id"], "why": f"held over {hold_days:g} days"})
                gone.add(j["id"])
        elif pats and j["priority"] >= min_p and not any(p.search(j["task"]) for p in pats):
            acts.append({"action": "hold", "job": j["id"], "why": "outside the focus patterns"})
    if apply:
        for a in acts:
            if a["action"] == "cancel":
                jobs.cancel(cfg, a["job"], a["why"])
            else:
                jobs.hold(cfg, a["job"], a["why"])
    return acts


def nightly(cfg, day: str | None = None) -> list[str]:
    day = day or today()
    seen_p = cfg.state / "nightly.json"
    seen = read_json(seen_p) or {}
    if seen.get("day") == day:
        return []
    made = []
    for n in cfg.data.get("nightly", []) or []:
        j = jobs.add(cfg, n["role"], n["task"], priority=int(n.get("priority", 60)), timeout=n.get("timeout"),
                     lease=n.get("lease", []), evidence=n.get("evidence"), by="nightly")
        made.append(j["id"])
    write_json(seen_p, {"day": day, "jobs": made})
    return made
