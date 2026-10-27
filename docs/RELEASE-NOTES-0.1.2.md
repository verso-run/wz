# wz 0.1.2

This release is about working with your helpers day to day: they keep one conversation each, the lead hands work out
instead of doing it, you can change the team without editing a file, and a few steps wait for you by name.

If you installed 0.1.1, run the install prompt again. It checks what is already there and changes only what is new.

## One conversation per helper

- `wz cli <helper>` opens that helper's own named conversation and keeps it. Close the window, restart the computer,
  come back tomorrow: `wz cli <helper>` picks up where you left off. `wz roll <helper>` starts a fresh one.
- It works from any folder. You no longer have to `cd` into the workspace first. `wz workspaces` lists the ones wz
  knows about and `wz workspaces use NAME` changes the default.
- `wz list` shows each helper, its conversation and whether it is waiting for you.
- With tmux installed, a helper stays open in the background if you only close the Terminal. It sits at its input box and
  does nothing until someone types to it; in the default mode it still asks before it acts. `/exit` in its window, or `wz park <helper>`, ends it. Earlier text in the install pages
  said closing the Terminal left nothing running; that was wrong for anyone with tmux, and the pages now say what
  really happens.

## Say something to a helper

- `wz say <helper> "text"` types a line into a helper's open window and tells you whether it arrived. It reports
  "sent" only after the helper's input box has emptied. If the helper is not open, nothing is typed; the line is saved
  at the top of the helper's STATE.md for when it next starts.
- A helper can `wz say` the lead when it is stuck. A helper cannot message another helper; it asks the lead.
- Every `wz say` is written to `.wz/say.jsonl`, so you can check what was handed over.

## The lead hands work out

The lead (`mission-ctl`) now plans, writes briefs and gives the work to the helper that owns it. It does not do a
helper's work itself, even a small piece. In the simple setup nothing runs by itself, so the lead opens the helper's
window and says the task there. Ask it for one small thing and it should tell you which helper took it.

## Safer by default

- A `wz cli` window asks before it acts unless you write a different `permission_mode` in `wz.toml`. wz says so each
  time it starts a session or a job in any mode that does not ask first. The simple setup refuses the mode that never asks.
- A `permission_mode` or `job_permission_mode` that Claude Code does not know is refused when wz starts, not in the middle of a job.
- Background jobs are the exception, on purpose: see the next section.

## Background jobs run in auto mode

A background job (`wz job add` then `wz serve`, a timer, or `--follow`) has nobody to answer a question, so under the
ask-first mode it could not write a file. Jobs now run in Claude Code's `auto` mode by default, set by the new
`[agent] job_permission_mode`. They can write files without asking, inside wz's guard. `wz cli` windows keep
`permission_mode`, which stays ask-first. wz has not checked where `auto` still stops, and prints a line saying so at
the start of every job; `wz status` shows both modes and each helper's `CHARTER.md` states both. To get jobs that stop
and ask (and so cannot write), set `job_permission_mode = "default"` under `[agent]`. Whether your plan or Claude Code
version offers `auto` is Claude Code's rule; if a job cannot start in it, use `acceptEdits` or `default`.
- Web access is off for every helper until `wz.toml` gives that helper `web`.

## Running a queue by hand

`wz serve --follow` runs the queue in front of you: it starts the ready jobs, waits, starts what they freed, stops
when nothing is left to do, and lists each job still waiting and why. Ctrl-C stops the following, not the jobs. Without
timers installed, nothing else starts a queued job, and `wz job add` now says so.

## Change the team without editing a file

- `wz role add NAME` and `wz role remove NAME` add or remove a helper.
- `wz rule add|remove HELPER "sentence"` changes a helper's rules.
- `wz owns add|remove HELPER STORE PATH` changes the files a helper may write.
- Each takes `--dry-run`, keeps the comments and layout of `wz.toml`, saves the old file to `.wz/backups/`, and stops
  with a plain message if the change would give two helpers the same files. Only you can run them; a helper cannot.

## Steps that wait for you

- `wz job add HELPER "task" --gate "what you decide"` adds a step that waits for you.
- `wz gate list` shows them, and so do `wz status` and the morning digest ("waiting on you").
- `wz gate pass JOB` lets it go. Only you can do that; the lead and the helpers cannot, and `wz job release` will not
  do it either.
- `wz serve --follow` runs up to a gate and then says which gates it stopped at.

## Follow-ups become held jobs

When a job finishes and names follow-up work, each follow-up now becomes a held job instead of only a line in a file.
A held job costs nothing until you release it with `wz job release JOB`, and `wz job cancel JOB` drops it. At most
five follow-ups come from one job, a follow-up's own follow-ups stay as lines in `FOLLOWUPS.md`, and a task already
queued or held for the same helper is not added twice.

## The qual-guides example

The example that writes an interview guide for a small project now has five helpers: a librarian that finds and
summarises reading, a guide writer, a reviewer that names the rule behind each point it raises, a designer that draws
phone-sized pictures of a small companion app, and the lead. It includes a worked sample, two small sample projects and
a chain you can queue where the lead holds two steps until you say go (it does not use `wz gate` yet). The page explains each step in plain words. The chain's
jobs run in `auto` mode, so there is no setting to change before you run it.

## Housekeeping

- `wz brief new` no longer overwrites a brief with the same name; the next one takes the next number.
- The example's checker refuses to write unless it runs in the window of the helper that owns what it writes.
- The test suite tears down the tmux sessions it starts.
- The install pages, `install.sh` and the README now all pin `v0.1.2` and carry the sealed checksum of `install.sh`.
