#!/usr/bin/env bash
# convert-model.sh — turn a Hugging Face Whisper model (e.g. a Darija fine-tune) into a
# faster-whisper (CTranslate2) model usable with `ev2 transcribe <dir> --model <output dir>`.
#
#   bash convert-model.sh <hf-repo-id> [quantization]     (default quantization: int8)
#   bash convert-model.sh amineouaki/whisper-medium-darija-combined
#
# Output: ~/.cache/editor-v2/models/<repo-name>-ct2. Needs ~2-4 GB of downloads the first time
# (CPU torch + transformers into the kit venv, then the model). Full models only: LoRA adapters
# must be merged into their base model first.
set -euo pipefail
SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"
REPO="${1:?usage: convert-model.sh <hf-repo-id> [int8|float16|float32]}"
Q="${2:-int8}"
OUT="$EV2_HOME/models/$(basename "$REPO")-ct2"
VENV="$EV2_HOME/venv"
if ! "$EV2_PY" -c 'import transformers, torch' 2>/dev/null; then
  echo "convert-model: installing CPU torch + transformers into $VENV (one time)"
  if command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="$VENV" uv pip install --index-url https://download.pytorch.org/whl/cpu torch
    VIRTUAL_ENV="$VENV" uv pip install transformers
  else
    "$VENV/bin/pip" install --index-url https://download.pytorch.org/whl/cpu torch
    "$VENV/bin/pip" install transformers
  fi
fi
CONV="$VENV/bin/ct2-transformers-converter"
[ -x "$CONV" ] || { echo "convert-model: $CONV missing (faster-whisper not installed?)" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"
"$CONV" --model "$REPO" --output_dir "$OUT" --quantization "$Q" --force \
  --copy_files tokenizer.json preprocessor_config.json 2>&1 | grep -v "^$" | tail -5 || true
[ -f "$OUT/model.bin" ] || { echo "convert-model: conversion failed" >&2; exit 1; }
echo "convert-model: $OUT"
echo "use it: ev2 transcribe <video-dir> --model $OUT    (or export EV2_WHISPER_MODEL=$OUT)"
