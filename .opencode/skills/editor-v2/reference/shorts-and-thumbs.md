# Pro 9:16 Shorts, Standalone Reels & Studio Thumbnails (v3.2)

Everything stays **DATA, not code**: the agent fills small JSON files (`work/shorts.json`, `work/thumbs.json`)
and the code builds the 1080×1920 HyperFrames Reels and 1280×720 thumbnails using your video's own brand theme,
`Cairo` + `Inter` fonts, and automatic Moroccan Darija + Latin BiDi isolation.

---

## 1. Pro Shorts from a Tutorial (`ev2 shorts`)

After `ev2 finish <dir>` (or right after `ev2 transcribe <dir>`):
```bash
ev2 shorts <dir> --init       # writes starter work/shorts.json + face check PNGs
ev2 check <dir>               # validates work/shorts.json (spans, recipes, 0 empty-band gaps)
ev2 shorts <dir> --final      # renders out/shorts/<name>.mp4 + .srt + review sheet
```

### `work/shorts.json` schema
```json
{
  "shorts": [
    {
      "name": "s1-order-flow",
      "layout": "stacked",
      "spans": [[122.0, 168.5]],
      "nudge": 0,
      "hook_kicker": "Zehri",
      "captions": true,
      "music": true,
      "beats": [
        {
          "at": 0.0,
          "dur": 3.5,
          "type": "card",
          "recipe": "statement",
          "data": {"kicker": "Zehri", "text": "بلا Excel: كل *الطلبات* فبلاصة وحدة"}
        },
        {
          "at": 3.5,
          "dur": 43.0,
          "type": "screen",
          "max_zoom": 1.85,
          "moves": [
            {"t": 3.5, "rect": [120, 60, 1680, 945], "dur": 0.0},
            {"t": 12.0, "rect": [420, 220, 960, 540], "dur": 0.65}
          ]
        }
      ]
    }
  ]
}
```

- **Layouts:**
  - `stacked`: Top `1080×1040` zoomed screen / recipe cards + seam word-highlighted captions (`y 1040..1180`) + bottom `1080×740` native-pixel face band. Always read `out/shorts/<name>_face_check.png`; adjust `"nudge"` (positive shifts right) if the face isn't on the red center line.
  - `talking-head`: Full-frame `1080×1920` speaker with subtle 10% punch-ins on cuts, split cards when a `"card"` beat plays, and captions in the mobile safe zone (`y 1300..1470`).
  - `screen-only`: No webcam — top badge + tall zoomed screen/cards + bottom word-highlighted captions.
- **Card recipes:** `statement`, `title`, `stat`, `steps`, `checklist`. Captions auto-hide during `statement`/`title` beats so words never double on screen.
- **No empty band:** In `stacked`/`screen-only`, beats must cover the full Short with no gap > 1.5 s (`ev2 check` catches gaps before rendering).

---

## 2. Standalone Short / Reel Mode (`--mode short`)

For a raw vertical (9:16) or short horizontal recording meant directly for Reels / Shorts / TikTok:
```bash
ev2 inspect <file>                      # Step 0 check & coaching
ev2 init <file> [name] --mode short     # preserves native 1080x1920 for vertical files
ev2 transcribe <dir>                    # tighter silence defaults (0.45s -> 0.18s, hook_split=0)
ev2 shorts <dir> --init                 # creates work/shorts.json
ev2 check <dir>
ev2 shorts <dir> --final                # -> out/shorts/reel-01.mp4 + .srt + review sheet
```

---

## 3. Dual-Mode Studio Thumbnails (`ev2 thumb`)

### Mode A — Local Free Studio Thumbnails (default, 100% offline)
```bash
ev2 thumb <dir> --init [--face photo.jpg]   # extracts sharpest face + screen -> work/thumbs.json
ev2 thumb <dir>                             # renders 3 1280x720 PNGs + grid.png + grid_phone.png
```
Always inspect **`out/thumbs/grid_phone.png`** (246×138): if the headline isn't instantly readable at phone feed size, shorten it to 2–4 punchy words (`*word*` highlights in brand accent).

Templates in `work/thumbs.json`:
- `split-hero`: angled app screen + speaker portrait + bold headline
- `big-stat`: giant accent stat (`6 دقايق`, `10x`) + headline + portrait
- `compare-vs`: red `left_text` vs accent `right_text` with `VS` badge

### Mode B — Optional OpenRouter AI Concepts (opt-in only)
Only run when the user asks AND `OPENROUTER_API_KEY` is set (env or `~/.config/editor-v2/.env`):
```bash
ev2 thumb --list-models
ev2 thumb <dir> --ai 'Developer pointing at glowing terminal. Text, exactly: "FAST SETUP"' [--models a,b]
```
Outputs go to `out/thumbs/ai_t1/` with `grid.png`, `grid_phone.png`, and USD costs logged in `work/costs.jsonl`.
