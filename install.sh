#!/bin/sh
# Install this repo's skills into the shared agent skills root.
#
# DSH reads ~/.agents/skills (rank 500), ~/.dsh/skills, and project roots.
# Claude Code reads ~/.claude/skills. OpenCode reads ~/.agents/skills,
# ~/.claude/skills and ~/.config/opencode/skills.
# ~/.agents/skills is therefore the one root all three agents share.
#
#   ./install.sh                 link every skill into ~/.agents/skills
#   ./install.sh --copy          copy instead of linking
#   ./install.sh --force         replace existing non-symlink directories
#   ./install.sh --dest=DIR      install somewhere else
#   AGENTS_SKILLS=DIR ./install.sh
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$REPO/.opencode/skills"
DEST="${AGENTS_SKILLS:-$HOME/.agents/skills}"
MODE=link
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --copy) MODE=copy ;;
    --link) MODE=link ;;
    --force) FORCE=1 ;;
    --dest=*) DEST="${arg#--dest=}" ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

[ -d "$SRC" ] || { echo "missing skill source: $SRC" >&2; exit 1; }
mkdir -p "$DEST"

linked=0; copied=0; skipped=0
for path in "$SRC"/*/; do
  name=$(basename -- "$path")
  target="$DEST/$name"
  if [ -L "$target" ]; then
    rm -f "$target"
  elif [ -e "$target" ]; then
    if [ "$FORCE" = 1 ]; then
      rm -rf "$target"
    else
      echo "skip    $name (exists; --force to replace)"
      skipped=$((skipped + 1))
      continue
    fi
  fi
  if [ "$MODE" = copy ]; then
    cp -a "${path%/}" "$target"
    copied=$((copied + 1))
  else
    ln -s "${path%/}" "$target"
    linked=$((linked + 1))
  fi
done

echo "done: $linked linked, $copied copied, $skipped skipped -> $DEST"
