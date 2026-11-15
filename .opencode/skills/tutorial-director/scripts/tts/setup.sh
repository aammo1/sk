#!/usr/bin/env bash
# setup.sh — Idempotently create per-engine TTS virtualenvs under ~/.cache/tutorial-director/venvs/.
# Usage:
#   bash setup.sh golha
#   bash setup.sh lahgtna
#   bash setup.sh all
set -euo pipefail

TD_CACHE="${TD_CACHE:-$HOME/.cache/tutorial-director}"
TD_MODELS="${TD_MODELS:-$HOME/Models}"
VENV_ROOT="$TD_CACHE/venvs"

usage() {
  cat <<'EOF'
Usage: setup.sh <golha|lahgtna|all>

Creates isolated per-engine virtualenvs under:
  ${TD_CACHE:-~/.cache/tutorial-director}/venvs/<engine>
Never touches editor-v2's virtualenv.
EOF
}

if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage
  exit 0
fi

TARGET="$1"

has_cuda() {
  command -v nvidia-smi >/dev/null 2>&1 || [ -e /dev/nvidiactl ]
}

ensure_venv() {
  local venv="$1"
  local pyver="$2"
  mkdir -p "$(dirname "$venv")"
  if [ -x "$venv/bin/python" ]; then
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    echo "[setup] creating venv $venv (Python $pyver via uv)..."
    uv venv --python "$pyver" "$venv"
  elif command -v "python$pyver" >/dev/null 2>&1; then
    echo "[setup] creating venv $venv (python$pyver -m venv)..."
    "python$pyver" -m venv "$venv"
  elif command -v python3 >/dev/null 2>&1; then
    echo "[setup] warning: uv and python$pyver not found; falling back to python3" >&2
    python3 -m venv "$venv"
  else
    echo "[setup] ERROR: neither uv nor python3 found. Install uv or python$pyver first." >&2
    exit 1
  fi
}

pip_install() {
  local venv="$1"; shift
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$venv/bin/python" "$@"
  else
    "$venv/bin/python" -m pip install --upgrade pip >/dev/null
    "$venv/bin/python" -m pip install "$@"
  fi
}

setup_golha() {
  local venv="$VENV_ROOT/golha"
  local mdir="$TD_MODELS/golha-darija-tts"
  local req="$mdir/requirements.txt"

  ensure_venv "$venv" "3.12"

  # Idempotency check: skip heavy install if core imports and pinned versions are already present.
  if "$venv/bin/python" -c "import torch, transformers, peft, fastapi, uvicorn, soundfile, num2words; assert torch.__version__.startswith('2.6.0'); assert transformers.__version__ == '4.46.3'" >/dev/null 2>&1; then
    echo "[golha] venv already healthy at $venv"
  else
    local torch_idx="${TD_GOLHA_TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
    if has_cuda; then
      echo "[golha] installing torch==2.6.0 (CUDA) into $venv..."
      pip_install "$venv" --index-url "$torch_idx" \
        torch==2.6.0 torchaudio==2.6.0 torchvision==0.21.0
    else
      echo "[golha] no NVIDIA GPU detected; installing CPU torch==2.6.0 into $venv..."
      pip_install "$venv" torch==2.6.0 torchaudio==2.6.0 torchvision==0.21.0
    fi

    if [ -f "$req" ]; then
      echo "[golha] installing requirements from $req..."
      pip_install "$venv" -r "$req"
    else
      echo "[golha] warning: $req not found; installing pinned core deps..." >&2
      pip_install "$venv" \
        transformers==4.46.3 peft==0.17.1 chatterbox-tts==0.1.2 \
        huggingface_hub fastapi==0.141.1 uvicorn==0.54.0 pydantic \
        silero-vad==6.2.0 librosa==0.11.0 soundfile==0.13.1 num2words pyloudnorm safetensors
    fi

    "$venv/bin/python" -c "import torch, transformers, peft, fastapi, soundfile; print('[golha] verified torch', torch.__version__, 'transformers', transformers.__version__)"
  fi

  local pdir="$mdir/pretrained_models"
  if [ -d "$mdir" ] && [ -f "$mdir/fetch_base_model.py" ]; then
    if [ ! -f "$pdir/t3_mtl23ls_v2.safetensors" ] || [ ! -f "$pdir/ve.pt" ] || [ ! -f "$pdir/s3gen.pt" ] || [ ! -f "$pdir/conds.pt" ]; then
      echo "[golha] fetching Chatterbox base model (~3 GB) via fetch_base_model.py..."
      "$venv/bin/python" "$mdir/fetch_base_model.py"
    else
      echo "[golha] base model weights already present in $pdir"
    fi
  else
    echo "[golha] note: model dir $mdir not present yet (skipping fetch_base_model.py)"
  fi
}

setup_lahgtna() {
  local venv="$VENV_ROOT/lahgtna"
  local repo_url="${TD_LAHGTNA_REPO:-git+https://github.com/Oddadmix/Lahgtna-OmniVoice.git}"

  ensure_venv "$venv" "3.12"

  if "$venv/bin/python" -c "import torch, transformers, soundfile, omnivoice" >/dev/null 2>&1; then
    echo "[lahgtna] venv already healthy at $venv"
    return 0
  fi

  local torch_idx="${TD_LAHGTNA_TORCH_INDEX:-https://download.pytorch.org/whl/cu128}"
  if has_cuda; then
    echo "[lahgtna] installing PyTorch (CUDA) into $venv..."
    pip_install "$venv" --index-url "$torch_idx" torch torchaudio
  else
    echo "[lahgtna] no NVIDIA GPU detected; installing CPU PyTorch into $venv..."
    pip_install "$venv" torch torchaudio
  fi

  echo "[lahgtna] installing Lahgtna-OmniVoice ($repo_url)..."
  pip_install "$venv" "$repo_url" "transformers>=5.3.0" accelerate soundfile librosa

  "$venv/bin/python" -c "import torch, transformers, soundfile, omnivoice; print('[lahgtna] verified torch', torch.__version__, 'transformers', transformers.__version__)"
}

case "$TARGET" in
  golha)   setup_golha ;;
  lahgtna) setup_lahgtna ;;
  all)     setup_golha; setup_lahgtna ;;
  *)
    echo "Unknown engine '$TARGET' (expected: golha | lahgtna | all)" >&2
    exit 2
    ;;
esac
