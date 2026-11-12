# Editor V2 — look, type, rhythm, layouts

Editor V2 blends the cinematic documentary look of Editor V1 with developer screencast clarity, Omarchy desktop layout rules, and Moroccan Darija RTL BiDi code-switching typography.

---

## 1 · Media Treatments (`scripts/ev1_treat.py`)

| Look | When to Use | Characteristic Share |
|---|---|---|
| `teal` split (teal shadows, cream highlights) | Establishing shots, infrastructure, architecture | 22% of B-roll |
| `mono` high-contrast B&W | Docs, git logs, archival, serious turning points | 18% |
| `warm` amber/sepia | High-stakes bugs, historical code, warnings | 8–11% |
| `invert` negative | 1–2 frame transition flashes, strobe pulses | Flashes |
| `natural` + subtle push + vignette | Hero footage, production UI captures | 35–45% |
| `recolor FROM-TO:TARGET` | Feature variations, theme comparisons | Selective |
| `halftone` (0.16–0.35) | Technical diagrams, schematics, vintage manual scans | As needed |

### Screencast & Camera Treatment
- **Your camera stays RAW:** No LUT, no heavy grading, no vignette on face beats. The raw plate is re-timed to 30 fps CFR (`-g 30`, `-crf 14`, `bt709`).
- **Omarchy Corner Webcam:** 8:9 aspect ratio overlay detected by `scripts/omarchy_detect.py`. In the hook, `screen_zoom(..., webcam_box=...)` pins the webcam card above the zoom. In the body, `body_render.py` tracks it and redraws it 1.35x larger with rounded corners, a border and a shadow; it never zooms away.

---

## 2 · Typography & BiDi Architecture

Typography follows a strict tier system with zero intermediate sizes. All Arabic / Darija copy renders in **Cairo** (700 bold), while Latin technical terms render in **Inter** or **JetBrains Mono**.

### Caption Tier
- **62px, weight 600** white (`.ev1-cap`: the `--ev1-sans` stack, so Latin is Inter and Arabic falls
  back to Cairo via "EV2 Arabic"), centered horizontally at 49–52% height.
- Layered soft black shadow plus a faint bloom (`--ev1-cap-shadow`, `--ev1-cap-bloom` in `tokens.css`).
- **RTL BiDi Rules:** Container has `dir="rtl"`. Any Latin technical term (e.g. `Docker`, `Kdenlive`, `Git`, `Python`) is automatically wrapped inside `<bdi>` by `bidi_text()` or `bidi_span()`, preventing Hebrew/Arabic bidi inversion bugs.
- Over rebuilt UIs or editor screencasts, a smaller caption (about 86%) avoids covering code. This is
  a style rule, not automatic: pass `y=`/sizes yourself (`captions` has no scale switch).

### Display Tiers
1. **Key:** 132px Arimo bold white (`.ev1-key` in `tokens.css`) with 6-frame blur-in for stressed technical terms.
2. **Title:** 136px Playfair Display chrome italic with drop shadow for chapter titles and concept naming.
3. **Shock:** 176px Bodoni Moda uppercase in `#F2030A` crimson, cutting on hard for catastrophic bugs or major takeaways (max 1–2 per video).
4. **Mega:** 560px Inter 900 red positioned behind the speaker's head (between raw plate and RVM alpha matte).

---

## 3 · Rhythm & Pacing

Editor V2 employs a **hybrid rhythm architecture**:

1. **The Hook (0:00 – ~0:20; aim for 15–25 s):**
   - High-tempo documentary pacing (median held shot: 0.6–1.2s).
   - Frequent ground changes: black card → treated screenshot → pop cards → shock word → flow diagram.
   - 78–113 SFX cues per minute, locked to word onsets within ±1 frame.
2. **The Tutorial Body (end of hook – end):** made by `body_render.py`, not by devices.
   - Cleaned screencast at natural tutorial pace (1.5–3.5s per action/focal area).
   - Pauses longer than 0.6 s are shortened to 0.3 s of air (1.2 s while the screen is busy), not removed.
   - Retake candidates are reported by `clean-retakes.py`; only the ones the creator approves are cut.
   - Structural transitions marked by automatic chapter lower-thirds (from `timeline.json` chapters).
   - Attention guided by automatic zooms (up to 2x) that follow localized screen activity.

---

## 4 · Speaker & Screencast Layouts

1. **Documentary Face Beat:** Speaker full-screen raw camera for personal claims, punchlines, or conclusions.
2. **Mega Word Face Beat:** Speaker matted in front of a 560px red keyword during critical caveats.
3. **Omarchy PiP Screencast:** Clean full-screen 1080p desktop with 8:9 corner webcam overlay.
4. **ROI Zoom Screencast:** Camera zooms into a specific terminal command or code block (scale 1.4x to 2.2x), with the corner webcam card pinned in the foreground.
5. **Architectural Graph (`flow_diagram`):** Dark glass cards with glowing borders and animated SVG arrows explaining system connections before diving into implementation.
