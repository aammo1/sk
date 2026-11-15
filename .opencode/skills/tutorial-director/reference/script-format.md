# `script.json` Format

Each tutorial run lives under `~/tutorial-director/runs/<name>/` (overridable via `TD_HOME`) and is driven by `script.json`.

## Top-Level Fields

| Field | Required | Default | Description |
|---|---|---|---|
| `title` | yes | — | Short video title |
| `promise` | yes | — | Hook promise (supports `*highlight*` markers for `editor-v2`) |
| `lang` | no | `"darija"` | Spoken language tag |
| `voice` | yes | `{"engine": "golha", "ref": null, "speed": 1.0}` | `engine`: `"golha"` or `"lahgtna"`; `ref`: optional voice reference file; `speed`: `0.5`–`2.0` |
| `screen` | no | `{"monitor": "auto", "workspace": 9}` | Target monitor name (or `"auto"`) and Hyprland workspace integer (`>= 1`) |
| `studio` | no | `{"font_px": 18, "browser_zoom": 1.25, "wallpaper": "plain", "hide_bar": true, "cursor_px": 32}` | Studio environment tuning applied during recording |
| `pace` | no | `{"cps": 10, "settle_after": 1.0, "pre_click": 0.25}` | Default typing speed (`cps`), post-step settle seconds, and pre-click pause |
| `layout` | no | `{}` | Named window rectangles `{"slot": [x, y, w, h]}` in logical screen pixels |
| `face` | no | `null` | Reserved for future avatar support (unused) |
| `setup` | no | `[]` | List of actions executed once before step 1 (outside recording timing) |
| `steps` | yes | — | Non-empty list of tutorial step objects |
| `cleanup` | no | `[]` | List of actions executed after the last step (always runs even on failure) |

## Step Object

| Field | Required | Description |
|---|---|---|
| `id` | yes | Unique step identifier (e.g. `"s01"`) |
| `say` | yes | Spoken Darija narration (`1`–`220` characters) |
| `actions` | yes | Non-empty list (`>= 1`) of action objects |
| `chapter` | no | Chapter title (`<= 40` chars) with exactly one `" — "` separator, e.g. `"Intro — المقدمة"` |
| `layout` | no | `{"window": "class:Alacritty", "slot": "terminal"}` — places matching window into a top-level `layout` slot before acting |
| `callout` | no | `{"text": "...", "at_action": 0, "dur": 3}` — label (`<= 40` chars, `dur` `1`–`8` s) pointing at action `at_action` |
| `insert` | no | `{"recipe": "...", "dur": 12, "data": {...}}` — `editor-v2` animated explainer insert (`dur` `1.5`–`30` s) |
| `pause_after` | no | Extra pause in seconds (`>= 0`) after this step finishes |

Allowed `insert.recipe` values: `flow`, `steps`, `checklist`, `compare`, `stat`, `statement`, `screens`.

## Actions

| `do` | Fields | Notes |
|---|---|---|
| `key` | `combo` (str) | Key chord, e.g. `"super+alt+space"`, `"Return"`, `"Escape"` |
| `type` | `text` (str), `cps?` (num > 0), `paste?` (bool) | Types text; `paste: true` uses clipboard paste + short typing burst. Subject to secrets guard |
| `move` | `to` (target) | Moves cursor to target |
| `click` | `to?` (target), `button?` (`left\|right\|middle`), `double?` (bool) | Clicks at `to` or current cursor position |
| `scroll` | `dy` (num), `to?` (target) | Scrolls vertically (optionally moving to `to` first) |
| `drag` | `from` (target), `to` (target) | Drags from `from` to `to` |
| `wait` | `s` (num >= 0) | Sleeps for `s` seconds |
| `wait_for` | `window?` \| `image?` \| `text?`, `timeout?` (num > 0) | Waits until window, template image, or OCR text appears |
| `focus` | `window` (str) | Focuses window via `hyprctl` (e.g. `"class:Alacritty"`) |
| `workspace` | `n` (int >= 1) | Switches to Hyprland workspace `n` |
| `launch` | `cmd` (str), `window?` (str) | Launches via `hyprctl dispatch exec`; optionally waits for `window` |
| `move_window` | `window` (str), `to` (`[x, y, w, h]`) | Moves & resizes window |
| `shell` | `cmd` (str) | Hidden helper command (never typed on screen) |
| `check` | `expect` (str), `image?` (str), `text?` (str) | Verifies screen state; aborts run if check fails |

### Target (`to` / `from`) Forms

- Absolute pixels: `[960, 540]`
- Window-relative fraction (`0.0`–`1.0`): `{"window": "class:firefox", "at": [0.5, 0.2]}`
- Image template match: `{"image": "assets/btn.png"}`
- OCR text match (requires optional `tesseract`): `{"text": "Save"}`

## Validation (`td check <run>`)

`td check` prints `FIX ...` lines and exits `1` if any check fails:
- Unique non-empty step `id`s
- Every step has `say` (`<= 220` chars) and `>= 1` action
- `chapter` titles `<= 40` chars with exactly one `" — "` separator
- `voice.engine` in `{golha, lahgtna}`
- `insert.recipe` in `{flow, steps, checklist, compare, stat, statement, screens}`
- **Secrets guard**: rejects `type.text` matching `(?i)(api[_-]?key|token|secret|password|passwd)|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}`

## Full Example

```json
{
  "title": "Omarchy menu f 3 dqayq",
  "promise": "Learn the *Omarchy menu* in 3 minutes",
  "lang": "darija",
  "voice": {"engine": "golha", "ref": null, "speed": 1.0},
  "screen": {"monitor": "auto", "workspace": 9},
  "studio": {"font_px": 18, "browser_zoom": 1.25, "wallpaper": "plain", "hide_bar": true, "cursor_px": 32},
  "pace": {"cps": 10, "settle_after": 1.0, "pre_click": 0.25},
  "layout": {"terminal": [160, 90, 1600, 900], "browser": [0, 0, 1920, 1080]},
  "setup": [{"do": "shell", "cmd": "pkill -x firefox || true"}],
  "steps": [
    {
      "id": "s01",
      "chapter": "Intro — المقدمة",
      "say": "سلام، اليوم غادي نشوفو Omarchy menu.",
      "actions": [{"do": "wait", "s": 0.5}]
    },
    {
      "id": "s02",
      "chapter": "Menu — اللائحة",
      "say": "ضغط على Super و Alt و Space باش تحل المينيو.",
      "actions": [
        {"do": "key", "combo": "super+alt+space"},
        {"do": "wait_for", "window": "class:walker", "timeout": 5},
        {"do": "check", "expect": "menu is open"}
      ],
      "callout": {"text": "Omarchy menu", "at_action": 0},
      "insert": {
        "recipe": "steps",
        "dur": 12,
        "data": {
          "title": "Omarchy Menu",
          "steps": [
            {"label": "Open menu"},
            {"label": "Search theme"}
          ]
        }
      }
    },
    {
      "id": "s03",
      "say": "اكتب theme وضغط Enter باش تبدل الستايل.",
      "actions": [
        {"do": "type", "text": "theme", "cps": 10},
        {"do": "key", "combo": "Return"}
      ],
      "pause_after": 0.6
    }
  ],
  "cleanup": [{"do": "key", "combo": "Escape"}]
}
```
