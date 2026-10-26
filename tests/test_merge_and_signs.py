import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from conftest import answers, git, make_repo
from wz import approvals, approve_page, jobs, merge, worker, setup_mode

QUIET = dict(say=lambda *_: None)


def done_job(cfg, role="app"):
    j = jobs.add(cfg, role, "change")
    worker.serve(cfg, role=role, wait=True, **QUIET)
    j = jobs.get(cfg, j["id"])
    assert j["status"] == "done"
    return j


def test_green_branch_is_merged(project):
    j = done_job(project)
    app = project.store_root("app")
    before = git(app, "rev-parse", "integration")
    v = merge.merge(project, **QUIET)
    assert [x["verdict"] for x in v] == ["merged"]
    after = git(app, "rev-parse", "integration")
    assert after != before and after == jobs.get(project, j["id"])["merged"]
    assert git(app, "rev-parse", "main") == before
    assert merge.merge(project, **QUIET) == []


def test_red_check_refuses(tmp_path):
    make_repo(tmp_path / "app")
    (tmp_path / "office").mkdir()
    cfg = setup_mode.apply(answers(tmp_path, checks=["false"]), tmp_path / "ws", git_init=False)
    j = done_job(cfg)
    before = git(cfg.store_root("app"), "rev-parse", "integration")
    v = merge.merge(cfg, **QUIET)
    assert v[0]["verdict"] == "red" and v[0]["check"] == "false"
    assert git(cfg.store_root("app"), "rev-parse", "integration") == before
    assert jobs.get(cfg, j["id"])["merge_refused"] == "red"


def test_ownership_backstop(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "outside")
    done_job(project)
    v = merge.merge(project, **QUIET)
    assert v[0]["verdict"] == "ownership" and v[0]["files"] == ["README-outside.md"]


def test_conflict_is_a_verdict(project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "conflict")
    done_job(project)
    done_job(project)
    v = merge.merge(project, **QUIET)
    assert [x["verdict"] for x in v] == ["merged", "conflict"]


def test_dry_run_moves_nothing(project):
    done_job(project)
    before = git(project.store_root("app"), "rev-parse", "integration")
    v = merge.merge(project, dry_run=True, **QUIET)
    assert v[0]["verdict"] == "would-merge"
    assert git(project.store_root("app"), "rev-parse", "integration") == before


def test_promote_needs_the_sign(project):
    done_job(project)
    merge.merge(project, **QUIET)
    app = project.store_root("app")
    integ = git(app, "rev-parse", "integration")
    req = merge.promote(project, "app", by="mission-ctl")
    assert req["action"]["sha"] == integ
    with pytest.raises(approvals.SignError, match="not signed"):
        approvals.run(project, req["id"])
    approvals.set_pin(project, "246810")
    approvals.sign(project, req["id"], "246810")
    out = approvals.run(project, req["id"])
    assert out["rc"] == 0 and git(app, "rev-parse", "main") == integ
    with pytest.raises(approvals.SignError, match="already run"):
        approvals.run(project, req["id"])


def test_pin_lockout_and_write_once(project):
    approvals.set_pin(project, "135790")
    r = approvals.request(project, "send the invoice", command="echo sent")
    for _ in range(approvals.MAX_FAILS):
        with pytest.raises(approvals.SignError, match="wrong PIN"):
            approvals.sign(project, r["id"], "000000")
    with pytest.raises(approvals.SignError, match="locked"):
        approvals.sign(project, r["id"], "135790")
    (project.state / "approvals" / "fails.json").unlink()
    approvals.sign(project, r["id"], "135790")
    with pytest.raises(approvals.SignError, match="already signed"):
        approvals.sign(project, r["id"], "135790")
    assert approvals.run(project, r["id"])["output"].strip() == "sent"


def test_tampered_request_does_not_run(project):
    approvals.set_pin(project, "135790")
    r = approvals.request(project, "post the notice", command="echo ok")
    approvals.sign(project, r["id"], "135790")
    p = project.state / "approvals" / "requests" / f"{r['id']}.json"
    p.write_text(p.read_text().replace("echo ok", "echo something-else"))
    with pytest.raises(approvals.SignError, match="changed after"):
        approvals.run(project, r["id"])


def test_deny_and_role_sessions(project, monkeypatch):
    approvals.set_pin(project, "135790")
    r = approvals.request(project, "pay supplier", command="true")
    approvals.deny(project, r["id"], "135790", why="wrong amount")
    with pytest.raises(approvals.SignError, match="denied"):
        approvals.run(project, r["id"])
    monkeypatch.setenv("WZ_ROLE", "writer")
    with pytest.raises(approvals.SignError, match="owner's"):
        approvals.owner_only()
    with pytest.raises(approvals.SignError):
        approvals.request(project, "no command")
    with pytest.raises(approvals.SignError):
        approvals.set_pin(project, "123")


def _post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_approval_page(project):
    approvals.set_pin(project, "135790")
    r = approvals.request(project, "send the grant letter", command="echo letter", by="writer")
    srv = approve_page.serve_in_thread(project)
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            page = resp.read().decode()
            assert resp.headers["X-Frame-Options"] == "DENY"
        assert "send the grant letter" in page and "echo letter" in page
        csrf = page.split("name=csrf value='")[1].split("'")[0]
        code, body = _post(base + "/sign", {"id": r["id"], "pin": "135790", "csrf": "stale", "do": "sign"})
        assert code == 403 and approvals.status(project, r["id"]) == "pending"
        code, body = _post(base + "/sign", {"id": r["id"], "pin": "999999", "csrf": csrf, "do": "sign"})
        assert code == 403 and "wrong PIN" in body
        code, body = _post(base + "/sign", {"id": r["id"], "pin": "135790", "csrf": csrf, "do": "sign"})
        assert code == 200 and approvals.status(project, r["id"]) == "signed"
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            assert "Nothing waits" in resp.read().decode()
    finally:
        srv.shutdown()
        srv.server_close()
    time.sleep(0.05)
