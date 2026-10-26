import pytest

from wz import jobs, leases


def test_ids_priority_and_age(project):
    a = jobs.add(project, "app", "first", priority=50)
    b = jobs.add(project, "app", "urgent", priority=10)
    c = jobs.add(project, "app", "second", priority=50)
    assert [a["id"], b["id"], c["id"]] == ["job-0001", "job-0002", "job-0003"]
    j, waits = jobs.next_ready(project, "app")
    assert j["id"] == b["id"] and waits == []
    assert [x["id"] for x in jobs.queue_order(jobs.all_jobs(project))] == [b["id"], a["id"], c["id"]]


def test_dependency_waits_until_done(project):
    a = jobs.add(project, "app", "build")
    b = jobs.add(project, "tester", "test it", after=a["id"])
    j, waits = jobs.next_ready(project, "tester")
    assert j is None and waits == [(b["id"], f"waits for {a['id']} (queued)")]
    jobs.set_status(project, a["id"], "done")
    j, _ = jobs.next_ready(project, "tester")
    assert j["id"] == b["id"]


def test_unknown_dependency_and_role(project):
    with pytest.raises(jobs.JobError):
        jobs.add(project, "app", "x", after="job-0099")
    with pytest.raises(Exception):
        jobs.add(project, "ghost", "x")
    with pytest.raises(jobs.JobError):
        jobs.add(project, "app", "   ")


def test_hold_release_cancel(project):
    a = jobs.add(project, "app", "x")
    jobs.hold(project, a["id"], "not now")
    assert jobs.next_ready(project, "app")[0] is None
    jobs.release(project, a["id"])
    assert jobs.next_ready(project, "app")[0]["id"] == a["id"]
    jobs.cancel(project, a["id"], "dup")
    assert jobs.get(project, a["id"])["status"] == "cancelled"
    with pytest.raises(jobs.JobError):
        jobs.release(project, a["id"])


def test_leases(project):
    with pytest.raises(leases.LeaseError):
        jobs.add(project, "bench", "x", lease=["scope"])
    j = jobs.add(project, "bench", "measure", lease=["bench-psu"])
    fds = leases.acquire(project, ["bench-psu"], holder="someone")
    try:
        assert leases.acquire(project, ["bench-psu"], holder="other") is None
        nxt, waits = jobs.next_ready(project, "bench")
        assert nxt is None and "leased" in waits[0][1]
        assert leases.table(project)[0]["free"] is False
    finally:
        leases.release(project, ["bench-psu"], fds)
    assert jobs.next_ready(project, "bench")[0]["id"] == j["id"]


def test_durations():
    from wz.util import parse_duration
    assert parse_duration("90s") == 90 and parse_duration("45m") == 2700 and parse_duration("2h") == 7200
    assert parse_duration(30) == 30
    with pytest.raises(ValueError):
        parse_duration("soon")
