"""The three safety fixes from the qual-guides field report: the permission-mode default, validating it and saying
what it means, and the guard's per-role web allow."""
import inspect
import json
import tomllib
from pathlib import Path

import pytest

from conftest import payload
from wz import charters, cli, config, guard, jobs, worker


def with_toml(cfg, mutate):
    data = tomllib.loads(cfg.path.read_text())
    mutate(data)
    cfg.path.write_text(config.dumps(data))
    return config.load(cfg.path)


def set_mode(cfg, mode):
    return with_toml(cfg, lambda d: d.setdefault("agent", {}).update(permission_mode=mode))


def set_job_mode(cfg, mode):
    return with_toml(cfg, lambda d: d.setdefault("agent", {}).update(job_permission_mode=mode))


def drop_mode(cfg):
    return with_toml(cfg, lambda d: d.setdefault("agent", {}).pop("permission_mode", None))


# ---- #2: a missing mode is the safe one ------------------------------------------------------------------------------
def test_missing_mode_is_default_everywhere(project, capsys):
    cfg = drop_mode(project)
    assert "permission_mode" not in cfg.section("agent")
    assert cfg.agent()["permission_mode"] == "default" and cfg.mode_notice() is None
    assert cli.main(["--config", str(cfg.path), "cli", "app", "--print"]) == 0
    assert "--permission-mode default" in capsys.readouterr().out


def test_no_agent_section_at_all_is_default(project):
    cfg = with_toml(project, lambda d: d.pop("agent", None))
    assert cfg.agent()["permission_mode"] == "default"


def test_bypass_only_when_written(project):
    cfg = set_mode(project, "bypassPermissions")
    assert "does NOT ask" in cfg.mode_notice()
    cmd = worker.build_command(cfg, "app", "do it")
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"  # jobs follow job_permission_mode, not this
    cfg = set_job_mode(cfg, "bypassPermissions")
    cmd = worker.build_command(cfg, "app", "do it")
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert "does NOT ask" in cfg.mode_notice(job=True)


# ---- #1: validated on load, announced when it is not an ask-first mode -------------------------------------------------
@pytest.mark.parametrize("bad", ["yolo", "Default", "bypass", "", 3, ["default"], True])
def test_unknown_mode_is_refused_on_load(project, bad):
    with pytest.raises(config.ConfigError, match="permission_mode .* is not a mode wz supports"):
        set_mode(project, bad)


def test_the_error_names_the_modes(project):
    with pytest.raises(config.ConfigError) as e:
        set_mode(project, "yolo")
    for m in config.SAFE_MODES + config.OTHER_MODES:
        assert m in str(e.value)


@pytest.mark.parametrize("mode", config.SAFE_MODES)
def test_safe_modes_are_silent(project, mode, capsys):
    cfg = set_mode(project, mode)
    assert cfg.mode_notice() is None
    assert cli.main(["--config", str(cfg.path), "cli", "app", "--print"]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("mode", config.OTHER_MODES)
def test_other_modes_are_announced_at_wz_cli(project, mode, capsys):
    cfg = set_mode(project, mode)
    assert mode in cfg.mode_notice()
    assert cli.main(["--config", str(cfg.path), "cli", "app", "--print"]) == 0
    err = capsys.readouterr().err
    assert f"permission mode is '{mode}'" in err and "Set it back" in err


def test_auto_is_announced_at_job_start_and_recorded(project, capsys):
    cfg = set_mode(project, "auto")
    j = jobs.add(cfg, "app", "add a greeting")
    worker.serve(cfg, role="app", wait=True, say=lambda *_: None)
    err = capsys.readouterr().err
    assert "permission mode is 'auto'" in err and j["id"] in err and "role app" in err
    assert jobs.get(cfg, j["id"])["permission_mode"] == "auto"


def test_default_job_is_silent_and_records_the_mode(project, capsys):
    cfg = set_job_mode(project, "default")
    j = jobs.add(cfg, "app", "add a greeting")
    worker.serve(cfg, role="app", wait=True, say=lambda *_: None)
    assert "permission mode" not in capsys.readouterr().err
    assert jobs.get(cfg, j["id"])["permission_mode"] == "default"


# ---- background jobs run in `auto` unless [agent] job_permission_mode says otherwise; `wz cli` keeps permission_mode ------
def mode_of(cmd):
    return cmd[cmd.index("--permission-mode") + 1]


def test_job_mode_defaults_to_auto_and_chat_stays_default(project, capsys):
    cfg = with_toml(drop_mode(project), lambda d: d["agent"].pop("job_permission_mode", None))
    assert "job_permission_mode" not in cfg.section("agent")
    assert cfg.job_permission_mode() == "auto" and cfg.permission_mode() == "default"
    assert mode_of(worker.build_command(cfg, "app", "do it")) == "auto"
    assert mode_of(worker.build_command(cfg, "app", "fix it", resume="abc")) == "auto"  # the fix turn is a job turn too
    assert cli.main(["--config", str(cfg.path), "cli", "app", "--print"]) == 0
    assert "--permission-mode default" in capsys.readouterr().out
    cfg = with_toml(project, lambda d: d.pop("agent", None))
    assert cfg.job_permission_mode() == "auto" and cfg.permission_mode() == "default"


def test_job_mode_set_in_wz_toml_reaches_the_job_and_not_the_window(project, capsys):
    cfg = set_job_mode(project, "acceptEdits")
    assert mode_of(worker.build_command(cfg, "app", "do it")) == "acceptEdits"
    assert cli.main(["--config", str(cfg.path), "cli", "app", "--print"]) == 0
    out = capsys.readouterr()
    assert "--permission-mode default" in out.out and out.err == ""
    cfg = set_mode(cfg, "plan")
    assert mode_of(worker.build_command(cfg, "app", "do it")) == "acceptEdits"


@pytest.mark.parametrize("bad", ["yolo", "Auto", "", 3, ["auto"], True])
def test_unknown_job_mode_is_refused_on_load(project, bad):
    with pytest.raises(config.ConfigError, match="job_permission_mode .* is not a mode wz supports"):
        set_job_mode(project, bad)


def test_the_default_job_mode_is_announced_at_job_start_and_recorded(project, capsys):
    j = jobs.add(project, "app", "add a greeting")
    worker.serve(project, role="app", wait=True, say=lambda *_: None)
    err = capsys.readouterr().err
    assert "job permission mode is 'auto'" in err and "job_permission_mode" in err and j["id"] in err and "role app" in err
    assert "do not count on being asked" in err and "cannot write" in err
    assert jobs.get(project, j["id"])["permission_mode"] == "auto"


def test_a_window_is_not_announced_when_only_the_job_mode_is_unsafe(project, capsys):
    assert project.mode_notice() is None and "job permission mode is 'auto'" in project.mode_notice(job=True)
    assert cli.main(["--config", str(project.path), "cli", "app", "--print"]) == 0
    assert capsys.readouterr().err == ""
    cfg = set_mode(project, "auto")
    assert "job" not in cfg.mode_notice()


def test_status_shows_both_modes(project, capsys):
    assert cli.main(["--config", str(project.path), "status"]) == 0
    out = capsys.readouterr().out
    assert "permission mode: default\n" in out and "job permission mode: auto  (" in out
    cfg = set_job_mode(project, "default")
    assert cli.main(["--config", str(cfg.path), "status"]) == 0
    assert "job permission mode: default\n" in capsys.readouterr().out


def test_job_charter_text_follows_the_job_mode(project):
    def charter(mode):
        cfg = set_job_mode(project, mode)
        charters.write_all(cfg)
        return cfg.charter_path("app").read_text()
    c = charter("auto")
    assert "Background job mode: `auto`" in c and "a job can usually write files" in c and "cannot do anything that needs a yes" not in c
    assert "Permission mode: `default`" in c and "asks the owner before it acts" in c
    c = charter("default")
    assert "Background job mode: `default`" in c and "cannot do anything that needs a yes" in c
    assert "Background job mode: `acceptEdits`" in charter("acceptEdits")
    assert "does NOT ask" in charter("bypassPermissions")
    for m in config.SAFE_MODES + config.OTHER_MODES:
        assert charters.JOB_MODE_TEXT.get(m) or charters.MODE_TEXT[m]


def test_a_hand_edit_of_the_job_mode_makes_the_charter_stale(project):
    charters.write_all(project)
    assert not charters.stale(project, "app")
    cfg = set_job_mode(project, "default")
    assert charters.stale(cfg, "app")


def test_status_shows_the_mode(project, capsys):
    assert cli.main(["--config", str(project.path), "status"]) == 0
    out = capsys.readouterr().out
    assert "permission mode: default" in out and "NOT asked" not in out
    cfg = set_mode(project, "auto")
    assert cli.main(["--config", str(cfg.path), "status"]) == 0
    assert "permission mode: auto" in capsys.readouterr().out


def test_every_accepted_mode_has_charter_and_notice_text():
    for m in config.SAFE_MODES + config.OTHER_MODES:
        assert charters.MODE_TEXT[m]
    for m in config.OTHER_MODES:
        assert config.MODE_FACTS[m]


def test_charter_claims_follow_the_mode(project):
    def charter(mode):
        cfg = set_mode(project, mode)
        charters.write_all(cfg)
        return cfg.charter_path("app").read_text()
    c = charter("default")
    assert "Permission mode: `default`" in c and "asks the owner before it acts" in c
    for mode in ("auto", "dontAsk", "manual", "bypassPermissions"):
        c = charter(mode)
        assert f"Permission mode: `{mode}`" in c
        assert "asks the owner before it acts" not in c
    assert "does NOT ask" in charter("bypassPermissions")
    assert "Do not assume you will be stopped" in charter("auto")
    c = charter("acceptEdits")
    assert "accepts file edits without asking" in c and "asks the owner before it acts" not in c


# ---- a hand edit of wz.toml never leaves a charter that says the old thing ---------------------------------------------
def charter_text(cfg):
    return cfg.charter_path("app").read_text()


def test_wz_cli_rebuilds_a_charter_after_a_hand_edit_of_the_mode(project, capsys):
    assert "asks the owner before it acts" in charter_text(project)
    cfg = set_mode(project, "auto")
    assert charters.stale(cfg, "app")
    assert cli.main(["--config", str(cfg.path), "cli", "app", "--print"]) == 0
    c = charter_text(cfg)
    assert "Permission mode: `auto`" in c and "asks the owner before it acts" not in c
    assert not charters.stale(cfg, "app")


def test_wz_cli_rebuilds_a_charter_after_a_hand_edit_of_web(project):
    assert "Web access: off" in charter_text(project)
    cfg = with_toml(project, lambda d: d["roles"]["app"].update(web=True))
    assert charters.stale(cfg, "app")
    cli.main(["--config", str(cfg.path), "cli", "app", "--print"])
    assert "Web access: allowed" in charter_text(cfg) and "Web access: off" not in charter_text(cfg)


def test_job_start_rebuilds_a_stale_charter(project):
    cfg = set_mode(project, "bypassPermissions")
    assert "asks the owner before it acts" in charter_text(cfg)
    jobs.add(cfg, "app", "add a greeting")
    worker.serve(cfg, role="app", wait=True, say=lambda *_: None)
    assert "does NOT ask" in charter_text(cfg)


def test_a_current_charter_is_left_alone_and_other_roles_are_not_rewritten(project):
    assert not charters.stale(project, "app")
    p = project.charter_path("app")
    p.write_text(p.read_text() + "\nA line the owner added.\n")
    charters.ensure(project, "app")
    assert "A line the owner added." in p.read_text()
    cfg = set_mode(project, "auto")
    other = [r for r in cfg.roles() if r != "app"][0]
    o = cfg.charter_path(other)
    o.write_text(o.read_text() + "\nOther role note.\n")
    charters.ensure(cfg, "app")
    assert "Other role note." in o.read_text() and "Permission mode: `auto`" in charter_text(cfg)


# ---- wz status says what the mode means, for every mode ------------------------------------------------------------------
@pytest.mark.parametrize("mode", config.SAFE_MODES + config.OTHER_MODES)
def test_status_prints_the_facts_for_the_mode(project, mode, capsys):
    cfg = set_mode(project, mode)
    assert cli.main(["--config", str(cfg.path), "status"]) == 0
    line = [x for x in capsys.readouterr().out.splitlines() if x.startswith("permission mode:")][0]
    assert line.startswith(f"permission mode: {mode}")
    if mode in config.OTHER_MODES:
        assert config.MODE_FACTS[mode] in line
    else:
        assert line == f"permission mode: {mode}"
    if mode != "bypassPermissions":
        assert "NOT asked to stop" not in line


# ---- the README says where the notice lands --------------------------------------------------------------------------
def test_readme_names_the_supervisor_log_where_a_job_notice_lands():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert ".wz/logs/<job>.supervisor.log" in readme
    assert "supervisor.log" in inspect.getsource(worker._spawn)


# ---- #3: web access is a per-role allow, off unless set ------------------------------------------------------------------
def run(cfg, role, tool, **inp):
    return guard.main(payload(tool, cfg.root, **inp), {"WZ_ROLE": role, "WZ_CONFIG": str(cfg.path)})


WEB = [("WebFetch", {"url": "https://example.com"}), ("WebSearch", {"query": "interview questions"}),
       ("mcp__docs__search", {"q": "x"})]


@pytest.mark.parametrize("tool,inp", WEB)
def test_web_is_off_unless_set(project, tool, inp, capsys):
    assert project.role("app")["web"] is False
    assert run(project, "app", tool, **inp) == 2
    assert "web access is off for role app" in capsys.readouterr().err
    assert tool in (project.state / "guard.log").read_text()


@pytest.mark.parametrize("tool,inp", WEB)
def test_web_true_allows_the_web_tools_for_that_role_only(project, tool, inp):
    cfg = with_toml(project, lambda d: d["roles"]["app"].update(web=True))
    assert run(cfg, "app", tool, **inp) == 0
    assert run(cfg, "tester", tool, **inp) == 2
    assert run(cfg, "mission-ctl", tool, **inp) == 2


def test_web_list_allows_only_those_tools(project):
    cfg = with_toml(project, lambda d: d["roles"]["app"].update(web=["WebFetch", "mcp__docs__*"]))
    assert run(cfg, "app", "WebFetch", url="https://example.com") == 0
    assert run(cfg, "app", "WebSearch", query="x") == 2
    assert run(cfg, "app", "mcp__docs__search", q="x") == 0
    assert run(cfg, "app", "mcp__other__search", q="x") == 2


def test_web_false_and_empty_list_are_off(project):
    for off in (False, []):
        cfg = with_toml(project, lambda d: d["roles"]["app"].update(web=off))
        assert run(cfg, "app", "WebFetch", url="https://example.com") == 2


@pytest.mark.parametrize("bad", ["yes", 1, [1], {"a": 1}])
def test_bad_web_value_is_refused_on_load(project, bad):
    with pytest.raises(config.ConfigError, match=r"\[roles.app\] web must be"):
        with_toml(project, lambda d: d["roles"]["app"].update(web=bad))


def test_local_tools_are_not_web_tools(project, tmp_path):
    for tool, inp in (("TodoWrite", {"todos": []}), ("Task", {"prompt": "x"}), ("Skill", {"skill": "x"}),
                      ("Read", {"file_path": str(project.root / "AGENTS.md")})):
        assert run(project, "app", tool, **inp) == 0, tool


def test_web_tools_fail_closed_when_the_config_cannot_be_read(project, tmp_path):
    cfg = with_toml(project, lambda d: d["roles"]["app"].update(web=True))
    env = {"WZ_ROLE": "app", "WZ_CONFIG": str(tmp_path / "gone" / "wz.toml")}
    assert guard.main(payload("WebFetch", tmp_path, url="https://example.com"), env) == 2
    assert guard.main(payload("mcp__docs__search", tmp_path, q="x"), env) == 2
    assert guard.main(payload("Read", tmp_path, file_path=str(tmp_path / "a.txt")), env) == 0
    assert run(cfg, "app", "WebFetch", url="https://example.com") == 0


def test_charter_states_the_web_setting(project):
    def charter(web):
        cfg = with_toml(project, lambda d: d["roles"]["app"].update(web=web))
        charters.write_all(cfg)
        return cfg.charter_path("app").read_text()
    assert "Web access: off for this role" in charter(False)
    assert "Web access: allowed for this role" in charter(True)
    c = charter(["WebFetch"])
    assert "only these tools" in c and "`WebFetch`" in c and "off for this role" not in c


def test_example_librarian_may_search_and_fetch_and_no_one_else_may(tmp_path):
    from wz import setup_mode
    from pathlib import Path
    ex = json.loads((Path(__file__).resolve().parent.parent / "examples" / "qual-guides" / "answers.json").read_text())
    cfg = setup_mode.apply(ex, tmp_path / "ws", git_init=False, simple=True)
    assert cfg.role("librarian")["web"] == ["WebSearch", "WebFetch"]
    assert [r for r, v in cfg.roles().items() if v["web"]] == ["librarian"]
    assert run(cfg, "librarian", "WebFetch", url="https://example.com") == 0
    assert run(cfg, "librarian", "WebSearch", query="x") == 0
    assert run(cfg, "designer", "WebSearch", query="x") == 2
    assert run(cfg, "reviewer", "WebFetch", url="https://example.com") == 2
