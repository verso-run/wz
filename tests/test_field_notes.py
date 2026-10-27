"""Field-note fixes: queued jobs with no timer say so, `serve --follow` runs a chain, a running job shows progress,
and a guard refusal that names its fix does not also say 'do not retry'."""
import json
import time

import pytest

from wz import cli, guard, jobs, unlock, worker
from wz.util import iso
from test_guard import bash, write


def _run(project, *argv):
    return cli.main(["--config", str(project.path), *argv])


# ---- #6: nothing starts queued jobs without a timer ---------------------------------------------------------------
def test_job_add_says_nothing_will_start_it_when_serve_has_not_run(project, capsys):
    assert worker.serve_age(project) is None
    assert _run(project, "job", "add", "app", "write the parser") == 0
    out = capsys.readouterr().out
    assert "queued for app" in out and "never run here" in out and "wz serve --follow" in out
    _run(project, "queue")
    assert "wz serve --follow" in capsys.readouterr().out
    _run(project, "status")
    assert "wz serve --follow" in capsys.readouterr().out


def test_no_hint_once_serve_has_run_lately_and_a_dry_run_does_not_count(project, capsys):
    jobs.add(project, "app", "x")
    worker.serve(project, dry_run=True, say=lambda *_: None)
    assert worker.serve_idle_hint(project) is not None
    worker.serve(project, role="writer", say=lambda *_: None)  # a timer's run: nothing ready for writer
    assert worker.serve_age(project) < 5 and worker.serve_idle_hint(project) is None
    _run(project, "job", "add", "app", "another")
    assert "note:" not in capsys.readouterr().out


def test_hint_returns_when_serve_is_stale(project):
    from wz.util import write_json
    write_json(project.state / "serve.last", {"t": time.time() - 3600})
    hint = worker.serve_idle_hint(project)
    assert "60 min ago" in hint


def test_follow_runs_a_chain_and_stops_at_a_hold(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "done")
    a = jobs.add(project, "writer", "first")
    b = jobs.add(project, "writer", "second", after=a["id"])
    c = jobs.add(project, "writer", "third", after=b["id"])
    h = jobs.add(project, "writer", "gated", after=c["id"])
    jobs.hold(project, h["id"], "the owner picks sources")
    msgs = []
    seen = worker.follow(project, role="writer", say=msgs.append, poll=0.05)
    assert [jobs.get(project, x["id"])["status"] for x in (a, b, c)] == ["done"] * 3
    assert jobs.get(project, h["id"])["status"] == "held"
    assert set(seen) == {a["id"], b["id"], c["id"]}
    text = "\n".join(msgs)
    assert f"{h['id']} (writer) held: the owner picks sources" in text and "wz job release" in text
    # a re-run on an idle queue starts nothing and says so
    again = []
    assert worker.follow(project, role="writer", say=again.append, poll=0.05) == {}
    assert "left waiting:" in "\n".join(again)


def test_follow_reports_a_blocked_dependency_and_an_empty_queue(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "blocked")
    a = jobs.add(project, "writer", "first")
    b = jobs.add(project, "writer", "second", after=a["id"])
    msgs = []
    worker.follow(project, role="writer", say=msgs.append, poll=0.05)
    text = "\n".join(msgs)
    assert f"{a['id']}: blocked" in text and f"{b['id']} (writer) waits for {a['id']} (blocked)" in text
    msgs = []
    worker.follow(project, role="app", say=msgs.append, poll=0.05)
    assert msgs == ["queue idle: nothing left waiting"]


def test_follow_flag_is_refused_with_wait(project):
    with pytest.raises(SystemExit):
        _run(project, "serve", "--follow", "--wait")


def test_cli_follow(project, capsys):
    j = jobs.add(project, "writer", "x")
    assert _run(project, "serve", "--follow", "--poll", "0.05", "--role", "writer") == 0
    assert jobs.get(project, j["id"])["status"] == "done"
    assert f"{j['id']}: done" in capsys.readouterr().out


def test_follow_keeps_going_when_a_job_ends_between_serve_and_the_running_check(project, monkeypatch):
    """The race `_startable` guards: a already finished when serve() returns, so nothing is `running`, yet b is ready."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "done")
    monkeypatch.setattr(worker, "_spawn", lambda cfg, jid: worker.run_job(cfg, jid) and 0)
    a = jobs.add(project, "writer", "first")
    b = jobs.add(project, "writer", "second", after=a["id"])
    worker.follow(project, role="writer", say=lambda *_: None, poll=0.05)
    assert [jobs.get(project, x["id"])["status"] for x in (a, b)] == ["done", "done"]


def test_follow_says_to_run_the_watchdog_when_a_supervisor_is_gone(project):
    j = jobs.add(project, "writer", "x")
    j.update(status="running", claimed=iso(), supervisor_pid=2 ** 22 + 12345)
    jobs.save(project, j)
    msgs = []
    worker.follow(project, role="writer", say=msgs.append, poll=0.05)
    assert any("run `wz watchdog` to mark it failed" in m and "will mark" not in m for m in msgs)


def test_follow_says_so_when_a_claimed_job_never_wrote_its_pid(project):
    j = jobs.add(project, "writer", "x")
    j.update(status="running", claimed=iso(time.time() - 3600))
    jobs.save(project, j)
    msgs = []
    worker.follow(project, role="writer", say=msgs.append, poll=0.05)
    assert any(j["id"] in m and "supervisor never started" in m and "wz watchdog" in m for m in msgs)
    # a job claimed a moment ago is still given its grace period
    k = jobs.add(project, "app", "y")
    k.update(status="running", claimed=iso())
    jobs.save(project, k)
    assert worker._never_started(jobs.get(project, k["id"])) is False


def test_follow_names_a_queued_job_whose_role_left_wz_toml(project):
    j = jobs.add(project, "writer", "x")
    j["role"] = "gone"
    jobs.save(project, j)
    msgs = []
    worker.follow(project, say=msgs.append, poll=0.05)
    text = "\n".join(msgs)
    assert f"{j['id']}: role 'gone' is not in wz.toml" in text
    assert f"{j['id']} (gone) its role 'gone' is not in wz.toml" in text


def test_follow_output_is_flushed_line_by_line(project, monkeypatch):
    class Out:
        def __init__(self):
            self.text, self.flushes = "", 0

        def write(self, s):
            self.text += s
            return len(s)

        def flush(self):
            self.flushes += 1

    out = Out()
    monkeypatch.setattr("sys.stdout", out)
    jobs.add(project, "writer", "x")
    assert _run(project, "serve", "--follow", "--poll", "0.05", "--role", "writer") == 0
    assert out.text.count("\n") >= 2 and out.flushes >= out.text.count("\n")


# ---- #7: progress of a running job --------------------------------------------------------------------------------
def test_running_job_shows_output_and_tail(project, tmp_path, monkeypatch, capsys):
    gate = tmp_path / "gate"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gated")
    monkeypatch.setenv("FAKE_GATE", str(gate))
    j = jobs.add(project, "writer", "slow one")
    worker.serve(project, role="writer", say=lambda *_: None)
    out = project.state / "logs" / f"{j['id']}.out"
    for _ in range(200):
        if out.exists() and out.stat().st_size:
            break
        time.sleep(0.05)
    try:
        age, size = worker.activity(project, jobs.get(project, j["id"]))
        assert size > 0 and age is not None and age < 30
        lines = worker.tail(project, j["id"])
        assert lines == ["says: Reading the brief.", "Bash: ls briefs"]
        _run(project, "job", "tail", j["id"])
        shown = capsys.readouterr().out
        assert "Bash: ls briefs" in shown and "last output" in shown
        _run(project, "status")
        assert f"{j['id']} (writer) running" in capsys.readouterr().out
        _run(project, "queue")
        assert "last output" in capsys.readouterr().out
    finally:
        gate.write_text("go")
    for _ in range(200):
        if jobs.get(project, j["id"])["status"] in jobs.TERMINAL:
            break
        time.sleep(0.1)
    st = jobs.get(project, j["id"])
    assert st["status"] == "done" and st["cost_usd"] == 0.25  # the result line still parses out of a stream


def test_tail_before_any_output_and_unknown_events(project):
    j = jobs.add(project, "writer", "x")
    assert worker.tail(project, j["id"]) == []
    logs = project.state / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{j['id']}.out").write_text("not json\n" + json.dumps({"type": "weird"}) + "\n" + json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b"}}]}}) + "\n")
    assert worker.tail(project, j["id"]) == ["Read: /a/b"]


def test_agent_command_streams(project):
    cmd = worker.build_command(project, "app", "p")
    assert "stream-json" in cmd and "--verbose" in cmd and cmd.index("--output-format") + 1 == cmd.index("stream-json")


# ---- #8: a refusal that names its fix says to apply it ------------------------------------------------------------
def _stderr(capsys):
    return capsys.readouterr().err


def test_fixable_refusal_does_not_say_do_not_retry(project, capsys):
    assert bash(project, "app", "echo hi > $S/out.txt") == 2
    err = _stderr(capsys)
    assert "spell the path out" in err and "Do not retry" not in err and "run it again" in err


def test_pattern_kill_and_force_push_are_fixable(project, capsys):
    assert bash(project, "app", "pkill -f server") == 2
    err = _stderr(capsys)
    assert "never by pattern" in err and "Do not retry" not in err
    unlock.grant(project, "app")
    assert bash(project, "app", "git push -f origin wz/app/job-0001") == 2
    err = _stderr(capsys)
    assert "push your own branch plainly" in err and "Do not retry" not in err
    assert bash(project, "app", "git push origin HEAD:main") == 2  # nothing to fix: the branch is not the role's
    assert "Do not retry a variant" in _stderr(capsys)


def test_a_plain_refusal_still_says_do_not_retry(project, capsys):
    assert write(project, "app", project.root / "DECISIONS.md") == 2
    err = _stderr(capsys)
    assert "Do not retry a variant" in err and "run it again" not in err


def test_refuse_default_is_not_fixable():
    assert guard.Refuse("x").fixable is False and guard.Refuse("x", fixable=True).fixable is True


def test_the_lead_charter_names_the_follow_runner_for_a_workspace_without_timers(project):
    from wz import charters
    charters.write_all(project)
    lead = project.charter_path(project.lead()).read_text()
    assert "`wz serve --follow`" in lead and "`wz job add` starts nothing" in lead


# ---- cleanup after the PR 2-4 reviews ------------------------------------------------------------------------------
def test_activity_and_tail_follow_the_fix_turn_log(project):
    import os
    logs = project.state / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    ev = lambda text: json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n"
    (logs / "job-9.out").write_text(ev("first turn"))
    os.utime(logs / "job-9.out", (time.time() - 500, time.time() - 500))
    age, _ = worker.activity(project, {"id": "job-9"})
    assert 499 < age < 600
    (logs / "job-9.fix.out").write_text(ev("the fix turn") * 2)
    age, size = worker.activity(project, {"id": "job-9"})
    assert age < 30 and size == len(ev("the fix turn") * 2)           # the newer of the two logs
    assert worker.tail(project, "job-9") == ["says: first turn", "says: the fix turn", "says: the fix turn"]
    assert worker.activity(project, {"id": "job-none"}) == (None, 0) and worker.tail(project, "job-none") == []


def test_follow_keeps_going_when_a_job_becomes_startable_between_serve_and_the_check(project, monkeypatch):
    """The race `_startable` exists for: serve() starts nothing now, the job is still ready, so follow must ask serve again."""
    j = jobs.add(project, "writer", "ready")
    calls = []

    def fake_serve(cfg, role=None, say=print, **kw):
        calls.append(1)
        if len(calls) == 2:
            jobs.cancel(cfg, j["id"])
        return []
    monkeypatch.setattr(worker, "serve", fake_serve)
    worker.follow(project, role="writer", say=lambda *_: None, poll=0.01)
    assert len(calls) == 2
