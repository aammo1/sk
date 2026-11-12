# Editor V2 — Sound Design & Audio Architecture

> **The empirical measured grammar is documented in `edl/SOUND.md`. The precise roles and parameters are defined in the `SND` table of `components/ev1_devices.py`.**

In Editor V2, sound design provides the tactile physical snap that makes cuts, zooms, and typing feel intentional rather than slide-based. The composition devices write their own sound cues into `sfx-cues.txt`, preventing timing drift during re-times.

---

## 1 · The Synthesized Sound Palette (`sfx/`)

All sound effects are synthesized in code via `scripts/synth-sfx.py` (deterministic DSP). Zero copyrighted samples are bundled:
- **Click Trains:** `clicktrain_1` (17ms pre-roll), `clicktrain_2` (12ms), `clicktrain_3` (32ms, pop cards), `clicktrain_4` (122ms, strobe bursts).
- **Single Clicks:** `click_3` (transient pop), `click_1` (`click_soft`, subtle menu/zoom marker), `key_click` (keyboard shortcut / terminal typing).
- **Transitions:** `swish_1` (title entrance swoosh, 270ms pre-roll), `glitch_1` (datamosh distortion, 170ms), `riser_1` (swell peaking exactly on cut).
- **Punches & Weight:** `impact_1` (`hit`, single cut with weight), `impact_2` (`impact`, slam after silence), `outro_1` (reverberant chord for final end card).
- **Sub Tones:** `subtone_1` (deep 40Hz drone under UI cards), `subboom_1` (impact rumble).

---

## 2 · Music Bed & Mixing Strategy (`scripts/bed-mix.py`)

### Built-in tutorial music (`scripts/synth-music.py`)
- When no custom song is given, the hook uses `sfx/ev1kit/bed_tutorial.wav`: a calm, warm 100 BPM loop in A minor (soft chord pad, plucked arpeggio with echo, round bass, light beat from bar 5). It is synthesized in code (no samples, no copyright) and loops without a click. Rebuild or change it with `synth-music.py --bpm N --seed N`.
- Use your own track with `ev2 finish <dir> --song path/to/music.mp3` (make sure you have the rights).
- The older dark sub-pulse (`bed_pulse.wav`, from `synth-sfx.py`) is still shipped; it sounds like a low rumble, so it is no longer the default. Use it with `bed-mix.py --song sfx/ev1kit/bed_pulse.wav --under 5.5`.
- **Relative Level:** the bed sits **13 LU under the voice** by default (`ev2 finish --bed-under LU` to change): you feel it more than you hear it. Fixed gain offset, never dynamic DRC.

### Cut, Don't Duck
- Background music is **cut**, not ducked, around structural video moments:
  - `-70 dB` (complete cut) under punchlines, caveats, or dramatic black cards.
  - `-8 dB` dip under complex code explanation beats.
- **Optional body music (off by default):** `ev2 finish <dir> --body-music` (or `"body_music": true` in `work/timeline.json`) puts the same music under the whole body, 20 LU under the voice (`--body-under LU`), fading in over 1.5 s and out over 3 s. It hides faint mic hiss but does not fix a bad recording; keep it very quiet so speech stays easy to follow. `--no-bed` turns all music off, `--no-body-music` forces it off.
- **Current limitation (hook only):** `ev2 finish` calls `bed-mix.py` with only `--song <--song> --under <--bed-under> --dur <hook>`, so
  `--ramp`, `--hook-end` and `--chapter-swell` are NOT applied by the pipeline today. The bed simply
  ends with the hook (there is no bed under the body, so a chapter swell cannot happen). Cuts and
  dips are a manual step: run `bed-mix.py` yourself and mix in Concat (lane T6), or skip the bed
  with `ev2 finish --no-bed`. Note that `--chapter-swell` is uncapped in `bed-mix.py`: do not use it.

---

## 3 · Cue Laying & Muxing (`scripts/mix-sfx.py` & `scripts/finish.py`)

1. `build.py` evaluates all devices, registering frame-exact timestamp cues in `sfx-cues.txt`.
2. `bed-mix.py` mixes the hook's voice (`assets/media/vo.wav`, first `hook_split` seconds) with the bed into `work/premix.wav` (regenerated on every finish, never reused stale).
3. `mix-sfx.py` lays the cues onto it through a brickwall limiter (`alimiter` at -1.0 dBFS) -> `work/hook_audio.wav`.
4. `finish.py` cleans the voice (high-pass, denoise, de-ess, EQ, compression), joins hook audio + the
   cleaned body voice (no bed under the body), then two-pass loudness-normalizes the whole mix to
   **−14 LUFS / −1.5 dBTP** (YouTube's reference; `--lufs` changes it).
5. `verify.py` measures integrated loudness and warns outside −16..−12 LUFS.
