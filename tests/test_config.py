import tomllib

import pytest

from wz import config, packs, setup_mode


def test_dumps_round_trips():
    data = {"project": {"name": "x", "workflows": ["software"], "n": 3, "on": True},
            "roles": {"mission-ctl": {"pack": "lead", "owns": {"workspace": ["a/**"]}}, "app": {"pack": "software"}},
            "stores": {"my store": {"kind": "folder", "path": "../q \"r\""}}}
    assert tomllib.loads(config.dumps(data)) == data


def test_project_loads_with_pack_defaults(project):
    cfg = project
    assert cfg.project == "fernhill"
    assert cfg.lead() == "mission-ctl"
    lead = cfg.role("mission-ctl")
    assert lead["owns"] == packs.PACKS["lead"]["owns"]
    app = cfg.role("app")
    assert app["model"] == "sonnet" and app["store"] == "app" and app["cap"] == 1
    assert any("checks" in r for r in app["rules"])
    assert cfg.store_root("app").name == "app"
    assert cfg.store_root("workspace") == cfg.root


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["roles"]["app"].update(pack="lead"), "exactly one role"),
    (lambda d: d["roles"]["app"].update(store="nowhere"), "not a [stores.*]"),
    (lambda d: d["roles"]["app"].update(pack="wizard"), "unknown pack"),
    (lambda d: d["roles"]["app"].update(account="other"), "not an [accounts.*]"),
    (lambda d: d["roles"].update({"Bad_Name": {"pack": "software"}}), "role name"),
])
def test_validation(project, mutate, needle):
    data = tomllib.loads(project.path.read_text())
    mutate(data)
    errs = config.Config(project.path, data).validate()
    assert any(needle in e for e in errs), errs


def test_find_walks_up(project, tmp_path, monkeypatch):
    deep = project.root / "briefs" / "x"
    deep.mkdir(parents=True)
    assert config.find(deep) == project.path
    monkeypatch.setenv("WZ_CONFIG", str(project.path))
    assert config.find(tmp_path) == project.path


def test_load_without_config_says_how(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(config.ConfigError, match="wz init"):
        config.load()


def test_default_roles_from_workflows():
    data = setup_mode.answers_to_config({"project": "p", "workflows": ["software", "admin", "firmware", "hardware"],
                                         "stores": {"code": {"kind": "git", "path": "../c"},
                                                    "docs": {"kind": "folder", "path": "../d"}}})
    roles = data["roles"]
    assert roles["mission-ctl"]["pack"] == "lead"
    assert roles["app"]["store"] == "code" and roles["writer"]["store"] == "docs"
    assert roles["firmware"]["store"] == "code"
    assert set(roles) == {"mission-ctl", "app", "tester", "writer", "firmware", "bench"}
