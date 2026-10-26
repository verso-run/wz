"""Serving jobs: `wz serve` picks ready jobs and starts one supervisor per job; the supervisor runs the agent.

serve (a timer calls it every minute, quick):
  for each role: skip if halted, over budget or at its cap; otherwise claim the next ready job (priority, then age;
  dependency done; leases free) and start `wz _run <job>` in its own session.

the supervisor (`wz _run <job>`, one per job):
  takes the job's leases, makes its git worktree on a fresh branch (wz/<role>/<job>) from the integration branch,
  writes the job's commit unlock, runs the agent headless with the role's charter and the guard hooks, waits up to
  the job's timeout, then kills the agent's own process group (and nothing else), reads the closing declaration,
  records cost, files follow-ups, raises the flag, and releases leases and the unlock.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path

from . import budget, charters, flags, jobs, leases, records, unlock
from .util import iso, now, read_json, write_json

DECL_KEYS = ("status", "block_reason", "result", "evidence", "owner_asks", "lead_asks", "followups")
CONTRACT = """End your final message with ONE fenced ```json block with exactly these keys:
{"status": "done|blocked", "block_reason": "<only when blocked: one line why>", "result": "<one line, the outcome itself>",
 "evidence": ["<path, command or number a reader can check>"], "owner_asks": ["<what only the owner can do, and the exact word or click>"],
 "lead_asks": ["<what the lead must decide or unblock>"], "followups": [{"role": "<role>", "task": "<one job>", "evidence_of_done": "<how it will be checked>"}]}
"done" only when the evidence of done is met; otherwise "blocked" with a block_reason. No declaration means the job failed."""


# ---- halt (the andon cord) ----------------------------------------------------------------------------------------
def _halt_path(cfg, lane: str) -> Path:
    return cfg.state / "halt" / f"{lane}.json"


def halt(cfg, lane: str, why: str, by: str = "") -> None:
    write_json(_halt_path(cfg, lane), {"lane": lane, "why": why, "by": by, "at": iso()})
    flags.event(cfg, by or "owner", "halt", lane, why)


def resume(cfg, lane: str) -> bool:
    p = _halt_path(cfg, lane)
    if not p.exists():
        return False
    p.unlink()
    flags.event(cfg, "lead", "resume", lane, "")
    return True


def halted(cfg, role: str) -> str | None:
    for lane in ("all", role):
        rec = read_json(_halt_path(cfg, lane))
        if isinstance(rec, dict):
            return f"halted ({lane}): {rec.get('why', '')}"
    return None


# ---- serve ----------------------------------------------------------------------------------------------------------
def wz_argv() -> list[str]:
    here = Path(__file__).resolve().parent
    script = here.parent / "bin" / "wz"
    if script.is_file():
        return [sys.executable, str(script)]
    return [sys.executable, "-m", "wz"]


def serve(cfg, role: str | None = None, wait: bool = False, dry_run: bool = False, say=print) -> list[str]:
    started = []
    for r in ([role] if role else list(cfg.roles())):
        cfg.role(r)
        why = halted(cfg, r)
        if why:
            say(f"{r}: {why}")
            continue
        ok, why = budget.allowed(cfg, r)
        if not ok:
            say(f"{r}: {why}")
            continue
        slots = cfg.role(r)["cap"] - len(jobs.running(cfg, r))
        while slots > 0:
            with jobs.lock(cfg):
                j, waits = jobs.next_ready(cfg, r)
                for jid, w in waits:
                    say(f"{r}: {jid} {w}")
                if j is None:
                    break
                if dry_run:
                    say(f"{r}: would start {j['id']}: {j['task'][:80]}")
                    break
                j["status"] = "running"
                j["claimed"] = iso()
                jobs.save(cfg, j)
            started.append(j["id"])
            slots -= 1
            say(f"{r}: starting {j['id']}")
            if wait:
                run_job(cfg, j["id"])
            else:
                _spawn(cfg, j["id"])
    return started


def _spawn(cfg, job_id: str) -> int:
    logs = cfg.state / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, WZ_CONFIG=str(cfg.path))
    with open(logs / f"{job_id}.supervisor.log", "a") as log:
        p = subprocess.Popen(wz_argv() + ["_run", job_id], stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, start_new_session=True, cwd=str(cfg.root))
    return p.pid


# ---- the supervisor -------------------------------------------------------------------------------------------------
def _git(repo, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def _branch_exists(repo, name: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode == 0


def base_branch(cfg, store: str) -> str:
    """The branch jobs start from: the integration branch (created from main if missing), else main."""
    s = cfg.stores()[store]
    repo = cfg.store_root(store)
    main = s.get("main", "main")
    integ = s.get("integration")
    if integ:
        if not _branch_exists(repo, integ):
            _git(repo, "branch", integ, main)
        return integ
    return main


def prepare(cfg, job: dict) -> tuple[Path, str | None, Path | None, str | None]:
    """(working directory, branch, worktree path, base branch) for the job."""
    store = job["store"]
    s = cfg.stores()[store]
    root = cfg.store_root(store)
    if s.get("kind") != "git" or not job.get("worktree", True):
        return root, None, None, None
    base = base_branch(cfg, store)
    branch = f"wz/{job['role']}/{job['id']}"
    wt = cfg.worktree_root(store) / f"{job['role']}.{job['id']}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists():
        return wt, branch, wt, base
    if _branch_exists(root, branch):
        _git(root, "worktree", "add", str(wt), branch)
    else:
        _git(root, "worktree", "add", "-b", branch, str(wt), base)
    return wt, branch, wt, base


def build_prompt(cfg, job: dict, cwd: Path, branch: str | None) -> str:
    role = job["role"]
    state_md = cfg.role_dir(role) / "STATE.md"
    state = state_md.read_text()[:4000] if state_md.is_file() else "(none yet)"
    parts = [
        f"You are the {role} role of project {cfg.project}, serving job {job['id']}.",
        "## Task\n" + job["task"],
    ]
    if job.get("brief"):
        parts.append(f"## Brief\nRead {cfg.root / job['brief']} first. Your report goes in its `## Report` section.")
    where = f"Working directory: {cwd}" + (f" (branch {branch}; the merge step integrates it, never you)" if branch else "")
    parts.append("## Where you work\n" + where + f"\nScratch for temp files and evidence: {cfg.scratch(role)}"
                 f"\nYour notes from earlier jobs: {state_md}")
    parts.append("## Evidence of done\n" + (job.get("evidence") or
                 "Name what you checked and how, so a reader can repeat it; a number names the command that produced it."))
    parts.append("## Scope\nThis job is this task and nothing else: name follow-ups in the declaration instead of doing them. "
                 "Run every command in the foreground; nothing you start may outlive this job. "
                 + ("Your job carries a commit unlock for its own branch." if job.get("unlock") else "This job has no commit unlock."))
    parts.append("## Your notes (roles/" + role + "/STATE.md)\n" + state)
    lessons = cfg.role_dir(role) / "LESSONS.md"
    if lessons.is_file():
        parts.append("## Lessons (roles/" + role + "/LESSONS.md)\n" + lessons.read_text()[-3000:])
    parts.append("## Before you finish\nRewrite " + str(state_md) + " whole, one screen: what the next job on this role needs to know.")
    parts.append("## Closing declaration\n" + CONTRACT)
    return "\n\n".join(parts)


def build_command(cfg, role: str, prompt: str, resume: str | None = None) -> list[str]:
    a, r = cfg.agent(), cfg.role(role)
    cmd = shlex.split(a["command"]) + [
        "-p", prompt, "--append-system-prompt-file", str(cfg.charter_path(role)),
        "--settings", str(cfg.role_settings), "--output-format", "json", "--permission-mode", a["permission_mode"],
    ]
    if r.get("model"):
        cmd += ["--model", r["model"]]
    if a.get("pass_effort") and r.get("effort"):
        cmd += ["--effort", r["effort"]]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def build_env(cfg, job: dict, cwd: Path) -> dict:
    role = job["role"]
    env = dict(os.environ)
    env.update(WZ_ROLE=role, WZ_JOB=job["id"], WZ_CONFIG=str(cfg.path), WZ_HOME=str(cfg.root),
               WZ_SCRATCH=str(cfg.scratch(role)), WZ_WORKTREE=str(cwd))
    if job.get("lease"):
        env[leases.HELD_ENV] = ",".join(job["lease"])
        env[leases.HOLDER_ENV] = job["id"]
    acct = cfg.role(role).get("account")
    cdir = cfg.account(acct).get("config_dir") if acct else ""
    if cdir:
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(cdir)
    return env


def execute(cmd: list[str], cwd: Path, env: dict, timeout_s: float, out_path: Path, err_path: Path,
            on_start=None) -> tuple[int, bool]:
    """Run the agent in its own process group; on timeout kill that group. Afterwards sweep the group once more,
    so nothing the agent started outlives it. Never touches any other process. Returns (exit code, timed out)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as out, open(err_path, "w") as err:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                start_new_session=True, text=True)
        if on_start:
            on_start(proc.pid)
        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        _killpg(proc.pid, signal.SIGKILL)
    return proc.returncode, timed_out


def _killpg(pgid: int, sig) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def parse_result(stdout: str) -> dict | None:
    for line in reversed([x for x in stdout.split("\n") if x.strip()]):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (obj.get("type") == "result" or "result" in obj):
            return obj
    return None


_FENCE = re.compile(r"```json\s*\n(.*?)```", re.S)


def declaration(text: str) -> tuple[dict | None, str]:
    """(the closing declaration, '') or (None, what is wrong with it)."""
    blocks = _FENCE.findall(text or "")
    if not blocks:
        return None, "no fenced json block"
    try:
        d = json.loads(blocks[-1])
    except json.JSONDecodeError as e:
        return None, f"the last json block does not parse ({e.msg})"
    if not isinstance(d, dict):
        return None, "the json block is not an object"
    st = d.get("status")
    if st not in ("done", "blocked"):
        return None, f"status must be done or blocked, not {st!r}"
    if st == "blocked" and not str(d.get("block_reason") or "").strip():
        return None, "blocked without a block_reason"
    if st == "done" and str(d.get("block_reason") or "").strip():
        return None, "done with a block_reason"
    return d, ""


def run_job(cfg, job_id: str) -> dict:
    job = jobs.get(cfg, job_id)
    names = job.get("lease", [])
    fds = leases.acquire(cfg, names, holder=job_id, hold_s=job["timeout_s"]) if names else []
    if fds is None:
        return jobs.set_status(cfg, job_id, "queued", "a lease was taken before the job could start")
    wt = None
    try:
        if not cfg.charter_path(job["role"]).is_file() or not cfg.role_settings.is_file():
            charters.write_all(cfg)
        cwd, branch, wt, base = prepare(cfg, job)
        cfg.scratch(job["role"]).mkdir(parents=True, exist_ok=True)
        if job.get("unlock"):
            unlock.grant(cfg, job["role"], job=job_id, hours=job["timeout_s"] / 3600 + 1, by="job")
        job.update(supervisor_pid=os.getpid(), started=iso(), started_t=now(), cwd=str(cwd), branch=branch, base=base,
                   worktree_path=str(wt) if wt else None)
        jobs.save(cfg, job)

        def _record_pid(pid):
            job["agent_pid"] = pid
            jobs.save(cfg, job)

        logs = cfg.state / "logs"
        prompt = build_prompt(cfg, job, cwd, branch)
        env = build_env(cfg, job, cwd)
        rc, timed_out = execute(build_command(cfg, job["role"], prompt), cwd, env, job["timeout_s"],
                                logs / f"{job_id}.out", logs / f"{job_id}.err", _record_pid)
        res = parse_result((logs / f"{job_id}.out").read_text())
        cost = float((res or {}).get("total_cost_usd") or 0)
        text = str((res or {}).get("result") or "")
        decl, problem = declaration(text)
        if decl is None and not timed_out and res and res.get("session_id"):
            fix = (f"Your final message has no valid closing declaration ({problem}). Reply now with only the fenced "
                   "json block the task asked for.")
            remaining = max(300, job["timeout_s"] - (now() - job["started_t"]))
            rc2, timed_out = execute(build_command(cfg, job["role"], fix, resume=res["session_id"]), cwd, env,
                                     min(600, remaining), logs / f"{job_id}.fix.out", logs / f"{job_id}.fix.err")
            res2 = parse_result((logs / f"{job_id}.fix.out").read_text())
            cost += float((res2 or {}).get("total_cost_usd") or 0)
            decl, problem = declaration(str((res2 or {}).get("result") or ""))
        return finish(cfg, job, decl, problem, rc, timed_out, cost, text)
    except Exception as e:
        job = jobs.get(cfg, job_id)
        job.update(status="failed", finished=iso(), error=f"{e.__class__.__name__}: {e}")
        jobs.save(cfg, job)
        flags.event(cfg, job["role"], "job", job_id, f"failed: {job['error']}", status="failed")
        return job
    finally:
        leases.release(cfg, names, fds)
        unlock.revoke(cfg, job["role"], job=job_id)
        if wt is not None:
            _tidy_worktree(cfg, job_id)


def finish(cfg, job: dict, decl: dict | None, problem: str, rc: int, timed_out: bool, cost: float, text: str) -> dict:
    job = {**jobs.get(cfg, job["id"]), **{k: job[k] for k in ("started", "started_t", "cwd", "branch", "base") if k in job}}
    if decl is not None:
        status = decl["status"]
        result = {k: decl.get(k) for k in DECL_KEYS if k in decl}
    else:
        status = "failed"
        why = f"timed out after {job['timeout_s']} s" if timed_out else (problem or f"agent exited {rc}")
        result = {"status": "failed", "result": why, "tail": text[-800:]}
    job.update(status=status, finished=iso(), finished_t=now(), exit_code=rc, timed_out=timed_out,
               cost_usd=round(cost, 4), result=result)
    jobs.save(cfg, job)
    budget.record(cfg, job["role"], job["id"], cost)
    for f in (decl or {}).get("followups") or []:
        if isinstance(f, dict) and f.get("task"):
            records.ledger_add(cfg, "followups", {"from": job["id"], "role": f.get("role", ""), "task": f["task"],
                                                  "evidence of done": f.get("evidence_of_done", "")})
    flags.event(cfg, job["role"], "job", job["id"], f"{status}: {result.get('result') or result.get('block_reason') or ''}",
                status=status)
    return job


def _tidy_worktree(cfg, job_id: str) -> None:
    """Remove the job's worktree when it is clean (the branch stays for the merge step); keep a dirty one and say so."""
    job = jobs.get(cfg, job_id)
    wt = job.get("worktree_path")
    if not wt or not Path(wt).exists():
        return
    repo = cfg.store_root(job["store"])
    dirty = _git(wt, "status", "--porcelain", check=False).stdout.strip()
    if dirty:
        job["worktree_dirty"] = dirty.splitlines()[:20]
        jobs.save(cfg, job)
        return
    _git(repo, "worktree", "remove", wt, check=False)
    base, branch = job.get("base"), job.get("branch")
    if base and branch:
        ahead = _git(repo, "rev-list", "--count", f"{base}..{branch}", check=False).stdout.strip()
        if ahead == "0":
            _git(repo, "branch", "-D", branch, check=False)
            job["branch_removed"] = "no commits"
            jobs.save(cfg, job)
