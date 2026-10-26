"""The post-run (field test) review loop: one command collects the session, packs metrics, drafts the review, and
asks the owner only for their words.

  wz review collect <session dir or file> [--name N]
      copies the session into runs/<name>/session/ (read-only source, never moved), runs [review] metrics (a command
      with {session} and {out}; it writes metrics.json), and drafts runs/<name>/REVIEW.md from runs/TEMPLATE.md (or
      the built-in one) with the metrics table filled in and one empty section: the owner's words.
  wz review words <name> "<what the owner said>"
      the owner (never an agent) fills that section; until then the review is a draft and the digest lists it.

The metrics are numbers read from files; the draft says which file each came from. Nothing in the draft is the
owner's opinion until they write it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import flags
from .util import iso, read_json, today

WORDS_HEAD = "## Owner's words"
WORDS_EMPTY = "(waiting for the owner: `wz review words {name} \"...\"`)"

TEMPLATE = """# Review: {name}

Collected {collected} from `{source}`. Draft by {by}; a review stands only with the owner's words below.

## Metrics

{metrics}

## What the agent saw

(the reviewing role fills this from the session files: what happened, against what was expected, with file:line)

{words_head}

{words}
"""


class ReviewError(Exception):
    pass


def _dir(cfg, name: str) -> Path:
    return cfg.root / "runs" / name


def _fill(text: str, **values) -> str:
    """Replace {name} placeholders only; any other braces (a JSON literal in a command) are left alone."""
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _metrics_table(m: dict, source: str) -> str:
    if not m:
        return "(no metrics command configured: [review] metrics)"
    rows = ["| metric | value | read from |", "|---|---|---|"]
    for k, v in m.items():
        rows.append(f"| {k} | {v} | {source} |")
    return "\n".join(rows)


def collect(cfg, session: Path, name: str | None = None, by: str = "") -> Path:
    session = Path(session).resolve()
    if not session.exists():
        raise ReviewError(f"no session at {session}")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name or session.stem).strip("-") or today()
    d = _dir(cfg, name)
    if (d / "REVIEW.md").exists():
        raise ReviewError(f"runs/{name}/REVIEW.md exists; pick another --name")
    dst = d / "session"
    d.mkdir(parents=True, exist_ok=True)
    if session.is_dir():
        shutil.copytree(session, dst, dirs_exist_ok=True)
    else:
        dst.mkdir(exist_ok=True)
        shutil.copy2(session, dst / session.name)
    metrics, source = {}, ""
    cmd = cfg.section("review").get("metrics")
    if cmd:
        out = d / "metrics.json"
        c = subprocess.run(_fill(cmd, session=str(dst), out=str(out)), shell=True, cwd=str(cfg.root),
                           capture_output=True, text=True)
        (d / "metrics.log").write_text(c.stdout + c.stderr)
        if c.returncode != 0:
            raise ReviewError(f"metrics command exited {c.returncode}; see runs/{name}/metrics.log")
        metrics, source = read_json(out) or {}, "metrics.json"
    tpl_path = cfg.root / "runs" / "TEMPLATE.md"
    tpl = tpl_path.read_text() if tpl_path.is_file() else TEMPLATE
    by = by or os.environ.get("WZ_ROLE", "owner")
    text = _fill(tpl, name=name, collected=iso(), source=str(session), by=by, metrics=_metrics_table(metrics, source),
                 words_head=WORDS_HEAD, words=WORDS_EMPTY.format(name=name))
    (d / "REVIEW.md").write_text(text)
    flags.event(cfg, by, "review", name, "draft ready; waiting for the owner's words")
    return d / "REVIEW.md"


def words(cfg, name: str, text: str, env=None) -> Path:
    env = os.environ if env is None else env
    if env.get("WZ_ROLE"):
        raise ReviewError("the owner's words are the owner's; an agent never writes them")
    p = _dir(cfg, name) / "REVIEW.md"
    if not p.is_file():
        raise ReviewError(f"no review {name}")
    body = p.read_text()
    empty = WORDS_EMPTY.format(name=name)
    if empty not in body:
        raise ReviewError(f"{name} already has the owner's words; add a dated line by hand if they said more")
    p.write_text(body.replace(empty, f"\"{text.strip()}\" ({iso()})"))
    flags.event(cfg, "owner", "review", name, "owner's words in")
    return p


def drafts(cfg) -> list[str]:
    out = []
    for p in sorted((cfg.root / "runs").glob("*/REVIEW.md")):
        if WORDS_EMPTY.format(name=p.parent.name) in p.read_text():
            out.append(p.parent.name)
    return out
