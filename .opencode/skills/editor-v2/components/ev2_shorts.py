"""ev2_shorts.py — Pro 9:16 Shorts & Reels HyperFrames engine (1080x1920 @ 30fps) for Editor V2.

Data-driven (`work/shorts.json`): the agent writes DATA (spans, layout, beats, caption flag);
this module handles 1080x1920 geometry, smooth screen zoom moves, Darija+Latin BiDi
word-highlighted captions, native-resolution face framing, and zero-empty-band enforcement.

Layouts:
  - stacked:      Top 1080x1040 screen/recipe band + seam captions (y 1040..1180) + bottom 1080x740 native face band.
  - talking-head: Full-frame 1080x1920 speaker with optional split-screen recipe cards + safe-zone captions (y 1300..1460).
  - screen-only:  No webcam — top kicker bar + tall 1080x1240 zoomed screen/recipe stage + bottom captions.
"""
import html as _html
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'scripts'))
import ev2_pro as P  # noqa: E402

W, H, FPS = 1080, 1920, 30
LAYOUTS = ('stacked', 'talking-head', 'screen-only')
CARD_RECIPES = ('statement', 'steps', 'checklist', 'stat', 'title')

# Stacked canvas geometry (1080x1920)
TOP_BAND = (0, 0, 1080, 1040)
SEAM_CAP = (0, 1040, 1080, 140)
FACE_BAND = (0, 1180, 1080, 740)
SCREEN_WIN = (40, 72, 1000, 910)

# Screen-only geometry
SCR_ONLY_WIN = (40, 150, 1000, 1200)
SCR_ONLY_CAP = (0, 1400, 1080, 180)

# Talking-head geometry
TH_CAP = (0, 1300, 1080, 170)
TH_SPLIT_CARD = (48, 88, 984, 860)


def esc(s):
    return _html.escape(str(s), quote=True)


def fr(t):
    return round(float(t) * FPS) / FPS


def dstr(dur):
    n = max(1, int(round(float(dur) * FPS)))
    return f'{math.floor(n / FPS * 1e4) / 1e4:.4f}'


def _rich_text(text, accent_hex):
    """Turn `*word*` markup into accent-colored spans with BiDi isolation."""
    parts = re.split(r'(\*[^*]+\*)', str(text))
    is_rtl = P.has_ar(text)
    out = []
    for part in parts:
        if not part:
            continue
        hi = part.startswith('*') and part.endswith('*') and len(part) > 2
        raw = part[1:-1] if hi else part
        # Isolate Latin tokens inside RTL text
        if is_rtl and not P.has_ar(raw) and re.search(r'[A-Za-z0-9]', raw):
            inner = f'<bdi>{esc(raw)}</bdi>'
        else:
            inner = esc(raw)
        if hi:
            out.append(f'<span class="acc" style="color:{accent_hex}">{inner}</span>')
        else:
            out.append(inner)
    return ''.join(out)


def _bidi_word_span(wtxt, wid, is_rtl):
    if is_rtl and not P.has_ar(wtxt):
        return f'<span class="w" id="{wid}"><bdi>{esc(wtxt)}</bdi></span>'
    return f'<span class="w" id="{wid}">{esc(wtxt)}</span>'


# ------------------------------------------------------------------ validation
def validate_short_spec(spec, duration=None):
    """Return plain-language issues for one entry in work/shorts.json."""
    probs = []
    if not isinstance(spec, dict):
        return ['each short entry must be a JSON object']
    name = str(spec.get('name') or '').strip()
    if not name or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,48}', name):
        probs.append(f'short "{name or "?"}": name must be lowercase kebab/snake-case (a-z, 0-9, -, _)')
    layout = spec.get('layout', 'stacked')
    if layout not in LAYOUTS:
        probs.append(f'short "{name}": layout must be one of {", ".join(LAYOUTS)} (got {layout!r})')
    spans = spec.get('spans')
    if not isinstance(spans, list) or not spans:
        probs.append(f'short "{name}": "spans" must be a non-empty list of [start, end] pairs')
    else:
        tot = 0.0
        for i, sp in enumerate(spans, 1):
            if (not isinstance(sp, (list, tuple)) or len(sp) != 2
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sp)
                    or sp[1] <= sp[0] + 0.5):
                probs.append(f'short "{name}": span #{i} must be [start, end] with end > start + 0.5')
            else:
                tot += float(sp[1]) - float(sp[0])
        if tot > 62.0:
            probs.append(f'short "{name}": total span duration {tot:.1f}s exceeds 60s Short limit (trim spans <= 59s)')
        if duration is None:
            duration = tot

    beats = spec.get('beats') or []
    if not isinstance(beats, list):
        probs.append(f'short "{name}": "beats" must be a list')
        beats = []
    intervals = []
    for i, b in enumerate(beats, 1):
        if not isinstance(b, dict):
            probs.append(f'short "{name}" beat #{i}: must be an object')
            continue
        at = b.get('at')
        dur = b.get('dur')
        btype = b.get('type', 'screen')
        if not isinstance(at, (int, float)) or not isinstance(dur, (int, float)) or at < 0 or dur < 0.8:
            probs.append(f'short "{name}" beat #{i}: needs numeric "at" >= 0 and "dur" >= 0.8')
            continue
        intervals.append((float(at), float(at) + float(dur)))
        if btype == 'card':
            rec = b.get('recipe')
            if rec not in CARD_RECIPES:
                probs.append(f'short "{name}" beat #{i}: card recipe must be one of {", ".join(CARD_RECIPES)}')
            data = b.get('data') or {}
            if rec == 'statement' and not str(data.get('text', '')).strip():
                probs.append(f'short "{name}" beat #{i} (statement): data.text is required')
            elif rec == 'title' and not str(data.get('title', '')).strip():
                probs.append(f'short "{name}" beat #{i} (title): data.title is required')
            elif rec == 'stat' and not str(data.get('value', '')).strip():
                probs.append(f'short "{name}" beat #{i} (stat): data.value is required')
            elif rec in ('steps', 'checklist'):
                key = 'steps' if rec == 'steps' else 'items'
                lst = data.get(key)
                if not isinstance(lst, list) or not 2 <= len(lst) <= 6:
                    probs.append(f'short "{name}" beat #{i} ({rec}): data.{key} needs 2-6 items')
        elif btype != 'screen':
            probs.append(f'short "{name}" beat #{i}: type must be "screen" or "card"')

    # Stacked layout: enforce no empty band gaps > 1.5 s when explicit beats are supplied
    if layout in ('stacked', 'screen-only') and intervals and duration and duration > 2.0:
        intervals.sort()
        cur = 0.0
        for a, b in intervals:
            if a - cur > 1.5:
                probs.append(f'short "{name}": EMPTY BAND gap {a - cur:.1f}s ({cur:.1f}s..{a:.1f}s) — extend previous beat or add a card/screen beat')
            cur = max(cur, b)
        if duration - cur > 1.5:
            probs.append(f'short "{name}": EMPTY BAND gap at end ({cur:.1f}s..{duration:.1f}s) — extend last beat to cover full duration')
    return probs


def validate_shorts_cfg(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get('shorts'), list):
        return ['work/shorts.json must be {"shorts": [...]}']
    probs = []
    seen = set()
    for sp in cfg['shorts']:
        n = sp.get('name') if isinstance(sp, dict) else None
        if n in seen:
            probs.append(f'work/shorts.json: duplicate short name "{n}"')
        elif n:
            seen.add(n)
        probs += validate_short_spec(sp)
    return probs


# ------------------------------------------------------------------ vertical caption grouping
def group_words_vertical(words, max_chars=24, max_words=4, max_gap=0.35):
    """Group [{w, s, e}] (local short seconds) into punchy 2-4 word vertical caption groups."""
    clean = [
        {'w': str(w['w']).strip(), 's': float(w['s']), 'e': max(float(w['s']) + 0.06, float(w.get('e', w['s'])))}
        for w in (words or []) if str(w.get('w', '')).strip()
    ]
    if not clean:
        return {'words': [], 'groups': []}
    groups = []
    cur = []
    for idx, wd in enumerate(clean):
        if cur:
            prev = clean[cur[-1]]
            cur_text = ' '.join(clean[j]['w'] for j in cur)
            nxt_text = cur_text + ' ' + wd['w']
            gap = wd['s'] - prev['e']
            end_punct = prev['w'][-1:] in '.!?؟،,'
            if len(cur) >= max_words or len(nxt_text) > max_chars or gap > max_gap or (end_punct and len(cur) >= 2):
                groups.append(cur)
                cur = []
        cur.append(idx)
    if cur:
        groups.append(cur)

    # Merge any lonely 1-word group that is very short (< 0.45 s) with its neighbor if space allows
    merged = []
    for g in groups:
        if merged and len(g) == 1:
            g_dur = clean[g[-1]]['e'] - clean[g[0]]['s']
            prev_txt = ' '.join(clean[j]['w'] for j in merged[-1])
            if g_dur < 0.45 and len(merged[-1]) < max_words + 1 and len(prev_txt) + 1 + len(clean[g[0]]['w']) <= max_chars + 6:
                merged[-1].extend(g)
                continue
        merged.append(g)

    out_groups = []
    for k, g in enumerate(merged):
        gs = clean[g[0]]['s']
        ge = clean[g[-1]]['e']
        nxt_s = clean[merged[k + 1][0]]['s'] if k + 1 < len(merged) else ge + 0.35
        ge = min(max(ge + 0.12, gs + 0.48), nxt_s)
        txt = ' '.join(clean[j]['w'] for j in g)
        out_groups.append({
            's': round(gs, 3),
            'e': round(ge, 3),
            'words': g,
            'text': txt,
            'rtl': P.has_ar(txt),
        })
    return {'words': clean, 'groups': out_groups}


# ------------------------------------------------------------------ screen camera math
def _screen_transform(rect, vw, vh, sw=1920, sh=1080, max_zoom=1.85):
    rx, ry, rw, rh = [float(v) for v in rect]
    sc = min(vw / max(1.0, rw), vh / max(1.0, rh), float(max_zoom))
    # Never zoom out smaller than fitting the window width/height cleanly
    min_sc = max(vw / sw, vh / sh) * 0.72
    sc = max(sc, min_sc)
    x = -rx * sc + (vw - rw * sc) / 2.0
    y = -ry * sc + (vh - rh * sc) / 2.0
    x = (vw - sw * sc) / 2.0 if sw * sc <= vw else min(0.0, max(vw - sw * sc, x))
    y = (vh - sh * sc) / 2.0 if sh * sc <= vh else min(0.0, max(vh - sh * sc, y))
    return round(x, 2), round(y, 2), round(sc, 5)


# ------------------------------------------------------------------ card renderers
def _render_card_beat(bid, beat, box, theme, t0, dur):
    """Return (html, pre_js, tl_js, suppress_captions) for one vertical recipe card."""
    x, y, w, h = box
    rec = beat.get('recipe', 'statement')
    data = beat.get('data') or {}
    acc = theme['accent']
    pre, js = [], []
    suppress_caps = rec in ('statement', 'title')
    kicker = str(data.get('kicker') or '').strip()
    kicker_html = f'<div class="kicker">{esc(kicker)}</div>' if kicker else ''

    body = ''
    if rec == 'statement':
        txt = str(data.get('text') or '').strip()
        icon_name = data.get('icon')
        ic_html = f'<div class="card-ic">{P.icon_svg(icon_name, 56, acc)}</div>' if icon_name and P.icon_exists(icon_name) else ''
        fs = 62 if len(P.plain(txt)) <= 38 else (52 if len(P.plain(txt)) <= 65 else 44)
        dir_attr = ' dir="rtl"' if P.has_ar(txt) else ''
        body = f'{ic_html}{kicker_html}<div class="stmt-txt"{dir_attr} style="font-size:{fs}px">{_rich_text(txt, acc)}</div>'
    elif rec == 'title':
        title = str(data.get('title') or '').strip()
        sub = str(data.get('sub') or '').strip()
        dir_t = ' dir="rtl"' if P.has_ar(title) else ''
        dir_s = ' dir="rtl"' if P.has_ar(sub) else ''
        sub_html = f'<div class="title-sub"{dir_s}>{_rich_text(sub, acc)}</div>' if sub else ''
        body = f'{kicker_html}<div class="title-main"{dir_t}>{_rich_text(title, acc)}</div><div class="title-rule"></div>{sub_html}'
    elif rec == 'stat':
        val = str(data.get('value') or '').strip()
        lab = str(data.get('label') or '').strip()
        dir_l = ' dir="rtl"' if P.has_ar(lab) else ''
        # Land directly on final value (editorial polish, no gimmicky count-up)
        body = f'{kicker_html}<div class="stat-val" style="color:{acc}">{esc(val)}</div><div class="stat-lab"{dir_l}>{_rich_text(lab, acc)}</div>'
    elif rec in ('steps', 'checklist'):
        key = 'steps' if rec == 'steps' else 'items'
        title = str(data.get('title') or '').strip()
        dir_t = ' dir="rtl"' if P.has_ar(title) else ''
        raw_items = data.get(key) or []
        rows = []
        n_items = max(1, len(raw_items))
        step_span = min(0.85, max(0.35, (dur - 1.4) / n_items))
        for idx, it in enumerate(raw_items):
            if isinstance(it, str):
                lab, sub, it_at = it, '', None
            else:
                lab = str(it.get('label', '')).strip()
                sub = str(it.get('sub', '')).strip()
                it_at = it.get('at')
            rid = f'{bid}_r{idx}'
            badge = (f'<span class="step-num">{idx + 1}</span>' if rec == 'steps'
                     else f'<span class="chk-box">{P.icon_svg("check", 24, "#07070B")}</span>')
            r_dir = ' dir="rtl"' if P.has_ar(lab) else ''
            sub_h = f'<div class="row-sub">{esc(sub)}</div>' if sub else ''
            rows.append(f'<div class="row-item" id="{rid}"{r_dir}>{badge}<div class="row-txt"><div class="row-lab">{_rich_text(lab, acc)}</div>{sub_h}</div></div>')
            pre.append(f'gsap.set("#{rid}",{{opacity:0,y:18}});')
            rt = float(it_at) if isinstance(it_at, (int, float)) else (t0 + 0.25 + idx * step_span)
            js.append(f'tl.to("#{rid}",{{opacity:1,y:0,duration:0.32,ease:"power3.out"}},{fr(rt):.3f});')
        t_html = f'<div class="list-title"{dir_t}>{_rich_text(title, acc)}</div>' if title else ''
        body = f'{kicker_html}{t_html}<div class="row-list">{"".join(rows)}</div>'

    cid = f'beat_{bid}'
    html = (f'<div class="card-beat" id="{cid}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
            f'<div class="card-inner">{body}</div></div>')
    pre.append(f'gsap.set("#{cid}",{{opacity:0,y:24,scale:0.97}});')
    js.append(f'tl.to("#{cid}",{{opacity:1,y:0,scale:1,duration:0.30,ease:"power3.out"}},{fr(t0):.3f});')
    t_out = max(t0 + 0.35, t0 + dur - 0.22)
    js.append(f'tl.to("#{cid}",{{opacity:0,y:-16,duration:0.22,ease:"power2.in"}},{fr(t_out):.3f});')
    return html, pre, js, suppress_caps


# ------------------------------------------------------------------ main HTML builder
def build_short_html(proj_dir, spec, duration, words, theme, has_screen=True, has_face=True, punch_times=()):
    """Write `<proj_dir>/index.html` and `<proj_dir>/meta.json` for one 1080x1920 Pro Short."""
    os.makedirs(proj_dir, exist_ok=True)
    layout = spec.get('layout', 'stacked')
    name = spec.get('name', 'short')
    show_caps = spec.get('captions', True)
    kicker = str(spec.get('hook_kicker') or '').strip()
    dur = fr(duration)

    # Write vertical backdrop + subtle grain locally inside proj_dir
    P.write_bg(os.path.join(proj_dir, 'bg.png'), theme, w=W, h=H)
    P.write_grain(os.path.join(proj_dir, 'grain.png'))

    cap_data = group_words_vertical(words) if show_caps else {'words': [], 'groups': []}
    beats = list(spec.get('beats') or [])
    if not beats:
        if layout in ('stacked', 'screen-only') and has_screen:
            beats = [{'at': 0.0, 'dur': dur, 'type': 'screen', 'max_zoom': 1.5,
                      'moves': [{'t': 0.0, 'rect': [0, 0, 1920, 1080], 'dur': 0.0}]}]

    pre_js, tl_js = [], []
    beat_htmls = []
    suppress_ranges = []
    screen_intervals = []
    split_intervals = []

    if layout == 'stacked':
        win_box = SCREEN_WIN
        cap_box = SEAM_CAP
    elif layout == 'screen-only':
        win_box = SCR_ONLY_WIN
        cap_box = SCR_ONLY_CAP
    else:
        win_box = TH_SPLIT_CARD
        cap_box = TH_CAP

    # Screen video container (shared single <video> element for smooth timeline playback)
    screen_moves_js = []
    for bi, b in enumerate(beats):
        bt0 = float(b.get('at', 0.0))
        bdur = min(float(b.get('dur', dur - bt0)), max(0.2, dur - bt0))
        btype = b.get('type', 'screen')
        if btype == 'screen' and has_screen:
            screen_intervals.append((bt0, bt0 + bdur))
            mz = float(b.get('max_zoom', 1.75))
            moves = b.get('moves') or [{'t': bt0, 'rect': [160, 90, 1600, 900], 'dur': 0.0}]
            for mi, mv in enumerate(moves):
                mt = float(mv.get('t', bt0))
                md = float(mv.get('dur', 0.65 if mi > 0 else 0.0))
                rect = mv.get('rect') or [160, 90, 1600, 900]
                tx, ty, ts = _screen_transform(rect, win_box[2], win_box[3], max_zoom=mz)
                if md <= 0.01:
                    screen_moves_js.append(f'tl.set("#scrcam",{{x:{tx},y:{ty},scale:{ts}}},{fr(mt):.3f});')
                else:
                    screen_moves_js.append(f'tl.to("#scrcam",{{x:{tx},y:{ty},scale:{ts},duration:{md:.3f},ease:"power2.inOut"}},{fr(mt):.3f});')
        elif btype == 'card':
            ch, cpre, cjs, supp = _render_card_beat(f'b{bi}', b, win_box, theme, bt0, bdur)
            beat_htmls.append(ch)
            pre_js.extend(cpre)
            tl_js.extend(cjs)
            if supp:
                suppress_ranges.append((bt0, bt0 + bdur))
            if layout == 'talking-head':
                split_intervals.append((bt0, bt0 + bdur))

    # Animate screen window visibility across screen intervals
    screen_html = ''
    if has_screen and screen_intervals:
        sx, sy, sw, sh = win_box
        screen_html = (
            f'<div id="scrwin" style="left:{sx}px;top:{sy}px;width:{sw}px;height:{sh}px">'
            f'<div id="scrcam" data-layout-allow-overflow>'
            f'<video id="scrvid" src="screen.mp4" muted playsinline data-start="0.0000" data-duration="{dstr(dur)}"></video>'
            f'</div></div>'
        )
        pre_js.append('gsap.set("#scrwin",{opacity:0,scale:0.98});')
        for s0, s1 in screen_intervals:
            tl_js.append(f'tl.to("#scrwin",{{opacity:1,scale:1,duration:0.25,ease:"power2.out"}},{fr(s0):.3f});')
            if s1 < dur - 0.1:
                tl_js.append(f'tl.to("#scrwin",{{opacity:0,duration:0.20,ease:"power2.in"}},{fr(max(s0 + 0.25, s1 - 0.15)):.3f});')
        tl_js.extend(screen_moves_js)

    # Face video layer
    face_html = ''
    if has_face and layout == 'stacked':
        fx, fy, fw, fh = FACE_BAND
        face_html = (
            f'<div id="faceband" style="left:{fx}px;top:{fy}px;width:{fw}px;height:{fh}px">'
            f'<div class="seam-line"></div>'
            f'<video id="facevid" src="face.mp4" muted playsinline data-start="0.0000" data-duration="{dstr(dur)}"></video>'
            f'</div>'
        )
    elif has_face and layout == 'talking-head':
        face_html = (
            f'<div id="facefull">'
            f'<div id="facezoom" data-layout-allow-overflow>'
            f'<video id="facevid" src="face.mp4" muted playsinline data-start="0.0000" data-duration="{dstr(dur)}"></video>'
            f'</div></div>'
        )
        # Subtle alternating 10% punch-in on cuts (inspired by edit-video)
        if punch_times:
            pre_js.append('gsap.set("#facezoom",{scale:1.0});')
            for idx, pt in enumerate(punch_times):
                sc = 1.10 if idx % 2 == 1 else 1.0
                tl_js.append(f'tl.set("#facezoom",{{scale:{sc:.2f}}},{fr(pt):.3f});')
        # Shift face cleanly into bottom half during split card beats
        for s0, s1 in split_intervals:
            tl_js.append(f'tl.to("#facefull",{{top:1020,height:900,duration:0.32,ease:"power3.out"}},{fr(max(0.0, s0 - 0.15)):.3f});')
            tl_js.append(f'tl.to("#facefull",{{top:0,height:1920,duration:0.32,ease:"power3.inOut"}},{fr(min(dur, s1)):.3f});')

    # Top kicker badge (screen-only or stacked when no card at top)
    kicker_bar = ''
    if kicker:
        kicker_bar = f'<div id="topbadge"><span class="dot"></span><span>{esc(kicker)}</span></div>'

    # Captions HTML + GSAP (auto-suppressed during statement/title cards so text never doubles)
    cap_html = '<div id="caps">'
    cap_groups_js = []
    if show_caps and cap_data['groups']:
        ws_ = cap_data['words']
        for gi, g in enumerate(cap_data['groups']):
            mid = (g['s'] + g['e']) / 2.0
            if any(a - 0.05 <= mid <= b + 0.05 for a, b in suppress_ranges):
                continue
            dir_attr = ' dir="rtl"' if g['rtl'] else ''
            spans = ''.join(_bidi_word_span(ws_[j]['w'], f'cw{j}', g['rtl']) for j in g['words'])
            cap_html += f'<div class="cg" id="cg{gi}"><div class="cline"{dir_attr}>{spans}</div></div>'
            cap_groups_js.append({'gi': gi, 's': g['s'], 'e': g['e'], 'w': g['words']})
    cap_html += '</div>'

    cx, cy, cw, ch = cap_box
    acc = theme['accent']
    acc2 = theme['accent2']
    font_css = """
@font-face{font-family:'Cairo';src:url('fonts/Cairo-Var.ttf') format('truetype');font-weight:200 900;font-display:block;}
@font-face{font-family:'Inter';src:url('fonts/Inter-700.woff2') format('woff2');font-weight:700;font-display:block;}
@font-face{font-family:'Inter';src:url('fonts/Inter-900.woff2') format('woff2');font-weight:900;font-display:block;}
@font-face{font-family:'JetBrains Mono';src:url('fonts/JetBrainsMono-400.woff2') format('woff2');font-weight:400;font-display:block;}
"""
    css = f"""{font_css}
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:{theme['bg0']};font-family:'Cairo','Inter',sans-serif;color:{theme['text']};}}
#root{{position:relative;width:{W}px;height:{H}px;overflow:hidden;background:{theme['bg0']};}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1;}}
#grain{{position:absolute;inset:0;background:url('grain.png');opacity:.18;mix-blend-mode:overlay;z-index:2;pointer-events:none;}}
#topbadge{{position:absolute;top:24px;left:50%;transform:translateX(-50%);z-index:60;display:flex;align-items:center;gap:10px;
  padding:8px 22px;border-radius:999px;background:rgba(12,12,20,.78);border:1.5px solid {P.rgba(acc, .45)};
  font-size:24px;font-weight:700;letter-spacing:.02em;color:{theme['text']};box-shadow:0 8px 28px rgba(0,0,0,.45);}}
#topbadge .dot{{width:10px;height:10px;border-radius:50%;background:{acc};box-shadow:0 0 12px {acc};}}
#scrwin{{position:absolute;z-index:15;border-radius:26px;overflow:hidden;background:#05070c;
  border:2px solid {P.rgba(acc, .42)};box-shadow:0 24px 70px rgba(0,0,0,.60),0 0 54px {P.rgba(acc, .18)};}}
#scrcam{{position:absolute;left:0;top:0;width:1920px;height:1080px;transform-origin:0 0;}}
#scrvid{{position:absolute;left:0;top:0;width:1920px;height:1080px;display:block;}}
#faceband{{position:absolute;z-index:12;overflow:hidden;background:#05070c;}}
#faceband .seam-line{{position:absolute;top:0;left:0;right:0;height:3px;z-index:5;background:linear-gradient(90deg,transparent,{acc},{acc2},transparent);opacity:.85;}}
#faceband video{{width:100%;height:100%;object-fit:cover;display:block;}}
#facefull{{position:absolute;left:0;top:0;width:{W}px;height:{H}px;overflow:hidden;z-index:10;}}
#facezoom{{position:absolute;inset:0;transform-origin:50% 34%;}}
#facefull video{{width:100%;height:100%;object-fit:cover;display:block;}}
.card-beat{{position:absolute;z-index:25;display:flex;align-items:center;justify-content:center;padding:34px;}}
.card-inner{{width:100%;height:100%;border-radius:28px;padding:46px 44px;display:flex;flex-direction:column;justify-content:center;align-items:center;
  text-align:center;background:rgba(16,17,28,.88);border:1.5px solid rgba(255,255,255,.14);box-shadow:0 24px 68px rgba(0,0,0,.55);gap:24px;}}
.kicker{{font-size:24px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:{acc2};padding:6px 18px;border-radius:999px;background:{P.rgba(acc, .16)};}}
.card-ic{{width:92px;height:92px;border-radius:24px;display:flex;align-items:center;justify-content:center;background:{P.rgba(acc, .16)};border:1.5px solid {P.rgba(acc, .38)};}}
.stmt-txt{{font-weight:900;line-height:1.25;letter-spacing:-.01em;color:{theme['text']};}}
.title-main{{font-size:66px;font-weight:900;line-height:1.18;color:{theme['text']};}}
.title-rule{{width:120px;height:6px;border-radius:999px;background:linear-gradient(90deg,{acc},{acc2});}}
.title-sub{{font-size:34px;font-weight:600;color:{theme['muted']};line-height:1.35;}}
.stat-val{{font-size:150px;font-weight:900;line-height:1.0;letter-spacing:-.03em;}}
.stat-lab{{font-size:40px;font-weight:700;color:{theme['text']};line-height:1.3;max-width:820px;}}
.list-title{{font-size:46px;font-weight:900;line-height:1.22;margin-bottom:6px;}}
.row-list{{width:100%;display:flex;flex-direction:column;gap:18px;}}
.row-item{{display:flex;align-items:center;gap:20px;padding:20px 24px;border-radius:20px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.10);text-align:start;}}
.step-num{{flex:0 0 48px;height:48px;border-radius:14px;display:flex;align-items:center;justify-content:center;background:{acc};color:#07070B;font-size:26px;font-weight:900;}}
.chk-box{{flex:0 0 44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:{theme['good']};}}
.row-lab{{font-size:34px;font-weight:700;line-height:1.25;color:{theme['text']};}}
.row-sub{{font-size:24px;font-weight:500;color:{theme['muted']};margin-top:4px;}}
#caps{{position:absolute;left:{cx}px;top:{cy}px;width:{cw}px;height:{ch}px;z-index:55;pointer-events:none;}}
.cg{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:0;visibility:hidden;padding:0 36px;}}
.cline{{max-width:980px;text-align:center;font-family:'Cairo','Inter',sans-serif;font-weight:900;font-size:56px;line-height:1.22;
  color:#F7F9FC;text-shadow:0 4px 16px rgba(0,0,0,.92),0 0 3px rgba(0,0,0,.98);}}
.cline .w{{display:inline-block;margin:0 0.14em;transition:none;}}
"""

    cw_json = json.dumps([{'s': w['s'], 'e': w['e']} for w in cap_data['words']])
    cg_json = json.dumps(cap_groups_js)
    cap_js = f"""
var CG={cg_json}, CW={cw_json};
CG.forEach(function(g){{
  var el=document.getElementById('cg'+g.gi);
  if(!el) return;
  tl.set(el,{{visibility:'visible'}},g.s);
  tl.fromTo(el,{{opacity:0,y:14,scale:0.96}},{{opacity:1,y:0,scale:1,duration:0.11,ease:'power3.out',immediateRender:false}},g.s);
  g.w.forEach(function(j){{
    var w=document.getElementById('cw'+j);
    if(!w) return;
    tl.set(w,{{color:'{acc}',scale:1.06}},CW[j].s);
    tl.set(w,{{color:'#F7F9FC',scale:1.0}},Math.min(CW[j].e+0.05,g.e));
  }});
  tl.set(el,{{opacity:0,visibility:'hidden'}},g.e);
}});
""" if show_caps and cap_groups_js else ''

    html_doc = f"""<!doctype html>
<html lang="ar">
<head>
<meta charset="utf-8">
<style>{css}</style>
<script src="vendor/gsap.min.js"></script>
</head>
<body>
<div id="root" data-composition-id="{esc(name)}" data-start="0" data-duration="{dstr(dur)}" data-width="{W}" data-height="{H}">
  <img id="bg" src="bg.png" alt="">
  <div id="grain"></div>
  {kicker_bar}
  {face_html}
  {screen_html}
  {''.join(beat_htmls)}
  {cap_html}
  <audio id="vo" src="audio.wav" data-start="0.0000" data-duration="{dstr(dur)}" data-volume="1"></audio>
</div>
<script>
window.__timelines = window.__timelines || {{}};
gsap.config({{force3D:true}});
{chr(10).join(pre_js)}
var tl = gsap.timeline({{paused:true}});
{chr(10).join(tl_js)}
{cap_js}
window.__timelines["{esc(name)}"] = tl;
</script>
</body>
</html>
"""
    with open(os.path.join(proj_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html_doc)
    with open(os.path.join(proj_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': name, 'name': name, 'width': W, 'height': H, 'fps': FPS, 'duration': dur}, f, indent=2)
    return {
        'html': os.path.join(proj_dir, 'index.html'),
        'duration': dur,
        'caption_groups': cap_data['groups'],
        'beats': len(beats),
        'layout': layout,
    }
