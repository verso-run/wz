"""The charters say the lead delegates (wz say / wz job add), and a role may message the lead. Text tests: the generated
files are what a real session reads, so the words are checked where they are written."""
import json
import re

from wz import charters, cli, config, setup_mode

LEAD_PHRASES = ("You delegate; you do not do a role's work", "wz say <role>", "wz job add <role>", "never a job")


def test_the_lead_charter_delegates_and_names_both_ways(project):
    charters.write_all(project)
    lead = project.charter_path(project.lead()).read_text()
    for phrase in LEAD_PHRASES:
        assert phrase in lead, phrase
    assert "do not open its files and do it" in lead and "You read their reports and rule on them" in lead


def test_other_roles_may_message_the_lead_but_are_not_told_to_delegate(project):
    charters.write_all(project)
    for role in project.roles():
        if project.is_lead(role):
            continue
        text = project.charter_path(role).read_text()
        assert f'wz say {project.lead()} "' in text
        assert "You delegate" not in text
        assert "Never message another role to acknowledge" in text


def test_the_full_setup_charter_delegates(tmp_path):
    text = setup_mode.setup_charter(tmp_path)
    assert "You do not do a role's work yourself" in text
    assert "wz say <role>" in text and "wz job add <role>" in text
    assert "hand it to a role and say which one" in text


def test_the_simple_setup_charter_delegates_in_plain_words_and_has_the_first_run_check(tmp_path):
    text = setup_mode.setup_charter(tmp_path, simple=True)
    assert "{wz}" not in text and "{dir}" not in text
    section = text[text.index("## After the setup"):]
    assert "You do not write the letters, forms or plans yourself" in section
    assert re.search(r"say <helper> \"<what to do>\"", section) and "cli <helper> --detach" in section
    assert "First small task" in section and "hand it\nto a helper" in section and "who you gave it to" in section
    for jargon in ("store", "roles", "lease", "pack", "worktree", "permission mode", "ring", "decide", "lead"):
        assert not re.search(rf"\b{jargon}\b", section, re.I), jargon
    assert "from any folder" in text and "cd {dir}" not in text and "type `cd " not in text


def test_simple_setup_registers_the_workspace_so_it_is_found_from_anywhere(tmp_path, monkeypatch):
    from wz import registry
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps(setup_mode.SIMPLE_EXAMPLE))
    assert cli.main(["init", "--simple", "--answers", str(ans), "--dir", str(tmp_path / "w"), "--no-git"]) == 0
    assert registry.load()["default"] == "home-paperwork"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert config.locate(elsewhere) == (tmp_path / "w" / "wz.toml", "registered")
    assert config.find(elsewhere, registered=False) is None
