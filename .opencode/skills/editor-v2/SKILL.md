---
name: editor-v2
description: "Edits Omarchy screencast recordings (Moroccan Darija + English tech terms, corner webcam) into a pro-looking YouTube tutorial: a designed hook (promise, montage of the app's own screens, end card) built from a short JSON, a polished body (screen inset on a branded backdrop, zoom-to-click, click ripples, callouts, speaker PiP, chapter cards, quiet music and sound effects), animated explainer inserts from data recipes (flow, steps, checklist, compare, stat, statement, screens), one synced final.mp4, a Concat (or Kdenlive) project, a 9:16 Short and YouTube chapters, all checked by a definition-of-done verifier and a beauty check. Optional: calm style, key-press pills, YouTube description, an input logger for exact clicks. Use when the user wants to edit, cut, caption or finish a recording/screencast/tutorial video, or mentions ev2, editor-v2, the hook, explainer insert, motion graphics, animated explanation, callout, zoom, click effects, Concat or Kdenlive projects for a video, key pills, shortcut overlay, calm style, title card, youtube description."
---

# Editor V2 — Darija screencast → pro YouTube tutorial

One recording in, these out: `out/final.mp4` (hook + polished body, 1920x1080/30, −14 LUFS),
`out/hook.mp4`, `out/concat/` (Concat project), `out/short.mp4` (9:16), `out/youtube-chapters.txt`,
`out/captions.srt`, `out/verify.md` (pass/fail) and `out/beauty.md` (how pro it looks/sounds).

## The rule that makes it look pro: you write DATA, the code designs

Every visual part is a tested design in code. The agent only fills small JSON files:

| file | what you write | what the code does |
|---|---|---|
| `work/hook.json` | one **promise** line (+ brand/title) | picks the best moments, crops the screens clear of the webcam, kinetic title, 3D montage with icon labels, end card with the chapters, music + whooshes, lands seamlessly in the body |
| `work/timeline.json` | chapters, `inserts` with a **recipe** + data, `callouts`, optional `keys` | animated explainer scenes, pointer labels that follow the zoom, chapter cards, sounds |
| `work/look.json` | usually nothing (defaults) | brand colour (auto from the app), inset frame, zoom limit, border trim |

**Do not** write HTML, CSS, GSAP or Python for the hook or the inserts, and do not edit
`build.py`. Copy an example from `reference/recipes.md`, change the words, run `ev2 check <dir>`.
The hand-written path (`ev2 style <dir> custom`, `inserts.py` scenes) exists for experts only, and only when
the creator explicitly asks for something no recipe can show.

**What the body gets automatically** (`scripts/body_render.py`, run by `ev2 finish`):
- **Stage:** the screen as a rounded card with a soft shadow on a backdrop tinted with the app's
  brand colour (`look.frame: "inset"`), window borders/wallpaper slivers trimmed (`look.trim`).
- **Zoom:** with an input log (`ev2 rec`) it eases in on each click a little before it lands, stays
  for nearby clicks/typing, pans to close targets and zooms out after a pause; without one it
  zooms where screen activity stays in a small area. Max 1.6x (`look.max_zoom`), 0.73 s smooth moves.
- **Clicks:** an accent ripple at every logged click, and a soft click sound.
- **Speaker:** the burned-in webcam is painted out and redrawn as a rounded PiP at a fixed corner
  (the same spot the hook uses; it follows if the creator moved the overlay). Fades out during full inserts.
- **Callouts, chapter cards (accent colour + whoosh), key pills** (timeline `keys` + shortcuts from the input log).
- **Inserts:** zoom-through transition in and out, with whooshes.
- **Sound:** voice cleanup, quiet music under the whole body (on by default, 20 LU under the voice),
  sound effects, two-pass −14 LUFS.
- **Gentle cuts:** pauses shortened to 0.3 s (1.2 s when the screen is busy), never removed.

**What it does not do (say so instead of implying otherwise):**
- Exact clicks and shortcuts need the input logger running while recording (`ev2 rec install`) and,
  for clicks/keys, the user in the `input` group. Without it: activity-based zooms, no ripples.
- It never decides chapters, insert moments or callouts by itself: those are agreed at the PLAN gate.
- Captions are Darija in Arabic script; the ASR is imperfect. `out/captions.srt` is not uploaded
  or burned in until a human checked it (the beauty check says when the ASR was unsure).

## Setup (once)
```bash
ev2 doctor --install-speech     # checks everything, links ~/.local/bin/ev2 -> <skill>/scripts/ev2
ev2 rec install                 # logs cursor/clicks/shortcuts while Omarchy records (systemd user service)
sudo usermod -aG input $USER    # the user runs this once (then re-login): lets the logger see clicks and shortcut keys
```
If `ev2` is not on PATH, run `bash ~/.agents/skills/editor-v2/scripts/ev2 <command>` (same commands).
`ev2 rec test` shows what the logger sees. It never stores typed characters, only key timing and
Ctrl/Alt/Super shortcuts, and only while a recording runs.

**Darija transcription model (recommended, once):** generic Whisper turns much of Darija into broken
standard Arabic. `ev2 convert-model amineouaki/whisper-medium-darija-combined` (~30 min, once), then
`export EV2_WHISPER_MODEL=~/.cache/editor-v2/models/whisper-medium-darija-combined-ct2`. Compare with
`ev2 asr-check` before trusting it; transcribe with `--windowed`. Term fixes:
`~/.config/editor-v2/darija-terms.json` (`{"فيرسل": "Vercel"}`), `EV2_HOTWORDS="Vercel, Supabase"`.
Doctor must end with `All set`. A `MISSING` line is a blocker, so fix it before editing.

## The workflow (agent: follow in order, stop where marked)

| # | Command | Agent does |
|---|---|---|
| 1 | `ev2 init <file\|--latest> [name] [--style calm]` | Confirm which recording. Creates `~/editor-v2/videos/<name>/`, reads the input log into `work/inputs.json` if there is one. |
| 2 | `ev2 transcribe <dir>` | Words, `work/timeline.json`, `work/cuts-report.md`. Language `ar`; never `auto` for Darija. Refuses to overwrite a hand-corrected `words.json` (`--force` keeps a backup). |
| 3 | `ev2 hook <dir> --init` | Writes `work/hook.json` with auto-picked shots. Read the list it prints. |
| 4 | **PLAN gate** (below) | Fill `PLAN.md`; write chapters, inserts (recipes), callouts into `work/timeline.json` and the promise into `work/hook.json`. Run `ev2 check <dir>` until `ready`. **STOP and get explicit approval.** |
| 5 | `ev2 hook <dir>` then `ev2 hook <dir> --final` | Renders `out/render.mp4` (~2 min). The final build refuses while `hook.json` has problems. |
| 6 | `ev2 inserts <dir> --final` | Only if the plan has inserts (~35 s each). |
| 7 | `ev2 finish <dir>` | Everything else, then verify + beauty check (~15-25 min for a 6 min video). Preview a few seconds first if you changed the look: `ev2 body <dir> --preview 40,55`. |
| 8 | Read `out/verify.md` (and `out/beauty.md`) | Fix every FAIL (see the table at the end); report every WARN to the user. |
| 9 | `ev2 describe <dir>` | Optional. Fill every `<!-- WRITE -->` slot from `work/description-notes.md`, then `--check`. |

`ev2 finish --editor concat|kdenlive|both|none` (default `concat`, or `EV2_EDITOR`).
Other flags: `--captions`, `--no-keys`, `--no-zoom`, `--no-cam`, `--raw-body` (plain cuts, the fastest; no inserts),
`--no-voice-fx`, `--no-bed`, `--song FILE`, `--bed-under LU`, `--no-body-music`, `--body-under LU`, `--lufs -14`, `--no-open`.
The body render is cached and only redone when its inputs change.

### PLAN gate: what to prepare and what approval means
Show the user `work/cuts-report.md` and the filled `PLAN.md`. Get an explicit "yes" on every box
in PLAN.md's **Approval** section:
1. Hook split (15-30 s, the end of the spoken intro) and final length.
2. Each retake candidate: cut or keep.
3. The transcript spot-checked, tech terms fixed in `work/tx/words.json` (text only, never `s`/`e`).
4. **The promise** in `work/hook.json`: one line, <= 60 chars, a result the viewer gets (not a
   greeting, not the title). Propose 2-3 and let the creator pick. Keep the auto-picked shots unless asked.
5. Body chapters: at least 3, the first at the start of the body, each >= 10 s, titles <= 40 chars,
   one separator style (e.g. `Commandes — اللائحة`). Never invent chapters the speaker did not cover.
6. **Inserts**: one every 2-3 minutes where the speaker explains a concept, as recipes
   (`reference/recipes.md`): moment (source time), recipe, the exact labels. 4-12 s each.
7. **Callouts**: 2-5 on the buttons that matter (source time + <= 40 chars).
8. Every third-party asset licensed (`reference/sourcing.md` › Rights).
9. Optional extras below: each ticked or declined.

Do not run `ev2 hook` without `--init`, `ev2 inserts` or `ev2 finish` before approval. If the user
changes cuts later: `ev2 clean`, then `ev2 finish`; rebuild the hook too if `hook_split` changed.

### Optional extras (the creator chooses)
- **Calm style** (title card over the live screen, for plain walkthroughs): `ev2 init <rec> --style calm`,
  or `ev2 style <dir> calm` (sets `"recipe": "calm"` in hook.json). Back: `ev2 style <dir> documentary`.
- **Key pills**: `ev2 keys <dir>` suggests them from the transcript (`work/keys-suggest.md`); copy the agreed ones
  into `"keys"`. With an input log, real shortcuts become pills automatically (`look.auto_keys`).
- **YouTube description**: `ev2 describe <dir> [--lang darija|en|fr]` after finish. Fill the slots from the notes only.
- **Look changes**: `ev2 look <dir> --accent "#E11D74"` (brand colour), `--frame full`, `--max-zoom 1.4`, `--trim off`.

### The single source of truth: `work/timeline.json`
`clean-retakes.py` writes it; `finish`, `concat-gen`, `kdenlive-gen`, `verify` read it.
- `hook_split`: the hook is source `[0, hook_split)`, uncut, under the designed hook. Change it with
  `ev2 clean <dir> --hook-split 20`, then rebuild the hook.
- `segments`: the body's kept source ranges. Tune with `ev2 clean <dir> --keep 0.3 --busy-keep 1.2 --max-silence 0.6`.
- `chapters`: `[{"src_t": <source seconds>, "title": "..."}]`, written at the PLAN gate.
- `inserts`: `[{"name": "order-flow", "src_t": 126.0, "dur": 8, "recipe": "flow", "data": {...}}]`.
  `name` kebab-case, unique; `src_t` SOURCE seconds (>= hook_split); `dur` 1.5-30 (4-12 is best);
  `recipe` one of flow, steps, checklist, compare, stat, statement, screens (data: `reference/recipes.md`);
  `cam` (default false for full scenes: the PiP fades out). No overlaps, none past the body end.
- `callouts`: `[{"src_t": 91.2, "text": "Confirmer ici", "dur": 3}]` (+ optional `x`, `y` in cam_raw pixels).
- `keys` (optional pills): `[{"src_t": 46.0, "keys": "Super + Space", "label": "...", "dur": 2.5}]`.
- `body_music`: default true; `false` turns the quiet body music off.

Retakes are **reported, not cut**, by default (Darija repeats on purpose). To cut one, set
`"enabled": true` in `work/cuts.json`, then `ev2 clean <dir>`.

### Definition of done
A video is done **only** when `ev2 finish` (or `ev2 verify <dir>`) prints `DONE` and nothing in
`out/verify.md` is FAIL. Besides sync, lengths, formats, staleness and the editor project, verify
runs the **beauty check** (`out/beauty.md`, `out/beauty-sheet.jpg`):
- hook: no black/empty stretch > 0.8 s, nothing frozen > 3.5 s, no face cut by the frame edge (FAIL);
  fewer than 2 cuts per 10 s, two faces at once, < 4 sound effects, > 32 s long (WARN);
- inserts: frozen > 4 s (FAIL), > 2.5 s (WARN);
- body: zoom past 2.0x (FAIL), not inset / no PiP, > 50 s with nothing new on screen, no music (WARN, with where);
- text: internal notes or paths in `out/youtube-description.md` (FAIL); unreliable captions,
  long or inconsistent chapter titles (WARN).
Report every WARN to the user, never hide one. Never say "finished" or "ready to publish" with a FAIL.

## When something fails
| Symptom | Fix |
|---|---|
| `ev2: command not found` | `bash ~/.agents/skills/editor-v2/scripts/ev2 doctor` (creates the link) |
| doctor: `speech MISSING` | `ev2 doctor --install-speech` |
| `check: FIX ...` | Do exactly what the line says, then `ev2 check <dir>` again. |
| `hook: TODO "promise" is empty` / `FINAL refused` | Write the promise in `work/hook.json` (<= 60 chars), then `ev2 hook <dir> --final`. |
| beauty `hook: faces` FAIL | A shot shows a face at the edge: replace that shot's `src_t` in hook.json (or remove it), rebuild. |
| beauty `hook: motion` / `dead air` FAIL | Only possible with `ev2 style custom`: go back to `ev2 style <dir> documentary`. |
| beauty `inserts: motion` FAIL | A hand-written scene is frozen: use a recipe instead. |
| beauty `body: monotony` WARN | Add an insert or a callout at the time it names (ask the creator what to show). |
| beauty `text: description` FAIL | Delete the listed notes/paths from `out/youtube-description.md`. |
| `inserts: fix these in work/timeline.json` | Each line names the insert and the field; fix it there. |
| Transcript has many wrong words | Use the Darija model (Setup), `ev2 asr-check`, fix terms in `darija-terms.json`. |
| `transcribe: ... words.json was edited` | Keep it (skip transcribe), or `--force` (backup kept). |
| verify: `hook build` FAIL | `ev2 hook <dir> --final`, then `ev2 finish <dir>`. |
| verify: `picture sync` / `voice sync` FAIL | Do not publish. Delete `work/body_video.mp4`, re-run `ev2 finish`; `--raw-body` isolates the body renderer. |
| verify: `stale` / `stale chapters` / `stale inserts` / `stale keys` | `ev2 finish <dir>`. |
| finish: `hook render is X s but hook_split is Y s` / `index.html is newer` | `ev2 hook <dir> --final`. |
| No click ripples / zooms look generic | No input log: `ev2 rec status`; record the next video with the logger running. For this one: `ev2 inputs <dir> --log <file>` if a log exists. |
| Wrong brand colour | `ev2 look <dir> --accent "#RRGGBB"`, then hook + inserts + finish. |
| `describe: ... was edited` | `--force` only if the creator agrees to lose the edits. |
| concat-gen: `open in Concat` | Close the project in Concat, then `ev2 concat <dir>`. |

Concat project (`concat --project <dir>/out/concat`): T4 main = `final.mp4` split at every cut;
T1/T2 chapter and caption titles (hidden); T3 empty for overlays; T5 the original cuts (hidden, muted);
T6 empty for music; T7 inserts (hidden, reference). Regenerated by finish (an edited one is backed up first).

## Video folder
```text
<dir>/
├── build.py (automatic hook)  PLAN.md  kit.json  index.html  sfx-cues.txt  insert-<name>.html
├── assets/media/   src.*  cam_raw.mp4 (1920x1080 30 CFR)  vo.wav (48k 24-bit stereo)
├── assets/pro/     bg.png grain.png stills/      (the look: shared backdrop, clean screenshots)
├── assets/ev1/     tokens.css fonts/ vendor/gsap.min.js
├── work/  timeline.json  hook.json  look.json  inputs.json  cuts.json  cuts-report.md  omarchy.json
│          tx/{words.json,...}  activity.npz  zoom_plan.json  body_video.mp4  body_fx_cues.txt
│          inserts/{<name>.mp4,<name>.cues.txt,<name>.json}  build.json  finish.json  ...
└── out/   render.mp4  hook.mp4  final.mp4  short.mp4  youtube-chapters.txt  captions.srt
           concat/  verify.md  beauty.md  beauty-sheet.jpg  youtube-description.md
```

## Read these when you need them
- **Writing hook.json, inserts, callouts, look: `reference/recipes.md` (start here).**
- Captions / transcripts in Darija: `reference/darija-guide.md`. Sound roles: `reference/sound-design.md`.
- Experts only (custom hook/scenes): `reference/devices.md`, `reference/look.md`, `template/build_custom.py`,
  `reference/sourcing.md` (footage + rights), `reference/edl/` (open one section at a time, never whole).
- Tests: `scripts/test_pipeline.py` (assembly + failure paths), `components/test_components.py`, `components/test_pro.py`.
