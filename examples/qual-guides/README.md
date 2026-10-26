# qual-guides: write an interview guide you can run yourself

You have a small project and you want to talk to a handful of people to find out something. You are not a researcher.
This example gives you a team of three helpers:

- **the librarian** reads published advice on how to interview people well and keeps a short, plain list of rules,
  each with where it came from;
- **the guide writer** reads your project (what you want to find out, who you will talk to, any documents) and writes a
  discussion guide you can run: what to say, what to ask, what to do if someone goes quiet;
- **the reviewer** checks the guide against those rules and points out questions that steer people, ask two things at
  once, use jargon, or can only be answered "yes" or "no". It names the rule it used, and the source.

A fourth helper, **mission-ctl**, is the one you talk to to describe a project. Nothing here is sent anywhere, and
nothing runs by itself.

## Start here

This page is for someone who has never used a terminal. If a word is new, it is explained where it first appears.

### What it costs

- wz and this example are free.
- The helpers use Claude. With a Claude subscription (Pro or Max) they use your plan's allowance; with an Anthropic
  API account every message costs a little real money.
- The example sets a **daily limit of $5**, but it only limits background jobs. Step 4 below opens each helper
  yourself with `wz cli`, and those windows are not counted or stopped by it: with an API account they cost money as
  you use them. The $1.88 below was measured on background jobs.
- For scale: producing the sample guide below took ten helper runs, **$1.88 in total** by Claude's own cost figure
  ($1.31 of it for the runs that worked, the rest for three attempts that stopped early). See [RUN-LOG.md](RUN-LOG.md).

### Step 1. Get wz and Claude Code

Do the install first, on the page called **Install**, at the top of the main [README](../../README.md#install). It
is a short paste into Claude Code and takes about ten minutes. When it says wz is installed, come back here.

### Step 2. Put this example on your computer

Open Claude Code (the same way you did for the install), and paste **everything in the grey box** below. Press Return.

<!-- EXAMPLE-PROMPT -->
```text
I would like you to set up a ready-made wz example called qual-guides on this computer, and then help me use it. I am not a programmer. Please explain each step in plain words, keep it short, and do not use jargon.

What it is: a small team of helpers that turns a project's description into an interview guide, and checks it. It is free. The Claude you are running on is what costs anything.

Rules you must follow all the way through:
1. Ask me before anything that costs money or changes a setting of mine, and wait for my "yes". Do not guess my answer.
2. Never use sudo and never ask me for a password. If a step cannot be done without them, stop and say in plain words what is missing.
3. Work only inside my home folder, and only inside the folder named in Step 2. Leave everything else as it is.
4. Never switch Claude Code to a mode that skips its questions. Never turn on timers or anything that runs by itself.
5. Never print or copy my passwords, keys, tokens or environment variables.
6. This must be safe to run twice: check what is already there first, and say so if a step is already done.
7. In every command, first run `export PATH="$HOME/.local/bin:$PATH"`, because a fresh session may not look there yet.

Step 1. Check wz is installed: run `wz --version`. If it is not found, stop and tell me to paste the wz install prompt first (it is in the file INSTALL-PROMPT.md at https://github.com/verso-run/wz). Do not install wz yourself.

Step 2. Tell me this downloads one small folder of text files from github.com/verso-run/wz and nothing else, then ask for my yes. If the folder "$HOME/wz-work/qual-guides" already contains a file called wz.toml, tell me it is already set up, change nothing, and skip to Step 5. Otherwise run:
  mkdir -p "$HOME/wz-work/qual-guides" && curl -fsSL https://codeload.github.com/verso-run/wz/tar.gz/refs/heads/main | tar -xz --strip-components=3 -C "$HOME/wz-work/qual-guides" wz-main/examples/qual-guides

Step 3. List what arrived (names only) and tell me in two lines what is in the folder: sources, methods-base, projects (with a finished sample project, larkspur-tool-library), tools.

Step 4. Ask me what the most I want the helpers to spend in one day is. Say honestly what the figure covers: it limits the work wz starts for me; my own chats with Claude are not counted. Suggest 5 dollars. Take my number exactly; if I say I do not know, use 5. Write it into answers.json in that folder, in both places where it says 5 (budget_usd and daily_usd). Show me the file in a few plain lines, ask "Shall I go ahead?", and only after my yes run, from inside that folder:
  wz init --simple --answers answers.json --dir .
It refuses to go on if the limit is missing or Claude Code is set to skip questions. If it refuses, tell me why in plain words and stop.

Step 5. Tell me, in plain words and short: the folder is $HOME/wz-work/qual-guides; the finished sample guide is projects/larkspur-tool-library/guide.md and its review is review.md; to use the helpers I open a Terminal, type `cd ~/wz-work/qual-guides`, then `wz cli librarian`, `wz cli mission-ctl`, `wz cli guide-writer` or `wz cli reviewer`; nothing runs unless a window with Claude is open in front of me; and how to stop everything (close the window). Then ask whether I would like to read the sample guide together first.
```
<!-- /EXAMPLE-PROMPT -->

It asks your yes before it downloads and before it writes anything. Pasting it twice is safe.

Honest note: this prompt fetches the current state of the `main` branch, not a fixed release, so what you get can
change. It only writes text files into one folder; it runs nothing from them while setting up.

### Step 3. Read the sample first

Open the folder `wz-work/qual-guides/projects/larkspur-tool-library` (Finder on a Mac, or ask Claude to show you a
file). Larkspur Tool Library is a **made-up** volunteer lending shelf. Read in this order:

1. `brief.md` and `audience.md`: what the committee wanted to find out, and who they could talk to. Plain answers.
2. `docs/committee-notes.md`: five questions the committee wrote themselves. Several steer the person, ask two things
   at once or use jargon (“inventory system”, “onboarding”). This is what the helpers have to fix.
3. `guide.md`: the finished discussion guide. Part 7 is the one-page card to read before you start.
4. `review.md`: the reviewer's verdict on the finished guide. Earlier rounds are kept as `round1-*` and `round2-*`:
   the first review sent the guide back with four questions flagged and timing that did not add up.

### Step 4. Do it for your own project

Open **Terminal**: on a Mac press Command and Space, type `Terminal`, press Return. Then type these, pressing Return
after each:

```sh
cd ~/wz-work/qual-guides
wz cli librarian
```

Claude opens. The first time, it asks whether you trust this folder: say yes. Then:

| Open | Say to it | What you get |
|---|---|---|
| `wz cli librarian` | *Read what is new in sources and update the methods base.* | `methods-base/METHODS-BASE.md` (do this once, and again whenever you add reading to `sources/`) |
| `wz cli mission-ctl` | *I want to make a guide for a new project called corner-shop.* | It asks you a few questions, one at a time, and writes your answers in `projects/corner-shop/` |
| `wz cli guide-writer` | *Write the guide for projects/corner-shop.* | `projects/corner-shop/guide.md` |
| `wz cli reviewer` | *Review the guide for projects/corner-shop.* | `projects/corner-shop/review.md`, ending in PASS or CHANGES NEEDED |

If the verdict is CHANGES NEEDED, open the guide writer again and say *"Fix everything in
projects/corner-shop/review.md"*, then the reviewer again. In the sample it took three rounds.

Claude asks before it writes a file or runs a check. Read what it wants and say yes. Close the window when you are done
(press Control and C twice, or type `/exit`). Nothing is left running.

To add reading, drop PDFs or web addresses into `sources/` (see `sources/README.md`) and open the librarian again.

## What is in this folder

| Path | What it is |
|---|---|
| `answers.json` | the setup answers `wz init` turns into a workspace: four helpers, their jobs in plain words, the $5 limit, Claude asking before it acts, no timers |
| `sources/links.md` | six freely available pieces of interviewing advice, each opened and read on 2026-10-26, with the quoted line and the address |
| `methods-base/METHODS-BASE.md` | the librarian's rules, built from those six, every rule with its source and a quoted line |
| `projects/_template/` | what a new project starts from (`brief.md`, `audience.md`, and the layouts the writer and reviewer follow) |
| `projects/larkspur-tool-library/` | the worked sample: made-up organisation, brief, audience, documents, guide, review, and the earlier rounds |
| `tools/qg.py` | the few checks that need no judgement (below) |
| `RUN-LOG.md` | how the sample was produced, and what it cost |

## The sources, and what is borrowed from them

No source text is bundled beyond short quotes (each under 40 words, with its link and the licence the page states); the quoted words stay their authors'. Every quote was read on its page.

| | Source | Licence, as the page states it | Used for |
|---|---|---|---|
| M1 | [Ontario Digital Service, “User interviews”](https://www.ontario.ca/page/user-interviews) | Creative Commons Attribution 4.0 | leading questions, probes, timing |
| M2 | [K. A. Stofer, UF/IFAS Extension, “Preparing for One-on-One Qualitative Interviews”](https://edis.ifas.ufl.edu/publication/WC338) | none stated (free to read) | consent, order, probes, closing |
| M3 | [Wikipedia, “Leading question”](https://en.wikipedia.org/wiki/Leading_question) | CC BY-SA 4.0 | leading |
| M4 | [Wikipedia, “Double-barreled question”](https://en.wikipedia.org/wiki/Double-barreled_question) | CC BY-SA 4.0 | double-barrelled |
| M5 | [Wikipedia, “Closed-ended question”](https://en.wikipedia.org/wiki/Closed-ended_question) | CC BY-SA 4.0 | yes/no |
| M6 | [Digital.gov, “Principles of plain language”](https://digital.gov/guides/plain-language/principles/) | none stated (US government site) | plain words |

This is a small base: six short web pages, not a literature review. It covers writing neutral questions and running a
simple interview. It says nothing on sampling, analysis, or children and other groups who need special care; the
reviewer writes “not covered by the methods base” rather than inventing support. Add your own reading to `sources/`.

## What the checks do, and do not do

`python3 tools/qg.py` (plain Python, nothing to install) does the parts that need no judgement; the helpers run it
and then use their own:

| Command | Does |
|---|---|
| `new-project <name>` | makes `projects/<name>/` from the template |
| `sources [--update]` | lists what is in `sources/` and what is new or changed since last time |
| `quotes <file>` | opens each link in the file and confirms every quoted line is really on the page |
| `lint <guide>` | flags questions that start with is/do/would (yes/no), carry a push or a loaded word (leading), join two questions with and/or (double-barrelled), or use jargon (a built-in list plus the project's `jargon.txt`) |
| `guide-check <guide>` | every part is there, minutes are written and add up to the total, every question has a follow-up, the consent script mentions recording, stopping, privacy and no wrong answers |
| `review-check <review> <guide>` | the review quotes questions that are really in the guide, names methods sources that really are in the methods base, and mentions every question the lint flagged |

The lint reads word patterns, not meaning. In the sample, it found nothing in the first draft, and the reviewer
(reading as a person would) still found four questions that assumed too much. The other way round, it can flag a
sentence that is fine. It is a second pair of eyes, not a verdict.

## What this is not

- It does not replace ethics approval. For research at a university, school or health service, ask their ethics
  contact before you recruit anyone. The consent script is for ordinary small-organisation conversations.
- It does not analyse interviews. It stops at the guide.
- The reviewer is a language model checking against six short sources. It is stricter about some things than others,
  and can be wrong. The final say is yours.

## Tests

From the wz folder: `python -m pytest tests/test_qual_guides.py -q` (no Claude account needed, nothing is spent).
