"""The agent watchdog and the wakes against a REAL tmux with the stand-in `claude` (same rig as test_sessions.py).

Each test runs its own tmux server; skipped when tmux is not installed (a failure when WZ_REQUIRE_TMUX is set, as in CI).
"""
import datetime as dt
import json
import time

from test_sessions import cfg, rig  # noqa: F401  (fixtures)

from wz import agents, approvals, hub, sessions, wakes, watchdog


def said(cfg, n, timeout=8):
    f = cfg.root / "said.jsonl"
    end = time.time() + timeout
    while time.time() < end:
        rows = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
        if len(rows) >= n:
            return [r["text"] for r in rows]
        time.sleep(0.1)
    raise AssertionError(f"wanted {n} lines typed into the stand-in, saw {len(rows) if f.exists() else 0}")


def test_two_windows_for_one_role_are_a_zombie_and_the_hub_names_it(rig, cfg):
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0 and rig.wz(cfg, "cli", "app", "--detach") == 0
    rig.calls(cfg, 2)
    rows = {r["role"]: r["status"] for r in agents.table(cfg)}
    assert rows == {"mission-ctl": "idle", "app": "idle"}                       # one window each, up, waiting at the input box
    name, _ = hub.prepare(cfg)
    assert [r["status"] for r in agents.tick(cfg)] == ["idle", "idle"]
    assert rig.tmux("show-options", "-v", "-t", f"={name}:", "status-right").stdout.strip() == ""
    # the second window: a stray session, as a restart of the hub or a hand-made `tmux new -s` leaves behind
    assert rig.tmux("new-session", "-d", "-s", "stray", "-n", "mission-ctl", "sleep 600").returncode == 0
    assert agents.table(cfg)[0]["status"] == "idle"                              # not ours (no @wz_root): left alone
    rig.tmux("set-option", "-t", "=stray:", "@wz_root", str(cfg.root))
    rows = {r["role"]: r for r in agents.table(cfg)}
    assert rows["mission-ctl"]["status"] == "zombie" and "duplicate: 2 windows" in rows["mission-ctl"]["reason"]
    assert rows["app"]["status"] == "idle"
    alerts = watchdog.check(cfg)
    assert ("ZOMBIE", "session:mission-ctl") in {(a["kind"], a["ref"]) for a in alerts}
    assert rig.tmux("show-options", "-v", "-t", f"={name}:", "status-right").stdout.strip() == "! mission-ctl:ZOMBIE"
    rig.tmux("kill-session", "-t", "=stray")                                      # the stale one goes: the hub clears on the next tick
    watchdog.check(cfg)
    assert rig.tmux("show-options", "-v", "-t", f"={name}:", "status-right").stdout.strip() == ""


def test_claude_ended_in_a_live_window_is_a_zombie(rig, cfg):
    assert rig.wz(cfg, "cli", "app", "--detach") == 0
    rig.calls(cfg, 1)
    (sessions.state_dir(cfg) / "app.state").write_text("exited 1 600\n")
    (row,) = agents.table(cfg)
    assert row["status"] == "zombie" and "Claude ended" in row["reason"]


def test_an_approved_wake_is_typed_into_the_live_session(rig, cfg):
    assert rig.wz(cfg, "cli", "mission-ctl", "--detach") == 0
    rig.calls(cfg, 1)
    cfg.data["wake"] = [{"id": "lead-digest", "role": "mission-ctl", "at": "07:15", "text": "Compose the digest."}]
    assert any("no approved wake" in a["text"] for a in wakes.alerts(cfg))          # the lead has none yet
    wakes.request_missing(cfg)
    approvals.set_pin(cfg, "123456")
    for r in approvals.pending(cfg):
        approvals.sign(cfg, r["id"], "123456")
    tomorrow = dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(7, 16)).timestamp()
    (r,) = wakes.tick(cfg, tomorrow)
    assert r["outcome"] == "said"
    assert said(cfg, 1) == ["[wz wake lead-digest] Compose the digest."]
    assert wakes.alerts(cfg, tomorrow) == []
