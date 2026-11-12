# Style: **editor-v2** (Hybrid Tutorial + Documentary Hook)

> Rows marked *(example)* are template examples: replace or delete every one of them.

## Approval (the PLAN gate: fill in, then get the creator's explicit OK)
- [ ] Hook split confirmed: `__` s (from `work/cuts-report.md`; change with `ev2 clean <dir> --hook-split S`)
- [ ] Final length from cuts-report looks right: `__:__`
- [ ] Retake candidates reviewed (each one: cut yes/no, set in `work/cuts.json`)
- [ ] Transcript spot-checked (wrong tech terms fixed in `work/tx/words.json`)
- [ ] Hook beats table complete, every beat has a real asset or an agreed placeholder
- [ ] Body chapters written to `work/timeline.json` (>= 3 incl. the hook, each >= 10 s)
- [ ] Explainer inserts agreed (each: source time, duration, mode, what it shows), or "none"
- [ ] Style chosen: documentary (default) or calm (`ev2 style <dir> calm`)
- [ ] Key pills: none, or listed in "keys" (start from `ev2 keys <dir>` suggestions)
- [ ] YouTube description: no, or yes (`ev2 describe <dir> --lang ...` after finish)
- [ ] Body music decided: quiet music under the whole tutorial, yes or no (`"body_music": true` in `work/timeline.json`)
- [ ] Every third-party asset in the Sources table has a licence; unclear rights flagged
- [ ] **Creator approved on:** ____ (no `ev2 build` render before this line is filled)

## Video Metadata
- **Title:** <!-- Video title -->
- **Style:** documentary
- **Target Length:** ~8 minutes (a 15–25 s fast documentary Hook + the cleaned screencast tutorial body)
- **Spoken Language:** Moroccan Darija (الدارجة المغربية) code-switching with English technical terms
- **Recording Source:** Omarchy screencast with 8:9 corner webcam overlay (`assets/media/src.mp4`)
- **Music:** built-in tutorial music (synth-music.py) under the hook; under the body only if "body_music" is true
- **ASR & Dictionary:** Faster-Whisper INT8 with `reference/darija-guide.md` phonetic tech mappings

---

## Silence & Retake Summary
<!-- Copy from work/cuts-report.md (written by clean-retakes.py). -->

| Metric | Raw Value | Cleaned Value | Savings / Notes |
|---|---|---|---|
| Duration | 00:00:00 | 00:00:00 | -00:00 (-0.0%) |
| Pauses Shortened | — | 0 pauses | pauses > 0.6 s kept at 0.3 s (1.2 s when the screen is busy) |
| Retake Candidates | — | 0 found / 0 cut | reported only; cut the ones the creator approves (`work/cuts.json`) |
| Hook Split Point | — | 00:00:20 | Hand-off from Hook render to Screencast (aim for 15–25 s) |

---

## Hook Beats (0:00 – end of hook, Documentary Style)
<!-- High-density documentary hook. Pictures swap every 0.6–1.5s on spoken word onsets.
     All technical English words inside Darija phrases are wrapped in <bdi> for BiDi rendering.
     Every beat sources real documentation, code diffs, or architecture diagrams. -->

| t (s) | Darija Line (said) | Device | Visual / Real Material | SFX / Cue |
|---|---|---|---|---|
| 0.00 *(example)* | هاد الفيديو غانشوفو فيه... | `tile_reveal` from black | `open_still` -> `open_clip` | `train_tile` |
| 1.40 *(example)* | كل سطر كود كايتعاود... | `pop_shatter` (3 cards) | `assets/img/diff_card*.jpg` | `train_pop` + `hit` |
| 2.80 *(example)* | بدون تضييع الوقت | `neg_flash` + `keyword` | Shock word: **ZERO BOILERPLATE** | `swish` + `hit` |
| 4.20 *(example)* | بستعمال هاذ الأمر البسيط | `cmd_toast` | `$ agy implement-feature` | `key_click` |
| 6.00 *(example)* | المعمارية كاملة مبنية على... | `flow_diagram` | 3 nodes: Omarchy -> ASR -> Concat | `click_soft` |
| ... | ... | ... | ... | ... |
| 18.50 *(example)* | يالاه نبداو بالخطوة الأولى | `chapter_banner` (card) | Chapter 01 title card | `swish` + `hit` |

---

## Body Chapters (-> `work/timeline.json`)
<!-- The body is the cleaned screencast, appended by `ev2 finish`. Chapters are given by SOURCE time
     (what you see in work/tx/transcript or the raw recording), written into timeline.json as
     {"src_t": 165.0, "title": "..."}; finish maps them to final-video time after the cuts.
     Zooms, the webcam PiP and chapter cards on the body are automatic (body_render.py); check
     work/zoom_plan.json / the video, use --no-zoom if it misfires, and add extra callouts by
     hand in Concat (lane T3, overlays). -->

| Source time (s) | Title (Darija / English) | Notes for the Concat pass (extra callouts) |
|---|---|---|
| 52 *(example)* | إعداد بيئة العمل (Setup) | callout on the terminal command |
| 165 *(example)* | كتابة الكود الأساسي (Core Code) | |
| 330 *(example)* | حل المشاكل والتصحيح (Debugging) | |
| 430 *(example)* | النتيجة النهائية (Demo) | |

---

## Explainer Inserts (-> `work/timeline.json` "inserts" + `inserts.py`)
<!-- Short animated scenes inside the body while you keep talking (4-12 s each). mode: full = opaque
     scene, over = animation over the dimmed screencast. Your webcam stays on top unless cam=false. -->

| name | Source time (s) | dur (s) | mode | What it shows (devices / assets) |
|---|---|---|---|---|
| order-flow *(example)* | 135.2 | 8 | over | `flow_diagram`: Boutique → Commande → WhatsApp → Livraison |

---

## Key Pills (optional, -> `work/timeline.json` "keys")
<!-- Shortcut overlays on the body. Start from `ev2 keys <dir>`; keep only the ones that help. -->

| Source time (s) | keys | label | dur |
|---|---|---|---|
| 46.0 *(example)* | Super + Space | then type the name | 2.5 |

---

## Sources, Assets & Licences
<!-- Verify every claim, number, and repo on its real page.
     Record URLs, commit hashes, licences, and flags for commentary attribution. -->

| Beat / Item | Material Description | Source (URL or Path) | Licence / Rights | Flag / Notes |
|---|---|---|---|---|
| sound | Kit synthesized SFX | `scripts/synth-sfx.py` | Own synthesis (no third-party audio) | Procedural code synthesis |
| music | Built-in tutorial music | `scripts/synth-music.py` | Own synthesis | Under the hook; under the body only if "body_music" is true |
| screen | Omarchy desktop capture | `assets/media/src.mp4` | Creator Original | 1080p 30fps CFR |
| brand | Official tool / framework logos | Wikimedia Commons / Official SVG | Trademark (identify only; see sourcing.md › Rights) | Rebuilt via `svg_mark` |
| docs | Official documentation pages | Tool docs / GitHub repository | Permissive / Docs | Captured via `capture.mjs` |
