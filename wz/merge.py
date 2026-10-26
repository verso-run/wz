"""The merge step: integrates finished job branches onto each git store's integration branch. Agents never merge.

For each `done` job with a branch, oldest first:
  1. ownership backstop: every file the branch changed must be owned by the job's role (the guard is a seatbelt;
     this is the check that cannot be talked around);
  2. merge it onto the integration tip in a throwaway worktree (a conflict is a verdict, not a fix);
  3. run the store's checks there;
  4. green: move the integration branch to the merge commit (compare-and-swap) and push it if a remote is set.
A store under a FREEZE hold (a presign window) is skipped. Verdicts go to .wz/merge/<store>.json and the event
stream. Promotion from integration to main is the owner's sign
(`wz promote <store>`), never this step's.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile

from . import approvals, flags, jobs, release
from .worker import _branch_exists, _git, base_branch
from .util import glob_match, iso, read_json, write_json


def _owned_violations(cfg, role: str, store: str, files: list[str]) -> list[str]:
    globs = cfg.role(role)["owns"].get(store, []) if role in cfg.roles() else []
    return [f for f in files if not any(glob_match(f, g) for g in globs)]


def merge_store(cfg, store: str, dry_run: bool = False, say=print) -> list[dict]:
    s = cfg.stores()[store]
    repo = cfg.store_root(store)
    integ = base_branch(cfg, store)
    verdicts = []
    cands = [j for j in jobs.all_jobs(cfg) if j.get("store") == store and j.get("status") == "done"
             and j.get("branch") and not j.get("merged") and not j.get("merge_refused")]
    for j in sorted(cands, key=lambda j: j.get("finished_t", 0)):
        branch = j["branch"]
        v = {"job": j["id"], "role": j["role"], "branch": branch, "at": iso()}
        if not _branch_exists(repo, branch):
            continue
        tip = _git(repo, "rev-parse", integ).stdout.strip()
        ahead = _git(repo, "rev-list", "--count", f"{integ}..{branch}").stdout.strip()
        if ahead == "0":
            v.update(verdict="empty", sha=tip)
        else:
            files = [f for f in _git(repo, "diff", "--name-only", f"{integ}...{branch}").stdout.splitlines() if f]
            bad = _owned_violations(cfg, j["role"], store, files)
            if bad:
                v.update(verdict="ownership", files=bad[:20])
            else:
                v.update(_try_merge(repo, s, integ, tip, branch, j, dry_run))
        verdicts.append(v)
        say(f"{store}: {j['id']} {branch}: {v['verdict']}" + (f" {v.get('sha', '')[:12]}" if v.get("sha") else ""))
        if not dry_run:
            fresh = jobs.get(cfg, j["id"])
            if v["verdict"] in ("merged", "empty"):
                fresh["merged"] = v.get("sha")
            elif v["verdict"] in ("ownership", "conflict", "red"):
                fresh["merge_refused"] = v["verdict"]
            fresh["merge_verdict"] = v
            jobs.save(cfg, fresh)
            flags.event(cfg, j["role"], "merge", j["id"], f"{v['verdict']} {branch}", store=store)
    if verdicts and not dry_run:
        hist = read_json(cfg.state / "merge" / f"{store}.json") or []
        write_json(cfg.state / "merge" / f"{store}.json", (hist + verdicts)[-200:])
    return verdicts


def _try_merge(repo, s: dict, integ: str, tip: str, branch: str, job: dict, dry_run: bool) -> dict:
    tmp = tempfile.mkdtemp(prefix="wz-merge-")
    try:
        _git(repo, "worktree", "add", "--detach", tmp, tip)
        m = _git(tmp, "merge", "--no-ff", "--no-edit", "-m", f"wz merge {branch} ({job['id']}, {job['role']})", branch, check=False)
        if m.returncode != 0:
            _git(tmp, "merge", "--abort", check=False)
            return {"verdict": "conflict", "detail": (m.stdout + m.stderr)[-600:]}
        for check in s.get("checks", []):
            try:
                c = subprocess.run(check, shell=True, cwd=tmp, capture_output=True, text=True,
                                   timeout=int(s.get("check_timeout", 1800)))
                rc, out = c.returncode, c.stdout + c.stderr
            except subprocess.TimeoutExpired:
                rc, out = -1, "check timed out"
            if rc != 0:
                return {"verdict": "red", "check": check, "detail": out[-800:]}
        new = _git(tmp, "rev-parse", "HEAD").stdout.strip()
        if dry_run:
            return {"verdict": "would-merge", "sha": new}
        _git(repo, "update-ref", f"refs/heads/{integ}", new, tip)
        if s.get("remote"):
            p = _git(repo, "push", s["remote"], integ, check=False)
            if p.returncode != 0:
                return {"verdict": "merged", "sha": new, "push": "failed: " + p.stderr[-300:]}
        return {"verdict": "merged", "sha": new}
    finally:
        _git(repo, "worktree", "remove", "--force", tmp, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


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
