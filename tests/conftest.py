import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wz import config, setup_mode  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_claude.py"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    for k in ("WZ_ROLE", "WZ_JOB", "WZ_CONFIG", "WZ_HOME", "WZ_SCRATCH", "WZ_WORKTREE", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))     # the workspace list: never the real one
    monkeypatch.setenv("GIT_AUTHOR_NAME", "wz test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "wz-test")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "wz test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "wz-test")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "claude-calls.jsonl"))
    (tmp_path / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "src").mkdir()
    (path / "src" / "shared.txt").write_text("base\n")
    (path / "README.md").write_text("app\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial")
    return path


def answers(tmp_path: Path, checks=None) -> dict:
    return {
        "project": "fernhill",
        "description": "a made-up greenhouse controller",
        "workflows": ["software", "admin", "hardware"],
        "agent_command": f"{sys.executable} {FAKE}",
        "stores": {
            "app": {"kind": "git", "path": "../app", "main": "main", "integration": "integration",
                    "checks": checks if checks is not None else ["test -f README.md"]},
            "office": {"kind": "folder", "path": "../office"},
        },
        "roles": {
            "mission-ctl": {"pack": "lead", "store": "workspace", "model": "opus"},
            "app": {"pack": "software", "store": "app", "owns": {"app": ["src/**", "tests/**"]}, "model": "sonnet"},
            "tester": {"pack": "tester", "store": "app", "owns": {"app": ["e2e/**"]}},
            "writer": {"pack": "admin", "store": "office", "owns": {"office": ["drafts/**"]}},
            "bench": {"pack": "hardware", "store": "workspace", "owns": {"workspace": ["bench/**"]}},
        },
        "resources": {"bench-psu": {"kind": "instrument", "note": "power supply"}},
        "accounts": {"main": {"config_dir": "", "daily_usd": 10}},
        "budget_usd": 20,
        "guard": {"temp": False, "allow": [str(tmp_path / "scratchspace")]},
        "digest_time": "08:00",
    }


@pytest.fixture
def project(tmp_path):
    make_repo(tmp_path / "app")
    (tmp_path / "office" / "drafts").mkdir(parents=True)
    cfg = setup_mode.apply(answers(tmp_path), tmp_path / "ws", git_init=False)
    return cfg


@pytest.fixture
def reload():
    def _r(cfg):
        return config.load(cfg.path)
    return _r


def payload(tool, cwd, **inp):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "cwd": str(cwd)})
