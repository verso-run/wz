"""A stand-in for `claude -p` in tests. FAKE_CLAUDE_MODE picks the behaviour; FAKE_CLAUDE_LOG records each call."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
resume = args[args.index("--resume") + 1] if "--resume" in args else None
mode = os.environ.get("FAKE_CLAUDE_MODE", "done")
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd(), "role": os.environ.get("WZ_ROLE"),
                            "job": os.environ.get("WZ_JOB")}) + "\n")


def declare(status="done", **kw):
    d = {"status": status, "result": kw.pop("result", f"fake {status}"), "evidence": ["fake"], "owner_asks": [],
         "lead_asks": [], "followups": [], **kw}
    return "Report written.\n\n```json\n" + json.dumps(d) + "\n```\n"


def commit(path, text="hello\n"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    subprocess.run(["git", "add", str(p)], check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", f"fake: {p}"], check=True, capture_output=True)


text = declare()
if resume:
    text = declare(result="declared on the corrective turn")
elif mode == "done":
    if os.path.isdir(".git") or os.path.isfile(".git"):
        commit(f"src/{os.environ.get('WZ_JOB', 'x')}.txt")
elif mode == "conflict":
    commit("src/shared.txt", f"from {os.environ.get('WZ_JOB')}\n")
elif mode == "outside":
    commit("README-outside.md")
elif mode == "blocked":
    text = declare("blocked", block_reason="the bench is not powered", result="could not measure")
elif mode == "nodecl":
    text = "I did the work but forgot the block."
elif mode == "asks":
    text = declare(owner_asks=["approve the logo", "pick a date", "read the draft", "sign the form"],
                   followups=[{"role": "tester", "task": "test the thing", "evidence_of_done": "suite green"}])
elif mode == "sleep":
    child = subprocess.Popen(["sleep", "60"])
    Path(os.environ["FAKE_PIDFILE"]).write_text(str(child.pid))
    time.sleep(60)
print(json.dumps({"type": "result", "subtype": "success", "result": text, "session_id": "sess-1",
                  "total_cost_usd": 0.25}))
