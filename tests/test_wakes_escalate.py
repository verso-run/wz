"""Scheduled wakes (wz/wakes.py) and severity escalation (wz/escalate.py). Fakes only: no tmux, no Claude, no network."""
import datetime as dt
import stat
import sys

import pytest

from wz import approvals, config, escalate, flags, sessions, util, wakes
from wz.escalate import EscalationError


class Said:
    def __init__(self, outcome="said"):
        self.told, self.pushed, self.outcome = [], [], outcome

    def tell(self, cfg, role, line, start=False):
        self.told.append((role, line, start))
        return self.outcome

    def push(self, cfg, esc):
        self.pushed.append((esc["id"], esc["sev"]))
        return "pushed"


@pytest.fixture(autouse=True)
def _signs_are_dated_the_29th(monkeypatch):
    """The tests use fixed days in the month; whatever the real date is, the owner signs the day before them, at noon."""
    monkeypatch.setattr(approvals, "iso", lambda t=None: util.iso(at(29, "12:00") if t is None else t))


def at(day, hhmm):
    h, m = hhmm.split(":")
    return dt.datetime(2026, 10, day, int(h), int(m)).timestamp()      # 2026-10-30 is a Friday


WAKE = {"id": "lead-digest", "role": "mission-ctl", "at": "07:15", "text": "Compose the digest.", "start": False}


def with_wakes(cfg, *ws):
    cfg.data["wake"] = [dict(w) for w in ws]
    return cfg


def sign_all(cfg, pin="123456"):
    if not approvals.has_pin(cfg):
        approvals.set_pin(cfg, pin)
    for r in approvals.pending(cfg):
        approvals.sign(cfg, r["id"], pin)


# ---- wakes: declaring and approving -------------------------------------------------------------------------------------------
def test_a_wake_is_validated_on_load(project):
    bad = [{"id": "Bad Id", "role": "nobody", "at": "7:5pm", "days": ["funday"], "text": "", "late": "soon", "oops": 1},
           {"id": "dup", "role": "app", "at": "07:15", "text": "x"}, {"id": "dup", "role": "app", "at": "07:15", "text": "x"}]
    text = "\n".join(wakes.problems(with_wakes(project, *bad)))
    for want in ("id must be lowercase", "role 'nobody'", "at must be a local time", "days must be", "text is required", "late:",
                 "'oops' is not a setting", "id appears twice"):
        assert want in text
    assert wakes.problems(with_wakes(project, WAKE)) == []


def test_a_bad_wake_stops_the_config_from_loading(project):
    project.path.write_text(project.path.read_text() + '\n[[wake]]\nid = "x"\nrole = "ghost"\nat = "07:15"\ntext = "hi"\n')
    with pytest.raises(config.ConfigError, match="role 'ghost'"):
        config.load(project.path)


def test_nothing_runs_until_the_owner_signs_and_a_change_needs_a_new_sign(project):
    cfg, s = with_wakes(project, WAKE), Said()
    (w,) = wakes.declared(cfg)
    assert wakes.approval(cfg, w) == "none"
    out = wakes.tick(cfg, at(30, "07:16"), tell_=s.tell)
    assert out[0]["outcome"] == "unapproved" and s.told == []
    (req,) = approvals.pending(cfg)                                # the tick asked once
    assert req["by"] == "wz" and "lead-digest" in req["what"] and req["action"]["type"] == "wake"
    wakes.tick(cfg, at(30, "07:17"), tell_=s.tell)
    assert len(approvals.pending(cfg)) == 1                         # and did not ask again
    assert wakes.approval(cfg, w) == "pending"
    sign_all(cfg)
    assert wakes.approval(cfg, w) == "approved"
    cfg.data["wake"][0]["text"] = "Compose the digest and read the owner the three asks."          # edited in wz.toml
    (w2,) = wakes.declared(cfg)
    assert wakes.approval(cfg, w2) == "none" and wakes.tick(cfg, at(30, "07:18"), tell_=s.tell)[0]["outcome"] == "unapproved"
    assert s.told == []


def test_a_role_cannot_sign_its_own_wake(project, monkeypatch):
    cfg = with_wakes(project, WAKE)
    wakes.request_missing(cfg)
    monkeypatch.setenv("WZ_ROLE", "mission-ctl")
    with pytest.raises(approvals.SignError, match="owner's"):
        approvals.owner_only()
    assert wakes.approval(cfg, wakes.declared(cfg)[0]) == "pending"


def test_a_sign_that_was_denied_stays_denied(project):
    cfg = with_wakes(project, WAKE)
    (rid,) = wakes.request_missing(cfg)
    approvals.set_pin(cfg, "123456")
    approvals.deny(cfg, rid, "123456", why="not now")
    assert wakes.approval(cfg, wakes.declared(cfg)[0]) == "denied" and wakes.request_missing(cfg) == []
    assert any("denied" in a["text"] for a in wakes.alerts(cfg, at(30, "08:00")))


# ---- wakes: firing -----------------------------------------------------------------------------------------------------------------
def test_an_approved_wake_fires_once_when_due(project):
    cfg, s = with_wakes(project, WAKE), Said()
    wakes.request_missing(cfg)
    sign_all(cfg)
    assert wakes.tick(cfg, at(30, "07:14"), tell_=s.tell) == [] and s.told == []        # 07:15 has not come; yesterday's was before the sign
    out = wakes.tick(cfg, at(30, "07:16"), tell_=s.tell)
    assert [(r["id"], r["outcome"]) for r in out] == [("lead-digest", "said")]
    assert s.told == [("mission-ctl", "[wz wake lead-digest] Compose the digest.", False)]
    assert wakes.tick(cfg, at(30, "07:17"), tell_=s.tell) == [] and len(s.told) == 1      # once per occurrence
    assert any(e["kind"] == "wake" and e["ref"] == "lead-digest" for e in flags.events(cfg))
    again = wakes.tick(cfg, at(31, "07:16"), tell_=s.tell)                                 # next day it fires again
    assert again[0]["outcome"] == "said" and len(s.told) == 2


def test_days_limit_which_occurrences_exist(project):
    cfg = with_wakes(project, {**WAKE, "days": ["mon"]})
    (w,) = wakes.declared(cfg)
    assert dt.datetime.fromtimestamp(wakes.last_occurrence(w, at(30, "08:00"))).strftime("%a %d %H:%M") == "Mon 26 07:15"
    assert dt.datetime.fromtimestamp(wakes.next_occurrence(w, at(30, "08:00"))).strftime("%a %m-%d %H:%M") == "Mon 11-02 07:15"


def test_a_wake_found_too_late_is_missed_not_fired_and_says_so(project):
    cfg, s = with_wakes(project, {**WAKE, "late": "1h"}), Said()
    wakes.request_missing(cfg)
    sign_all(cfg)
    out = wakes.tick(cfg, at(30, "10:30"), tell_=s.tell)                  # the machine was off from 07:00 to 10:30
    assert out[0]["outcome"] == "missed" and s.told == []
    assert any(e["kind"] == "wake-missed" for e in flags.events(cfg))
    (e,) = escalate.open_ones(cfg)
    assert e["sev"] == "P2" and e["subject"] == "mission-ctl" and "was missed" in e["text"]
    assert wakes.tick(cfg, at(30, "10:31"), tell_=s.tell) == []           # handled: not retried


def test_a_wake_for_a_session_that_is_down_is_noted_or_starts_it(project, monkeypatch):
    cfg = with_wakes(project, {**WAKE, "start": True})
    wakes.request_missing(cfg)
    sign_all(cfg)
    s = Said(outcome="noted")
    assert wakes.tick(cfg, at(30, "07:16"), tell_=s.tell)[0]["outcome"] == "noted" and s.told[0][2] is True
    # the real delivery with no tmux session: the line lands at the top of the role's STATE.md
    cfg2 = with_wakes(project, {**WAKE, "id": "other", "start": False})
    monkeypatch.setattr(sessions, "_live", lambda cfg, role: (False, "no live session"))
    assert escalate.tell(cfg2, "mission-ctl", "[wz wake other] hi") == "noted"
    assert "[wz wake other] hi" in (cfg2.role_dir("mission-ctl") / "STATE.md").read_text()


def test_the_lead_with_no_wake_is_named_and_the_table_lists_what_is_declared(project):
    sessions.save(project, "mission-ctl", {**sessions.load(project, "mission-ctl"), "launched": True})
    texts = [a["text"] for a in wakes.alerts(project, at(30, "08:00"))]
    assert len(texts) == 1 and "no approved wake" in texts[0]
    cfg = with_wakes(project, WAKE)
    texts = [a["text"] for a in wakes.alerts(cfg, at(30, "08:00"))]
    assert any("not approved" in t for t in texts) and any("no approved wake" in t for t in texts)
    wakes.request_missing(cfg)
    sign_all(cfg)
    assert wakes.alerts(cfg, at(30, "07:00")) == []                                  # yesterday's 07:15 came before the sign: not missed
    (row,) = wakes.table(cfg, at(30, "08:00"))
    assert row["approval"] == "approved" and row["next"].startswith("2026-10-31T07:15")


def test_a_lead_that_never_started_is_not_nagged(project):
    assert wakes.alerts(project, at(30, "08:00")) == []


# ---- escalation ----------------------------------------------------------------------------------------------------------------------------
def test_each_severity_reaches_its_own_level(project):
    s = Said()
    e2 = escalate.raise_(project, "bench is blocked on the scope", "P2", subject="tester", by="app", tell_=s.tell, push_=s.push)
    e1 = escalate.raise_(project, "two roles want one lease", "P1", subject="app", by="app", tell_=s.tell, push_=s.push)
    e0 = escalate.raise_(project, "the release fails the sign", "P0", subject="app", by="mission-ctl", tell_=s.tell, push_=s.push)
    assert [(r, l.split("]")[0]) for r, l, _ in s.told] == [("tester", f"[wz P2 {e2['id']}"), ("mission-ctl", f"[wz P1 {e1['id']}")]
    assert s.pushed == [(e0["id"], "P0")]
    assert [e["trail"][0]["to"] for e in (e2, e1, e0)] == ["tester", "mission-ctl", "owner"]
    assert {e["kind"] for e in flags.events(project)} == {"escalation"}


def test_a_blocker_rises_when_nobody_answers_and_stops_when_acknowledged(project):
    s, t0 = Said(), 1_800_000_000.0
    e = escalate.raise_(project, "no one owns the lease", "P2", subject="app", by="app", t=t0, tell_=s.tell, push_=s.push)
    assert escalate.tick(project, t0 + 3 * 3600, tell_=s.tell, push_=s.push) == []                  # 4 h not reached
    (m,) = escalate.tick(project, t0 + 4 * 3600, tell_=s.tell, push_=s.push)
    assert m["sev"] == "P1" and s.told[-1][0] == "mission-ctl"
    assert escalate.tick(project, t0 + 4 * 3600 + 1800, tell_=s.tell, push_=s.push) == []             # P1 has an hour
    (m,) = escalate.tick(project, t0 + 5 * 3600 + 1, tell_=s.tell, push_=s.push)
    assert m["sev"] == "P0" and s.pushed == [(e["id"], "P0")]
    escalate.ack(project, e["id"], env={})
    assert escalate.tick(project, t0 + 99 * 3600, tell_=s.tell, push_=s.push) == [] and len(s.pushed) == 1
    assert escalate.get(project, e["id"])["state"] == "acked"


def test_a_p0_repeats_no_faster_than_the_gap_and_no_more_than_the_maximum(project):
    s, t0 = Said(), 1_800_000_000.0
    escalate.raise_(project, "prod is down", "P0", by="wz", t=t0, tell_=s.tell, push_=s.push)
    for minutes in (10, 59, 61, 100, 125, 190, 500):
        escalate.tick(project, t0 + minutes * 60, tell_=s.tell, push_=s.push)
    assert len(s.pushed) == 3                                  # t0, +61 min, +125 min; push_max is 3


def test_the_push_rules_are_read_from_one_section(project):
    project.data["escalation"] = {"push_gap": "10m", "push_max": 5, "stale_p2": "30m", "stale_p1": "5m"}
    assert escalate.rules(project) == {"push": "", "push_gap": 600, "push_max": 5, "stale": {"P2": 1800, "P1": 300}}
    project.data["escalation"] = {"push_gapp": "10m", "stale_p2": "soon"}
    text = "\n".join(escalate.problems(project))
    assert "'push_gapp' is not a setting" in text and "not a duration" in text


def test_a_blocker_about_the_lead_skips_the_lead(project):
    s = Said()
    e = escalate.raise_(project, "the lead's session is stuck", "P1", subject="mission-ctl", by="app", tell_=s.tell, push_=s.push)
    assert s.told == [] and s.pushed == [(e["id"], "P0")] and e["sev"] == "P0"


def test_who_may_raise_and_who_may_acknowledge(project, monkeypatch):
    s = Said()
    with pytest.raises(EscalationError, match="a role may raise P2 or P1"):
        escalate.raise_(project, "x", "P0", by="app", tell_=s.tell, push_=s.push)
    e1 = escalate.raise_(project, "x1", "P1", subject="app", by="app", tell_=s.tell, push_=s.push)
    e0 = escalate.raise_(project, "x0", "P0", by="wz", tell_=s.tell, push_=s.push)
    with pytest.raises(EscalationError, match="a role cannot acknowledge"):
        escalate.ack(project, e1["id"], env={"WZ_ROLE": "app"})
    with pytest.raises(EscalationError, match="owner"):
        escalate.ack(project, e0["id"], env={"WZ_ROLE": "mission-ctl"})                  # the lead cannot acknowledge a push
    assert escalate.ack(project, e1["id"], env={"WZ_ROLE": "mission-ctl"})["state"] == "acked"
    assert escalate.ack(project, e0["id"], env={})["acked_by"] == "owner"
    with pytest.raises(EscalationError, match="already"):
        escalate.ack(project, e0["id"], env={})


def test_the_same_key_while_open_raises_nothing_new(project):
    s = Said()
    a = escalate.raise_(project, "x", "P1", subject="app", by="wz", key="k", tell_=s.tell, push_=s.push)
    b = escalate.raise_(project, "x again", "P1", subject="app", by="wz", key="k", tell_=s.tell, push_=s.push)
    assert a["id"] == b["id"] and len(s.told) == 1
    assert escalate.resolve(project, "k", "gone") == [a["id"]] and escalate.open_ones(project) == []
    c = escalate.raise_(project, "x", "P1", subject="app", by="wz", key="k", tell_=s.tell, push_=s.push)
    assert c["id"] != a["id"]


def test_the_owner_push_runs_the_configured_command_with_the_text_on_stdin(project, tmp_path):
    out = tmp_path / "pushed.txt"
    script = tmp_path / "push.py"
    script.write_text(f"import os, sys\nopen({str(out)!r}, 'a').write(os.environ['WZ_PUSH_SEV'] + '|' + sys.stdin.read().replace('\\n', '/') + '\\n')\n")
    project.data["escalation"] = {"push": f"{sys.executable} {script}"}
    s = Said()
    e = escalate.raise_(project, "do not paste $(rm -rf /) here", "P0", by="wz", tell_=s.tell)           # the real push
    assert e["trail"][0]["outcome"] == "pushed"
    assert out.read_text().startswith("P0|fernhill P0: do not paste $(rm -rf /) here//do not paste $(rm -rf /) here/")


def test_no_push_channel_is_said_not_hidden(project):
    e = escalate.raise_(project, "x", "P0", by="wz", tell_=Said().tell)
    assert "no push channel" in e["trail"][0]["outcome"]
    assert escalate.owner_asks(project)[0]["id"] == e["id"]


def test_a_failing_push_command_is_recorded(project, tmp_path):
    project.data["escalation"] = {"push": f"{sys.executable} -c 'import sys; sys.exit(3)'"}
    e = escalate.raise_(project, "x", "P0", by="wz", tell_=Said().tell)
    assert e["trail"][0]["outcome"].startswith("push failed: exit 3")


# ---- the command line ------------------------------------------------------------------------------------------------------------------------
def test_wz_wake_and_escalate_commands(project, capsys, monkeypatch):
    from wz import cli
    project.path.write_text(project.path.read_text() + '\n[[wake]]\nid = "lead-digest"\nrole = "mission-ctl"\nat = "07:15"\ntext = "Compose the digest."\n')
    base = ["--config", str(project.path)]
    assert cli.main([*base, "wake"]) == 0
    out = capsys.readouterr().out
    assert "lead-digest" in out and "none" in out
    assert cli.main([*base, "wake", "request"]) == 0
    assert "filed sign-0001" in capsys.readouterr().out
    assert cli.main([*base, "wake", "request"]) == 0 and "nothing to ask" in capsys.readouterr().out
    assert cli.main([*base, "escalate", "raise", "stuck on the lease", "--sev", "p2", "--role", "app"]) == 0
    assert "esc-0001 P2" in capsys.readouterr().out
    assert cli.main([*base, "escalate", "list"]) == 0 and "stuck on the lease" in capsys.readouterr().out
    monkeypatch.setenv("WZ_ROLE", "app")
    with pytest.raises(SystemExit, match="a role may raise P2 or P1"):
        cli.main([*base, "escalate", "raise", "wake the owner", "--sev", "P0"])
    with pytest.raises(SystemExit, match="the timer's"):
        cli.main([*base, "wake", "tick"])
    assert cli.main([*base, "agents"]) == 0
