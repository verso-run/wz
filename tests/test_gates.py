"""Owner gates (D3): a job held for the owner's decision. Only `wz gate pass`, from the owner's own shell, queues it."""
import pytest

from wz import cli, digest, jobs, upkeep, worker
from test_guard import bash


def _run(project, *argv):
    return cli.main(["--config", str(project.path), *argv])


def test_a_gated_job_is_held_with_the_owners_words_and_never_served(project):
    j = jobs.add(project, "writer", "draft the note", gate="owner picks sources")
    assert j["status"] == "held" and jobs.open_gate(j) == "owner picks sources"
    assert j["gate"] == {"text": "owner picks sources", "state": "open"}
    assert jobs.next_ready(project, "writer")[0] is None
    assert worker.serve(project, role="writer", say=lambda *_: None) == []
    assert jobs.get(project, j["id"])["status"] == "held"


def test_a_blank_gate_is_refused(project):
    with pytest.raises(jobs.JobError):
        jobs.add(project, "writer", "x", gate="   ")


def test_release_refuses_a_gate_and_so_does_every_other_way_to_queue_it(project):
    j = jobs.add(project, "writer", "x", gate="owner picks sources")
    with pytest.raises(jobs.JobError, match="only the owner passes it"):
        jobs.release(project, j["id"])
    with pytest.raises(jobs.JobError):
        jobs.set_status(project, j["id"], "queued")
    with pytest.raises(jobs.JobError):
        jobs.set_status(project, j["id"], "running")
    with pytest.raises(jobs.JobError, match="waits on the owner's gate"):
        worker.run_job(project, j["id"])
    assert jobs.get(project, j["id"])["status"] == "held"


def test_passing_queues_the_job_once_and_it_then_runs(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "done")
    j = jobs.add(project, "writer", "x", gate="owner picks sources")
    p = jobs.pass_gate(project, j["id"], by="owner", note="use the two journals")
    assert p["status"] == "queued" and jobs.open_gate(p) is None
    assert p["gate"]["state"] == "passed" and p["gate"]["passed_by"] == "owner" and p["gate"]["note"] == "use the two journals"
    assert any("the owner passed the gate" in n for n in p["notes"])
    with pytest.raises(jobs.JobError, match="already passed"):
        jobs.pass_gate(project, j["id"])
    assert worker.serve(project, role="writer", wait=True, say=lambda *_: None) == [j["id"]]
    assert jobs.get(project, j["id"])["status"] == "done"


def test_pass_needs_a_gate_and_a_job_still_held(project):
    plain = jobs.add(project, "writer", "plain")
    with pytest.raises(jobs.JobError, match="has no gate"):
        jobs.pass_gate(project, plain["id"])
    g = jobs.add(project, "writer", "gated", gate="decide")
    jobs.cancel(project, g["id"], "no longer needed")
    with pytest.raises(jobs.JobError, match="nothing left to pass"):
        jobs.pass_gate(project, g["id"])
    assert jobs.gates(project) == []  # a cancelled gate waits on no one


def test_a_job_after_a_gate_says_it_waits_on_the_owner(project):
    g = jobs.add(project, "writer", "gated", gate="owner picks sources")
    nxt = jobs.add(project, "tester", "check it", after=g["id"])
    _, waits = jobs.next_ready(project, "tester")
    assert waits == [(nxt["id"], f"waits for {g['id']}, which waits on the owner: owner picks sources (`wz gate pass {g['id']}`)")]


def test_remint_cannot_launder_a_gate(project):
    g = jobs.add(project, "writer", "gated", gate="owner picks sources")
    jobs.cancel(project, g["id"], "oops")
    n = jobs.remint(project, g["id"])
    assert n["status"] == "held" and jobs.open_gate(n) == "owner picks sources"
    # a gate the owner already passed is not asked again for the re-run of a failed job
    h = jobs.add(project, "writer", "gated two", gate="decide")
    jobs.pass_gate(project, h["id"])
    jobs.set_status(project, h["id"], "failed")
    m = jobs.remint(project, h["id"])
    assert m["status"] == "queued" and m["gate"]["state"] == "passed"


def test_prune_never_drops_an_owner_gate(project):
    g = jobs.add(project, "writer", "gated", gate="owner picks sources")
    twin = jobs.add(project, "writer", "gated", gate="owner picks sources")
    future = g["created_t"] + 400 * 86400
    assert upkeep.prune(project, apply=True, t=future) == []
    assert jobs.get(project, g["id"])["status"] == jobs.get(project, twin["id"])["status"] == "held"


# ---- the commands -------------------------------------------------------------------------------------------------
def test_cli_add_list_pass(project, capsys):
    _run(project, "gate", "list")
    assert "no gate waits on you" in capsys.readouterr().out
    assert _run(project, "job", "add", "writer", "draft the note", "--gate", "owner picks sources") == 0
    out = capsys.readouterr().out
    assert "waits on you: owner picks sources" in out and "wz gate pass job-0001" in out
    _run(project, "gate", "list")
    out = capsys.readouterr().out
    assert "job-0001" in out and "owner picks sources" in out and "open" in out
    _run(project, "queue")
    assert "waits on you: owner picks sources" in capsys.readouterr().out
    assert _run(project, "job", "release", "job-0001") != 0
    assert "only the owner passes it" in capsys.readouterr().err
    assert jobs.get(project, "job-0001")["status"] == "held"
    assert _run(project, "gate", "pass", "job-0001", "--note", "journals A and B") == 0
    assert "job-0001 (writer) is queued" in capsys.readouterr().out
    _run(project, "gate", "list")
    assert "no gate waits on you" in capsys.readouterr().out
    _run(project, "gate", "list", "--all")
    assert "passed" in capsys.readouterr().out


def test_cli_pass_is_refused_inside_a_role_session_even_for_the_lead(project, monkeypatch):
    j = jobs.add(project, "writer", "x", gate="decide")
    for role in ("writer", project.lead()):
        monkeypatch.setenv("WZ_ROLE", role)
        with pytest.raises(SystemExit, match="owner's decision"):
            _run(project, "gate", "pass", j["id"])
    assert jobs.get(project, j["id"])["status"] == "held"
    monkeypatch.delenv("WZ_ROLE")
    with pytest.raises(SystemExit, match="no job"):
        _run(project, "gate", "pass", "job-0099")


def test_guard_refuses_gate_pass_for_every_role(project):
    for role in ("writer", project.lead()):
        assert bash(project, role, "wz gate pass job-0001") == 2
        assert bash(project, role, "cd x && wz gate pass job-0001 --note ok") == 2
    assert bash(project, "writer", "wz gate list") == 0


def test_status_and_digest_have_waiting_on_you_lines(project, capsys):
    g = jobs.add(project, "writer", "gated", gate="owner picks sources")
    _run(project, "status")
    out = capsys.readouterr().out
    assert "waiting on you (1):" in out and f"{g['id']} (writer) owner picks sources - `wz gate pass {g['id']}`" in out
    text = digest.compose(project)
    assert "## Waiting on you" in text and f"owner picks sources ({g['id']}, writer): `wz gate pass {g['id']}`" in text
    assert "Nothing needs you today." not in text
    jobs.pass_gate(project, g["id"])
    text = digest.compose(project)
    assert "## Waiting on you" not in text and "Nothing needs you today." in text
    _run(project, "status")
    assert "waiting on you" not in capsys.readouterr().out


def test_follow_runs_up_to_the_gate_and_names_it(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "done")
    a = jobs.add(project, "writer", "research")
    g = jobs.add(project, "writer", "draft", after=a["id"], gate="owner picks sources")
    z = jobs.add(project, "writer", "polish", after=g["id"])
    msgs = []
    worker.follow(project, role="writer", say=msgs.append, poll=0.05)
    text = "\n".join(msgs)
    assert jobs.get(project, a["id"])["status"] == "done" and jobs.get(project, g["id"])["status"] == "held"
    assert "stopped at 1 gate(s) that wait on you" in text
    assert f"  {g['id']} (writer) owner picks sources" in text
    assert f"{z['id']} (writer) waits for {g['id']}, which waits on the owner" in text
    assert "queue idle" not in text
    assert text.count(f"  {g['id']} (writer)") == 1  # the gate is listed once, not again under "left waiting"
    # the owner passes it; following again runs the rest
    jobs.pass_gate(project, g["id"])
    worker.follow(project, role="writer", say=lambda *_: None, poll=0.05)
    assert [jobs.get(project, x["id"])["status"] for x in (g, z)] == ["done", "done"]
