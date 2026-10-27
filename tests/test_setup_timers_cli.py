import json
import plistlib
import subprocess
import sys

import pytest

from conftest import FAKE, make_repo
from wz import cli, config, jobs, scan, setup_mode, timers


def test_example_answers_make_a_valid_project(tmp_path):
    cfg = setup_mode.apply(setup_mode.ANSWERS_EXAMPLE, tmp_path / "ws", git_init=True)
    assert set(cfg.roles()) == {"mission-ctl", "app", "tester", "firmware", "bench", "writer"}
    assert cfg.role("writer")["store"] == "office" and cfg.role("firmware")["store"] == "firmware"
    for role in cfg.roles():
        text = cfg.charter_path(role).read_text()
        assert f"role `{role}`" in text and "Kill only the process ID you started" in text
    assert "Lead commands" in cfg.charter_path("mission-ctl").read_text()
    assert "Lead commands" not in cfg.charter_path("app").read_text()
    hooks = json.loads(cfg.role_settings.read_text())["hooks"]
    assert hooks["PreToolUse"][0]["hooks"][0]["command"].endswith("hook guard")
    for f in ("PLAN.md", "DECISIONS.md", "AGENTS.md", "briefs/TEMPLATE.md", "ledgers/DEFECTS.md", ".gitignore"):
        assert (cfg.root / f).exists(), f
    assert (cfg.root / ".git").exists()
    with pytest.raises(setup_mode.SetupError, match="exists"):
        setup_mode.apply(setup_mode.ANSWERS_EXAMPLE, tmp_path / "ws")


def test_plain_interview(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    replies = iter(["fernhill", "a made-up controller", "software hardware", "app", "git", "../app", "main",
                    "integration", "make test", "", "psu", "instrument", "bench supply", "", "", "25", "07:30"])
    a = setup_mode.interview_plain(ask=lambda _q: next(replies), say=lambda *_: None)
    assert a["project"] == "fernhill" and a["workflows"] == ["software", "hardware"]
    assert a["stores"]["app"]["checks"] == ["make test"] and a["resources"]["psu"]["kind"] == "instrument"
    assert a["budget_usd"] == 25.0 and a["digest_time"] == "07:30"
    cfg = setup_mode.apply(a, tmp_path / "ws", git_init=False)
    assert cfg.role("bench")["pack"] == "hardware"


def test_init_example_end_to_end_via_cli(tmp_path):
    make_repo(tmp_path / "app")
    a = dict(setup_mode.ANSWERS_EXAMPLE, agent_command=f"{sys.executable} {FAKE}")
    a["stores"] = {"app": {"kind": "git", "path": "../app", "main": "main", "integration": "integration", "checks": []}}
    (tmp_path / "answers.json").write_text(json.dumps(a))
    ws = tmp_path / "ws"
    assert cli.main(["init", "--answers", str(tmp_path / "answers.json"), "--dir", str(ws), "--no-git"]) == 0
    assert cli.main(["init", "--example", "--dir", str(ws)]) == 0
    cfg = config.load(ws / "wz.toml")
    assert jobs.get(cfg, "job-0001")["status"] == "done"


def test_cli_without_config_starts_setup(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(setup_mode, "launch_setup", lambda d: seen.setdefault("dir", d) and 0)
    monkeypatch.chdir(tmp_path)
    cli.main(["cli", "mission-ctl", "--dir", str(tmp_path)])
    assert seen["dir"] == tmp_path.resolve()
    charter = setup_mode.setup_charter(tmp_path)
    assert "interview" in charter and "init --answers" in charter and "set-pin" in charter


def test_cli_print_and_commands(project, capsys):
    p = str(project.path)
    assert cli.main(["--config", p, "cli", "app", "--print"]) == 0
    out = capsys.readouterr().out
    assert "WZ_ROLE=app" in out and "--append-system-prompt-file" in out and "--model sonnet" in out
    assert cli.main(["--config", p, "job", "add", "app", "write the parser", "-p", "20"]) == 0
    assert cli.main(["--config", p, "queue"]) == 0
    assert "write the parser" in capsys.readouterr().out
    assert cli.main(["--config", p, "decide", "parser first", "--reading", "parser before UI"]) == 0
    assert cli.main(["--config", p, "ledger", "add", "defects", "the parser drops tabs", "--field", "severity=low"]) == 0
    assert cli.main(["--config", p, "status"]) == 0
    assert cli.main(["--config", p, "budget"]) == 0
    assert cli.main(["--config", p, "watchdog"]) == 0
    assert cli.main(["--config", p, "halt", "app", "--why", "test"]) == 0
    assert cli.main(["--config", p, "resume", "app"]) == 0
    assert cli.main(["--config", p, "lease", "list"]) == 0
    assert cli.main(["--config", p, "job", "add", "ghost", "x"]) == 1


def test_role_session_cannot_unlock_or_decide(project, monkeypatch):
    monkeypatch.setenv("WZ_ROLE", "app")
    with pytest.raises(SystemExit, match="only the lead"):
        cli.main(["--config", str(project.path), "unlock", "tester"])
    with pytest.raises(SystemExit, match="only the lead"):
        cli.main(["--config", str(project.path), "decide", "x"])
    with pytest.raises(SystemExit, match="owner's"):
        cli.main(["--config", str(project.path), "sign", "approve", "sign-0001"])


def test_lease_run_holds_for_one_command(project):
    rc = cli.main(["--config", str(project.path), "lease", "run", "bench-psu", "--", sys.executable, "-c",
                   "import sys; sys.exit(3)"])
    assert rc == 3


def test_linux_units(project):
    units = timers.linux_units(project)
    assert set(units) == {f"wz-fernhill-{n}.{k}" for n in ("serve", "merge", "watchdog", "digest", "nightly") for k in ("service", "timer")}
    assert "KillMode=process" in units["wz-fernhill-serve.service"]
    assert "OnUnitActiveSec=60s" in units["wz-fernhill-serve.timer"]
    assert "OnCalendar=*-*-* 08:00:00" in units["wz-fernhill-digest.timer"]
    assert "OnCalendar=*-*-* 02:30:00" in units["wz-fernhill-nightly.timer"]
    assert f"--config {project.path} serve --quiet" in units["wz-fernhill-serve.service"]


def test_macos_plists(project):
    pl = {k: plistlib.loads(v) for k, v in timers.macos_plists(project).items()}
    serve = pl["org.wz.fernhill.serve.plist"]
    assert serve["StartInterval"] == 60 and serve["AbandonProcessGroup"] is True
    assert serve["ProgramArguments"][-2:] == ["serve", "--quiet"]
    assert pl["org.wz.fernhill.digest.plist"]["StartCalendarInterval"] == {"Hour": 8, "Minute": 0}


@pytest.mark.parametrize("platform", ["linux", "macos"])
def test_install_dry_run_touches_nothing_real(project, tmp_path, monkeypatch, platform):
    def boom(*a, **k):
        raise AssertionError("dry run must not run commands")
    monkeypatch.setattr(subprocess, "run", boom)
    said = []
    files = timers.install(project, platform, tmp_path / "home", dry_run=True, say=said.append)
    assert files and all(str(f).startswith(str(tmp_path / "home")) and f.exists() for f in files)
    assert any(s.startswith("would run: ") for s in said)


def test_scan(tmp_path):
    (tmp_path / "a.txt").write_text("hello\nour secret codename is BLUEFIN\nCopyright BLUEFIN Ltd\n")
    (tmp_path / "BLUEFIN-notes.md").write_text("x\n")
    (tmp_path / "b.bin").write_bytes(b"\0BLUEFIN")
    (tmp_path / "deny.txt").write_text("# private words\nbluefin\n")
    hits = scan.scan(tmp_path, scan.load_patterns(tmp_path / "deny.txt"), allow=["^Copyright "])
    assert {(h[0], h[1]) for h in hits} == {("a.txt", 2), ("BLUEFIN-notes.md", 0), ("deny.txt", 2)}
    assert scan.scan(tmp_path, [scan.EMAIL]) == []


def test_simple_setup_starts_safe(tmp_path):
    cfg = setup_mode.apply(setup_mode.SIMPLE_EXAMPLE, tmp_path / "ws", git_init=False, simple=True)
    assert cfg.agent()["permission_mode"] == "default"
    assert cfg.section("budget")["daily_usd"] == 5.0
    assert set(cfg.roles()) == {"mission-ctl", "writer"}


def test_simple_setup_refuses_unsafe_or_uncapped(tmp_path):
    no_cap = {k: v for k, v in setup_mode.SIMPLE_EXAMPLE.items() if k != "budget_usd"}
    with pytest.raises(setup_mode.SetupError, match="daily spend cap"):
        setup_mode.apply(no_cap, tmp_path / "a", git_init=False, simple=True)
    with pytest.raises(setup_mode.SetupError, match="bypassPermissions"):
        setup_mode.apply({**setup_mode.SIMPLE_EXAMPLE, "permission_mode": "bypassPermissions"}, tmp_path / "b",
                         git_init=False, simple=True)
    with pytest.raises(setup_mode.SetupError, match="permission_mode must be"):
        setup_mode.apply({**setup_mode.SIMPLE_EXAMPLE, "permission_mode": "yolo"}, tmp_path / "c", git_init=False)


def test_full_setup_without_a_mode_is_the_safe_default(tmp_path):
    cfg = setup_mode.apply(setup_mode.ANSWERS_EXAMPLE, tmp_path / "ws", git_init=False)
    assert cfg.agent()["permission_mode"] == "default"
    cfg = setup_mode.apply({**setup_mode.ANSWERS_EXAMPLE, "permission_mode": "bypassPermissions"}, tmp_path / "ws2", git_init=False)
    assert cfg.agent()["permission_mode"] == "bypassPermissions"


def test_simple_charter_is_plain_and_has_no_timers(tmp_path):
    text = setup_mode.setup_charter(tmp_path, simple=True)
    assert '"permission_mode": "default"' in text and "{example}" not in text and "{dir}" not in text
    assert "Suggest $5" in text and "Do not install timers" in text
    p = setup_mode.write_setup_charter(tmp_path / "w", simple=True)
    assert p.read_text().startswith("# wz simple setup")


def test_init_simple_cli_print_charter(tmp_path, capsys):
    assert cli.main(["init", "--simple", "--print-charter", "--dir", str(tmp_path / "w")]) == 0
    assert capsys.readouterr().out.strip().endswith(".wz/setup/CHARTER.md")
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps(setup_mode.SIMPLE_EXAMPLE))
    assert cli.main(["init", "--simple", "--answers", str(ans), "--dir", str(tmp_path / "w2"), "--no-git"]) == 0


def test_simple_setup_makes_the_work_folder_and_says_no_timers(tmp_path, capsys):
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps(setup_mode.SIMPLE_EXAMPLE))
    assert cli.main(["init", "--simple", "--answers", str(ans), "--dir", str(tmp_path / "w"), "--no-git"]) == 0
    assert (tmp_path / "w" / "files").is_dir()
    out = capsys.readouterr().out
    assert "no timers are installed" in out and "set-pin" not in out
