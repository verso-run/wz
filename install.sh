#!/bin/sh
# wz simple installer. Installs, for you only (no sudo, no Homebrew):
#   uv (a small Python installer), a Python for wz if you have none, wz itself, and Claude Code.
# It writes a list of everything it added to ~/.local/share/wz-install/manifest, so uninstall.sh can remove exactly that.
#
#   sh install.sh [STEP...] [--yes] [--no-claude] [--no-open] [--dir FOLDER]
# Steps (default: all, in this order): check uv wz claude path verify workspace open
# Safe to run twice. Environment: WZ_REF (release tag), WZ_SRC (folder, file or URL to install wz from instead).
set -eu

WZ_REF="${WZ_REF:-v0.1.1}"
WZ_SRC="${WZ_SRC:-https://github.com/verso-run/wz/archive/refs/tags/$WZ_REF.tar.gz}"
UV_VERSION="${UV_VERSION:-0.11.7}"
CLAUDE_CHANNEL="${CLAUDE_CHANNEL:-stable}"
BIN="$HOME/.local/bin"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/wz-install"
MANIFEST="$DATA/manifest"
WORKDIR="$HOME/wz-work"
YES=0; NOCLAUDE=0; NOOPEN=0; STEPS=""

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
stop() { printf '\nI have stopped here, and nothing is half-done.\n%s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --no-claude) NOCLAUDE=1 ;;
    --no-open) NOOPEN=1 ;;
    --dir) shift; WORKDIR="$1" ;;
    check|uv|wz|claude|path|verify|workspace|open) STEPS="$STEPS $1" ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) stop "I do not know the option '$1'." ;;
  esac
  shift
done
[ -n "$STEPS" ] || STEPS="check uv wz claude path verify workspace open"
case "$STEPS" in *" open"*) [ "$NOOPEN" = 1 ] && STEPS="${STEPS% open}" ;; esac

ask() { # ask "question" -> 0 for yes. Never silent: with no keyboard and no --yes the answer is no.
  [ "$YES" = 1 ] && return 0
  if [ -r /dev/tty ] && (exec </dev/tty) 2>/dev/null; then
    printf '%s [y/N] ' "$1" >/dev/tty
    read -r a </dev/tty || a=n
    case "$a" in y|Y|yes|YES|Yes) return 0 ;; esac
  fi
  return 1
}
have() { command -v "$1" >/dev/null 2>&1; }
add_path() { case ":$PATH:" in *":$BIN:"*) ;; *) PATH="$BIN:$PATH"; export PATH ;; esac; }
record() { # record key=value, once
  mkdir -p "$DATA"; touch "$MANIFEST"
  grep -qxF "$1" "$MANIFEST" 2>/dev/null || printf '%s\n' "$1" >> "$MANIFEST"
}
recorded() { grep -qxF "$1" "$MANIFEST" 2>/dev/null; }
sha() { if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

do_check() {
  step "Looking at your computer"
  OS=$(uname -s); ARCH=$(uname -m)
  case "$OS" in Darwin) say "This is a Mac ($ARCH)." ;; Linux) say "This is Linux ($ARCH)." ;;
    *) stop "wz installs on a Mac or on Linux. This computer says '$OS'. On Windows, use WSL (Ubuntu) and run this there." ;; esac
  [ "$(id -u)" != 0 ] || stop "You are running as the administrator (root). wz installs for one person only, without sudo. Open a normal terminal as yourself and run it again."
  have curl || stop "I need 'curl', and this computer does not have it. Installing it needs the administrator, which I will not use. Ask whoever looks after this computer to install curl, then run me again."
  have tar || stop "I need 'tar', which this computer does not have. Ask whoever looks after this computer to install it."
  [ -n "${HOME:-}" ] && [ -w "$HOME" ] || stop "I cannot write in your home folder."
  have uv || [ -x "$BIN/uv" ] && say "uv (the Python helper): already here." || say "uv (the Python helper): not here yet, I will add it."
  have wz || [ -x "$BIN/wz" ] && say "wz: already here." || say "wz: not here yet, I will add it."
  have claude || [ -x "$BIN/claude" ] && say "Claude Code: already here." || say "Claude Code: not here yet, I will add it."
  have git && say "git: here (not needed for the simple setup)." || say "git: not here (not needed for the simple setup)."
  have tmux && say "tmux: here (not needed)." || say "tmux: not here (not needed)."
}

do_uv() {
  step "Python helper (uv)"
  add_path
  if have uv; then say "uv is already installed: $(uv --version). Leaving it alone."; return; fi
  say "Adding uv $UV_VERSION to $BIN. It is a small program; it lives only in your home folder."
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | UV_NO_MODIFY_PATH=1 UV_UNMANAGED_INSTALL="$BIN" sh \
    || stop "Downloading uv failed. Check that this computer is online, then run me again."
  record "uv=added"
  have uv || stop "uv did not install where I expected ($BIN)."
  say "uv installed: $(uv --version)"
}

do_wz() {
  step "wz"
  add_path
  have uv || stop "uv is missing; run the 'uv' step first."
  pdir=$(uv python dir 2>/dev/null || true)
  if ! recorded "python_dir_was_empty=yes" && ! recorded "python_dir_was_empty=no"; then
    if [ -z "$pdir" ] || [ ! -d "$pdir" ] || [ -z "$(ls -A "$pdir" 2>/dev/null)" ]; then record "python_dir_was_empty=yes"; else record "python_dir_was_empty=no"; fi
  fi
  say "Installing wz ($WZ_REF). If this computer has no Python 3.11 or newer, uv fetches one into your home folder."
  uv tool install --force --python '>=3.11,<3.14' "$WZ_SRC" \
    || stop "I could not install wz from $WZ_SRC. If wz is not public yet, that address does not work yet; ask whoever sent you this."
  record "wz=added"
  wz --version || stop "wz installed but does not start."
  save_uninstaller
}

do_claude() {
  step "Claude Code"
  add_path
  if [ "$NOCLAUDE" = 1 ]; then say "Skipping Claude Code, as asked."; return; fi
  if have claude; then say "Claude Code is already installed: $(claude --version 2>/dev/null || echo present). Leaving it alone."; return; fi
  say "Installing Claude Code with Anthropic's own installer (the $CLAUDE_CHANNEL release). It goes in your home folder."
  curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_CHANNEL" \
    || stop "Anthropic's installer did not finish. See https://code.claude.com/docs/en/setup for what to try."
  record "claude=added"
  have claude || stop "Claude Code did not appear in $BIN."
  say "Claude Code installed: $(claude --version)"
}

profile_file() {
  case "${SHELL:-}" in
    */zsh) echo "$HOME/.zshrc" ;;
    */bash) if [ "$(uname -s)" = Darwin ]; then echo "$HOME/.bash_profile"; else echo "$HOME/.bashrc"; fi ;;
    *) echo "$HOME/.profile" ;;
  esac
}

do_path() {
  step "Making 'wz' and 'claude' work in new terminal windows"
  add_path
  pf=$(profile_file)
  if grep -q '>>> wz install >>>' "$pf" 2>/dev/null; then say "$pf already has the line. Nothing to do."; return; fi
  if [ ! -d "$BIN" ] || [ -z "$(ls "$BIN" 2>/dev/null)" ]; then say "Nothing was added to $BIN, so no change is needed."; return; fi
  # ~/.local/bin is on the default PATH of most new Linux accounts once it exists; add the line only if a fresh shell lacks it
  fresh=$(env -i HOME="$HOME" SHELL="${SHELL:-/bin/sh}" TERM=dumb PATH=/usr/bin:/bin "${SHELL:-/bin/sh}" -l -i -c 'printf %s "$PATH"' 2>/dev/null </dev/null || true)
  if case ":$fresh:" in *":$BIN:"*) true ;; *) false ;; esac; then
    say "New terminal windows already find $BIN. Nothing to do."; return
  fi
  say "New terminal windows do not look in $BIN yet. I would add three marked lines at the end of $pf."
  if ask "May I add them?"; then
    [ -e "$pf" ] || record "profile_created=yes"
    { printf '\n# >>> wz install >>>\nexport PATH="$HOME/.local/bin:$PATH"\n# <<< wz install <<<\n'; } >> "$pf"
    record "profile=$pf"
    say "Added. Open a new terminal window for it to take effect."
  else
    say "Not changed. Until you do, run this in each new terminal:  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
}

do_verify() {
  step "Checking that it works"
  add_path
  have wz || stop "wz is not found. Run the 'wz' step."
  wz --version
  T=$(mktemp -d)
  cat > "$T/answers.json" <<'EOF'
{"project": "smoke", "description": "install check", "workflows": ["admin"],
 "stores": {"office": {"kind": "folder", "path": "files"}}, "roles": {},
 "accounts": {"main": {"config_dir": "", "daily_usd": 5}}, "budget_usd": 5, "permission_mode": "default"}
EOF
  wz init --simple --answers "$T/answers.json" --dir "$T/ws" --no-git >/dev/null || { rm -rf "$T"; stop "The wz self-check could not set up a test project."; }
  grep -q 'permission_mode = "default"' "$T/ws/wz.toml" || { rm -rf "$T"; stop "The self-check config is not in the ask-first mode."; }
  wz --config "$T/ws/wz.toml" status >/dev/null || { rm -rf "$T"; stop "The wz self-check could not read its own status."; }
  rm -rf "$T"
  say "wz works: made a throwaway test project, it is in ask-first mode, and I deleted it."
  if have claude; then claude --version; else say "(Claude Code is not installed; the setup interview needs it.)"; fi
}

do_workspace() {
  step "Your wz folder"
  mkdir -p "$WORKDIR"
  say "Your wz files will live in $WORKDIR. I will never delete this folder."
  record "workspace=$WORKDIR"
}

do_open() {
  step "Starting the setup conversation"
  add_path
  have claude || stop "Claude Code is not installed, so I cannot start the conversation. Run:  sh install.sh claude"
  say "Next, Claude Code opens. The first time, it asks you to sign in to your Claude account in your web browser."
  say "Then it asks you a few short questions. It will not do anything without asking you first."
  cd "$WORKDIR"
  exec wz init --simple --dir "$WORKDIR"
}

save_uninstaller() { # keep a copy next to the manifest, so removing wz never depends on the network
  mkdir -p "$DATA"
  here=$(dirname "$0")
  if [ -f "$here/uninstall.sh" ]; then cp "$here/uninstall.sh" "$DATA/uninstall.sh"
  elif [ -f "$WZ_SRC/uninstall.sh" ]; then cp "$WZ_SRC/uninstall.sh" "$DATA/uninstall.sh"
  else curl -fsSL "${WZ_RAW:-https://raw.githubusercontent.com/verso-run/wz/$WZ_REF}/uninstall.sh" -o "$DATA/uninstall.sh" 2>/dev/null || true
  fi
}
for s in $STEPS; do "do_$s"; done
case "$STEPS" in *" open"*|"open") ;; *) say ""; say "Done: $STEPS" ;; esac
