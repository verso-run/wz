"""The merge step: integrates finished job branches onto each git store's integration branch. Agents never merge.

For each `done` job with a branch, oldest first:
  1. ownership backstop: every file the branch changed must be owned by the job's role (the guard is a seatbelt;
     this is the check that cannot be talked around);
  2. the survivors go to the merge QUEUE (mergeq.py): stacked on the integration tip in a throwaway worktree in batches
     (a conflict is a verdict, not a fix), the store's checks run once per batch, a red batch is bisected to the bad
     branch, which is bounced alone while the rest land;
  3. green: move the integration branch to the checked commit (compare-and-swap) and push it if a remote is set.
A store under a FREEZE hold (a presign window) is skipped. Verdicts go to .wz/merge/<store>.json and the event
stream. Promotion from integration to main is the owner's sign
(`wz promote <store>`), never this step's.
"""
from __future__ import annotations

from . import approvals, flags, jobs, mergeq, release
from .worker import _branch_exists, _git, base_branch
from .util import glob_match, iso, read_json, write_json


def _owned_violations(cfg, role: str, store: str, files: list[str]) -> list[str]:
    globs = cfg.role(role)["owns"].get(store, []) if role in cfg.roles() else []
    return [f for f in files if not any(glob_match(f, g) for g in globs)]


def merge_store(cfg, store: str, dry_run: bool = False, say=print) -> list[dict]:
    """Land the store's finished job branches through the batch queue (mergeq.py). Store keys: `merge_batch` (branches
    per gate pass, default 8; 1 = one at a time), `merge_gate_runs` (check passes per call, default 24)."""
    s = cfg.stores()[store]
    repo = cfg.store_root(store)
    integ = base_branch(cfg, store)
    verdicts, ready = [], []
    cands = [j for j in jobs.all_jobs(cfg) if j.get("store") == store and j.get("status") == "done"
             and j.get("branch") and not j.get("merged") and not j.get("merge_refused")]
    for j in sorted(cands, key=lambda j: j.get("finished_t", 0)):
        branch = j["branch"]
        if not _branch_exists(repo, branch):
            continue
        v = {"job": j["id"], "role": j["role"], "branch": branch}
        if _git(repo, "rev-list", "--count", f"{integ}..{branch}").stdout.strip() == "0":
            v.update(verdict="empty", sha=_git(repo, "rev-parse", integ).stdout.strip())
            verdicts.append(v)
        else:
            files = [f for f in _git(repo, "diff", "--name-only", f"{integ}...{branch}").stdout.splitlines() if f]
            bad = _owned_violations(cfg, j["role"], store, files)
            if bad:
                v.update(verdict="ownership", files=bad[:20])
                verdicts.append(v)
            else:
                ready.append(mergeq.Entry(j["id"], branch, j["role"], j.get("finished_t", 0)))
    out = mergeq.run_queue(repo, integ, ready, s.get("checks", []), remote=s.get("remote", ""),
                           timeout=int(s.get("check_timeout", 1800)), batch_max=max(1, int(s.get("merge_batch", mergeq.DEFAULT_BATCH))),
                           max_gate_runs=int(s.get("merge_gate_runs", mergeq.DEFAULT_MAX_GATE_RUNS)), dry_run=dry_run, say=say)
    order = {j["id"]: i for i, j in enumerate(sorted(cands, key=lambda j: j.get("finished_t", 0)))}
    verdicts = sorted(verdicts + out["verdicts"], key=lambda v: order[v["job"]])      # oldest first, as before
    for v in verdicts:
        say(f"{store}: {v['job']} {v['branch']}: {v['verdict']}" + (f" {v.get('sha', '')[:12]}" if v.get("sha") else ""))
        if not dry_run:
            fresh = jobs.get(cfg, v["job"])
            if v["verdict"] in ("merged", "empty"):
                fresh["merged"] = v.get("sha")
            elif v["verdict"] in ("ownership", "conflict", "red"):
                fresh["merge_refused"] = v["verdict"]
            v["at"] = iso()
            fresh["merge_verdict"] = v
            jobs.save(cfg, fresh)
            flags.event(cfg, v["role"], "merge", v["job"], f"{v['verdict']} {v['branch']}", store=store)
    if ready:
        say(f"{store}: queue: {len(ready)} ready, {out['batches']} batch(es), {out['gate_runs']} check pass(es) "
            f"({out['bisect_runs']} to find a bad branch), {len(out['landed'])} landed")
    if verdicts and not dry_run:
        hist = read_json(cfg.state / "merge" / f"{store}.json") or []
        write_json(cfg.state / "merge" / f"{store}.json", (hist + verdicts)[-200:])
    return verdicts


def merge(cfg, store: str | None = None, dry_run: bool = False, say=print) -> list[dict]:
    out = []
    for name, s in cfg.stores().items():
        if (store and name != store) or s.get("kind") != "git" or not s.get("integration"):
            continue
        fz = release.frozen(cfg, name)
        if fz:
            say(f"{name}: frozen by {fz['id']} until {fz['expires']}: {fz['text']}")
            continue
        out += merge_store(cfg, name, dry_run=dry_run, say=say)
    return out


def promote(cfg, store: str, by: str = "") -> dict:
    """Ask the owner to sign moving main to the integration tip as it is now (a specific commit, not a branch name)."""
    s = cfg.stores().get(store)
    if not s or s.get("kind") != "git" or not s.get("integration"):
        raise ValueError(f"{store} is not a git store with an integration branch")
    repo = cfg.store_root(store)
    sha = _git(repo, "rev-parse", s["integration"]).stdout.strip()
    release.check_not_held(cfg, store, sha, cfg.rings()["order"][-1])
    main = s.get("main", "main")
    log = _git(repo, "log", "--oneline", f"{main}..{sha}", check=False).stdout.strip().splitlines()
    return approvals.request(cfg, f"Release {store}: move {main} to {sha[:12]} ({len(log)} commits)",
                             action={"type": "promote", "store": store, "to": main, "sha": sha},
                             why="\n".join(log[:30]), ring=cfg.rings()["order"][-1], by=by)
