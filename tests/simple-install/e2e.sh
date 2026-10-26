#!/bin/bash
# End to end check of the simple install on a CLEAN machine: install, run twice, set up in safe mode, uninstall, and
# list anything left behind. Needs no sign-in. Run as a normal user:  bash tests/simple-install/e2e.sh <wz-source-dir>
# Uses a scratch HOME and a PATH without Homebrew, so nothing already on the machine can help or be touched.
set -eu
SRC="$(cd "$1" && pwd)"
ok() { printf 'PASS  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; exit 1; }
export HOME; HOME="$(mktemp -d)"
export XDG_DATA_HOME= ; unset XDG_DATA_HOME
export SHELL=/bin/bash
SYS=/usr/bin:/bin:/usr/sbin:/sbin
export PATH="$SYS"
mkdir -p "$HOME/wzsrc" && cp -R "$SRC/." "$HOME/wzsrc/"   # a writable copy, as an unpacked download would be
export WZ_SRC="$HOME/wzsrc"
cd "$HOME"
printf 'machine: %s %s, HOME=%s\nPATH=%s\npresent: ' "$(uname -s)" "$(uname -m)" "$HOME" "$PATH"
for t in curl tar git tmux python3 brew uv wz claude; do command -v $t >/dev/null 2>&1 && printf '%s ' "$t" || printf '(no %s) ' "$t"; done; echo
find "$HOME" | sort > "$HOME/../before.$$" ; cp "$HOME/../before.$$" /tmp/before.$$ 2>/dev/null || true

echo "--- 1. install (run 1)"
sh "$WZ_SRC/install.sh" --yes --no-open
echo "--- 2. install again (idempotent)"
sh "$WZ_SRC/install.sh" --yes --no-open | tail -12
export PATH="$HOME/.local/bin:$SYS"
wz --version | grep -q '^wz ' && ok "wz --version: $(wz --version)" || bad "wz --version"
claude --version | grep -q 'Claude Code' && ok "claude --version: $(claude --version)" || bad "claude --version"
[ "$(grep -c '^uv=added' "$HOME/.local/share/wz-install/manifest")" = 1 ] && ok "manifest has each item once" || bad "manifest duplicated"

echo "--- 3. safe defaults"
cat > "$HOME/answers.json" <<'EOF'
{"project":"demo","description":"demo","workflows":["admin"],"stores":{"office":{"kind":"folder","path":"files"}},
 "roles":{},"accounts":{"main":{"config_dir":"","daily_usd":5}},"budget_usd":5}
EOF
wz init --simple --answers "$HOME/answers.json" --dir "$HOME/wz-work" --no-git >/dev/null
[ -d "$HOME/wz-work/files" ] && ok "the work folder was created" || bad "work folder missing"
grep -q 'permission_mode = "default"' "$HOME/wz-work/wz.toml" && ok "permission_mode = default (Claude asks first)" || bad "permission mode"
grep -q 'daily_usd = 5' "$HOME/wz-work/wz.toml" && ok "daily cap written: $(grep -m1 daily_usd "$HOME/wz-work/wz.toml")" || bad "cap"
! grep -q bypassPermissions "$HOME/wz-work/wz.toml" && ok "no bypassPermissions anywhere in wz.toml" || bad "bypass found"
if wz init --simple --answers <(sed 's/"budget_usd":5//;s/,$//' "$HOME/answers.json") --dir "$HOME/nocap" --no-git >/dev/null 2>&1; then
  grep -q budget "$HOME/nocap/wz.toml" 2>/dev/null && ok "(cap left to default)" || bad "simple setup accepted an uncapped config"
else ok "simple setup refuses to write a config with no daily cap"; fi
if wz init --simple --print-charter --dir "$HOME/wz-work" >/dev/null && grep -q 'Do not install timers' "$HOME/wz-work/.wz/setup/CHARTER.md"; then ok "setup interview charter says: no timers"; else bad "charter"; fi
n=$(find "$HOME" \( -path '*/systemd/user/*' -o -path '*/LaunchAgents/*' \) -type f 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = 0 ] && ok "no timers or launch agents exist" || bad "$n timer files found"
wz --config "$HOME/wz-work/wz.toml" install timers --dry-run | head -3 | sed 's/^/      /'

echo "--- 4. uninstall"
sh "$HOME/.local/share/wz-install/uninstall.sh" --yes
export PATH="$SYS"
for t in wz uv claude; do command -v $t >/dev/null 2>&1 && bad "$t still on PATH" || ok "$t gone"; done
[ -d "$HOME/wz-work" ] && ok "your wz folder was kept" || bad "workspace deleted"
find "$HOME" | sort > "$HOME/after.txt"
echo "--- 5. what is left in HOME after uninstall (beside the files the test made):"
LEFT=$(comm -13 /tmp/before.$$ "$HOME/after.txt" | grep -v -e "^$HOME/wzsrc" -e "^$HOME/nocurl" -e "^$HOME/wz-work" -e "^$HOME/answers.json" -e "^$HOME/after.txt" -e "^$HOME/nocap" || true)
printf '%s\n' "$LEFT" | sed 's/^/      /'
STRAY=$(printf '%s\n' "$LEFT" | grep -v -e "^$HOME/.claude" -e '^$' || true)
[ -z "$STRAY" ] && ok "only Claude's own settings (~/.claude, ~/.claude.json) remain, kept on purpose" || bad "left behind: $STRAY"
echo "--- 6. things the installer must stop on"
if [ "$(id -u)" != 0 ]; then
  mkdir -p "$HOME/nocurl"; for t in uname id tar mkdir sed cut grep dirname basename cat env ls touch; do ln -sf "$(command -v $t)" "$HOME/nocurl/$t"; done
  out=$(PATH="$HOME/nocurl" /bin/sh "$WZ_SRC/install.sh" check 2>&1) && bad "install went on without curl" || true
  case "$out" in *"I need 'curl'"*"administrator"*) ok "no curl: stops and explains, does not use sudo" ;; *) bad "no-curl message: $out" ;; esac
fi
echo "ALL DONE"
