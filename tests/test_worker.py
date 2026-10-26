import json
import time

from conftest import git
from wz import budget, flags, jobs, worker, unlock
from wz.util import pid_alive


def calls(tmp_path):
    p = tmp_path / "claude-calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_end_to_end_done(project, tmp_path):
    j = jobs.add(project, "app", "add a greeting", evidence="src file exists")
    started = worker.serve(project, role="app", wait=True, say=lambda *_: None)
    assert started == [j["id"]]
    j = jobs.get(project, j["id"])
    assert j["status"] == "done", j
    assert j["cost_usd"] == 0.25 and budget.spent(project) == 0.25
    app = project.store_root("app")
    assert git(app, "rev-parse", "--verify", "wz/app/job-0001")
    assert "src/job-0001.txt" in git(app, "show", "--name-only", "--format=", "wz/app/job-0001")
    assert git(app, "rev-parse", "--verify", "integration")
    assert not (project.worktree_root("app") / "app.job-0001").exists()
    assert not unlock.has(project, "app", "job-0001")
    c = calls(tmp_path)[0]
    assert c["role"] == "app" and c["job"] == "job-0001"
    args = c["args"]
    assert args[args.index("--append-system-prompt-file") + 1] == str(project.charter_path("app"))
    assert args[args.index("--model") + 1] == "sonnet" and args[args.index("--effort") + 1] == "high"
    prompt = args[args.index("-p") + 1]
    assert "add a greeting" in prompt and "src file exists" in prompt and "```json" in prompt
    ev = [e for e in flags.events(project) if e["kind"] == "job"]
    assert ev[-1]["ref"] == "job-0001" and ev[-1]["status"] == "done"


def test_blocked_and_no_commit_branch_removed(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "blocked")
    j = jobs.add(project, "app", "measure")
    worker.serve(project, role="app", wait=True, say=lambda *_: None)
    j = jobs.get(project, j["id"])
    assert j["status"] == "blocked" and j["result"]["block_reason"] == "the bench is not powered"
    assert j.get("branch_removed") == "no commits"


def test_missing_declaration_gets_one_corrective_turn(project, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nodecl")
    j = jobs.add(project, "writer", "draft a letter")
    worker.serve(project, role="writer", wait=True, say=lambda *_: None)
    j = jobs.get(project, j["id"])
    assert j["status"] == "done" and j["result"]["result"] == "declared on the corrective turn"
    c = calls(tmp_path)
    assert len(c) == 2 and "--resume" in c[1]["args"]
    assert j["cost_usd"] == 0.5


def test_timeout_kills_only_its_own_group(project, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    monkeypatch.setenv("FAKE_PIDFILE", str(tmp_path / "child.pid"))
    j = jobs.add(project, "writer", "hang", timeout="2s")
    t0 = time.time()
    worker.serve(project, role="writer", wait=True, say=lambda *_: None)
    assert time.time() - t0 < 30
    j = jobs.get(project, j["id"])
    assert j["status"] == "failed" and j["timed_out"] and "timed out" in j["result"]["result"]
    child = int((tmp_path / "child.pid").read_text())
    for _ in range(50):
        if not pid_alive(child):
            break
        time.sleep(0.1)
    assert not pid_alive(child)
    assert not pid_alive(j["agent_pid"])


def test_followups_and_asks(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "asks")
    j = jobs.add(project, "writer", "draft")
    worker.serve(project, role="writer", wait=True, say=lambda *_: None)
    assert jobs.get(project, j["id"])["result"]["owner_asks"][0] == "approve the logo"
    fu = (project.root / "ledgers" / "FOLLOWUPS.md").read_text()
    assert "| FU-001 |" in fu and "test the thing" in fu and j["id"] in fu


def test_halt_budget_and_cap(project, monkeypatch):
    jobs.add(project, "app", "x")
    worker.halt(project, "app", "smoke", by="owner")
    assert worker.serve(project, role="app", wait=True, say=lambda *_: None) == []
    assert worker.resume(project, "app")
    budget.record(project, "app", "job-x", 10.0)
    msgs = []
    assert worker.serve(project, role="app", wait=True, say=msgs.append) == []
    assert "budget spent" in msgs[0]
    (project.state / "budget.jsonl").unlink()
    jobs.add(project, "app", "y")
    fake_running = jobs.add(project, "app", "z", priority=1)
    jobs.set_status(project, fake_running["id"], "running")
    assert worker.serve(project, role="app", wait=True, say=lambda *_: None) == []


def test_dry_run_claims_nothing(project):
    j = jobs.add(project, "app", "x")
    msgs = []
    worker.serve(project, role="app", dry_run=True, say=msgs.append)
    assert jobs.get(project, j["id"])["status"] == "queued" and "would start" in msgs[0]


def test_detached_supervisor(project):
    j = jobs.add(project, "writer", "draft")
    worker.serve(project, role="writer", say=lambda *_: None)
    for _ in range(200):
        if jobs.get(project, j["id"])["status"] in jobs.TERMINAL:
            break
        time.sleep(0.1)
    assert jobs.get(project, j["id"])["status"] == "done"


def test_declaration_parser():
    ok, why = worker.declaration('x\n```json\n{"status": "done", "result": "r"}\n```')
    assert ok["status"] == "done" and why == ""
    for text, needle in [("nothing", "no fenced"), ('```json\n{"status": "maybe"}\n```', "done or blocked"),
                         ('```json\n{"status": "blocked"}\n```', "block_reason"),
                         ('```json\n{"status": "done", "block_reason": "x"}\n```', "done with"),
                         ('```json\n{oops}\n```', "does not parse")]:
        d, why = worker.declaration(text)
        assert d is None and needle in why
