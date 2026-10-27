# wz 0.2.0

This release is about seeing your helpers at a glance. Each helper's window changes colour with what it is doing, one
terminal can show them all as tabs, and `wz doctor` tells you in plain words whether everything is set up and what to type
if it is not.

If you installed 0.1.2, run the install prompt again. It checks what is already there and changes only what is new. A helper
that is already open keeps the settings it started with, so run `wz cli HELPER --restart` for each one you want colours on
(its conversation is kept).

## Colours: who is working, who is asking, who is done

- A helper's tmux window turns **amber** while Claude works on your message, **red** when it asks you something (a question,
  a plan to approve, a permission), and **green** when it has stopped and waits for you. When Claude ends, the colour goes
  and your own tmux theme is back.
- `wz list` shows the same state in a `light` column.
- It runs from Claude Code's own hooks. There is no background program. A hook that finds the colour already right does
  nothing and starts nothing, so it adds a few milliseconds to a message or a tool call.
- A background job never colours a helper's window.
- Two limits: if you press Esc on a permission question, the window stays red until your next message; and while a colour
  shows it replaces your theme's colours for that window, including the colours of the window you are in (underlined, so
  you can still tell it apart).

## The hub: one terminal, a tab per helper

- `wz hub` opens one terminal with a tab for every helper that is open (the lead first, then the order of `wz.toml`, at most
  nine). `Ctrl-b` and the tab's number jumps to it, and the colours show on the tabs.
- The tabs are the helpers' own windows, not copies and not a tmux inside a tmux, so there is one prefix key. Close the
  terminal and every helper keeps running; `wz hub` brings the same tabs back in a few milliseconds.
- `wz hub hide HELPER` and `wz hub show HELPER` choose the tabs, `wz hub kill` closes the hub, and a second `wz hub` in
  another terminal is a second view with its own current tab. Starting, restarting, rolling or parking a helper updates a
  hub that is open. `wz park` now closes the helper's window, so its tab goes and Claude stops.
- It is safe to type `wz hub` inside tmux: it switches your terminal to the hub instead of nesting one.
- `.wz/hub.log` has one line for every build, reattach, hide, show, kill and ended attach.

## `wz doctor`

`wz doctor` checks tmux and its version (3.0 or newer), that Claude Code is found and signed in, that the workspace and the
list of workspaces can be read, that the hook settings are in place and current, that no helper's charter has drifted from
`wz.toml`, that no colour is left recorded for a helper that is gone, and which permission modes windows and background jobs use. Each problem
prints its one-line fix. It changes nothing, reads no password or key (it only asks `claude auth status` for yes or no), and
exits 1 when something is a problem so a script can use it. It works before a workspace exists, for the checks that need
none.

## Housekeeping

- Every tmux call goes through one file, `wz/mux.py`, which also counts them, so a test can prove that a hook started none.
- The hub, the colours and `wz doctor` were run against tmux 3.4 (Linux) and 3.5a. 3.0 is the oldest `wz doctor` accepts; 3.0a
  and 3.1c have not been run for this release.
