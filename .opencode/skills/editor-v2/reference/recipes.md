# Recipes: the designed parts you fill with data

Everything that makes the video look designed is code. You write small JSON; the code does
layout, motion, timing, sound and colour, the same way every time. Copy an example, change the
words, run `ev2 check <dir>`. Never write HTML, CSS or animation code for these.

The colour comes from `work/look.json` (`accent: "auto"` = the app's own brand colour, picked
from the recording). Text may be Darija, French or English; Darija is set right-to-left
automatically. Wrap a word in `*stars*` to colour it with the accent.

---

## 1. The hook: `work/hook.json`

`ev2 hook <dir> --init` writes it with the best moments of the recording already picked
(one per chapter, labelled from the chapter titles). You write **only the promise**, then
`ev2 hook <dir>` (draft) and `ev2 hook <dir> --final`.

```json
{
  "recipe": "showcase",
  "promise": "من *الطلب* حتى التسليم فـ 6 دقايق",
  "brand": "Zehri",
  "title": "Zehri — إدارة الطلبات",
  "shots": [
    {"src_t": 152.0, "label": "Commandes", "icon": "shopping-bag"},
    {"src_t": 291.5, "label": "Ozon Express", "icon": "truck"}
  ],
  "agenda": true
}
```

| key | rule |
|---|---|
| `promise` | **required.** One line, <= 60 chars: what the viewer gets ("Deploy a Next.js app in 5 minutes", "من الطلب حتى التسليم"). Not a greeting, not the title. |
| `brand` | optional, <= 24 chars: product/channel name, shown as a small chip |
| `title` | optional, <= 70 chars: the end-card title (default: `hook_title` in timeline.json) |
| `shots` | optional: `src_t` = SOURCE seconds in the tutorial body; `label` <= 28 chars; `icon` optional. Leave the auto-picked ones unless the creator wants other moments. |
| `recipe` | `showcase` (default: promise → montage → end card) or `calm` (title card over the live screen) |
| `agenda` | `true` = the chapters appear as chips on the end card |

Good promises: a result, a time, a contrast. "Ship your first app in 10 min". "بلا Excel: كل
الطلبات فبلاصة وحدة". Bad: "Hello guys", "Tutorial part 3", a full sentence of 15 words.

---

## 2. Explainer inserts: `"inserts"` in `work/timeline.json`

A full-screen animated scene that replaces the screen for 4-12 s while the voice keeps going.
Use one every 2-3 minutes, where the speaker explains a concept (a flow, steps, a comparison).
`src_t` = SOURCE seconds where it starts. `ev2 inserts <dir>`, then `ev2 inserts <dir> --final`.

Items are strings, or objects `{"label", "sub", "icon", "at"}`:
`label` <= 34 chars, `sub` <= 60 chars (smaller line under it), `icon` = a Lucide name
(https://lucide.dev/icons, e.g. `truck`, `shopping-cart`, `database`) or `brand:<name>`
(`brand:whatsapp`, `brand:github`, `brand:docker` ...) or left out (guessed from the label),
`at` = local second it appears (default: spread over the first half, or when the label is said).

### flow — steps joined by arrows, a glowing dot travels the path (2-6 steps)
```json
{"name": "order-flow", "src_t": 126.0, "dur": 8, "recipe": "flow",
 "data": {"title": "كيفاش كتدوز *الطلبية*", "kicker": "Order flow",
          "steps": ["Boutique", "Commande", {"label": "WhatsApp", "sub": "Confirmation"}, "Ozon Express"]}}
```

### steps — numbered list + a big icon that follows the current step (2-6 steps)
```json
{"name": "ship-steps", "src_t": 330.0, "dur": 8, "recipe": "steps",
 "data": {"title": "من التأكيد حتى *التسليم*",
          "steps": [{"label": "Confirmer la commande", "sub": "WhatsApp + appel"},
                    {"label": "Créer le BL", "sub": "PDF signé"},
                    {"label": "Remise au livreur", "sub": "Ozon Express"}]}}
```

### checklist — rows tick one by one (2-8 items)
```json
{"name": "before-confirm", "src_t": 60.0, "dur": 7, "recipe": "checklist",
 "data": {"title": "قبل ما تأكد الطلب", "items": ["Nom complet", "Téléphone", "Adresse", "Stock disponible"]}}
```

### compare — two columns, bad vs good, VS badge (1-5 items per side)
```json
{"name": "before-after", "src_t": 180.0, "dur": 7, "recipe": "compare",
 "data": {"title": "Avant / *Zehri*",
          "left": {"title": "Avant", "items": ["Excel + WhatsApp", "Commandes perdues"]},
          "right": {"title": "Avec Zehri", "items": ["Tout dans un tableau", "Rappels automatiques"]}}}
```

### stat — one big number counting up (+ up to 3 small numbers)
```json
{"name": "pending", "src_t": 230.0, "dur": 6, "recipe": "stat",
 "data": {"value": "10", "label": "commandes en attente aujourd'hui",
          "items": [{"value": "0", "label": "Rappels dus"}, {"value": "3", "label": "Échecs"}]}}
```

### statement — one big sentence (a rule, a key idea), optional icon (<= 90 chars)
```json
{"name": "golden-rule", "src_t": 270.0, "dur": 5, "recipe": "statement",
 "data": {"text": "Chaque commande passe par *WhatsApp* avant l'expédition", "icon": "brand:whatsapp", "kicker": "Règle d'or"}}
```

### screens — 1-3 screenshots from the recording, fanned in 3D, with labels
```json
{"name": "key-screens", "src_t": 370.0, "dur": 6, "recipe": "screens",
 "data": {"title": "Les 3 écrans clés",
          "shots": [{"src_t": 150, "label": "Commandes"}, {"src_t": 290, "label": "Ozon Express"}, {"src_t": 395, "label": "Stock"}]}}
```

Optional on every insert: `"cam": true` keeps the speaker's PiP on top (default: it fades out
during a full-screen insert). `"kicker"`: a small uppercase line above the title.

---

## 3. Callouts: `"callouts"` in `work/timeline.json`

An accent label that points at the thing being clicked, following the zoom. 2-5 per video, on
the buttons that matter. With an input log (`ev2 rec`) it lands exactly on the click nearest
`src_t`; without one it points at the screen activity, or give `x`/`y` (cam_raw pixels).

```json
"callouts": [
  {"src_t": 91.2, "text": "Confirmer ici", "dur": 3},
  {"src_t": 205.0, "text": "WhatsApp: تأكيد", "x": 1310, "y": 640}
]
```
`text` <= 40 chars, `dur` 1-8 s (default 3).

---

## 4. The look: `work/look.json` (`ev2 look <dir> ...`)

```json
{"accent": "auto", "frame": "inset", "inset": 0.9, "max_zoom": 1.6, "trim": "auto",
 "click_fx": true, "click_sfx": true, "chapter_sfx": true, "auto_keys": true}
```
Leave the defaults unless the creator asks: `accent` a brand hex (`"#E11D74"`), `frame: "full"`
for edge-to-edge screen, `max_zoom` lower (1.4) for dense UIs, `trim: "off"` if the edges are
part of the content.
