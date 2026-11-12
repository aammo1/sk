# Editor V2 — Device Library (45 functions)

The library has **45 public device functions**: 19 in `components/ev1_devices.py`, 19 in
`components/ev1_more.py` and 7 tutorial devices in `components/ev2_tutorial.py`. The index
below covers the 30 most used (numbered as in the original catalogue); the remaining 14 are
documented under [More devices](#more-devices-the-other-14), and `black_card` is a pattern,
not a function (see 13). Signatures here are copied from the code; when in doubt, read the
function's docstring.

Devices run in the **hook** (`build.py` composes source `[0, hook_split)`), and in **explainer
inserts** in the body (see "Explainer inserts" below). The tutorial body is appended by
`ev2 finish`, and its zooms, webcam PiP and chapter cards are automatic (`body_render.py`), not devices.

**`z` is required** (positional, after the media/content arguments) on most documentary
devices: `still(c, t0, t1, src, 1)`, `seq(c, items, 1, t_end)`. Check the signature column.
The SFX column lists what the code really cues; roles are the keys of `SND` in
`components/ev1_devices.py` (`click click_soft key_click swish whoosh hit impact glitch tick
riser subtone subboom outro train_pop train_tile train_tile2 train_strobe`). `sfx()` with any
other name raises KeyError.

```python
from ev2_tutorial import *     # every device + Comp, fr, esc, sfx, bidi helpers
```

---

## Quick Reference Index

| ID | Device Name | Primary Use Case | SFX Cue |
|---|---|---|---|
| **01** | `tile_reveal` | Chapter open, world swap, grid flash reveal | `train_tile` / `train_tile2` (by seed) |
| **02** | `cutout_world` | Matted speaker in front of changing background | `hit` (+ tile trains) |
| **03** | `pop_collage` | Rapid count of items landing on chalkboard | `click` per pop |
| **04** | `wall3d` | Sweeping 3D perspective plane of screenshots | `whoosh`, only with `sound=True` |
| **05** | `paper_card` | Quoting documents/sources on vignetted paper | `click` |
| **06** | `strobe` | High-tempo 2-3 frame thematic shape flashes | `train_strobe` |
| **07** | `focus_card` | Document or post racking from blur to sharp | `click_soft` |
| **08** | `terminal` | Rebuilt UI/receipt with typing and checkmarks | `click_soft` |
| **09** | `typewriter` | Monospaced code/quote typing with cursor | `click_soft` |
| **10** | `frames` | Datamosh, RGB split slices, glitch cuts | `glitch` (`sound=`) |
| **11** | `neg_flash` | 1-2 frame negative color invert flash | `click` (`sound=`) |
| **12** | `keyword` | Display typography (key, title, shock, mega) | none unless `sound=` |
| **13** | *black card* (pattern) | Dramatic pause, caption alone on pure black | none (bed cut is manual) |
| **14** | `still` | Static treated plate with subtle push/pan | none |
| **15** | `broll` | Moving footage with rate, focus, and punches | none |
| **16** | `seq` | Hard-cut sequence of stills on spoken words | `click` (`click=`) |
| **17** | `vseq` | Hard-cut sequence of moving clips on words | `click` (`click=`) |
| **18** | `pop_shatter` | Cards pop on words, pull out 11%, shatter | `click` + `hit` |
| **19** | `whip_out` | Accelerating zoom-out over final frames | none |
| **20** | `silence_cut` | Editor waveform showing dead silences snapped | `click` |
| **21** | `edit_timeline` | Multi-track timeline preview with sweep | `click_soft` |
| **22** | `comment_box` | Rebuilt social comment composer with typing | none |
| **23** | `bed_wave` | Music bed waveform scrolling under center line | none |
| **24** | `filmstrip` | Perforated filmstrip of video frames racing past | `click` |
| **25** | `player_window` | Video shrinking into framed player window | `click_soft` |
| **26** | `screen_zoom` | Dynamic camera zoom into ROI with spotlight | `click_soft` |
| **27** | `shortcut_pill` / `cmd_toast` | Glass keyboard keycaps & CLI prompt toasts | `key_click` (one cue) |
| **28** | `chapter_banner` | Fullscreen title card or sleek lower-third | card: `swish` + `hit`; lower third: `click_soft` |
| **29** | `flow_diagram` | Architecture node graph with glowing arrows | `click` + `click_soft` |
| **30** | `split_compare` | Side-by-side comparison with staggered bullets | `click_soft` |
| **+** | `omarchy_cam_pip` | Omarchy 8:9 corner webcam crop and pin card | none |

---

## Documentary Devices (01 – 25)

### 01 · Tile-flash reveal — `tile_reveal(c, t, src, z, cols=3, rows=3, frames_n=10, seed=1, size=(2112, 1188), click=True)`
- **Seen:** REF-1 0.12–0.46s (street → Golden Gate), 1.88–2.17s; full-res f6, f9, f49.
- **Description:** A rule-of-thirds grid (428/855 and 240/480 px) where panes switch one per frame in pseudo-random order. Each pane flashes solid white for one frame before displaying the new image.
- **Sound:** Click train at 1 click/frame (`clicktrain_1` / `clicktrain_2`).
- **Use:** Chapter intros, sudden scene swaps, opening frame of the video.

### 02 · Cut-out on a changing world — `cutout_world(c, t0, t1, worlds, matte_src, matte_first_s, z=1, mega=None, matte_rate=0.0, tiles=True)`
- **Seen:** REF-1 0–4.5s (Palmer Luckey beach photo cutout with rotating background).
- **Description:** Matting plate extracted via `scripts/matte.py` (rembg first, else RVM at downsample 0.4; VP9 with alpha). Matted speaker stands still while backgrounds swap via tile reveals. Mega display word placed directly behind the speaker's head (`z=10`), under the cutout video (`z=20`).

### 03 · Pop collage — `pop_collage(c, t0, t1, cards, z, ground='black')`
- **Seen:** REF-2 0.0–1.0s (B&W photos landing on dark ground).
- **Description:** Cards pop in on spoken words, each preceded by a 1-frame white bounding box. The entire collage gently drifts in perspective.
- **Sound:** `click` on every pop.
- **Use:** Listing 2 to 4 items, features, or examples on consecutive words.

### 04 · 3D wall — `wall3d(c, t0, t1, tiles, z, cols=4, tile_w=760, gap=40, rot=(56, 0, -24), travel=(-1500, 380), sound=False)`
- **Seen:** REF-1 41.4–45.3s (endless plane of screenshots, motion-blurred).
- **Description:** Perspective grid tilted in 3D CSS space with camera gliding across real screenshots, articles, or code snippets.
- **Use:** "Everyone is talking about this", "found everywhere", dense ecosystem overviews.

### 05 · Paper card — `paper_card(c, t0, t1, src, z, card_w=1000, left=(), right=(), invert_in=2)`
- **Seen:** REF-1 8.2–9.0s.
- **Description:** Source image or document card centered on a vignetted paper-white background, flanked by small ink typographic quotes. Opens with a 2-frame invert flash.
- **Use:** Quoting a specific news article, paper, or research claim.

### 06 · Strobe — `strobe(c, t0, t1, srcs, z, step_frames=3, tracker=True, seed=4)`
- **Seen:** REF-2 83.2–84.6s ("perception" sequence).
- **Description:** Rapid succession of thematic images holding 2 to 3 frames each, sharing a consistent visual silhouette (circles, stamps, symbols).
- **Sound:** Rapid strobe click train (`clicktrain_4`).
- **Use:** Emphasizing single abstract nouns or dramatic escalations.

### 07 · Rack-focus card — `focus_card(c, t0, t1, src, z, card_w=1180, frames_n=12, mark=None, ground='black')`
- **Seen:** REF-1 9.9s (blur racking to sharp over ~10 frames).
- **Description:** Full-bleed or floating document that transitions from heavy gaussian blur to crisp focus, with an animated yellow highlighter sweeping across the cited line.

### 08 · Rebuilt terminal / UI — `terminal(c, t0, t1, cmd, rows, z, stop_t, marks=(), font=34, cmd_frames=10)`
- **Seen:** REF-1 13.0–14.5s (rebuilt PayPal receipt), REF-2 69.6s (ChatGPT input).
- **Description:** Pixel-accurate reconstructed software interface displaying real data and API parameters without compression artifacts.

### 09 · Typewriter — `typewriter(c, t0, t1, lines, z, font=46, top=380)`
- **Seen:** REF-2 51.8–52.8s ("with no ▮").
- **Description:** Monospaced typing across a dark terminal plate, complete with a blinking rectangular cursor and subtle CRT scanline flickering.

### 10 · Datamosh — `frames(c, t0, srcs, z, per=1, sound='glitch')` + `ev1_treat.glitch_frames`
- **Seen:** REF-1 f192–195 (8.00–8.12s: RGB-split slices).
- **Description:** 3 to 4 frames of compressed artifact smears and chromatic aberration slices transitioning hard into the subsequent scene.
- **Sound:** Glitch burst (`glitch_1`).

### 11 · Invert flash — `neg_flash(c, t, ids, sound='click')`
- **Seen:** REF-2 f503–504 (#1 Signaling → cyan negative → cut).
- **Description:** 1 to 2 frames of inverted color luminance, transitioning high-energy beats into dark plates.

### 12 · Display words — `keyword(c, t0, t1, text, z, x=960, y=540, kind='key', blur_in=True, sound=None, size=None)`
- **Tiers:**
  - `kind='key'`: 132px Arimo bold white (`--ev1-key-size`), 6-frame blur-in. Stressed spoken word.
  - `kind='title'`: 136px Playfair Display chrome italic with drop shadow.
  - `kind='shock'`: 176px Bodoni Moda caps in vivid crimson (`#F2030A`). Max 1-2 per video.
  - `kind='mega'`: 560px Inter 900 red positioned behind the speaker's head.

### 13 · Black card (pattern, no function) — pure silence / dramatic break
- **Seen:** REF-2 66.2s, 82.1s.
- **Description:** Minimalist white caption isolated on solid black. Music bed is cut completely to command absolute audience focus.
- **How:** `c.clip(t0, t1, '<div class="ev1-layer ev1-black"></div>', z=1)` + `captions(c, [(words, t1)])`. Cutting the bed under it is manual today: `ev2 finish` does not pass `--ramp` to `bed-mix.py` (see `sound-design.md`).

### 14 · Still plate — `still(c, t0, t1, src, z, push=1.06, origin='50% 50%', size=(2112, 1188), push_from=1.0)`
- High-resolution treated still with subtle continuous scale push (1.0 -> 1.06).

### 15 · B-Roll clip — `broll(c, t0, t1, src, z, rate=0.055, direction='in', focus_in=0, start_scale=None, origin='50% 50%', media_start=0.0, punches=(), style='')`
- Moving video layer with steady push, optional focus racking, and instant scale punches on stressed syllables. Use a small `rate` (e.g. 0.012) for the speaker's raw camera.

### 16 · Stills sequence — `seq(c, items, z, t_end, click='click', push=0.05, rot=0.0, seed=1, fit='cover', ground='black', origin='50% 50%', dim=None, white_box=False)`
- Rapid-fire hard cut of treated stills, advancing on each word onset with click SFX. Note the order: `z` comes BEFORE `t_end`.

### 17 · Video sequence — `vseq(c, items, z, t_end, click='click', rate=0.06, focus_in=0)`
- Synchronized chain of moving B-roll video fragments cut to the spoken cadence (`z` before `t_end`).

### 18 · Pop and shatter — `pop_shatter(c, t0, t1, cards, z, ground_src=None, shatter=True)`
- **Seen:** REF-2 0.00–1.16s.
- Cards pop in with 1-frame white bounding boxes, stack pulls out by ~11%, then shatters into fragmented white blocks across 2 frames.

### 19 · Whip out — `whip_out(c, vid, t_end, frames_n=4)`
- Exponential zoom out accelerating over final 4 frames (x1.15, 1.30, 1.45, 1.83) with motion blur into the next cut. No sound of its own.

### 20 · Silence cut visualizer — `silence_cut(c, t0, t1, wav, win, silences, cut_at, z, width=1680, clip_name=None)`
- Needs numpy and a non-empty `cut_at`. Do not use it in the same comp after `typewriter` until the `css_once` key clash is fixed (its CSS is skipped).
- Audio waveform visualizer rendering real audio, highlighting detected pauses in red and snapping them shut with click cues.

### 21 · Timeline visualizer — `edit_timeline(c, t0, t1, view, clips, words, cues, z, sweep=None, wav=None, hl_word=None)`
- Multi-track timeline reproduction featuring video thumbnails, speech waveforms, and sweeping playhead marker.

### 22 · Comment composer — `comment_box(c, t0, t1, z, placeholder='Add a comment…', avatar_letter='Y', type_text='', type_at=None, fpc=2)`
- Clean social comment composer with profile badge, typing prompt, and blinking caret.

### 23 · Bed wave — `bed_wave(c, t0, t1, wav, song_at, z, span=6.0, color='#F2F2F2')`
- Real music bed waveform scrolling across a calibrated red center needle.

### 24 · Filmstrip — `filmstrip(c, t0, t1, thumbs, z, tw=420, travel=None)`
- Tilted cinematic 35mm filmstrip carrying video frame thumbnails racing across the frame.

### 25 · Stepped player window — `player_window(c, t0, t1, src, media_start, z, steps=((0.0, 1.0), (3, 0.7), (6, 0.46)), dur_label='0:46', bar_t=None)`
- Video scaled into an OS window frame shrinking through distinct discrete steps (100% -> 70% -> 46%).

---

## Tutorial Devices (26 – 30)

### 26 · Screen Zoom — `screen_zoom(...)`
```python
screen_zoom(c, t0, t1, src, roi, z=1, media_start=0.0,
            zoom_in_frames=8, zoom_out_frames=8,
            highlight_box=None, webcam_box=None)
```
- **Description:** Dynamic camera zoom targeting a designated region of interest (ROI) on a high-resolution screencast or code editor.
- **ROI:** `(x, y, w, h)` in 1920x1080 screen coordinates. Computes smooth transform-origin at the ROI centroid.
- **Highlight Box:** Optional `(hx, hy, hw, hh)` highlighting an active function or terminal output with a glowing neon border and soft drop shadow.
- **Webcam Box:** When provided, pins the speaker's corner webcam card at `z + 2` so zooming into the workspace never cuts off or distorts the speaker's face.
- **Sound:** `click_soft` on zoom onset.

### 27 · Shortcut Pill & Command Toast
#### `shortcut_pill(c, t0, t1, keys, label='', z=65, x=960, y=920)`
- **Description:** Dark translucent glass pill displaying keycaps joined by `+` separators. Pops in with elastic spring physics.
- **BiDi:** Native support for Arabic/Darija labels alongside Latin key symbols (e.g., `['Super', 'Shift', 'R']` with label `'تسجيل الشاشة'`).
- **Sound:** `key_click` on entrance.

#### `cmd_toast(c, t0, t1, cmd, z=65, y=900)`
- **Description:** Floating terminal capsule showing a shell prompt (`$`) with sequential character typing animation and glowing cursor.
- **Sound:** one `key_click` cue on appearance.

### 28 · Chapter Banner — `chapter_banner(...)`
```python
chapter_banner(c, t0, t1, number, title, subtitle='', z=70, style='card'|'lower_third')
```
- **Chapters:** Appends `(t0, f"{number} {title}")` to `c.chapters`; `build.py` writes these to `work/hook_chapters.json`, and `ev2 finish` merges them with the body chapters from `work/timeline.json` into `out/youtube-chapters.txt`.
- **Style `card`:** Cinematic full-screen title card with metallic chapter counter, Cairo/Playfair typography, animated accent divider, and ambient vignette. Sound: `swish` + `hit`.
- **Style `lower_third`:** Non-intrusive floating glass badge positioned over active screencast with colored accent border and slide-in transition. Sound: `click_soft`.

### 29 · Flow Diagram — `flow_diagram(...)`
```python
flow_diagram(c, t0, t1, nodes, edges=(), z=10, title='')
```
- **Description:** Technical architecture diagram with frosted glass cards, glowing borders, animated SVG connector arrows, and BiDi labels.
- **Nodes:** `[('id1', 'Omarchy Screencast', 360, 540), ('id2', 'Faster-Whisper INT8', 960, 540), ...]`
- **Edges:** `[('id1', 'id2', 0.25), ('id2', 'id3', 0.55)]`
- **Sound:** Sequential `click` on node reveals and `click_soft` on arrow draws.

### 30 · Split Compare — `split_compare(...)`
```python
split_compare(c, t0, t1, left, right, z=10, vs_label='VS')
```
- **Description:** High-contrast side-by-side comparison screen dividing before/after or manual/automated workflows.
- **Panels:** Two sliding dark gradient panels with custom accent colors (e.g. red for manual pain, green for automated solution).
- **Staggered Bullets:** Animated bullet points sliding in with cross/check indicators and `click_soft` SFX. Center circle badge with `VS` label pops in with back-bounce ease.

---

## Explainer inserts (devices in the body)

An insert is a short animated scene (1.5–30 s, ideally 4–12 s) placed at a moment of the body while the
voice keeps playing. It is listed in `work/timeline.json` (`"inserts": [{"name": "order-flow", "src_t": 135.2,
"dur": 8, "mode": "over", "cam": true}]`) and written in the video's `inserts.py`; `ev2 inserts <dir>` renders it.
- `mode: "full"`: an opaque full-screen scene, crossfaded in and out over 9 frames. Output `work/inserts/<name>.mp4`.
- `mode: "over"`: a transparent animation drawn over the dimmed, blurred screencast. Output `work/inserts/<name>.mov` (ProRes 4444 alpha).
- `cam` (default true): the webcam PiP stays on top so the creator still appears to explain.

```python
@scene('order-flow')
def order_flow(c, ins):
    flow_diagram(c, 0.4, ins['dur'] - 0.4, ['Boutique', 'Commande', 'WhatsApp', 'Livraison'])
    captions(c, [(words(ins)[:6], ins['dur'])])
    run()
```

Rules:
- Times are **local** to the insert (0 = insert start). `words(ins)` returns the transcript words spoken during it, with local onsets.
- Design for 1920x1080 but keep the webcam corner free when `cam` is true.
- In `over` mode the page is transparent and the devices' black backdrop layers (`ev1-black`) and vignette are switched off automatically, so the screencast shows through. Don't add your own full-frame opaque layers or `finish(...)`. `terminal` paints its own opaque backdrop: use it in `full` inserts only.
- Devices that work best: `flow_diagram`, `split_compare`, `keyword`, `slap_caps`, `typewriter`, `code_scroll`, `terminal`, `cmd_toast`, `shortcut_pill`, `still`/`page_card` (with `hype_slide`).
- Other helpers: `asset(key)`, `ph(...)`, `example(label)`. `ev2 inserts <dir> --final` refuses while placeholders/missing assets remain.
- Hype (optional): `hype_slide('slides.md', 3)` renders slide 3 to a PNG via `hype render`. Write slides with `hype new slides.md` / `hype open slides.md`.

---

## Omarchy Corner Webcam Helper
### `omarchy_cam_pip(c, t0, t1, src, media_start=0.0, webcam_box=(1380, 500, 480, 540), z=50, style='', is_cropped=False)`
- **Description:** Crops and pins the Omarchy 8:9 webcam region into a floating card with rounded corners (`18px`), subtle outer glow, and clean white border.
- **Integration:** It does NOT read `work/omarchy.json` itself, and its default box matches no Omarchy
  preset. Always pass the detected box: `build.py` loads it as `CAM_BOX` (`webcam_box=CAM_BOX`).

---

## More devices (the other 14)

| Device | Signature | Use |
|---|---|---|
| `captions` | `captions(c, groups, z=60, y=None, on_paper=False, slots=None)` | **The caption device.** `groups = [([(word, onset), ...], t_end), ...]`; words appear on their onsets in pre-laid slots; Arabic words are set RTL with Latin terms isolated (`<bdi>`). Only `caption_mode='hook-only'` changes anything (drops groups at/after `hook_end`). |
| `captions_switch` | `captions_switch(c, words, segs, z=60, y=None)` | Captions whose position/style switches per segment (`segs`). |
| `svg_mark` | `svg_mark(c, t0, t1, svg_markup, z, width=980, x=960, y=540, color='#fff', blur_in=True)` | A logo/wordmark rebuilt as SVG (sharp at any size). |
| `img_mark` | `img_mark(c, t0, t1, src, z, width=520, x=960, y=540, white=False, blur_in=True, shadow=True)` | A logo from a PNG/JPG, optionally flattened to white. |
| `find_hop` | `find_hop(c, t0, t1, pages, query, z, type_at=None, fpc=2, counter='0/0', rate=0.05, dim=0.55)` | Browser find-bar typing a query and hopping between highlighted matches on page captures. |
| `overlay` | `overlay(c, t0, t1, src, z, blend='screen', opacity=1.0, media_start=0.0)` | Texture/light-leak video blended over the picture. |
| `white_flash` | `white_flash(c, t, z=90, frames_n=1, sound='click')` | 1-frame white flash on a cut. |
| `double_neg` | `double_neg(c, t, out_ids, in_ids, sound='click')` | Negative flash on both the outgoing and incoming layer. |
| `finish` | `finish(c, t0, t1, z=80, grid=True, vignette=True)` | The look's finishing layer: vignette, optional thirds grid, grain. |
| `calendar` | `calendar(c, t0, t1, months, events, z, pan=True)` | Month grid with events landing on dates (timelines, "in 3 weeks..."). |
| `code_scroll` | `code_scroll(c, t0, t1, lines, z, font=30, title=None, speed=None, hl=None, start_y=980, end_y=None)` | Scrolling code listing with an optional highlighted line range. |
| `slap_caps` | `slap_caps(c, items, t_end, z, y=640, size=132, big=None)` | Words slapped on screen one by one in heavy caps. |
| `triptych` | `triptych(c, t0, t1, vids, z, gap=10, rate=0.05)` | Three clips side by side. |
| `page_card` | `page_card(c, t0, t1, src, z, marks=(), mark_t=None, dark=False, focus_frames=6, push=0.05, step=4)` | A captured web page with highlighter marks swept in. |

Helpers: `fr(t)` (round to frame), `esc(s)`, `sfx(c, t, role, gain_scale)` (cue a sound role from `SND`),
`has_arabic`, `bidi_span`, `bidi_text`, `css_once`, `dstr`.
