"""The hook commands in .wz/role-settings.json, run the way Claude Code runs them: a shell command, JSON on stdin."""
import json
import os
import subprocess
from pathlib import Path

from conftest import payload
from wz import packs


def hook(cfg, event, role, data):
    settings = json.loads(cfg.role_settings.read_text())
    cmd = settings["hooks"][event][0]["hooks"][0]["command"]
    env = {**os.environ, "WZ_ROLE": role, "WZ_CONFIG": str(cfg.path)}
    return subprocess.run(cmd, shell=True, input=data, capture_output=True, text=True, env=env)


def test_guard_hook_command(project):
    r = hook(project, "PreToolUse", "app", payload("Write", project.root, file_path=str(project.root / "DECISIONS.md")))
    assert r.returncode == 2 and "[wz guard]" in r.stderr
    ok = hook(project, "PreToolUse", "app", payload("Write", project.root,
                                                     file_path=str(project.store_root("app") / "src" / "x.py")))
    assert ok.returncode == 0, ok.stderr


def test_flag_hook_command(project):
    brief = project.root / "briefs" / "01-x.md"
    brief.write_text("# x\n")
    r = hook(project, "PostToolUse", "app", json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(brief)},
                                                         "cwd": str(project.root)}))
    assert r.returncode == 0 and (project.state / "flags" / "app.01-x.md.done").exists()


def test_readme_carries_every_rule():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    for rule, failure in packs.STANDING_RULES:
        assert rule in readme, rule
        assert failure in readme, failure
