"""A stand-in for the interactive `claude` in tests: records how it was started, shows an input box, and stays up.

Behaviour comes from the file $WZ_HOME/fake-mode: "exit" ends at once without saving anything, "exit-saved" saves the
conversation (as Claude does under <config dir>/projects/<folder>/) and ends, "login" shows a login screen, anything else
(or no file) shows the input box. Each start appends one line to $WZ_HOME/claude-calls.jsonl.

The input box takes keys like Claude's: typing fills it, Ctrl-U clears it, Enter submits (one line appended to
$WZ_HOME/said.jsonl, box emptied). Mode "stuck" ignores Enter, so typed text stays in the box; mode "queued" submits and
shows Claude's "Press up to edit queued messages" footer, as a session does that is in the middle of a turn.
"""
import json
import os
import select
import sys
import termios
import time
import tty
from pathlib import Path

home = Path(os.environ.get("WZ_HOME", "."))
mode_file = home / "fake-mode"
mode = mode_file.read_text().strip() if mode_file.exists() else "ready"
keys = ("WZ_ROLE", "WZ_CONFIG", "WZ_HOME", "WZ_SCRATCH", "WZ_JOB", "CLAUDE_CONFIG_DIR", "PATH")
with open(home / "claude-calls.jsonl", "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "env": {k: os.environ.get(k) for k in keys}}) + "\n")
if mode == "exit-saved":
    a = sys.argv[1:]
    name = a[a.index("--name") + 1] if "--name" in a else a[a.index("--resume") + 1]
    d = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects" / "".join(
        c if c.isascii() and c.isalnum() else "-" for c in os.getcwd())
    d.mkdir(parents=True, exist_ok=True)
    (d / "s1.jsonl").write_text(json.dumps({"type": "custom-title", "customTitle": name}, separators=(",", ":")) + "\n")
    sys.exit(3)
if mode == "exit":
    sys.exit(3)
rule = "\u2500" * 78
if mode == "login":
    print("Select login method:\n  1. Claude account\n  2. Anthropic Console")
    sys.stdout.flush()
    while True:
        time.sleep(60)


def draw(typed, footer="  ? for shortcuts"):
    sys.stdout.write("\x1b[2J\x1b[H" + "Claude Code v0 (fake)\n\n" + rule + "\n\u276f " + typed + "\n" + rule + "\n" + footer + "\n")
    sys.stdout.flush()


typed, footer = "", "  ? for shortcuts"
if sys.stdin.isatty():
    tty.setcbreak(sys.stdin.fileno())
    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
draw(typed)
while True:
    if not select.select([sys.stdin], [], [], 60)[0]:
        continue
    data = os.read(0, 4096).decode("utf-8", "replace")
    for ch in data:
        if ch == "\x15":
            typed = ""
        elif ch in "\r\n":
            if mode == "stuck" or not typed:
                continue
            with open(home / "said.jsonl", "a") as f:
                f.write(json.dumps({"text": typed}) + "\n")
            typed = ""
            if mode == "queued":
                footer = "  Press up to edit queued messages"
        elif ch.isprintable():
            typed += ch
    draw(typed, footer)
