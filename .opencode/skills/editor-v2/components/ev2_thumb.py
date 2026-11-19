"""ev2_thumb.py — 1280x720 local studio thumbnail HTML generator for Editor V2.

Data-driven (`work/thumbs.json`): 3 tested high-CTR layouts built on ev2_pro theme tokens,
Cairo + Inter heavy typography, automatic Darija/Latin BiDi, and phone-size legibility.

Layouts:
  - split-hero: Angled app screenshot + speaker portrait + bold 2-4 word headline
  - big-stat:   Giant accent stat/number + short promise + speaker badge + dark app backdrop
  - compare-vs: Red "Before" vs Accent "After" split with VS badge + speaker portrait
"""
import html as _html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ev2_pro as P  # noqa: E402

W, H = 1280, 720
TEMPLATES = ('split-hero', 'big-stat', 'compare-vs')


def esc(s):
    return _html.escape(str(s), quote=True)


def _rich(text, accent):
    parts = re.split(r'(\*[^*]+\*)', str(text))
    is_rtl = P.has_ar(text)
    out = []
    for part in parts:
        if not part:
            continue
        hi = part.startswith('*') and part.endswith('*') and len(part) > 2
        raw = part[1:-1] if hi else part
        if is_rtl and not P.has_ar(raw) and re.search(r'[A-Za-z0-9]', raw):
            inner = f'<bdi>{esc(raw)}</bdi>'
        else:
            inner = esc(raw)
        if hi:
            out.append(f'<span class="hl" style="color:{accent}">{inner}</span>')
        else:
            out.append(inner)
    return ''.join(out)


def validate_thumbs_cfg(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get('concepts'), list) or not cfg['concepts']:
        return ['work/thumbs.json must be {"concepts": [...]} with at least 1 concept']
    probs = []
    seen = set()
    for i, c in enumerate(cfg['concepts'], 1):
        if not isinstance(c, dict):
            probs.append(f'concept #{i}: must be a JSON object')
            continue
        name = str(c.get('name') or '').strip()
        if not name or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,40}', name):
            probs.append(f'concept #{i}: name must be lowercase kebab/snake-case')
        elif name in seen:
            probs.append(f'concept "{name}": duplicate name')
        else:
            seen.add(name)
        tpl = c.get('template', 'split-hero')
        if tpl not in TEMPLATES:
            probs.append(f'concept "{name}": template must be one of {", ".join(TEMPLATES)}')
        hl = str(c.get('headline') or '').strip()
        if not hl:
            probs.append(f'concept "{name}": "headline" is required (2-5 punchy words)')
        elif len(P.plain(hl)) > 42:
            probs.append(f'concept "{name}": headline is {len(P.plain(hl))} chars; keep <= 42 for phone readability')
    return probs


def build_thumb_html(out_html, concept, theme, face_uri=None, screen_uri=None, fonts_dir_uri=''):
    """Write a standalone 1280x720 thumbnail HTML file ready for headless Chrome screenshot."""
    tpl = concept.get('template', 'split-hero')
    headline = str(concept.get('headline') or '').strip()
    sub = str(concept.get('sub') or '').strip()
    badge = str(concept.get('badge') or '').strip()
    stat = str(concept.get('stat') or '100%').strip()
    left_txt = str(concept.get('left_text') or 'قبل').strip()
    right_txt = str(concept.get('right_text') or 'دابا').strip()
    acc = concept.get('accent') or theme['accent']
    acc2 = theme['accent2']
    is_rtl = P.has_ar(headline)
    dir_attr = ' dir="rtl"' if is_rtl else ''

    # Dynamic font sizing so text fills space cleanly and stays legible at 246x138 phone size
    n_ch = len(P.plain(headline))
    hl_px = 92 if n_ch <= 16 else (76 if n_ch <= 26 else 62)

    font_css = f"""
@font-face{{font-family:'Cairo';src:url('{fonts_dir_uri}/Cairo-Var.ttf') format('truetype');font-weight:200 900;font-display:block;}}
@font-face{{font-family:'Inter';src:url('{fonts_dir_uri}/Inter-700.woff2') format('woff2');font-weight:700;font-display:block;}}
@font-face{{font-family:'Inter';src:url('{fonts_dir_uri}/Inter-900.woff2') format('woff2');font-weight:900;font-display:block;}}
"""

    bg_screen = f'<img class="bg-blur" src="{esc(screen_uri)}" alt="">' if screen_uri else ''
    badge_html = f'<div class="badge"><span class="bdot"></span>{esc(badge)}</div>' if badge else ''
    sub_html = f'<div class="sub"{dir_attr}>{_rich(sub, acc2)}</div>' if sub else ''
    face_card = (f'<div class="face-wrap"><img src="{esc(face_uri)}" alt=""></div>'
                 if face_uri else '')
    screen_card = (f'<div class="screen-card"><img src="{esc(screen_uri)}" alt=""></div>'
                   if screen_uri else '')

    if tpl == 'split-hero':
        body = f"""
<div class="layout split-hero">
  <div class="left-col">
    {badge_html}
    <h1 class="headline"{dir_attr} style="font-size:{hl_px}px">{_rich(headline, acc)}</h1>
    {sub_html}
  </div>
  <div class="right-col">
    {screen_card}
    {face_card}
  </div>
</div>"""
    elif tpl == 'big-stat':
        body = f"""
<div class="layout big-stat">
  <div class="stat-col">
    {badge_html}
    <div class="giant-stat" style="color:{acc}">{esc(stat)}</div>
    <h1 class="headline"{dir_attr} style="font-size:{min(78, hl_px)}px">{_rich(headline, acc2)}</h1>
    {sub_html}
  </div>
  <div class="portrait-col">
    {face_card}
  </div>
</div>"""
    else:  # compare-vs
        body = f"""
<div class="layout compare-vs">
  <div class="top-head">
    {badge_html}
    <h1 class="headline"{dir_attr} style="font-size:{min(74, hl_px)}px">{_rich(headline, acc)}</h1>
  </div>
  <div class="vs-row">
    <div class="vs-side bad">
      <div class="vs-tag">✕</div>
      <div class="vs-label"{' dir="rtl"' if P.has_ar(left_txt) else ''}>{esc(left_txt)}</div>
    </div>
    <div class="vs-pill">VS</div>
    <div class="vs-side good">
      <div class="vs-tag">✓</div>
      <div class="vs-label"{' dir="rtl"' if P.has_ar(right_txt) else ''}>{esc(right_txt)}</div>
    </div>
  </div>
  {face_card}
</div>"""

    css = f"""{font_css}
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:{theme['bg0']};font-family:'Cairo','Inter',sans-serif;color:#F8FAFC;}}
#stage{{position:relative;width:{W}px;height:{H}px;overflow:hidden;
  background:radial-gradient(circle at 18% 15%,{P.rgba(acc,.34)},transparent 55%),
             radial-gradient(circle at 86% 88%,{P.rgba(acc2,.28)},transparent 55%),
             linear-gradient(135deg,#07080F 0%,#0E1020 100%);}}
.bg-blur{{position:absolute;inset:-24px;width:calc(100% + 48px);height:calc(100% + 48px);object-fit:cover;filter:blur(26px) brightness(.24) saturate(1.2);z-index:1;}}
.vignette{{position:absolute;inset:0;z-index:2;background:radial-gradient(circle at 50% 50%,transparent 35%,rgba(5,6,11,.82) 100%);}}
.layout{{position:relative;z-index:10;width:100%;height:100%;padding:52px 58px;}}
.badge{{display:inline-flex;align-items:center;gap:12px;padding:10px 22px;border-radius:999px;
  background:rgba(15,17,28,.82);border:2px solid {P.rgba(acc,.65)};font-size:26px;font-weight:800;letter-spacing:.03em;color:#fff;
  box-shadow:0 10px 28px rgba(0,0,0,.45);margin-bottom:22px;}}
.bdot{{width:12px;height:12px;border-radius:50%;background:{acc};box-shadow:0 0 14px {acc};}}
.headline{{font-weight:900;line-height:1.12;letter-spacing:-.02em;color:#FFFFFF;
  text-shadow:0 8px 28px rgba(0,0,0,.85),0 2px 4px rgba(0,0,0,.95);}}
.hl{{filter:drop-shadow(0 0 18px {P.rgba(acc,.45)});}}
.sub{{margin-top:18px;font-size:34px;font-weight:700;color:rgba(241,245,249,.86);line-height:1.3;
  text-shadow:0 4px 16px rgba(0,0,0,.8);}}

/* split-hero */
.split-hero{{display:grid;grid-template-columns:1.12fr 1fr;gap:36px;align-items:center;}}
.split-hero .left-col{{display:flex;flex-direction:column;align-items:{'flex-end' if is_rtl else 'flex-start'};text-align:{'right' if is_rtl else 'left'};}}
.split-hero .right-col{{position:relative;height:100%;display:flex;align-items:center;justify-content:center;}}
.split-hero .screen-card{{position:absolute;top:24px;right:0;width:520px;height:320px;border-radius:22px;overflow:hidden;
  border:3px solid {P.rgba(acc,.65)};box-shadow:0 24px 64px rgba(0,0,0,.72),0 0 48px {P.rgba(acc,.28)};transform:rotate(-2.5deg);}}
.split-hero .screen-card img{{width:100%;height:100%;object-fit:cover;}}
.split-hero .face-wrap{{position:absolute;bottom:10px;left:16px;width:300px;height:330px;border-radius:28px;overflow:hidden;
  border:4px solid {acc};box-shadow:0 22px 58px rgba(0,0,0,.82),0 0 42px {P.rgba(acc,.42)};background:#0B0D18;}}
.split-hero .face-wrap img{{width:100%;height:100%;object-fit:cover;object-position:50% 25%;}}

/* big-stat */
.big-stat{{display:grid;grid-template-columns:1.3fr .85fr;gap:32px;align-items:center;}}
.big-stat .stat-col{{display:flex;flex-direction:column;align-items:{'flex-end' if is_rtl else 'flex-start'};text-align:{'right' if is_rtl else 'left'};}}
.giant-stat{{font-size:172px;font-weight:900;line-height:.96;letter-spacing:-.04em;margin-bottom:14px;
  text-shadow:0 12px 36px rgba(0,0,0,.85),0 0 44px {P.rgba(acc,.42)};}}
.big-stat .portrait-col{{display:flex;justify-content:center;align-items:center;}}
.big-stat .face-wrap{{width:390px;height:520px;border-radius:32px;overflow:hidden;border:4px solid {acc};
  box-shadow:0 28px 72px rgba(0,0,0,.82),0 0 54px {P.rgba(acc,.35)};}}
.big-stat .face-wrap img{{width:100%;height:100%;object-fit:cover;object-position:50% 22%;}}

/* compare-vs */
.compare-vs{{display:flex;flex-direction:column;justify-content:space-between;}}
.compare-vs .top-head{{display:flex;flex-direction:column;align-items:center;text-align:center;}}
.vs-row{{display:grid;grid-template-columns:1fr auto 1fr;gap:24px;align-items:center;margin-bottom:24px;}}
.vs-side{{height:290px;border-radius:26px;padding:30px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:18px;text-align:center;
  box-shadow:0 20px 52px rgba(0,0,0,.65);}}
.vs-side.bad{{background:linear-gradient(155deg,rgba(127,29,29,.88),rgba(30,14,18,.92));border:3px solid #F87171;}}
.vs-side.good{{background:linear-gradient(155deg,{P.rgba(acc,.32)},rgba(12,24,34,.92));border:3px solid {acc};}}
.vs-tag{{width:72px;height:72px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:900;}}
.vs-side.bad .vs-tag{{background:#EF4444;color:#fff;}}
.vs-side.good .vs-tag{{background:{acc};color:#07070B;}}
.vs-label{{font-size:44px;font-weight:900;line-height:1.2;color:#fff;}}
.vs-pill{{width:86px;height:86px;border-radius:50%;background:#FFFFFF;color:#07070B;display:flex;align-items:center;justify-content:center;
  font-size:34px;font-weight:900;box-shadow:0 12px 36px rgba(0,0,0,.75);}}
.compare-vs .face-wrap{{position:absolute;bottom:24px;left:50%;transform:translateX(-50%);width:154px;height:154px;border-radius:50%;
  overflow:hidden;border:4px solid #fff;box-shadow:0 14px 38px rgba(0,0,0,.8);display:none;}}
"""

    doc = f"""<!doctype html>
<html lang="ar">
<head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div id="stage">
  {bg_screen}
  <div class="vignette"></div>
  {body}
</div>
</body>
</html>
"""
    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(doc)
    return out_html
