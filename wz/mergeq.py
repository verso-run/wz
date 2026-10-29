"""The merge queue: land a BATCH of ready branches with one run of the gates, and find the bad one when the batch is red.

The engine knows git and a list of checks, nothing else: no jobs, no config, no records. `merge.py` feeds it entries
from the job records today; the same `run_queue` call takes entries from any other source (a table, a PR list).

One pass over `entries` (oldest first, at most `batch_max` at a time):
  1. STACK    merge the batch one branch at a time onto the integration tip in a throwaway worktree. A branch that does
              not merge is bounced alone (`conflict`); the rest stay in the stack.
  2. GATE     run the checks once on the top of the stack. Green: integration moves to that commit (compare-and-swap),
              every branch in the stack is `merged`, and the checks ran once for the whole batch.
  3. BISECT   red: binary-search the stack for the first prefix that is red (the tip with nothing on it is the known
              green end), O(log n) check runs. The branch that turns the prefix red is bounced alone (`red`); the green
              prefix below it lands; the branches above it are stacked again on the new tip and gated again.
  Integration only ever moves to a commit the checks passed on, so it never goes red, and a red branch costs the others
  one extra gate pass, not a stop.

Blame is by position: a branch that is red only together with an earlier one in the same batch is bounced, the earlier one
lands. If the TIP ITSELF fails the checks, nobody is blamed (`base-red`) and nothing moves.
`max_gate_runs` caps the check passes of one call; entries not reached keep waiting and get no verdict.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

DEFAULT_BATCH = 8
DEFAULT_MAX_GATE_RUNS = 24


@dataclass
class Entry:
    id: str
    branch: str
    role: str = ""
    t: float = 0.0
    meta: dict = field(default_factory=dict)


def git(repo, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def _gate(tree, checks: list[str], timeout: int) -> tuple[bool, str, str]:
    """Run the checks in `tree`, first failure stops: (green, failed_check, output tail)."""
    for check in checks:
        try:
            c = subprocess.run(check, shell=True, cwd=tree, capture_output=True, text=True, timeout=timeout)
            rc, out = c.returncode, c.stdout + c.stderr
        except subprocess.TimeoutExpired:
            rc, out = -1, "check timed out"
        if rc != 0:
            return False, check, out[-800:]
    return True, "", ""


def run_queue(repo, integ: str, entries: list[Entry], checks: list[str], *, remote: str = "", timeout: int = 1800,
              batch_max: int = DEFAULT_BATCH, max_gate_runs: int = DEFAULT_MAX_GATE_RUNS, dry_run: bool = False,
              say=print) -> dict:
    """Process `entries` against branch `integ` of `repo`. Returns {"verdicts": [...], "gate_runs": n, "landed": [...]}.
    A verdict is {"job": id, "branch", "role", "verdict": merged|would-merge|conflict|red|base-red, ...}."""
    verdicts: list[dict] = []
    stats = {"gate_runs": 0, "batches": 0, "landed": [], "bisect_runs": 0}
    pending = list(entries)
    if not pending:
        return {"verdicts": verdicts, **stats}
    tip = git(repo, "rev-parse", integ).stdout.strip()
    tmp = tempfile.mkdtemp(prefix="wz-mergeq-")
    seen: dict[str, tuple[bool, str, str]] = {}      # commit -> gate result; a commit is gated once per call
    landed_any = False

    def verdict(e: Entry, **kw) -> dict:
        v = {"job": e.id, "role": e.role, "branch": e.branch, **kw}
        verdicts.append(v)
        return v

    def gate(sha: str, why: str):
        if sha in seen:
            return seen[sha]
        if stats["gate_runs"] >= max_gate_runs:
            return None
        git(tmp, "checkout", "-q", "--detach", sha)
        git(tmp, "clean", "-fdxq", check=False)
        stats["gate_runs"] += 1
        if why == "bisect":
            stats["bisect_runs"] += 1
        seen[sha] = _gate(tmp, checks, timeout)
        return seen[sha]

    def land(new: str) -> str | None:
        """Move integ from `tip` to `new`. None on success, else the reason it did not move."""
        if dry_run:
            return None
        r = git(repo, "update-ref", f"refs/heads/{integ}", new, tip, check=False)
        return None if r.returncode == 0 else "integration moved while the queue ran: " + r.stderr[-200:]

    try:
        git(repo, "worktree", "add", "--detach", tmp, tip)
        while pending:
            batch, pending = pending[:batch_max], pending[batch_max:]
            stats["batches"] += 1
            # 1. STACK
            git(tmp, "checkout", "-q", "--detach", tip)
            stack: list[tuple[Entry, str]] = []
            for e in batch:
                m = git(tmp, "merge", "--no-ff", "--no-edit", "-m", f"wz merge {e.branch} ({e.id}, {e.role})", e.branch, check=False)
                if m.returncode != 0:
                    git(tmp, "merge", "--abort", check=False)
                    git(tmp, "reset", "-q", "--hard", stack[-1][1] if stack else tip)
                    verdict(e, verdict="conflict", detail=(m.stdout + m.stderr)[-600:])
                    continue
                stack.append((e, git(tmp, "rev-parse", "HEAD").stdout.strip()))
            if not stack:
                continue
            # 2. GATE the whole stack once
            r = gate(stack[-1][1], "batch")
            if r is None:
                pending = [e for e, _ in stack] + pending       # out of gate runs: wait for the next call
                break
            if r[0]:
                bad = land(stack[-1][1])
                if bad:
                    pending = [e for e, _ in stack] + pending
                    say(f"queue: {bad}")
                    break
                for e, sha in stack:
                    verdict(e, verdict="would-merge" if dry_run else "merged", sha=sha, batch=len(stack))
                    stats["landed"].append(e.id)
                tip = stack[-1][1]
                landed_any = landed_any or not dry_run
                continue
            # 3. BISECT: lo = longest known-green prefix (0 = the tip), hi = shortest known-red one
            lo, hi, red = 0, len(stack), r
            exhausted = False
            while hi - lo > 1:
                mid = (lo + hi) // 2
                g = gate(stack[mid - 1][1], "bisect")
                if g is None:
                    exhausted = True
                    break
                if g[0]:
                    lo = mid
                else:
                    hi, red = mid, g
            if exhausted:
                pending = [e for e, _ in stack] + pending
                break
            culprit = stack[hi - 1][0]
            if hi == 1:        # nothing below it: is the tip itself red?
                g = gate(tip, "bisect")
                if g is None:
                    pending = [e for e, _ in stack] + pending
                    break
                if not g[0]:
                    for e, _ in stack:
                        verdict(e, verdict="base-red", check=g[1], detail=g[2])
                    say(f"queue: {integ} itself fails the checks ({g[1]}); nothing lands until it is fixed")
                    pending = []
                    break
            if lo > 0:
                bad = land(stack[lo - 1][1])
                if bad:
                    pending = [e for e, _ in stack] + pending
                    say(f"queue: {bad}")
                    break
                for e, sha in stack[:lo]:
                    verdict(e, verdict="would-merge" if dry_run else "merged", sha=sha, batch=len(stack))
                    stats["landed"].append(e.id)
                tip = stack[lo - 1][1]
                landed_any = landed_any or not dry_run
            verdict(culprit, verdict="red", check=red[1], detail=red[2], bisected=len(stack))
            pending = [e for e, _ in stack[hi:]] + pending       # re-stacked on the new tip next round
        if landed_any and remote:
            p = git(repo, "push", remote, integ, check=False)
            if p.returncode != 0:
                for v in verdicts:
                    if v["verdict"] == "merged":
                        v["push"] = "failed: " + p.stderr[-300:]
    finally:
        git(repo, "worktree", "remove", "--force", tmp, check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return {"verdicts": verdicts, **stats}
