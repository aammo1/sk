---
name: editor-v2
description: "Edits Omarchy screencast recordings (Moroccan Darija + English tech terms, corner webcam) into a YouTube tutorial: a code-rendered documentary hook (HyperFrames + GSAP devices, BiDi Darija captions), a silence-trimmed screencast body with optional short animated explainer inserts (motion graphics) inside it, one synced final.mp4, a Concat (or Kdenlive) project for hand finishing, a 9:16 Short and YouTube chapters, all checked by a definition-of-done verifier, plus an optional calm title-card style, key-press pills and a YouTube description writer. Use when the user wants to edit, cut, caption or finish a recording/screencast/tutorial video, or mentions ev2, editor-v2, the hook, explainer insert, motion graphics, animated explanation, Concat or Kdenlive projects for a video, key pills, shortcut overlay, calm style, title card, youtube description."
---

# Editor V2 — Darija screencast → YouTube tutorial

One recording in, these out: `out/final.mp4` (hook + polished body, 1920x1080/30, −14 LUFS),
`out/hook.mp4`, `out/concat/` (Concat project), `out/short.mp4` (9:16), `out/youtube-chapters.txt`,
`out/captions.srt` and `out/verify.md` (pass/fail report).

**The body is polished automatically** (`scripts/body_render.py`, run by `ev2 finish`):
- **Auto zoom:** the screen is analyzed at 5 fps. When the action (typing, pointing, a menu) stays
  in a small area for over 1.2 s, the camera eases in (up to 2x), follows it, and zooms out on
  page changes or after 6 s of quiet. Plan in `work/zoom_plan.json`. Turn off with `--no-zoom`.
- **Webcam PiP:** the Omarchy corner camera is tracked (YuNet face model) and re-drawn 1.35x larger,
  rounded, with a border and shadow. It never zooms away. Turn off with `--no-cam`.
- **Chapter cards:** a lower-third slides in at each body chapter from `timeline.json`.
- **Voice:** high-pass, denoise, de-ess, EQ and compression, then the whole mix is two-pass
  normalized to −14 LUFS. Turn off with `--no-voice-fx`.
- **Gentle cuts:** pauses are shortened to 0.3 s, not removed. If the screen is busy during a pause
  (page loading), 1.2 s is kept. There are no slivers shorter than 0.5 s.
- **Explainer inserts:** short animated scenes (the hook's 45 devices) placed at chosen moments of the body
  while the voice keeps playing: `full` (opaque scene) or `over` (animation over the dimmed screencast).
  The webcam stays on top. Only the moments the PLAN lists; see `ev2 inserts`.
- **Captions:** always written to `out/captions.srt` and to a hidden Concat lane. Burned into the
  body only with `ev2 finish <dir> --captions`, after the transcript is checked.

**What it does not do (yet). Say so instead of implying otherwise:**
- Cursor highlights or click effects. Zoom targets come from screen changes, not from meaning.
  Review `work/zoom_plan.json`/the video, and use `--no-zoom` if it misfires.
- It does not decide where inserts go or what they show: that is agreed at the PLAN gate.
- Captions are Darija in Arabic script. Romanized and English modes are not implemented.
- Darija ASR is imperfect, even with `large-v3-turbo` (use the Darija model from Setup). A human checks the transcript before
  captions are burned in or trusted.

## Setup (once)
```bash
ev2 doctor --install-speech     # checks everything, links ~/.local/bin/ev2 -> <skill>/scripts/ev2
```
If `ev2` is not on PATH, run `bash ~/.agents/skills/editor-v2/scripts/ev2 <command>` (same commands).

**Darija transcription model (recommended, once):** generic Whisper turns much of Darija into broken
standard Arabic. A public model fine-tuned on Moroccan Darija should do much better:
```bash
ev2 convert-model amineouaki/whisper-medium-darija-combined     # ~2-4 GB download, ~30 min, one time
export EV2_WHISPER_MODEL=~/.cache/editor-v2/models/whisper-medium-darija-combined-ct2   # add to ~/.bashrc
```
**Not yet tested on this creator's voice.** The model card reports 3.5% WER on test splits of its
own (overlapping) training sets, which is optimistic for code-switched tech talk. Compare it with
`large-v3-turbo` on one video using `ev2 asr-check` before trusting it. It was trained on clips of
15 s or less, so transcribe with `--windowed` (20 s chunks). Expect English/French terms to come out
in Arabic script: the term map and `darija-terms.json` fix those. If the model is a LoRA adapter
rather than a full model, the conversion fails. Pick a full fine-tune instead.

**Tech terms:** the Latin spellings in `transcribe.py` `HOTWORDS`, the values of
`~/.config/editor-v2/darija-terms.json` and `EV2_HOTWORDS="Vercel, Supabase"` are passed to Whisper
as hotwords in every 30 s window (the initial prompt only reaches the first window).
Doctor must end with `All set`. A `MISSING` line is a blocker, so fix it before editing.

## The workflow (agent: follow in order, stop where marked)

| # | Command | Produces | Agent does |
|---|---|---|---|
| 1 | `ev2 init <file\|--latest> [name] [--style calm]` | `~/editor-v2/videos/<name>/` with `assets/media/{src.*,cam_raw.mp4,vo.wav}`, `work/omarchy.json`, `build.py`, `PLAN.md` | Confirm with the user which recording. `--style calm` only if the creator chose it (see Optional extras). |
| 2 | `ev2 transcribe <dir>` | `work/tx/words.json`, `work/timeline.json`, `work/cuts-report.md` | Model: `$EV2_WHISPER_MODEL` if set (the Darija fine-tune, see Setup), else `large-v3-turbo` (slow on CPU, 1.6 GB first download). `--model small` gives a quick draft. Language defaults to `ar`. Never use `auto` for Darija: it misdetects (a real test came out as Czech and Romanian). Refuses to overwrite a hand-corrected `words.json`; `--force` re-transcribes and keeps a `words.json.bak-<time>`. |
| 3 | **PLAN gate** (see below) | filled `PLAN.md`, chapters in `timeline.json` | **STOP and get explicit approval.** |
| 4 | edit `build.py`, then `ev2 build <dir>` | `out/render.mp4` (the hook) | One code block per PLAN beat. Assets go in `work/assets.json`. The best and rights-free material is **the recording itself**: export stills with `ffmpeg -ss T -i assets/media/cam_raw.mp4 -frames:v 1 assets/img/x.jpg`, crop the face with the webcam box from `work/activity.npz`, and use `screen_zoom` on `cam_raw.mp4`. Keep the hook short (15–25 s): end `hook_split` where the intro ends. If the transcript is unreliable, use display keywords you know are true instead of word captions. Look at a contact sheet of the render before finishing. |
| 5 | `FINAL=1` check: `ev2 build <dir> --final` | refuses while placeholders, missing assets or `example()` template beats remain | Required: verify FAILs unless the last hook build was `--final`. |
| 5b | `ev2 inserts <dir> [--final]` | `work/inserts/<name>.mp4\|.mov` | Only if PLAN.md lists inserts. One @scene per insert in inserts.py; times are local; keep each 4–12 s; --final before publishing. Flags: `--only NAME`, `--force`. |
| 6 | `ev2 finish <dir>` | all outputs above, then verify | Read `out/verify.md`. |
| 7 | `ev2 describe <dir>` | `out/youtube-description.md` | Optional. Fill every `<!-- WRITE -->` slot from `work/description-notes.md`, then `--check`. |

`ev2 finish --editor concat|kdenlive|both|none` (default `concat`, or `EV2_EDITOR`).
Other flags: `--captions`, `--no-keys` (skip the key pills for this run, also when they are invalid), `--no-zoom`, `--no-cam`, `--raw-body` (plain cuts, the fastest),
`--no-voice-fx`, `--no-bed`, `--song FILE`, `--bed-under LU`, `--body-music` / `--no-body-music`, `--body-under LU`, `--lufs -14`, `--no-open`. The body render is cached and is only
redone when cuts, chapters, captions or the zoom plan change.

### The single source of truth: `work/timeline.json`
`clean-retakes.py` writes it. `finish`, `concat-gen`, `kdenlive-gen` and `verify` all read it.
- `hook_split`: the hook is source `[0, hook_split)`, uncut, under the HyperFrames render. Default 45 s, snapped to the nearest pause. Change it with `ev2 clean <dir> --hook-split 15`, then **rebuild the hook** (finish refuses a render of the wrong length).
- `segments`: the body's kept source ranges (long pauses shortened, frame-quantized). Tune with `ev2 clean <dir> --keep 0.3 --busy-keep 1.2 --max-silence 0.6`.
- `chapters`: `[{"src_t": <source seconds>, "title": "..."}]`, written by you or the agent at the PLAN gate. finish maps them through the cuts. Never invent chapters.
- `inserts`: `[{"name": "order-flow", "src_t": 135.2, "dur": 8, "mode": "over", "cam": true}]`. `name` kebab-case, unique; `src_t` SOURCE seconds (≥ `hook_split`; inside a cut it snaps forward like chapters); `dur` FINAL seconds, 1.5–30; `mode` `full` (opaque, 9-frame crossfade in/out) or `over` (transparent, over the dimmed, blurred screencast); `cam` (default true) keeps the webcam PiP on top. No overlaps, none past the body end. Scenes live in `inserts.py` (`@scene('<name>') def fn(c, ins)`, helpers `words(ins)`, `asset`, `ph`, `example`, `hype_slide(deck, slide)`; see `reference/devices.md`). `ev2 finish` composites them, mixes their SFX into the body audio, and refuses `--raw-body` when inserts exist.
- `keys` (optional key pills): `[{"src_t": 46.0, "keys": "Super + Space", "label": "then type the name", "dur": 2.5, "sfx": true, "pos": "bottom"}]`. `src_t` SOURCE seconds (≥ `hook_split`); `keys` "A + B" or a list, 1–4 keys of ≤ 12 chars; `label` ≤ 40 chars, Darija OK; `dur` 0.8–8 s (default 2.5); `sfx` (default true) mixes a soft key click into the body audio; `pos` `bottom`|`top`. Pills may not overlap; one near the body end is shortened. `ev2 finish` draws them over the PiP and inserts, under chapter cards, raised when captions are on; not drawn with `--raw-body`. Chapter cards cover a bottom pill, so avoid the first ~3.6 s of a chapter.

Retakes are **reported, not cut**, by default: Darija repeats phrases on purpose. To cut one, set
`"enabled": true` on it in `work/cuts.json`, then run `ev2 clean <dir>`. `ev2 clean <dir> --retakes` enables all of them.
An enabled retake is always cut (clean stops with an error otherwise), and the choice is matched by
the retake's text, so it survives re-transcription.

### PLAN gate: what approval means
Show the user `work/cuts-report.md` and the filled `PLAN.md`. Get an explicit "yes" on every box
in PLAN.md's **Approval** section:
1. Hook split and final length.
2. Each retake candidate: cut or keep.
3. The transcript spot-checked, with tech terms fixed in `work/tx/words.json`. Text only: never move `s`/`e` by hand.
4. Hook beats, each with a real asset or an agreed placeholder.
5. Body chapters: at least 3 including 00:00, each at least 10 s.
6. Every third-party asset licensed, unclear rights flagged (`reference/sourcing.md` › Rights).
7. Explainer inserts: moment (source time), duration, mode, what it shows — or none.
8. The optional extras below: each ticked or explicitly declined.

Do not run `ev2 build` before approval. If the user changes cuts later, re-run `ev2 clean` and
then `ev2 finish`. Re-run `ev2 build` too if `hook_split` changed.

### Optional extras (the creator chooses; never on by default)
Offer these as choices at the PLAN gate. Never enable an extra the creator did not tick. Without them
the outputs are exactly the same as before.
- **Calm style** (title card, then the screencast as recorded, for plain walkthroughs): `ev2 init <rec> [name] --style calm`,
  or `ev2 style <dir> calm` for an existing video (a modified `build.py` is first backed up as `build.py.bak-<date>`;
  `kit.json` records `"style"`). Off: `ev2 style <dir> documentary` (the default). Template `template/build_calm.py`:
  `title_card` for ~4.5 s, then `cam_raw.mp4` until the hook split; optional `shortcut_pill` beats; screenshots from
  optional `thumb1`/`thumb2` keys in `work/assets.json`. Set the hook split at the end of the spoken intro (5–15 s).
- **Key pills** (shortcut overlays on the body, cheaper than an insert): `ev2 keys <dir>` writes suggestions to
  `work/keys-suggest.md|.json` from the transcript (Latin or Arabic-script key names) and never edits the timeline.
  Copy the agreed ones into `"keys"` (see the timeline section), then `ev2 finish`. Off: remove `"keys"`, or `--no-keys` for one run.
- **YouTube description**: after `ev2 finish`, `ev2 describe <dir> [--lang darija|en|fr] [--apps a,b]` writes
  `out/youtube-description.md` (summary slot, one slot per chapter, the chapters, a setup line from
  `omarchy-version`/os-release + `pacman -Q` of `--apps`, recording date, sources from PLAN.md + the music credit)
  and `work/description-notes.md` (transcript per chapter). Fill every `<!-- WRITE ... -->` slot from the notes only
  (no invented facts), then `ev2 describe <dir> --check` (exit 0 = ready). It refuses to overwrite an edited
  description without `--force`. Off: don't run it (verify adds a `description` line only when the file exists).

### Definition of done
A video is done **only** when `ev2 finish` (or `ev2 verify <dir>`) prints `DONE` and nothing
in `out/verify.md` is FAIL:
- `final.mp4` is exactly hook + cleaned body long, 1920x1080 @ 30, audio length = video length.
- The voice in `final.mp4` matches `vo.wav` within 1 frame at several body points (cross-correlation).
- The picture matches the timeline within 1 frame: the timing of screen changes in `final.mp4` is
  cross-checked against the expected `cam_raw.mp4` frames through the cuts (zoom/PiP don't affect it).
- The hook's last build was `ev2 build --final` (no placeholders, no missing assets) for the current `hook_split`.
- Neither cuts nor chapters changed after the last `ev2 finish`.
- Every insert is rendered FINAL, has the right frame count, and nothing changed since `ev2 finish`. Picture sync skips insert ranges.
- `hook.mp4` = `hook_split` long. The Concat/Kdenlive project has the same cuts and is not stale. For Concat, the project is opened headless with `concat --mcp headless`.
- `short.mp4` is 1080x1920 and at most 60 s.
- When `keys` are listed: the pills are valid, drawn, and unchanged since `ev2 finish` (else `stale keys`).
- `out/youtube-description.md`, if it exists, gets a WARN-only `description` line (slots left, over 5000 chars, outdated chapters).

The WARN lines must be reported to the user, never hidden: YouTube chapter rules not met,
loudness outside −16..−12 LUFS, a sync check that found nothing clear enough to measure. Never say
"finished" or "ready to publish" with a FAIL.

## When something fails
| Symptom | Fix |
|---|---|
| `ev2: command not found` | `bash ~/.agents/skills/editor-v2/scripts/ev2 doctor` (creates the link) |
| doctor: `speech MISSING` | `ev2 doctor --install-speech` |
| Transcript has many wrong words | Generic Whisper turns a lot of Darija into broken standard Arabic. Try a Darija fine-tune: `ev2 convert-model amineouaki/whisper-medium-darija-combined`, then `ev2 transcribe <dir> --model ~/.cache/editor-v2/models/whisper-medium-darija-combined-ct2`. Measure with `ev2 asr-check <dir> --ref said.txt --from 60 --to 180`. Put recurring fixes in `~/.config/editor-v2/darija-terms.json` (`{"فيرسل": "Vercel"}`). |
| `transcribe: ... words.json was edited` | Your corrections would be lost. Keep them (skip transcribe), or `ev2 transcribe <dir> --force` (backup kept as `words.json.bak-<time>`). |
| `build.py: FINAL refused` | Source the listed assets into `work/assets.json`, or agree to cut the beat. `template example: ...` entries: replace that template beat with the real one and delete its `example()` call. |
| verify: `hook build` FAIL | `ev2 build <dir> --final`, then `ev2 finish <dir>`. |
| verify: `picture sync` FAIL | Do not publish. Delete `work/body_video.mp4` and re-run `ev2 finish`. If it persists, try `--raw-body` to isolate `body_render.py`. |
| verify: `stale chapters` | Chapters changed after finish: `ev2 finish <dir>` (redraws cards and `youtube-chapters.txt`). |
| `hf lint` / render fails | Read the error. Usually a missing asset path or a device argument. Fix `build.py`, then `ev2 build` again. |
| finish: `hook render is X s but hook_split is Y s` | `ev2 build <dir>` (the render predates the split change). |
| finish: `index.html is newer than out/render.mp4` | The render is stale: `ev2 build <dir>`. |
| verify: `stale` | `timeline.json` changed after finish: `ev2 finish <dir>`. |
| verify: `voice sync` FAIL | Do not publish. Re-run `ev2 finish`. If it persists, check that `cam_raw.mp4` and `vo.wav` come from the same `ev2 init`. |
| `inserts: insert "X" is in work/timeline.json but inserts.py has no @scene("X")` | Write that scene (or remove the entry). |
| verify: `inserts` FAIL | `ev2 inserts <dir> --final`, then `ev2 finish <dir>`. |
| verify: `stale inserts` | `ev2 finish <dir>`. |
| `finish: inserts need the polished body` | Drop `--raw-body`. |
| verify: `stale keys` / `WARN key pills` (not drawn) | `ev2 finish <dir>` (without `--no-keys`/`--raw-body`). |
| `describe: no chapters yet` | Run `ev2 finish <dir>` first. |
| `describe: ... was edited` | `--force` only if the creator agrees to lose the edits. |
| verify: `WARN description` | Fill the `<!-- WRITE -->` slots, then `ev2 describe <dir> --check`; outdated chapters: `--force`; too long: shorten. |
| concat-gen: `open in Concat` | Close the project in Concat, then re-run (`ev2 concat <dir>`). |

Concat project (`concat --project <dir>/out/concat`):
- **T4 main:** the polished `final.mp4`, split at every cut.
- **T1 / T2:** chapter and caption title clips. Hidden; show a lane to burn it in.
- **T3:** empty, for your overlays.
- **T5:** the same cuts from the original recording. Hidden and muted; use it to re-trim into a removed pause.
- **T6:** empty, for music.
- **T7:** inserts, hidden + muted (reference; already in T4).

`ev2 finish`/`ev2 concat` regenerate the project. If you edited it in Concat since the last
generation, the old file is kept first as `concat.json.bak-<time>`.

## Video folder
```text
<dir>/
├── build.py  PLAN.md  kit.json  index.html  sfx-cues.txt  build.py.bak-* (ev2 style)
├── inserts.py  insert-<name>.html          (explainer inserts)
├── assets/media/   src.* (original)  cam_raw.mp4 (1920x1080 30 CFR)  vo.wav (48k 24-bit stereo)
├── assets/ev1/     tokens.css fonts/ vendor/gsap.min.js     assets/img|clips|captures/
├── work/  timeline.json  cuts.json  cuts-report.md  silences.txt  omarchy.json  assets.json
│          tx/{words_raw.json,words.json,words.auto.json,transcript.txt,engine.json}
│          build.json  hook_chapters.json  chapters.json  premix.wav  hook_audio.wav
│          vo_clean.wav  body_voice.wav  final_audio.wav  activity.npz  zoom_plan.json
│          body_video.mp4  final.filtergraph  finish.json  concat-gen.json
│          inserts/{<name>.mp4|.mov,<name>.cues.txt,<name>.json}  body_cues.txt  body_mix.wav
│          keys-suggest.md|.json  description-notes.md  description.json   (optional extras)
└── out/   render.mp4  hook.mp4  final.mp4  short.mp4  youtube-chapters.txt  captions.srt  youtube-description.md
           concat/concat.json  project.kdenlive (optional)  verify.md  verify.json
```

## Read these when you need them
- Writing hook beats: `reference/devices.md` (45 devices, signatures), `reference/look.md` (type tiers, grades, rhythm), `reference/sound-design.md` (SFX roles, bed rules).
- Captions / transcripts in Darija: `reference/darija-guide.md`.
- Finding real pictures/footage and rights: `reference/sourcing.md`. Tools: `ev2 find`, `ev2 capture`, `scripts/ev1_clip.py`, `scripts/ev1_treat.py`, `scripts/clipsheet.py`, `scripts/matte.py`.
- How the style was measured: `reference/reference-log.md`, `reference/edl/` (about 180 KB / 45k tokens: open only
  the one section you need, never load it whole). Worked v1 example (English, media not shipped, older numbers): `reference/example-v1/`.
- Tests: `scripts/test_pipeline.py` (end-to-end assembly incl. failure paths) and `components/test_components.py`.
