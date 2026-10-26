"""Leases (named holder, released on exit or expiry, never taken over, protected devices, inherited by a job's
commands) and hand-steps (asked by agents, answered only by a person, attended only on hazardous hardware)."""
import json
import os
import subprocess
import sys
import time

import pytest

from wz import config, guard, hands, leases, watchdog
from wz.util import read_json

from conftest import payload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def bench(project, reload):
    p = project.path
    p.write_text(p.read_text() + """
[resources.board-a]
kind = "device"
ids = ["FH-0001"]
max_hold = "2s"

[resources.owner-phone]
kind = "phone"
protected = true
ids = ["OWNERPHONE-1"]

[resources.cell-1]
kind = "battery"
hazard = true

[bench.safety.limits]
volts = [3.0, 3.6]
""")
    return reload(project)


def _holder_proc(cfg, name, seconds):
    code = (f"import sys,time; sys.path.insert(0, {ROOT!r}); from wz import config, leases; "
            f"cfg = config.load({str(cfg.path)!r}); fds = leases.acquire(cfg, [{name!r}], 'job-0042'); "
            f"print('held' if fds else 'busy', flush=True); time.sleep({seconds})")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def test_lock_file_names_the_job_and_others_wait(bench):
    p = _holder_proc(bench, "bench-psu", 30)
    try:
        assert leases.acquire(bench, ["bench-psu"], "job-0099") is None
        h = leases.holder(bench, "bench-psu")
        assert h["holder"] == "job-0042" and h["pid"] == p.pid
        assert "job-0042" in (bench.state / "leases" / "bench-psu.lock").read_text()
    finally:
        p.kill()
        p.wait()
    fds = leases.acquire(bench, ["bench-psu"], "job-0099")
    assert fds, "a lease ends when its holder's process ends, however it ends"
    leases.release(bench, ["bench-psu"], fds)


def test_all_or_none(bench):
    p = _holder_proc(bench, "board-a", 30)
    try:
        assert leases.acquire(bench, ["bench-psu", "board-a"], "job-0001") is None
        assert leases.is_free(bench, "bench-psu"), "a partial lease is given back"
    finally:
        p.kill()
        p.wait()


def test_expired_lease_is_an_alert_never_a_takeover(bench, monkeypatch):
    p = _holder_proc(bench, "board-a", 30)
    try:
        later = time.time() + 60
        assert [a for a in watchdog.check(bench, t=later, apply=False) if a["kind"] == "LEASE"]
        assert leases.acquire(bench, ["board-a"], "job-0005") is None, "an expired lease is still never stolen"
    finally:
        p.kill()
        p.wait()


def test_lease_run_stops_the_command_at_max_hold(bench, tmp_path):
    t0 = time.time()
    rc = leases.run_with(bench, ["board-a"], [sys.executable, "-c", "import time; time.sleep(30)"], holder="owner")
    assert rc == 124 and time.time() - t0 < 15
    assert leases.is_free(bench, "board-a")


def test_lease_run_waits_then_gives_up(bench):
    p = _holder_proc(bench, "bench-psu", 30)
    try:
        t0 = time.time()
        with pytest.raises(leases.LeaseError, match="never taken over"):
            leases.run_with(bench, ["bench-psu"], ["true"], holder="owner", wait_s=1)
        assert time.time() - t0 >= 0.9
    finally:
        p.kill()
        p.wait()


def test_protected_device_is_never_leased_or_named(bench, tmp_path):
    with pytest.raises(leases.LeaseError, match="protected"):
        leases.acquire(bench, ["owner-phone"], "job-0001")
    out = guard.main(stdin=payload("Bash", tmp_path, command="phonectl install app.ipa --device OWNERPHONE-1"),
                     env={"WZ_ROLE": "bench", "WZ_CONFIG": str(bench.path)})
    assert out == 2
    ok = guard.main(stdin=payload("Bash", tmp_path, command="phonectl install app.ipa --device TESTPHONE-B"),
                    env={"WZ_ROLE": "bench", "WZ_CONFIG": str(bench.path)})
    assert ok == 0
    for cmd in ("env -u WZ_ROLE wz hand done hand-0001", "wz hand attend --minutes 60", "wz review words s1 'fine'"):
        assert guard.main(stdin=payload("Bash", tmp_path, command=cmd),
                          env={"WZ_ROLE": "bench", "WZ_CONFIG": str(bench.path)}) == 2, cmd


def test_a_jobs_commands_inherit_its_leases(bench):
    fds = leases.acquire(bench, ["bench-psu"], "job-0010")
    try:
        env = {leases.HELD_ENV: "bench-psu", leases.HOLDER_ENV: "job-0010"}
        assert leases.inherited(bench, ["bench-psu"], env=env) == ["bench-psu"]
        assert leases.inherited(bench, ["bench-psu"], env={leases.HELD_ENV: "bench-psu", leases.HOLDER_ENV: "job-0011"}) == []
        assert leases.inherited(bench, ["bench-psu"], env={}) == []
    finally:
        leases.release(bench, ["bench-psu"], fds)


# ---- hand-steps ---------------------------------------------------------------------------------------------------
def test_hand_step_file_event_and_answer(bench, monkeypatch):
    monkeypatch.setenv("WZ_ROLE", "bench")
    h = hands.ask(bench, "Swap board-a's probe cable", resource="board-a", why="the old cable is intermittent")
    md = (bench.root / "hands" / f"{h['id']}.md").read_text()
    assert "Swap board-a's probe cable" in md and "wz hand done" in md and h["by"] == "bench"
    assert [a for a in watchdog.check(bench, apply=False) if a["kind"] == "HAND"]
    with pytest.raises(hands.HandError, match="agents never"):
        hands.answer(bench, h["id"], "done", "bench")
    monkeypatch.delenv("WZ_ROLE")
    hands.answer(bench, h["id"], "done", "tester", "swapped")
    assert hands.wait(bench, h["id"], poll_s=0.01)["status"] == "done"
    with pytest.raises(hands.HandError):
        hands.answer(bench, h["id"], "done", "tester")


def test_hand_step_expires(bench):
    h = hands.ask(bench, "Plug in the charger", timeout="1s")
    assert hands.wait(bench, h["id"], poll_s=0.1, timeout_s=5)["status"] == "expired"


def test_hazardous_hand_step_needs_attendance(bench):
    h = hands.ask(bench, "Connect cell-1 to the board", resource="cell-1")
    assert h["hazard"] and h["limits"] == {"volts": [3.0, 3.6]}
    with pytest.raises(hands.HandError, match="attendance"):
        hands.answer(bench, h["id"], "done", "tester")
    with pytest.raises(hands.HandError, match="nobody is attending"):
        hands.require_attended(bench, ["cell-1"], "charge")
    hands.attend(bench, "tester", 1)
    hands.require_attended(bench, ["cell-1"], "charge")
    hands.answer(bench, h["id"], "done", "tester")
    assert not hands.attended(bench, t=time.time() + 120), "attendance ends at its expiry"
    with pytest.raises(hands.HandError):
        hands.attend(bench, "agent", 10, env={"WZ_ROLE": "bench"})


def test_limits(bench):
    assert hands.out_of_limits(bench, {"volts": 3.3, "amps": 9}) == []
    assert hands.out_of_limits(bench, {"volts": 4.4}) == ["volts = 4.4 outside 3.0..3.6"]
    assert hands.out_of_limits(bench, {"amps": 0.9}, {"amps": [0, 0.5]}) == ["amps = 0.9 outside 0..0.5"]


def test_cli_hand_and_lease_list(bench, capsys):
    from wz import cli
    assert cli.main(["--config", str(bench.path), "hand", "ask", "Press reset on board-a", "--resource", "board-a"]) == 0
    assert cli.main(["--config", str(bench.path), "hand", "list"]) == 0
    out = capsys.readouterr().out
    assert "hand-0001" in out and "nobody attending" in out
    assert cli.main(["--config", str(bench.path), "lease", "list"]) == 0
    assert "protected" in capsys.readouterr().out
    rec = read_json(bench.root / "hands" / "hand-0001.json")
    assert json.dumps(rec) and rec["status"] == "waiting"
