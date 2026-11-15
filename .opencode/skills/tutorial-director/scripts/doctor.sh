#!/usr/bin/env bash
# doctor.sh — check (and with --install, set up) everything tutorial-director needs per user.
#
# Usage:
#   bash ~/.agents/skills/tutorial-director/scripts/doctor.sh
#   bash ~/.agents/skills/tutorial-director/scripts/doctor.sh --install

set -u

TD="$(cd "$(dirname "$0")/.." && pwd)"
TD_HOME="${TD_HOME:-$HOME/tutorial-director}"
TD_CACHE="${TD_CACHE:-$HOME/.cache/tutorial-director}"
TD_MODELS="${TD_MODELS:-$HOME/Models}"
export TD_HOME TD_CACHE TD_MODELS

INSTALL=0
for a in "$@"; do
  case "$a" in
    --install) INSTALL=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: doctor.sh [--install]

Checks per-user prerequisites for tutorial-director:
  - Hyprland session, hyprctl, wtype, grim, gpu-screen-recorder, ffmpeg, tesseract
  - ydotool + ydotoold (with --install: writes ~/.config/systemd/user/td-ydotoold.service)
  - input group membership and /dev/uinput access
  - Python venv at ~/.cache/tutorial-director/venv (with --install: installs core deps)
  - Darija TTS models at $TD_MODELS (default ~/Models) and TTS engine venvs
  - NVIDIA GPU (nvidia-smi), editor-v2 (ev2), and ~/.local/bin/td symlink
USAGE
      exit 0
      ;;
  esac
done

# Ensure common user/system bins are on PATH in non-interactive shells.
for _p in /usr/bin /usr/local/bin "$HOME/.local/bin" \
          "$HOME/.local/share/mise/installs/uv/latest/.mise-bins" \
          "$HOME/.local/share/mise/shims" "$TD_CACHE/bin"; do
  case ":$PATH:" in
    *":$_p:"*) ;;
    *) [ -d "$_p" ] && PATH="$_p:$PATH" ;;
  esac
done
unset _p
export PATH

OS="$(uname -s)"
ARCH="$(uname -m)"
BAD=0

ok()   { printf '  ok      %-16s %s\n' "$1" "$2"; }
no()   { printf '  MISSING %-16s %s\n' "$1" "$2"; BAD=1; }
note() { printf '  note    %-16s %s\n' "$1" "$2"; }

echo "tutorial-director doctor  ($OS $ARCH, user=$USER)"

# ── Hyprland session & hyprctl ──────────────────────────────────────────────
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && [ -S "$RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket.sock" ]; then
  ok hyprland "session active ($HYPRLAND_INSTANCE_SIGNATURE)"
elif [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
  ok hyprland "HYPRLAND_INSTANCE_SIGNATURE=$HYPRLAND_INSTANCE_SIGNATURE"
else
  no hyprland "HYPRLAND_INSTANCE_SIGNATURE not set (run inside a Hyprland session)"
fi

if command -v hyprctl >/dev/null 2>&1; then
  ok hyprctl "$(command -v hyprctl)"
else
  no hyprctl "hyprctl not found: install hyprland (sudo pacman -S hyprland)"
fi

# ── ydotool + ydotoold (per-user systemd service) ───────────────────────────
YDOTOOL_BIN="$(command -v ydotool 2>/dev/null || true)"
YDOTOOLD_BIN="$(command -v ydotoold 2>/dev/null || true)"
if [ -n "$YDOTOOL_BIN" ] && [ -n "$YDOTOOLD_BIN" ]; then
  ok ydotool "$YDOTOOL_BIN / $YDOTOOLD_BIN"
else
  no ydotool "ydotool / ydotoold not found: sudo pacman -S ydotool"
fi

UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/td-ydotoold.service"
YDO_SOCK="$RUNTIME_DIR/.ydotool_socket"

if [ $INSTALL -eq 1 ] && [ -n "$YDOTOOLD_BIN" ]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_FILE" <<EOF
[Unit]
Description=tutorial-director ydotoold input daemon
After=graphical-session.target

[Service]
Type=simple
Environment=YDOTOOL_SOCKET=%t/.ydotool_socket
ExecStart=$YDOTOOLD_BIN --socket-path=%t/.ydotool_socket
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    if [ -w /dev/uinput ]; then
      systemctl --user enable --now td-ydotoold.service >/dev/null 2>&1 || true
    else
      systemctl --user enable td-ydotoold.service >/dev/null 2>&1 || true
    fi
  fi
fi

if command -v systemctl >/dev/null 2>&1 && [ "$(systemctl --user is-active td-ydotoold.service 2>/dev/null || true)" = "active" ]; then
  ok ydotoold "td-ydotoold.service active ($YDO_SOCK)"
elif [ -S "$YDO_SOCK" ] || pgrep -u "$(id -u)" -x ydotoold >/dev/null 2>&1; then
  ok ydotoold "ydotoold running"
elif [ -n "$YDOTOOLD_BIN" ] && [ -f "$UNIT_FILE" ]; then
  no ydotoold "td-ydotoold.service not active: systemctl --user enable --now td-ydotoold.service"
elif [ -n "$YDOTOOLD_BIN" ]; then
  no ydotoold "ydotoold user service not configured: re-run with --install to create $UNIT_FILE"
else
  no ydotoold "ydotoold not running (install ydotool, then re-run with --install)"
fi

# ── input group & /dev/uinput ───────────────────────────────────────────────
if id -nG 2>/dev/null | grep -qw input; then
  ok input-group "user '$USER' is in 'input' group"
else
  no input-group "user '$USER' missing from 'input' group: sudo usermod -aG input $USER  (then re-login)"
fi

if [ -w /dev/uinput ]; then
  ok uinput "/dev/uinput writable"
else
  no uinput "/dev/uinput not writable: echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' | sudo tee /etc/udev/rules.d/80-uinput.rules && sudo udevadm control --reload-rules && sudo udevadm trigger"
fi

# ── Desktop driving & capture tools ─────────────────────────────────────────
if command -v wtype >/dev/null 2>&1; then
  ok wtype "$(command -v wtype)"
else
  no wtype "wtype not found: sudo pacman -S wtype"
fi

if command -v grim >/dev/null 2>&1; then
  ok grim "$(command -v grim)"
else
  no grim "grim not found: sudo pacman -S grim"
fi

if command -v gpu-screen-recorder >/dev/null 2>&1; then
  ok recorder "gpu-screen-recorder ($(command -v gpu-screen-recorder))"
else
  no recorder "gpu-screen-recorder not found: install gpu-screen-recorder"
fi

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  ok ffmpeg "$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"
else
  no ffmpeg "ffmpeg and ffprobe are required: sudo pacman -S ffmpeg"
fi

if command -v tesseract >/dev/null 2>&1; then
  ok tesseract "$(tesseract --version 2>/dev/null | head -1)"
else
  note tesseract "tesseract not found (optional OCR check: sudo pacman -S tesseract)"
fi

# ── Core Python virtualenv (~/.cache/tutorial-director/venv) ────────────────
VENV="$TD_CACHE/venv"
if [ $INSTALL -eq 1 ]; then
  mkdir -p "$TD_CACHE" "$TD_CACHE/bin"
  case ":$PATH:" in
    *":$TD_CACHE/bin:"*) ;;
    *) export PATH="$TD_CACHE/bin:$PATH" ;;
  esac
fi
if [ $INSTALL -eq 1 ] && [ ! -x "$VENV/bin/python" ]; then
  echo "  ..      venv             creating $VENV (no sudo)"
  if ! command -v uv >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
    echo "  ..      uv               installing private uv into $TD_CACHE/bin"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TD_CACHE/bin" UV_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || true
  fi
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" --python 3.11 >/dev/null 2>&1 || uv venv "$VENV" >/dev/null 2>&1
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$VENV" >/dev/null 2>&1 || true
  fi
fi

if [ -x "$VENV/bin/python" ]; then
  TD_PY="$VENV/bin/python"
  ok python "$("$TD_PY" -V 2>&1 | awk '{print $2}') ($VENV)"
  if [ $INSTALL -eq 1 ] && ! "$TD_PY" -c 'import numpy, cv2, PIL, soundfile, requests' 2>/dev/null; then
    echo "  ..      packages         installing numpy, opencv-python-headless, pillow, soundfile, requests"
    if command -v uv >/dev/null 2>&1; then
      VIRTUAL_ENV="$VENV" uv pip install numpy opencv-python-headless pillow soundfile requests >/dev/null 2>&1 || true
    else
      "$VENV/bin/pip" install -q numpy opencv-python-headless pillow soundfile requests >/dev/null 2>&1 || true
    fi
  fi
  if "$TD_PY" -c 'import numpy, cv2, PIL, soundfile, requests' 2>/dev/null; then
    ok packages "numpy opencv-python-headless pillow soundfile requests"
  else
    no packages "core python packages missing in $VENV: re-run with --install"
  fi
else
  no venv "venv missing at $VENV: re-run with --install"
fi

# ── Darija TTS Models (${TD_MODELS:-~/Models}) ──────────────────────────────
_find_model_dir() {
  local pat="$1" d
  [ -d "$TD_MODELS" ] && [ -r "$TD_MODELS" ] || return 1
  for d in "$TD_MODELS"/${pat}*; do
    if [ -d "$d" ] && [ -r "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
      printf '%s\n' "$d"
      return 0
    fi
  done
  return 1
}

GOLHA_DIR="$(_find_model_dir golha || true)"
LAHGTNA_DIR="$(_find_model_dir lahgtna || true)"

if [ -n "$GOLHA_DIR" ] && [ -n "$LAHGTNA_DIR" ]; then
  ok models "golha ($GOLHA_DIR) & lahgtna ($LAHGTNA_DIR)"
else
  if [ ! -d "$TD_MODELS" ] || [ ! -r "$TD_MODELS" ]; then
    no models "models directory not readable at $TD_MODELS"
  else
    [ -z "$GOLHA_DIR" ] && no model-golha "golha model not found/readable in $TD_MODELS" || ok model-golha "$GOLHA_DIR"
    [ -z "$LAHGTNA_DIR" ] && no model-lahgtna "lahgtna model not found/readable in $TD_MODELS" || ok model-lahgtna "$LAHGTNA_DIR"
  fi
  note models-share "to share models read-only for a fresh user:"
  printf '                     sudo mkdir -p /srv/td-models && sudo cp -r ~/Models/* /srv/td-models/\n'
  printf '                     sudo chmod -R a+rX /srv/td-models && export TD_MODELS=/srv/td-models\n'
fi

# ── TTS Engine venvs ($TD/scripts/tts/setup.sh) ─────────────────────────────
TTS_SETUP="$TD/scripts/tts/setup.sh"
if [ -f "$TTS_SETUP" ]; then
  for eng in golha lahgtna; do
    TTS_SETUP_OK=1
    if [ $INSTALL -eq 1 ]; then
      echo "  ..      tts-$eng          running $TTS_SETUP $eng"
      rc=0
      bash "$TTS_SETUP" "$eng" || rc=$?
      if [ $rc -ne 0 ]; then
        TTS_SETUP_OK=0
        no "tts-$eng" "setup failed (exit $rc): re-run bash $TTS_SETUP $eng"
      fi
    fi
    if [ $TTS_SETUP_OK -eq 1 ]; then
      ENG_VENV=""
      for cand in "$TD_CACHE/venvs/$eng" "$TD_CACHE/venv-$eng" "$TD_CACHE/$eng"; do
        if [ -x "$cand/bin/python" ]; then
          ENG_VENV="$cand"
          break
        fi
      done
      if [ -n "$ENG_VENV" ]; then
        ok "tts-$eng" "$ENG_VENV"
      elif [ $INSTALL -eq 1 ]; then
        no "tts-$eng" "engine venv missing after running $TTS_SETUP $eng"
      else
        note "tts-$eng" "engine venv not checked/found (run: bash $TTS_SETUP $eng)"
      fi
    fi
  done
else
  note tts-venvs "$TTS_SETUP not present yet (skipping TTS engine setup)"
fi

# ── CUDA GPU (nvidia-smi) ───────────────────────────────────────────────────
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
  ok gpu "${GPU_NAME:-NVIDIA CUDA GPU}"
else
  note gpu "nvidia-smi unavailable or no CUDA GPU detected (CPU fallback)"
fi

# ── editor-v2 (ev2) ─────────────────────────────────────────────────────────
EV2_BIN="$(command -v ev2 2>/dev/null || true)"
[ -z "$EV2_BIN" ] && [ -x "$HOME/.local/bin/ev2" ] && EV2_BIN="$HOME/.local/bin/ev2"
if [ -n "$EV2_BIN" ]; then
  ok ev2 "$EV2_BIN"
else
  no ev2 "ev2 not found on PATH: run bash ~/.agents/skills/editor-v2/scripts/doctor.sh"
fi

# ── td CLI symlink (~/.local/bin/td -> $TD/scripts/td) ──────────────────────
TD_BIN="$TD/scripts/td"
TD_LINK="$HOME/.local/bin/td"
if [ -f "$TD_BIN" ]; then
  if [ $INSTALL -eq 1 ] && [ "$(readlink -f "$TD_LINK" 2>/dev/null || true)" != "$(readlink -f "$TD_BIN" 2>/dev/null || echo "$TD_BIN")" ]; then
    mkdir -p "$HOME/.local/bin"
    chmod +x "$TD_BIN"
    ln -sfn "$TD_BIN" "$TD_LINK"
  fi
  if [ "$(readlink -f "$TD_LINK" 2>/dev/null || true)" = "$(readlink -f "$TD_BIN" 2>/dev/null || echo "$TD_BIN")" ]; then
    ok td "$TD_LINK -> $TD_BIN"
  else
    no td "$TD_LINK not linked to $TD_BIN: re-run with --install"
  fi
else
  note td "$TD_BIN not created yet (symlink will be set up once task-01 creates it)"
fi

echo
if [ $BAD -eq 0 ]; then
  echo "All set"
  exit 0
fi

echo "Not ready yet: check the MISSING items above, then re-run doctor.sh."
exit 1
