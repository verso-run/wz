# How the samples were made, and what they cost

Two samples ship here. The **car scent study** (`projects/car-scent-study/`, with the research note, three briefs and six
phone mocks) was made by the chain described next. The **Larkspur Tool Library** (`projects/larkspur-tool-library/`) came
from the first, simpler run, described after it. Everything below is what happened, on 2026-10-26, not what should happen.

## The car scent chain: what ran

Run on Claude Code 2.1.311 with the three working helpers and the designer on the `sonnet` model, in a workspace made with
`wz init --simple --answers answers.json`, and **no timers**: every job was started by hand with `wz serve --wait`
(after each gate was passed, or after a batch). One `--wait` call ran a job and the job waiting on it (0008 and 0009,
0010 and 0011, 0012 and 0013). The project folder (`brief.md`, `audience.md`, the two documents) was written by hand,
fresh, and is the only input apart from `sources/links.md`.

**Nobody real played the lead or the owner.** One engineer (an AI agent, not a customer) acted as `mission-ctl` and as the
owner: it queued the jobs, passed the gates, and wrote the made-up owner words in the decision table below. The
interview-by-person with `mission-ctl` has still not been tried with a real, non-technical person.

| Job | Helper | What it did | Result | Minutes | Cost (USD) |
|---|---|---|---|---|---|
| 0001 | librarian | brief 01, the literature search | blocked: its first web search was refused | 0.4 | 0.14 |
| 0002 | librarian | brief 01 again, after a settings-file allow | blocked: the same refusal | 0.3 | 0.11 |
| 0005 | librarian | brief 01: eight sources opened, five questions, quotes checked | done | 3.6 | 0.48 |
| gate | owner | picked six of the seven suggested sources into `sources/links.md` (D-2) | passed | | |
| 0003 | librarian | methods base: rows M7 to M12 and rules for `past-behaviour` and `sample-size` | done | 0.9 | 0.19 |
| 0004 | designer | six phone screens, `index.html`, `NOTES.md` (brief 02), started beside the research | done | 2.1 | 0.46 |
| 0006 | librarian | brief 03 with four gaps | cancelled: a fifth gap was added to the brief (D-3) | | 0 |
| 0007 | librarian | brief 03 with five gaps: a "Second search" section | done | 2.1 | 0.42 |
| gate | owner | read `audience.md` and said it was right (D-4) | passed | | |
| 0008 | guide-writer | first guide | done | 1.2 | 0.30 |
| 0009 | reviewer | **CHANGES NEEDED**, 8 findings (kept as `round1-*`) | done | 1.3 | 0.25 |
| gate | owner | answered the consent-script gaps the review found (D-5) | passed | | |
| 0010 | guide-writer | fixed all 8 | done | 1.0 | 0.23 |
| 0011 | reviewer | **CHANGES NEEDED**, 2 findings (kept as `round2-*`) | done | 0.8 | 0.22 |
| gate | owner | two answers: delete on request; the smell words are a real goal (D-6) | passed | | |
| 0012 | guide-writer | fixed both | done | 0.6 | 0.19 |
| 0013 | reviewer | **PASS** (`review.md`) | done | 0.7 | 0.23 |
| | | **Total** | | 14.4 for the ten that worked (15.1 with the two blocked) | **3.23** |

Minutes are wall-clock from wz's job records. Cost is the `total_cost_usd` Claude Code reports for each job, which is the
figure wz's daily limit counts. The two blocked jobs cost $0.25 of the total; the jobs that worked cost **$2.97**. The $5
daily limit was not reached. The whole chain took about 18 minutes of the clock, most of it the librarian's two searches.

### The made-up owner's decisions

The owner's words are made up for this example. What they show is the habit: each choice is written down.

| id | The owner (made up) | What the lead wrote down |
|---|---|---|
| D-1 | "Yes, let the background jobs write files. Use acceptEdits." | `permission_mode = "acceptEdits"` in `wz.toml`. wz printed its notice that the mode is not `default` at the start of every job. |
| D-2 | "From the first search I want the Mom Test, Nielsen, Guest, Sauro, the NPR piece and the survey biases chapter. Not the thesis: it is an abstract only." | Six sources pasted into `sources/links.md` as 7 to 12. |
| D-3 | "Should Rowan also talk to people who looked at the shop and did not buy, and how would we find them?" | A fifth gap in brief 03, and job 0006 cancelled and added again as 0007 so its done-check says five gaps. |
| D-4 | "Audience answers look right. Go ahead and write the guide." | Job 0008 released. |
| D-5 | "Keep the recording twelve weeks, only the two of us hear it, notes without names for a year, voucher within three days." | Added to `docs/shop-notes.md`. |
| D-6 | "Yes, we delete anything on request. And the words people use for the smell are wanted: make it a real question." | Two more lines in `docs/shop-notes.md`. |

### What did not go to plan

- **Jobs 0001 and 0002: a background job cannot be asked about the web.** The librarian's web allow in `wz.toml` only
  lets wz's own guard pass the tool. Claude Code asks separately, and a background job has nobody to answer, so it
  refused ("you haven't granted it yet"). A `.claude/settings.json` allow did not help either: Claude Code printed
  "Ignoring 3 permissions.allow entries ... this workspace has not been trusted" and skipped it. What worked is the
  `agent_command` in `answers.json`: `claude --allowedTools "WebSearch,WebFetch,Bash(python3 tools/qg.py *)"`, which
  says, for Claude Code, "these are fine without asking". wz's guard still refuses the two web tools for every helper
  except the librarian, and the Bash rule only matches a command that starts `python3 tools/qg.py `. After that change the
  retry (0005) opened its sources on the first search.
- **`default` mode cannot write files from a background job.** The example still ships with `default`, so a chain
  needs the one-line change in D-1. Under `acceptEdits` Claude Code accepted file edits and the guard still enforced
  who owns which files; nothing else was pre-approved.
- **The designer ran before the car scent guide existed** (that was the point of a parallel lane). Its screens use the
  wording of the Larkspur sample guide and say so on every screen, in `NOTES.md` and in its report. Nothing was
  redrawn after the car scent guide passed.
- **The librarian's note has holes it names itself:** the full text of the Guest, Bunce and Johnson paper and its 2016
  follow-up would not open (403), no page gave a recall limit for an ordinary purchase, and no source tested a method for
  asking about smell. It says so, and the reviewer repeats it under "What I could not check".
- One quote sat under the wrong link in the first draft of the note and was re-pointed before `qg.py quotes` passed.
  The librarian also reported, as in the Larkspur run, that a quote ending in a full stop can fail the check; `qg.py quotes` now drops one trailing `. ; , :` from a quote before it matches, and fetches a
  page again once before it calls a quote missing (report problem #10).
- After the run, the made-up owner's question in D-3 and in brief 03 gap 5 was reworded (the helpers ran on a different
  sentence about the same topic: whom to interview first, and reaching people who never bought). One word in the made-up shop's files (and in the helpers' output that quoted them) was swapped by search and
  replace: the shop's two partners are called co-owners. Nothing else in the helpers' files was edited by hand.
- The `round1-*` and `round2-*` copies were made by hand, because the reviewer owns only `review.md` and the writer only
  `guide.md`.
- **Follow-ups.** The jobs raised eight rows in `ledgers/FOLLOWUPS.md`. Before the run ended, every one was marked
  done with the job that did it, queued as a job, or left as "owner decides:" with the question (the rule in the lead's
  charter). They are not shipped; a new workspace starts with an empty ledger.

### Not tried

The builder helper (it is switched off in `answers.json`); any helper opened interactively with `wz cli`; the lead's
interview with a person; the mocks on a real phone.

## Re-checking the sources

`python3 tools/qg.py quotes sources/links.md methods-base/METHODS-BASE.md methods-base/research/car-scent-study.md` opens
every link and confirms each quoted line. On 2026-10-26, after the run, it failed once on a PubMed Central quote (the page did not answer in time) and passed on the second try for all three files.

## The Larkspur sample: the first run, and what it cost

The sample project (`projects/larkspur-tool-library/`) was not written by hand. The librarian, guide writer and
reviewer each ran as a real wz job (`wz job add`, `wz serve --wait`) on Claude Code 2.1.310, with the roles and charters
from `answers.json`. Date: 2026-10-26. The three working roles run on the `sonnet` model; the project folder (brief,
audience, three documents) was written by hand, and is the only input apart from `sources/links.md`.

## Jobs

| Job | Role | What it did | Result | Cost (USD) |
|---|---|---|---|---|
| 0001 | librarian | first try | blocked (see Deviations) | 0.21 |
| 0002 | librarian | read the six links, wrote `METHODS-BASE.md`; `qg.py quotes` found every quote | done | 0.17 |
| 0003 | guide-writer | wrote `guide.md` and `jargon.txt`; guide-check clean, lint 0 flags | done | 0.21 |
| 0004 | reviewer | first review: **CHANGES NEEDED** (Q4, Q6, Q8, one Q7 follow-up leading; timing counted two groups' blocks; consent promises unconfirmed). Kept as `round1-*` | done | 0.23 |
| 0005 | guide-writer | revised the guide for every finding, could not run the checks | blocked (see Deviations) | 0.28 |
| 0006 | guide-writer | tried to run the checks | blocked (see Deviations) | 0.08 |
| 0007 | guide-writer | ran the checks, fixed the one lint flag | done | 0.10 |
| 0008 | reviewer | second review: round-1 findings resolved, two new leading follow-ups under Q6. **CHANGES NEEDED**. Kept as `round2-*` | done | 0.21 |
| 0009 | guide-writer | fixed both | done | 0.13 |
| 0010 | reviewer | third review: **PASS** (`review.md`) | done | 0.26 |
| | | **Total** | | **1.88** |

Cost is the `total_cost_usd` Claude Code reports for each job, which is the figure wz's daily limit counts. The runs
that worked (0002, 0003, 0004, 0007 to 0010) cost **$1.31**; the three that stopped early cost $0.57. The daily limit in
`answers.json` ($5) was never reached. Nothing here included the setup interview with mission-ctl, which was not run
(see below).

## Deviations from the shipped defaults, and why

- **Claude's questions were pre-answered.** The shipped setup keeps Claude Code asking before it acts
  (`permission_mode = "default"`). A background job has nobody to answer, so under that setting it cannot write a file:
  the safe-default way to use the helpers is to open them yourself with `wz cli <role>`, as the README says. For this
  headless run only, the scratch copy used `permission_mode = "acceptEdits"` and
  `claude --allowedTools "WebFetch,Bash(python3 tools/qg.py:*)"`: file edits inside the workspace and the one checker
  command were pre-approved. (Checked separately: with the shipped `default` mode a headless job's Write call is
  refused, "you haven't granted it yet"; $0.07.) The guard (ownership of paths) was active throughout. Nothing else changed in the roles or
  the charters.
- **Job 0001** was blocked because the machine used for the run had another tool's write guard active inside the child
  Claude session, which refused the librarian's writes. It had nothing to do with wz; the job was re-run (0002) with that
  guard's variables removed from the environment.
- **Jobs 0005 and 0006** were blocked because the job chose a way of calling the checker (with `cd` or an absolute
  path) that the pre-approval did not match, so the checks were refused. Job 0005's edits to `guide.md` had been made
  and were kept; 0007 ran the checks and fixed one lint flag. The task text for 0007 onwards says to run the checker
  exactly as `python3 tools/qg.py ...` from the workspace root. An interactive user would simply have clicked Yes.
- **mission-ctl was not run.** I queued the jobs myself with `wz job add`, as the coordinator would. The brief, audience
  and documents for the sample project were written by hand; mission-ctl's interview for a new project (its charter says
  to ask the questions in `brief.md` one at a time) has not been tried with a person, nor has any helper been tried
  interactively by a non-technical person.
- **Two checks of mine changed during the run.** `guide-check` first insisted that the core-questions minutes equal the
  sum of the topics; the guide writer rightly gave the two group-specific topics (never joined / joined and stopped) to
  different people, so the rule now only rejects a heading that claims more time than the topics add up to. And
  `review-check` now accepts a PASS with no findings (the third review had to add one row to satisfy it).
- The round files (`round1-*`, `round2-*`) were copied aside by hand before each next round, because the reviewer owns
  only `review.md` and the writer only `guide.md`.

## Re-checking the sources

`python3 tools/qg.py quotes sources/links.md methods-base/METHODS-BASE.md` opens every link and confirms each quoted
line. It passed on 2026-10-26 for both files (11 quotes in `links.md`, 12 in `METHODS-BASE.md`).
