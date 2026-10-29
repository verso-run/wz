"""Rehearsal of the agent watchdog, the wakes and the escalation on a scratch workspace, printed for a human.

    python3 tests/rehearse_agents.py /some/empty/scratch/dir

Real tmux (its own server, in the scratch folder) and the stand-in `claude` of the tests: no network, no tokens, nothing of
the machine's own tmux or timers is touched. Three cases are made to happen and followed to the hub and the digest:

  1. a job reaches its 90-minute limit and writes no report
  2. two windows run the lead (the duplicate after a hub restart)
  3. the lead has no morning wake; then one is declared, signed by the owner and fired into the live session
"""
import datetime as dt
import json
import os
import pathlib
import shlex
import shutil
import stat
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
from conftest import answers, make_repo  # noqa: E402

root = pathlib.Path(sys.argv[1]).resolve()
shutil.rmtree(root, ignore_errors=True)
sock = root / "tmux"
sock.mkdir(parents=True)
(root / "bin").mkdir()
claude = root / "bin" / "claude"
claude.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'fake_claude_tui.py'))} \"$@\"\n")
claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
os.environ.update(GIT_AUTHOR_NAME="rehearsal", GIT_AUTHOR_EMAIL="rehearsal", GIT_COMMITTER_NAME="rehearsal", GIT_COMMITTER_EMAIL="rehearsal",
                  GIT_CONFIG_GLOBAL=str(root / "gitconfig"), XDG_CONFIG_HOME=str(root / "xdg"), TMUX_TMPDIR=str(sock), HOME=str(root / "home"),
                  PATH=f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}", TERM="xterm", WZ_START_SETTLE="0.4", WZ_START_WAIT="15",
                  WZ_SAY_SETTLE="0.15", WZ_SAY_WAIT="0.4")
os.environ.pop("TMUX", None)
(root / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")

from wz import agents, approvals, cli, digest, escalate, flags, hub, jobs, setup_mode, wakes, watchdog  # noqa: E402

(root / "office" / "drafts").mkdir(parents=True)
make_repo(root / "app")
push_log = root / "owner-push.log"
push = root / "push.py"
push.write_text(f"import os, sys\nopen({str(push_log)!r}, 'a').write(os.environ['WZ_PUSH_SEV'] + ' ' + sys.stdin.read().splitlines()[0] + '\\n')\n")
ans = answers(root)
ans["agent_command"] = "claude"                        # the stand-in TUI on PATH, not the headless one
cfg = setup_mode.apply(ans, root / "ws", git_init=False)
cfg.path.write_text(cfg.path.read_text() + f'\n[escalation]\npush = "{sys.executable} {push}"\n')
cfg = cli.config.load(cfg.path)


def tmux(*a):
    return subprocess.run(["tmux", *a], capture_output=True, text=True).stdout.strip()


def show(title):
    print(f"\n=== {title}")


def hub_bar(name):
    return tmux("show-options", "-v", "-t", f"={name}:", "status-right") or "(empty)"


procs = []
try:
    cli.main(["--config", str(cfg.path), "cli", "mission-ctl", "--detach"])
    cli.main(["--config", str(cfg.path), "cli", "app", "--detach"])
    hub_name, _ = hub.prepare(cfg)
    show("start: two live sessions, a hub, no job")
    print("agents:", [(r["key"], r["status"]) for r in agents.tick(cfg)], "| hub bar:", hub_bar(hub_name))

    show("case 3a: the lead has no morning wake")
    for a in watchdog.check(cfg):
        print(f"watchdog {a['kind']:7} {a['ref']:14} {a['text']}")

    show("case 1: a 90-minute job reaches 85 minutes with no report (a real supervisor process that does nothing)")
    sup = subprocess.Popen(["sleep", "600"])
    procs.append(sup)
    j = jobs.get(cfg, jobs.add(cfg, "app", "long task", timeout="90m")["id"])
    j.update(status="running", supervisor_pid=sup.pid, started_t=time.time() - 85 * 60)
    jobs.save(cfg, j)
    log = cfg.state / "logs" / f"{j['id']}.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("{}\n")
    print("agents:", [(r["key"], r["status"], r["reason"]) for r in agents.table(cfg) if r["kind"] == "job"])

    show("case 2: a second window runs the lead (duplicate after a hub restart)")
    tmux("new-session", "-d", "-s", "left-over", "-n", "mission-ctl", "sleep 600")
    tmux("set-option", "-t", "=left-over:", "@wz_root", str(cfg.root))
    for a in watchdog.check(cfg):
        print(f"watchdog {a['kind']:7} {a['ref']:20} {a['text']}")
    print("hub status bar:", hub_bar(hub_name))
    print("escalations:", [(e["id"], e["sev"], e["subject"], e["trail"][-1]["outcome"]) for e in escalate.open_ones(cfg)])
    print("owner push log:", push_log.read_text().strip().splitlines())

    show("the digest, as the owner reads it (Asks, Agents, Open escalations)")
    text = digest.compose(cfg)
    for head in ("## Asks", "## Agents", "## Open escalations"):
        print(head + text.split(head)[1].split("\n## ")[0].rstrip())

    show("the job reaches its limit and is killed with no report: zombie until reminted")
    j = jobs.get(cfg, j["id"])
    j.update(status="failed", timed_out=True, finished_t=time.time())
    jobs.save(cfg, j)
    print("agents:", [(r["key"], r["status"], r["reason"]) for r in agents.table(cfg) if r["kind"] == "job"])

    show("case 3b: the lead declares a 07:15 wake; the owner signs; the timer fires it into the live session")
    tmux("kill-session", "-t", "=left-over")
    cfg.path.write_text(cfg.path.read_text() + '\n[[wake]]\nid = "lead-digest"\nrole = "mission-ctl"\nat = "07:15"\n'
                        'text = "Compose the daily digest and send the owner the three asks."\n')
    cfg = cli.config.load(cfg.path)
    print("wz wake request ->", wakes.request_missing(cfg))
    print("before the sign:", [(r["id"], r["approval"]) for r in wakes.table(cfg)])
    tomorrow = dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(7, 16)).timestamp()
    print("tick 07:16 unsigned ->", wakes.tick(cfg, tomorrow))
    approvals.set_pin(cfg, "123456")
    for r in approvals.pending(cfg):
        approvals.sign(cfg, r["id"], "123456")
    print("after the sign:", [(r["id"], r["approval"], "next " + r["next"]) for r in wakes.table(cfg)])
    print("tick 07:16 signed   ->", wakes.tick(cfg, tomorrow))
    print("tick 07:17          ->", wakes.tick(cfg, tomorrow + 60), "(once per occurrence)")
    f = cfg.root / "said.jsonl"
    deadline = time.time() + 8
    while time.time() < deadline and not (f.exists() and "lead-digest" in f.read_text()):
        time.sleep(0.1)
    print("typed into the lead's pane:", [json.loads(x)["text"] for x in f.read_text().splitlines()])
    print("watchdog now:", sorted({(a["kind"], a["ref"]) for a in watchdog.check(cfg)}), "| hub bar:", hub_bar(hub_name))
    print("events:", sorted({e["kind"] for e in flags.events(cfg)}))
finally:
    for p in procs:
        p.terminate()
        p.wait()
    pids = [int(x) for x in subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_pid}"], capture_output=True, text=True).stdout.split()]
    subprocess.run(["tmux", "kill-server"], capture_output=True)
    print(f"\n(scratch tmux server stopped; {len(pids)} pane process(es) were its own)")
