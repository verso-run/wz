"""Build and release: holds with an expiry and freezes, pins by hash and ring gates, the revert rehearsal, the live
read, the flag inventory; and queue upkeep: remint with re-pointing, backlog refill, prune, nightly, review loop."""
import http.server
import json
import threading
import time
import tomllib

import pytest

from wz import config, featureflags, jobs, merge, records, release, review, upkeep
from wz.worker import base_branch


@pytest.fixture
def rel(project, reload):
    data = tomllib.loads(project.path.read_text())
    data["rings"] = {"order": ["lab", "dev", "prod"], "sign": ["prod"],
                     "dev": {"gates": ['test -s "$WZ_ARTIFACT"', "test ${#WZ_ARTIFACT_SHA256} -eq 64"],
                             "deploy": "echo deploy >> rings.log", "rollback": "echo rollback >> rings.log"}}
    data["release"] = {"pin_params": ["sample_hz", "threshold"], "flag_sources": ["src/**/*.py"]}
    project.path.write_text(config.dumps(data))
    return reload(project)


# ---- holds --------------------------------------------------------------------------------------------------------
def test_blocking_hold_stops_promote_until_cleared_by_a_decision(rel):
    with pytest.raises(release.ReleaseError, match="evidence"):
        release.hold_add(rel, "app", "BLOCKS", "export drops rows")
    base_branch(rel, "app")
    h = release.hold_add(rel, "app", "BLOCKS", "export drops rows", evidence="runs/x/REPORT.md")
    with pytest.raises(release.ReleaseError, match="held"):
        merge.promote(rel, "app")
    with pytest.raises(release.ReleaseError, match="not a row"):
        release.hold_clear(rel, h["id"], "D-9")
    did = records.decide(rel, "ship it, the dropped rows are the test fixture", "the finding was a fixture artefact")
    release.hold_clear(rel, h["id"], did)
    assert merge.promote(rel, "app")["id"].startswith("sign-")


def test_inconclusive_blocks_note_does_not_and_holds_expire(rel):
    release.hold_add(rel, "prod", "NOTE", "slow first load")
    release.check_not_held(rel, "prod")
    release.hold_add(rel, "prod", "INCONCLUSIVE", "soak test did not finish", evidence="status/soak.txt", expires="1s")
    with pytest.raises(release.ReleaseError):
        release.check_not_held(rel, "prod")
    time.sleep(1.1)
    release.check_not_held(rel, "prod")
    assert [h["state"] for h in release.holds(rel)] == ["open", "expired"]


def test_freeze_stops_the_merge_step(rel):
    release.hold_add(rel, "app", "FREEZE", "presign window for the release candidate")
    said = []
    assert merge.merge(rel, say=said.append) == []
    assert "frozen" in said[0]


# ---- pins, gates, rehearsal, live read ----------------------------------------------------------------------------
def test_gate_reads_the_pinned_artifact(rel, tmp_path):
    art = tmp_path / "app-1.2.tar"
    art.write_bytes(b"artifact bytes")
    with pytest.raises(release.ReleaseError, match="pin_params"):
        release.pin(rel, "dev", art, {"logic": "x"})
    release.pin(rel, "dev", art, {"sample_hz": "50"})
    r = release.gate(rel, "dev")
    assert r["pass"] and len(r["gates"]) == 2 and (rel.root / "status" / "releases" / r["sha256"][:12] / "dev-gate.json").exists()
    art.write_bytes(b"swapped after pinning")
    with pytest.raises(release.ReleaseError, match="never a label"):
        release.gate(rel, "dev")


def test_rehearse_rollback_on_an_unsigned_ring_only(rel, tmp_path):
    art = tmp_path / "a.bin"
    art.write_bytes(b"x")
    release.pin(rel, "dev", art)
    r = release.rehearse(rel, "dev")
    assert r["pass"] and (rel.root / "rings.log").read_text().split() == ["deploy", "rollback", "deploy"]
    with pytest.raises(release.ReleaseError, match="signed ring"):
        release.rehearse(rel, "prod")


def test_live_read_writes_the_field_as_evidence(rel):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"code": {"version": "1.2.0"}, "flags": {"export_csv": True}}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        p = rel.path
        p.write_text(p.read_text().replace('[rings.dev]\n', f'[rings.dev]\nhealth_url = "http://127.0.0.1:{srv.server_address[1]}/healthz"\n'))
        cfg = config.load(p)
        r = release.live_read(cfg, "dev", "code.version")
        assert r["value"] == "1.2.0" and (cfg.root / "status" / "live" / "dev-code.version.json").exists()
        with pytest.raises(release.ReleaseError, match="not in what the ring served"):
            release.live_read(cfg, "dev", "code.nope")
    finally:
        srv.shutdown()
        srv.server_close()


# ---- flags inventory ----------------------------------------------------------------------------------------------
def test_flag_inventory(rel):
    src = rel.root / "src"
    src.mkdir()
    (src / "a.py").write_text('if flag("export_csv"):\n    pass\nif flag(\'night_mode\'):\n    pass\n')
    (rel.root / "flags.toml").write_text('[flag.export_csv]\nowner = "app"\ndefault = false\n'
                                         '[flag.old_thing]\nowner = "app"\ndefault = false\n')
    errors, warnings = featureflags.check(rel)
    assert errors == ["night_mode: used at src/a.py:3 but not registered in flags.toml"]
    assert warnings and "old_thing" in warnings[0]
    (rel.root / "flags.toml").write_text('[flag.export_csv]\nowner = "app"\ndefault = true\n'
                                         '[flag.night_mode]\nowner = "app"\ndefault = true\nrelease_default = true\ndecision = "D-1"\n')
    errors, _ = featureflags.check(rel)
    assert any("export_csv: defaults on" in e for e in errors) and any("night_mode: release_default needs" in e for e in errors)
    records.decide(rel, "night mode ships on", "release default")
    errors, _ = featureflags.check(rel)
    assert errors == ["export_csv: defaults on; new behaviour ships off unless a decision names it the release default"]


# ---- queue upkeep -------------------------------------------------------------------------------------------------
def test_remint_repoints_dependents(rel):
    a = jobs.add(rel, "app", "build the export", timeout="10m")
    b = jobs.add(rel, "tester", "test the export", after=a["id"])
    with pytest.raises(jobs.JobError):
        jobs.remint(rel, a["id"])
    j = jobs.get(rel, a["id"])
    j.update(status="failed", timed_out=True)
    jobs.save(rel, j)
    n = jobs.remint(rel, a["id"])
    assert n["timeout_s"] == 1200 and n["reminted_from"] == a["id"] and n["repointed"] == [b["id"]]
    assert jobs.get(rel, b["id"])["after"] == n["id"] and jobs.get(rel, a["id"])["reminted_as"] == n["id"]
    with pytest.raises(jobs.JobError, match="already reminted"):
        jobs.remint(rel, a["id"])


def test_backlog_refill_is_idempotent(rel):
    records.ledger_add(rel, "defects", {"severity": "P2", "role": "app", "what": "export drops the last row"})
    records.ledger_add(rel, "defects", {"severity": "P3", "role": "app", "what": "old", "status": "fixed"})
    records.ledger_add(rel, "followups", {"from": "job-0001", "role": "tester", "task": "add an export e2e test"})
    assert upkeep.refill(rel) == {"app": ["DEF-001"], "tester": ["FU-001"]}
    assert upkeep.refill(rel) == {}
    assert "- [ ] DEF-001: export drops the last row" in (rel.role_dir("app") / "BACKLOG.md").read_text()


def test_prune_duplicates_stale_holds_and_focus(rel, reload):
    a = jobs.add(rel, "app", "add CSV export to the history page", priority=20)
    b = jobs.add(rel, "app", "add CSV export to history page", priority=50)
    c = jobs.add(rel, "app", "rewrite the logo in pastel", priority=60)
    d = jobs.add(rel, "app", "fix export timezone", priority=55)
    jobs.hold(rel, d["id"], "later")
    p = rel.path
    p.write_text(p.read_text() + '\n[focus]\npatterns = ["export"]\nhold_days = 1\n')
    rel = reload(rel)
    acts = upkeep.prune(rel, t=time.time() + 3 * 86400)
    assert {(x["action"], x["job"]) for x in acts} == {("cancel", b["id"]), ("cancel", d["id"]), ("hold", c["id"])}
    upkeep.prune(rel, apply=True, t=time.time() + 3 * 86400)
    assert jobs.get(rel, a["id"])["status"] == "queued" and jobs.get(rel, b["id"])["status"] == "cancelled"


def test_nightly_queues_once_per_day(rel, reload):
    p = rel.path
    p.write_text(p.read_text() + '\n[[nightly]]\nrole = "tester"\ntask = "run the full e2e suite on integration"\n')
    rel = reload(rel)
    assert len(upkeep.nightly(rel, day="2026-01-01")) == 1
    assert upkeep.nightly(rel, day="2026-01-01") == []
    assert len(upkeep.nightly(rel, day="2026-01-02")) == 1


def test_review_collects_drafts_and_waits_for_the_owners_words(rel, tmp_path, reload):
    sess = tmp_path / "session-7"
    sess.mkdir()
    (sess / "log.csv").write_text("t,v\n0,1\n1,3\n")
    p = rel.path
    p.write_text(p.read_text() + '\n[review]\nmetrics = "python3 -c \\"import json; json.dump({\'rows\': 2, \'max\': 3}, open(\'{out}\', \'w\'))\\""\n')
    rel = reload(rel)
    path = review.collect(rel, sess, by="tester")
    text = path.read_text()
    assert "| rows | 2 | metrics.json |" in text and review.drafts(rel) == ["session-7"]
    assert (rel.root / "runs" / "session-7" / "session" / "log.csv").exists()
    with pytest.raises(review.ReviewError, match="never writes"):
        review.words(rel, "session-7", "felt fine", env={"WZ_ROLE": "tester"})
    review.words(rel, "session-7", "felt fine, the valve clicked twice", env={})
    assert review.drafts(rel) == [] and "the valve clicked twice" in path.read_text()
