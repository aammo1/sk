#!/usr/bin/env bash
# new-video.sh — start a new Editor V2 hybrid tutorial video from an Omarchy recording.
#
#   bash <skill>/scripts/new-video.sh <recording|--latest> [name] [--dir <parent>] [--style calm|documentary] [--cam FILE [--cam-offset S] [--voice screen|cam]] [--no-cam]
#
#   <recording>  the talking-head / screencast recording (.mov / .mp4 / .mkv), 16:9
#   --latest     auto-detect the newest screenrecording-*.mp4 (or *.mp4) in ~/Videos
#   [name]       folder name; default: today's date + normalized source filename
#   --dir        where videos live; default: ~/editor-v2/videos
#   --style      hook style: documentary (default, fast montage) or calm (title card + screencast)
#   --cam        separately recorded camera file (synced by audio -> assets/media/cam_face.mp4)
#   --cam-offset force camera offset in seconds (cam_t = screen_t + S) instead of audio sync
#   --voice      which recording provides assets/media/vo.wav: screen (default) or cam
#   --no-cam     skip auto-picking up a camera file recorded by `ev2 rec`
#
# Creates <parent>/<name>/ with
#   build.py  PLAN.md  kit.json        the template starter (calm: template/build_calm.py), skill pointer, style
#   assets/ev1/                        tokens.css, fonts/, vendor/gsap.min.js
#   assets/media/src.<ext>             the recording (hard-linked or copied)
#   assets/media/cam_raw.mp4           raw 30 fps CFR (keyframe every 1s, bt709)
#   assets/media/cam_face.mp4          aligned separate camera, if --cam or `ev2 rec` camera (work/camera.json)
#   assets/media/vo.wav                voice track, 48 kHz 24-bit PCM stereo (same t=0 as cam_raw)
#   work/omarchy.json                  detected webcam overlay coordinates & layout
#   assets/{img,clips,captures,music}/ work/tx/  out/
set -euo pipefail
SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"

if [ $# -eq 0 ]; then
  echo "usage: new-video.sh <recording|--latest> [name] [--dir parent] [--style calm|documentary] [--cam FILE [--cam-offset S] [--voice screen|cam]] [--no-cam]" >&2
  echo "       new-video.sh --from-director <handoff_dir> [name] [--dir parent] [--style calm|documentary]" >&2
  exit 1
fi

PARENT="$HOME/editor-v2/videos"; STYLE="documentary"; MODE="tutorial"
CAM=""; CAM_OFFSET=""; VOICE="screen"; NO_CAM=0; DIRECTOR_DIR=""
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --from-director) [ $# -ge 2 ] && [ -n "$2" ] || { echo "new-video: error: --from-director requires a directory" >&2; exit 1; }; DIRECTOR_DIR="$2"; shift 2;;
    --from-director=*) DIRECTOR_DIR="${1#--from-director=}"; [ -n "$DIRECTOR_DIR" ] || { echo "new-video: error: --from-director requires a directory" >&2; exit 1; }; shift;;
    --dir) [ $# -ge 2 ] || { echo "new-video: error: --dir requires a path" >&2; exit 1; }; PARENT="$2"; shift 2;;
    --style) STYLE="${2:-}"; shift $(( $# > 1 ? 2 : 1 ));;
    --style=*) STYLE="${1#--style=}"; shift;;
    --mode) MODE="${2:-}"; shift $(( $# > 1 ? 2 : 1 ));;
    --mode=*) MODE="${1#--mode=}"; shift;;
    --cam) [ $# -ge 2 ] && [ -n "$2" ] || { echo "new-video: error: --cam requires a file" >&2; exit 1; }; CAM="$2"; shift 2;;
    --cam=*) CAM="${1#--cam=}"; [ -n "$CAM" ] || { echo "new-video: error: --cam requires a file" >&2; exit 1; }; shift;;
    --cam-offset) [ $# -ge 2 ] && [ -n "$2" ] || { echo "new-video: error: --cam-offset requires seconds" >&2; exit 1; }; CAM_OFFSET="$2"; shift 2;;
    --cam-offset=*) CAM_OFFSET="${1#--cam-offset=}"; [ -n "$CAM_OFFSET" ] || { echo "new-video: error: --cam-offset requires seconds" >&2; exit 1; }; shift;;
    --voice) [ $# -ge 2 ] || { echo "new-video: error: --voice requires screen or cam" >&2; exit 1; }; VOICE="$2"; shift 2;;
    --voice=*) VOICE="${1#--voice=}"; shift;;
    --no-cam) NO_CAM=1; shift;;
    *) POSITIONAL+=("$1"); shift;;
  esac
done

case "$STYLE" in
  calm|documentary) ;;
  *) echo "new-video: error: --style must be calm or documentary (got '$STYLE')" >&2; exit 1;;
esac
case "$MODE" in
  tutorial|short) ;;
  *) echo "new-video: error: --mode must be tutorial or short (got '$MODE')" >&2; exit 1;;
esac
case "$VOICE" in
  screen|cam) ;;
  *) echo "new-video: error: --voice must be screen or cam (got '$VOICE')" >&2; exit 1;;
esac
[ -s "$SK/assets/vendor/gsap.min.js" ] || { echo "new-video: error: GSAP missing: run scripts/doctor.sh first" >&2; exit 1; }

if [ -n "$DIRECTOR_DIR" ]; then
  [ -z "$CAM" ] && [ -z "$CAM_OFFSET" ] || { echo "new-video: error: cannot combine --from-director with --cam/--cam-offset" >&2; exit 1; }
  [ -d "$DIRECTOR_DIR" ] || { echo "new-video: error: no such handoff directory: $DIRECTOR_DIR" >&2; exit 1; }
  DIRECTOR_DIR="$(cd "$DIRECTOR_DIR" && pwd)"
  for req in screen.mp4 vo.wav words.json; do
    [ -f "$DIRECTOR_DIR/$req" ] || { echo "new-video: error: missing $req in handoff directory: $DIRECTOR_DIR" >&2; exit 1; }
  done
  NAME="${POSITIONAL[0]:-}"
  if [ -z "$NAME" ]; then
    base="$(basename "$DIRECTOR_DIR")"
    if [ "$base" = "handoff" ]; then
      base="$(basename "$(dirname "$DIRECTOR_DIR")")"
    fi
    slug="$(printf '%s' "$base" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//' | cut -c1-40)"
    NAME="$(date +%Y-%m-%d)-${slug:-director}"
  fi
  VD="$PARENT/$NAME"
  [ -e "$VD" ] && { echo "new-video: error: $VD already exists" >&2; exit 1; }

  mkdir -p "$VD"/assets/{ev1,media,img,clips,captures,music} "$VD"/work/tx "$VD"/out
  cp "$SK/assets/tokens.css" "$VD/assets/ev1/"
  cp -R "$SK/assets/fonts" "$SK/assets/vendor" "$VD/assets/ev1/"
  cp "$SK/template/build.py" "$SK/template/PLAN.md" "$VD/"
  if [ "$STYLE" = calm ]; then printf '{\n  "recipe": "calm",\n  "promise": ""\n}\n' > "$VD/work/hook.json"; fi
  printf '{\n  "skill": "%s",\n  "created": "%s",\n  "style": "%s",\n  "director": true\n}\n' "$SK" "$(date +%Y-%m-%d)" "$STYLE" > "$VD/kit.json"

  ln "$DIRECTOR_DIR/screen.mp4" "$VD/assets/media/src.mp4" 2>/dev/null || cp "$DIRECTOR_DIR/screen.mp4" "$VD/assets/media/src.mp4"

  echo "new-video: director mode (no webcam overlay) -> work/omarchy.json + work/camera.json"
  "$EV2_PY" "$SK/scripts/omarchy_detect.py" "$VD/assets/media/src.mp4" --size none --out-json "$VD/work/omarchy.json" >"$VD/work/omarchy.log" 2>&1
  printf '{\n  "mode": "none"\n}\n' > "$VD/work/camera.json"

  REMUX_OK="$("$EV2_PY" -c '
import json, subprocess, sys
r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate",
    "-of", "json", sys.argv[1]], capture_output=True, text=True)
if r.returncode == 0:
    st = (json.loads(r.stdout).get("streams") or [{}])[0]
    ok = (st.get("codec_name") == "h264" and st.get("width") == 1920 and st.get("height") == 1080
          and st.get("pix_fmt") == "yuv420p"
          and st.get("r_frame_rate") == "30/1" and st.get("avg_frame_rate") == "30/1")
    print("1" if ok else "0")
else:
    print("0")
' "$VD/assets/media/src.mp4" 2>/dev/null || echo "0")"

  if [ "$REMUX_OK" = "1" ]; then
    echo "new-video: director screen -> assets/media/cam_raw.mp4 (remux 1080p 30fps)"
    ffmpeg -nostdin -v error -y -i "$VD/assets/media/src.mp4" -map 0:v:0 -c:v copy -an "$VD/assets/media/cam_raw.mp4"
  else
    VENC=(-c:v libx264 -crf 14 -preset fast -g 30 -keyint_min 30)
    if "$EV2_PY" "$SK/scripts/gpu.py" on >/dev/null 2>&1; then
      VENC=(-c:v h264_nvenc -preset p6 -tune hq -rc vbr -cq 14 -b:v 0 -spatial-aq 1 -temporal-aq 1 -bf 0 -g 30 -forced-idr 1)
    fi
    echo "new-video: director screen -> assets/media/cam_raw.mp4 (30 fps CFR)"
    ffmpeg -nostdin -v error -stats -y -i "$VD/assets/media/src.mp4" -map 0:v:0 \
      -vf "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
      "${VENC[@]}" -pix_fmt yuv420p \
      -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 -an "$VD/assets/media/cam_raw.mp4"
  fi

  WAV_OK="$("$EV2_PY" -c '
import json, subprocess, sys
r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
    "-show_entries", "stream=codec_name,sample_rate,channels",
    "-of", "json", sys.argv[1]], capture_output=True, text=True)
if r.returncode == 0:
    st = (json.loads(r.stdout).get("streams") or [{}])[0]
    ok = (st.get("codec_name") == "pcm_s24le" and str(st.get("sample_rate")) == "48000" and st.get("channels") == 2)
    print("1" if ok else "0")
else:
    print("0")
' "$DIRECTOR_DIR/vo.wav" 2>/dev/null || echo "0")"
  if [ "$WAV_OK" = "1" ]; then
    echo "new-video: director voice -> assets/media/vo.wav (48 kHz 24-bit PCM)"
    cp "$DIRECTOR_DIR/vo.wav" "$VD/assets/media/vo.wav"
  else
    echo "new-video: director voice -> assets/media/vo.wav (converting to 48 kHz 24-bit stereo)"
    ffmpeg -nostdin -v error -y -i "$DIRECTOR_DIR/vo.wav" -ac 2 -ar 48000 -c:a pcm_s24le "$VD/assets/media/vo.wav"
  fi

  if [ -f "$DIRECTOR_DIR/inputs.json" ]; then
    cp "$DIRECTOR_DIR/inputs.json" "$VD/work/inputs.json"
    echo "new-video: director inputs -> work/inputs.json"
  fi
  if [ -f "$DIRECTOR_DIR/director.json" ]; then
    cp "$DIRECTOR_DIR/director.json" "$VD/work/director.json"
  fi

  "$EV2_PY" -c '
import json, os, sys
src, dst_dir = sys.argv[1], sys.argv[2]
raw = json.load(open(src, encoding="utf-8"))
words = raw.get("words", []) if isinstance(raw, dict) else raw
if not isinstance(words, list):
    raise SystemExit(f"new-video: invalid words.json format in {src}")
for path in (os.path.join(dst_dir, "words.json"), os.path.join(dst_dir, "words_raw.json")):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
with open(os.path.join(dst_dir, "words.auto.json"), "w", encoding="utf-8") as f:
    json.dump({"sha": "script", "source": "script"}, f, indent=2)
with open(os.path.join(dst_dir, "transcript.txt"), "w", encoding="utf-8") as f:
    f.write(" ".join(str(w.get("w", "")) for w in words).strip() + "\n")
with open(os.path.join(dst_dir, "engine.json"), "w", encoding="utf-8") as f:
    json.dump({"engine": "director-script", "source": "script", "mean_prob": 1.0,
               "low_prob_share": 0.0, "script": True, "words": len(words)}, f, indent=2)
' "$DIRECTOR_DIR/words.json" "$VD/work/tx"
  echo "new-video: script words -> work/tx/words.json (source: script; ASR skipped)"

  if [ -f "$DIRECTOR_DIR/plan.json" ]; then
    cp "$DIRECTOR_DIR/plan.json" "$VD/work/director-plan.json"
    echo "plan suggestions from tutorial-director loaded: approve at the PLAN gate"
  fi

  LOOK_CFG="${EV2_DIRECTOR_LOOK:-$HOME/.config/editor-v2/director-look.json}"
  if [ -f "$LOOK_CFG" ]; then
    cp "$LOOK_CFG" "$VD/work/look.json"
    echo "new-video: brand look loaded from $LOOK_CFG -> work/look.json"
  else
    "$EV2_PY" -c '
import json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "components"))
import ev2_pro as P
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(P.LOOK_DEFAULTS, f, indent=2)
    f.write("\n")
' "$SK" "$VD/work/look.json"
    echo "new-video: default look -> work/look.json"
    echo "  to use one brand look for every director video, run once:"
    echo "    ev2 look \"$VD\" --accent \"#RRGGBB\" && mkdir -p ~/.config/editor-v2 && cp \"$VD/work/look.json\" ~/.config/editor-v2/director-look.json"
  fi

  D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VD/assets/media/cam_raw.mp4" 2>/dev/null || echo "0")
  echo
  echo "new-video: director workspace ready at $VD  (${D}s)"
  echo "next steps:"
  echo "  1. ev2 transcribe \"$VD\"       (cuts + work/timeline.json from script words, no ASR)"
  echo "  2. PLAN gate: confirm director suggestions in work/timeline.json + work/hook.json"
  echo "  3. ev2 hook \"$VD\" --final     (the designed hook from work/hook.json)"
  echo "  4. ev2 inserts \"$VD\" --final  (only if the plan has inserts)"
  echo "  5. ev2 finish \"$VD\"           (final.mp4, Concat project, Short, chapters, verify + beauty check)"
  exit 0
fi

[ ${#POSITIONAL[@]} -ge 1 ] || { echo "usage: new-video.sh <recording|--latest> [name] [--dir parent] [--style calm|documentary] [--cam FILE [--cam-offset S] [--voice screen|cam]] [--no-cam]" >&2; exit 1; }
REC_ARG="${POSITIONAL[0]}"
NAME="${POSITIONAL[1]:-}"

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

[ -f "$REC" ] || { echo "new-video: error: no such file: $REC" >&2; exit 1; }
if [ -n "$CAM" ]; then
  [ "$NO_CAM" = 0 ] || { echo "new-video: error: cannot combine --cam with --no-cam" >&2; exit 1; }
  [ -f "$CAM" ] || { echo "new-video: error: no such camera file: $CAM" >&2; exit 1; }
  CAM="$(cd "$(dirname "$CAM")" && pwd)/$(basename "$CAM")"
elif [ -n "$CAM_OFFSET" ] || [ "$VOICE" = cam ]; then
  if [ "$NO_CAM" = 1 ] || ! "$EV2_PY" "$SK/scripts/camsync.py" find "$REC" >/dev/null 2>&1; then
    echo "new-video: error: --cam-offset/--voice cam require a separate camera (--cam FILE or ev2 rec cam)" >&2
    exit 1
  fi
fi

if [ -z "$NAME" ]; then
  base="$(basename "$REC")"; base="${base%.*}"
  NAME="$(date +%Y-%m-%d)-$(printf '%s' "$base" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//' | cut -c1-40)"
fi
VD="$PARENT/$NAME"
[ -e "$VD" ] && { echo "new-video: error: $VD already exists" >&2; exit 1; }

mkdir -p "$VD"/assets/{ev1,media,img,clips,captures,music} "$VD"/work/tx "$VD"/out
cp "$SK/assets/tokens.css" "$VD/assets/ev1/"
cp -R "$SK/assets/fonts" "$SK/assets/vendor" "$VD/assets/ev1/"
cp "$SK/template/build.py" "$SK/template/PLAN.md" "$VD/"
if [ "$STYLE" = calm ]; then printf '{\n  "recipe": "calm",\n  "promise": ""\n}\n' > "$VD/work/hook.json"; fi
printf '{\n  "skill": "%s",\n  "created": "%s",\n  "style": "%s",\n  "mode": "%s"\n}\n' "$SK" "$(date +%Y-%m-%d)" "$STYLE" "$MODE" > "$VD/kit.json"

ext="${REC##*.}"
ln "$REC" "$VD/assets/media/src.$ext" 2>/dev/null || cp "$REC" "$VD/assets/media/src.$ext"

SRC_VERT="$("$EV2_PY" -c '
import json, subprocess, sys
r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=width,height", "-of", "json", sys.argv[1]], capture_output=True, text=True)
if r.returncode == 0:
    st = (json.loads(r.stdout).get("streams") or [{}])[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    print("1" if h > w and w > 0 else "0")
else:
    print("0")
' "$VD/assets/media/src.$ext" 2>/dev/null || echo "0")"

if [ "$MODE" = "short" ] && [ "$SRC_VERT" = "1" ]; then
  echo "new-video: standalone vertical Short/Reel mode (1080x1920 native)"
  printf '{\n  "has_webcam_overlay": false,\n  "width": 1080,\n  "height": 1920,\n  "vertical_source": true\n}\n' > "$VD/work/omarchy.json"
  SCALE_VF="fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
else
  echo "new-video: detecting Omarchy webcam overlay -> work/omarchy.json"
  if ! "$EV2_PY" "$SK/scripts/omarchy_detect.py" "$VD/assets/media/src.$ext" --out-json "$VD/work/omarchy.json" >"$VD/work/omarchy.log" 2>&1; then
    echo "new-video: WARNING webcam detection failed (see work/omarchy.log); continuing without PiP data" >&2
  fi
  SCALE_VF="fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
fi

VENC=(-c:v libx264 -crf 14 -preset fast -g 30 -keyint_min 30)
if "$EV2_PY" "$SK/scripts/gpu.py" on >/dev/null 2>&1; then
  VENC=(-c:v h264_nvenc -preset p6 -tune hq -rc vbr -cq 14 -b:v 0 -spatial-aq 1 -temporal-aq 1 -bf 0 -g 30 -forced-idr 1)
  echo "new-video: encoding on the GPU (NVENC); EV2_GPU=0 for the CPU"
fi
echo "new-video: camera/screencast -> assets/media/cam_raw.mp4 (raw, 30 fps CFR)"
ffmpeg -nostdin -v error -stats -y -i "$VD/assets/media/src.$ext" -map 0:v:0 \
  -vf "$SCALE_VF" \
  "${VENC[@]}" -pix_fmt yuv420p \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc bt709 -an "$VD/assets/media/cam_raw.mp4"

echo "new-video: voice -> assets/media/vo.wav (48 kHz 24-bit PCM)"
ffmpeg -nostdin -v error -y -i "$VD/assets/media/src.$ext" -map 0:a:0 -af "aresample=async=1:first_pts=0" -ac 2 -ar 48000 -c:a pcm_s24le "$VD/assets/media/vo.wav"

echo "new-video: input log (cursor, clicks, shortcuts from \`ev2 rec\`) -> work/inputs.json"
"$EV2_PY" "$SK/scripts/inputs.py" "$VD" --recording "$REC" || echo "new-video: WARNING could not read the input log; zooms will follow screen activity" >&2

if [ -n "$CAM" ]; then
  echo "new-video: separate camera -> assets/media/cam_face.mp4 (synced by audio)"
  args=(import "$VD" --cam "$CAM" --voice "$VOICE")
  [ -n "$CAM_OFFSET" ] && args+=(--offset "$CAM_OFFSET")
  "$EV2_PY" "$SK/scripts/camsync.py" "${args[@]}" || {
    echo "new-video: ERROR camera sync failed. The video folder is ready without the camera;" >&2
    echo "  fix and re-run: $EV2_PY $SK/scripts/camsync.py import \"$VD\" --cam \"$CAM\" --offset <seconds>" >&2
    exit 1; }
elif [ "$NO_CAM" = 0 ]; then
  if FOUND="$("$EV2_PY" "$SK/scripts/camsync.py" find "$REC" --vd "$VD" 2>/dev/null)"; then
    RC_FILE="$(printf '%s\n' "$FOUND" | sed -n 1p)"; RC_GUESS="$(printf '%s\n' "$FOUND" | sed -n 2p)"
    echo "new-video: ev2 rec recorded the camera ($RC_FILE) -> assets/media/cam_face.mp4"
    rc_args=(import "$VD" --cam "$RC_FILE" --guess "$RC_GUESS" --source ev2-rec --voice "$VOICE")
    [ -n "$CAM_OFFSET" ] && rc_args+=(--offset "$CAM_OFFSET")
    "$EV2_PY" "$SK/scripts/camsync.py" "${rc_args[@]}" \
      || echo "new-video: WARNING could not sync the ev2 rec camera; continuing without it (see above)" >&2
  fi
fi

D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VD/assets/media/cam_raw.mp4" 2>/dev/null || echo "0")
echo
echo "new-video: workspace ready at $VD  (${D}s)"
[ -f "$VD/work/camera.json" ] && echo "camera: separate (work/camera.json) — the PiP comes from assets/media/cam_face.mp4"
echo "next steps:"
if [ "$MODE" = "short" ]; then
  echo "  1. ev2 transcribe \"$VD\"       (words + tight Short cuts in work/timeline.json)"
  echo "  2. ev2 shorts \"$VD\" --init    (generates work/shorts.json + face check sheet)"
  echo "  3. Review work/shorts.json + ev2 check \"$VD\""
  echo "  4. ev2 shorts \"$VD\" --final   (renders 1080x1920 Pro Short/Reel + captions + .srt)"
  echo "  5. Optional: ev2 thumb \"$VD\" --init && ev2 thumb \"$VD\""
else
  echo "  1. ev2 transcribe \"$VD\"       (words + work/timeline.json + work/cuts-report.md)"
  echo "  2. PLAN gate: chapters, inserts (recipes), callouts, hook.json promise -> approval"
  echo "  3. ev2 hook \"$VD\" --final     (the designed hook from work/hook.json)"
  echo "  4. ev2 inserts \"$VD\" --final  (only if the plan has inserts)"
  echo "  5. ev2 finish \"$VD\"           (final.mp4, Concat project, Short, chapters, verify + beauty check)"
  echo "  6. Optional: ev2 shorts \"$VD\" --init | ev2 thumb \"$VD\" --init | ev2 describe \"$VD\""
fi
