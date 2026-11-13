"""ev2_pro.py — the Editor V2 "pro look": one design system shared by the hook, the explainer
inserts and the polished body, so a whole video looks like it came from one studio.

Nothing here is free-form: every recipe calls these helpers with DATA (text, icons, times) and
gets the same tested layout, motion and sound every time. That is the point: a weak model
fills a JSON, the code does the design.

    theme = make_theme('#E11D74')        # or auto_accent(...) from the recording itself
    bg_png = write_bg('work/pro/bg.png', theme)   # the shared backdrop (body + hook + inserts)
    pro_css(c, theme)                    # once per composition
    backdrop(c, 0, dur, theme, 'assets/pro/bg.png', z=1)
    ids = text_block(c, ...); reveal_words(c, ids, t)
    icon_svg('truck', 64, '#fff')  /  icon_svg('brand:whatsapp', 64)  /  guess_icon('Livraison')

Icons: Lucide (ISC) and a curated Simple Icons subset (CC0, brand marks = trademarks: identify
only), vendored in assets/icons/.
"""
import colorsys, json, math, os, re

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
ICON_DIR = os.path.join(SK, 'assets', 'icons')
FONT_DIR = os.path.join(SK, 'assets', 'fonts')
W, H, FPS = 1920, 1080, 30

DEFAULT_ACCENT = '#7C5CFF'


# ------------------------------------------------------------------ colour
def hex2rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb2hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, int(round(v)))):02X}' for v in rgb)


def rgba(h, a):
    r, g, b = hex2rgb(h)
    return f'rgba({r},{g},{b},{a})'


def _hsv(h):
    r, g, b = (v / 255 for v in hex2rgb(h))
    return colorsys.rgb_to_hsv(r, g, b)


def _from_hsv(hh, s, v):
    return rgb2hex(tuple(x * 255 for x in colorsys.hsv_to_rgb(hh % 1.0, s, v)))


def normalize_accent(h):
    """Any brand colour -> a vivid, readable-on-dark accent (same hue)."""
    hh, s, v = _hsv(h)
    if s < 0.15:                      # grey/black/white brand: fall back to the default violet
        return DEFAULT_ACCENT
    return _from_hsv(hh, min(0.85, max(0.62, s)), min(1.0, max(0.88, v)))


def make_theme(accent=None):
    a = normalize_accent(accent or DEFAULT_ACCENT)
    hh, s, v = _hsv(a)
    a2 = _from_hsv(hh + 0.11, min(0.8, s), 1.0)          # a neighbour hue for gradients
    a3 = _from_hsv(hh - 0.09, min(0.75, s), 0.95)
    deep = _from_hsv(hh, 0.55, 0.16)                       # tinted dark for the backdrop
    return {
        'accent': a, 'accent2': a2, 'accent3': a3, 'deep': deep,
        'bg0': '#07070B', 'bg1': _from_hsv(hh, 0.45, 0.10),
        'text': '#F5F6FA', 'muted': 'rgba(235,238,245,0.66)', 'faint': 'rgba(235,238,245,0.38)',
        'card': 'rgba(18,18,28,0.78)', 'card2': 'rgba(255,255,255,0.055)',
        'line': 'rgba(255,255,255,0.10)', 'line2': 'rgba(255,255,255,0.18)',
        'good': '#34D399', 'bad': '#F87171', 'warn': '#FBBF24',
    }


def auto_accent(frames_bgr, mask_boxes=()):
    """The app's own brand colour: the most common saturated hue in a few screen frames.
    Ignored: webcam boxes, a 4% frame margin (wallpaper / window borders), thin lines, and
    pixels that never change across the frames (desktop decoration). Returns a hex or None."""
    import cv2
    if not frames_bgr:
        return None
    smalls = [cv2.resize(f, (480, 270), interpolation=cv2.INTER_AREA) for f in frames_bgr]
    m = np.zeros((270, 480), bool)
    m[11:-11, 19:-19] = True
    sx, sy = 480 / frames_bgr[0].shape[1], 270 / frames_bgr[0].shape[0]
    for (x, y, w, h) in mask_boxes:
        m[max(0, int(y * sy) - 4):int((y + h) * sy) + 4, max(0, int(x * sx) - 4):int((x + w) * sx) + 4] = False
    stack = np.array(smalls, np.int16)
    static = (np.abs(stack - np.median(stack, axis=0)).max(axis=3) < 12).mean(axis=0) > 0.85 if len(smalls) >= 4 else np.zeros_like(m)
    hist = np.zeros(36)
    for small in smalls:
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0].astype(int), hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        sel = m & (sat > 0.45) & (val > 0.35)
        sel = cv2.morphologyEx(sel.astype(np.uint8), cv2.MORPH_OPEN, np.ones((4, 4), np.uint8)).astype(bool)
        if sel.sum() < 20:
            continue
        wgt = (sat * val * np.where(static, 0.15, 1.0))[sel]
        hist += np.bincount((hue[sel] * 2 // 10) % 36, weights=wgt, minlength=36)[:36]
    if hist.sum() < 20:
        return None
    k = int(np.argmax(np.convolve(np.r_[hist[-1], hist, hist[0]], [0.25, 0.5, 0.25], 'valid')))
    return normalize_accent(_from_hsv((k * 10 + 5) / 360.0, 0.75, 0.95))


# ------------------------------------------------------------------ the shared backdrop
def render_bg(theme, w=W, h=H, seed=3):
    """Dark tinted gradient + two soft colour glows + a faint dot grid + grain + vignette.
    BGR uint8. Used as the body's stage (behind the inset screen) and the hook/insert ground."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    b0 = np.array(hex2rgb(theme['bg0']), np.float32)
    b1 = np.array(hex2rgb(theme['bg1']), np.float32)
    t = (yy / h * 0.75 + xx / w * 0.25)[..., None]
    img = b0 * (1 - t) + b1 * t

    def glow(cx, cy, r, col, a):
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        k = np.exp(-d * d * 2.2)[..., None] * a
        return k * np.array(hex2rgb(col), np.float32)

    img = img + glow(w * 0.12, h * 0.02, w * 0.55, theme['accent'], 0.30)
    img = img + glow(w * 0.95, h * 1.02, w * 0.55, theme['accent2'], 0.22)
    img = img + glow(w * 0.55, h * 0.45, w * 0.45, theme['accent3'], 0.05)
    # dot grid, strongest in the middle
    grid = ((xx % 36 < 2) & (yy % 36 < 2)).astype(np.float32)
    fall = np.exp(-(((xx - w / 2) / (w * 0.55)) ** 2 + ((yy - h / 2) / (h * 0.6)) ** 2))
    img = img + (grid * fall * 10.0)[..., None]
    # vignette + grain
    vig = 1 - 0.38 * np.clip(((xx - w / 2) / (w * 0.62)) ** 2 + ((yy - h / 2) / (h * 0.62)) ** 2, 0, 1.6) / 1.6
    img = img * vig[..., None]
    img = img + rng.normal(0, 2.2, (h, w, 1)).astype(np.float32)
    img = np.clip(img, 0, 255).astype(np.uint8)
    return img[..., ::-1].copy()


def write_bg(path, theme, w=W, h=H):
    import cv2
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cv2.imwrite(path, render_bg(theme, w, h))
    return path


def write_grain(path, size=512, seed=9):
    import cv2
    rng = np.random.default_rng(seed)
    n = rng.normal(128, 38, (size, size)).clip(0, 255).astype(np.uint8)
    a = np.full((size, size), 22, np.uint8)
    cv2.imwrite(path, np.dstack([n, n, n, a]))
    return path


# ------------------------------------------------------------------ text measuring / fitting
_FONTS = {}


def _font(size, weight=700, arabic=False):
    from PIL import ImageFont
    k = (size, weight, arabic)
    if k not in _FONTS:
        if arabic:
            f = ImageFont.truetype(os.path.join(FONT_DIR, 'Cairo-Var.ttf'), size)
            try:
                f.set_variation_by_axes([min(1000, max(200, weight)), 0])
            except Exception:
                pass
        else:
            name = {600: 'Inter-600.woff2', 700: 'Inter-700.woff2', 800: 'Inter-900.woff2', 900: 'Inter-900.woff2'}.get(weight, 'Inter-700.woff2')
            f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
        _FONTS[k] = f
    return _FONTS[k]


def has_ar(text):
    return any('\u0600' <= ch <= '\u06FF' or '\u0750' <= ch <= '\u08FF' or '\uFB50' <= ch <= '\uFEFF' for ch in str(text))


def text_width(text, size, weight=700):
    """Pixel width of a (mixed Darija/Latin) string as the browser will roughly set it."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    total = 0.0
    words = str(text).split()
    for i, wd in enumerate(words):
        ar = has_ar(wd)
        try:
            total += d.textlength(wd, font=_font(size, weight, ar), direction='rtl' if ar else 'ltr')
        except Exception:
            total += d.textlength(wd, font=_font(size, weight, ar))
        if i:
            total += size * 0.28
    return total


def wrap_lines(text, size, max_w, weight=700, max_lines=2):
    words, lines, cur = str(text).split(), [], ''
    for wd in words:
        t = (cur + ' ' + wd).strip()
        if cur and text_width(t, size, weight) > max_w:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines if len(lines) <= max_lines else None


def balance(lines, size, weight=700):
    """Two lines -> the split with the most even widths (no lonely last word)."""
    if len(lines) != 2:
        return lines
    words = ' '.join(lines).split()
    best = None
    for k in range(1, len(words)):
        a, b = ' '.join(words[:k]), ' '.join(words[k:])
        m = max(text_width(a, size, weight), text_width(b, size, weight))
        if best is None or m < best[0]:
            best = (m, [a, b])
    return best[1]


def fit_text(text, max_w, sizes=(120, 104, 92, 80, 70, 62, 54, 48, 42, 36, 32, 28), weight=700, max_lines=2):
    """Largest size from `sizes` at which `text` fits in max_lines lines of max_w px (lines balanced)."""
    text = plain(text)
    for s in sizes:
        ls = wrap_lines(text, s, max_w, weight, max_lines)
        if ls is not None:
            return s, balance(ls, s, weight)
    s = sizes[-1]
    return s, wrap_lines(text, s, max_w, weight, 99) or [text]


def short_label(title, max_chars=26):
    """A chapter title -> a short on-screen keyword ("Tableau de bord — نظرة عامة" -> "Tableau de bord")."""
    t = str(title).strip()
    for sep in (' — ', ' – ', ' - ', ' | ', ': '):
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if parts:
                t = min(parts, key=len) if len(parts[0]) > max_chars else parts[0]
            break
    if len(t) > max_chars:
        cut = t[:max_chars].rsplit(' ', 1)[0]
        t = (cut or t[:max_chars]).rstrip(' ,.;:+—-') + '…'
    return t


# ------------------------------------------------------------------ icons
_ICONS = {}


def _icons():
    if not _ICONS:
        _ICONS['lucide'] = json.load(open(os.path.join(ICON_DIR, 'lucide.json')))
        _ICONS['tags'] = json.load(open(os.path.join(ICON_DIR, 'lucide-tags.json'), encoding='utf-8'))
        _ICONS['brands'] = json.load(open(os.path.join(ICON_DIR, 'brands.json')))
    return _ICONS


# words a tutorial says (fr / en / darija) -> lucide icon. Checked before the tag search.
ICON_WORDS = [
    (r'whats ?app|واتساب|واتس', 'brand:whatsapp'), (r'telegram', 'brand:telegram'), (r'github', 'brand:github'),
    (r'youtube', 'brand:youtube'), (r'docker', 'brand:docker'), (r'supabase', 'brand:supabase'),
    (r'vercel', 'brand:vercel'), (r'stripe', 'brand:stripe'), (r'shopify', 'brand:shopify'), (r'notion', 'brand:notion'),
    (r'figma', 'brand:figma'), (r'claude|anthropic', 'brand:claude'), (r'neovim|nvim', 'brand:neovim'),
    (r'omarchy', 'brand:omarchy'), (r'hyprland', 'brand:hyprland'), (r'arch ?linux', 'brand:archlinux'),
    (r'postgres', 'brand:postgresql'), (r'python', 'brand:python'), (r'react', 'brand:react'),
    (r'next\.?js', 'brand:nextdotjs'), (r'node', 'brand:nodedotjs'), (r'tailwind', 'brand:tailwindcss'),
    (r'retour|return|refund|remboursement|رجوع', 'undo-2'), (r'assign|attribu|تعيين', 'user-check'),
    (r'upsell|offre|offer|promo|discount|réduction', 'badge-percent'), (r'star|favori|review|avis', 'star'),
    (r'filtre|filter|فلتر|الفلاتر', 'list-filter'), (r'search|recherche|بحث', 'search'), (r'list|liste|لائحة|اللائحة', 'list'),
    (r'confirm|valid|تأكيد|أكد', 'circle-check'),
    (r'boutique|shop|store|magasin|متجر|المتجر|حانوت', 'store'), (r'panier|cart|سلة|السلة', 'shopping-cart'),
    (r'commande|order|طلب|الطلب|طلبية|الطلبية|كوموند', 'shopping-bag'),
    (r'livr|deliver|ship|expédi|ozon|توصيل|التوصيل|شحن|livreur', 'truck'), (r'colis|package|parcel|box|carton|كولي', 'package'),
    (r'stock|inventaire|inventory|مخزون|ستوك', 'boxes'), (r'bordereau|\bbl\b|pdf|facture|invoice|فاتورة', 'file-text'),
    (r'print|imprim', 'printer'), (r'client|customer|user|utilisateur|عميل|الزبون|زبون|كليان', 'user'),
    (r'team|équipe|users|فريق', 'users'), (r'phone|appel|téléphone|تيليفون|هاتف|call', 'phone'),
    (r'message|chat|sms|رسالة|ميساج', 'message-circle'), (r'mail|email|courriel', 'mail'),
    (r'paie|pay|prix|price|money|cash|cod|mad|dh|درهم|فلوس|الثمن', 'banknote'), (r'card|carte', 'credit-card'),
    (r'dashboard|tableau|statist|stats|analytics|لوحة', 'layout-dashboard'), (r'chart|graph|rapport|report', 'chart-column'),
    (r'setting|param|config|réglage|إعداد', 'settings'), (r'code|script|dev', 'code'), (r'terminal|shell|cli|bash', 'square-terminal'),
    (r'database|base de données|db\b|sql', 'database'), (r'cloud|deploy|serveur|server|hosting', 'cloud'),
    (r'secur|lock|password|mot de passe|login|auth', 'lock'), (r'key|clé|api', 'key-round'), (r'notif|alert|rappel|reminder', 'bell'),
    (r'time|temps|clock|minute|heure|وقت|دقايق|دقيقة', 'clock'), (r'date|calendar|calendrier', 'calendar'),
    (r'home|accueil', 'house'), (r'link|lien', 'link'), (r'web|site|internet|browser|navigateur', 'globe'),
    (r'fast|rapide|speed|vite|automat|auto', 'zap'), (r'launch|start|démarr|rocket|lanc', 'rocket'),
    (r'edit|modif|écrire|write', 'pencil'), (r'upload|import', 'upload'), (r'download|télécharg|export', 'download'),
    (r'video|vidéo|record|enregistr', 'video'), (r'image|photo|picture', 'image'), (r'music|musique|\bson\b|audio', 'audio-lines'),
    (r'ai\b|ia\b|model|gpt|llm|agent|ذكاء', 'sparkles'), (r'check|done|ok|terminé|fini|سالي|صافي', 'check'),
    (r'error|erreur|échec|fail|خطأ', 'circle-exclamation-point'), (r'warning|attention', 'triangle-exclamation-point'), (r'location|adresse|address|map|ville|عنوان', 'map-pin'),
    (r'mobile|smartphone', 'smartphone'), (r'computer|ordinateur|pc|laptop|desktop', 'monitor'), (r'file|fichier|document', 'file'),
    (r'folder|dossier', 'folder'), (r'tag|étiquette|label', 'tag'), (r'idea|idée|فكرة', 'lightbulb'), (r'goal|objectif|target|هدف', 'target'),
]


def guess_icon(label, default='circle-dot'):
    s = str(label).lower()
    for pat, name in ICON_WORDS:
        if re.search(pat, s):
            return name
    ic = _icons()
    words = [w for w in re.findall(r'[a-z]{4,}', s)]
    for w in words:
        if w in ic['lucide']:
            return w
    for w in words:
        for name, tags in ic['tags'].items():
            if w in tags and name in ic['lucide']:
                return name
    return default


def icon_exists(name):
    ic = _icons()
    if name.startswith('brand:'):
        return name[6:] in ic['brands']
    return name in ic['lucide']


def icon_svg(name, size=48, color='currentColor', stroke=1.9, draw_cls=''):
    """Inline SVG for a Lucide icon name or 'brand:<simple-icons slug>'. Unknown names fall back
    to guess_icon(name). draw_cls: a class put on every stroke element (paths get pathLength=1,
    so `stroke-dashoffset 1 -> 0` draws the icon on)."""
    ic = _icons()
    if not name:
        name = 'circle-dot'
    if name.startswith('brand:') and name[6:] in ic['brands']:
        b = ic['brands'][name[6:]]
        return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="{color}" '
                f'style="display:block"><path d="{b["d"]}"/></svg>')
    if name not in ic['lucide']:
        name = guess_icon(name)
        if name.startswith('brand:'):
            return icon_svg(name, size, color, stroke, draw_cls)
    parts = []
    for tag, attrs in ic['lucide'].get(name, ic['lucide']['circle-dot']):
        a = ' '.join(f'{k}="{v}"' for k, v in attrs.items() if k != 'key')
        extra = f' pathLength="1" class="{draw_cls}"' if draw_cls else ''
        parts.append(f'<{tag} {a}{extra}/>')
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" style="display:block;overflow:visible">'
            + ''.join(parts) + '</svg>')


# ------------------------------------------------------------------ composition helpers
def esc(s):
    import html
    return html.escape(str(s), quote=True)


def bidi(text):
    """Escape, isolating Latin runs inside Arabic text so mixed Darija/French reads right."""
    if not has_ar(text):
        return esc(text)
    out = []
    for tok in str(text).split(' '):
        out.append(esc(tok) if has_ar(tok) else f'<bdi>{esc(tok)}</bdi>')
    return ' '.join(out)


def pro_css(c, th):
    """The pro classes, once per composition."""
    if getattr(c, '_pro_css', False):
        return
    c._pro_css = True
    a, a2 = th['accent'], th['accent2']
    c.css.append(f'''
:root {{ --pro-accent:{a}; --pro-accent2:{a2}; --pro-text:{th['text']}; --pro-muted:{th['muted']};
        --pro-card:{th['card']}; --pro-line:{th['line']}; --pro-line2:{th['line2']}; --pro-good:{th['good']}; --pro-bad:{th['bad']}; }}
.pro-abs {{ position:absolute; }}
.pro-txt {{ font-family:"EV1 Sans","EV2 Arabic",system-ui,sans-serif; color:var(--pro-text); letter-spacing:-0.015em; }}
.pro-txt[dir="rtl"] {{ font-family:"EV2 Arabic","EV1 Sans",sans-serif; letter-spacing:0; }}
.pro-w {{ display:inline-block; white-space:pre; will-change:transform,opacity,filter; }}
.pro-hl {{ background:linear-gradient(92deg,{a} 0%,{a2} 100%); -webkit-background-clip:text; background-clip:text; color:transparent; }}
.pro-card {{ background:linear-gradient(180deg,rgba(255,255,255,0.075),rgba(255,255,255,0.03)); border:1px solid var(--pro-line2);
            border-radius:26px; box-shadow:0 30px 80px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.08);
            backdrop-filter:blur(8px); }}
.pro-chip {{ display:inline-flex; align-items:center; gap:14px; padding:12px 24px 12px 14px; border-radius:999px;
            background:rgba(14,14,22,0.82); border:1px solid var(--pro-line2); box-shadow:0 14px 40px rgba(0,0,0,0.5);
            font:700 30px/1 "EV1 Sans","EV2 Arabic",sans-serif; color:var(--pro-text); white-space:nowrap; }}
.pro-chip[dir="rtl"] {{ padding:12px 14px 12px 24px; font-family:"EV2 Arabic","EV1 Sans",sans-serif; }}
.pro-ico {{ display:flex; align-items:center; justify-content:center; border-radius:50%;
           background:linear-gradient(140deg,{a} 0%,{a2} 100%); box-shadow:0 8px 26px {rgba(a, 0.45)}; color:#fff; }}
.pro-kicker {{ font:800 22px/1 "EV1 Sans",sans-serif; letter-spacing:0.22em; text-transform:uppercase; color:{a2}; }}
.pro-kicker[dir="rtl"] {{ font:700 28px/1 "EV2 Arabic",sans-serif; letter-spacing:0; }}
.pro-draw {{ stroke-dasharray:1 1; stroke-dashoffset:1; }}
.pro-shot {{ position:absolute; overflow:hidden; border-radius:22px; background:#0b0b12;
            border:1px solid rgba(255,255,255,0.16); box-shadow:0 40px 110px rgba(0,0,0,0.65), 0 0 0 1px rgba(0,0,0,0.4); }}
.pro-shot::after {{ content:""; position:absolute; inset:0; border-radius:22px; pointer-events:none;
                   box-shadow:inset 0 1px 0 rgba(255,255,255,0.10); }}
''')


def backdrop(c, t0, t1, th, bg_src, z=1, glow=True, grain_src=None, drift=0.035):
    """The shared stage: the backdrop PNG, slow drifting colour glows (so nothing is ever frozen)
    and optional grain. Returns the clip id."""
    gid = c.uid('pbg')
    g1, g2 = c.uid('pgl'), c.uid('pgl')
    glows = ''
    if glow:
        glows = (f'<div id="{g1}" class="pro-abs" style="left:-300px;top:-420px;width:1300px;height:1100px;border-radius:50%;'
                 f'background:radial-gradient(closest-side,{rgba(th["accent"], 0.30)},transparent);filter:blur(30px)"></div>'
                 f'<div id="{g2}" class="pro-abs" style="left:1000px;top:520px;width:1300px;height:1000px;border-radius:50%;'
                 f'background:radial-gradient(closest-side,{rgba(th["accent2"], 0.22)},transparent);filter:blur(30px)"></div>')
    grain = (f'<div class="pro-abs" style="inset:0;background:url({esc(grain_src)});background-size:512px;'
             f'opacity:0.55;mix-blend-mode:overlay"></div>') if grain_src else ''
    inner = (f'<div id="{gid}" class="pro-abs" style="left:-40px;top:-24px;width:2000px;height:1128px">'
             f'<img src="{esc(bg_src)}" style="position:absolute;left:0;top:0;width:2000px;height:1128px;object-fit:cover"></div>'
             f'{glows}{grain}')
    cid = c.clip(t0, t1, inner, z)
    d = max(0.1, t1 - t0)
    c.at(f'tl.fromTo("#{gid}",{{x:0,y:0,scale:1}},{{x:{-24 * drift / 0.035:.1f},y:{-10 * drift / 0.035:.1f},scale:{1 + drift:.3f},'
         f'duration:{d:.3f},ease:"none",immediateRender:false}},{t0:.4f});')
    if glow:
        c.at(f'tl.fromTo("#{g1}",{{x:0,y:0}},{{x:220,y:120,duration:{d:.3f},ease:"sine.inOut",immediateRender:false}},{t0:.4f});')
        c.at(f'tl.fromTo("#{g2}",{{x:0,y:0}},{{x:-260,y:-90,duration:{d:.3f},ease:"sine.inOut",immediateRender:false}},{t0:.4f});')
    return cid


def _tokens(text):
    out = []
    for tok in re.findall(r'\*[^*]+\*|\S+', str(text)):
        hl = tok.startswith('*') and tok.endswith('*') and len(tok) > 2
        for sub in (tok[1:-1] if hl else tok).split():
            out.append((sub, hl))
    return out


def plain(text):
    return ' '.join(w for w, _ in _tokens(text))


def text_block(c, text, x, y, w, size, weight=800, color=None, align='center', line_h=1.12, highlight=True, cls=''):
    """Words as spans in a positioned block (top-left x,y; width w), broken into balanced lines.
    '*word*' marks highlight words (accent gradient). Returns (html, [word ids]).
    Darija lines go right-to-left."""
    toks = _tokens(text)
    rtl = has_ar(plain(text))
    lines = wrap_lines(plain(text), size, w * 0.97, weight, 99) or [plain(text)]
    lines = balance(lines, size, weight)
    ids, rows, k = [], [], 0
    for ln in lines:
        n = len(ln.split())
        parts = []
        for sub, hl in toks[k:k + n]:
            wid = c.uid('pw')
            ids.append(wid)
            inner = esc(sub) if (has_ar(sub) or not rtl) else f'<bdi>{esc(sub)}</bdi>'
            parts.append(f'<span id="{wid}" class="pro-w{" pro-hl" if hl and highlight else ""}">{inner}</span>')
        k += n
        rows.append('<div>' + ' '.join(parts) + '</div>')
    col = f'color:{color};' if color else ''
    ta = {'center': 'center', 'left': 'right' if rtl else 'left', 'right': 'left' if rtl else 'right'}[align]
    d = ' dir="rtl"' if rtl else ''
    html = (f'<div class="pro-abs pro-txt {cls}"{d} style="left:{x}px;top:{y}px;width:{w}px;text-align:{ta};'
            f'font-size:{size}px;font-weight:{weight};line-height:{line_h};{col}">' + ''.join(rows) + '</div>')
    return html, ids


def block_height(text, size, w, weight=800, line_h=1.12):
    lines = wrap_lines(plain(text), size, w * 0.97, weight, 99) or [text]
    return len(lines) * size * line_h


def reveal_words(c, ids, t, stagger=0.06, dur=0.42, dy=36, blur=14, sound=None):
    for k, wid in enumerate(ids):
        tk = t + k * stagger
        c.pre.append(f'gsap.set("#{wid}",{{opacity:0,y:{dy},filter:"blur({blur}px)"}});')
        c.at(f'tl.fromTo("#{wid}",{{opacity:0,y:{dy},filter:"blur({blur}px)"}},{{opacity:1,y:0,filter:"blur(0px)",'
             f'duration:{dur:.3f},ease:"power3.out",immediateRender:false}},{tk:.4f});')
    if sound:
        from ev1_devices import sfx
        sfx(c, t, sound)
    return t + max(0, len(ids) - 1) * stagger + dur


def hide_words(c, ids, t, dur=0.28, dy=-22):
    for wid in ids:
        c.at(f'tl.fromTo("#{wid}",{{opacity:1,y:0,filter:"blur(0px)"}},{{opacity:0,y:{dy},filter:"blur(10px)",'
             f'duration:{dur:.3f},ease:"power2.in",immediateRender:false}},{t:.4f});')


def pop_in(c, el_id, t, dur=0.45, from_scale=0.86, dy=24, ease='back.out(1.6)'):
    c.pre.append(f'gsap.set("#{el_id}",{{opacity:0,scale:{from_scale},y:{dy}}});')
    c.at(f'tl.fromTo("#{el_id}",{{opacity:0,scale:{from_scale},y:{dy}}},{{opacity:1,scale:1,y:0,duration:{dur:.3f},'
         f'ease:"{ease}",immediateRender:false}},{t:.4f});')


def fade_out(c, el_id, t, dur=0.3, scale=0.96, dy=0, blur=8):
    c.at(f'tl.to("#{el_id}",{{opacity:0,scale:{scale},y:{dy},filter:"blur({blur}px)",duration:{dur:.3f},ease:"power2.in"}},{t:.4f});')


def chip_html(cid, label, icon=None, th=None, num=None, size=30, ico_size=44):
    rtl = has_ar(label)
    ic = ''
    if icon:
        ic = (f'<span class="pro-ico" style="width:{ico_size}px;height:{ico_size}px;flex:none">'
              f'{icon_svg(icon, int(ico_size * 0.56), "#fff")}</span>')
    n = f'<span style="font:800 {int(size * 0.7)}px/1 \'EV1 Sans\';color:var(--pro-accent2);letter-spacing:0.08em">{esc(num)}</span>' if num else ''
    d = ' dir="rtl"' if rtl else ''
    return (f'<div id="{cid}" class="pro-chip"{d} style="font-size:{size}px">{ic}{n}<span>{bidi(label)}</span></div>')


# ------------------------------------------------------------------ the video's look (work/look.json)
LOOK_DEFAULTS = {
    'accent': 'auto',        # "auto" = the app's own brand colour from the recording, or "#RRGGBB"
    'frame': 'inset',        # body: "inset" (screen on the backdrop, rounded, shadow) or "full"
    'inset': 0.9,            # inset screen scale (0.84-0.96)
    'max_zoom': 1.6,         # body auto-zoom cap (1.2-2.0)
    'click_fx': True,        # ripples on clicks (needs an input log from `ev2 rec`)
    'click_sfx': True,       # a soft click sound on each click
    'chapter_sfx': True,     # whoosh on each chapter card
    'trim': 'auto',          # cut the window border / wallpaper slivers at the edges: "auto", "off" or [x, y, w, h]
    'auto_keys': True,       # shortcut pills from the input log
}


def cam_box_1080(vd):
    p = os.path.join(vd, 'work', 'omarchy.json')
    if not os.path.isfile(p):
        return None
    om = json.load(open(p))
    if not om.get('has_webcam_overlay') or not om.get('webcam_box'):
        return None
    sw, sh = om.get('width') or W, om.get('height') or H
    s = min(W / sw, H / sh)
    ox, oy = (W - round(sw * s)) / 2, (H - round(sh * s)) / 2
    x, y, bw, bh = om['webcam_box']
    return (x * s + ox, y * s + oy, bw * s, bh * s)


def _sample_frames(vd, n=10):
    import cv2
    p = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    vc = cv2.VideoCapture(p)
    total = vc.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    out = []
    for k in range(n):
        vc.set(cv2.CAP_PROP_POS_FRAMES, int(total * (0.08 + 0.84 * k / max(1, n - 1))))
        ok, f = vc.read()
        if ok:
            out.append(f)
    vc.release()
    return out


def ensure_look(vd, force=False):
    """work/look.json (defaults filled in, accent resolved) + assets/pro/{bg.png,grain.png}.
    Returns (look, theme). Safe to call from every stage; cheap when up to date."""
    lp = os.path.join(vd, 'work', 'look.json')
    look = dict(LOOK_DEFAULTS)
    if os.path.isfile(lp):
        try:
            look.update(json.load(open(lp, encoding='utf-8')))
        except ValueError as e:
            raise SystemExit(f'work/look.json is not valid JSON: {e}')
    acc = str(look.get('accent') or 'auto')
    if acc == 'auto':
        resolved = look.get('resolved_accent')
        if force or not resolved:
            try:
                cb = cam_box_1080(vd)
                resolved = auto_accent(_sample_frames(vd), [cb] if cb else []) or DEFAULT_ACCENT
            except Exception:
                resolved = DEFAULT_ACCENT
    elif re.match(r'^#?[0-9a-fA-F]{6}$', acc):
        resolved = normalize_accent('#' + acc.lstrip('#'))
    else:
        raise SystemExit(f'work/look.json: accent must be "auto" or "#RRGGBB" (got {acc!r})')
    look['resolved_accent'] = resolved
    if look.get('trim', 'auto') == 'auto' and ('resolved_trim' not in look or force):
        try:
            tr = detect_trim(vd)
        except Exception:
            tr = None
        look['resolved_trim'] = list(tr) if tr else None
    look['inset'] = float(min(0.96, max(0.84, float(look.get('inset', 0.9)))))
    look['max_zoom'] = float(min(2.0, max(1.2, float(look.get('max_zoom', 1.6)))))
    if look.get('frame') not in ('inset', 'full'):
        raise SystemExit('work/look.json: frame must be "inset" or "full"')
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    old = open(lp, encoding='utf-8').read() if os.path.isfile(lp) else ''
    new = json.dumps(look, indent=2, ensure_ascii=False) + '\n'
    if new != old:
        open(lp, 'w', encoding='utf-8').write(new)
    th = make_theme(resolved)
    pro = os.path.join(vd, 'assets', 'pro')
    os.makedirs(pro, exist_ok=True)
    stamp = os.path.join(pro, 'bg.json')
    key = {'accent': resolved, 'v': 2}
    if force or not os.path.isfile(os.path.join(pro, 'bg.png')) or not os.path.isfile(stamp) or json.load(open(stamp)) != key:
        write_bg(os.path.join(pro, 'bg.png'), th)
        write_grain(os.path.join(pro, 'grain.png'))
        json.dump(key, open(stamp, 'w'))
    return look, th


def paint_out(frame, box, pad=8):
    """Paint the burned-in webcam box out of a BGR frame (inpainting at half size: smooth, fast)."""
    import cv2
    if not box:
        return frame
    x, y, w, h = [int(round(v)) for v in box]
    hh, ww = frame.shape[:2]
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(ww, x + w + pad), min(hh, y + h + pad)
    if x1 <= x0 or y1 <= y0:
        return frame
    m = np.zeros(frame.shape[:2], np.uint8)
    m[y0:y1, x0:x1] = 255
    small = cv2.resize(frame, (ww // 2, hh // 2), interpolation=cv2.INTER_AREA)
    ms = cv2.resize(m, (ww // 2, hh // 2), interpolation=cv2.INTER_NEAREST)
    fill = cv2.inpaint(small, ms, 9, cv2.INPAINT_TELEA)
    fill = cv2.GaussianBlur(cv2.resize(fill, (ww, hh), interpolation=cv2.INTER_LINEAR), (0, 0), 3)
    out = frame.copy()
    out[y0:y1, x0:x1] = fill[y0:y1, x0:x1]
    return out


def tracked_cam_box(vd, src_t=None):
    """The webcam box (1920x1080 coords) as tracked by the body analysis (work/activity.npz),
    at src_t or the median over the recording; falls back to omarchy.json."""
    p = os.path.join(vd, 'work', 'activity.npz')
    if os.path.isfile(p):
        cam = np.load(p, allow_pickle=False)['cam']
        ok = cam[:, 0] >= 0
        if ok.any():
            if src_t is not None:
                k = int(min(len(cam) - 1, max(0, round(src_t * 5))))
                if cam[k][0] >= 0:
                    return tuple(float(v) for v in cam[k])
            return tuple(float(v) for v in np.median(cam[ok], axis=0))
    return cam_box_1080(vd)


def clean_still(vd, src_t, rel_dir=os.path.join('assets', 'pro', 'stills')):
    """assets/pro/stills/<t>.jpg: the recording's frame at src_t, webcam painted out. Returns the
    path relative to the video dir."""
    import cv2
    rel = os.path.join(rel_dir, f'{float(src_t):09.3f}.jpg')
    full = os.path.join(vd, rel)
    if not os.path.isfile(full):
        os.makedirs(os.path.dirname(full), exist_ok=True)
        vc = cv2.VideoCapture(os.path.join(vd, 'assets', 'media', 'cam_raw.mp4'))
        vc.set(cv2.CAP_PROP_POS_MSEC, float(src_t) * 1000.0)
        ok, f = vc.read()
        vc.release()
        if not ok:
            raise SystemExit(f'could not read a frame at {src_t:.2f}s from cam_raw.mp4')
        f = paint_out(f, tracked_cam_box(vd, src_t))
        cv2.imwrite(full, f, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return rel


def content_rect(vd):
    """The part of cam_raw.mp4 (1920x1080) that is the recording, without the letterbox bars
    `ev2 init` adds when the capture is not 16:9. (x, y, w, h)."""
    p = os.path.join(vd, 'work', 'omarchy.json')
    sw = sh = None
    if os.path.isfile(p):
        om = json.load(open(p))
        sw, sh = om.get('width'), om.get('height')
    if not sw or not sh:
        return (0, 0, W, H)
    s = min(W / sw, H / sh)
    w, h = round(sw * s), round(sh * s)
    return ((W - w) // 2, (H - h) // 2, w, h)


def stage_geometry(look, content):
    """Where the body puts the screen on the stage: (x, y, w, h, radius). 'full' = edge to edge."""
    cx, cy, cw, ch = content
    if look.get('frame', 'inset') != 'inset':
        return 0, 0, W, H, 0
    s = float(look.get('inset', 0.9))
    w = W * s
    h = w * ch / cw
    if h > H * s:
        h = H * s
        w = h * cw / ch
    w, h = int(round(w / 2) * 2), int(round(h / 2) * 2)
    return (W - w) // 2, (H - h) // 2, w, h, int(round(22 * s / 0.9))


def pip_rect(cam_box, look=None):
    """Where the speaker's PiP goes on the stage (same in the hook and the body):
    the corner nearest the webcam's corner, ~300 px tall. (x, y, w, h)."""
    if not cam_box:
        return None
    bx, by, bw, bh = cam_box
    inset = 3
    bw, bh = bw - 2 * inset, bh - 2 * inset
    h = min(420.0, max(270.0, bh * 1.35))
    w = h * bw / bh
    right, bottom = bx + bw / 2 > W / 2, by + bh / 2 > H / 2
    m = 40
    x = W - m - w if right else m
    y = H - m - h if bottom else m
    return (int(round(x)), int(round(y)), int(round(w / 2) * 2), int(round(h / 2) * 2))


def detect_trim(vd, n=16):
    """The app window inside the recording: Hyprland window borders and wallpaper slivers at the
    edges stay put while the app changes, so look for a persistent straight edge near each side
    of the content (<= 7% in). Returns the trimmed content rect (x, y, w, h), or None."""
    import cv2
    ox, oy, cw, ch = content_rect(vd)
    frames = _sample_frames(vd, n)
    if len(frames) < 6:
        return None
    box = cam_box_1080(vd)
    ex = ey = None
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        sx = (np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) > 30).astype(np.float32)
        sy = (np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) > 30).astype(np.float32)
        ex, ey = (sx, sy) if ex is None else (ex + sx, ey + sy)
    ex, ey = ex / len(frames), ey / len(frames)
    if box:
        bx, by, bw, bh = [int(v) for v in box]
        ex[max(0, by - 20):by + bh + 20, max(0, bx - 20):bx + bw + 20] = 0
        ey[max(0, by - 20):by + bh + 20, max(0, bx - 20):bx + bw + 20] = 0
    mx, my = int(cw * 0.07), int(ch * 0.07)
    rows = slice(oy + int(ch * 0.2), oy + int(ch * 0.8))
    cols = slice(ox + int(cw * 0.2), ox + int(cw * 0.8))

    def side(prof, lo, hi, inward):
        """Innermost persistent line in [lo, hi) scanning from the edge; returns the first pixel
        inside it, or None."""
        idx = range(lo, hi) if inward > 0 else range(hi - 1, lo - 1, -1)
        found = None
        for k in idx:
            if prof[k] > 0.8:
                found = k
            elif found is not None and abs(k - found) > 3:
                break
        return None if found is None else found + inward

    px = ex[rows].mean(axis=0)
    py = ey[:, cols].mean(axis=1)
    L = side(px, ox, ox + mx, 1)
    R = side(px, ox + cw - mx, ox + cw, -1)
    T = side(py, oy, oy + my, 1)
    B = side(py, oy + ch - my, oy + ch, -1)
    x0 = L + 1 if L is not None else ox
    x1 = R if R is not None else ox + cw
    y0 = T + 1 if T is not None else oy
    y1 = B if B is not None else oy + ch
    if (x0, y0, x1, y1) == (ox, oy, ox + cw, oy + ch) or x1 - x0 < cw * 0.8 or y1 - y0 < ch * 0.8:
        return None
    m = 2                                   # a hair more, so no border pixel survives
    x0, y0 = x0 + (m if L is not None else 0), y0 + (m if T is not None else 0)
    x1, y1 = x1 - (m if R is not None else 0), y1 - (m if B is not None else 0)
    return (int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def view_rect(vd, look=None):
    """What the viewer should see of the recording: the content rect, minus the window border
    and wallpaper slivers when look.trim is "auto" (detected once) or an explicit [x, y, w, h]."""
    if look is None:
        lp = os.path.join(vd, 'work', 'look.json')
        look = json.load(open(lp)) if os.path.isfile(lp) else {}
    t = look.get('resolved_trim')
    if look.get('trim', 'auto') is False or look.get('trim') == 'off':
        return content_rect(vd)
    if isinstance(look.get('trim'), list) and len(look['trim']) == 4:
        return tuple(int(v) for v in look['trim'])
    return tuple(int(v) for v in t) if t else content_rect(vd)
