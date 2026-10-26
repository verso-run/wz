"""The guard: a Claude Code PreToolUse hook that refuses what a role may not do.

It is a no-op unless WZ_ROLE is set (wz sets it for every role session and job). It refuses:
  * a file write (Edit, Write, MultiEdit, NotebookEdit, or a shell redirect/cp/mv/rm/... target) outside the role's
    owned paths, its own roles/<role>/ folder, the shared briefs/ and ledgers/, its scratch dir and the temp dir;
  * a kill by pattern (pkill, killall, kill $(pgrep ...), pgrep | xargs kill);
  * a read of a secret (a path matching [guard] secrets, `env`/`printenv`, a $..._TOKEN-style variable);
  * git commit/tag/push without the job's unlock, force pushes, and pushes to the integration or main branches;
  * owner-only commands (signing, the approval page, unlocking, lifting a halt) from a role session.

Exit 2 with the reason on stderr refuses the call; every refusal is appended to .wz/guard.log. The guard fails closed:
if it cannot check a write-capable call it refuses it, and lets reads through. It is a seatbelt, not a sandbox: a
determined shell one-liner can still write somewhere; the merge step's ownership check is the backstop.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

from . import config as _config
from . import leases as _leases
from . import unlock as _unlock
from .util import glob_match, is_within

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}
SHARED_GLOBS = ["briefs/*.md", "ledgers/*.md"]


class Refuse(Exception):
    pass


# ---- paths --------------------------------------------------------------------------------------------------------
def _norm(path: str, cwd: str) -> Path:
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(cwd) / p
    return Path(os.path.realpath(p))


def _temp_roots(cfg) -> list[Path]:
    roots = {Path(os.path.realpath(tempfile.gettempdir())), Path(os.path.realpath("/tmp"))} if cfg.guard()["temp"] else set()
    for a in cfg.guard().get("allow", []):
        roots.add(Path(os.path.realpath(os.path.expanduser(a))))
    return sorted(roots)


def owners_of(cfg, store: str, rel: str) -> list[str]:
    return [n for n, r in cfg.roles().items() if any(glob_match(rel, g) for g in r["owns"].get(store, []))]


def locate(cfg, p: Path) -> tuple[str, str, str | None] | None:
    """(store, path relative to that store's root, owning role of the worktree or None) for an absolute path."""
    wt_base = cfg.state / "worktrees"
    if is_within(p, wt_base):
        parts = p.relative_to(wt_base).parts
        if len(parts) >= 2:
            store, wt = parts[0], parts[1]
            return store, "/".join(parts[2:]), wt.split(".", 1)[0]
        return None
    best = None
    for name in cfg.stores():
        root = cfg.store_root(name)
        if is_within(p, root) and (best is None or len(str(root)) > len(str(best[1]))):
            best = (name, root)
    if best is None:
        return None
    return best[0], p.relative_to(best[1]).as_posix(), None


def may_write(cfg, role: str, p: Path) -> tuple[bool, str]:
    if str(p) in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"):
        return True, "device"
    if is_within(p, cfg.scratch(role)):
        return True, "scratch"
    if is_within(p, cfg.state) and not is_within(p, cfg.state / "worktrees"):
        return False, "wz state under .wz/ is written by wz itself, not by a role"
    loc = locate(cfg, p)
    if loc is None:
        if any(is_within(p, t) for t in _temp_roots(cfg)):
            return True, "temp"
        return False, "outside every store in wz.toml"
    store, rel, wt_role = loc
    if wt_role is not None and wt_role != role:
        return False, f"that worktree belongs to role {wt_role}"
    if store == _config.WORKSPACE and wt_role is None:
        if rel == f"roles/{role}" or rel.startswith(f"roles/{role}/"):
            return True, "own role folder"
        if any(glob_match(rel, g) for g in SHARED_GLOBS):
            return True, "shared (report section / ledger append)"
    if any(glob_match(rel, g) for g in cfg.role(role)["owns"].get(store, [])):
        return True, "owned"
    who = owners_of(cfg, store, rel)
    return False, f"{store}:{rel} is " + (f"owned by {', '.join(who)}" if who else "owned by no role")


def is_secret(cfg, p: Path) -> bool:
    parts = p.parts
    for g in cfg.guard()["secrets"]:
        if "/" in g:
            for i in range(len(parts)):
                if glob_match("/".join(parts[i:]), g):
                    return True
        elif glob_match(p.name, g):
            return True
    return False


# ---- shell parsing ------------------------------------------------------------------------------------------------
_SEPS = {";", "&&", "||", "|", "&", "(", ")", ";;", "|&", ";&"}
_KILL_PATTERNS = [
    (re.compile(r"(^|[\s;&|(`])pkill(\s|$)"), "pkill"),
    (re.compile(r"(^|[\s;&|(`])killall(\s|$)"), "killall"),
    (re.compile(r"\bkill\b[^;&|]*(\$\(|`)\s*(pgrep|pidof|ps\b)"), "kill $(pgrep ...)"),
    (re.compile(r"\b(pgrep|pidof)\b[^;&]*\|\s*xargs\s+(-\S+\s+)*kill\b"), "pgrep | xargs kill"),
    (re.compile(r"\bps\b[^;&]*\|[^;&]*\bxargs\s+(-\S+\s+)*kill\b"), "ps | xargs kill"),
]
_SECRET_VAR = re.compile(r"\$\{?[A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Za-z0-9_]*\}?")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_WRITERS_ALL_ARGS = {"touch", "mkdir", "rm", "rmdir", "truncate", "chmod", "chown", "shred", "unlink"}
_WRITERS_LAST_ARG = {"cp", "mv", "install", "rsync", "ln", "scp"}
_PREFIXES = {"sudo", "nohup", "time", "command", "exec", "nice"}
_OWNER_ONLY = [
    (re.compile(r"\bwz\s+sign\s+(approve|deny|set-pin)\b"), "signing is the owner's, from the owner's own shell"),
    (re.compile(r"\bwz\s+approve\b"), "the approval page is the owner's"),
    (re.compile(r"\bwz\s+hand\s+(done|refuse|attend|leave)\b"),
     "only a person at the bench answers a hand-step or declares attendance; ask and wait (`wz hand wait`)"),
    (re.compile(r"\bwz\s+review\s+words\b"), "the owner's words are the owner's; leave that section for them"),
]
_LEAD_ONLY = [
    (re.compile(r"\bwz\s+unlock\b"), "only the lead unlocks a role"),
    (re.compile(r"\bwz\s+resume\b"), "only the lead lifts a halt"),
]


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: their text is data for the command, not more commands."""
    out, delim = [], None
    for line in command.split("\n"):
        if delim is not None:
            if line.strip() == delim:
                delim = None
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            delim = m.group(2)
    return "\n".join(out)


def _lex(command: str) -> list[str]:
    lx = shlex.shlex(command, posix=True, punctuation_chars=True)
    lx.whitespace_split = True
    try:
        return list(lx)
    except ValueError:
        return command.split()


def segments(command: str) -> list[list[str]]:
    """The simple commands of a shell line, quote-aware, each as a token list (redirect operators kept)."""
    segs, cur = [], []
    for t in _lex(_strip_heredocs(command).replace("\n", " ; ")):
        if t in _SEPS:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def split_redirects(seg: list[str]) -> tuple[list[str], list[str]]:
    """(the command's words, its output redirect targets)."""
    args, targets, i = [], [], 0
    while i < len(seg):
        t = seg[i]
        nxt = seg[i + 1] if i + 1 < len(seg) else None
        if t and set(t) <= set("<>&|") and ">" in t:
            if args and args[-1].isdigit():
                args.pop()
            if "&" in t and t.endswith("&") and (nxt is None or nxt.isdigit() or nxt == "-"):
                i += 2
                continue
            if nxt is not None:
                targets.append(nxt)
            i += 2
            continue
        if t and set(t) <= set("<&"):
            if args and args[-1].isdigit():
                args.pop()
            i += 2
            continue
        args.append(t)
        i += 1
    return args, targets


def _git_sub(tokens: list[str]) -> tuple[str | None, list[str]]:
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, tokens[i + 1:]
    return None, []


def _protected(cfg) -> set[str]:
    out = set(cfg.guard().get("protected_branches", []))
    for s in cfg.stores().values():
        if s.get("kind") == "git":
            out.add(s.get("main", "main"))
            if s.get("integration"):
                out.add(s["integration"])
    return out


def _arg_targets(args: list[str]) -> list[str]:
    if not args:
        return []
    cmd, rest = os.path.basename(args[0]), args[1:]
    plain = [a for a in rest if not a.startswith("-")]
    if cmd == "tee":
        return plain
    if cmd == "sed" and any(a == "--in-place" or (a.startswith("-i") and not a.startswith("--")) for a in rest):
        return plain[1:]
    if cmd in _WRITERS_ALL_ARGS:
        return plain
    if cmd in _WRITERS_LAST_ARG and plain:
        return [plain[-1]]
    if cmd == "dd":
        return [a[3:] for a in rest if a.startswith("of=")]
    if cmd == "git":
        sub, r = _git_sub(args)
        pl = [a for a in r if not a.startswith("-")]
        if sub == "clone" and len(pl) >= 2:
            return [pl[1]]
    return []


def _is_env_dump(args: list[str]) -> bool:
    if not args:
        return False
    c = args[0]
    if c == "printenv":
        return True
    if c == "env":
        return all(a.startswith("-") or "=" in a for a in args[1:])
    if c == "set":
        return len(args) == 1
    if c in ("export", "declare", "typeset"):
        return len(args) == 1 or any(a in ("-p", "-x", "-px", "-xp") for a in args[1:])
    return False


def check_bash(cfg, role: str, command: str, cwd: str, job: str | None) -> None:
    for rx, what in _KILL_PATTERNS:
        if rx.search(command):
            raise Refuse(f"{what}: kill only the process ID you started (record $! and kill that), never by pattern")
    if _SECRET_VAR.search(command):
        raise Refuse("the command names a secret variable; agents never read or print secrets")
    prot = _leases.command_names_protected(cfg, command)
    if prot:
        raise Refuse(f"the command names {prot}, a protected device (the owner's own); no agent drives it")
    for rx, why in _OWNER_ONLY:
        if rx.search(command):
            raise Refuse(why)
    if not cfg.is_lead(role):
        for rx, why in _LEAD_ONLY:
            if rx.search(command):
                raise Refuse(why)
    for seg in segments(command):
        args, targets = split_redirects(seg)
        while args and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]) or args[0] in _PREFIXES):
            args = args[1:]
        if not args and not targets:
            continue
        if args and args[0] == "cd":
            if len(args) > 1 and "$" not in args[1]:
                cwd = str(_norm(args[1], cwd))
            continue
        if _is_env_dump(args):
            raise Refuse("dumping the environment can print secrets")
        for t in args[1:] + targets:
            if ("/" in t or t.startswith(".") or t.startswith("~")) and not t.startswith("-") and "://" not in t:
                if is_secret(cfg, _norm(t.split("=", 1)[-1], cwd)):
                    raise Refuse(f"{t} is a secret path; agents never read secrets")
        if args and args[0] == "git":
            sub, rest = _git_sub(args)
            if sub in ("commit", "tag", "push") and not (sub == "commit" and cfg.is_lead(role)):
                if not _unlock.has(cfg, role, job):
                    raise Refuse(f"git {sub} needs an unlock: a job carries its own; in a chat session ask the lead for `wz unlock {role}`")
            if sub == "push":
                if any(a in ("-f", "--force", "--mirror", "--delete", "-d") or a.startswith("--force") for a in rest):
                    raise Refuse("force, mirror and delete pushes are refused; push your own branch plainly")
                prot = _protected(cfg)
                for r in [a for a in rest if not a.startswith("-")][1:]:
                    dst = r.split(":", 1)[-1].lstrip("+")
                    dst = dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst
                    if dst in prot:
                        raise Refuse(f"{dst} is integrated by the merge step and promoted on the owner's sign, never pushed by a role")
        for target in targets + _arg_targets(args):
            if "$" in target or "`" in target:
                raise Refuse(f"write target {target!r} uses a variable the guard cannot resolve; spell the path out")
            if any(c in target for c in "*?["):
                target = str(Path(re.split(r"[*?\[]", target)[0] or ".") / "_")
            p = _norm(target, cwd)
            ok, why = may_write(cfg, role, p)
            if not ok:
                raise Refuse(f"write to {p}: {why}")


def check(payload: dict, cfg, role: str, env: dict) -> None:
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    job = env.get("WZ_JOB") or None
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = inp.get("file_path") or inp.get("notebook_path")
        if not fp:
            raise Refuse(f"{tool} without a path")
        p = _norm(fp, cwd)
        if is_secret(cfg, p):
            raise Refuse(f"{p} is a secret path")
        ok, why = may_write(cfg, role, p)
        if not ok:
            raise Refuse(f"write to {p}: {why}")
    elif tool == "Bash":
        check_bash(cfg, role, inp.get("command") or "", cwd, job)
    elif tool in ("Read", "Grep", "Glob", "NotebookRead"):
        fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
        if fp and is_secret(cfg, _norm(fp, cwd)):
            raise Refuse(f"{fp} is a secret path; agents never read secrets")


def _log(cfg, role: str, tool: str, reason: str) -> None:
    try:
        cfg.state.mkdir(parents=True, exist_ok=True)
        with open(cfg.state / "guard.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{role}\t{tool}\t{reason}\n")
    except OSError:
        pass


def main(stdin: str | None = None, env: dict | None = None) -> int:
    env = dict(os.environ if env is None else env)
    role = env.get("WZ_ROLE")
    if not role:
        return 0
    raw = sys.stdin.read() if stdin is None else stdin
    tool, cfg = None, None
    try:
        payload = json.loads(raw)
        tool = payload.get("tool_name")
        if payload.get("hook_event_name", "PreToolUse") != "PreToolUse":
            return 0
        cfg = _config.load(Path(env["WZ_CONFIG"]) if env.get("WZ_CONFIG") else None)
        cfg.role(role)
        check(payload, cfg, role, env)
        return 0
    except Refuse as r:
        _log(cfg, role, tool or "?", str(r))
        sys.stderr.write(f"[wz guard] role {role}: {r}. Do not retry a variant; if the work needs it, "
                         "put the request in your report and stop.\n")
        return 2
    except Exception as e:  # fail closed for anything that can write
        if tool is not None and tool not in WRITE_TOOLS:
            return 0
        if cfg is not None:
            _log(cfg, role, tool or "?", f"GUARD_ERROR {e.__class__.__name__}: {e}")
        sys.stderr.write(f"[wz guard] could not check this call ({e.__class__.__name__}: {e}); refusing it rather than "
                         "letting it through unchecked. Reads are unaffected.\n")
        return 2
