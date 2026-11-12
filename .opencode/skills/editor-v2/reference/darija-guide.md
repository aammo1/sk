# Moroccan Darija (الدارجة المغربية) Technical Code-Switching Guide

In Moroccan technical screencasts, developer tutorials, and engineering presentations, speech naturally alternates between Moroccan Darija (الدارجة) for grammar, connective phrases, and explanations, and English for technical terminology.

Editor V2 is specifically designed to handle this code-switching seamlessly across speech-to-text transcription, phonetic dictionary correction, bidirectional (BiDi) typesetting, and animated captions.

---

## 1 · Code-Switching Anatomy in Darija Tech Content

Moroccan developers communicate using a rich linguistic blend:
- **Darija Grammatical Frame:** Verbs (كانديرو، كانخدمو، تقاد), prepositions (بـ، فـ، لـ), demonstratives (هاد، داك), temporal markers (دابا، من بعد), and relative pronouns (اللي).
- **English Technical Tokens:** Tool names, protocols, programming languages, CLI commands, and libraries (e.g. `Docker`, `Git`, `Hyprland`, `Kdenlive`, `Omarchy`, `Antigravity`, `OpenCode`, `DeepSeek`, `Terminal`, `FFmpeg`, `TypeScript`, `Next.js`).

### Example Spoken Phrase:
> **Spoken:** "هاد الفيديو تقاد بـ Editor V2 باش نسجلو الشاشة فـ Omarchy Linux ونخرجو Kdenlive timeline."
> **Translation:** "This video was edited with Editor V2 to record the screen in Omarchy Linux and export a Kdenlive timeline."

---

## 2 · Phonetic Dictionary Correction (`scripts/transcribe.py`)

Standard Whisper models often attempt to transcribe English tech words into phonetic Arabic script. Without correction, this produces confusing Arabic transliterations rather than crisp industry terms.

`scripts/transcribe.py` integrates a multi-stage post-processor (`fix_tech_terms`):

### 2.1 The Core Lexicon (`TECH_MAP_WORDS`)
Transliterations are mapped to standard casing:

| Arabic Transliteration | Normalized Latin Term |
|---|---|
| `كلود` | `Claude` |
| `دوكر` | `Docker` |
| `لينكس` | `Linux` |
| `جيت هاب` | `GitHub` |
| ~~`جيت`~~ | *not mapped on purpose*: جيت is everyday Darija for "I came". Fix `Git` by hand in `words.json`. |
| `بايثون` | `Python` |
| `تيرمينال` | `Terminal` |
| `أومارشي لينكس` / `اومارشي` | `Omarchy Linux` / `Omarchy` |
| `هايبرلاند` | `Hyprland` |
| `أنتيغرافيتي` / `انتيغرافيتي` | `Antigravity` |
| `أوبن كود` / `اوبنكود` | `OpenCode` |
| `ديب سيك` / `ديبسيك` | `DeepSeek` |
| `نيكست جي اس` | `Next.js` |
| `تايب سكريبت` / `تايبسكريبت` | `TypeScript` |
| `اف اف ام بيج` / `إف إف إم بيج` | `FFmpeg` |
| `كدينلايف` | `Kdenlive` |
| `واتساب` | `WhatsApp` |

**French terms** (Darija code-switches into French too, especially for UI and e-commerce words):

| Arabic transliteration | Latin term |
|---|---|
| `كوماند` / `كماند` / `كوموند` (+ `ات`) | `commande(s)` |
| `ليفريزون` | `livraison` |
| `بوتيك` | `boutique` |
| `ستوك` | `stock` |
| `ريتور` (+ `ات`) | `retour(s)` |
| `اكسبيديسيون` / `اكسبيديسيو` | `expédition` |
| `فاكتور` / `فاكتورة` | `facture` |
| `تابلو دو بور` | `Tableau de bord` |

Multi-word keys match across consecutive words. Add your own in `~/.config/editor-v2/darija-terms.json`
(`{"فيرسل": "Vercel"}`); their Latin values are also passed to Whisper as **hotwords** in every 30 s
window (with the built-in `HOTWORDS` list and `EV2_HOTWORDS`), which nudges the decoder to write the
term correctly in the first place.

### 2.2 Attached Darija Preposition Separation
Darija prepositions and the article attach directly to the noun without a space. The engine strips
these clitics (longest first: `وال بال فال كال لل ال`, then `بـ لـ فـ وـ`, then `ب ل و ف`) and
reconstructs the token:

- **Article `الـ` (and `بالـ`, `للـ`, ...):**
  - Raw ASR: `الكماند` / `بالليفريزون`
  - Engine Result: `الـ commande` / `بالـ livraison`

- **Preposition `بـ` (with / by means of):**
  - Spoken: `بدوكر` or `بـ دوكر`
  - Raw ASR: `بدوكر`
  - Engine Result: `بـ Docker`
- **Preposition `لـ` (for / to):**
  - Spoken: `لدوكر`
  - Engine Result: `لـ Docker`
- **Conjunction `وـ` (and):**
  - Spoken: `وكلود`
  - Engine Result: `وـ Claude`
- **Preposition `فـ` (in / on):**
  - Spoken: `فتيرمينال`
  - Engine Result: `فـ Terminal`

---

## 3 · Bidirectional (BiDi) Layout Architecture

When right-to-left (RTL) Arabic script contains embedded left-to-right (LTR) Latin words, naive web rendering inverts sentence ordering and misplaces trailing punctuation.

Editor V2 enforces a three-point BiDi contract:

### 3.1 Container Directionality
The parent container holding Arabic text **must** declare `dir="rtl"`:
```html
<div class="ev1-cap" dir="rtl">
  <!-- words here -->
</div>
```

### 3.2 Bidirectional Isolation (`<bdi>`)
Every Latin technical word inside an Arabic phrase is wrapped inside a `<bdi>` tag via `bidi_text()` or `bidi_span()`:
```html
<span>هاد</span>
<span>الفيديو</span>
<span>بـ</span>
<span><bdi>Editor V2</bdi></span>
```
`<bdi>` isolates the directional context, preventing the browser's Unicode Bidirectional Algorithm (UBA) from flipping words or wrapping punctuation to the opposite end of the line.

**Known gap:** a clitic fix produces ONE caption word that mixes scripts (`بـ Docker`). Because it
contains Arabic, `bidi_span` does not wrap its Latin part in `<bdi>`. It renders correctly in
practice, but check those words on the contact sheet.

### 3.3 Typography Token (`tokens.css`)
In `assets/tokens.css`, the Arabic typography stack is pinned:
```css
--ev2-arabic: "EV2 Arabic", "Noto Sans Arabic", sans-serif;
```
"EV2 Arabic" is the full **Cairo variable font** (`assets/fonts/Cairo-Var.ttf`, weights 200–1000, OFL).
The Latin stacks (`--ev1-sans`, `--ev1-grotesk`, `--ev1-didone`) fall back to it for Arabic glyphs,
so captions (`.ev1-cap`, weight 600) render Arabic in Cairo and Latin in Inter. The mono stack has no
Arabic fallback. The body's burned-in captions and chapter cards (`body_render.py`) use the same
Cairo file through Pillow.

---

## 4 · Caption Modes (`caption_mode`)

`Comp(dur, caption_mode=...)` accepts these names. **Only `darija-ar` and `hook-only` are implemented**; `darija-latin` and `en` are planned (nothing romanizes or translates yet; pass them and you get `darija-ar` rendering). `caption_mode` only affects the hook composed by `build.py`. Body captions are separate: always written to `out/captions.srt`, burned into the body only with `ev2 finish --captions`.

### 1. `darija-ar` (Default)
- **Format:** Moroccan Darija in Arabic script with embedded Latin tech terms.
- **Audience:** Core Moroccan and North African developer community.
- **Appearance:** 62px Cairo 700 white with soft black shadow, fully RTL aligned.

### 2. `darija-latin` (Arabizi / Darija Latin) — NOT IMPLEMENTED
- **Format:** Romanized Moroccan Darija (e.g. *"Had l-video t9ad b Editor V2"*).
- **Audience:** Viewers comfortable reading Arabizi / Latin transcription on mobile.
- **Appearance:** 62px Inter 600 white centered captions.

### 3. `en` (English Translation) — NOT IMPLEMENTED
- **Format:** Full English technical translation of the Darija speech.
- **Audience:** Global developer audience, GitHub documentation links, international distribution.

### 4. `hook-only` (Hybrid Tutorial Optimization)
- **Behavior:** Captions are enabled **exclusively** during the high-tempo Hook (`0:00` to `HOOK_SPLIT`, e.g. `45.0s`).
- **Rationale:** During fast-paced documentary hooks, captions provide essential punch and pacing. During long technical screencasts (~7 minutes), persistent centered subtitles can obscure code lines, IDE sidebars, or terminal error outputs.
- **Implementation:** with `caption_mode='hook-only'`, `Comp` ignores caption groups whose start time `t >= hook_end`. The template uses `darija-ar`, where this filter does not run (the hook ends at `hook_end` anyway).
