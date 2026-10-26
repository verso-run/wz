# Start here

This page is for anyone who wants to use wz and does not write code. No special words are needed.

## What wz does

wz helps you get things done with Claude, the AI assistant. You tell it what you want in a plain sentence, such as
"draft a letter to the council about the fence". wz keeps a small team of Claude helpers organised, gives each one its
own area of your files, writes down what was decided and what was done, and **asks you before anything is sent, paid
or published**. Each morning it can leave a short summary of what got done.

## What it costs

- **wz is free.** You pay for nothing to install it.
- **Claude is what costs.** wz uses Claude Code. You need a Claude account to sign in with:
  - With a **Claude subscription (Pro or Max)**, wz uses your plan's allowance. There is no extra bill, but if
    you use a lot, your plan can run out for a while.
  - With an **Anthropic API account**, you pay for each use, so every message costs a little real money.
- **You choose a daily spending limit** while you set up wz (it suggests a low one, $5). It only limits work wz
  runs in the background, which the simple setup never starts by itself. It does **not** limit Claude windows you
  open yourself, including `wz cli` helpers: with an API account those cost money as you use them, so watch
  Claude's own usage page.

## How to start (the easy way: let Claude do it)

1. Install Claude Code if you do not have it, and sign in. The steps are at https://code.claude.com/docs/en/quickstart
   (on a Mac, open the app called **Terminal**, paste the one line shown there, press Return, then type `claude`).
2. In Claude, paste **everything in the grey box below** and press Return.
3. Claude installs wz by itself, telling you what it is doing in plain words. It asks your yes before anything that
   changes a setting, then asks you a few short questions (including your daily limit). Say yes to its
   "may I run this?" boxes while you read them; that is Claude Code asking before it acts.

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

Step 8. When the setup is written, tell me in three or four lines: where my files are, how to talk to wz again, how to stop everything (close the window; nothing runs by itself), and how to uninstall. Then ask what I would like done first.
```
<!-- /PROMPT -->

Pasting it twice is safe: it checks what is already there and says so.

### Or: one line in Terminal

If you would rather not use Claude for this, open **Terminal** (on a Mac: press Command and Space, type
`Terminal`, press Return) and paste this one line:

```sh
mkdir -p "$HOME/.cache/wz-install" && curl -fsSL https://raw.githubusercontent.com/verso-run/wz/v0.1.1/install.sh -o "$HOME/.cache/wz-install/install.sh" && sh "$HOME/.cache/wz-install/install.sh"
```

It does the same things, asks before it changes anything, then opens Claude. The first time, Claude shows a web
page for signing in to your Claude account. This is the one step that cannot be done for you.

## How wz starts: safe

- **Claude asks before it acts.** You see each thing it wants to do and say yes or no.
- **Nothing runs by itself.** There are no timers and no work in the background. wz only works while a window with
  Claude is open in front of you. You can ask for automatic daily work later, and wz explains it first.
- **Your limit is set before anything is written.**

## How to stop everything

Close the Terminal window (or press Control and C twice). Nothing is left running.

If you ever turned automatic daily work on, you can turn it off with this line (in the folder `wz-work`):

```sh
wz install timers --uninstall
```

## How to uninstall

Paste this one line in Terminal. It removes what the installer added (wz, the Python helper it fetched, and Claude Code if
the installer put it there) and the three lines in your shell settings. It keeps **your own files**: the folder
`wz-work` and Claude's sign-in and settings (`~/.claude`).

```sh
sh ~/.local/share/wz-install/uninstall.sh
```

If that file is missing, use the same thing from the internet:

```sh
curl -fsSL https://raw.githubusercontent.com/verso-run/wz/v0.1.1/uninstall.sh | sh
```

To delete your own files as well, delete the `wz-work` folder yourself afterwards. To remove Claude's sign-in too,
follow the last section of https://code.claude.com/docs/en/setup ("Remove configuration files").

## If something goes wrong

- The installer never uses the administrator password. If it says it needs something that has to be installed by the
  person who looks after your computer, it stops and tells you in plain words what is missing. Nothing is half-done.
- Windows: install **WSL** (a Linux inside Windows), open it, and use the same steps there.
- More detail for technical readers is in [README.md](README.md).
