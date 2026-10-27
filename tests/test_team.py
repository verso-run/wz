"""`wz role`, `wz rule`, `wz owns` (add and remove): the owner changes the team without hand-editing wz.toml."""
import tomllib

import pytest

from wz import cli, config, guard, jobs, team, tomltext
from conftest import payload

COMMENTED = '''# the owner's own file: comments must survive every edit
[project]
name = "fern"          # the name
workflows = ["software"]

[stores.app]
kind = "git"
path = "../app"
main = "main"
integration = "integration"

[stores.office]
kind = "folder"
path = "../office"

# the lead
[roles.mission-ctl]
pack = "lead"

# builds the product
[roles.app]
pack = "software"
store = "app"
rules = [
    "Run the full suite.",   # the owner asked for this one
    "Never touch the lockfile."
]
[roles.app.owns]
app = [
    "src/**",     # the code
    "tests/**",
]
# the writer
[roles.writer]
pack = "admin"
store = "office"
rules = ["Quote the source."]

[budget]
daily_usd = 5.0
'''


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "office").mkdir()
    d = tmp_path / "ws"
    d.mkdir()
    (d / "wz.toml").write_text(COMMENTED)
    return config.load(d / "wz.toml")


def text(cfg):
    return cfg.path.read_text()


def fresh(cfg):
    return config.load(cfg.path)


# ---- overlap ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("a,b,want", [
    ("src/**", "src/**", True),
    ("src/**", "src/a/**", True),
    ("src/a/**", "src/b/**", False),
    ("src/**", "tests/**", False),
    ("src/**", "src", True),                 # `dir/**` includes the directory itself, as the guard does
    ("**", "anything/at/all.txt", True),
    ("*.md", "docs/*.md", False),            # `*` stays inside one segment
    ("**/*.md", "docs/*.md", True),
    ("src/*.py", "src/a*.py", True),
    ("src/*.py", "src/*.txt", False),
    ("README.md", "README.md", True),
    ("README.md", "README.mdx", False),
    ("a/?", "a/b", True),
    ("a/?", "a/bc", False),
    ("bench/**", "bench/scenarios/**", True),
])
def test_globs_overlap(a, b, want):
    assert team.globs_overlap(a, b) is want
    assert team.globs_overlap(b, a) is want


# ---- the text editor keeps what the owner wrote ----------------------------------------------------------------------------
def array_of(t, key, table):
    tab = tomltext.find(tomltext.scan(t), table)
    return tab.keys[key]


@pytest.mark.parametrize("src", [
    'a = ["x", "y"]\n',
    'a = ["x", "y",]\n',
    'a = [\n  "x",\n  "y"\n]\n',
    'a = [\n  "x",\n  "y",   # note\n]\n',
    'a = [\n  "x", # one\n  "y"  # two\n]\n',
    'a = ["x",\n  "y"]\n',
    'a = []\n',
    'a = [\n]\n',
])
def test_array_add_and_remove_round_trip(src):
    k = array_of("[t]\n" + src, "a", ("t",))
    t = "[t]\n" + src
    t2 = tomltext.array_add(t, k.val_start, k.val_end, '"new"')
    want = tomllib.loads(t)["t"]["a"] + ["new"]
    assert tomllib.loads(t2)["t"]["a"] == want
    k2 = array_of(t2, "a", ("t",))
    t3 = tomltext.array_remove(t2, k2.val_start, k2.val_end, len(want) - 1)
    assert tomllib.loads(t3)["t"]["a"] == want[:-1]


def test_array_remove_each_position():
    t = '[t]\na = [\n  "x",   # keep me out\n  "y",\n  "z"\n]\n'
    for i, left in enumerate([["y", "z"], ["x", "z"], ["x", "y"]]):
        k = array_of(t, "a", ("t",))
        out = tomltext.array_remove(t, k.val_start, k.val_end, i)
        assert tomllib.loads(out)["t"]["a"] == left


def test_scan_survives_awkward_text():
    t = ('[a]\ns = """multi\n[not.a.table]\nline"""\nx = [ "]", \'[\' ]  # [b]\n'
         '"quoted key" = 1\n[b."dotted name".c]\nk = {i = [1, 2], j = "}"}\n')
    tabs = tomltext.scan(t)
    assert [x.path for x in tabs] == [(), ("a",), ("b", "dotted name", "c")]
    assert set(tabs[1].keys) == {"s", "x", "quoted key"}


def test_dotted_keys_are_recorded_so_they_can_be_refused():
    tabs = tomltext.scan("[roles.app]\nowns.app = [\"a\"]\n")
    assert tomltext.has_dotted_keys(tomltext.find(tabs, ("roles", "app")))


# ---- rule ---------------------------------------------------------------------------------------------------------------------
def test_rule_add_keeps_comments_and_rebuilds_the_charter(ws):
    out = team.rule_add(fresh(ws), "app", "Write a test first.")
    t = text(ws)
    assert "# the owner's own file" in t and "# the owner asked for this one" in t and "# the code" in t
    assert fresh(ws).role("app")["rules"][-3:] == ["Run the full suite.", "Never touch the lockfile.", "Write a test first."]
    assert "Write a test first." in ws.charter_path("app").read_text()
    assert "+" in out and "Write a test first." in out and "roles/app/CHARTER.md" in out


def test_rule_add_to_a_role_with_no_rules_key_and_to_a_single_line_array(ws):
    team.rule_add(fresh(ws), "mission-ctl", "Be brief.")
    team.rule_add(fresh(ws), "writer", "Quote the date.")
    cfg = fresh(ws)
    assert "Be brief." in cfg.role("mission-ctl")["rules"]
    assert cfg.section("roles")["writer"]["rules"] == ["Quote the source.", "Quote the date."]
    assert 'rules = ["Quote the source.", "Quote the date."]' in text(ws)


def test_rule_round_trip_restores_the_file_byte_for_byte(ws):
    before = text(ws)
    team.rule_add(fresh(ws), "writer", "Another.")
    team.rule_remove(fresh(ws), "writer", "Another.")
    assert text(ws) == before
    team.rule_add(fresh(ws), "mission-ctl", "Be brief.")
    team.rule_remove(fresh(ws), "mission-ctl", "Be brief.")
    assert text(ws) == before


def test_rule_remove_of_an_owner_line_with_a_comment(ws):
    team.rule_remove(fresh(ws), "app", "Run the full suite.")
    assert fresh(ws).section("roles")["app"]["rules"] == ["Never touch the lockfile."]
    assert "the owner asked for this one" not in text(ws)


def test_rule_that_comes_from_the_pack_cannot_be_removed_and_nothing_changes(ws):
    before = text(ws)
    pack_rule = fresh(ws).role("app")["rules"][0]
    assert pack_rule not in ["Run the full suite.", "Never touch the lockfile."]
    with pytest.raises(team.TeamError, match="comes with"):
        team.rule_remove(fresh(ws), "app", pack_rule)
    with pytest.raises(team.TeamError, match="no added rule"):
        team.rule_remove(fresh(ws), "app", "never written")
    assert text(ws) == before


def test_rule_add_twice_is_a_no_op_and_unknown_role_is_refused(ws):
    assert "already has" in team.rule_add(fresh(ws), "writer", "Quote the source.")
    with pytest.raises(team.TeamError, match="no role called"):
        team.rule_add(fresh(ws), "nobody", "x")


# ---- owns ---------------------------------------------------------------------------------------------------------------------
def test_owns_add_to_an_existing_list(ws):
    team.owns_add(fresh(ws), "app", "app", "docs/**")
    assert fresh(ws).role("app")["owns"]["app"] == ["src/**", "tests/**", "docs/**"]
    assert "# the code" in text(ws)
    assert "docs/**" in (ws.root / "AGENTS.md").read_text()
    assert "docs/**" in ws.charter_path("app").read_text()


def test_owns_add_in_a_new_store_and_for_a_role_with_no_owns_table(ws):
    team.owns_add(fresh(ws), "app", "office", "app-notes/**")
    team.owns_add(fresh(ws), "writer", "office", "drafts/**")
    cfg = fresh(ws)
    assert cfg.role("app")["owns"] == {"app": ["src/**", "tests/**"], "office": ["app-notes/**"]}
    assert cfg.role("writer")["owns"] == {"office": ["drafts/**"]}


def test_owns_add_for_a_pack_default_role_keeps_the_pack_defaults_and_says_so(ws):
    out = team.owns_add(fresh(ws), "mission-ctl", "workspace", "notes/**")
    owns = fresh(ws).role("mission-ctl")["owns"]["workspace"]
    assert "notes/**" in owns and "DECISIONS.md" in owns and "briefs/**" in owns
    assert "defaults of its lead pack" in out


def test_owns_overlap_with_another_role_is_refused_and_changes_nothing(ws):
    team.owns_add(fresh(ws), "writer", "office", "drafts/**")
    before, backups = text(ws), sorted((ws.state / "backups").iterdir())
    for role, store, glob in [("app", "office", "drafts/**"), ("app", "office", "drafts/old/**"), ("app", "office", "**"),
                              ("writer", "app", "src/a/**")]:
        with pytest.raises(team.TeamError, match="overlaps"):
            team.owns_add(fresh(ws), role, store, glob)
    with pytest.raises(team.TeamError, match="owns remove"):
        team.owns_add(fresh(ws), "writer", "app", "tests/unit/**")
    assert text(ws) == before
    assert sorted((ws.state / "backups").iterdir()) == backups


def test_overlap_with_a_pack_default_path_is_refused(ws):
    with pytest.raises(team.TeamError, match="mission-ctl"):
        team.owns_add(fresh(ws), "app", "workspace", "briefs/**")


def test_owns_add_inside_what_the_role_already_owns_is_a_no_op(ws):
    assert "through `src/**`" in team.owns_add(fresh(ws), "app", "app", "src/deep/**")
    assert "already owns" in team.owns_add(fresh(ws), "app", "app", "src/**")


def test_owns_round_trip_and_remove(ws):
    before = text(ws)
    team.owns_add(fresh(ws), "app", "app", "docs/**")
    team.owns_remove(fresh(ws), "app", "app", "docs/**")
    assert text(ws) == before
    team.owns_remove(fresh(ws), "app", "app", "src/**")
    assert fresh(ws).role("app")["owns"]["app"] == ["tests/**"]
    assert "# the code" not in text(ws)
    with pytest.raises(team.TeamError, match="does not own"):
        team.owns_remove(fresh(ws), "app", "app", "src/**")


def test_owns_remove_from_pack_defaults(ws):
    team.owns_remove(fresh(ws), "mission-ctl", "workspace", "PLAN.md")
    owns = fresh(ws).role("mission-ctl")["owns"]["workspace"]
    assert "PLAN.md" not in owns and "DECISIONS.md" in owns


def test_bad_paths_and_stores_are_refused(ws):
    for bad in ["/etc/**", "../x/**", "~/x", "", "a\\b"]:
        with pytest.raises(team.TeamError, match="relative"):
            team.owns_add(fresh(ws), "app", "app", bad)
    with pytest.raises(team.TeamError, match="no store called"):
        team.owns_add(fresh(ws), "app", "nowhere", "x/**")


def test_a_form_the_editor_does_not_handle_is_refused_and_nothing_changes(ws):
    ws.path.write_text(text(ws).replace('[roles.app.owns]\napp = [\n    "src/**",     # the code\n    "tests/**",\n]\n',
                                        'owns = {app = ["src/**"]}\n'))
    cfg = fresh(ws)
    before = text(ws)
    with pytest.raises(team.TeamError, match="by hand|Open wz.toml"):
        team.owns_add(cfg, "app", "app", "docs/**")
    assert text(ws) == before


# ---- role ---------------------------------------------------------------------------------------------------------------------
def test_role_add_writes_a_section_and_the_charter(ws):
    out = team.role_add(fresh(ws), "designer", "admin", store="office", owns=["office=mocks/**"], desc="draws the screens")
    cfg = fresh(ws)
    r = cfg.role("designer")
    assert r["pack"] == "admin" and r["store"] == "office" and r["owns"] == {"office": ["mocks/**"]}
    assert r["desc"] == "draws the screens"
    assert cfg.charter_path("designer").is_file()
    assert "designer" in (ws.root / "AGENTS.md").read_text()
    assert "# the owner's own file" in text(ws) and "daily_usd = 5.0" in text(ws)
    assert text(ws).index("[roles.designer]") < text(ws).index("[budget]")        # sits with the other roles
    assert "[roles.designer]" in out and "roles/designer/CHARTER.md" in out


def test_role_add_without_owns_says_it_owns_nothing(ws):
    out = team.role_add(fresh(ws), "reviewer", "auditor")
    assert fresh(ws).role("reviewer")["owns"] == {}
    assert "owns no paths yet" in out and "wz owns add reviewer" in out


def test_role_add_refusals_change_nothing(ws):
    before = text(ws)
    cases = [(("app", "software"), "already a role"), (("Bad_Name", "software"), "usable role name"),
             (("x", "wizard"), "no pack"), (("second-lead", "lead"), "already a lead"),
             (("x", "software", dict(store="nowhere")), "no store"),
             (("x", "software", dict(owns=["app=src/new/**"])), "overlaps"),
             (("x", "software", dict(owns=["app"])), "STORE=PATH"),
             (("x", "software", dict(owns=["app=a/**", "app=a/b/**"])), "overlap each other"),
             (("x", "software", dict(account="ghost")), "no account")]
    for args, needle in cases:
        kw = args[2] if len(args) > 2 else {}
        with pytest.raises(team.TeamError, match=needle):
            team.role_add(fresh(ws), args[0], args[1], **kw)
    assert text(ws) == before


def test_role_round_trip(ws):
    before = text(ws)
    team.role_add(fresh(ws), "designer", "admin", store="office", owns=["office=mocks/**"])
    out = team.role_remove(fresh(ws), "designer")
    assert text(ws) == before
    assert "designer" not in fresh(ws).roles()
    assert (ws.root / "roles" / "designer").is_dir() and "left in place" in out
    assert "designer" not in (ws.root / "AGENTS.md").read_text()


def test_role_remove_refuses_the_lead_and_a_role_with_open_jobs(ws):
    with pytest.raises(team.TeamError, match="is the lead"):
        team.role_remove(fresh(ws), "mission-ctl")
    jobs.add(ws, "writer", "draft the letter")
    before = text(ws)
    with pytest.raises(team.TeamError, match="still has 1 job"):
        team.role_remove(fresh(ws), "writer")
    assert text(ws) == before
    with pytest.raises(team.TeamError, match="no role called"):
        team.role_remove(fresh(ws), "ghost")


def test_role_remove_takes_its_owns_table_too_and_keeps_the_rest(ws):
    team.role_remove(fresh(ws), "app")
    t = text(ws)
    assert "[roles.app" not in t and "# builds the product" in t and "[roles.writer]" in t and "[budget]" in t
    assert "app" not in fresh(ws).roles()


# ---- safety -------------------------------------------------------------------------------------------------------------------
def test_backup_validation_and_dry_run(ws):
    before = text(ws)
    out = team.rule_add(fresh(ws), "writer", "x.", dry_run=True)
    assert "DRY RUN" in out and text(ws) == before and not (ws.state / "backups").exists()
    team.rule_add(fresh(ws), "writer", "x.")
    (b,) = (ws.state / "backups").iterdir()
    assert b.read_text() == before
    team.rule_add(fresh(ws), "writer", "y.")
    assert len(list((ws.state / "backups").iterdir())) == 2          # a second change in the same second keeps its own backup


def test_a_result_wz_would_not_accept_is_not_written(ws, monkeypatch):
    before = text(ws)
    cfg = fresh(ws)
    monkeypatch.setattr(config.Config, "validate", lambda self: ["[roles.x] something is wrong"])
    with pytest.raises(team.TeamError, match="would not accept"):
        team.rule_add(cfg, "writer", "x.")
    assert text(ws) == before and not (ws.state / "backups").exists()


def test_text_that_parses_to_other_settings_than_intended_is_never_written(ws):
    ed = team.Edit(fresh(ws))
    ed.want["roles"]["writer"]["rules"].append("intended")
    ed.text = ed.text.replace('rules = ["Quote the source."]', 'rules = ["Quote the source.", "something else"]')
    with pytest.raises(team.TeamError, match="different meaning"):
        ed.finish(dry_run=False, what="x")
    assert "something else" not in text(ws)
    ed.text = ed.text + "[broken\n"
    with pytest.raises(team.TeamError, match="did not parse"):
        ed.finish(dry_run=False, what="x")


def test_a_charter_failure_puts_the_old_file_back(ws, monkeypatch):
    before = text(ws)

    def boom(cfg):
        raise OSError("disk full")
    monkeypatch.setattr(team.charters, "write_all", boom)
    with pytest.raises(team.TeamError, match="back as it was"):
        team.rule_add(fresh(ws), "writer", "x.")
    assert text(ws) == before


def test_a_change_made_underneath_us_is_noticed(ws, monkeypatch):
    orig_tables = team.Edit.tables

    def tables(self):                      # another writer changes the file after we read it, before we replace it
        got = orig_tables(self)
        ws.path.write_text(self.raw + "# someone else\n")
        return got
    monkeypatch.setattr(team.Edit, "tables", tables)
    with pytest.raises(team.TeamError, match="changed by something else"):
        team.rule_add(fresh(ws), "writer", "x.")
    assert text(ws).endswith("# someone else\n") and "x." not in text(ws)


def test_a_role_session_cannot_run_these(ws, monkeypatch):
    monkeypatch.setenv("WZ_ROLE", "mission-ctl")
    before = text(ws)
    for fn, args in [(team.rule_add, ("writer", "x.")), (team.owns_add, ("writer", "office", "z/**")),
                     (team.role_add, ("n", "admin")), (team.role_remove, ("writer",))]:
        with pytest.raises(team.TeamError, match="owner's"):
            fn(ws, *args)
    assert text(ws) == before


@pytest.mark.parametrize("cmd", ["wz role add x --pack admin", "wz rule add app 'x'", "wz owns remove app app 'src/**'",
                                 "cd /tmp && wz owns add app app 'x/**'"])
def test_the_guard_refuses_them_for_every_role(project, cmd):
    for role in ("app", "mission-ctl"):
        assert guard.main(payload("Bash", project.root, command=cmd), {"WZ_ROLE": role, "WZ_CONFIG": str(project.path)}) == 2
    assert guard.main(payload("Bash", project.root, command="wz status"), {"WZ_ROLE": "app", "WZ_CONFIG": str(project.path)}) == 0


# ---- the command line --------------------------------------------------------------------------------------------------------------
def test_cli_round_trip(ws, capsys):
    base = ["--config", str(ws.path)]
    before = text(ws)
    assert cli.main(base + ["rule", "add", "writer", "Check the date."]) == 0
    assert "Check the date." in capsys.readouterr().out
    assert cli.main(base + ["owns", "add", "writer", "office", "drafts/**"]) == 0
    assert cli.main(base + ["role", "add", "designer", "--pack", "admin", "--store", "office", "--owns", "office=mocks/**",
                            "--cap", "2", "--web"]) == 0
    cfg = fresh(ws)
    assert cfg.role("designer")["cap"] == 2 and cfg.role("designer")["web"] is True
    assert cli.main(base + ["role", "remove", "designer"]) == 0
    assert cli.main(base + ["owns", "remove", "writer", "office", "drafts/**"]) == 0
    assert cli.main(base + ["rule", "remove", "writer", "Check the date."]) == 0
    capsys.readouterr()
    assert tomllib.loads(text(ws)) == tomllib.loads(before)


def test_cli_refusal_is_plain_and_exits_1(ws, capsys):
    base = ["--config", str(ws.path)]
    assert cli.main(base + ["owns", "add", "writer", "app", "src/**"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("wz: not changed:") and "overlaps" in err and "wz owns remove app app 'src/**'" in err
    assert cli.main(base + ["rule", "add", "writer", "x", "--dry-run"]) == 0


def test_cli_help_is_in_plain_words(capsys):
    for argv, needle in [(["role", "--help"], "Examples"), (["rule", "--help"], "Examples"), (["owns", "--help"], "one owner")]:
        with pytest.raises(SystemExit):
            cli.main(argv)
        out = capsys.readouterr().out
        assert needle in out and "Only you, the owner" in out
