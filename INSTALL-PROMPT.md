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

Step 1. Fetch the installer, pinned to the release v0.2.0, and check it has not been changed:
  mkdir -p "$HOME/.cache/wz-install" && curl -fsSL https://raw.githubusercontent.com/verso-run/wz/v0.2.0/install.sh -o "$HOME/.cache/wz-install/install.sh"
Then compute its SHA-256 (`shasum -a 256` on a Mac, `sha256sum` on Linux). It must be exactly
  0e59faff023311f72de8b8b38f5180a117109fdf35d456f6a6aaf0ba80ad3d28
If it is not exactly that, stop, tell me the installer does not match, and do not run it.

Step 2. Look at this computer: run `sh "$HOME/.cache/wz-install/install.sh" check`. Tell me in plain words what it found (Mac or Linux, what is already installed). If it stops with a message, tell me that message in your own plain words and stop there.

Step 3. Tell me the plan and ask for my yes. The plan: add three things to my home folder only, skipping any that are already there: a small Python helper called uv (it also fetches a Python for wz if this computer has none), wz itself, and Claude Code if it is somehow missing. Say that installing costs nothing, that nothing is changed outside my home folder, and that I can remove all of it later with one line (see the Start-here page).

Step 4. After my yes, run `sh "$HOME/.cache/wz-install/install.sh" --yes uv wz claude verify workspace`. Show me the result in plain words. The `verify` part makes a throwaway test project, shows that wz starts, and checks that it is in the ask-before-acting mode. If anything fails, explain what failed, do not retry in a loop, and stop.

Step 5. One more change needs its own yes: so that `wz` works in new Terminal windows, the installer may add three marked lines to my shell settings file. Ask me. Only after a yes, run `sh "$HOME/.cache/wz-install/install.sh" --yes path`. If I say no, tell me the line to type instead: export PATH="$HOME/.local/bin:$PATH"

Step 6. Before the setup questions, say to me out loud, in plain words, what wz starts with: Claude Code keeps asking before it acts in the windows I open; work I later put on a helper's list runs in the background in Claude Code's auto mode, where it can write files without asking, inside wz's guard; nothing runs by itself, with no timers until I ask for them; and I choose a daily spending limit in the next step.

Step 7. Open the setup conversation. First look for `$HOME/wz-work/wz.toml`. If it already exists, wz was set up before: tell me so, show me the daily limit it holds, and ask whether I want to start the setup over; if I do not, skip to Step 8 and change nothing. Otherwise run `wz init --simple --print-charter --dir "$HOME/wz-work"`. It prints the path of a file with your instructions for the setup conversation. Read that file and follow it exactly from now on: it asks me a few short questions, one at a time, including the daily limit (suggest a low one, such as 5 dollars). Do not skip its questions and do not answer them for me.

Step 8. When the setup is written, tell me in three or four lines: where my files are, how to talk to wz again, how to stop everything (type /exit in each Claude window, or run `wz park <helper>`; if you only close the Terminal, a helper stays open in the background, waiting for you; nothing starts work by itself), and how to uninstall. Then ask what I would like done first.
