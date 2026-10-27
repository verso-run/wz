"""The pages a new person reads must not say that closing the Terminal stops everything: with tmux it does not."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["START-HERE.md", "INSTALL-PROMPT.md", "README.md", "examples/qual-guides/README.md"]


def test_no_page_says_closing_the_terminal_leaves_nothing_running():
    for name in PAGES:
        text = (ROOT / name).read_text()
        assert "Nothing is left running" not in text, name
        assert "close the window; nothing runs by itself" not in text, name


def test_each_stop_instruction_names_exit_and_park_and_the_open_terminal():
    for name in PAGES:
        lines = [l for l in (ROOT / name).read_text().splitlines() if "how to stop everything" in l]
        assert lines, name
        for l in lines:
            assert "/exit" in l and "wz park" in l and "Terminal" in l, (name, l)
