import os

from wz import approvals, digest, flags, jobs, records, worker, watchdog
from wz.util import now


def test_decisions_need_the_owners_words(project):
    d1 = records.decide(project, "ship the dashboard before the bench work", "dashboard first; bench waits a week")
    d2 = records.decide(project, None, "we should add a nightly backup")
    text = (project.root / "DECISIONS.md").read_text()
    assert (d1, d2) == ("D-1", "D-2")
    assert '| D-1 |' in text and '"ship the dashboard before the bench work"' in text and "decided, revisitable" in text
    assert "| D-2 |" in text and "(none: proposal)" in text and "| proposal |" in text


def test_ledger_rows_escape_and_count(project):
    a = records.ledger_add(project, "defects", {"severity": "high", "role": "app", "what": "a | b\nc"})
    b = records.ledger_add(project, "defects", {"what": "second"})
    assert (a, b) == ("DEF-001", "DEF-002")
    text = (project.root / "ledgers" / "DEFECTS.md").read_text()
    assert "a \\| b c" in text and text.count("| open |") == 2


def test_brief_numbering(project):
    p1 = records.brief_new(project, "Bench Bring-up", "bench", "Bring the board up")
    p2 = records.brief_new(project, "letters", "writer")
    assert p1.name == "01-bench-bring-up.md" and p2.name == "02-letters.md"
    t = p1.read_text()
    assert t.startswith("# Brief 01 — Bring the board up") and "**Role:** bench" in t and "## Report" in t


def test_digest_three_asks_and_lead_errors(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "asks")
    jobs.add(project, "writer", "draft")
    worker.serve(project, role="writer", wait=True, say=lambda *_: None)
    approvals.request(project, "send the letter", command="true")
    sync = digest.sync(project)
    sync.write_text(sync.read_text().replace("- (what I got wrong, what it cost, the rule that stops it next time)",
                                             "- queued the same job twice; now I check `wz queue` first"))
    text = digest.write(project).read_text()
    asks = text.split("## Asks")[1].split("##")[0]
    assert asks.count("\n1. ") == 1 and "\n3. " in asks and "\n4. " not in asks and "2 more ask(s)" in asks
    assert "queued the same job twice" in text
    assert "| job-0001 | writer | done |" in text
    assert "| (project) | 0.25 |" in text


def test_watchdog_alerts(project):
    lost = jobs.add(project, "app", "lost")
    lost = jobs.get(project, lost["id"])
    lost.update(status="running", supervisor_pid=2 ** 22 + 12345, started_t=now())
    jobs.save(project, lost)
    dead = jobs.add(project, "tester", "dead dep")
    jobs.set_status(project, dead["id"], "blocked")
    orphan = jobs.add(project, "tester", "orphan", after=dead["id"])
    old = jobs.add(project, "writer", "old")
    old = jobs.get(project, old["id"])
    old["created_t"] = now() - 7 * 3600
    jobs.save(project, old)
    (project.role_dir("bench") / "BACKLOG.md").write_text("- [ ] calibrate the supply\n- [x] done thing\n")
    unstarted = jobs.add(project, "app", "claimed but never started")
    unstarted = jobs.get(project, unstarted["id"])
    unstarted.update(status="running", claimed="2000-01-01T00:00:00+00:00")
    jobs.save(project, unstarted)
    alerts = watchdog.check(project)
    assert ("LOST", unstarted["id"]) in {(a["kind"], a["ref"]) for a in alerts}
    kinds = {(a["kind"], a["ref"]) for a in alerts}
    assert ("LOST", lost["id"]) in kinds and ("ORPHANED", orphan["id"]) in kinds
    assert ("STUCK", old["id"]) in kinds and ("IDLE", "bench") in kinds
    assert jobs.get(project, lost["id"])["status"] == "failed"
    n = len([e for e in flags.events(project) if e["kind"] == "alert"])
    watchdog.check(project)
    assert len([e for e in flags.events(project) if e["kind"] == "alert"]) == n


def test_next_cursor_and_flag_hook(project):
    flags.event(project, "app", "job", "job-0009", "done: x")
    assert len(flags.since_cursor(project, peek=True)) == 1
    assert len(flags.since_cursor(project)) == 1
    assert flags.since_cursor(project) == []
    brief = records.brief_new(project, "x", "app")
    import json
    env = {"WZ_ROLE": "app", "WZ_CONFIG": str(project.path), "WZ_JOB": "job-0009"}
    flags.hook(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(brief)}, "cwd": str(project.root)}), env)
    assert (project.state / "flags" / f"app.{brief.name}.done").exists()
    assert flags.wait(project, "app", brief.name, timeout_s=1)
    assert flags.since_cursor(project)[0]["kind"] == "report"
    assert not os.environ.get("WZ_ROLE")


def test_brief_new_never_overwrites_a_brief_made_at_the_same_moment(project, monkeypatch):
    first = records.brief_new(project, "same-slug", "app", "mine")
    first.write_text("the first one's work")
    # a second `wz brief new` that listed the folder before the first one wrote: it counts the same number
    real_glob = type(first.parent).glob
    monkeypatch.setattr(type(first.parent), "glob", lambda self, pat: iter([]) if self == first.parent else real_glob(self, pat))
    second = records.brief_new(project, "same-slug", "app", "yours")
    assert second != first and second.name.startswith("02-same-slug")
    assert first.read_text() == "the first one's work"
    assert "yours" in second.read_text()
