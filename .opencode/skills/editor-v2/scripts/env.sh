#!/usr/bin/env bash
# env.sh — source this at the top of every script: source "<skill>/scripts/env.sh"
#
# Sets up PATH for non-interactive shells, pins the renderer version,
# and points EV2_PY / EV1_PY at the kit's private Python environment.
# Every line must exit 0: callers run under `set -e`.

_ev2_add(){ case ":$PATH:" in *":$1:"*) ;; *) if [ -d "$1" ]; then PATH="$1:$PATH"; fi;; esac; return 0; }
_ev2_add /usr/bin
_ev2_add /usr/local/bin
_ev2_add "$HOME/.local/bin"
_ev2_add "$HOME/.local/share/mise/installs/python/latest/bin"
_ev2_add "$HOME/.local/share/mise/installs/node/latest/bin"
_ev2_add "$HOME/.local/share/mise/shims"
export PATH
export PYTHONDONTWRITEBYTECODE=1   # keep __pycache__ out of the skill folder

# the renderer, pinned (override: export HF_VERSION=latest). Every caller goes through hf().
export HF_VERSION="${HF_VERSION:-0.8.181}"
hf(){ npx -y "hyperframes@${HF_VERSION}" "$@"; }

# finishing editor for `ev2 finish`: concat (default) | kdenlive | both | none
if [ -z "${EV2_EDITOR:-}" ]; then
  # Concat when it is installed, else no editor project (final.mp4 is still made); set EV2_EDITOR to force one
  if command -v concat >/dev/null 2>&1 || [ -x "$HOME/.local/share/concat/concat" ]; then EV2_EDITOR=concat; else EV2_EDITOR=none; fi
fi
export EV2_EDITOR

# the kit's private cache and Python
export EV2_HOME="$HOME/.cache/editor-v2"
_ev2_add "$EV2_HOME/bin"          # the private uv that doctor installs when the system has none
export EV1_HOME="$EV2_HOME"

if [ -x "$EV2_HOME/venv/bin/python" ]; then
  EV2_PY="$EV2_HOME/venv/bin/python"
else
  EV2_PY="$(command -v python3 2>/dev/null || echo python3)"
fi
export EV2_PY
export EV1_PY="$EV2_PY"

true
