"""The bench loop on the simulated board in examples/fernhill-bench: budget gates, parity, SCPI capture, hand-steps,
safety limits, device rules and the owner hand-over."""
import shutil
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from wz import bench, config, flags, hands, leases, worker

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "fernhill-bench"
SIM = EXAMPLE / "sim"


# ---- budget gates -----------------------------------------------------------------------------------------------
BERKELEY = "   text    data     bss     dec     hex filename\n  96000    2048   18000  116048   1c550 build/app.elf\n"


def test_parse_size_berkeley_and_json():
    s = bench.parse_size(BERKELEY)
    assert s["flash"] == 96000 + 2048 and s["ram"] == 2048 + 18000 and s["source"] == "berkeley"
    assert bench.parse_size('{"flash": 10, "ram": 20}') == {"flash": 10, "ram": 20, "source": "json"}
    with pytest.raises(bench.BenchError):
        bench.parse_size("no numbers here")


def test_parse_bytes_units():
    assert bench.parse_bytes("512K") == 524288 and bench.parse_bytes("1M") == 1048576 and bench.parse_bytes(77) == 77
    with pytest.raises(bench.BenchError):
        bench.parse_bytes("12 parsecs")


def test_budget_gate_pass_and_over():
    ok = bench.budget_gate({"flash": 98048, "ram": 20048}, {"flash": 524288, "ram": 65536})
    assert ok["pass"] and ok["checks"]["flash"]["headroom"] == 524288 - 98048
    over = bench.budget_gate({"flash": 600000, "ram": 20048}, {"flash": 524288, "ram": 65536})
    assert not over["pass"] and not over["checks"]["flash"]["pass"] and over["checks"]["ram"]["pass"]
    exact = bench.budget_gate({"flash": 100, "ram": 1}, {"flash": 100, "ram": 1})
    assert exact["pass"], "a budget is a limit you may reach, not one you must stay under"


# ---- parity -----------------------------------------------------------------------------------------------------
def test_parity_equal_and_first_difference():
    a = b"".join(bytes([i]) * 8 for i in range(10))
    assert bench.parity(a, a, 8)["equal"]
    b = bytearray(a)
    b[8 * 6 + 3] ^= 1
    p = bench.parity(a, bytes(b), 8)
    assert not p["equal"] and p["first_difference"]["record"] == 6 and p["first_difference"]["byte"] == 3
    assert p["records_equal"] == 9


def test_parity_count_mismatch_and_lines():
    p = bench.parity(b"a\nb\nc\n", b"a\nb\n", "line")
    assert not p["equal"] and "record counts differ" in p["first_difference"]["note"]
    assert bench.parity(b"x\ny\n", b"x\ny\n")["equal"]
    assert not bench.parity(b"x\ny\n", b"x\ny")["equal"], "byte for byte: a missing newline is a difference"


def _sim(*args, cwd):
    subprocess.run([sys.executable, *map(str, args)], cwd=cwd, check=True, capture_output=True)


def test_simulated_device_matches_host_and_a_fault_is_caught(tmp_path):
    _sim(SIM / "gen_inputs.py", "--seed", "3", "--n", "300", "--out", tmp_path / "in.txt", cwd=tmp_path)
    _sim(SIM / "host_ref.py", tmp_path / "in.txt", tmp_path / "host.bin", cwd=tmp_path)
    for fault, want in ((None, True), (120, False)):
        out = tmp_path / f"b{fault}"
        _sim(SIM / "build.py", "--out", out, *(["--fault", fault] if fault else []), cwd=tmp_path)
        _sim(SIM / "device.py", "flash", out / "app.img", "--state", out / "st", cwd=tmp_path)
        _sim(SIM / "device.py", "play", tmp_path / "in.txt", "--state", out / "st", cwd=tmp_path)
        p = bench.parity((out / "st" / "records.bin").read_bytes(), (tmp_path / "host.bin").read_bytes(), 8)
        assert p["equal"] is want
        if fault:
            assert p["first_difference"]["record"] == 120 and p["records_device"] == 300


# ---- the whole loop -----------------------------------------------------------------------------------------------
class _Scpi(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _scpi_server(readings):
    class H(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile:
                q = line.decode().strip()
                if q.endswith("?"):
                    self.wfile.write((readings.get(q, "0") + "\n").encode())
    srv = _Scpi(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def benchws(tmp_path):
    ws = tmp_path / "bench"
    shutil.copytree(EXAMPLE, ws, ignore=shutil.ignore_patterns(".sim", ".wz", "bench", "hands", "roles"))
    readings = {"*IDN?": "TEST,PA-9,42,1.0", "MEAS:VOLT?": "3.30", "MEAS:CURR?": "0.014", "MEAS:TEMP?": "25.0"}
    srv = _scpi_server(readings)
    text = (ws / "wz.toml").read_text().replace("127.0.0.1:5025", f"127.0.0.1:{srv.server_address[1]}")
    (ws / "wz.toml").write_text(text)
    sc = ws / "scenarios" / "replay.toml"
    sc.write_text(sc.read_text().replace('timeout = "30m"', 'timeout = "15s"'))   # an unanswered step expires, never hangs
    cfg = config.load(ws / "wz.toml")
    yield cfg, ws, readings
    srv.shutdown()
    srv.server_close()


def _answer_when_asked(cfg, status="done"):
    """A person at the bench answers the first hand-step it sees (env={}: not a role session)."""
    def go():
        for _ in range(200):
            w = hands.waiting(cfg)
            if w:
                hands.answer(cfg, w[0]["id"], status, "tester", "leads on", env={})
                return
            time.sleep(0.05)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def test_whole_loop_passes_and_names_every_field(benchws, monkeypatch):
    cfg, ws, _ = benchws
    monkeypatch.setenv("WZ_ROLE", "bench")
    monkeypatch.setenv("WZ_JOB", "job-0007")
    t = _answer_when_asked(cfg)
    rec = bench.run(cfg, ws / "scenarios" / "replay.toml", say=lambda *_: None, hand_poll_s=0.05)
    t.join(5)
    assert rec["verdict"] == "pass", rec.get("why")
    assert [s["kind"] for s in rec["steps"]] == ["host", "firmware", "hand", "flash", "drive", "capture", "records", "parity", "app"]
    got = {f["field"]: f["value"] for f in rec["fields"]}
    assert got["parity.records_equal"] == "600/600" and got["analyser.volts"] == 3.30 and got["hand-0001.status"] == "done"
    assert got["budget.flash"].startswith("98048 of 524288")
    report = (bench.runs_dir(cfg) / rec["run"] / "REPORT.md").read_text()
    assert "## Fields read" in report and "TEST,PA-9,42,1.0" in report
    assert all(leases.is_free(cfg, n) for n in rec["leases"]), "leases end with the run"
    assert any(e["kind"] == "bench" for e in flags.events(cfg))


def test_over_budget_stops_before_flash(benchws):
    cfg, ws, _ = benchws
    sc = ws / "scenarios" / "replay.toml"
    sc.write_text(sc.read_text().replace("sim/build.py --out {run}/build", "sim/build.py --bloat --out {run}/build"))
    rec = bench.run(cfg, sc, say=lambda *_: None)
    assert rec["verdict"] == "fail" and "over budget: flash" in rec["why"]
    assert [s["kind"] for s in rec["steps"]] == ["host", "firmware"], "nothing is flashed after a failed gate"


def test_parity_failure_names_the_record(benchws):
    cfg, ws, _ = benchws
    sc = ws / "scenarios" / "replay.toml"
    sc.write_text(sc.read_text().replace("sim/build.py --out {run}/build", "sim/build.py --fault 250 --out {run}/build"))
    _answer_when_asked(cfg)
    rec = bench.run(cfg, sc, say=lambda *_: None, hand_poll_s=0.05)
    assert rec["verdict"] == "fail" and "record 250" in rec["why"]
    assert rec["steps"][-1]["kind"] == "parity", "the app step does not run on a board that disagrees with the host"


def test_refused_hand_step_blocks_the_run(benchws):
    cfg, ws, _ = benchws
    _answer_when_asked(cfg, status="refused")
    rec = bench.run(cfg, ws / "scenarios" / "replay.toml", say=lambda *_: None, hand_poll_s=0.05)
    assert rec["verdict"] == "blocked" and "refused" in rec["why"]


def test_safety_limit_halts_and_makes_safe(benchws):
    cfg, ws, readings = benchws
    readings["MEAS:VOLT?"] = "4.90"
    _answer_when_asked(cfg)
    rec = bench.run(cfg, ws / "scenarios" / "replay.toml", say=lambda *_: None, hand_poll_s=0.05)
    assert rec["verdict"] == "halted" and "volts = 4.9 outside 3.0..3.6" in rec["why"]
    assert (bench.runs_dir(cfg) / rec["run"] / "safe-state.txt").exists()
    assert worker.halted(cfg, "bench")


def test_hazardous_step_needs_attendance(benchws):
    cfg, ws, _ = benchws
    sc = ws / "scenarios" / "charge.toml"
    sc.write_text('name = "charge"\ndevice = "board-a"\ncwd = ".."\n[[step]]\nkind = "drive"\nresource = "cell-1"\n'
                  'run = "echo charging"\n')
    rec = bench.run(cfg, sc, say=lambda *_: None)
    assert rec["verdict"] == "blocked" and "nobody is attending" in rec["why"]
    hands.attend(cfg, "tester", 5, env={})
    assert bench.run(cfg, sc, say=lambda *_: None)["verdict"] == "pass"


def test_device_rules(benchws):
    cfg, ws, _ = benchws
    sc = ws / "scenarios" / "x.toml"
    sc.write_text('name = "x"\ndevice = "board-a"\nphone = "owner-phone"\n[[step]]\nkind = "app"\nrun = "true"\n')
    with pytest.raises(bench.BenchError, match="protected"):
        bench.run(cfg, sc, say=lambda *_: None)
    text = (ws / "wz.toml").read_text() + '\n[resources.phone-c]\nkind = "phone"\n'
    (ws / "wz.toml").write_text(text)
    cfg = config.load(ws / "wz.toml")
    sc.write_text('name = "x"\ndevice = "board-a"\nphone = "phone-c"\n[[step]]\nkind = "app"\nrun = "true"\n')
    with pytest.raises(bench.BenchError, match="reserved to phone-b"):
        bench.run(cfg, sc, say=lambda *_: None)


def test_owner_is_never_the_first_tester(benchws, monkeypatch):
    cfg, ws, _ = benchws
    sc = ws / "scenarios" / "replay.toml"
    with pytest.raises(bench.BenchError, match="never the first tester"):
        bench.ready_for_owner(cfg, sc)
    _answer_when_asked(cfg)
    bench.run(cfg, sc, say=lambda *_: None, hand_poll_s=0.05)        # the owner's own run does not count
    with pytest.raises(bench.BenchError):
        bench.ready_for_owner(cfg, sc)
    monkeypatch.setenv("WZ_ROLE", "bench")
    _answer_when_asked(cfg)
    rec = bench.run(cfg, sc, say=lambda *_: None, hand_poll_s=0.05)
    assert bench.ready_for_owner(cfg, sc)["run"] == rec["run"]


def test_capture_reads_scpi(benchws):
    cfg, _, _ = benchws
    cap = bench.capture(cfg, "analyser", {"amps": "MEAS:CURR?"})
    assert cap["idn"] == "TEST,PA-9,42,1.0" and cap["fields"]["amps"]["value"] == 0.014


def test_an_error_mid_run_is_recorded_not_left_running(benchws):
    cfg, ws, _ = benchws
    sc = ws / "scenarios" / "bad.toml"
    sc.write_text('name = "bad"\ndevice = "board-a"\n[[step]]\nkind = "flash"\nrun = "flash {device.nope}"\n')
    with pytest.raises(bench.BenchError, match="placeholder"):
        bench.run(cfg, sc, say=lambda *_: None)
    rec = bench.all_runs(cfg)[-1]
    assert rec["verdict"] == "error" and leases.is_free(cfg, "board-a")
