---
name: tutorial-director
description: "Makes a whole Darija screen tutorial with AI: writes the script, speaks it with local Darija TTS (golha or lahgtna), drives the Omarchy desktop (mouse, keyboard, windows, workspaces) while recording, and hands the recording to editor-v2. Use when the user wants the AI to record a tutorial by itself, automated screencast, TTS tutorial, td, tutorial-director."
---

# tutorial-director (`td`)

Creates a Moroccan Darija screen tutorial end-to-end — writes `script.json`, speaks it with local Darija TTS (`golha` or `lahgtna`), drives the desktop while recording, and exports `<run>/handoff/` — and **pairs with `editor-v2`** (`ev2`), which edits the hook, zooms, inserts, chapters, music, Short, and final verification. Runs live in `~/tutorial-director/runs/<name>/`; see [reference/script-format.md](reference/script-format.md) and [reference/handoff.md](reference/handoff.md).

## Before the first run (user does once; agent checks with `td doctor`)
- `sudo pacman -S ydotool`: mouse/keyboard control. Required.
- The user must be in the `input` group: `sudo usermod -aG input $USER`, then log out and in.
  For every new Linux user that will record: `sudo usermod -aG input <user>` + re-login.
- Optional, to find buttons by their text: `sudo pacman -S tesseract tesseract-data-ara tesseract-data-eng tesseract-data-fra`.
- New user only: share the TTS models read-only (`sudo mkdir -p /srv/td-models && sudo cp -r ~/Models/* /srv/td-models/`)
  and `export TD_MODELS=/srv/td-models` in that user's shell; then run `td doctor --install` inside that user's Hyprland session.
- Emergency stop hotkey in `~/.config/hypr/bindings.conf`: `bind = SUPER CTRL, Escape, exec, td stop`.
If `td doctor` shows a MISSING line, stop and give the user the exact command above; continue only after `All set`.

Never run `sudo` yourself.

## Setup (once per user/machine)

Run `td doctor --install` (links `~/.local/bin/td`, sets up `td-ydotoold` and venvs), then `td voice test` so the creator compares `golha` vs `lahgtna` and picks `voice.engine`.

## Workflow (follow in order; stop at every STOP gate)

| # | Command | Agent does |
|---|---|---|
| 1 | `td new <name>` | Scaffolds `~/tutorial-director/runs/<name>/` from `templates/script.json`. |
| 2 | write `script.json` | From the creator's brief; Darija sentences <= 220 chars, Latin tech terms kept; one chapter per topic; an insert about every 60 s. |
| 3 | `td check <run>` | Fix every `FIX` (and review `TIP`s) until `ready` → **STOP: creator approves the script**. |
| 4 | `td voice render <run>` | First time per engine/voice: creator listens to 2 steps → **STOP: approve**. |
| 5 | `td dry <run>` | Read `dry/report.md`, **view every check screenshot**; fix the script if needed → **STOP: show the creator**. |
| 6 | `td record <run>` | Hands off the desktop; tell the creator not to touch mouse/keyboard (`Super+Ctrl+Esc` stops). |
| 7 | `td handoff <run>` | Run `ev2 init --from-director <run>/handoff <name>`, then follow `editor-v2` (`ev2 transcribe` with no ASR, PLAN gate, `ev2 hook --final`, `ev2 inserts --final`, `ev2 finish`). |

## Writing rules for good-looking videos

- **Same structure every video** (`templates/script.json`): hook line (the result first) → 3–5 chapters (`<= 40` chars, `"EN — AR"`) → an explainer insert about every 60 s (creator may choose 120 s) → a 1-step recap at the end.
- **Show, then explain**: the screen action happens first, the explainer/insert comes after it.
- **Short spoken lines**: one idea per sentence, `<= 15` words; keep Latin tech terms as written; pronunciation fixes go in `~/.config/tutorial-director/pronounce.json`.
- **Clean framing**: every window used gets a `layout` slot (fixed position/size); keep big text (`studio` defaults).
- **Plan visuals in `script.json`**: define `insert` (recipes) and `callout` on steps so `td handoff` forwards exact timings to `editor-v2`.

## Safety & YouTube

- **Safety**: never run `sudo`; never type secrets or open password managers, mail, or banking; ask before acting outside the recording workspace; on any failure stop and report — never improvise inputs live.
- **YouTube**: tick **"altered or synthetic content"** when uploading (AI voice).

## Common failures

| Failure | Fix |
|---|---|
| `ydotoold` not running | Run `td doctor --install` (or `systemctl --user restart td-ydotoold`). |
| `input` group missing | Ask user to run `sudo usermod -aG input $USER` and re-login. |
| Window not found | Verify Hyprland class/title (`hyprctl clients -j`), add `wait_for` or increase `timeout`. |
| Image not found | Re-crop template PNG at native display scale or switch to `window` + `at` / OCR target. |
| OCR missing | Ask user to install `tesseract` + `tesseract-data-{ara,eng,fra}` or use `window`/`image`. |
| TTS venv missing | Run `td doctor --install` (or `bash scripts/tts/setup.sh`). |
| GPU busy | Close other GPU workloads (or wait for ASR/render) and retry `td voice render`. |
| `record` refused | Run `td dry <run>` (and `td voice render <run>`) after any `script.json` edit. |
| Modifiers stuck | Run `td stop` (or press `Super+Ctrl+Esc`) to abort and release all held keys/buttons. |
