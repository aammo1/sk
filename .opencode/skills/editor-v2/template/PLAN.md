# Style: **editor-v2** (designed hook + polished tutorial body)

> Rows marked *(example)* are template examples: replace or delete every one of them.
> You write data only (hook.json, timeline.json); the code designs. Recipes: `reference/recipes.md`.

## Approval (the PLAN gate: fill in, then get the creator's explicit OK)
- [ ] Hook split confirmed: `__` s, 15-30 s, the end of the spoken intro (`ev2 clean <dir> --hook-split S`)
- [ ] Final length from cuts-report looks right: `__:__`
- [ ] Retake candidates reviewed (each one: cut yes/no, set in `work/cuts.json`)
- [ ] Transcript spot-checked (wrong tech terms fixed in `work/tx/words.json`)
- [ ] Promise chosen (written to `work/hook.json`); hook shots kept as auto-picked, or changed
- [ ] Body chapters written to `work/timeline.json` (>= 3, titles <= 40 chars, one separator style)
- [ ] Explainer inserts agreed (one every 2-3 min: time, recipe, exact labels), or "none"
- [ ] Callouts agreed (2-5 key buttons: time + text), or "none"
- [ ] Style: documentary (default) or calm (`ev2 style <dir> calm`)
- [ ] Look: defaults (brand colour auto from the app), or changed (`ev2 look <dir> ...`)
- [ ] Key pills: none, auto from the input log, or listed in "keys" (`ev2 keys <dir>` suggests)
- [ ] YouTube description: no, or yes (`ev2 describe <dir> --lang ...` after finish)
- [ ] Body music: on (default, very quiet) or off (`"body_music": false`)
- [ ] Every third-party asset in the Sources table has a licence; unclear rights flagged
- [ ] `ev2 check <dir>` prints `ready`
- [ ] **Creator approved on:** ____ (no hook/insert/finish render before this line is filled)

## Video Metadata
- **Title:** <!-- Video title -->
- **Style:** documentary
- **Target Length:** ~8 minutes (a 15-30 s designed hook + the cleaned screencast tutorial body)
- **Spoken Language:** Moroccan Darija (الدارجة المغربية) code-switching with English/French technical terms
- **Recording Source:** Omarchy screencast with corner webcam overlay (`assets/media/src.mp4`)
- **Input log:** yes / no (`work/inputs.json`: exact zooms + click ripples)

---

## Silence & Retake Summary
<!-- Copy from work/cuts-report.md (written by clean-retakes.py). -->

| Metric | Raw Value | Cleaned Value | Savings / Notes |
|---|---|---|---|
| Duration | 00:00:00 | 00:00:00 | -00:00 (-0.0%) |
| Pauses Shortened | — | 0 pauses | pauses > 0.6 s kept at 0.3 s (1.2 s when the screen is busy) |
| Retake Candidates | — | 0 found / 0 cut | reported only; cut the ones the creator approves (`work/cuts.json`) |
| Hook Split Point | — | 00:00:20 | Hand-off from hook to screencast (aim for 15-30 s) |

---

## Hook (-> `work/hook.json`, from `ev2 hook <dir> --init`)

| Field | Value |
|---|---|
| promise | <!-- one line, <= 60 chars, a result the viewer gets; *word* = accent --> |
| promise options shown to the creator | 1. … 2. … 3. … |
| brand | <!-- product/channel name, optional --> |
| title (end card) | <!-- optional, default hook_title --> |
| shots | auto-picked (list them: time + label), or the creator's moments |

---

## Body Chapters (-> `work/timeline.json` "chapters")
<!-- SOURCE times (as in work/tx/transcript or the raw recording): {"src_t": 165.0, "title": "..."}. -->

| Source time (s) | Title (<= 40 chars) |
|---|---|
| 52 *(example)* | إعداد بيئة العمل — Setup |
| 165 *(example)* | الكود الأساسي — Core code |
| 330 *(example)* | التصحيح — Debugging |

---

## Explainer Inserts (-> `work/timeline.json` "inserts", recipes: `reference/recipes.md`)

| name | Source time (s) | dur (s) | recipe | data (title + exact labels) |
|---|---|---|---|---|
| order-flow *(example)* | 135.2 | 8 | flow | title "كيفاش كتدوز الطلبية"; steps Boutique → Commande → WhatsApp → Livraison |

---

## Callouts (-> `work/timeline.json` "callouts")

| Source time (s) | text (<= 40 chars) |
|---|---|
| 91.2 *(example)* | Confirmer ici |

---

## Key Pills (optional, -> `work/timeline.json` "keys")

| Source time (s) | keys | label | dur |
|---|---|---|---|
| 46.0 *(example)* | Super + Space | then type the name | 2.5 |

---

## Sources, Assets & Licences
<!-- Only THIRD-PARTY material needs a row (docs pages, logos, footage, a song). The recording, the
     built-in music/sounds and the generated graphics are the creator's own: they are not listed
     and never appear in the description. -->

| Item | Material Description | Source (URL) | Licence / Rights | Flag / Notes |
|---|---|---|---|---|
| docs *(example)* | Official documentation page | https://… | Docs licence | Captured via `capture.mjs` |
