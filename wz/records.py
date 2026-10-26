"""The written record: the decisions log, the ledgers and the briefs. Plain markdown tables, append-only.

Decisions: one row per decision, the owner's exact words quoted, the lead's reading beside them. A row without the
owner's words is a proposal (status `proposal`) until the owner says so.
Ledgers: defects, follow-ups and hypotheses; any role appends, nobody rewrites another's row.
Briefs: one file per piece of work, numbered, from briefs/TEMPLATE.md; the role fills its Report section.
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import locked, today

TEMPLATES = Path(__file__).resolve().parent / "templates"

DECISIONS_HEAD = """# Decisions

One row per decision. The owner's words are quoted exactly; a row without them is a proposal until the owner says so.
The reading is the lead's own and stays revisitable. Rows are never edited; a change of mind is a new row that names
the one it replaces.

| id | date | owner's words | lead's reading | status |
|---|---|---|---|---|
"""

LEDGERS = {
    "defects": ("DEFECTS.md", "DEF", ["severity", "role", "what", "status"],
                "Defects: what is wrong, how bad, who owns the fix."),
    "followups": ("FOLLOWUPS.md", "FU", ["from", "role", "task", "evidence of done", "status"],
                  "Follow-ups proposed by jobs. The lead queues them as jobs or closes them; nothing here runs by itself."),
    "audits": ("AUDITS.md", "AUD", ["ref", "role", "verdict", "evidence", "status"],
               "Auditor passes: a decision row or outward claim stands only once a row here names it with verdict pass."),
    "hypotheses": ("HYPOTHESES.md", "HYP", ["hypothesis", "test", "status"],
                   "Hypotheses: what we believe, and the test that would show it wrong."),
}


def cell(v) -> str:
    return str(v if v is not None else "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def _next_num(text: str, prefix: str) -> int:
    nums = [int(m) for m in re.findall(rf"^\| {re.escape(prefix)}-(\d+) \|", text, re.M)]
    return max(nums, default=0) + 1


def init_files(cfg) -> list[Path]:
    """Create the decisions log, ledgers and folders if missing. Returns what it created."""
    made = []
    root = cfg.root
    if not (root / "DECISIONS.md").exists():
        (root / "DECISIONS.md").write_text(DECISIONS_HEAD)
        made.append(root / "DECISIONS.md")
    for name, (fname, _prefix, cols, doc) in LEDGERS.items():
        p = root / "ledgers" / fname
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            head = ["id", "date"] + cols
            p.write_text(f"# {fname[:-3].title()}\n\n{doc}\n\n| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n")
            made.append(p)
    for d in ("briefs", "status", "roles"):
        (root / d).mkdir(parents=True, exist_ok=True)
    tpl = root / "briefs" / "TEMPLATE.md"
    if not tpl.exists():
        tpl.write_text((TEMPLATES / "brief.md").read_text())
        made.append(tpl)
    return made


def decide(cfg, words: str | None, reading: str, proposal: bool = False) -> str:
    p = cfg.root / "DECISIONS.md"
    with locked(cfg.state / "records.lock"):
        if not p.exists():
            p.write_text(DECISIONS_HEAD)
        text = p.read_text()
        did = f"D-{_next_num(text, 'D')}"
        has_words = bool(words and words.strip())
        status = "proposal" if (proposal or not has_words) else "decided, revisitable"
        quoted = f"\"{cell(words)}\"" if has_words else "(none: proposal)"
        row = f"| {did} | {today()} | {quoted} | {cell(reading)} | {status} |\n"
        if not text.endswith("\n"):
            row = "\n" + row
        with open(p, "a") as f:
            f.write(row)
    return did


def ledger_add(cfg, ledger: str, fields: dict) -> str:
    if ledger not in LEDGERS:
        raise ValueError(f"unknown ledger {ledger!r} (ledgers: {', '.join(LEDGERS)})")
    fname, prefix, cols, _doc = LEDGERS[ledger]
    p = cfg.root / "ledgers" / fname
    with locked(cfg.state / "records.lock"):
        if not p.exists():
            init_files(cfg)
        text = p.read_text()
        rid = f"{prefix}-{_next_num(text, prefix):03d}"
        vals = [fields.get(c, "open" if c == "status" else "") for c in cols]
        row = "| " + " | ".join([rid, today()] + [cell(v) for v in vals]) + " |\n"
        with open(p, "a") as f:
            f.write(("" if text.endswith("\n") else "\n") + row)
    return rid


def brief_new(cfg, slug: str, role: str, title: str = "") -> Path:
    cfg.role(role)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "work"
    d = cfg.root / "briefs"
    d.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for p in d.glob("*.md") if (m := re.match(r"^(\d+)-", p.name))]
    n = max(nums, default=0) + 1
    p = d / f"{n:02d}-{slug}.md"
    tpl = (d / "TEMPLATE.md") if (d / "TEMPLATE.md").exists() else (TEMPLATES / "brief.md")
    text = tpl.read_text().replace("{NN}", f"{n:02d}").replace("{slug}", slug).replace("{role}", role)
    text = text.replace("{title}", title or slug.replace("-", " ")).replace("{date}", today())
    p.write_text(text)
    return p
