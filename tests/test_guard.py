import os

import pytest

from wz import guard, unlock
from conftest import payload


def run(cfg, role, tool, cwd=None, job=None, **inp):
    env = {"WZ_ROLE": role, "WZ_CONFIG": str(cfg.path)}
    if job:
        env["WZ_JOB"] = job
    return guard.main(payload(tool, cwd or cfg.root, **inp), env)


def write(cfg, role, path, **kw):
    return run(cfg, role, "Write", file_path=str(path), content="x", **kw)


def bash(cfg, role, command, cwd=None, job=None):
    return run(cfg, role, "Bash", cwd=cwd, job=job, command=command)


def test_no_role_is_a_noop(project):
    assert guard.main("not json", {}) == 0


def test_owned_and_unowned_writes(project):
    app = project.store_root("app")
    assert write(project, "app", app / "src" / "a.py") == 0
    assert write(project, "app", app / "e2e" / "t.py") == 2
    assert write(project, "tester", app / "e2e" / "t.py") == 0
    assert write(project, "app", app / "README.md") == 2


def test_workspace_rules(project):
    ws = project.root
    assert write(project, "app", ws / "roles" / "app" / "STATE.md") == 0
    assert write(project, "app", ws / "roles" / "tester" / "STATE.md") == 2
    assert write(project, "app", ws / "briefs" / "01-x.md") == 0
    assert write(project, "app", ws / "ledgers" / "DEFECTS.md") == 0
    assert write(project, "app", ws / "DECISIONS.md") == 2
    assert write(project, "mission-ctl", ws / "DECISIONS.md") == 0
    assert write(project, "mission-ctl", project.store_root("app") / "src" / "a.py") == 2


def test_state_scratch_temp_and_outside(project, tmp_path):
    assert write(project, "app", project.state / "jobs" / "job-0001.json") == 2
    assert write(project, "app", project.scratch("app") / "notes.txt") == 0
    assert write(project, "app", tmp_path / "scratchspace" / "x.txt") == 0
    assert write(project, "app", tmp_path / "elsewhere" / "x.txt") == 2
    assert write(project, "app", "/etc/wz-guard-test") == 2


def test_worktrees_belong_to_their_role(project):
    wt = project.worktree_root("app")
    assert write(project, "app", wt / "app.job-0001" / "src" / "x.py") == 0
    assert write(project, "app", wt / "app.job-0001" / "README.md") == 2
    assert write(project, "tester", wt / "app.job-0001" / "e2e" / "x.py") == 2


@pytest.mark.parametrize("cmd", ["pkill -f server", "killall python", "kill $(pgrep -f server)",
                                 "kill -9 `pgrep node`", "pgrep -f x | xargs kill", "ps aux | grep x | xargs -r kill"])
def test_pattern_kills_refused(project, cmd):
    assert bash(project, "app", cmd) == 2


def test_pid_kill_allowed(project):
    assert bash(project, "app", "kill 12345") == 0


@pytest.mark.parametrize("cmd", ["cat ~/.ssh/id_rsa", "cat .env", "printenv", "env", "echo $GITHUB_TOKEN",
                                 "head -1 deploy/server.pem", "export -p"])
def test_secret_reads_refused(project, cmd):
    assert bash(project, "app", cmd) == 2


def test_secret_read_tool_refused_and_env_with_command_allowed(project):
    assert run(project, "app", "Read", file_path=str(project.root / ".env")) == 2
    assert run(project, "app", "Read", file_path=str(project.root / "PLAN.md")) == 0
    assert bash(project, "app", "env FOO=1 python3 -c 'print(1)'") == 0


def test_commit_needs_unlock(project):
    app = project.store_root("app")
    assert bash(project, "app", 'git commit -m "x"', cwd=app) == 2
    unlock.grant(project, "app", job="job-0001")
    assert bash(project, "app", 'git commit -m "x"', cwd=app, job="job-0001") == 0
    assert bash(project, "app", 'git commit -m "x"', cwd=app, job="job-0002") == 2
    unlock.revoke(project, "app")
    unlock.grant(project, "app", job=None)
    assert bash(project, "app", 'git commit -m "x"', cwd=app) == 0


def test_lead_commits_without_unlock_but_not_push(project):
    assert bash(project, "mission-ctl", 'git commit -m "plan"') == 0
    assert bash(project, "mission-ctl", "git push origin main") == 2


def test_push_rules(project):
    unlock.grant(project, "app")
    assert bash(project, "app", "git push origin wz/app/job-0001") == 0
    assert bash(project, "app", "git push origin HEAD:main") == 2
    assert bash(project, "app", "git push origin wz/app/x:refs/heads/integration") == 2
    assert bash(project, "app", "git push -f origin wz/app/job-0001") == 2
    assert bash(project, "app", "git push --force-with-lease origin wz/app/job-0001") == 2


def test_redirects_are_checked_quote_aware(project):
    app = project.store_root("app")
    unlock.grant(project, "app")
    assert bash(project, "app", "echo hi > src/out.txt", cwd=app) == 0
    assert bash(project, "app", "echo hi > README.md", cwd=app) == 2
    assert bash(project, "app", "echo hi >> ../escape.txt", cwd=app) == 2
    assert bash(project, "app", 'git commit -m "a -> b; c > d" && echo ok 2>&1', cwd=app) == 0
    assert bash(project, "app", "cd src && echo x > y.txt", cwd=app) == 0
    assert bash(project, "app", "cd .. && echo x > y.txt", cwd=app) == 2
    assert bash(project, "app", "cp src/a.txt README.md", cwd=app) == 2
    assert bash(project, "app", "rm -rf src/old", cwd=app) == 0
    assert bash(project, "app", "rm -rf e2e", cwd=app) == 2
    assert bash(project, "app", "sed -i s/a/b/ README.md", cwd=app) == 2
    assert bash(project, "app", "echo x | tee src/t.txt", cwd=app) == 0
    assert bash(project, "app", "echo x > $HOME/x", cwd=app) == 2


def test_heredoc_body_is_data(project):
    app = project.store_root("app")
    cmd = "cat > src/gen.py <<'EOF'\nif a > b:\n    print(1) > 2\nEOF\npython3 src/gen.py"
    assert bash(project, "app", cmd, cwd=app) == 0


def test_owner_and_lead_only_commands(project):
    assert bash(project, "app", "wz sign approve sign-0001") == 2
    assert bash(project, "mission-ctl", "wz sign approve sign-0001") == 2
    assert bash(project, "mission-ctl", "wz approve serve") == 2
    assert bash(project, "app", "wz unlock tester") == 2
    assert bash(project, "mission-ctl", "wz unlock tester") == 0
    assert bash(project, "app", "wz sign request 'send it' --cmd 'true'") == 0


def test_fails_closed_and_logs(project, capsys):
    env = {"WZ_ROLE": "app", "WZ_CONFIG": str(project.path)}
    assert guard.main("{not json", env) == 2
    assert guard.main(payload("Read", project.root, file_path="x"), {**env, "WZ_CONFIG": "/nonexistent/wz.toml"}) == 0
    assert guard.main(payload("Write", project.root, file_path="x"), {**env, "WZ_CONFIG": "/nonexistent/wz.toml"}) == 2
    write(project, "app", project.root / "DECISIONS.md")
    log = (project.state / "guard.log").read_text()
    assert "DECISIONS.md" in log and "app" in log


def test_unknown_role_fails_closed(project):
    assert guard.main(payload("Write", project.root, file_path="x"), {"WZ_ROLE": "ghost", "WZ_CONFIG": str(project.path)}) == 2


def test_segments_and_redirects():
    segs = guard.segments('a "x;y" && b > out 2>&1; c')
    assert segs[0] == ["a", "x;y"]
    args, targets = guard.split_redirects(segs[1])
    assert args == ["b"] and targets == ["out"]
    assert os.path.basename(guard.segments("c")[0][0]) == "c"
