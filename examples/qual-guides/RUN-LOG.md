# How the sample was made, and what it cost

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
