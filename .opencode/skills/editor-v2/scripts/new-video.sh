#!/usr/bin/env bash
# new-video.sh — start a new Editor V2 hybrid tutorial video from an Omarchy recording.
#
#   bash <skill>/scripts/new-video.sh <recording|--latest> [name] [--dir <parent>]
#
#   <recording>  the talking-head / screencast recording (.mov / .mp4 / .mkv), 16:9
#   --latest     auto-detect the newest screenrecording-*.mp4 (or *.mp4) in ~/Videos
#   [name]       folder name; default: today's date + normalized source filename
#   --dir        where videos live; default: ~/editor-v2/videos
#
# Creates <parent>/<name>/ with
#   build.py  PLAN.md  kit.json        the template starter and skill pointer
#   assets/ev1/                        tokens.css, fonts/, vendor/gsap.min.js
#   assets/media/src.<ext>             the recording (hard-linked or copied)
#   assets/media/cam_raw.mp4           raw 30 fps CFR (keyframe every 1s, bt709)
#   assets/media/vo.wav                voice track, 48 kHz 24-bit PCM stereo (same t=0 as cam_raw)
#   work/omarchy.json                  detected webcam overlay coordinates & layout
#   assets/{img,clips,captures,music}/ work/tx/  out/
set -euo pipefail
SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"

if [ $# -eq 0 ]; then
  echo "usage: new-video.sh <recording|--latest> [name] [--dir parent]" >&2
  exit 1
fi

REC_ARG="$1"; shift

if [ "$REC_ARG" = "--latest" ]; then
  REC=""
  # 1. Search for newest screenrecording-*.mp4 in ~/Videos
  if ls "$HOME/Videos"/screenrecording-*.mp4 >/dev/null 2>&1; then
    REC=$(ls -t "$HOME/Videos"/screenrecording-*.mp4 2>/dev/null | head -n 1)
  fi
  # 2. Fallback to any newest *.mp4 in ~/Videos
  if [ -z "$REC" ] || [ ! -f "$REC" ]; then
    if ls "$HOME/Videos"/*.mp4 >/dev/null 2>&1; then
      REC=$(ls -t "$HOME/Videos"/*.mp4 2>/dev/null | head -n 1)
    fi
  fi
  if [ -z "$REC" ] || [ ! -f "$REC" ]; then
    echo "new-video: error: --latest specified but no recording found in $HOME/Videos/" >&2
    exit 1
  fi
  echo "new-video: auto-detected latest recording: $REC"
else
  REC="$REC_ARG"
fi

NAME=""; PARENT="$HOME/editor-v2/videos"
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) PARENT="$2"; shift 2;;
    *) NAME="$1"; shift;;
  esac
done

[ -f "$REC" ] || { echo "new-video: error: no such file: $REC" >&2; exit 1; }
[ -s "$SK/assets/vendor/gsap.min.js" ] || { echo "new-video: error: GSAP missing: run scripts/doctor.sh first" >&2; exit 1; }

if [ -z "$NAME" ]; then
  base="$(basename "$REC")"; base="${base%.*}"
  NAME="$(date +%Y-%m-%d)-$(printf '%s' "$base" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//' | cut -c1-40)"
fi
VD="$PARENT/$NAME"
[ -e "$VD" ] && { echo "new-video: error: $VD already exists" >&2; exit 1; }

mkdir -p "$VD"/assets/{ev1,media,img,clips,captures,music} "$VD"/work/tx "$VD"/out
cp "$SK/assets/tokens.css" "$VD/assets/ev1/"
cp -R "$SK/assets/fonts" "$SK/assets/vendor" "$VD/assets/ev1/"
cp "$SK/template/build.py" "$SK/template/PLAN.md" "$SK/template/inserts.py" "$VD/"
printf '{\n  "skill": "%s",\n  "created": "%s"\n}\n' "$SK" "$(date +%Y-%m-%d)" > "$VD/kit.json"

ext="${REC##*.}"
ln "$REC" "$VD/assets/media/src.$ext" 2>/dev/null || cp "$REC" "$VD/assets/media/src.$ext"

echo "new-video: detecting Omarchy webcam overlay -> work/omarchy.json"
if ! "$EV2_PY" "$SK/scripts/omarchy_detect.py" "$VD/assets/media/src.$ext" --out-json "$VD/work/omarchy.json" >"$VD/work/omarchy.log" 2>&1; then
  echo "new-video: WARNING webcam detection failed (see work/omarchy.log); continuing without PiP data" >&2
fi

echo "new-video: camera/screencast -> assets/media/cam_raw.mp4 (raw, 30 fps CFR)"
ffmpeg -nostdin -v error -stats -y -i "$VD/assets/media/src.$ext" -map 0:v:0 \
  -vf "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -crf 14 -preset fast -g 30 -keyint_min 30 -pix_fmt yuv420p \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 -an "$VD/assets/media/cam_raw.mp4"

echo "new-video: voice -> assets/media/vo.wav (48 kHz 24-bit PCM)"
ffmpeg -nostdin -v error -y -i "$VD/assets/media/src.$ext" -map 0:a:0 -af "aresample=async=1:first_pts=0" -ac 2 -ar 48000 -c:a pcm_s24le "$VD/assets/media/vo.wav"

D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VD/assets/media/cam_raw.mp4" 2>/dev/null || echo "0")
echo
echo "new-video: workspace ready at $VD  (${D}s)"
echo "next steps:"
echo "  1. ev2 transcribe \"$VD\"     (words + work/timeline.json + work/cuts-report.md)"
echo "  2. PLAN gate: review PLAN.md + work/cuts-report.md with the user"
echo "  3. edit build.py, then: ev2 build \"$VD\""
echo "  4. ev2 finish \"$VD\"         (final.mp4, Concat project, Short, chapters, verify)"
