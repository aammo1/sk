#!/bin/sh
# Install skills from this repo into the shared agent skills root.
#
# DSH reads ~/.agents/skills (rank 500), ~/.dsh/skills, and project roots.
# Claude Code reads ~/.claude/skills. OpenCode reads ~/.agents/skills,
# ~/.claude/skills and ~/.config/opencode/skills.
# ~/.agents/skills is therefore the one root all three agents share.
#
#   ./install.sh --list                    show installable skill names
#   ./install.sh coolify-deploy nextjs     install only those skills
#   ./install.sh                           install every skill
#   ./install.sh --all                     install every skill, explicitly
#
#   --copy          copy instead of symlinking
#   --force         replace an existing real directory (default: skip it)
#   --dest=DIR      install somewhere else
#   AGENTS_SKILLS=DIR ./install.sh ...
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$REPO/.opencode/skills"
DEST="${AGENTS_SKILLS:-$HOME/.agents/skills}"
MODE=link
FORCE=0
ALL=0
LIST=0
NAMES=""

for arg in "$@"; do
  case "$arg" in
    --copy) MODE=copy ;;
    --link) MODE=link ;;
    --force) FORCE=1 ;;
    --all) ALL=1 ;;
    --list) LIST=1 ;;
    --dest=*) DEST="${arg#--dest=}" ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    *) NAMES="$NAMES$arg
" ;;
  esac
done

[ -d "$SRC" ] || { echo "missing skill source: $SRC" >&2; exit 1; }

if [ "$LIST" = 1 ]; then
  ls -1 "$SRC"
  exit 0
fi

# Explicit names win; otherwise --all and no-arg both mean everything.
if [ -n "$NAMES" ] && [ "$ALL" = 1 ]; then
  echo "pick skills by name or use --all, not both" >&2
  exit 2
fi
if [ -z "$NAMES" ]; then
  NAMES=$(ls -1 "$SRC")
fi

# Validate every requested name before touching the destination.
BAD=0
for name in $NAMES; do
  if [ ! -d "$SRC/$name" ]; then
    echo "no such skill: $name" >&2
    BAD=1
  fi
done
if [ "$BAD" = 1 ]; then
  echo "available: $(ls -1 "$SRC" | tr '\n' ' ')" >&2
  exit 2
fi

mkdir -p "$DEST"
linked=0; copied=0; skipped=0
for name in $NAMES; do
  path="$SRC/$name"
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
    cp -a "$path" "$target"
    copied=$((copied + 1))
  else
    ln -s "$path" "$target"
    linked=$((linked + 1))
  fi
done

echo "done: $linked linked, $copied copied, $skipped skipped -> $DEST"
