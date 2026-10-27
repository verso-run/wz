# wz-lite for hardware, firmware and bench work

One file. Give it to Claude Code in your project and say: **"Follow docs/WZ-LITE-HARDWARE.md."** Nothing to install:
it is plain files, one small Python script and git. It is the [wz](../README.md) bench loop with the machinery taken
out, so you can move to wz later.

You are the **owner**. One Claude Code session is the **lead**, and only it talks to you. The lead writes down what
you said, splits the work into briefs and starts one job per piece. Role sessions do the work and report in files.
Nothing that bricks, fuses or ships a device happens without your signature.

## 0. Set up (ten minutes, the lead does it)

```
DECISIONS.md                     what the owner said, in the owner's words
briefs/NN-title.md               one per piece of work
roles/<role>/CHARTER.md          what a role may write and must never do
roles/<role>/STATE.md            what the role's next job needs (one screen, rewritten whole)
ledgers/DEFECTS.md  ledgers/BENCH.md
bench/RESOURCES.md               every board, instrument, test phone, with its limits
bench/lease.py                   the lease script (section 5)
bench/runs/<scenario>-NNN/       evidence for each run
bench/hands/  bench/signs/       hand-steps and sign requests
bench/leases/  bench/ATTENDED  bench/HALT      lock files and flags (git-ignored)
```

Create the empty files with their table headers (sections 3, 5, 9) and commit. No plan lives in chat.

## 1. The rules, and the failure each one prevents
| Rule | Without it |
|---|---|
| A board or instrument is driven only under a lease that names the job. | Two jobs flash one board and each blames the other. |
| A lease ends when its holder ends or its time is up. Nobody takes it over. | A lock is broken by hand mid-flash, or a forgotten one blocks the bench for days. |
| Flash and RAM are checked against the budget before flashing. The device's records equal a host replay, byte for byte. | An image that cannot fit is flashed anyway; "close enough" hides a real divergence. |
| Every instrument reading is a file, and the report names it. | A number in a report that nobody can trace. |
| A physical act is a hand-step a person answers; hazardous hardware is attended only. | An agent "assumes" a cable was swapped, or a cell charges alone. |

## 2. The lead and the roles

**Lead.** Writes decisions, briefs and ledger rows, starts jobs, and opens the files a report names before accepting
it. Each morning it lists the open hand-steps and sign requests for you. It never flashes, never drives an instrument
and never edits firmware.

| Role | Owns (writes only here) | Does | Never |
|---|---|---|---|
| `firmware` | `fw/`, `roles/firmware/` | builds, flashes and tests firmware on leased boards; keeps the host replay test | touches an instrument setting, or a board it did not lease |
| `bench` | `bench/scenarios/`, `bench/tools/`, `bench/runs/`, `roles/bench/` | drives instruments, captures readings, runs the whole scenario, writes hand-steps | answers a hand-step, acts on hazardous hardware unattended |
| `tester` (and optional `auditor`) | `roles/tester/`, `ledgers/` (append) | runs a candidate end to end the way the owner would; files defects with steps to reproduce; the auditor re-derives each number from its file | fixes what it finds |

Each role has a charter of about ten lines:

```
# Charter: <role>
Read first: this file, roles/<role>/STATE.md, then your brief. You may write only: <paths>. For anything else, put
the request in your brief's Report and stop.
Rules: 1) Drive only resources your job holds a lease on. 2) Never answer a hand-step or write bench/ATTENDED.
3) Numbers come from files and the report names the file. 4) A simulator result says "simulator"; a datasheet figure
says "estimate". 5) Never kill a process by name pattern; kill only a PID you started and recorded.
6) Write your Report early and update it; end with the closing block (section 8). 7) This job is this brief and
nothing else; name extra work in the report and stop.
```

**Running a job by hand.** The lead makes a branch and working copy, then starts one session inside the brief's leases:

```sh
git worktree add -b job/firmware/07 ../job-07 && cd ../job-07
python3 bench/lease.py board-a job-07 7200 -- claude -p "You are the firmware role. Read roles/firmware/CHARTER.md, \
  then briefs/07-sampling-timer.md. Do that brief and nothing else."
```

Before merging, the lead runs `git diff --stat main..job/firmware/07` and checks that every path is one the role owns
(lite has no hook to refuse a bad write). Merge into an integration branch only; you decide what reaches the branch
that ships.

## 3. Decisions in the owner's words
`DECISIONS.md` is a table. One row per decision, never edited. A change of mind is a new row naming the one it replaces.

```
| id | date | owner's words | lead's reading | status |
|---|---|---|---|---|
| D-4 | 2026-03-02 | "Don't charge anything unless I'm in the room." | Cells are hazardous: attended only, no overnight runs. | decided |
| D-5 | 2026-03-02 | (none) | Proposal: cap the supply at 3.6 V. | proposal |
```

The words are quoted exactly. A row without your words is a **proposal** and binds nobody until you say so. The
reading is the lead's and can be revisited. A brief names the decision it serves.

## 4. A brief per piece, one job per piece

A piece is one thing with one result a reader can check ("sampling runs from the hardware timer", "idle current at
two voltages"). One brief per piece, one job per brief, and a job does its brief and nothing else. Extra work it finds
goes in the Report as a follow-up, which the lead queues as its own brief. `briefs/NN-title.md`:

```
# Brief NN: <title>
Role: <role> · Written: <date> · Decision: <D-n and the owner's words>
## Read first
1. roles/<role>/CHARTER.md and STATE.md  2. <the documents that bind this work>
## What done means
One or two sentences a reader can check without asking.
## Resources
Leases: board-a, analyser (max 2h).  Attended: no.  Limits: from bench/RESOURCES.md.
## Ladder (in order; stop and report if a rung fails its acceptance)
1. <step>. Accept: <a number or something observable, and the file that shows it>
2. ...
## Not yours
- <what this job must not touch>
## Report
(the role fills this in)
```

## 5. Resources and leases
Every board, instrument, test phone or remote machine is one row in `bench/RESOURCES.md`. Only you change it.

```
| name | kind | ids | max_hold | hazard | protected | limits and ceilings | notes |
|---|---|---|---|---|---|---|---|
| board-a | device | serial 0001 | 2h | no | no | supply 3.0 to 3.6 V | pairs only with phone-b |
| phone-b | phone | TESTPHONE-B | 2h | no | no | | the only phone that pairs with board-a |
| owner-phone | phone | OWNERPHONE-1 | | no | **yes** | | the owner's own; never leased, never named |
| analyser | instrument | 192.0.2.20:5025 | 1h | no | no | 0 to 5 V, 0 to 0.5 A | read and set over SCPI |
| cell-1 | battery | tag 1 | 1h | **yes** | no | 3.0 to 4.2 V, 0 to 45 C, charge 0.5 A | attended only |
```

**The lease is a lock file** that the OS drops when the holder's process ends. Save this as `bench/lease.py`:

```python
#!/usr/bin/env python3
"""bench/lease.py NAME HOLDER SECONDS -- COMMAND...
Hold the lease NAME while COMMAND runs. Exit 75 if it is taken, 124 if SECONDS passed first. Never waits, never steals."""
import fcntl, os, signal, subprocess, sys, time

name, holder, secs = sys.argv[1], sys.argv[2], int(sys.argv[3])
cmd = sys.argv[sys.argv.index("--") + 1:]
here = os.path.dirname(os.path.abspath(__file__))
os.makedirs(f"{here}/leases", exist_ok=True)
fd = os.open(f"{here}/leases/{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print(f"{name} is taken: {open(f'{here}/leases/{name}.lock').read().strip()}", file=sys.stderr)
    sys.exit(75)
stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
os.ftruncate(fd, 0)
os.write(fd, f"holder={holder} pid={os.getpid()} since={stamp(time.time())} expires={stamp(time.time() + secs)}\n".encode())
env = dict(os.environ, LEASES_HELD=",".join(filter(None, [os.environ.get("LEASES_HELD", ""), name])), LEASE_HOLDER=holder)
p = subprocess.Popen(cmd, env=env, pass_fds=(fd,), start_new_session=True)  # the child keeps the lock if we die
try:
    sys.exit(p.wait(timeout=secs))
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGTERM)
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
    sys.exit(124)
```

A job that needs several resources nests the calls, in alphabetical order, and gets all of them or none:
`python3 bench/lease.py analyser job-09 3600 -- python3 bench/lease.py board-a job-09 3600 -- claude -p "..."`

The rules:
- **Take the lease before the first command that touches the resource and keep it to the end of the job.** `SECONDS`
  is the job's time limit, never more than the row's `max_hold`.
- **Nothing takes a lease over.** A taken lease prints its holder and exits 75. The job does other work or reports
  `blocked`. A holder past its `expires` time is reported to the owner, never broken.
- **Every tool that flashes or drives checks the lease** and refuses without it:
  `case ",$LEASES_HELD," in *,board-a,*) ;; *) echo "board-a not leased" >&2; exit 2;; esac`
- **To see whether a resource is free,** try to take it for `true`: `python3 bench/lease.py board-a look 5 -- true`.
  Exit 0 means free. If the lock file's text and what you see at the bench disagree, stop and ask the person.
- **Check the port before a flash.** `fuser` on the serial port or debug probe must show nothing else using it. Never
  clear it with a pattern kill (`pkill -f`, `killall`).
- **Protected devices** are never leased and their ids never appear in a command: search every flash or install
  command for each protected id before it runs. A board pairs only with the phone its row names.

## 6. Build, flash and test, with evidence

One run is one directory, `bench/runs/<scenario>-NNN/`, and every step writes its log there. The loop, in order,
stopping at the first rung that fails its acceptance:

1. **Host build and host tests** at the job's commit. Record the commit.
2. **Firmware build.** Write `build.json` beside the image: toolchain version, source commit, image sha256.
3. **Budget gate, before flashing.** Read the sizes from the toolchain's size tool and compare with the budget in
   `bench/RESOURCES.md`: flash is text + data, RAM is data + bss. Over budget: stop. Do not flash.
   `size build/fw.elf | awk 'NR==2 {print "flash", $1+$2, "ram", $2+$3}' > bench/runs/<run>/budget.txt`
4. **Flash** the leased board. Keep the log. Read the image hash or version back from the board and compare it with
   `build.json`. A flash that was not read back did not happen.
5. **Drive** with recorded or generated inputs. Save the input files (or their sha256 and the generator's command line).
6. **Capture instruments.** Save every reading as a file, never only in a log:

```python
import json, socket, sys, time
host, query, out = sys.argv[1:4]
f = socket.create_connection((host, 5025), timeout=10).makefile("rw", newline="\n")      # SCPI over raw TCP
ask = lambda q: (f.write(q + "\n"), f.flush(), f.readline().strip())[2]
rec = {"idn": ask("*IDN?"), "query": query, "reply": ask(query), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
open(out, "w").write(json.dumps(rec) + "\n")
```

   Compare each reading with the limits (section 7) as it arrives. Record the instrument settings too.
7. **Pull the device's own records, then replay the same inputs on the host** with the reference code. Compare with
   `cmp device.bin host.bin`. It must be equal. A mismatch names the first differing byte; report it. Never loosen
   the comparison to make a run pass.
8. **App on the test phone**, if there is one, through the same scenario, under its own lease. Then **report**
   (section 8): every value and the file it came from.

How to word a result:
- A result on a simulator or mock says **"simulator"**; on the board it says **"board"**, with the commit. A datasheet
  or calculated figure says **"estimate"** until a measurement replaces it.
- "Tests pass" and "merged" are not "works on the board". Say which board, which commit, which file.
- An agent passes the scenario at the commit and names the run directory **before** the owner runs it.

## 7. Safety stops

**Limits are numbers in `bench/RESOURCES.md`.** A limit that exists only in a sentence is not a limit.
- Before an output is switched on, set the instrument's own over-voltage and over-current limits to the row's ceilings,
  then enable the output. A tool asked for a level above a ceiling refuses.
- Switch outputs off at the end of every job, including a failed one. The safe state is a command written in the
  brief (for example "supply output off, load disconnected").
- **A reading outside its limits stops the run.** Run the safe-state command, then write `bench/HALT` with the
  resource, the reading, the file and the time. Do not retry. Every job looks for `bench/HALT` first and refuses to
  start while it exists. Only the owner deletes it.
- **Hazardous hardware** (a cell, mains, a heater, anything that can burn, charge or discharge) is attended only.
  The owner writes `bench/ATTENDED` when at the bench: `echo "until=$(date -u -d '+90 min' +%FT%TZ) who=owner" >
  bench/ATTENDED`. A job acts on a `hazard = yes` resource only while now is before `until`. Agents never write that
  file. Lite cannot enforce this with a lock; it is the charter's rule and the lead's check. If nobody can watch the
  bench, do not run those steps.
- **No unattended destructive act.** Erase, mass write, unlock, charge, discharge and anything a reflash cannot undo
  wait for the owner.

**Hand-steps.** A physical act (plug, swap, move a probe, charge) is a file the agent writes and a person answers:

```
bench/hands/hand-0003.md:  Ask: Move the probe to bed 2.   Resource: board-a   Expires: 30 min
Answer:
```

The agent reads the file once a minute until it expires, then reports `blocked`. **Only a person writes the Answer
line** (`done`, or `refused: <why>`). The agent never fills it in, assumes it or works around it.

**The owner signs** anything that bricks, fuses or ships. That means: erasing or locking debug access; writing one-time
fuses or protection bits; provisioning keys; replacing the bootloader; publishing an image; running anything on a device
that is not leased for test; and anything on the owner's own devices. The agent asks with `bench/signs/sign-NNNN.md`:

```
Command (exactly): <the full command>     Image sha256: <hash>     Device: <id>
If it goes wrong: <what is lost, and how to undo it, or "cannot be undone">
SIGNED:
```

Only the owner writes `SIGNED: <date> <word>`. The agent runs that one command, once, and only if the image hash is
still the one in the file. Then it appends the result to the same file. A changed image is a new request.

## 8. The report, and the done/blocked line

The role writes the brief's `## Report` **early** and updates it as it goes, because a job cut off at its time limit
leaves nothing otherwise. A usage-limit stop or a timeout is never "done".

```
## Report
Outcome, one line:
Acceptance per rung:   | rung | accept | got | file |
Fields read:           | field | value | file | resource | commit |
Deviations and why. What in the documents was wrong. Ledger ids filed.
Asks (owner / lead). Follow-ups (named, not started).
```

Keep it to about forty lines and tables; long logs go in a linked file. The final message ends with one fenced block:

```json
{"status": "done|blocked", "block_reason": "<only when blocked: one line why>", "result": "<one line, the outcome>",
 "evidence": ["<path or number a reader can check>"], "owner_asks": ["<what only the owner can do, and the exact word>"],
 "lead_asks": ["<what the lead must decide>"], "followups": [{"role": "<role>", "task": "<one job>", "evidence_of_done": "<how it is checked>"}]}
```

`done` only when the brief's "what done means" is met. Otherwise `blocked` with a reason (a lease taken, a hand-step
expired, a limit crossed, a budget exceeded, a rung failed). No block, or an unknown status, is not done. The lead
trusts the line, not the prose, and opens one file from the evidence list before it accepts.

## 9. Ledgers
Append-only tables in `ledgers/`: defects in `DEFECTS.md`, bench findings in `BENCH.md`. Any role adds rows and nobody
edits another's row; a status change is a new row naming the old id.

```
| id | date | severity | role | what (steps to reproduce) | file | status |      <- DEFECTS.md: DEF-1, DEF-2 ...
| id | date | role | resource | finding (value, unit, conditions) | file | status |      <- BENCH.md: BEN-1, BEN-2 ...
```

A bench finding states the value with its unit, the setup (board, commit, instrument settings) and its file. A defect
states the steps to reproduce it. A claim with no file stays an open hypothesis.

## 10. The lead's day, and what lite lacks

Each morning the lead reads `bench/HALT`, the open hand-steps, the open sign requests and any lease past its `expires`,
and tells the owner first. After each job it reads the closing block, opens one evidence file, checks the diff against
the role's paths, merges or sends back, and rewrites that role's `STATE.md` whole.

Lite has no hook that refuses writes outside a role's paths, no timers that start and watch jobs, no merge step, no
enforced attendance check, no approval page and no morning digest. When one of those starts to hurt, install wz. It
keeps the same decisions, briefs, ledgers, leases and run directories, so moving over is a small step.
