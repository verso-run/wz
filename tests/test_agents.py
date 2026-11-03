"""The agent watchdog (wz/agents.py): one status per agent, the nudge, the handoff. Fakes only: no tmux, no Claude."""
import os
import time

import pytest

from wz import agents, approvals, digest, escalate, flags, jobs, sessions, watchdog
from wz.agents import Seen
from wz.util import now

TH = {"stall_s": 45 * 60, "job_stall_s": 20 * 60, "nudge_s": 15 * 60, "nudges": 2, "warn_at": 0.9, "window_s": 86400}


class FakeProbe:
    def __init__(self, windows=None, kinds=None):
        self.w, self.k = windows or {}, kinds or {}

    def windows(self, cfg):
        return self.w

    def pane_kind(self, cfg, role):
        return self.k.get(role, "ready")


class Said:
    """A stand-in for escalate.tell / escalate.push that records what would have been delivered."""
    def __init__(self):
        self.told, self.pushed = [], []

    def tell(self, cfg, role, line, start=False):
        self.told.append((role, line))
        return "said"

    def push(self, cfg, esc):
        self.pushed.append(esc["id"])
        return "pushed"


def session(cfg, role, light="", beat_min=None, t=None):
    """Make the files the role's hooks leave: its light and its beat, `beat_min` minutes old."""
    d = sessions.state_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    if light:
        (d / f"{role}.light").write_text(f"{light} %1\n")
    if beat_min is not None:
        p = d / f"{role}.beat"
        p.write_text("")
        ts = (now() if t is None else t) - beat_min * 60
        os.utime(p, (ts, ts))


def running_job(cfg, role="app", elapsed_min=5, timeout="90m", pid=None, log_age_min=None):
    j = jobs.get(cfg, jobs.add(cfg, role, "work", timeout=timeout)["id"])
    j.update(status="running", supervisor_pid=pid or os.getpid(), started_t=now() - elapsed_min * 60)
    jobs.save(cfg, j)
    if log_age_min is not None:
        log = cfg.state / "logs" / f"{j['id']}.out"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("{}\n")
        ts = now() - log_age_min * 60
        os.utime(log, (ts, ts))
    return j


# ---- the judgement ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("seen, waiting, want", [
    (Seen(windows=["@1"], light="done", beat_age=60), 0, "idle"),
    (Seen(windows=["@1"], kind="ready", light="", beat_age=None), 0, "idle"),
    (Seen(windows=["@1"], light="work", beat_age=30), 0, "working"),
    (Seen(windows=["@1"], light="work", beat_age=50 * 60), 0, "stalled"),      # a turn open, silent for 50 min
    (Seen(windows=["@1"], light="ask", beat_age=50 * 60), 0, "stalled"),       # waiting on a person
    (Seen(windows=["@1"], light="ask", beat_age=60), 0, "working"),
    (Seen(windows=["@1"], kind="login"), 10 * 60, "working"),
    (Seen(windows=["@1"], kind="login"), 50 * 60, "stalled"),
    (Seen(windows=["@1"], kind="busy", light="", beat_age=None), 0, "working"),
    (Seen(windows=["@1"], kind="busy", light="", beat_age=3600), 0, "stalled"),
    (Seen(windows=["@1"], exited=True), 0, "zombie"),
    (Seen(windows=["@1"], kind="shell"), 0, "zombie"),
    (Seen(windows=["@1", "@7"], light="done"), 0, "zombie"),
])
def test_judge_session(seen, waiting, want):
    assert agents.judge_session(seen, TH, waiting)[0] == want


def test_a_duplicate_names_both_windows():
    status, why = agents.judge_session(Seen(windows=["@1", "@7"]), TH)
    assert status == "zombie" and "duplicate" in why and "@1" in why and "@7" in why


# ---- sessions, from the files the hooks keep ----------------------------------------------------------------------------
def test_a_role_with_no_window_is_not_an_agent(project):
    assert agents.table(project, probe=FakeProbe()) == []


def test_session_rows_read_the_light_and_the_beat(project):
    session(project, "mission-ctl", light="work", beat_min=1)
    session(project, "app", light="done", beat_min=300)
    session(project, "tester", light="work", beat_min=90)
    rows = {r["role"]: r for r in agents.table(project, probe=FakeProbe(windows={"mission-ctl": ["@1"], "app": ["@2"], "tester": ["@3"]}))}
    assert {k: v["status"] for k, v in rows.items()} == {"mission-ctl": "working", "app": "idle", "tester": "stalled"}
    assert "no sign of life for 90 min" in rows["tester"]["reason"]


def test_a_question_that_stays_open_becomes_a_stall_only_after_the_threshold(project):
    probe = FakeProbe(windows={"app": ["@2"]}, kinds={"app": "dialog"})
    t0 = now()
    agents.tick(project, t0, probe=probe, tell_=Said().tell)
    assert agents.table(project, t0 + 20 * 60, probe=probe)[0]["status"] == "working"
    (row,) = agents.table(project, t0 + 50 * 60, probe=probe)
    assert row["status"] == "stalled" and "a question" in row["reason"] and "50 min" in row["reason"]


# ---- jobs --------------------------------------------------------------------------------------------------------------
def job_rows(cfg):
    return {r["key"]: r for r in agents.table(cfg, probe=FakeProbe())}


def test_a_job_with_fresh_output_is_working(project):
    j = running_job(project, elapsed_min=30, log_age_min=1)
    assert job_rows(project)[f"job:{j['id']}"]["status"] == "working"


def test_a_job_whose_log_stopped_growing_is_stalled(project):
    j = running_job(project, elapsed_min=40, log_age_min=25)
    r = job_rows(project)[f"job:{j['id']}"]
    assert r["status"] == "stalled" and "no output for 25 min" in r["reason"]


def test_a_job_near_its_limit_with_no_report_is_stalled_and_a_report_clears_it(project):
    j = running_job(project, elapsed_min=82, timeout="90m", log_age_min=0.1)          # the 90-minute job that wrote no report
    r = job_rows(project)[f"job:{j['id']}"]
    assert r["status"] == "stalled" and "82 of 90 min used and no report written" in r["reason"]
    flags.event(project, "app", "report", "briefs/01-x.md", "app wrote briefs/01-x.md", job=j["id"])
    assert job_rows(project)[f"job:{j['id']}"]["status"] == "working"


def test_a_job_that_timed_out_and_left_no_report_is_a_zombie_until_reminted(project):
    j = running_job(project)
    j = jobs.get(project, j["id"])
    j.update(status="failed", timed_out=True, finished_t=now() - 600)
    jobs.save(project, j)
    r = job_rows(project)[f"job:{j['id']}"]
    assert r["status"] == "zombie" and "hit its 90 min limit and left no report" in r["reason"]
    new = jobs.remint(project, j["id"])
    assert f"job:{j['id']}" not in job_rows(project) and new["reminted_from"] == j["id"]


def test_a_job_with_a_dead_supervisor_and_a_job_over_the_cap_are_zombies(project):
    dead = running_job(project, pid=2 ** 22 + 777, log_age_min=1)
    a, b = running_job(project, "app", log_age_min=1), running_job(project, "app", log_age_min=1)
    rows = job_rows(project)
    assert rows[f"job:{dead['id']}"]["status"] == "zombie" and "supervisor" in rows[f"job:{dead['id']}"]["reason"]
    assert [rows[f"job:{x['id']}"]["status"] for x in (a, b)].count("zombie") >= 1        # cap is 1: the newer one is the duplicate
    assert "duplicate" in " ".join(r["reason"] for r in rows.values() if r["status"] == "zombie")


# ---- the nudge and the handoff ---------------------------------------------------------------------------------------------
def test_a_stalled_session_is_nudged_twice_then_handed_to_the_lead(project):
    probe, s = FakeProbe(windows={"app": ["@2"]}), Said()
    session(project, "app", light="work", beat_min=60)
    t0 = now()
    agents.tick(project, t0, probe=probe, tell_=s.tell, push_=s.push)
    assert [r for r, _ in s.told] == ["app"] and "no progress" in s.told[0][1] and escalate.open_ones(project) == []
    agents.tick(project, t0 + 5 * 60, probe=probe, tell_=s.tell, push_=s.push)         # too soon for another
    assert len(s.told) == 1
    agents.tick(project, t0 + 16 * 60, probe=probe, tell_=s.tell, push_=s.push)
    assert len(s.told) == 2 and escalate.open_ones(project) == []
    agents.tick(project, t0 + 32 * 60, probe=probe, tell_=s.tell, push_=s.push)        # both nudges used, a quarter hour passed
    (e,) = escalate.open_ones(project)
    assert (e["sev"], e["subject"], e["ref"]) == ("P1", "app", "session:app") and "stalled" in e["text"]
    assert s.told[-1][0] == "mission-ctl" and f"P1 {e['id']}" in s.told[-1][1]
    n = len(s.told)
    agents.tick(project, t0 + 40 * 60, probe=probe, tell_=s.tell, push_=s.push)        # same stall: one escalation, said once
    assert len(escalate.open_ones(project)) == 1 and len(s.told) == n


def test_recovery_closes_the_escalation_and_resets_the_count(project):
    probe, s = FakeProbe(windows={"app": ["@2"]}), Said()
    session(project, "app", light="work", beat_min=60)
    t0 = now()
    for k in (0, 16, 32):
        agents.tick(project, t0 + k * 60, probe=probe, tell_=s.tell, push_=s.push)
    assert escalate.open_ones(project)
    session(project, "app", light="done", beat_min=0, t=t0 + 33 * 60)
    agents.tick(project, t0 + 33 * 60, probe=probe, tell_=s.tell, push_=s.push)
    assert escalate.open_ones(project) == [] and escalate.all_escalations(project)[0]["state"] == "resolved"
    assert [r["status"] for r in agents.table(project, t0 + 33 * 60, probe=probe)] == ["idle"]


def test_a_zombie_session_is_handed_off_at_once_and_never_nudged(project):
    s = Said()
    agents.tick(project, probe=FakeProbe(windows={"app": ["@2", "@9"]}), tell_=s.tell, push_=s.push)
    (e,) = escalate.open_ones(project)
    assert e["sev"] == "P1" and "duplicate" in e["text"] and [r for r, _ in s.told] == ["mission-ctl"]


def test_a_stalled_job_is_handed_to_the_lead_without_a_nudge(project):
    s = Said()
    j = running_job(project, elapsed_min=85, log_age_min=0.2)
    agents.tick(project, probe=FakeProbe(), tell_=s.tell, push_=s.push)
    (e,) = escalate.open_ones(project)
    assert e["ref"] == f"job:{j['id']}" and e["subject"] == "app" and [r for r, _ in s.told] == ["mission-ctl"]


def test_a_dead_lead_goes_to_the_owner_not_to_itself(project):
    s = Said()
    agents.tick(project, probe=FakeProbe(windows={"mission-ctl": ["@1", "@5"]}), tell_=s.tell, push_=s.push)      # duplicate lead sessions
    (e,) = escalate.open_ones(project)
    assert e["sev"] == "P0" and e["subject"] == "mission-ctl" and s.told == [] and s.pushed == [e["id"]]


# ---- the watchdog and the digest ---------------------------------------------------------------------------------------------
def test_watchdog_and_digest_name_each_case(project, monkeypatch):
    j = running_job(project, elapsed_min=85, log_age_min=0.2)
    monkeypatch.setattr(agents.TmuxProbe, "windows", lambda self, cfg: {"mission-ctl": ["@1", "@5"], "app": ["@2"]})
    monkeypatch.setattr(agents.TmuxProbe, "pane_kind", lambda self, cfg, role: "ready")
    s = Said()
    monkeypatch.setattr(escalate, "tell", s.tell)
    monkeypatch.setattr(escalate, "push", s.push)
    session(project, "app", light="work", beat_min=1)
    alerts = {(a["kind"], a["ref"]) for a in watchdog.check(project)}
    assert ("ZOMBIE", "session:mission-ctl") in alerts and ("STALLED", f"job:{j['id']}") in alerts
    text = digest.compose(project)
    assert "## Agents" in text and "| session:mission-ctl | zombie |" in text and f"| job:{j['id']} | stalled |" in text
    assert "## Open escalations" in text and "P0" in text.split("## Asks")[1].split("##")[0]      # the dead lead is the first ask


def test_a_lost_job_is_not_also_reported_as_a_zombie_alert(project):
    j = running_job(project, pid=2 ** 22 + 99)
    kinds = [a["kind"] for a in watchdog.check(project, apply=False) if a["ref"] == j["id"] or a["ref"] == f"job:{j['id']}"]
    assert kinds == ["LOST"]
    assert agents.table(project, probe=FakeProbe(), every=[jobs.get(project, j["id"])])[0]["status"] == "zombie"
