#!/usr/bin/env bash
# set-style.sh — switch an existing video's hook style.
#
#   bash <skill>/scripts/set-style.sh <video-dir> calm|documentary
#
#   documentary  the fast montage hook (template/build.py), the default
#   calm         a title card, then the screencast itself (template/build_calm.py)
#
# Copies the chosen template to <video-dir>/build.py and records "style" in kit.json.
# A build.py that matches neither template (hand-edited) is first backed up to
# build.py.bak-YYYYmmdd-HHMMSS. Run `ev2 build <video-dir>` afterwards.
set -euo pipefail
SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"

usage(){ echo "usage: set-style.sh <video-dir> calm|documentary" >&2; exit 1; }
[ $# -eq 2 ] || usage
VD="${1%/}"; STYLE="$2"

case "$STYLE" in
  calm) TPL="$SK/template/build_calm.py";;
  documentary) TPL="$SK/template/build.py";;
  *) echo "set-style: error: style must be calm or documentary (got '$STYLE')" >&2; exit 1;;
esac
[ -f "$VD/kit.json" ] || { echo "set-style: error: $VD/kit.json not found: not a video folder (create one with ev2 init)" >&2; exit 1; }

if [ -f "$VD/build.py" ] && ! cmp -s "$VD/build.py" "$SK/template/build.py" && ! cmp -s "$VD/build.py" "$SK/template/build_calm.py"; then
  BAK="build.py.bak-$(date +%Y%m%d-%H%M%S)"
  cp -p "$VD/build.py" "$VD/$BAK"
  echo "set-style: build.py was modified: backed up to $VD/$BAK"
fi

cp "$TPL" "$VD/build.py"
"$EV2_PY" -c '
import json, sys
p, style = sys.argv[1], sys.argv[2]
k = json.load(open(p))
k["style"] = style
with open(p, "w") as f:
    json.dump(k, f, indent=2, ensure_ascii=False)
    f.write("\n")
' "$VD/kit.json" "$STYLE"

echo "style: $VD -> $STYLE (run ev2 build $VD next)"
