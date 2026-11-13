"""ev2_recipes.py — explainer inserts from DATA, not code.

An insert in work/timeline.json with a "recipe" needs no inserts.py scene:

    {"name": "order-flow", "src_t": 126, "dur": 8, "recipe": "flow",
     "data": {"title": "كيفاش كتدور الطلبية", "steps": ["Boutique", "Commande", "WhatsApp", "Ozon Express"]}}

Recipes (all full-screen, on the video's own backdrop, every element animated, nothing frozen):
  flow       steps joined by animated connectors, a glowing dot travels the path   steps: 2-6
  steps      numbered list + a big icon panel that follows the current step         steps: 2-6
  checklist  rows that tick one by one                                              items: 2-8
  compare    two columns (before/after, bad/good) with a VS badge                   left/right: {title, items}
  stat       one big number counting up, label, up to 3 small numbers               value, label
  statement  one big sentence, *highlight* words, optional icon                     text
  screens    2-3 framed screenshots from the recording, fanned in 3D                shots: [{src_t, label}]

Items/steps are strings or {"label", "sub", "icon", "at"}: icon = a Lucide name, "brand:<slug>"
or omitted (guessed from the label); at = local seconds when it appears (default: spread over
the first ~55% of the insert, matched to the speech when the label is said).
validate(entry) returns a list of plain-language problems (empty = OK).
"""
import json, math, os, re, subprocess

import ev2_pro as P
from ev1_devices import sfx, fr

RTL = ' dir="rtl"'
RECIPES = ('flow', 'steps', 'checklist', 'compare', 'stat', 'statement', 'screens')
LIMITS = {'flow': (2, 6), 'steps': (2, 6), 'checklist': (2, 8)}


# ------------------------------------------------------------------ data helpers
def _item(x):
    if isinstance(x, str):
        return {'label': x}
    return dict(x)


def items_of(data, key):
    return [_item(x) for x in (data.get(key) or [])]


def validate(entry):
    """Problems with an insert entry's recipe data, as sentences a person (or a weak model) can act on."""
    r, d, name = entry.get('recipe'), entry.get('data') or {}, entry.get('name', '?')
    out = []
    if r not in RECIPES:
        return [f'insert "{name}": unknown recipe {r!r}; use one of {", ".join(RECIPES)}']
    if not isinstance(d, dict):
        return [f'insert "{name}": "data" must be an object']

    def need_list(key, lo, hi):
        v = d.get(key)
        if not isinstance(v, list) or not lo <= len(v) <= hi:
            out.append(f'insert "{name}" ({r}): "{key}" needs {lo}-{hi} entries (got {len(v) if isinstance(v, list) else "none"})')
            return []
        its = [_item(x) for x in v]
        for i, it in enumerate(its, 1):
            lab = str(it.get('label', '')).strip()
            if not lab:
                out.append(f'insert "{name}" ({r}): {key} #{i} has no label')
            elif len(lab) > 34:
                out.append(f'insert "{name}" ({r}): {key} #{i} "{lab}" is {len(lab)} chars; keep labels <= 34 (put details in "sub")')
            if it.get('sub') and len(str(it['sub'])) > 60:
                out.append(f'insert "{name}" ({r}): {key} #{i} "sub" is longer than 60 chars')
            if it.get('icon') and not P.icon_exists(str(it['icon'])):
                out.append(f'insert "{name}" ({r}): {key} #{i} icon "{it["icon"]}" not found (Lucide name or brand:<slug>; or leave it out)')
        return its

    if r in ('flow', 'steps'):
        need_list('steps', *LIMITS[r])
    elif r == 'checklist':
        need_list('items', *LIMITS[r])
    elif r == 'compare':
        for side in ('left', 'right'):
            v = d.get(side)
            if not isinstance(v, dict) or not isinstance(v.get('items'), list) or not 1 <= len(v['items']) <= 5:
                out.append(f'insert "{name}" (compare): "{side}" needs {{"title": "...", "items": [1-5 strings]}}')
    elif r == 'stat':
        if not str(d.get('value', '')).strip():
            out.append(f'insert "{name}" (stat): "value" is required (e.g. "6", "95%", "-46%")')
        if not str(d.get('label', '')).strip():
            out.append(f'insert "{name}" (stat): "label" is required')
        if len(d.get('items') or []) > 3:
            out.append(f'insert "{name}" (stat): at most 3 small "items"')
    elif r == 'statement':
        t = str(d.get('text', '')).strip()
        if not t:
            out.append(f'insert "{name}" (statement): "text" is required')
        elif len(P.plain(t)) > 90:
            out.append(f'insert "{name}" (statement): text is {len(P.plain(t))} chars; keep it <= 90')
    elif r == 'screens':
        v = d.get('shots')
        if not isinstance(v, list) or not 1 <= len(v) <= 3 or not all(isinstance(x, dict) and isinstance(x.get('src_t'), (int, float)) for x in v):
            out.append(f'insert "{name}" (screens): "shots" needs 1-3 entries like {{"src_t": 150.0, "label": "..."}}')
    t = d.get('title')
    if t is not None and len(P.plain(str(t))) > 60:
        out.append(f'insert "{name}": title is {len(P.plain(str(t)))} chars; keep it <= 60')
    return out


def schedule(n, dur, start=0.55, frac=0.55, ats=None, said=None):
    """Reveal times for n elements: explicit 'at' wins, else when the label is said, else spread
    evenly from `start` to `frac` of the insert. Always increasing, >= 0.25 s apart."""
    end = max(start + 0.3 * (n - 1), dur * frac)
    even = [start + (end - start) * k / max(1, n - 1) for k in range(n)] if n > 1 else [start]
    out, prev = [], -1.0
    for k in range(n):
        t = None
        if ats and ats[k] is not None:
            t = float(ats[k])
        elif said and said[k] is not None and abs(said[k] - even[k]) < dur * 0.35:
            t = said[k] - 0.15
        t = even[k] if t is None else t
        t = max(t, prev + 0.25, 0.2)
        t = min(t, dur - 1.2)
        out.append(t)
        prev = t
    return out


def _norm(s):
    s = str(s).lower()
    s = re.sub(r'[^\w\u0600-\u06FF]+', ' ', s)
    return [w for w in s.split() if len(w) >= 3]


def said_times(labels, words):
    """Local time each label is first said (fuzzy: a 4-letter prefix of one of its words)."""
    out = []
    for lab in labels:
        keys = [w[:4] for w in _norm(lab)]
        t = None
        for wd, wt in words or []:
            ws = _norm(wd)
            if any(x[:4] == k for x in ws for k in keys):
                t = wt
                break
        out.append(t)
    return out


# ------------------------------------------------------------------ shared scaffold
class Ctx:
    """What a recipe needs besides its data: theme, backdrop paths, the words said during the
    insert (local times) and a still() extractor for screenshots from the recording."""
    def __init__(self, theme, bg='assets/pro/bg.png', grain='assets/pro/grain.png', words=None, vd='.'):
        self.th, self.bg, self.grain, self.words, self.vd = theme, bg, grain, words or [], vd

    def still(self, src_t):
        """A frame of the recording with the burned-in webcam painted out (a face from another
        moment would not match the voice)."""
        return P.clean_still(self.vd, src_t)


def scaffold(c, dur, ctx, title='', kicker='', z=1):
    """Backdrop + kicker + title + a thin progress line. Returns (content_top, title_ids)."""
    th = ctx.th
    P.pro_css(c, th)
    P.backdrop(c, 0, dur, th, ctx.bg, z=z, grain_src=ctx.grain)
    top = 150
    ids = []
    if kicker:
        kid = c.uid('pk')
        rtl = P.has_ar(kicker)
        c.clip(0, dur, f'<div id="{kid}" class="pro-abs pro-kicker"{RTL if rtl else ""} '
                       f'style="left:0;top:96px;width:1920px;text-align:center">{P.bidi(kicker)}</div>', z + 5, cls='')
        P.pop_in(c, kid, 0.12, 0.4, 1.0, 14, 'power3.out')
        top = 170
    if title:
        size, lines = P.fit_text(title, 1500, (66, 60, 54, 48, 44, 40), 800, 2)
        html, ids = P.text_block(c, title, 210, top - 20, 1500, size, 800)
        c.clip(0, dur, html, z + 5, cls='')
        P.reveal_words(c, ids, 0.18, 0.05, 0.45, 28, 12)
        top = top - 20 + len(lines) * size * 1.12 + 60
    # progress line: the insert's own clock, so the frame always moves
    pid = c.uid('pp')
    c.clip(0, dur, f'<div class="pro-abs" style="left:0;bottom:0;width:1920px;height:6px;background:rgba(255,255,255,0.06)">'
                   f'<div id="{pid}" style="width:1920px;height:6px;transform-origin:0 50%;'
                   f'background:linear-gradient(90deg,{th["accent"]},{th["accent2"]})"></div></div>', z + 6, cls='')
    c.pre.append(f'gsap.set("#{pid}",{{scaleX:0}});')
    c.at(f'tl.fromTo("#{pid}",{{scaleX:0}},{{scaleX:1,duration:{dur:.3f},ease:"none",immediateRender:false}},0);')
    return top, ids


def _drift(c, gid, dur, s=0.035):
    c.at(f'tl.fromTo("#{gid}",{{scale:1}},{{scale:{1 + s:.3f},duration:{dur:.3f},ease:"none",immediateRender:false}},0);')


# ------------------------------------------------------------------ flow
def r_flow(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    steps = items_of(d, 'steps')
    n = len(steps)
    top, _ = scaffold(c, dur, ctx, d.get('title', ''), d.get('kicker', ''))
    rtl = d.get('dir') == 'rtl' or (d.get('dir') is None and sum(P.has_ar(s['label']) for s in steps) > n / 2)
    gid = c.uid('pflow')
    cy = (top + 1000) / 2 - 20
    margin = 230 if n <= 4 else 170
    xs = [margin + (1920 - 2 * margin) * k / max(1, n - 1) for k in range(n)] if n > 1 else [960]
    if rtl:
        xs = xs[::-1]
    gap = (xs[1] - xs[0]) if n > 1 else 800
    lab_w = int(min(420, abs(gap) - 30))
    R = 74 if n <= 4 else 64
    labels = [s['label'] for s in steps]
    times = schedule(n, dur, 0.6, 0.5, [s.get('at') for s in steps], said_times(labels, ctx.words))
    lab_size = min(P.fit_text(l, lab_w, (40, 36, 32, 30, 28, 26, 24), 700, 2)[0] for l in labels)

    # connectors (SVG), drawn when the next node lands
    svg = [f'<svg class="pro-abs" style="left:0;top:0;width:1920px;height:1080px;overflow:visible" viewBox="0 0 1920 1080">',
           f'<defs><linearGradient id="{gid}g" x1="0" x2="1"><stop offset="0" stop-color="{th["accent"]}"/>'
           f'<stop offset="1" stop-color="{th["accent2"]}"/></linearGradient></defs>']
    con = []
    for k in range(n - 1):
        x1, x2 = xs[k] + (R + 18) * (1 if not rtl else -1), xs[k + 1] - (R + 18) * (1 if not rtl else -1)
        lid, fid = c.uid('pcl'), c.uid('pcf')
        svg.append(f'<line x1="{x1:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{cy:.1f}" stroke="rgba(255,255,255,0.12)" stroke-width="4" stroke-linecap="round"/>')
        svg.append(f'<line id="{lid}" x1="{x1:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{cy:.1f}" stroke="url(#{gid}g)" stroke-width="4" '
                   f'stroke-linecap="round" pathLength="1" style="stroke-dasharray:1 1;stroke-dashoffset:1"/>')
        svg.append(f'<line id="{fid}" x1="{x1:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{cy:.1f}" stroke="rgba(255,255,255,0.55)" stroke-width="4" '
                   f'stroke-linecap="round" style="stroke-dasharray:2 18;opacity:0"/>')
        ax = x2 - 6 * (1 if not rtl else -1)
        aid = c.uid('pca')
        sgn = 1 if not rtl else -1
        svg.append(f'<path id="{aid}" d="M {ax - 14 * sgn:.1f} {cy - 12:.1f} L {ax:.1f} {cy:.1f} L {ax - 14 * sgn:.1f} {cy + 12:.1f}" '
                   f'fill="none" stroke="{th["accent2"]}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" opacity="0"/>')
        con.append((lid, fid, aid, x1, x2))
    svg.append('</svg>')

    nodes = []
    for k, s in enumerate(steps):
        nid, rid, lid = c.uid('pn'), c.uid('pr'), c.uid('pl')
        ic = s.get('icon') or P.guess_icon(s['label'])
        sub = s.get('sub', '')
        rtl_l = P.has_ar(s['label'])
        lab = (f'<div id="{lid}" class="pro-abs pro-txt"{RTL if rtl_l else ""} style="left:{xs[k] - lab_w / 2:.0f}px;'
               f'top:{cy + R + 34:.0f}px;width:{lab_w}px;text-align:center;font-size:{lab_size}px;font-weight:700;line-height:1.18">'
               f'{P.bidi(s["label"])}'
               + (f'<div style="font-size:{max(20, int(lab_size * 0.62))}px;font-weight:600;color:var(--pro-muted);margin-top:10px">{P.bidi(sub)}</div>' if sub else '')
               + '</div>')
        num = (f'<div class="pro-abs" style="left:{xs[k] - 18:.0f}px;top:{cy - R - 58:.0f}px;width:36px;text-align:center;'
               f'font:800 20px/1 \'EV1 Sans\';letter-spacing:0.1em;color:var(--pro-muted)">{k + 1:02d}</div>')
        node = (f'<div id="{nid}" class="pro-abs" style="left:{xs[k] - R:.0f}px;top:{cy - R:.0f}px;width:{2 * R}px;height:{2 * R}px">'
                f'<div id="{rid}" class="pro-abs" style="left:-14px;top:-14px;width:{2 * R + 28}px;height:{2 * R + 28}px;border-radius:50%;'
                f'border:2px solid {P.rgba(th["accent2"], 0.55)};opacity:0"></div>'
                f'<div class="pro-ico" style="width:{2 * R}px;height:{2 * R}px">{P.icon_svg(ic, int(R * 0.92), "#fff", 1.7)}</div></div>')
        nodes.append((nid, rid, lid, num, node, lab))
    dot = c.uid('pdot')
    inner = (f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px;transform-origin:50% {cy:.0f}px">'
             + ''.join(svg) + ''.join(x[3] + x[4] + x[5] for x in nodes)
             + f'<div id="{dot}" class="pro-abs" style="left:{xs[0] - 11:.0f}px;top:{cy - 11:.0f}px;width:22px;height:22px;border-radius:50%;'
               f'background:#fff;box-shadow:0 0 18px 6px {P.rgba(th["accent2"], 0.85)};opacity:0"></div></div>')
    c.clip(0, dur, inner, 3, cls='')
    _drift(c, gid, dur, 0.03)

    for k, (nid, rid, lid, *_rest) in enumerate(nodes):
        t = times[k]
        P.pop_in(c, nid, t, 0.5, 0.4, 0, 'back.out(1.8)')
        P.pop_in(c, lid, t + 0.1, 0.4, 1.0, 18, 'power3.out')
        sfx(c, t, 'click_soft', 0.9)
        if k > 0:
            lid_c, fid, aid, *_ = con[k - 1]
            c.at(f'tl.fromTo("#{lid_c}",{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:0.45,ease:"power2.inOut",immediateRender:false}},{max(0, t - 0.4):.4f});')
            c.at(f'tl.fromTo("#{aid}",{{opacity:0}},{{opacity:1,duration:0.2,immediateRender:false}},{t - 0.05:.4f});')
    # after the last node: the dashes flow and a dot travels the chain, each node pulses as it arrives
    t_all = times[-1] + 0.6
    for lid_c, fid, aid, x1, x2 in con:
        c.at(f'tl.fromTo("#{fid}",{{opacity:0}},{{opacity:1,duration:0.3,immediateRender:false}},{t_all:.4f});')
        c.at(f'tl.fromTo("#{fid}",{{strokeDashoffset:0}},{{strokeDashoffset:{-20 * max(1, (dur - t_all) * 2.2):.0f},duration:{max(0.1, dur - t_all):.3f},ease:"none",immediateRender:false}},{t_all:.4f});')
    if n > 1 and dur - t_all > 1.2:
        hop = min(0.9, max(0.45, (dur - t_all - 0.4) / max(1, n - 1)))
        t = t_all
        c.at(f'tl.fromTo("#{dot}",{{opacity:0}},{{opacity:1,duration:0.2,immediateRender:false}},{t:.4f});')
        k = 0
        while t + hop <= dur - 0.25:
            a, b = k % (n - 1), k % (n - 1) + 1
            if a == 0 and k:
                c.at(f'tl.set("#{dot}",{{x:0}},{t:.4f});')
            c.at(f'tl.fromTo("#{dot}",{{x:{xs[a] - xs[0]:.1f}}},{{x:{xs[b] - xs[0]:.1f},duration:{hop:.3f},ease:"power1.inOut",immediateRender:false}},{t:.4f});')
            rid = nodes[b][1]
            c.at(f'tl.fromTo("#{rid}",{{opacity:0.9,scale:0.9}},{{opacity:0,scale:1.35,duration:0.6,ease:"power2.out",immediateRender:false}},{t + hop - 0.05:.4f});')
            t += hop
            k += 1


# ------------------------------------------------------------------ steps
def r_steps(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    steps = items_of(d, 'steps')
    n = len(steps)
    top, _ = scaffold(c, dur, ctx, d.get('title', ''), d.get('kicker', ''))
    rtl = sum(P.has_ar(s['label']) for s in steps) > n / 2
    labels = [s['label'] for s in steps]
    times = schedule(n, dur, 0.55, 0.6, [s.get('at') for s in steps], said_times(labels, ctx.words))
    avail = 1000 - top
    row_h = min(150, avail / n)
    list_w, panel = 980, 620
    lx = 1920 - 160 - list_w if rtl else 160
    px = 160 if rtl else 1920 - 160 - panel
    y0 = top + (avail - row_h * n) / 2
    lab_size = min(P.fit_text(l, list_w - 160, (44, 40, 36, 32, 30, 28), 700, 1)[0] for l in labels)
    gid, bar = c.uid('psteps'), c.uid('pbar')
    rows, panel_items = [], []
    for k, s in enumerate(steps):
        rid = c.uid('prow')
        y = y0 + k * row_h
        sub = s.get('sub', '')
        num = (f'<div class="pro-ico" style="width:66px;height:66px;flex:none;font:800 28px/1 \'EV1 Sans\'">{k + 1}</div>')
        txt = (f'<div class="pro-txt"{RTL if P.has_ar(s["label"]) else ""} style="font-size:{lab_size}px;font-weight:700;line-height:1.15">'
               f'{P.bidi(s["label"])}' + (f'<div style="font-size:{max(22, int(lab_size * 0.6))}px;color:var(--pro-muted);font-weight:600;margin-top:6px">{P.bidi(sub)}</div>' if sub else '')
               + '</div>')
        rows.append(f'<div id="{rid}" class="pro-abs" style="left:{lx + 24}px;top:{y:.0f}px;width:{list_w - 48}px;height:{row_h:.0f}px;'
                    f'display:flex;align-items:center;gap:30px;flex-direction:{"row-reverse" if rtl else "row"}">{num}{txt}</div>')
        pid = c.uid('ppan')
        ic = s.get('icon') or P.guess_icon(s['label'])
        panel_items.append(f'<div id="{pid}" class="pro-abs" style="left:0;top:0;width:{panel}px;height:{panel}px;display:flex;flex-direction:column;'
                           f'align-items:center;justify-content:center;gap:34px;opacity:0">'
                           f'<div class="pro-ico" style="width:250px;height:250px">{P.icon_svg(ic, 140, "#fff", 1.5)}</div>'
                           f'<div class="pro-txt" style="font:800 30px/1 \'EV1 Sans\';letter-spacing:0.2em;color:var(--pro-muted)">STEP {k + 1:02d}</div></div>')
        rows[-1] = (rows[-1], rid, pid, y)
    hl = (f'<div id="{bar}" class="pro-abs pro-card" style="left:{lx}px;top:{y0:.0f}px;width:{list_w}px;height:{row_h - 14:.0f}px;'
          f'border-radius:22px;border-color:{P.rgba(th["accent"], 0.55)};opacity:0"></div>')
    pan = (f'<div class="pro-abs pro-card" style="left:{px}px;top:{top + (avail - panel) / 2:.0f}px;width:{panel}px;height:{panel}px">'
           + ''.join(panel_items) + '</div>')
    c.clip(0, dur, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">{hl}{pan}'
           + ''.join(r[0] for r in rows) + '</div>', 3, cls='')
    _drift(c, gid, dur, 0.025)
    prev_pid = None
    for k, (html, rid, pid, y) in enumerate(rows):
        t = times[k]
        P.pop_in(c, rid, t, 0.45, 0.94, 0, 'power3.out')
        c.at(f'tl.fromTo("#{bar}",{{opacity:{0 if k == 0 else 1}}},{{opacity:1,y:{y - y0 + 7:.0f},duration:0.4,ease:"power3.inOut",immediateRender:false}},{t - 0.05:.4f});')
        c.at(f'tl.fromTo("#{pid}",{{opacity:0,scale:0.8}},{{opacity:1,scale:1,duration:0.45,ease:"back.out(1.6)",immediateRender:false}},{t:.4f});')
        if prev_pid:
            c.at(f'tl.to("#{prev_pid}",{{opacity:0,scale:1.1,duration:0.3,ease:"power2.in"}},{t - 0.05:.4f});')
        prev_pid = pid
        sfx(c, t, 'click_soft', 0.9)
    # tour: after the list is complete, the highlight (and the icon panel) walk the steps again
    t = times[-1] + 1.0
    hop = max(0.8, min(1.3, (dur - t - 0.3) / max(1, n)))
    k, cur = 0, n - 1
    while n > 1 and t + hop <= dur - 0.2:
        y, pid = rows[k % n][3], rows[k % n][2]
        c.at(f'tl.to("#{bar}",{{y:{y - y0 + 7:.0f},duration:0.4,ease:"power3.inOut"}},{t:.4f});')
        c.at(f'tl.to("#{rows[cur][2]}",{{opacity:0,scale:1.1,duration:0.25,ease:"power2.in"}},{t:.4f});')
        c.at(f'tl.fromTo("#{pid}",{{opacity:0,scale:0.85}},{{opacity:1,scale:1,duration:0.4,ease:"back.out(1.6)",immediateRender:false}},{t + 0.12:.4f});')
        cur = k % n
        t += hop
        k += 1


# ------------------------------------------------------------------ checklist
def r_checklist(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    items = items_of(d, 'items')
    n = len(items)
    top, _ = scaffold(c, dur, ctx, d.get('title', ''), d.get('kicker', ''))
    labels = [s['label'] for s in items]
    times = schedule(n, dur, 0.55, 0.6, [s.get('at') for s in items], said_times(labels, ctx.words))
    cols = 2 if n > 4 else 1
    per = math.ceil(n / cols)
    col_w = 760 if cols == 2 else 1100
    avail = 1000 - top
    row_h = min(165, avail / per)
    x0 = (1920 - cols * col_w - (cols - 1) * 60) / 2
    y0 = top + (avail - per * row_h) / 2 - 20
    lab_size = min(P.fit_text(l, col_w - 150, (46, 42, 38, 34, 30, 28), 700, 1)[0] for l in labels)
    gid = c.uid('pchk')
    rows = []
    for k, s in enumerate(items):
        ci, ri = divmod(k, per)
        rtl = P.has_ar(s['label'])
        x, y = x0 + ci * (col_w + 60), y0 + ri * row_h
        rid, bid, chk = c.uid('pcr'), c.uid('pcb'), c.uid('pcc')
        box = (f'<div id="{bid}" style="width:58px;height:58px;flex:none;border-radius:16px;border:3px solid {th["line2"]};'
               f'display:flex;align-items:center;justify-content:center">'
               f'<svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">'
               f'<path id="{chk}" d="M5 12.5l4.5 4.5L19 7.5" pathLength="1" style="stroke-dasharray:1 1;stroke-dashoffset:1"/></svg></div>')
        txt = (f'<div class="pro-txt"{RTL if rtl else ""} style="font-size:{lab_size}px;font-weight:700">{P.bidi(s["label"])}'
               + (f'<div style="font-size:{max(20, int(lab_size * 0.6))}px;color:var(--pro-muted);font-weight:600;margin-top:4px">{P.bidi(s.get("sub", ""))}</div>' if s.get('sub') else '')
               + '</div>')
        rows.append((f'<div id="{rid}" class="pro-abs pro-card" style="left:{x:.0f}px;top:{y:.0f}px;width:{col_w}px;height:{row_h - 18:.0f}px;'
                     f'border-radius:20px;display:flex;align-items:center;gap:28px;padding:0 30px;box-sizing:border-box;'
                     f'flex-direction:{"row-reverse" if rtl else "row"}">{box}{txt}</div>', rid, bid, chk))
    c.clip(0, dur, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">' + ''.join(r[0] for r in rows) + '</div>', 3, cls='')
    _drift(c, gid, dur, 0.025)
    for k, (_, rid, bid, chk) in enumerate(rows):
        t = times[k]
        P.pop_in(c, rid, t - 0.35, 0.4, 0.96, 20, 'power3.out')
        c.at(f'tl.fromTo("#{bid}",{{background:"rgba(0,0,0,0)",borderColor:"{th["line2"]}"}},{{background:"{th["accent"]}",borderColor:"{th["accent"]}",duration:0.2,immediateRender:false}},{t:.4f});')
        c.at(f'tl.fromTo("#{chk}",{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:0.32,ease:"power2.out",immediateRender:false}},{t + 0.05:.4f});')
        c.at(f'tl.fromTo("#{bid}",{{scale:0.8}},{{scale:1,duration:0.4,ease:"back.out(2.4)",immediateRender:false}},{t:.4f});')
        sfx(c, t, 'click', 0.7)


# ------------------------------------------------------------------ compare
def r_compare(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    top, _ = scaffold(c, dur, ctx, d.get('title', ''), d.get('kicker', ''))
    L, R = d['left'], d['right']
    li, ri = [_item(x) for x in L['items']], [_item(x) for x in R['items']]
    n = len(li) + len(ri)
    times = schedule(n + 2, dur, 0.5, 0.62)
    pw, gap = 780, 120
    x0 = (1920 - 2 * pw - gap) / 2
    avail = 1000 - top
    rows_n = max(len(li), len(ri))
    ph = min(avail, 44 * 2 + 44 + 22 + 28 + rows_n * 108)
    y = top + (avail - ph) / 2 - 10
    gid = c.uid('pcmp')
    out = []

    def pane(x, side, its, good, t_title, t_items):
        pid = c.uid('ppane')
        col = th['good'] if good else th['bad']
        icon = 'check' if good else 'x'
        rtl = P.has_ar(side.get('title', '')) or any(P.has_ar(i['label']) for i in its)
        size = min([P.fit_text(i['label'], pw - 170, (36, 32, 30, 28, 26), 700, 2)[0] for i in its] or [32])
        rows, ids = [], []
        for it in its:
            iid = c.uid('pci')
            ids.append(iid)
            rows.append(f'<div id="{iid}" style="display:flex;align-items:center;gap:22px;flex-direction:{"row-reverse" if rtl else "row"};'
                        f'padding:20px 26px;border-radius:18px;background:rgba(255,255,255,0.045);border:1px solid {th["line"]}">'
                        f'<div style="width:48px;height:48px;flex:none;border-radius:50%;background:{P.rgba(col, 0.16)};display:flex;align-items:center;justify-content:center">'
                        f'{P.icon_svg(icon, 28, col, 3)}</div>'
                        f'<div class="pro-txt"{RTL if P.has_ar(it["label"]) else ""} style="font-size:{size}px;font-weight:700;line-height:1.2">{P.bidi(it["label"])}</div></div>')
        tt = side.get('title', '')
        head = (f'<div class="pro-txt"{RTL if P.has_ar(tt) else ""} style="font-size:44px;font-weight:800;padding-bottom:22px;'
                f'border-bottom:3px solid {col};margin-bottom:28px;text-align:{"right" if rtl else "left"}">{P.bidi(tt)}</div>')
        out.append(f'<div id="{pid}" class="pro-abs pro-card" style="left:{x:.0f}px;top:{y:.0f}px;width:{pw}px;height:{ph:.0f}px;'
                   f'padding:44px;box-sizing:border-box;display:flex;flex-direction:column;gap:18px;'
                   f'{"box-shadow:0 30px 90px rgba(0,0,0,.55),0 0 0 2px " + P.rgba(col, 0.35) + ";" if good else ""}">{head}{"".join(rows)}</div>')
        P.pop_in(c, pid, t_title, 0.5, 0.94, 40, 'power3.out')
        for k, iid in enumerate(ids):
            P.pop_in(c, iid, t_items[k], 0.35, 0.96, 16, 'power3.out')
            sfx(c, t_items[k], 'click_soft', 0.7)
        return pid

    pane(x0, L, li, False, times[0] - 0.2, times[1:1 + len(li)])
    rp = pane(x0 + pw + gap, R, ri, True, times[1 + len(li)] - 0.2, times[2 + len(li):])
    vs = c.uid('pvs')
    out.append(f'<div id="{vs}" class="pro-abs pro-ico" style="left:{960 - 56}px;top:{y + ph / 2 - 56:.0f}px;width:112px;height:112px;'
               f'font:900 34px/1 \'EV1 Sans\';color:#fff">{P.esc(d.get("vs", "VS"))}</div>')
    c.clip(0, dur, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">' + ''.join(out) + '</div>', 3, cls='')
    _drift(c, gid, dur, 0.025)
    P.pop_in(c, vs, times[0] + 0.3, 0.5, 0.3, 0, 'back.out(2.2)')
    sfx(c, times[0] + 0.3, 'click', 0.8)
    tw = times[-1] + 0.8
    if tw < dur - 0.6:
        c.at(f'tl.fromTo("#{rp}",{{scale:1}},{{scale:1.03,duration:0.5,ease:"back.out(2)",immediateRender:false}},{tw:.4f});')


# ------------------------------------------------------------------ stat
def _num_parts(v):
    m = re.match(r'^(.*?)(-?\d+(?:[.,]\d+)?)(.*)$', str(v).strip())
    if not m:
        return None
    pre, num, suf = m.groups()
    dec = len(num.split('.')[1]) if '.' in num else (len(num.split(',')[1]) if ',' in num else 0)
    return pre, float(num.replace(',', '.')), suf, dec, ',' in num


def r_stat(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    top, _ = scaffold(c, dur, ctx, d.get('title', ''), d.get('kicker', ''))
    gid, vid = c.uid('pstat'), c.uid('pval')
    val = str(d['value'])
    parts = _num_parts(val)
    small = d.get('items') or []
    avail = 1000 - top
    big = 260 if len(val) <= 4 else (210 if len(val) <= 7 else 160)
    cy = top + avail * (0.38 if small else 0.45)
    lab = d.get('label', '')
    lsize = P.fit_text(lab, 1400, (56, 50, 44, 40, 36), 700, 2)[0]
    html = [f'<div id="{vid}" class="pro-abs pro-txt pro-hl" style="left:0;top:{cy - big * 0.62:.0f}px;width:1920px;text-align:center;'
            f'font-size:{big}px;font-weight:900;line-height:1;letter-spacing:-0.04em">{P.esc(val)}</div>']
    lh, lids = P.text_block(c, lab, 260, cy + big * 0.5, 1400, lsize, 700, color=th['muted'])
    html.append(lh)
    if d.get('sub'):
        sh, sids = P.text_block(c, d['sub'], 360, cy + big * 0.5 + lsize * 1.4, 1200, int(lsize * 0.62), 600, color=th['faint'])
        html.append(sh)
    else:
        sids = []
    mids = []
    if small:
        k = len(small)
        cw = 400
        x0 = (1920 - k * cw - (k - 1) * 40) / 2
        for i, it in enumerate(small):
            mid = c.uid('pms')
            mids.append(mid)
            it = it if isinstance(it, dict) else {'value': str(it), 'label': ''}
            html.append(f'<div id="{mid}" class="pro-abs pro-card" style="left:{x0 + i * (cw + 40):.0f}px;top:{1000 - 190}px;width:{cw}px;height:150px;'
                        f'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px">'
                        f'<div class="pro-txt" style="font-size:54px;font-weight:900;color:{th["accent2"]}">{P.esc(it.get("value", ""))}</div>'
                        f'<div class="pro-txt"{RTL if P.has_ar(it.get("label", "")) else ""} style="font-size:24px;font-weight:600;color:var(--pro-muted)">{P.bidi(it.get("label", ""))}</div></div>')
    c.clip(0, dur, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">' + ''.join(html) + '</div>', 3, cls='')
    _drift(c, gid, dur, 0.03)
    P.pop_in(c, vid, 0.45, 0.6, 0.7, 30, 'back.out(1.5)')
    sfx(c, 0.45, 'hit', 0.8)
    if parts:
        pre, num, suf, dec, comma = parts
        cnt = min(1.6, dur * 0.3)
        c.pre.append(f'window.__pv_{vid}={{v:0}};')
        fmt = f'(o.v).toFixed({dec})' + ('.replace(".",",")' if comma else '')
        c.at(f'tl.fromTo(window.__pv_{vid},{{v:0}},{{v:{num},duration:{cnt:.3f},ease:"power2.out",immediateRender:false,'
             f'onUpdate:function(){{var o=window.__pv_{vid};document.getElementById("{vid}").textContent={json.dumps(pre)}+{fmt}+{json.dumps(suf)};}}}},0.45);')
    P.reveal_words(c, lids, 0.9, 0.05)
    if sids:
        P.reveal_words(c, sids, 1.2, 0.04)
    for i, mid in enumerate(mids):
        P.pop_in(c, mid, 1.4 + i * 0.25, 0.45, 0.9, 30, 'back.out(1.6)')
        sfx(c, 1.4 + i * 0.25, 'click_soft', 0.8)


# ------------------------------------------------------------------ statement
def r_statement(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    P.pro_css(c, th)
    P.backdrop(c, 0, dur, th, ctx.bg, z=1, grain_src=ctx.grain)
    text = d['text']
    gid = c.uid('pstm')
    size, lines = P.fit_text(text, 1500, (110, 96, 86, 76, 68, 60, 54), 800, 3)
    hgt = len(lines) * size * 1.12
    icon = d.get('icon')
    ih = 170 if icon else 0
    y = (1080 - hgt - ih) / 2 + ih
    html, ids = P.text_block(c, text, 210, y, 1500, size, 800)
    parts = [html]
    iid = None
    if icon:
        iid = c.uid('psi')
        parts.append(f'<div id="{iid}" class="pro-abs pro-ico" style="left:{960 - 60}px;top:{y - 170:.0f}px;width:120px;height:120px">'
                     f'{P.icon_svg(icon, 64, "#fff", 1.8)}</div>')
    sids = []
    if d.get('sub'):
        sh, sids = P.text_block(c, d['sub'], 360, y + hgt + 34, 1200, max(30, int(size * 0.36)), 600, color=th['muted'])
        parts.append(sh)
    if d.get('kicker'):
        kid = c.uid('pk')
        parts.append(f'<div id="{kid}" class="pro-abs pro-kicker" style="left:0;top:{y - ih - 70:.0f}px;width:1920px;text-align:center">{P.bidi(d["kicker"])}</div>')
        P.pop_in(c, kid, 0.15, 0.4, 1.0, 12, 'power3.out')
    c.clip(0, dur, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">' + ''.join(parts) + '</div>', 3, cls='')
    _drift(c, gid, dur, 0.045)
    if iid:
        P.pop_in(c, iid, 0.2, 0.55, 0.4, 0, 'back.out(2)')
    end = P.reveal_words(c, ids, 0.35, max(0.05, min(0.12, (dur * 0.45) / max(1, len(ids)))), 0.5, 40, 16)
    sfx(c, 0.35, 'click_soft', 0.8)
    if sids:
        P.reveal_words(c, sids, end + 0.1, 0.04)


# ------------------------------------------------------------------ screens
def r_screens(c, ins, d, ctx):
    dur, th = ins['dur'], ctx.th
    top, _ = scaffold(c, dur, ctx, d.get('title', ''), d.get('kicker', ''))
    shots = d['shots'][:3]
    k = len(shots)
    gid = c.uid('pscr')
    avail = 1000 - top
    sw = {1: 1300, 2: 860, 3: 640}[k]
    sh = sw * 9 / 16
    gap = {1: 0, 2: 40, 3: -20}[k]
    x0 = (1920 - k * sw - (k - 1) * gap) / 2
    y = top + (avail - sh - 80) / 2
    rot = {1: [0], 2: [7, -7], 3: [10, 0, -10]}[k]
    parts, ids = [], []
    times = schedule(k, dur, 0.5, 0.45)
    for i, s in enumerate(shots):
        sid, lid = c.uid('pss'), c.uid('psl')
        ids.append((sid, lid))
        src = ctx.still(float(s['src_t']))
        lab = s.get('label', '')
        parts.append(f'<div id="{sid}" class="pro-shot" style="left:{x0 + i * (sw + gap):.0f}px;top:{y:.0f}px;width:{sw}px;height:{sh:.0f}px;'
                     f'transform:perspective(1800px) rotateY({rot[i]}deg)"><img src="{P.esc(src)}" style="width:100%;height:100%;object-fit:cover"></div>')
        if lab:
            parts.append(f'<div class="pro-abs" style="left:{x0 + i * (sw + gap):.0f}px;top:{y + sh + 34:.0f}px;width:{sw}px;display:flex;justify-content:center">'
                         + P.chip_html(lid, lab, s.get('icon') or P.guess_icon(lab), th, f'{i + 1:02d}', 28, 40) + '</div>')
        else:
            ids[-1] = (sid, None)
    c.clip(0, dur, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">' + ''.join(parts) + '</div>', 3, cls='')
    _drift(c, gid, dur, 0.04)
    for i, (sid, lid) in enumerate(ids):
        P.pop_in(c, sid, times[i], 0.6, 0.85, 80, 'power3.out')
        sfx(c, times[i], 'click_soft', 0.8)
        if lid:
            P.pop_in(c, lid, times[i] + 0.25, 0.4, 0.8, 10, 'back.out(1.8)')


BUILDERS = {'flow': r_flow, 'steps': r_steps, 'checklist': r_checklist, 'compare': r_compare,
            'stat': r_stat, 'statement': r_statement, 'screens': r_screens}


def build(c, ins, entry, ctx):
    probs = validate(entry)
    if probs:
        raise ValueError('; '.join(probs))
    BUILDERS[entry['recipe']](c, ins, entry.get('data') or {}, ctx)
