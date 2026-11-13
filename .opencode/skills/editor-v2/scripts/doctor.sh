#!/usr/bin/env bash
# doctor.sh — check (and where safe/free, fix) everything Editor V2 needs.
#
# Usage:
#   bash ~/.agents/skills/editor-v2/scripts/doctor.sh
#   bash ~/.agents/skills/editor-v2/scripts/doctor.sh --install-speech
#   bash ~/.agents/skills/editor-v2/scripts/doctor.sh --install-matte
#   bash ~/.agents/skills/editor-v2/scripts/doctor.sh --install-speech --install-matte

SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"

SPEECH=0
MATTE=0
for a in "$@"; do
  case "$a" in
    --install-speech) SPEECH=1 ;;
    --install-matte)  MATTE=1 ;;
  esac
done

OS="$(uname -s)"
ARCH="$(uname -m)"
BAD=0

ok(){   printf '  ok      %-14s %s\n' "$1" "$2"; }
no(){   printf '  MISSING %-14s %s\n' "$1" "$2"; BAD=1; }
note(){ printf '  note    %-14s %s\n' "$1" "$2"; }

echo "editor-v2 doctor  ($OS $ARCH)"

# ── Node.js 22+ ─────────────────────────────────────────────────────────────
if command -v node >/dev/null 2>&1; then
  NV="$(node -v | sed 's/^v//')"
  if [ "${NV%%.*}" -ge 22 ] 2>/dev/null; then
    ok node "v$NV"
  else
    no node "v$NV is too old, need 22+: update with mise or from https://nodejs.org"
  fi
else
  no node "Node.js 22+ not found: install via mise or https://nodejs.org"
fi

# ── ffmpeg / ffprobe, with libvpx-vp9 ───────────────────────────────────────
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  FF_VER="$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"
  ok ffmpeg "$FF_VER"
  if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libvpx-vp9; then
    ok vp9 "libvpx-vp9 encoder present"
  else
    no vp9 "libvpx-vp9 encoder missing in ffmpeg (required for alpha cutout export)"
  fi
else
  no ffmpeg "ffmpeg and ffprobe are required: install via package manager"
fi

# ── Finishing editor: Concat (default) / Kdenlive (optional) ────────────────
CONCAT_BIN="${EV2_CONCAT_BIN:-$(command -v concat 2>/dev/null || true)}"
[ -z "$CONCAT_BIN" ] && [ -x "$HOME/.local/share/concat/concat" ] && CONCAT_BIN="$HOME/.local/share/concat/concat"
if [ -n "$CONCAT_BIN" ] && CV="$("$CONCAT_BIN" --version 2>/dev/null | grep -io 'concat [0-9.]*' | head -1)" && [ -n "$CV" ]; then
  ok concat "$CV ($CONCAT_BIN) - default editor, projects are checked headless"
elif [ "$EV2_EDITOR" = "concat" ] || [ "$EV2_EDITOR" = "both" ]; then
  no concat "Concat not found but EV2_EDITOR=$EV2_EDITOR: install from https://concat.standalones.org or set EV2_EDITOR=kdenlive|none"
else
  note concat "Concat not found (EV2_EDITOR=$EV2_EDITOR)"
fi
if command -v kdenlive >/dev/null 2>&1; then
  ok kdenlive "$(kdenlive --version 2>/dev/null | head -1) (optional: ev2 finish --editor kdenlive)"
else
  note kdenlive "kdenlive not found (optional)"
fi
if command -v hype >/dev/null 2>&1; then
  ok hype "$(hype --version 2>/dev/null | head -1) (optional: Hype slides in explainer inserts)"
else
  note hype "hype not found (optional: Hype slides in explainer inserts)"
fi

# ── Chromium / Chrome ───────────────────────────────────────────────────────
CH=""
for c in "${CHROME_PATH:-}" \
         "$(command -v chromium 2>/dev/null)" \
         "$(command -v google-chrome 2>/dev/null)" \
         "$(command -v google-chrome-stable 2>/dev/null)" \
         "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
  if [ -n "$c" ] && [ -x "$c" ]; then CH="$c"; break; fi
done
if [ -n "$CH" ]; then
  CH_VER="$("$CH" --version 2>/dev/null | head -1)"
  ok chromium "$CH ($CH_VER)"
else
  note chromium "chromium / google-chrome not found: install via your package manager"
fi

# ── yt-dlp ──────────────────────────────────────────────────────────────────
if command -v yt-dlp >/dev/null 2>&1; then
  ok yt-dlp "$(yt-dlp --version 2>/dev/null)"
else
  note yt-dlp "yt-dlp not found (optional: for pulling b-roll clips: pacman -S yt-dlp)"
fi

# ── HyperFrames + Headless Chrome ───────────────────────────────────────────
if command -v npx >/dev/null 2>&1; then
  HV="$(hf --version 2>/dev/null | tail -1)"
  if [ -n "$HV" ]; then
    ok hyperframes "$HV (pinned; override with HF_VERSION)"
  else
    no hyperframes "npx -y hyperframes@$HF_VERSION --version failed: check internet connection"
  fi
  if hf browser ensure >/dev/null 2>&1; then
    ok render-chrome "$(hf browser path 2>/dev/null | tail -1)"
  elif [ -n "$CH" ]; then
    ok render-chrome "$CH (fallback system chrome)"
  else
    no render-chrome "hyperframes browser setup failed: check connection"
  fi
else
  no hyperframes "npx not found (requires Node.js)"
fi

# ── Python 3.11+ & Private Virtualenv ───────────────────────────────────────
VENV="$EV2_HOME/venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "  ..      venv           creating $VENV (no sudo, isolated private venv)"
  mkdir -p "$EV2_HOME"
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" --python 3.11 >/dev/null 2>&1 || uv venv "$VENV" >/dev/null 2>&1
  fi
  if [ ! -x "$VENV/bin/python" ] && command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$VENV" >/dev/null 2>&1
  fi
fi

if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
  no python "$("$VENV/bin/python" -V 2>&1) in $VENV is outside 3.10-3.13 (faster-whisper/opencv wheels): rm -rf $VENV && install uv, then re-run doctor"
fi
if [ -x "$VENV/bin/python" ]; then
  EV2_PY="$VENV/bin/python"
  ok python "$("$EV2_PY" -V 2>&1 | awk '{print $2}') ($VENV)"

  # Core Python dependencies
  if ! "$EV2_PY" -c 'import numpy, cv2, PIL, soundfile' 2>/dev/null; then
    echo "  ..      packages       installing numpy, opencv-python-headless, pillow, soundfile"
    if command -v uv >/dev/null 2>&1; then
      VIRTUAL_ENV="$VENV" uv pip install numpy opencv-python-headless pillow soundfile >/dev/null 2>&1
    else
      "$VENV/bin/pip" install -q numpy opencv-python-headless pillow soundfile >/dev/null 2>&1
    fi
  fi

  if "$EV2_PY" -c 'import numpy, cv2, PIL, soundfile' 2>/dev/null; then
    ok packages "numpy opencv-python-headless pillow soundfile"
  else
    no packages "pip install of required python packages into $VENV failed"
  fi

  # Speech transcription: faster-whisper
  if [ $SPEECH -eq 1 ] && ! "$EV2_PY" -c 'import faster_whisper' 2>/dev/null; then
    echo "  ..      speech         installing faster-whisper into venv"
    if command -v uv >/dev/null 2>&1; then
      VIRTUAL_ENV="$VENV" uv pip install faster-whisper >/dev/null 2>&1
    else
      "$VENV/bin/pip" install -q faster-whisper >/dev/null 2>&1
    fi
  fi

  if "$EV2_PY" -c 'import faster_whisper' 2>/dev/null; then
    FW_VER="$("$EV2_PY" -c 'import faster_whisper; print(faster_whisper.__version__)')"
    ok speech "faster-whisper $FW_VER"
    WM="${EV2_WHISPER_MODEL:-large-v3-turbo}"
    CACHED="$(ls -d "$HOME"/.cache/huggingface/hub/models--*faster-whisper-* 2>/dev/null | sed 's/.*faster-whisper-//' | paste -sd' ' -)"
    if [ -f "$WM/model.bin" ]; then
      ok whisper-model "$WM (local converted model)"
    elif ls -d "$HOME"/.cache/huggingface/hub/models--*faster-whisper-"$WM" >/dev/null 2>&1; then
      ok whisper-model "$WM cached (also: ${CACHED:-none})"
    else
      note whisper-model "$WM not cached yet: first transcribe downloads it (~1.6 GB for large-v3-turbo). Cached: ${CACHED:-none}"
    fi
    if [ ! -f "${EV2_WHISPER_MODEL:-/nonexistent}/model.bin" ]; then
      note darija-model "no Darija fine-tune set: ev2 convert-model amineouaki/whisper-medium-darija-combined (see SKILL.md Setup)"
    fi
  else
    no speech "faster-whisper not installed (transcription will not work): re-run with --install-speech"
  fi

  # Matte / Cut-out: torch + torchvision or rembg
  if [ $MATTE -eq 1 ] && ! "$EV2_PY" -c 'import torch, torchvision' 2>/dev/null && ! "$EV2_PY" -c 'import rembg' 2>/dev/null; then
    echo "  ..      matte          installing torch torchvision (or rembg) into venv"
    if command -v uv >/dev/null 2>&1; then
      VIRTUAL_ENV="$VENV" uv pip install torch torchvision >/dev/null 2>&1 || VIRTUAL_ENV="$VENV" uv pip install rembg onnxruntime >/dev/null 2>&1
    else
      "$VENV/bin/pip" install -q torch torchvision >/dev/null 2>&1 || "$VENV/bin/pip" install -q rembg onnxruntime >/dev/null 2>&1
    fi
  fi

  if "$EV2_PY" -c 'import torch, torchvision' 2>/dev/null; then
    T_VER="$("$EV2_PY" -c 'import torch; print(torch.__version__)')"
    ok matte "PyTorch $T_VER"
  elif "$EV2_PY" -c 'import rembg' 2>/dev/null; then
    ok matte "rembg installed"
  else
    note matte "matte not installed: re-run with --install-matte for background removal"
  fi
else
  no venv "failed to set up private Python virtualenv at $VENV"
fi

# ── GSAP (vendor asset) ─────────────────────────────────────────────────────
GS="$SK/assets/vendor/gsap.min.js"
if [ ! -s "$GS" ] || ! head -c 200 "$GS" | grep -q GSAP; then
  echo "  ..      gsap           downloading gsap.min.js"
  mkdir -p "$SK/assets/vendor"
  curl -fsSL "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js" -o "$GS" 2>/dev/null \
    || curl -fsSL "https://unpkg.com/gsap@3.14.2/dist/gsap.min.js" -o "$GS" 2>/dev/null
fi
if [ -s "$GS" ] && head -c 200 "$GS" | grep -q GSAP; then
  ok gsap "$(head -c 80 "$GS" | grep -o 'GSAP [0-9.]*')"
else
  no gsap "could not download GSAP 3.14.2: check network connection"
fi

# ── Cairo (full Arabic + Latin variable font) ───────────────────────────────
CAIRO_FONT="$SK/assets/fonts/Cairo-Var.ttf"
if [ ! -s "$CAIRO_FONT" ]; then
  echo "  ..      font           downloading Cairo (OFL) variable TTF"
  curl -fsSL "https://github.com/google/fonts/raw/main/ofl/cairo/Cairo%5Bslnt%2Cwght%5D.ttf" -o "$CAIRO_FONT" 2>/dev/null || rm -f "$CAIRO_FONT"
fi
if [ -s "$CAIRO_FONT" ]; then
  ok font-cairo "Cairo-Var.ttf present"
else
  no font-cairo "Cairo-Var.ttf missing in assets/fonts/ (captions and cards need it)"
fi

# ── Face model for webcam tracking (YuNet, OpenCV zoo) ─────────────────────
YUNET="$EV2_HOME/models/yunet.onnx"
if [ ! -s "$YUNET" ]; then
  mkdir -p "$EV2_HOME/models"
  curl -fsSL "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" -o "$YUNET" 2>/dev/null || rm -f "$YUNET"
fi
if [ -s "$YUNET" ]; then
  ok face-model "YuNet ($YUNET)"
else
  note face-model "YuNet download failed: webcam PiP assumes the camera never moves"
fi

# ── Sound kit (synthesized procedural sounds; shipped, only rebuilt if absent) ─
N_SFX=$(ls "$SK"/sfx/ev1kit/*.wav 2>/dev/null | wc -l | tr -d ' ')
if [ "$N_SFX" -eq 0 ] && [ -f "$SK/scripts/synth-sfx.py" ] && [ -x "$EV2_PY" ]; then
  echo "  ..      sfx            sfx/ev1kit is empty: synthesizing via synth-sfx.py"
  "$EV2_PY" "$SK/scripts/synth-sfx.py" >/dev/null 2>&1 || true
  N_SFX=$(ls "$SK"/sfx/ev1kit/*.wav 2>/dev/null | wc -l | tr -d ' ')
fi
if [ ! -f "$SK/sfx/ev1kit/bed_tutorial.wav" ] && [ -f "$SK/scripts/synth-music.py" ] && [ -x "$EV2_PY" ]; then
  echo "  ..      music          bed_tutorial.wav missing: synthesizing via synth-music.py"
  "$EV2_PY" "$SK/scripts/synth-music.py" >/dev/null 2>&1 || true
fi
if [ "$N_SFX" -gt 0 ] && [ -f "$SK/sfx/ev1kit/bed_tutorial.wav" ]; then
  ok sfx "$N_SFX sounds in sfx/ev1kit (incl. bed_tutorial.wav music)"
else
  no sfx "sound kit incomplete in $SK/sfx/ev1kit: run $EV2_PY $SK/scripts/synth-sfx.py and synth-music.py"
fi

# ── ev2 command on PATH ────────────────────────────────────────────────────
EV2_LINK="$HOME/.local/bin/ev2"
if [ "$(readlink -f "$EV2_LINK" 2>/dev/null)" != "$SK/scripts/ev2" ]; then
  mkdir -p "$HOME/.local/bin"
  if [ -e "$EV2_LINK" ] && [ ! -L "$EV2_LINK" ]; then
    mv "$EV2_LINK" "$EV2_LINK.old-$(date +%Y%m%d%H%M%S)"
    echo "  ..      ev2            moved the old standalone ev2 wrapper aside"
  fi
  chmod +x "$SK/scripts/ev2"
  ln -sfn "$SK/scripts/ev2" "$EV2_LINK"
fi
if [ "$(readlink -f "$EV2_LINK" 2>/dev/null)" = "$SK/scripts/ev2" ]; then
  ok ev2 "$EV2_LINK -> $SK/scripts/ev2"
else
  no ev2 "could not link $EV2_LINK; call: bash $SK/scripts/ev2 <command>"
fi

# ── input logger (optional: exact zoom-to-click, click ripples, shortcut pills) ──
if [ "$(systemctl --user is-active ev2-rec.service 2>/dev/null)" = active ]; then
  ok rec "input logger running (ev2 rec status)"
else
  note rec "input logger off: run 'ev2 rec install' before recording for exact clicks"
fi
if ! ls /dev/input/event* >/dev/null 2>&1 || [ ! -r "$(ls /dev/input/event* 2>/dev/null | head -1)" ]; then
  note input "clicks/shortcut keys not readable: sudo usermod -aG input \$USER (then re-login)"
fi

echo
if [ $BAD -eq 0 ]; then
  echo "All set"
  exit 0
fi

echo "Not ready yet: check the MISSING items above, then re-run doctor.sh."
exit 1
