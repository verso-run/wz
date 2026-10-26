"""`wz scan`: a leak scan before anything is published. Every text file in a tree is searched for words that must not
leave the project (internal hostnames, people's names, account names, ticket ids, home paths, email addresses).

Patterns come from [publish] deny in wz.toml and from --deny-file (one regular expression per line, `#` comments),
so the list of private words can itself stay private. Lines matching a [publish] allow pattern are skipped.
Exit status 1 when anything is found: wire it in front of `git push`.
"""
from __future__ import annotations

import re
from pathlib import Path

SKIP_DIRS = {".git", ".wz", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}
EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+"


def load_patterns(deny_file: Path | None, extra: list[str] = ()) -> list[str]:
    pats = list(extra)
    if deny_file:
        for line in Path(deny_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pats.append(line)
    return pats


def scan(root: Path, patterns: list[str], allow: list[str] = (), ignore_case: bool = True) -> list[tuple[str, int, str, str]]:
    flags = re.I if ignore_case else 0
    deny = [(p, re.compile(p, flags)) for p in patterns]
    allow_rx = [re.compile(a, flags) for a in allow]
    hits = []
    root = Path(root)
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        try:
            text = p.read_bytes()
        except OSError:
            continue
        if b"\0" in text[:4096]:
            continue
        rel = p.relative_to(root).as_posix()
        for pat, rx in deny:
            if rx.search(rel):
                hits.append((rel, 0, pat, "(file name)"))
        for i, line in enumerate(text.decode("utf-8", "replace").splitlines(), 1):
            if any(a.search(line) for a in allow_rx):
                continue
            for pat, rx in deny:
                if rx.search(line):
                    hits.append((rel, i, pat, line.strip()[:160]))
    return hits
