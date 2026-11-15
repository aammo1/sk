# Hand-off Contract (`<run>/handoff/`)

`td handoff <run>` produces a self-contained directory at `runs/<name>/handoff/` that `ev2 init --from-director <run>/handoff [name]` imports directly — skipping transcription and webcam sync while pre-filling `work/inputs.json`, `work/tx/words.json`, and `work/timeline.json` suggestions.

## Files in `<run>/handoff/`

| File | Format / Spec | Purpose |
|---|---|---|
| `screen.mp4` | 1920x1080, 30 fps CFR, H.264, no audio track | Recorded desktop (`cam_raw.mp4` source for `editor-v2`) |
| `vo.wav` | 48 kHz, 24-bit (`pcm_s24le`), stereo (`2` ch) | TTS voiceover placed at actual step start times, `t=0` = `screen.mp4` `t=0` |
| `inputs.json` | Exact `editor-v2` `work/inputs.json` schema | Clicks, typing spans, shortcut combos, cursor path |
| `words.json` | Exact `editor-v2` `work/tx/words.json` schema | Word timings aligned to TTS output (script words, zero ASR errors) |
| `plan.json` | Editorial suggestions in source seconds | `title`, `promise`, `chapters`, `inserts`, `callouts`, `keys` |
| `director.json` | Provenance & step execution metadata | Engine, `script_sha`, `user`, per-step timings and verification status |

---

## `inputs.json` (from `editor-v2/scripts/inputs.py` & `body_render.py`)

Matches the JSON written by `$EV2/scripts/inputs.py` (`convert()`):

```json
{
  "log": null,
  "offset_wall": 0.0,
  "align": {"method": "director", "confidence": 1.0},
  "clicks_inferred": false,
  "clicks": [
    {"t": 14.52, "x": 640.0, "y": 420.0, "btn": "left"}
  ],
  "typing": [
    [16.1, 17.8]
  ],
  "keys": [
    {"t": 14.1, "combo": ["Super", "Alt", "Space"]}
  ],
  "cursor": [
    [0.0, 960.0, 540.0],
    [0.067, 940.2, 520.5]
  ]
}
```

Exact fields read by `editor-v2`:
- `log` (`string | null`): source log path or `null` when emitted by `tutorial-director`.
- `offset_wall` (`float`): wall-clock time of video `t=0` (`0.0` when times are already in source seconds).
- `align` (`object`): `{"method": string, "confidence": float}`.
- `clicks_inferred` (`bool`): `false` for exact director clicks (if `true`, `editor-v2` suppresses click ripples and only zooms).
- `clicks` (`list[object]`): each entry has `"t"` (source seconds `>= 0`), `"x"`, `"y"` (`1920x1080` `cam_raw` pixels), and `"btn"` (`"left"`, `"right"`, or `"middle"`). Optional `"inferred": true` is omitted for exact clicks.
- `typing` (`list[[float, float]]`): `[start_s, end_s]` spans in source seconds. Note: `body_render.py` requires `clicks` or `typing` to be non-empty for `load_inputs()` to activate input-driven zooms, and anchors typing zooms to the last click within 30 s prior.
- `keys` (`list[object]`): shortcut events `{"t": float, "combo": [str, ...]}` (at least 2.5 s apart in `inputs.py`).
- `cursor` (`list[[float, float, float]]`): `[t, x, y]` samples in source seconds and `1920x1080` `cam_raw` pixels (~15 Hz).

---

## `words.json` (from `editor-v2/scripts/transcribe.py` & `check.py`)

Matches `$EV2/scripts/transcribe.py` (`post_process_words()`): a JSON array of word objects sorted ascending by `s`:

```json
[
  {"w": "سلام،", "s": 0.5, "e": 0.82},
  {"w": "اليوم", "s": 0.84, "e": 1.15},
  {"w": "غادي", "s": 1.17, "e": 1.43}
]
```

Exact fields read by `editor-v2`:
- `w` (`string`): exact word token from the script's `say` text.
- `s` (`float`): start time in source seconds (rounded to 3 decimal places).
- `e` (`float`): end time in source seconds (rounded to 3 decimal places, `e >= s`).

---

## `plan.json`

Editorial suggestions in **source seconds** (`screen.mp4` / `vo.wav` timeline) used by `ev2 init --from-director`:

```json
{
  "title": "Omarchy menu f 3 dqayq",
  "promise": "Learn the *Omarchy menu* in 3 minutes",
  "chapters": [
    {"src_t": 0.0, "title": "Intro — المقدمة"}
  ],
  "inserts": [
    {"name": "s02-steps", "src_t": 14.2, "dur": 12, "recipe": "steps", "data": {}}
  ],
  "callouts": [
    {"src_t": 15.0, "text": "Omarchy menu", "dur": 3, "x": 960, "y": 40}
  ],
  "keys": [
    {"src_t": 14.1, "keys": "Super + Alt + Space", "dur": 2.5}
  ]
}
```

Field constraints matching `$EV2/scripts/ev2_timeline.py`:
- `chapters`: `src_t` (float), `title` (`<= 40` chars).
- `inserts`: `name` (`^[a-z0-9][a-z0-9-]{0,39}$`, unique), `src_t` (float), `dur` (`1.5`–`30` s), `recipe` (`flow|steps|checklist|compare|stat|statement|screens`), `data` (object).
- `callouts`: `src_t` (float), `text` (`<= 40` chars), `dur` (`1`–`8` s, default `3`), optional `x`, `y` (`cam_raw` pixels).
- `keys`: `src_t` (float), `keys` (`"A + B"` or `["A", "B"]`, 1–4 keys each `<= 12` chars), `dur` (`0.8`–`8` s, default `2.5`), optional `label`, `sfx`, `pos`.

---

## `director.json`

Run provenance and step-by-step execution record:

```json
{
  "engine": "golha",
  "script_sha": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "user": "anas_omarchy",
  "steps": [
    {
      "id": "s01",
      "start": 0.0,
      "end": 4.25,
      "voice_start": 0.5,
      "voice_end": 3.4,
      "ok": true
    }
  ]
}
```

Fields:
- `engine` (`string`): TTS engine used (`"golha"` or `"lahgtna"`).
- `script_sha` (`string`): SHA-256 hex digest of `script.json`.
- `user` (`string`): Linux user that executed `td record`.
- `steps` (`list[object]`): per-step source start/end seconds, voice placement (`voice_start`, `voice_end`), and verification result (`ok`).
