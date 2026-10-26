"""Flags: finished work announces itself through files, never through a model turn.

Every event (a job ended, a role wrote a report or ledger row, a watchdog alert, a sign request) is one line in
.wz/events.jsonl. The lead reads what is new with `wz next`, which keeps a cursor; `wz wait <role> <file>` blocks a
shell (not a model) until a role writes that file.

The PostToolUse hook (`wz hook flag`) raises a flag when a role session writes briefs/*.md or ledgers/*.md.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import config as _config
from .util import append_jsonl, glob_match, iso, now, read_json, read_jsonl, write_json


def _events(cfg) -> Path:
    return cfg.state / "events.jsonl"


def event(cfg, role: str, kind: str, ref: str = "", text: str = "", **extra) -> dict:
    ev = {"t": now(), "at": iso(), "role": role, "kind": kind, "ref": ref, "text": text, **extra}
    append_jsonl(_events(cfg), ev)
    return ev


def events(cfg) -> list[dict]:
    return read_jsonl(_events(cfg))


def since_cursor(cfg, peek: bool = False) -> list[dict]:
    cur_path = cfg.state / "lead-cursor.json"
    cur = (read_json(cur_path) or {}).get("n", 0)
    evs = events(cfg)
    new = evs[cur:]
    if not peek:
        write_json(cur_path, {"n": len(evs), "at": iso()})
    return new


def _flag_path(cfg, role: str, name: str) -> Path:
    return cfg.state / "flags" / f"{role}.{name}.done"


def wait(cfg, role: str, name: str, timeout_s: float = 0, poll_s: float = 2.0) -> bool:
    """Block until `role` has written `name` (a brief or ledger file name). Consumes the flag."""
    p = _flag_path(cfg, role, name)
    end = time.time() + timeout_s if timeout_s else None
    while not p.exists():
        if end is not None and time.time() > end:
            return False
        time.sleep(poll_s)
    p.unlink(missing_ok=True)
    return True


def hook(stdin: str | None = None, env: dict | None = None) -> int:
    """PostToolUse: flag writes of briefs/*.md and ledgers/*.md by a role. Never blocks, never prints."""
    env = dict(os.environ if env is None else env)
    role = env.get("WZ_ROLE")
    if not role:
        return 0
    try:
        payload = json.loads(sys.stdin.read() if stdin is None else stdin)
        cfg = _config.load(Path(env["WZ_CONFIG"]) if env.get("WZ_CONFIG") else None)
    except Exception:
        return 0
    if cfg.is_lead(role):
        return 0
    inp = payload.get("tool_input") or {}
    fp = inp.get("file_path") or ""
    if not fp:
        return 0
    p = Path(os.path.realpath(Path(payload.get("cwd") or ".") / fp))
    try:
        rel = p.relative_to(cfg.root).as_posix()
    except ValueError:
        return 0
    if any(glob_match(rel, g) for g in ("briefs/*.md", "ledgers/*.md")) and p.exists():
        f = _flag_path(cfg, role, p.name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(int(now())))
        event(cfg, role, "report", rel, f"{role} wrote {rel}", job=env.get("WZ_JOB", ""))
    return 0
