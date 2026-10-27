# wz

wz is a mission control for a team of AI coding agents. One lead agent, `mission-ctl`, turns your short instructions
into briefs and queued jobs. Role agents do the work on their own branches, inside the paths they own. A hook refuses
what a role may not do. Nothing ships, sends or pays until you sign.

It runs on one Linux or macOS machine with Python 3.11+ and [Claude Code](https://docs.claude.com/en/docs/claude-code).
It uses only the Python standard library.

**Want to install it?** [Install with Claude](#install-with-claude-recommended): paste one message into Claude Code and
Claude does the rest (no programming needed). [Install by hand](#install-by-hand-for-developers) is for developers.

> Status: early (0.1). The machinery below is tested; the conventions are the ones it was extracted from. Expect
> rough edges, and read the guard's limits before you trust it with anything you cannot undo.

## What it is

You talk only to the lead. The lead records what you said as a numbered decision in your own words, writes a brief,
and queues one job per piece of work. A timer serves each job: it creates a git worktree on a fresh branch, holds any
instrument or device the job leased, and runs a Claude Code session with the role's charter. The job ends with a
written report and a closing declaration (`done` with evidence, or `blocked` with a reason). A merge step integrates
green branches. Releases and outward acts wait on an approval page until you enter your PIN. Each morning a digest
tells you what finished and what waits, with at most three asks.

Everything is a file: `wz.toml` (the one config), `DECISIONS.md`, `briefs/`, `ledgers/`, `status/`, and wz's own
state under `.wz/`. Agents coordinate through those files, not by messaging each other.

## Four uses

The core does not care whether the work is code. The workflow packs give each kind of role its default rules.

**Software.** Roles own paths in git repositories. Jobs run on `wz/<role>/<job>` branches. The merge step runs your
checks and moves the integration branch. You sign each release from integration to main.

```sh
wz job add app "add CSV export to the history page" --evidence "tests/test_export.py passes"
wz merge                 # the merge timer does this every 5 minutes
wz promote app           # asks you to sign: main -> the integration commit, by sha
```

**Firmware.** Build and flash jobs lease the device they use, so two jobs never flash the same board.

```sh
wz job add firmware "move the controller's sampling loop to the hardware timer" --lease board-a --timeout 2h
```

**Hardware.** Bench instruments and devices are resources in `wz.toml`. A job holds its leases from start to end. A
chat session can hold one for a single command.

```sh
wz job add bench "measure board-a idle current at 3.3 V and 5 V" --lease bench-psu --lease board-a
wz lease run bench-psu -- python3 bench/sweep.py
```

**Admin.** Documents, email and finance drafts live in a folder store. The agent drafts. Every outward act is a sign
request carrying the exact command. It runs once, after you sign, and only if the request has not changed since.

```sh
wz job add writer "draft the quarterly supplier letter from notes/q3.md"
wz sign request "Email the Q3 letter to the supplier" --cmd "./send-mail drafts/q3-letter.eml"
wz sign approve sign-0001        # or tap Sign on the approval page
wz sign run sign-0001
```

## Worked examples

| Example | For | What it shows |
|---|---|---|
| [examples/qual-guides](examples/qual-guides) | someone who has never used a terminal | a small team that turns a project description into an interview guide and checks it against published advice, with a finished sample and its cost |
| [examples/fernhill](examples/fernhill) | the setup answers | a made-up greenhouse controller set up from an answers file |
| [examples/fernhill-bench](examples/fernhill-bench) | the bench loop | the same project run end to end on simulated hardware |

## Bench loop

The bench loop is hardware : firmware : software : app : instrument, run as one scenario under one set of leases.
Full reference: [docs/BENCH-LOOP.md](docs/BENCH-LOOP.md).

1. Make the change on a branch (a job does this already).
2. Host build and tests.
3. Firmware build, gated on flash and RAM limits from `[bench.budget.<target>]`.
4. Flash a device under test. The job holds the device's **lease**: a lock file naming the job. The lease ends when
   the job exits or times out, and nothing ever takes it over.
5. Drive the device with recorded or generated inputs (a replay tool, a signal generator).
6. Capture instrument readings over SCPI on the network (power analyser, DMM, scope) as evidence files.
7. Pull the device's own records. The host reference replays the same inputs and must match **byte for byte**.
8. Run the app on a leased test phone through the same scenario, end to end.
9. Write the report. It names each field read and the file it was read from.

When a person has to do something physical (plug, swap, charge), the agent writes a **hand-step** (`wz hand ask`).
The lead's `wz next` and the watchdog show it, and the agent waits. Only a person answers a hand-step. Hazardous
hardware (`hazard = true`) is attended only: nothing acts on it until a person runs `wz hand attend` at the bench.
A reading outside `[bench.safety.limits]` stops the run, runs the scenario's `safe_state` command and halts the lane.

Device rules live in `wz.toml`:
- `pair_only_with` reserves a device's pairing slot to one test phone.
- `protected = true` marks an owner's own device. No job may lease it, and the guard refuses any command that
  names its ids.

The owner is never the first tester. `wz bench ready <scenario>` names an agent's passing run of that scenario at
that commit, or it refuses.

**Worked example: the made-up fernhill greenhouse controller** ([examples/fernhill-bench](examples/fernhill-bench)).
The board smooths a moisture probe and opens a watering valve. `sim/` simulates the board, the host reference, the app
and a SCPI power analyser, so this runs on any computer:

```sh
cd examples/fernhill-bench
./run-example.sh                     # starts the simulated analyser, runs scenarios/replay.toml
# when it prints "waiting on hand-0001", answer from a second terminal, as the person at the bench:
wz --config examples/fernhill-bench/wz.toml hand done hand-0001 --note "leads on"
```

The run writes `bench/runs/replay-001/` with every log, `evidence.json` and `REPORT.md`:

```
| step | field                 | value                       | read from                                    |
| 2    | budget.flash          | 98048 of 524288 B (18.7 %)  | build/size.txt                               |
| 6    | analyser.volts        | 3.301                       | 06-capture-analyser.json (MEAS:VOLT? -> ...) |
| 8    | parity.records_equal  | 600/600                     | 08-parity.json                               |
```

Build with `--fault 250` and parity fails at record 250. Build with `--bloat` and the flash gate stops the run before
anything is flashed. [examples/fernhill-bench/briefs/01-replay-loop.md](examples/fernhill-bench/briefs/01-replay-loop.md)
is a brief that has an agent run the whole loop.

```sh
wz bench run scenarios/replay.toml    # the whole loop
wz bench gate --size-file build/size.txt --target default
wz bench parity device.bin host.bin --record 8
wz bench capture analyser volts=MEAS:VOLT? amps=MEAS:CURR?
wz lease run board-a -- ./flash.sh    # hold one lease for one command, never past its max_hold
wz hand list | ask | wait | done | refuse | attend | leave
wz bench ready scenarios/replay.toml  # before the owner touches it
```

## Build and release

Full reference: [docs/BUILD-AND-RELEASE.md](docs/BUILD-AND-RELEASE.md).

| Process | Command or file | What it holds to |
|---|---|---|
| Rings and their gates | `[rings]` order lab, dev, prod; `[rings.<ring>] gates` | A gate passes before an artifact enters a ring. Signed rings wait for the owner. |
| Interface contract | charter rule | The contract changes first, only by adding, and carries a version. |
| Feature flag inventory | `flags.toml`, `wz flags check` (run it in CI) | Every flag is registered and owned, and defaults off unless a decision row ships it on. |
| Artifacts pinned by hash | `wz ring pin`, `wz ring gate` | Gates read the pinned file and check its sha256 before and after, never a tag or a label. |
| Pins carry parameters only | `[release] pin_params` | Hard invariants stay in the code. A pin may set only declared scalar parameters. |
| Cut, sign, presign window | `wz promote`, `wz sign`, `wz hold add <store> --level FREEZE` | The candidate cannot move while the owner signs it. |
| Rollback and revert rehearsal | `[rings.<ring>] rollback`, `wz ring rehearse <ring>` | Deploy, then rollback, then deploy again, on an unsigned ring, before the revert is ever needed. |
| Merge bot and CI queue | `wz merge` (timer) | Ownership backstop, checks, compare-and-swap onto integration. |
| Shipped means read on the live ring | `wz ring read <ring> <field>` | "Live" quotes a field the running ring served, with its read time, kept under `status/live/`. |
| Post-run or field-test review | `wz review collect <session>`, `wz review words` | Collects the session, packs metrics, drafts the review. It asks the owner only for their words. |
| Backlog refill | `wz backlog refill` | Open ledger rows land in each role's backlog once. |
| Focus and prune | `[focus]`, `wz prune [--apply]` | Duplicates and stale holds are cancelled. Off-focus work is held. |
| Holds with an expiry | `wz hold add/list/clear` | BLOCKS and INCONCLUSIVE stop promote and signed acts. Only a decision row clears them. An expired hold is an alert. |
| Andon halt | `wz halt <role\|all>` | Anyone stops a lane. Only the lead lifts it. |
| Budget controller, watchdog | `[budget]`, `wz watchdog` (timer) | No new job starts past the cap. Lost, overdue, stuck, orphaned and idle work, waiting hand-steps, overdue leases. |
| Job timeouts, reminting | `wz job remint <id>` | A failed or timed-out job returns with a new id (its timeout doubled if it timed out), and its dependents are re-pointed. |
| STATE.md and LESSONS.md | `roles/<role>/` | Each job reads both and rewrites STATE.md. LESSONS.md gains one line per failure. |
| Lead handoff | `roles/<lead>/HANDOFF.md` | Written when the lead's context rolls. The fresh session reads it first, then deletes it. |
| Auditor pass | `auditor` pack, `ledgers/AUDITS.md` | A decision row or outward claim stands only when an audit row names it. |
| Remote compute (GPU) | `[resources.gpu-1] kind = "gpu", max_hold = "6h"` | A lease like any device, so one job at a time and never past its bound. |
| Nightly jobs | `[[nightly]]`, the nightly timer | Queued once per day. |
| Daily sync and digest | `wz sync`, `wz digest` (timer) | At most three asks. The lead names its own errors. |
| Status dashboard | `wz status --html status/dashboard.html` | One static page: roles, running work, hand-steps, leases, holds, signs, spend, bench runs. |

## Install

### Install with Claude (recommended)

This is the main way to install wz, and it needs no programming. You paste one message into Claude Code, and Claude
installs wz for you, telling you each step in plain words and asking before it changes anything. About ten minutes.

**1. Get Claude Code.** It is Anthropic's own program for working with Claude. Follow Anthropic's official steps at
https://code.claude.com/docs/en/quickstart (on a Mac the first step is to open the app called **Terminal**: press
Command and Space, type `Terminal`, press Return). You need a Claude account to sign in with, and that is the only
thing that costs money:

- wz itself is free.
- With a **Claude subscription (Pro or Max)**, wz uses your plan's allowance and there is no extra bill. If you use a lot,
  your plan can run out for a while.
- With an **Anthropic API account**, you pay for each use, so every message costs a little real money.
- During setup you choose a **daily spending limit** for the work wz starts (it suggests $5). Your own chats with
  Claude are not counted by it. Plans and prices are on Anthropic's site and change; wz does not set them.

**2. Open Claude Code in a new, empty folder.** In Terminal, type these two lines, pressing Return after each:

```sh
mkdir wz-start && cd wz-start
claude
```

The first time, Claude shows a web page to sign in to your Claude account (the one step nobody can do for you), then
asks whether you trust the folder: say yes.

**3. Paste the install prompt.** Copy **everything in the grey box below**, paste it into Claude, and press Return.
The same text is in [INSTALL-PROMPT.md](INSTALL-PROMPT.md). It pins a released version of the installer and checks its
fingerprint before running it, so if the installer has been changed, Claude stops.

<!-- PROMPT -->
```text
I would like you to install a program called wz on this computer, by yourself, and then help me set it up. I am not a programmer. Please explain each step in plain words, keep it short, and do not use jargon.

What wz is: a helper that keeps a small team of AI assistants organised, so I can tell it what I want done in plain sentences. It is free. The Claude you are running on is what costs anything.

Rules you must follow all the way through:
1. Ask me before anything that costs money or changes a setting of mine, and wait for my "yes". Do not guess my answer.
2. Never use sudo and never ask me for a password. If a step cannot be done without them, stop and explain in plain words what is missing and who could fix it. Do not work around it.
3. Install only into my home folder. Leave everything that was here before as it is.
4. Never switch Claude Code to a mode that skips its questions. Never turn on timers or anything that runs by itself.
5. Never print or copy my passwords, keys, tokens or environment variables.
6. This must be safe to run twice: check what is already there before changing anything, and say so if a step is already done.
7. In every command, first run `export PATH="$HOME/.local/bin:$PATH"`, because a fresh session may not look there yet.

Do these steps in order, telling me in one or two plain sentences what each is about to do before you do it.

Step 1. Fetch the installer, pinned to the release v0.1.1, and check it has not been changed:
  mkdir -p "$HOME/.cache/wz-install" && curl -fsSL https://raw.githubusercontent.com/verso-run/wz/v0.1.1/install.sh -o "$HOME/.cache/wz-install/install.sh"
Then compute its SHA-256 (`shasum -a 256` on a Mac, `sha256sum` on Linux). It must be exactly
  827e44b2d3842e135d5f4fe325b65b7baa3e77874d9a9d53f4b3aed46b78c970
If it is not exactly that, stop, tell me the installer does not match, and do not run it.

Step 2. Look at this computer: run `sh "$HOME/.cache/wz-install/install.sh" check`. Tell me in plain words what it found (Mac or Linux, what is already installed). If it stops with a message, tell me that message in your own plain words and stop there.

Step 3. Tell me the plan and ask for my yes. The plan: add three things to my home folder only, skipping any that are already there: a small Python helper called uv (it also fetches a Python for wz if this computer has none), wz itself, and Claude Code if it is somehow missing. Say that installing costs nothing, that nothing is changed outside my home folder, and that I can remove all of it later with one line (see the Start-here page).

Step 4. After my yes, run `sh "$HOME/.cache/wz-install/install.sh" --yes uv wz claude verify workspace`. Show me the result in plain words. The `verify` part makes a throwaway test project, shows that wz starts, and checks that it is in the ask-before-acting mode. If anything fails, explain what failed, do not retry in a loop, and stop.

Step 5. One more change needs its own yes: so that `wz` works in new Terminal windows, the installer may add three marked lines to my shell settings file. Ask me. Only after a yes, run `sh "$HOME/.cache/wz-install/install.sh" --yes path`. If I say no, tell me the line to type instead: export PATH="$HOME/.local/bin:$PATH"

Step 6. Before the setup questions, say to me out loud, in plain words, what wz starts with: Claude Code keeps asking before it acts; nothing runs by itself, with no timers until I ask for them; and I choose a daily spending limit in the next step.

Step 7. Open the setup conversation. First look for `$HOME/wz-work/wz.toml`. If it already exists, wz was set up before: tell me so, show me the daily limit it holds, and ask whether I want to start the setup over; if I do not, skip to Step 8 and change nothing. Otherwise run `wz init --simple --print-charter --dir "$HOME/wz-work"`. It prints the path of a file with your instructions for the setup conversation. Read that file and follow it exactly from now on: it asks me a few short questions, one at a time, including the daily limit (suggest a low one, such as 5 dollars). Do not skip its questions and do not answer them for me.

Step 8. When the setup is written, tell me in three or four lines: where my files are, how to talk to wz again, how to stop everything (type /exit in each Claude window, or run `wz park <helper>`; if you only close the Terminal, a helper stays open in the background, waiting for you; nothing starts work by itself), and how to uninstall. Then ask what I would like done first.
```
<!-- /PROMPT -->

**4. What you will see, and what to answer.**

- Claude explains each step in a sentence or two before it does it. Every time it wants to run a command, Claude Code
  shows a box asking whether to allow it. Read it and choose **Yes**. That is Claude Code asking before it acts, and it
  stays that way.
- It asks for your **yes to the plan** (add three small things, all in your home folder, nothing outside it) and,
  separately, for your **yes to three lines** in your shell settings file so `wz` works in new Terminal windows.
- Then it asks a few short questions, one at a time, each with a suggestion: a name and one line about what the work is
  for; what kind of work (paperwork and writing is the default); which folder; **your daily limit** (take your own number;
  5 dollars is suggested); and what time you want a short summary file each morning (08:00). Nothing is sent anywhere.
- It ends by telling you where your files are, how to talk to wz again (`cd` into the folder, then `wz cli mission-ctl`),
  how to stop everything (type `/exit` in each Claude window, or run `wz park <helper>`; closing only the Terminal leaves a
  helper open in the background, waiting for you, and no timers are installed, so nothing starts work by itself), and how to
  uninstall.

Pasting the prompt twice is safe: it checks what is already there. The same steps, with the Terminal one-liner and the
uninstall line, are on [START-HERE.md](START-HERE.md).

### Install by hand (for developers)

The Terminal one-liner does what the prompt does without Claude, then opens Claude (which needs the same sign-in):

```sh
mkdir -p "$HOME/.cache/wz-install" && curl -fsSL https://raw.githubusercontent.com/verso-run/wz/v0.1.1/install.sh -o "$HOME/.cache/wz-install/install.sh" && sh "$HOME/.cache/wz-install/install.sh"
```

Or from a checkout, with Python 3.11+:

```sh
git clone <this repository> wz
cd wz
pipx install .
wz --version
```

Without pipx, use a virtual environment (a plain `pip install --user` fails on distributions that mark Python as
externally managed, PEP 668):

```sh
python3 -m venv .venv && . .venv/bin/activate && pip install .
```

You can also run it from the checkout without installing: `./bin/wz`.

You also need Claude Code installed and logged in (`claude` on your PATH). git is needed for git stores, and tmux is optional
(`wz cli` uses it when it is there and runs the session in your terminal when it is not).

## Safety

Read this before you start a timer.

- wz passes `[agent] permission_mode` to Claude Code unchanged, and the default is `default`: Claude Code asks before it
  edits or runs anything you have not already allowed. Any other mode has to be written in `wz.toml`, and wz says so at every `wz cli` and job start (see
  "Permission mode" below). The guard is a seatbelt, not a sandbox (see "What the guard does not do" below).
- Timers spend unattended, up to `[budget] daily_usd` per day. A job that is already running can pass that figure.
- Run wz as a dedicated user or in a VM, an account that cannot reach what it must never touch. This matters most if
  you set a mode in which Claude Code does not ask.
- Web access is off for every role until `wz.toml` gives that role `web` (see "What the guard covers").
- Claude Code asks "trust this folder?" the first time it starts in a new workspace or worktree. Answer it once by
  running `claude` there yourself, or the first job waits on that prompt.

### Permission mode

`[agent] permission_mode` in `wz.toml` is handed to `claude --permission-mode` for every `wz cli` session and every job.
A missing line means `default`. wz refuses to load a `wz.toml` whose mode is not one Claude Code accepts
(`default`, `plan`, `acceptEdits`, `auto`, `dontAsk`, `manual`, `bypassPermissions`), so a typo stops at the first
command, not in the middle of a job. `wz init` writes `default` unless the answers name another mode, and the simple setup
refuses `bypassPermissions`.

Which of this README's sentences hold depends on the mode:

| Mode | "Claude asks before it acts" | "A background job cannot ask permission" |
|---|---|---|
| `default` | Yes. | Yes: a job has nobody to answer, so it cannot do what needs a yes. |
| `plan` | Yes (it only plans). | Yes: it edits and runs nothing. |
| `acceptEdits` | Only for actions other than file edits. | Edits go through; other actions need a yes a job cannot get. |
| `auto`, `dontAsk`, `manual` | wz has not checked where Claude Code asks in these modes. Do not rely on it. | Do not rely on it. |
| `bypassPermissions` | No. | No: a job runs without stopping. |

For every mode except `default` and `plan`, wz prints one line at each `wz cli` start (to the terminal, before the
session opens) and at each job start. A job started by `wz serve` or the timers has no terminal, so its line lands in
`.wz/logs/<job>.supervisor.log`; one run in the foreground prints it to that terminal. The job's record in `.wz/jobs/`
also keeps the mode, and `wz status` shows the mode and what it means. Each role's `CHARTER.md`
states the mode in use and what it means for that role, so the lead no longer repeats a sentence that is not true for
the mode in force. START-HERE.md and the install prompt describe the setup as shipped, which is always `default`;
they are not rewritten when you change the mode.

## Getting started (about 15 minutes)

1. **Make a workspace** for the lead's files, next to your repositories:
   ```sh
   mkdir -p ~/work/fernhill-ctl && cd ~/work/fernhill-ctl
   wz init
   ```
   With no `wz.toml`, `wz init` (or `wz cli mission-ctl`) starts the lead in setup mode. It asks about your project,
   which of the four workflows you need, your repositories or folders, roles, devices to lease, Claude accounts and
   budgets, and the digest time. It writes `wz.toml`, the workspace files, one charter per role and the hook
   settings. Without Claude Code, use `wz init --plain` for the same questions at the prompt. To script it, use
   `wz init --answers answers.json` (see `examples/fernhill/answers.json`).
2. **Set your signing PIN** (6 or more characters), in your own terminal. No agent ever sees it.
   ```sh
   wz sign set-pin
   ```
3. **Run the example job end to end.** The lead offers this during setup.
   ```sh
   wz init --example
   wz next
   ```
4. **Install the timers.** Look at the dry run first.
   ```sh
   wz install timers --dry-run
   wz install timers           # systemd user timers on Linux, launchd agents on macOS
   ```
   **Without timers nothing starts a queued job.** `wz job add`, `wz queue` and `wz status` say so when no `wz serve`
   has run in the last five minutes. To run a queue by hand, `wz serve --follow` stays in the foreground: it starts the
   ready jobs, waits, starts what they unblocked, and stops when the queue is idle, then lists each job left waiting
   and why (held, waiting for another job, over budget). Ctrl-C stops the following, not the jobs.
   While a job runs, `wz status` and `wz queue` show when it last wrote output, and `wz job tail <id>` shows what the
   agent last said or did. Each job's whole transcript (every file it read, every command's output) is kept in
   `.wz/logs/<job>.out`; nothing deletes these, so clear old ones from time to time.
5. **Start the lead** and tell it what you want, in one sentence:
   ```sh
   wz cli mission-ctl
   ```
6. **Watch it** with `wz status`, `wz queue` and `wz next`. Read `status/DIGEST-<date>.md` each morning. To sign
   from your phone, run `wz approve serve` and reach it over your own VPN or an SSH tunnel.

### Gates: a step that waits for you

When a step needs your decision before the work after it should start ("you pick the sources"), the lead adds the job
with a gate:

```sh
wz job add librarian "read the two journals and write the note" --gate "owner picks sources"
wz gate list               # everything that waits on you (also in `wz status` and the digest, under "waiting on you")
wz gate pass job-0004      # your go-ahead: the job is queued and runs next
```

A gated job is held, not a new status, and it is not the same as `wz job hold`: a hold is the lead's pause and the lead
can release it; a gate is yours. `wz job release` refuses a gate, `wz gate pass` is refused inside any role session
(the lead's too) and by the guard, and a job that comes after a gated one waits for it. `wz serve --follow` runs up to
the gate, names it, and stops; run it again after you pass the gate. `wz prune` never cancels a gate, however old.

## Sessions

`wz cli <role>` opens a role's interactive session: one named Claude conversation per role, kept in a tmux session so it
survives a closed window, a detach and a reboot. Without tmux it runs in your terminal and the conversation is still saved.

| What | How |
|---|---|
| Open, or come back to, a role | `wz cli <role>` (the lead if you give no role), from any folder (see "Which workspace" below). Inside tmux it switches your client to it; outside it attaches. `Ctrl-b d` leaves it running. |
| Start it without attaching | `wz cli <role> --detach` |
| The conversation | The first start runs `claude --name wz-<project>-<role>`; every later start runs `claude --resume` with that name, from the same `CLAUDE_CONFIG_DIR` (recorded in `.wz/sessions/<role>.json`). `wz cli <role> --print` shows the command. |
| A fresh conversation | `wz roll <role>` (the name becomes `wz-<project>-<role>-2`, then `-3`). The old conversation stays on disk. |
| Stop a role | `wz park <role>` closes its tmux session and `wz start-all` leaves it alone; `wz cli <role>` brings it back, resuming. |
| After a reboot | `wz start-all` starts, one at a time and detached, every role that had a session and is not parked, and waits for each to show Claude's input box. It never presses a key in a dialog: a login screen or a question is reported, and you open that role with `wz cli <role>`. Exit code 1 if any role is not at its input box. |
| See them | `wz list`: each role's tmux session, conversation name and state. |
| Apply a changed `wz.toml`, charter or account | A running session keeps the settings it started with, and `wz cli` says so. `wz cli <role> --restart` closes it and starts it again with the current ones, resuming the same conversation. |

How it works. The tmux session is `wz-<project>-<role>` and runs a small script (`.wz/sessions/<role>.sh`) that sets `PATH`,
`WZ_ROLE`, `WZ_CONFIG`, `WZ_HOME`, `WZ_SCRATCH` and `CLAUDE_CONFIG_DIR` itself, so those do not depend on the environment an
already-running tmux server started with (anything else in that environment still reaches the role), and it needs no `tmux new-session -e` (tmux 3.2). When Claude exits the window
becomes a shell, so the session never vanishes; `wz cli <role>` starts Claude again in it. Two workspaces with the same
`[project] name` would share session names; wz refuses the second and tells you to rename the project.

With tmux, closing the Terminal window leaves the role's Claude running in the background. In the safe setup Claude asks
before it acts, so a left-over session waits quietly (one closed in the middle of a turn finishes that step first, then waits at the next question); `wz park <role>` (or `/exit` in its window) ends it. This is separate from
`wz halt`, which stops a role's queued jobs. If Claude ended within 30 seconds of starting and no conversation by that name
was saved (a login you abandoned, an immediate `/exit`), the next `wz cli <role>` creates it again instead of resuming nothing.

Tested against tmux 3.0a, 3.1c, 3.4 (Linux) and 3.5a (macOS).

### Which workspace (any folder)

`wz init` records the workspace in a per-user list, `workspaces.json` in `$XDG_CONFIG_HOME/wz` (else `~/.config/wz`), and the
first one is the default. A command that needs a workspace looks, in this order, at `$WZ_CONFIG` (inside a role's session),
`--ws NAME`, a `wz.toml` in the current folder or above, then the default. So `wz cli mission-ctl`, `wz say`, `wz list`,
`wz start-all`, `wz park` and `wz roll` work from any folder. Every command that falls back to the default workspace (no
`wz.toml` here, no `--ws`) prints a line on stderr naming the workspace it is acting on, `wz job list` included. Setup mode starts
only when no workspace is registered (or you run `wz init`). A workspace made before this list existed is added the first
time you run `wz cli` inside it.

A role's conversation always resumes from the role's own folder (Claude files conversations by folder), whichever folder you
typed the command in.

| What | How |
|---|---|
| List them | `wz workspaces` (`*` marks the default) |
| Use another one for one command | `wz --ws NAME cli <role>` (or `--ws NAME` after the command) |
| Change the default | `wz workspaces use NAME` |
| Forget one (its files are untouched) | `wz workspaces forget NAME` |

Two workspaces with one project name are named `name` and `name-2` in the list. `uninstall.sh` removes the list (never the workspace folders).

## Talking to your roles

`wz say <role> "<text>"` types a line into that role's live session and says it was sent only when Claude's input box has
emptied again. The lead uses it to hand work to roles; any role can `wz say` the lead when it is blocked or needs a decision
(a role may not message another role: it asks the lead in its report). The sender is shown to the receiver as `[from <role>]`.

| What happened | What `wz say` prints, and the exit code |
|---|---|
| The box emptied | `said to <role> … its input box emptied`, 0 |
| The role is in the middle of a turn and Claude queued the line | `queued, delivered when its turn ends`, 0 (Enter is not pressed again: that would queue a second copy) |
| The line is still in the box after 4 Enters | `FAILED … still in <role>'s input box, unsent`, 1; the box is cleared again so it is not glued onto the next line |
| The box disappeared after typing (a dialog opened) | `UNCONFIRMED`, 1; it is not noted, so it is never sent twice |
| No live session: not started, parked, Claude ended (its window is a shell), a login screen, a question, a loading session | **nothing is typed** (a shell would run it as a command); the line is saved as a dated `> **Note …**` at the top of `roles/<role>/STATE.md`, which that role reads when it next starts, exit 0. **No job is queued**: `wz job add <role> "<task>"` is how work starts. |

Newlines are folded into spaces (a newline would press Enter mid-line). Every `wz say` appends a line to `.wz/say.jsonl`
(who, to whom, the outcome above, the text), which is how you check that the lead handed something over.

**The lead delegates.** `mission-ctl`'s charter (the one `wz init` writes, and both setup charters) says it plans, writes
briefs, and hands the work to the role that owns it, by `wz say` to a live session or `wz job add`; it reads their reports and
does not do a role's work itself, even a small piece. To check this on a fresh simple setup, ask `mission-ctl` for one small
thing; it should say which helper it gave it to, and `.wz/say.jsonl` (or `wz job list`) shows the hand-over. In the simple
setup nothing runs by itself, so the lead opens the helper's window first (`wz cli <helper> --detach`) and says it there; the
helper's questions wait for you in that window (`wz cli <helper>`).

## The rules, and the failure each prevents

Every charter carries these rules. "Enforced by" says what wz checks in code. "Charter" means the rule is an
instruction to the agent, and wz does not check it.

| Rule | The failure it prevents | Enforced by |
|---|---|---|
| Every path has one owner, and the guard enforces it. | Agents trusted to stay in their lane edit each other's files. | the guard refuses the out-of-lane writes it can see; the merge step re-checks every changed file in a git store |
| Coordination goes through files (briefs, reports, flags), never extra model turns. | Agents spend the budget acknowledging and polling each other. | flags and `wz next`; charter |
| "Shipped" or "live" names the field you read from the running system and the source line at the commit. | "Merged" or "tests green" is reported as live when it is not. | charter |
| A claim about what the code does cites the code at a commit; a label, docstring or report is not evidence. | Names and summaries overstate what actually runs. | charter |
| A decision carries the owner's own words, or it is only a proposal. | The lead invents a requirement and it hardens into a gate. | `wz decide` records a row without words as a proposal |
| New behaviour ships behind a switch that is off by default, unless the brief names it the release default. | Half-built work reaches users. | charter |
| Interfaces change contract first, and only by adding. | Two components drift apart and break each other. | charter |
| An agent runs the work end to end before the owner touches it. | The owner becomes the first tester. | tester pack; charter |
| Releases and every outward act (send, file, pay, post, deploy) wait for the owner's sign. | An agent ships or sends on its own judgment. | sign requests (PIN, write-once, bound to a digest); guard refuses pushes to main and integration |
| Kill only the process ID you started, never by pattern. | A pattern kill takes down someone else's live environment. | guard refuses pattern kills; the job supervisor kills only its own process group |
| Nothing restarts inside a declared freeze window. | A late change breaks a live test. | charter (`wz halt` stops a lane at once) |
| A job ends with a declared status and its evidence; nothing it started keeps running. | Work is left running that nobody reads, and "done" is assumed. | supervisor: no valid declaration means failed (after one corrective turn); process group swept at the end |
| Agents never read or print secrets. | A token lands in a log or a transcript. | guard refuses secret paths, environment dumps and secret-named variables |
| The lead names its own errors in the digest. | Mistakes are hidden and repeated. | the digest has the section; charter |

**What the guard covers.** The guard sees these tool calls and nothing else:

| Tool call | What it checks |
|---|---|
| `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | the path is one the role owns or may always write; not a secret path |
| `Bash` | redirects, `tee`, `cp`, `mv`, `rm`, `sed -i` targets; pattern kills; secret paths and environment dumps; `git commit/tag/push` without an unlock, force pushes, pushes to a protected branch; owner-only `wz` commands |
| `Read`, `Grep`, `Glob`, `NotebookRead` | the path is not a secret |
| `WebFetch`, `WebSearch`, and any `mcp__*` tool | the role has web access: `web = true`, or a list of tool names or globs, under `[roles.<name>]` in `wz.toml`. Off unless set. |

Web access is a per-role switch the owner sets, for example `web = ["WebFetch"]` to let a librarian open the links it is
given but not search, or `web = true` for every web and MCP tool. The guard checks the tool's name. It does not see what
is fetched or where it goes, and it does not treat a `curl`, `wget` or `python3 -c` in a shell as web access: a role with
`web` off can still reach the network from `Bash`. Any other tool (`TodoWrite`, `Task`, `Skill`, a tool Claude Code adds
later) is let through unchecked. If the guard cannot read its config, it refuses a web or MCP call and a write, and lets
other calls through.

**What the guard does not do.** It is a seatbelt, not a sandbox. It parses shell commands with quotes and heredocs in
mind: redirects, `tee`, `cp`, `mv`, `rm`, `sed -i` and git. A determined interpreter one-liner can still write
somewhere it should not. The merge step's ownership check is the backstop for anything that reaches a branch. Run
agents under an account that cannot reach what it must never touch.

## Architecture

```mermaid
flowchart TD
    O(["Owner"]) -- "one sentence" --> L["mission-ctl, the lead"]
    L -- "wz decide" --> D[("DECISIONS.md")]
    L -- "wz brief new" --> B[("briefs/")]
    L -- "wz job add" --> Q[("job queue")]
    T{{"serve timer"}} --> Q
    Q -- "one supervisor per job: worktree, leases, unlock, timeout" --> R["role agents: software, firmware, hardware, admin"]
    G["guard hook"] -. "refuses unowned writes, pattern kills, secret reads" .-> R
    R -- "report" --> B
    R -- "branch" --> M["merge step: ownership and checks"]
    M --> I[("integration branch")]
    R -- "flag" --> E[("events")]
    W{{"watchdog"}} --> E
    E -- "wz next" --> L
    L -- "wz promote, wz sign request" --> S["approval page"]
    O -- "PIN" --> S
    S -- "signed, runs once" --> P["main branch or outward act"]
    L -- "wz digest" --> DG[("daily digest")]
    DG --> O
```

| Piece | Where | What it does |
|---|---|---|
| Config | `wz.toml` | project, stores (git or folder), roles and their owned paths, rings, accounts, resources, budgets |
| Charters | `wz charters` → `roles/<role>/CHARTER.md` | each role's instructions, built from the config, its pack and the rules |
| Team changes | `wz role`, `wz rule`, `wz owns` (`add` / `remove`) | the owner changes helpers, rules and owned paths without editing `wz.toml` by hand |
| Queue | `wz job`, `.wz/jobs/` | priority, dependency, timeout, leases, per-job commit unlock |
| Serve | `wz serve` (timer, every minute; `--follow` by hand) | claims ready jobs within each role's cap and the budget; one supervisor per job |
| Guard | `wz hook guard` (PreToolUse) | ownership, pattern kills, secrets, unlocks, protected branches, owner-only commands, web and MCP tools |
| Flags | `wz hook flag` (PostToolUse), `wz next`, `wz wait` | finished work announces itself through files |
| Merge | `wz merge` (timer, every 5 minutes) | ownership backstop, merge, checks, then moves the integration branch |
| Signs | `wz sign`, `wz approve serve` | requests anyone may make; signs only the owner gives |
| Watchdog | `wz watchdog` (timer, every 10 minutes) | lost, overdue, stuck, orphaned and idle work; unsigned requests |
| Budget | `wz budget` | daily spend per account from each job's reported cost; serve stops starting jobs at the cap |
| Records | `wz decide`, `wz ledger`, `wz brief`, `wz sync`, `wz digest` | the written record and the morning digest |
| Andon cord | `wz halt <role>`, `wz halt all` | anyone stops a lane at once; only the lead lifts it |
| Leak scan | `wz scan --deny-file private-words.txt` | grep a tree for words that must not be published |
| Bench | `wz bench`, `wz hand`, `wz lease` | scenarios under leases, budget gates, SCPI capture, parity, hand-steps, safety limits |
| Release | `wz ring`, `wz hold`, `wz flags check` | pins by hash, ring gates, revert rehearsal, live read, holds and freezes, flag inventory |
| Upkeep | `wz job remint`, `wz backlog refill`, `wz prune`, `wz nightly`, `wz review` | the queue stays honest and on focus |

## Configuration

`wz.toml` is the only config. Setup writes it. Edit it, then run `wz charters`. A small one:

```toml
[project]
name = "fernhill"
workflows = ["software", "admin"]
digest_time = "08:00"

[budget]
daily_usd = 40.0

[stores.app]
kind = "git"
path = "../fernhill-app"
main = "main"
integration = "integration"
checks = ["python3 -m pytest -q"]

[stores.office]
kind = "folder"
path = "../fernhill-office"

[accounts.main]
config_dir = ""        # CLAUDE_CONFIG_DIR for jobs; empty means your default login
daily_usd = 40.0

[roles.mission-ctl]
pack = "lead"

[roles.app]
pack = "software"
store = "app"
[roles.app.owns]
app = ["src/**", "tests/**"]

[roles.writer]
pack = "admin"
store = "office"
[roles.writer.owns]
office = ["drafts/**"]
```

### Changing the team without editing the file

You can edit `wz.toml` by hand, or let wz do the common changes. These are the owner's commands: they run from your own
terminal, and the guard refuses them inside any role session.

```sh
wz owns add writer office 'drafts/**'          # a helper may write this path (role, store, path)
wz owns remove writer office 'drafts/**'
wz rule add app "Run the full suite before you report."   # one more standing rule in that helper's charter
wz rule remove app "Run the full suite before you report."
wz role add designer --pack admin --store office --owns office='mocks/**'
wz role remove designer
```

Add `--dry-run` to any of them to see the change without making it. Each command edits the text of `wz.toml`, so your comments
and the order of the file stay. Before it writes, it checks that the edited file means exactly what you asked, that wz accepts
it, and (for paths) that no other role owns an overlapping path (each path has one owner). It keeps the old file in
`.wz/backups/`, rebuilds the affected charters and prints what changed. When the file is written in a form it cannot edit
safely, it changes nothing and says what to add by hand. A role removed this way keeps its `roles/<name>/` folder. A role session that is already open
keeps its old charter until it is restarted (`wz cli <role> --restart`).

Packs: `lead`, `software`, `tester`, `firmware`, `hardware`, `bench`, `release`, `admin` and `auditor`. A role may override `desc`,
`model`, `effort`, `account`, `cap` (concurrent jobs, default 1), `timeout` and `rules`. `[resources.<name>]` declares
anything a job can lease (`kind`, `ids`, `max_hold`, `protected`, `pair_only_with`, `hazard`, `scpi`). `[bench]` holds
`budget.<target>` (flash, ram) and `safety` (attended_only, limits). A role may also set `web` (`true`, `false`, or a list of tool
names such as `["WebFetch"]`; default `false`). `[agent]` sets `command`, `permission_mode` (default `"default"`), `pass_effort` and `default_model`. `[guard]` sets `secrets` (globs), `allow` (extra writable roots) and `temp` (whether the
temp directory is writable). `[publish] deny` and `allow` hold leak-scan patterns.

## Tests

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install pytest
python -m pytest -q
```

CI runs the suite on Linux and macOS (`.github/workflows/ci.yml`). The tests use a stand-in for `claude`, so they
need no account and spend nothing.

## Licence

Apache License 2.0; see [LICENSE](LICENSE). Copyright 2026 Verso Labs Inc.

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) (tests, pull requests, sign-off, no CLA). Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security problems: [SECURITY.md](SECURITY.md) (report privately).
