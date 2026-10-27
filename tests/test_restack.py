"""What the three open PRs promise together: the mode notice and the charter refresh reach every way a session starts,
the lead is told that a queue without timers runs nothing, and a command that falls back to the registered workspace
says which one."""
import tomllib

from test_sessions import REAL_TMUX, Rig, rig  # noqa: F401  (the tmux rig and its fixture)
from wz import charters, cli, config, registry, setup_mode


def set_mode(cfg, mode):
    data = tomllib.loads(cfg.path.read_text())
    data.setdefault("agent", {})["permission_mode"] = mode
    cfg.path.write_text(config.dumps(data))
    return config.load(cfg.path)


# ---- E1: the steady-state lead charter -----------------------------------------------------------------------------
def test_every_lead_charter_says_a_queue_without_timers_runs_nothing(project):
    charters.write_all(project)
    lead = project.charter_path(project.lead()).read_text()
    assert "`wz job add` starts nothing" in lead and "wz cli <role> --detach" in lead and "wz say" in lead
    assert "Never tell the person a queued job will run" in lead
    assert "First small task" not in lead                         # only a `--simple` workspace has the check


def test_a_simple_workspace_lead_also_gets_the_first_small_task_check(tmp_path):
    cfg = setup_mode.apply(setup_mode.SIMPLE_EXAMPLE, tmp_path / "ws", git_init=False, simple=True)
    lead = cfg.charter_path(cfg.lead()).read_text()
    assert "`wz job add` starts nothing" in lead and "wz cli <role> --detach" in lead
    assert "First small task" in lead and "who you gave it to" in lead
    others = [r for r in cfg.roles() if not cfg.is_lead(r)]
    assert all("First small task" not in cfg.charter_path(r).read_text() for r in others)


def test_a_lead_charter_from_before_this_text_is_rebuilt_at_the_next_start(project):
    charters.write_all(project)
    p = project.charter_path(project.lead())
    p.write_text(p.read_text().replace("**No timers, no queue.**", "**Old.**"))
    assert charters.stale(project, project.lead())
    charters.ensure(project, project.lead())
    assert "`wz job add` starts nothing" in p.read_text()


# ---- the notice and the refresh in every start ---------------------------------------------------------------------
def test_start_all_and_roll_announce_a_non_default_mode_and_refresh_the_charter(rig, capsys):  # noqa: F811
    cfg = rig.workspace()
    assert rig.wz(cfg, "cli", "app", "--detach") == 0
    assert "permission mode" not in capsys.readouterr().err
    cfg = set_mode(cfg, "auto")                                   # a hand edit of wz.toml
    assert "Permission mode: `default`" in cfg.charter_path("app").read_text()
    rig.tmux("kill-server")                                       # the reboot
    capsys.readouterr()
    assert rig.wz(cfg, "start-all") == 0
    err = capsys.readouterr().err
    assert "permission mode is 'auto'" in err and "Set it back" in err
    assert "Permission mode: `auto`" in cfg.charter_path("app").read_text()
    cfg = set_mode(cfg, "dontAsk")
    assert rig.wz(cfg, "roll", "app") == 0
    assert "permission mode is 'dontAsk'" in capsys.readouterr().err
    assert "Permission mode: `dontAsk`" in cfg.charter_path("app").read_text()


def test_wz_cli_announces_once_for_a_new_window_and_again_for_a_running_one(rig, capsys):  # noqa: F811
    cfg = set_mode(rig.workspace(), "auto")
    assert rig.wz(cfg, "cli", "app", "--detach") == 0
    assert capsys.readouterr().err.count("permission mode is 'auto'") == 1
    assert rig.wz(cfg, "cli", "app", "--detach") == 0             # already running: still said, once
    assert capsys.readouterr().err.count("permission mode is 'auto'") == 1


def test_a_default_mode_start_is_silent(rig, capsys):  # noqa: F811
    cfg = rig.workspace()
    assert rig.wz(cfg, "cli", "app", "--detach") == 0
    assert rig.wz(cfg, "start-all") == 0
    assert "permission mode" not in capsys.readouterr().err


# ---- E3: which workspace ---------------------------------------------------------------------------------------------
def test_a_command_that_falls_back_to_the_registered_workspace_names_it(project, tmp_path, monkeypatch, capsys):
    registry.register(project.path, project.project, make_default=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert cli.main(["job", "list"]) == 0
    err = capsys.readouterr().err
    assert f"workspace {registry.name_of(project.path)} ({project.root}) from the registered default" in err
    monkeypatch.chdir(project.root)                               # inside the workspace: nothing to say
    assert cli.main(["job", "list"]) == 0
    assert "registered default" not in capsys.readouterr().err
    assert cli.main(["--config", str(project.path), "job", "list"]) == 0
    assert "registered default" not in capsys.readouterr().err
