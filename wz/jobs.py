"""The job queue. One JSON file per job under .wz/jobs/; `wz serve` picks from it, `wz job` edits it.

A job: role, task, priority (lower runs first, default 50), an optional dependency on another job, a timeout,
resource leases, a per-job commit unlock, an optional brief and evidence-of-done line. Statuses:

  queued    waiting to be served (also while its dependency or a lease is not ready)
  held      parked by the lead; not served until released. A held job with an open `gate` waits on the OWNER instead:
            only `wz gate pass` (the owner's own shell) makes it queued; `release` refuses it, and so does every other path
  running   a supervisor process owns it
  done      declared done by the agent, with evidence
  blocked   declared blocked by the agent, with a reason; jobs that depend on it stay waiting
  failed    no valid declaration, a crash or a timeout
  cancelled removed by the lead
"""
from __future__ import annotations

from . import leases as _leases
from .util import iso, locked, now, parse_duration, read_json, write_json

TERMINAL = {"done", "blocked", "failed", "cancelled"}
STATUSES = ("queued", "held", "running", "done", "blocked", "failed", "cancelled")


class JobError(Exception):
    pass


def _dir(cfg):
    return cfg.state / "jobs"


def lock(cfg):
    return locked(cfg.state / "jobs.lock")


def path(cfg, job_id: str):
    return _dir(cfg) / f"{job_id}.json"


def get(cfg, job_id: str) -> dict:
    j = read_json(path(cfg, job_id))
    if not isinstance(j, dict):
        raise JobError(f"no job {job_id}")
    return j


def save(cfg, job: dict) -> None:
    job["updated"] = iso()
    write_json(path(cfg, job["id"]), job)


def all_jobs(cfg, role: str | None = None) -> list[dict]:
    out = []
    d = _dir(cfg)
    if d.is_dir():
        for p in sorted(d.glob("job-*.json")):
            j = read_json(p)
            if isinstance(j, dict) and (role is None or j.get("role") == role):
                out.append(j)
    return out


def _next_id(cfg) -> str:
    seq_path = cfg.state / "jobs.seq"
    n = int((read_json(seq_path) or {}).get("next", 1))
    write_json(seq_path, {"next": n + 1})
    return f"job-{n:04d}"


def add(cfg, role: str, task: str, priority: int = 50, after: str | None = None, timeout=None, lease=(),
        unlock: bool = True, brief: str | None = None, evidence: str | None = None, worktree: bool = True,
        by: str = "", gate: str | None = None, gate_state: str = "open") -> dict:
    r = cfg.role(role)
    if not task.strip():
        raise JobError("a job needs a task")
    if gate is not None and not gate.strip():
        raise JobError("a gate needs the words of what the owner decides")
    if lease:
        _leases.check_names(cfg, lease)
    with lock(cfg):
        if after:
            get(cfg, after)
        job = {
            "id": _next_id(cfg), "role": role, "task": task.strip(), "priority": int(priority),
            "after": after, "timeout_s": parse_duration(timeout or r["timeout"]), "lease": sorted(set(lease)),
            "unlock": bool(unlock), "brief": brief, "evidence": evidence, "worktree": bool(worktree),
            "store": r["store"], "status": "queued", "created": iso(), "created_t": now(), "by": by,
        }
        if gate:
            job["gate"] = {"text": gate.strip(), "state": gate_state}
            if gate_state == "open":
                job["status"] = "held"
                job["notes"] = [f"{iso()} held: waiting on the owner: {gate.strip()}"]
        save(cfg, job)
    return job


def set_status(cfg, job_id: str, status: str, note: str = "", allowed_from: set | None = None) -> dict:
    with lock(cfg):
        j = get(cfg, job_id)
        if allowed_from is not None and j["status"] not in allowed_from:
            raise JobError(f"{job_id} is {j['status']}; cannot make it {status}")
        if status in ("queued", "running") and open_gate(j):
            raise JobError(f"{job_id} waits on the owner's gate ({open_gate(j)}); only the owner passes it: `wz gate pass {job_id}`")
        j["status"] = status
        if note:
            j.setdefault("notes", []).append(f"{iso()} {status}: {note}")
        save(cfg, j)
        return j


def open_gate(job: dict) -> str | None:
    """The words of the owner's gate on this job while it is still shut, else None."""
    g = job.get("gate")
    return g.get("text") if isinstance(g, dict) and g.get("state") == "open" else None


def gates(cfg, role: str | None = None, state: str = "open") -> list[dict]:
    """Jobs carrying a gate in `state` ('open' or 'passed'), in queue order. An open gate on a cancelled job is not
    waiting on anyone, so it is not listed."""
    out = [j for j in all_jobs(cfg, role) if isinstance(j.get("gate"), dict) and j["gate"].get("state") == state]
    if state == "open":
        out = [j for j in out if j["status"] == "held"]
    return queue_order(out)


def pass_gate(cfg, job_id: str, by: str = "owner", note: str = "") -> dict:
    """The owner's go-ahead: the held job becomes queued. The caller (cli) has already refused a role session."""
    with lock(cfg):
        j = get(cfg, job_id)
        g = j.get("gate")
        if not isinstance(g, dict):
            raise JobError(f"{job_id} has no gate")
        if g.get("state") != "open":
            raise JobError(f"{job_id}'s gate was already passed")
        if j["status"] != "held":
            raise JobError(f"{job_id} is {j['status']}; there is nothing left to pass")
        g.update(state="passed", passed=iso(), passed_by=by, **({"note": note} if note else {}))
        j["status"] = "queued"
        j.setdefault("notes", []).append(f"{iso()} queued: the owner passed the gate ({g['text']})" + (f" - {note}" if note else ""))
        save(cfg, j)
        return j


def cancel(cfg, job_id: str, why: str = "") -> dict:
    return set_status(cfg, job_id, "cancelled", why or "cancelled", {"queued", "held"})


def hold(cfg, job_id: str, why: str = "") -> dict:
    return set_status(cfg, job_id, "held", why or "held", {"queued"})


def release(cfg, job_id: str) -> dict:  # an open gate is refused inside set_status
    return set_status(cfg, job_id, "queued", "released", {"held"})


def wait_reason(cfg, job: dict, by_id: dict) -> str | None:
    """Why a queued job cannot start now, or None when it can."""
    dep = job.get("after")
    if dep:
        d = by_id.get(dep)
        if d is None:
            return f"depends on {dep}, which does not exist"
        if open_gate(d):
            return f"waits for {dep}, which waits on the owner: {open_gate(d)} (`wz gate pass {dep}`)"
        if d["status"] != "done":
            return f"waits for {dep} ({d['status']})"
    for name in job.get("lease", []):
        if name not in cfg.resources():
            return f"resource {name} is no longer declared"
        if not _leases.is_free(cfg, name):
            return f"resource {name} is leased"
    return None


def queue_order(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: (j.get("priority", 50), j.get("created_t", 0)))


def running(cfg, role: str | None = None) -> list[dict]:
    return [j for j in all_jobs(cfg, role) if j["status"] == "running"]


def next_ready(cfg, role: str) -> tuple[dict | None, list[tuple[str, str]]]:
    """(the job to serve next for `role` or None, [(job id, why it waits)] for the queued jobs passed over)."""
    every = all_jobs(cfg)
    by_id = {j["id"]: j for j in every}
    waits = []
    for j in queue_order([j for j in every if j["role"] == role and j["status"] == "queued"]):
        why = wait_reason(cfg, j, by_id)
        if why is None:
            return j, waits
        waits.append((j["id"], why))
    return None, waits


def remint(cfg, job_id: str, timeout=None, task: str | None = None, by: str = "") -> dict:
    """A failed, blocked or timed-out job comes back as a new job (same role, lease, brief and evidence), and every
    queued or held job that waited on the old one is re-pointed to the new one, so nothing is orphaned."""
    old = get(cfg, job_id)
    if old["status"] not in ("failed", "blocked", "cancelled"):
        raise JobError(f"{job_id} is {old['status']}; only a failed, blocked or cancelled job is reminted")
    if old.get("reminted_as"):
        raise JobError(f"{job_id} was already reminted as {old['reminted_as']}")
    to = timeout or (old["timeout_s"] * 2 if old.get("timed_out") else old["timeout_s"])
    new = add(cfg, old["role"], task or old["task"], priority=old["priority"], after=old.get("after"), timeout=to,
              lease=old.get("lease", []), unlock=old.get("unlock", True), brief=old.get("brief"),
              evidence=old.get("evidence"), worktree=old.get("worktree", True), by=by,
              gate=(old.get("gate") or {}).get("text"), gate_state=(old.get("gate") or {}).get("state", "open"))
    with lock(cfg):
        o = get(cfg, job_id)
        o["reminted_as"] = new["id"]
        save(cfg, o)
        n = get(cfg, new["id"])
        n["reminted_from"] = job_id
        save(cfg, n)
        moved = []
        for j in all_jobs(cfg):
            if j.get("after") == job_id and j["status"] in ("queued", "held"):
                j["after"] = new["id"]
                j.setdefault("notes", []).append(f"{iso()} re-pointed from {job_id} to {new['id']}")
                save(cfg, j)
                moved.append(j["id"])
    n["repointed"] = moved
    return n
