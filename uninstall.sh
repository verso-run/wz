#!/bin/sh
# wz uninstaller. Removes what install.sh added, as listed in ~/.local/share/wz-install/manifest, and nothing else.
# Your own files (your wz folder, and Claude's sign-in and settings in ~/.claude) are never touched.
#   sh uninstall.sh [--yes] [--dry-run] [--keep-claude]
set -eu
BIN="$HOME/.local/bin"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/wz-install"
MANIFEST="$DATA/manifest"
YES=0; DRY=0; KEEPCLAUDE=0
for a in "$@"; do
  case "$a" in --yes|-y) YES=1 ;; --dry-run) DRY=1 ;; --keep-claude) KEEPCLAUDE=1 ;; -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "I do not know the option '$a'." >&2; exit 1 ;; esac
done
say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
recorded() { grep -qxF "$1" "$MANIFEST" 2>/dev/null; }
do_() { if [ "$DRY" = 1 ]; then say "  would run: $*"; else "$@"; fi; }
[ -f "$MANIFEST" ] || { say "There is nothing to remove: wz's installer left no record on this computer."; exit 0; }
PATH="$BIN:$PATH"; export PATH

say "This removes what the wz installer added to your home folder:"
recorded wz=added && say "  - wz"
recorded claude=added && [ "$KEEPCLAUDE" = 0 ] && say "  - Claude Code (not your sign-in or settings)"
recorded uv=added && say "  - uv, and the Python it fetched"
! recorded uv=added && recorded python_dir_was_empty=yes && say "  - the Python that uv fetched for wz"
grep -q '^profile=' "$MANIFEST" && say "  - the three lines added to $(sed -n 's/^profile=//p' "$MANIFEST" | head -1)"
say "It keeps your files: $(sed -n 's/^workspace=//p' "$MANIFEST" | head -1) and ~/.claude."
if [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then
  if [ -r /dev/tty ] && (exec </dev/tty) 2>/dev/null; then
    printf 'Go ahead? [y/N] ' >/dev/tty; read -r a </dev/tty || a=n
    case "$a" in y|Y|yes|YES|Yes) ;; *) say "Nothing was changed."; exit 0 ;; esac
  else say "No keyboard to ask on, so nothing was changed. Run again with --yes."; exit 0; fi
fi

# 1. timers, if the person ever turned them on
WS=$(sed -n 's/^workspace=//p' "$MANIFEST" | head -1)
if have wz && [ -n "$WS" ]; then
  for c in "$WS"/wz.toml "$WS"/*/wz.toml; do
    [ -f "$c" ] || continue
    do_ wz --config "$c" install timers --uninstall >/dev/null 2>&1 || true
  done
fi
# 2. wz
if recorded wz=added && have uv; then do_ uv tool uninstall wz || true; fi
# 3. Claude Code
if recorded claude=added && [ "$KEEPCLAUDE" = 0 ]; then
  do_ rm -f "$BIN/claude"; do_ rm -rf "$HOME/.local/share/claude" "$HOME/.cache/claude" "$HOME/.local/state/claude"
fi
# 4. uv and the Python it fetched
if have uv; then
  PYD=$(uv python dir 2>/dev/null || true); TLD=$(uv tool dir 2>/dev/null || true); CCD=$(uv cache dir 2>/dev/null || true)
  if recorded uv=added; then
    [ -n "$PYD" ] && do_ rm -rf "$PYD"; [ -n "$TLD" ] && do_ rm -rf "$TLD"; [ -n "$CCD" ] && do_ rm -rf "$CCD"
    do_ rm -f "$BIN/uv" "$BIN/uvx"
  elif recorded python_dir_was_empty=yes && [ -n "$PYD" ]; then
    do_ rm -rf "$PYD"
  fi
fi
# 5. the PATH lines
PF=$(sed -n 's/^profile=//p' "$MANIFEST" | head -1)
if [ -n "$PF" ] && [ -f "$PF" ] && [ "$DRY" != 1 ]; then
  T=$(mktemp); awk '/# >>> wz install >>>/{skip=1} !skip{print} /# <<< wz install <<</{skip=0}' "$PF" > "$T" && cat "$T" > "$PF"; rm -f "$T"
  if recorded profile_created=yes && ! grep -q '[^[:space:]]' "$PF"; then rm -f "$PF"; fi
elif [ -n "$PF" ]; then say "  would remove the marked lines from $PF"; fi
# 6. the record itself, and folders the installer left empty
do_ rm -rf "$DATA"
for d in "$HOME/.local/share/uv" "$BIN" "$HOME/.local/share" "$HOME/.local/state" "$HOME/.local" "$HOME/.cache"; do
  [ "$DRY" = 1 ] || rmdir "$d" 2>/dev/null || true
done
say ""
say "Done. Open a new terminal window. Your files are where you left them."
