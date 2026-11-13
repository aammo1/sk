#!/usr/bin/env bash
# set-style.sh — switch an existing video's hook style.
#
#   bash <skill>/scripts/set-style.sh <video-dir> documentary|calm|custom
#
#   documentary  the designed "showcase" hook from work/hook.json (default): promise, montage, end card
#   calm         the designed "calm" hook from work/hook.json: a title card over the live screen
#   custom       the old hand-written hook (template/build_custom.py, device by device): experts only
#
# documentary and calm use the automatic build.py and set "recipe" in work/hook.json.
# A build.py that matches no template (hand-edited) is first backed up to
# build.py.bak-YYYYmmdd-HHMMSS. Records "style" in kit.json. Run `ev2 hook <video-dir>` afterwards.
set -euo pipefail
SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"

usage(){ echo "usage: set-style.sh <video-dir> documentary|calm|custom" >&2; exit 1; }
[ $# -eq 2 ] || usage
VD="${1%/}"; STYLE="$2"

case "$STYLE" in
  calm|documentary) TPL="$SK/template/build.py";;
  custom) TPL="$SK/template/build_custom.py";;
  *) echo "set-style: error: style must be documentary, calm or custom (got '$STYLE')" >&2; exit 1;;
esac
[ -f "$VD/kit.json" ] || { echo "set-style: error: $VD/kit.json not found: not a video folder (create one with ev2 init)" >&2; exit 1; }

if [ -f "$VD/build.py" ] && ! cmp -s "$VD/build.py" "$SK/template/build.py" \
   && ! cmp -s "$VD/build.py" "$SK/template/build_custom.py" && ! cmp -s "$VD/build.py" "$SK/template/build_calm.py"; then
  BAK="build.py.bak-$(date +%Y%m%d-%H%M%S)"
  cp -p "$VD/build.py" "$VD/$BAK"
  echo "set-style: build.py was modified: backed up to $VD/$BAK"
fi

cp "$TPL" "$VD/build.py"
"$EV2_PY" -c '
import json, os, sys
p, style, vd = sys.argv[1], sys.argv[2], sys.argv[3]
k = json.load(open(p))
k["style"] = style
with open(p, "w") as f:
    json.dump(k, f, indent=2, ensure_ascii=False)
    f.write("\n")
if style in ("calm", "documentary"):
    hp = os.path.join(vd, "work", "hook.json")
    h = json.load(open(hp, encoding="utf-8")) if os.path.isfile(hp) else {"promise": ""}
    h["recipe"] = "calm" if style == "calm" else "showcase"
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    with open(hp, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)
        f.write("\n")
' "$VD/kit.json" "$STYLE" "$VD"

echo "style: $VD -> $STYLE (next: ev2 hook $VD)"
