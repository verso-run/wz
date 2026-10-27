"""D5: a finished job's follow-ups become held jobs, with a depth of one and a cap of five per job."""
from wz import jobs, records, worker


def finish(cfg, job_id, followups):
    job = jobs.get(cfg, job_id)
    decl = {"status": "done", "result": "r", "evidence": [], "followups": followups}
    return worker.finish(cfg, job, decl, "", 0, False, 0.0, "")


def fu(n, role="tester", **kw):
    return {"role": role, "task": f"check thing {n}", "evidence_of_done": f"proof {n}", **kw}


def ledger_rows(cfg):
    return [x for x in (cfg.root / "ledgers" / "FOLLOWUPS.md").read_text().splitlines() if x.startswith("| FU-")]


def test_cap_of_five_held_jobs_rest_ledger_only(project):
    j = jobs.add(project, "app", "parent")
    done = finish(project, j["id"], [fu(n) for n in range(8)])
    assert len(done["followup_jobs"]) == 5
    held = [x for x in jobs.all_jobs(project) if x.get("followup_of") == j["id"]]
    assert [x["task"] for x in held] == [f"check thing {n}" for n in range(5)]
    assert all(x["status"] == "held" for x in held)
    assert [x["task"] for x in done["followups_ledger_only"]] == [f"check thing {n}" for n in (5, 6, 7)]
    assert all(x["why"].startswith("cap") for x in done["followups_ledger_only"])
    assert len(ledger_rows(project)) == 8   # every follow-up still has its row


def test_follow_up_of_a_follow_up_is_ledger_only(project):
    j = jobs.add(project, "app", "parent")
    first = finish(project, j["id"], [fu(1)])
    (child,) = first["followup_jobs"]
    jobs.release(project, child)
    second = finish(project, child, [fu(2), fu(3)])
    assert second["followup_jobs"] == []
    assert len(second["followups_ledger_only"]) == 2
    assert second["followups_ledger_only"][0]["why"].startswith("depth")
    assert not [x for x in jobs.all_jobs(project) if x.get("followup_of") == child]
    assert len(ledger_rows(project)) == 3


def test_reminted_follow_up_stays_depth_one(project):
    j = jobs.add(project, "app", "parent")
    (child,) = finish(project, j["id"], [fu(1)])["followup_jobs"]
    jobs.cancel(project, child)
    new = jobs.remint(project, child)
    assert jobs.get(project, new["id"])["followup_of"] == j["id"]
    assert finish(project, new["id"], [fu(9)])["followup_jobs"] == []


def test_duplicate_task_already_queued_or_held_is_skipped(project):
    jobs.add(project, "tester", "Check   THING 1")
    j = jobs.add(project, "app", "parent")
    done = finish(project, j["id"], [fu(1), fu(2), fu(2)])
    assert [jobs.get(project, i)["task"] for i in done["followup_jobs"]] == ["check thing 2"]
    assert [x["why"][:7] for x in done["followups_ledger_only"]] == ["already", "already"]
    assert len(ledger_rows(project)) == 3


def test_unknown_role_or_empty_task_makes_no_job(project):
    j = jobs.add(project, "app", "parent")
    done = finish(project, j["id"], [fu(1, role="nobody"), fu(2, role=""), {"role": "tester"}, "junk"])
    assert done["followup_jobs"] == []
    assert len(done["followups_ledger_only"]) == 2 and "no role" in done["followups_ledger_only"][0]["why"]
    assert len(ledger_rows(project)) == 2   # the empty task and the string never had a row


def test_cap_is_per_finished_job(project):
    a = jobs.add(project, "app", "a")
    b = jobs.add(project, "app", "b")
    assert len(finish(project, a["id"], [fu(n) for n in range(5)])["followup_jobs"]) == 5
    assert len(finish(project, b["id"], [fu(n) for n in range(10, 15)])["followup_jobs"]) == 5


def test_no_followups_leaves_job_record_clean(project):
    j = jobs.add(project, "app", "parent")
    done = finish(project, j["id"], [])
    assert "followup_jobs" not in done
