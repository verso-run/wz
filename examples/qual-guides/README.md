# qual-guides: write an interview guide you can run yourself

You have a small project and you want to talk to a handful of people to find out something. You are not a researcher.
This example gives you a team of helpers:

- **the librarian** reads published advice on how to interview people well and keeps a short, plain list of rules, each
  with where it came from. When you ask, it also **searches the web** for new reading and writes you a note about it;
  you decide what the rules are allowed to rest on (the librarian's rules say so; wz itself lets the librarian write the whole methods-base folder);
- **the guide writer** reads your project (what you want to find out, who you will talk to, any documents) and writes a
  discussion guide you can run: what to say, what to ask, what to do if someone goes quiet;
- **the reviewer** checks the guide against those rules and points out questions that steer people, ask two things at
  once, use jargon, can only be answered "yes" or "no", or ask people what they *would* buy instead of what they *did*
  buy. It also asks whether the number of conversations fits the decision. It names the rule it used, and the source;
- **the designer** draws phone-sized pictures (web pages you can open) of a small app that sits beside whoever runs the
  interview, while the guide is still being written. It builds nothing;
- **mission-ctl** is the one you talk to. It helps you describe a project in plain words, writes down what you decided,
  and queues the work for the others. It does not do their work.

A seventh role, **the builder**, is written down but switched off (see "What is in this folder"): it waits until you have
signed off the pictures.

Nothing here is sent anywhere except the librarian's web searches, and nothing runs by itself: you start the work.

## Start here

This page is for someone who has never used a terminal. If a word is new, it is explained where it first appears.

### What it costs

- wz and this example are free.
- The helpers use Claude. With a Claude subscription (Pro or Max) they use your plan's allowance; with an Anthropic
  API account every message costs a little real money.
- The example sets a **daily limit of $5**, but it only limits background jobs. Step 4 below opens each helper
  yourself with `wz cli`, and those windows are not counted or stopped by it: with an API account they cost money as
  you use them. The figures below were measured on background jobs.
- For scale: the car scent sample below (a research note, a second search, six phone pictures, a guide, and three
  reviews with two fix rounds) took twelve helper runs, **$3.23 in total** by Claude's own cost figure ($2.97 of it for
  the runs that worked, the rest for two attempts that stopped at the first web search), in about eighteen minutes. See
  [RUN-LOG.md](RUN-LOG.md).

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

Step 3. List what arrived (names only) and tell me in two lines what is in the folder: sources, methods-base (with a research note), briefs, app (phone pictures), tools, and projects (with two finished samples, car-scent-study and larkspur-tool-library).

Step 4. Ask me what the most I want the helpers to spend in one day is. Say honestly what the figure covers: it limits the work wz starts for me; my own chats with Claude are not counted. Suggest 5 dollars. Take my number exactly; if I say I do not know, use 5. Write it into answers.json in that folder, in both places where it says 5 (budget_usd and daily_usd). Show me the file in a few plain lines, ask "Shall I go ahead?", and only after my yes run, from inside that folder:
  wz init --simple --answers answers.json --dir .
It refuses to go on if the limit is missing or Claude Code is set to skip questions. If it refuses, tell me why in plain words and stop.

Step 5. Tell me, in plain words and short: the folder is $HOME/wz-work/qual-guides; the finished sample guide is projects/car-scent-study/guide.md and its review is review.md; to use the helpers I open a Terminal, type `cd ~/wz-work/qual-guides`, then `wz cli librarian`, `wz cli mission-ctl`, `wz cli guide-writer`, `wz cli reviewer` or `wz cli designer`; nothing runs unless a window with Claude is open in front of me; and how to stop everything (type /exit in each Claude window, or run `wz park` and the helper's name; if I only close the Terminal, a helper stays open in the background, waiting for me). Then ask whether I would like to read the sample guide together first.
```
<!-- /EXAMPLE-PROMPT -->

It asks your yes before it downloads and before it writes anything. Pasting it twice is safe.

Honest note: this prompt fetches the current state of the `main` branch, not a fixed release, so what you get can
change. It only writes text files into one folder; it runs nothing from them while setting up.

### Step 3. Read the sample first

Open the folder `wz-work/qual-guides/projects/car-scent-study` (Finder on a Mac, or ask Claude to show you a file).
Tumbledown Scent Co. is a **made-up** two-person shop that sells car air fresheners and wants to know why most customers
buy once. Read in this order:

1. `brief.md` and `audience.md`: what the shop wants to find out, and who it can talk to. Plain answers.
2. `docs/draft-questions.md`: six questions the owners wrote themselves. Several steer the person or ask them to guess
   what they would buy ("Would you pay £4 a month for a refill subscription?"). This is what the helpers have to fix.
3. `../../methods-base/research/car-scent-study.md`: what the librarian found when asked for new reading, with the
   links, the licences as the pages state them, and the places it could not open.
4. `guide.md`: the finished discussion guide. Part 7 is the one-page card to read before you start.
5. `review.md`: the reviewer's verdict on the finished guide. Earlier rounds are kept as `round1-*` and `round2-*`: the
   first review sent the guide back with eight findings, the second with two.
6. `../../app/mocks/index.html`: open it in a browser. Six phone-sized pictures of the interview companion. Their words
   come from the other sample, because the designer worked while the guide was still waiting.

The older sample, `projects/larkspur-tool-library`, is a made-up tool-lending shelf with three rounds of the same loop.

### Step 4. Do it for your own project

Open **Terminal**: on a Mac press Command and Space, type `Terminal`, press Return. Then type these, pressing Return
after each:

```sh
cd ~/wz-work/qual-guides
wz cli mission-ctl
```

Claude opens. The first time, it asks whether you trust this folder: say yes. Then:

| Open | Say to it | What you get |
|---|---|---|
| `wz cli mission-ctl` | *I want to make a guide for a new project called corner-shop.* | It asks you a few questions, one at a time, and writes your answers in `projects/corner-shop/` |
| `wz cli librarian` | *Read what is new in sources and update the methods base.* | `methods-base/METHODS-BASE.md` (once, and again whenever you add reading to `sources/`) |
| `wz cli guide-writer` | *Write the guide for projects/corner-shop.* | `projects/corner-shop/guide.md` |
| `wz cli reviewer` | *Review the guide for projects/corner-shop.* | `projects/corner-shop/review.md`, ending in PASS or CHANGES NEEDED |

If the verdict is CHANGES NEEDED, open the guide writer again and say *"Fix everything in
projects/corner-shop/review.md"*, then the reviewer again. In the car scent sample it took three rounds.

Claude asks before it writes a file or runs most commands. Read what it wants and say yes. (Two things are pre-approved
in this example, see Step 5: the web tools, which only the librarian is let use, and the checker `python3 tools/qg.py`.)
When you are done, type `/exit`.
Each helper keeps its conversation: the next `wz cli reviewer` carries on where you stopped, and `wz roll reviewer`
starts a fresh one. If your computer has tmux, closing the window instead leaves the helper waiting quietly in the
background (it cannot act without asking you); `wz park reviewer` shuts it. See "Sessions" in the main README.

To add reading, drop PDFs or web addresses into `sources/` (see `sources/README.md`) and open the librarian again. To
have the librarian *find* new reading, write it a brief (next section). Only the librarian may use the web
(`web = ["WebSearch", "WebFetch"]` in its `wz.toml` entry); wz's guard refuses both tools to every other helper.

### Step 5. Let the helpers work while you do something else (the chain)

Opening each helper yourself is the careful way. The other way is to ask `mission-ctl` to **queue the whole chain** and
let wz run the helpers in the background: search the web, update the methods base, write the guide, review it, and draw
the pictures beside all that. You stay in charge at two **gates**, the places where the next step waits for you.

```
 librarian: research note (brief 01) ──▶ GATE: you pick the sources ──▶ librarian: methods base ──▶ librarian: second search (brief 03)
                                                                                                           │
                                          GATE: you say audience.md is right ◀──────────────────────────────┘
                                                      │
                                                      ▼
                                       guide writer ──▶ reviewer ──▶ (fix and review again until PASS)
 designer: phone pictures (brief 02) ───────────── runs beside all of this and touches none of its files
```

What to know before you say "go":

1. **Background helpers cannot ask you anything,** so wz runs them in Claude Code's `auto` mode (`job_permission_mode` in
   `wz.toml`, the default): they can write files without stopping to ask, and wz's guard still keeps each helper to its
   own files. You change nothing to run the chain. The windows you open yourself with `wz cli` stay in the ask-first
   mode (`permission_mode = "default"`), so Step 4's "Claude asks before it writes a file" stays true. wz prints a
   line at the start of each job saying it is in `auto` and that wz has not checked where `auto` still stops. To make
   jobs stop and ask, set `job_permission_mode = "default"` under `[agent]`; they then cannot write. If you change
   either setting, tell `mission-ctl` and it writes it down. (It may not change `wz.toml` itself.)
2. **Nothing starts by itself.** There are no timers. `mission-ctl` starts the work with `wz serve` and starts it again
   after each gate and each finished job, or you can leave `wz serve --follow` running in a terminal and it carries a chain on
   to its next gate. When a window says "waiting for you", that is a gate.
3. **The web is allowed to the librarian only,** and Claude Code is told once (the `agent_command` in `answers.json`) that
   it need not ask about the two web tools or about the one checker, `python3 tools/qg.py`. Without that, a background
   librarian is stopped at its first search. This setting also applies to the windows you open yourself.
4. Say to `mission-ctl`: *Run the whole chain for my project: search for reading first, and draw the pictures too.* It
   writes the briefs, queues the jobs (see the briefs in `briefs/` for the shape), and tells you each gate when it
   arrives and what to say to pass it.

The `mission-ctl` rules that keep this honest are in `answers.json`: it reads the mode from the file rather than telling
you from memory; it holds a step with `wz job hold <id> --why "..."` until you pass the gate and releases it with `wz job
release <id>`; it changes a queued job's done-check when the brief changes; and it closes or queues every follow-up
a report raises, the same day.

### Owner tips (the things that worked, in plain words)

Seven habits from the person who first pushed this example this far. None needs code.

1. **Ask "should a helper do this?"** When `mission-ctl` starts searching the web or writing the guide itself, stop it and
   ask. Either a helper owns the job and gets it, or nobody does, and the right answer is a proposed new helper for you
   to approve. "Find more reading" belonged to nobody until the librarian was given a research rule.
2. **Ask the lead to read wz's own files before it explains a setting.** *"Read wz.toml and tell me what the permission
   mode is."* A claim about the setup should point at a line in the file, not at memory of the README.
3. **Write a mode choice down as a decision.** When you change `permission_mode` or `job_permission_mode`, say why in your words and have
   `mission-ctl` put it in `DECISIONS.md` (D-1 in the sample). A quiet setting change becomes a choice you made.
4. **Use gates as holds.** *"Hold the guide until I have read the audience answers."* A held job waits; you release it
   when you are ready. You stop carrying messages between windows and still decide at the points that matter.
5. **Fold a question into a brief that has not run yet.** Briefs are files, and a queued job reads the latest. Say your
   new question to `mission-ctl` before it starts the job and ask it to add it to the brief (D-3 in the sample); it then
   also has to update the job's done-check so the two agree.
6. **Run a pictures-first lane beside the writing.** The designer needs no answers from the guide to draw the screens, and
   its pictures make a good thing to comment on while you wait. The builder stays switched off until you have signed the
   pictures off in `DECISIONS.md`.
7. **Ask for the record as you go.** *"Write that down."* Decisions in your own words, each with a number, and the
   follow-ups closed or queued, are what lets you pick the work up a week later.

(The sample's first owner also ran small scripts for `mission-ctl` to change the helpers' rules, and had the librarian
given a research rule by hand. This example ships both already, so those two habits are not needed here.)

## What is in this folder

| Path | What it is |
|---|---|
| `answers.json` | the setup answers `wz init` turns into a workspace: five helpers and their jobs in plain words, the $5 limit, Claude asking before it acts in its windows and jobs running in `auto`, no timers. A `roles_later` block holds the **builder**, switched off: move it into `roles` only after you have signed off the pictures. |
| `sources/links.md` | twelve freely available pieces of reading, each opened and read on 2026-10-26, with the quoted line and the address. Seven to twelve are the ones the made-up owner kept from the librarian's first note. |
| `methods-base/METHODS-BASE.md` | the librarian's rules, built from those twelve, every rule with its source and a quoted line |
| `methods-base/research/car-scent-study.md` | the librarian's research note for the car scent study: its two searches, the links, the licences as stated, checked quotes, what it could not open |
| `briefs/` | the three task sheets of the car scent run, each with the helper's filled-in Report |
| `projects/_template/` | what a new project starts from (`brief.md`, `audience.md`, and the layouts the writer and reviewer follow) |
| `projects/car-scent-study/` | the worked chain sample: made-up shop, brief, audience, documents, guide, review, and the two earlier rounds |
| `projects/larkspur-tool-library/` | the first worked sample: a made-up tool-lending shelf, brief, audience, documents, guide, review, and the earlier rounds |
| `app/mocks/` | the designer's six phone pictures, an index and its notes for you |
| `tools/qg.py` | the few checks that need no judgement (below) |
| `RUN-LOG.md` | how the samples were made, what each job cost, and what went wrong |

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
| M7 | [Michael Lynch, review of “The Mom Test”](https://mtlynch.io/book-reports/the-mom-test/) | CC BY 4.0 | past behaviour |
| M8 | [Jakob Nielsen, “Interviewing Users”, Nielsen Norman Group](https://www.nngroup.com/articles/interviewing-users/) | all rights reserved (link and short quote only) | past behaviour |
| M9 | [Guest, Bunce and Johnson, “How Many Interviews Are Enough?” (abstract page)](https://citedrive.com/en/discovery/how-many-interviews-are-enough/) | none stated | sample size |
| M10 | [Sauro and Lewis, “Six Ways to Improve Participant Recall”, MeasuringU](https://measuringu.com/six-ways-to-improve-recall/) | none stated | past behaviour, timing |
| M11 | [Angus Chen, NPR (via KPBS), on putting smells into words](https://www.kpbs.org/news/2018/jan/18/that-smells-like-um-i-cant-think-of-a-word-for-it) | copyright NPR (link and short quote only) | plain words |
| M12 | [A. Bhattacherjee, “Biases in Survey Research”](https://socialsci.libretexts.org/Bookshelves/Social_Work_and_Human_Services/Social_Science_Research_-_Principles_Methods_and_Practices_%28Bhattacherjee%29/09:_Survey_Research/9.04:_Biases_in_Survey_Research) | CC BY-SA 3.0 | sample size |

This is a small base: twelve short web pages, not a literature review. It covers writing neutral questions, asking about what
people did rather than what they would do, and a first look at how many conversations are enough. It says nothing
firm on how far back people remember an ordinary purchase or how to ask about smell, and the research note says so. It
says nothing on analysis, or children and other groups who need special care; the reviewer writes “not covered by the
methods base” rather than inventing support. Add your own reading to `sources/`.

## What the checks do, and do not do

`python3 tools/qg.py` (plain Python, nothing to install) does the parts that need no judgement; the helpers run it
and then use their own. The two modes that write refuse unless they run in the right role's window (wz tells each window
who it is), and the checker only works on its own folder. Run from a plain Terminal they are refused too:

| Command | Does |
|---|---|
| `new-project <name>` | makes `projects/<name>/` from the template (only the coordinator, `mission-ctl`, may run it) |
| `sources [--update]` | lists what is in `sources/` and what is new or changed since last time; `--update` writes the index and only the librarian may run it |
| `quotes <file>` | opens each link in the file and confirms every quoted line is really on the page |
| `lint <guide>` | flags questions that start with is/do/would (yes/no), carry a push or a loaded word (leading), join two questions with and/or (double-barrelled), or use jargon (a built-in list plus the project's `jargon.txt`) |
| `guide-check <guide>` | every part is there, minutes are written and add up to the total, every question has a follow-up, the consent script mentions recording, stopping, privacy and no wrong answers |
| `review-check <review> <guide>` | the review quotes questions that are really in the guide, names methods sources that really are in the methods base, and mentions every question the lint flagged |

The lint reads word patterns, not meaning. In both samples it found nothing in the first draft, and the reviewer
(reading as a person would) still found questions that assumed too much. The other way round, it can flag a
sentence that is fine. It is a second pair of eyes, not a verdict. `quotes` needs the internet, and a page that fails
once sometimes passes the second time.

## What this is not

- It does not replace ethics approval. For research at a university, school or health service, ask their ethics
  contact before you recruit anyone. The consent script is for ordinary small-organisation conversations.
- It does not analyse interviews. It stops at the guide.
- The reviewer is a language model checking against twelve short sources. It is stricter about some things than others,
  and can be wrong. The final say is yours.
- wz is **not the quickest way to change a small app** by trial and error: one ordinary Claude chat is better for
  "move that button, now this". It suits work with several parts at once, a brief written before the work, a second
  helper checking the first, and your sign-off. The builder helper is not tried, and the pictures are not an app.
- The librarian's searches find what a search finds. Each source is a link and a short quote, not a verdict on the
  study; the note says where it only read an abstract.

## Tests

From the wz folder: `python -m pytest tests/test_qual_guides.py -q` (no Claude account needed, nothing is spent). One
test opens the real pages to re-check the research note's quotes: `WZ_TEST_NETWORK=1 python -m pytest tests/test_qual_guides.py -q`.
