"""ev2_tutorial.py — Editor V2 tutorial devices library.

Extends the 38 Editor V1 devices (ev1_devices + ev1_more) with 7 tutorial-specific devices
and the Omarchy corner webcam overlay helper:
1. screen_zoom: dynamic zoom into screen regions with optional spotlight highlight & webcam pinning
2. shortcut_pill & cmd_toast: keyboard shortcut glass pills & typed CLI command toasts
3. chapter_banner: YouTube chapter sync + full-screen title card or sleek lower-third
4. flow_diagram: animated architectural node graph with glowing edges & SVG arrows
5. split_compare: split-screen side-by-side comparison with staggered bullet reveals
6. omarchy_cam_pip: Omarchy 8:9 corner webcam crop and pin card

All text rendering natively supports Moroccan Darija RTL BiDi (dir="rtl", <bdi>).
Import this for every device: `from ev2_tutorial import *` (catalogue: reference/devices.md).
"""
import sys, math, random, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ev1_more import *          # noqa: Brings in all Editor V1 devices + Comp, fr, dstr, esc, has_arabic, bidi_span, sfx, FPS, W, H, F1


def bidi_text(text):
    """Format a string that may mix Arabic (Moroccan Darija) and Latin tech words.
    Wraps Latin words in <bdi> if the string contains Arabic characters.
    """
    if not has_arabic(text):
        return esc(str(text))
    tokens = str(text).split(' ')
    res = []
    for tok in tokens:
        if has_arabic(tok):
            res.append(esc(tok))
        else:
            res.append(f'<bdi>{esc(tok)}</bdi>')
    return ' '.join(res)


# ------------------------------------------------------------------ 1. SCREEN ZOOM
def screen_zoom(c, t0, t1, src, roi, z=1, media_start=0.0, zoom_in_frames=8, zoom_out_frames=8, highlight_box=None, webcam_box=None):
    """Dynamic camera zoom into a region of interest (ROI) on a tutorial screencast or code editor.

    roi = (x, y, w, h) in 1920x1080 coordinates.
    scale = min(2.6, 1920 / w, 1080 / h).
    transform-origin = center of roi.
    GSAP zooms from 1.0 -> scale over zoom_in_frames, holds, then returns to 1.0 over zoom_out_frames.
    If highlight_box=(hx, hy, hw, hh): animates a pulsing spotlight/accent box around that element.
    If webcam_box=(wx, wy, ww, wh): renders a pinned rounded corner webcam PiP overlay at z + 2
      so zooming into screen does not obscure or distort the speaker's face.
    """
    t0, t1 = fr(t0), fr(t1)
    dur = t1 - t0
    x, y, w, h = roi
    scale = min(2.6, 1920.0 / max(1, w), 1080.0 / max(1, h))
    cx = (x + w / 2.0) / 1920.0 * 100.0
    cy = (y + h / 2.0) / 1080.0 * 100.0

    tin = max(F1, zoom_in_frames / FPS)
    tout = max(0.0, zoom_out_frames / FPS)

    is_video = not src.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif'))

    # Base screencast layer
    if is_video:
        vid = c.uid('szv')
        c.els.append(f'<video id="{vid}" class="clip ev1-fill" src="{src}" muted playsinline '
                     f'data-start="{t0:.4f}" data-duration="{dstr(t0, t1)}" data-media-start="{media_start:.4f}" '
                     f'style="z-index:{z};transform-origin:{cx:.2f}% {cy:.2f}%"></video>')
    else:
        vid = c.uid('szi')
        c.clip(t0, t1, f'<img id="{vid}" src="{src}" class="ev1-fill" style="transform-origin:{cx:.2f}% {cy:.2f}%">', z)

    # Zoom in animation
    c.pre.append(f'gsap.set("#{vid}",{{scale:1.0,transformOrigin:"{cx:.2f}% {cy:.2f}%"}});')
    c.at(f'tl.fromTo("#{vid}",{{scale:1.0}},{{scale:{scale:.4f},duration:{tin:.4f},ease:"power2.out",immediateRender:false}},{t0:.4f});')

    # Zoom out animation
    if tout > 0:
        t_out = max(t0 + tin, t1 - tout)
        c.at(f'tl.fromTo("#{vid}",{{scale:{scale:.4f}}},{{scale:1.0,duration:{tout:.4f},ease:"power2.inOut",immediateRender:false}},{t_out:.4f});')

    # Sound cue on zoom onset
    sfx(c, t0, 'click_soft')

    # Optional highlight box (zoomed in lockstep)
    if highlight_box:
        hx, hy, hw, hh = highlight_box
        hl_layer_id = c.uid('szhl')
        hl_box_id = c.uid('szbox')
        hl_html = (f'<div id="{hl_layer_id}" style="position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none;transform-origin:{cx:.2f}% {cy:.2f}%">'
                   f'<div id="{hl_box_id}" style="position:absolute;left:{hx}px;top:{hy}px;width:{hw}px;height:{hh}px;'
                   f'border:3px solid var(--ev1-marker);border-radius:10px;box-shadow:0 0 24px rgba(255,224,74,0.7), inset 0 0 12px rgba(255,224,74,0.3);'
                   f'opacity:0;pointer-events:none"></div></div>')
        c.clip(t0, t1, hl_html, z + 1, cls='', style='position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none')

        c.pre.append(f'gsap.set("#{hl_layer_id}",{{scale:1.0,transformOrigin:"{cx:.2f}% {cy:.2f}%"}});')
        c.at(f'tl.fromTo("#{hl_layer_id}",{{scale:1.0}},{{scale:{scale:.4f},duration:{tin:.4f},ease:"power2.out",immediateRender:false}},{t0:.4f});')
        if tout > 0:
            c.at(f'tl.fromTo("#{hl_layer_id}",{{scale:{scale:.4f}}},{{scale:1.0,duration:{tout:.4f},ease:"power2.inOut",immediateRender:false}},{t_out:.4f});')

        c.pre.append(f'gsap.set("#{hl_box_id}",{{opacity:0}});')
        c.at(f'tl.fromTo("#{hl_box_id}",{{opacity:0}},{{opacity:1,duration:0.18,ease:"power2.out",immediateRender:false}},{t0 + tin * 0.7:.4f});')
        if tout > 0:
            c.at(f'tl.fromTo("#{hl_box_id}",{{opacity:1}},{{opacity:0,duration:{tout:.4f},ease:"power2.in",immediateRender:false}},{t_out:.4f});')

    # Optional pinned webcam PiP overlay at z + 2
    if webcam_box:
        omarchy_cam_pip(c, t0, t1, src, media_start=media_start, webcam_box=webcam_box, z=z + 2)

    return vid


# ------------------------------------------------------------------ 2. SHORTCUT PILL & CMD TOAST
def shortcut_pill(c, t0, t1, keys, label='', z=65, x=960, y=920):
    """Sleek dark glass keyboard shortcut pill with keycaps joined by '+' and spring pop-in.

    keys = ['Super', 'Shift', 'R'] or 'Super + Shift + R'.
    label = optional text description (supports Moroccan Darija RTL & English).
    Triggers 'key_click' SFX at t0.
    """
    t0, t1 = fr(t0), fr(t1)
    if isinstance(keys, str):
        key_list = [k.strip() for k in keys.split('+')]
    else:
        key_list = [str(k).strip() for k in keys]

    keycaps = [f'<kbd class="key">{esc(k)}</kbd>' for k in key_list]
    sep = '<span style="color:rgba(255,255,255,0.45);font-size:22px;margin:0 4px;font-weight:400">+</span>'
    keys_markup = sep.join(keycaps)

    if label:
        is_ar = has_arabic(label)
        if is_ar:
            label_markup = f'<span class="pill-lbl" dir="rtl" style="font-family:var(--ev2-arabic),var(--ev1-sans);color:#E5E7EB;font-size:24px;font-weight:600;margin-right:12px">{bidi_text(label)}</span>'
            content = f'{label_markup}{keys_markup}'
        else:
            label_markup = f'<span class="pill-lbl" style="font-family:var(--ev1-sans);color:#E5E7EB;font-size:24px;font-weight:600;margin-left:12px">{esc(label)}</span>'
            content = f'{keys_markup}{label_markup}'
    else:
        content = keys_markup

    pid = c.uid('spill')
    pill_box = (f'<div style="position:absolute;left:{x}px;top:{y}px;transform:translate(-50%, -50%);pointer-events:none">'
                f'<div id="{pid}" class="ev2-pill" style="position:relative">{content}</div></div>')
    c.clip(t0, t1, pill_box, z, cls='', style='position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none')

    c.pre.append(f'gsap.set("#{pid}",{{scale:0.85,opacity:0}});')
    c.at(f'tl.fromTo("#{pid}",{{scale:0.85,opacity:0}},{{scale:1.0,opacity:1,duration:0.2,ease:"back.out(1.7)",immediateRender:false}},{t0:.4f});')

    t_out = max(t0 + 0.25, t1 - 0.18)
    c.at(f'tl.fromTo("#{pid}",{{opacity:1,scale:1.0}},{{opacity:0,scale:0.92,duration:0.18,ease:"power2.in",immediateRender:false}},{t_out:.4f});')

    sfx(c, t0, 'key_click')
    return pid


def cmd_toast(c, t0, t1, cmd, z=65, y=900):
    """Floating terminal prompt toast with command typing animation and keystroke SFX.

    cmd = '$ agy implement-feature' or 'git status'.
    Pops in, types over 6-12 frames, and plays 'key_click' SFX.
    """
    t0, t1 = fr(t0), fr(t1)
    cmd_str = str(cmd)
    if cmd_str.startswith('$ '):
        prompt_icon = '$'
        cmd_text = cmd_str[2:]
    elif cmd_str.startswith('$'):
        prompt_icon = '$'
        cmd_text = cmd_str[1:].strip()
    else:
        prompt_icon = '$'
        cmd_text = cmd_str

    tid = c.uid('toast')
    typing_frames = min(12, max(6, len(cmd_text)))
    step_f = typing_frames / max(1, len(cmd_text))
    t_start = t0 + 3 / FPS

    chars_spans = []
    for j, ch in enumerate(cmd_text):
        sid = c.uid('tch')
        chars_spans.append(f'<span id="{sid}" style="opacity:0">{esc(ch)}</span>')
        c.at(f'tl.set("#{sid}",{{opacity:1}},{t_start + (j * step_f) / FPS:.4f});')

    cur_id = c.uid('tcur')
    cur_html = f'<span id="{cur_id}" class="ev1-cursor" style="display:inline-block;width:3px;height:28px;background:var(--ev1-marker);vertical-align:-4px;margin-left:4px"></span>'

    toast_html = (f'<div style="position:absolute;left:50%;top:{y}px;transform:translate(-50%, -50%);pointer-events:none">'
                  f'<div id="{tid}" class="ev2-toast" style="position:relative">'
                  f'<span class="icon">{esc(prompt_icon)}</span>'
                  f'<span class="cmd" style="font-family:var(--ev1-mono);color:#9CC7FF;white-space:nowrap">{"".join(chars_spans)}{cur_html}</span>'
                  f'</div></div>')
    c.clip(t0, t1, toast_html, z, cls='', style='position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none')

    c.pre.append(f'gsap.set("#{tid}",{{scale:0.9,opacity:0}});')
    c.at(f'tl.fromTo("#{tid}",{{scale:0.9,opacity:0}},{{scale:1.0,opacity:1,duration:0.16,ease:"back.out(1.5)",immediateRender:false}},{t0:.4f});')

    t_out = max(t0 + 0.3, t1 - 0.18)
    c.at(f'tl.fromTo("#{tid}",{{opacity:1,scale:1.0}},{{opacity:0,scale:0.92,duration:0.18,ease:"power2.in",immediateRender:false}},{t_out:.4f});')

    sfx(c, t0, 'key_click')
    return tid


# ------------------------------------------------------------------ 3. CHAPTER BANNER
def chapter_banner(c, t0, t1, number, title, subtitle='', z=70, style='card'):
    """Chapter transition banner that automatically syncs with c.chapters for YouTube chapters.

    style = 'card': Full-screen chapter title card with metallic chapter number, large BiDi
                    title (Cairo / Serif), subtle subtitle, animated accent bar, swish & hit SFX.
    style = 'lower_third': Non-intrusive animated glass card overlaying screencast in corner,
                           with slide-in/out and click_soft SFX.
    """
    t0, t1 = fr(t0), fr(t1)
    chapter_entry = f"{number} {title}" if number else title
    c.chapters.append((t0, chapter_entry))

    is_ar = has_arabic(title) or has_arabic(subtitle)
    num_str = str(number).strip() if number is not None else ''

    if style == 'card':
        bid = c.uid('chc')
        barid = c.uid('chbar')

        num_html = (f'<div class="num" style="font:800 32px/1 var(--ev1-mono);color:var(--ev1-marker);letter-spacing:0.18em;text-transform:uppercase;margin-bottom:18px">'
                    f'{esc(num_str)}</div>') if num_str else ''

        if is_ar:
            title_html = f'<div dir="rtl" style="font:700 72px/1.2 var(--ev2-arabic);color:var(--ev1-white);letter-spacing:-0.01em;text-align:center">{bidi_text(title)}</div>'
        else:
            title_html = f'<div class="ev1-title" style="font-size:76px;line-height:1.1;text-align:center">{esc(title)}</div>'

        bar_html = f'<div id="{barid}" style="width:140px;height:4px;background:var(--ev1-marker);box-shadow:0 0 16px rgba(255,224,74,0.6);margin:24px auto;border-radius:2px"></div>'

        sub_html = ''
        if subtitle:
            sub_dir = ' dir="rtl"' if has_arabic(subtitle) else ''
            sub_font = 'var(--ev2-arabic)' if has_arabic(subtitle) else 'var(--ev1-sans)'
            sub_html = f'<div{sub_dir} style="font:500 28px/1.4 {sub_font};color:rgba(255,255,255,0.72);margin-top:12px;text-align:center">{bidi_text(subtitle)}</div>'

        card_html = (f'<div class="ev1-layer ev1-black"><div class="ev1-vignette"></div>'
                     f'<div id="{bid}" style="position:absolute;left:50%;top:50%;transform:translate(-50%, -50%);width:1600px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center">'
                     f'{num_html}{title_html}{bar_html}{sub_html}</div></div>')
        c.clip(t0, t1, card_html, z)

        sfx(c, t0, 'swish')
        sfx(c, t0 + 0.16, 'hit')

        c.pre.append(f'gsap.set("#{bid}",{{opacity:0,scale:0.92,filter:"blur(16px)"}});')
        c.pre.append(f'gsap.set("#{barid}",{{scaleX:0}});')

        c.at(f'tl.fromTo("#{bid}",{{opacity:0,scale:0.92,filter:"blur(16px)"}},{{opacity:1,scale:1.0,filter:"blur(0px)",duration:0.35,ease:"power2.out",immediateRender:false}},{t0 + 0.1:.4f});')
        c.at(f'tl.fromTo("#{barid}",{{scaleX:0}},{{scaleX:1.0,duration:0.4,ease:"power2.out",immediateRender:false}},{t0 + 0.2:.4f});')

        d_hold = t1 - (t0 + 0.45)
        if d_hold > 0:
            c.at(f'tl.fromTo("#{bid}",{{scale:1.0}},{{scale:1.03,duration:{d_hold:.4f},ease:"none",immediateRender:false}},{t0 + 0.45:.4f});')

        t_out = max(t0 + 0.5, t1 - 0.22)
        c.at(f'tl.fromTo("#{bid}",{{opacity:1}},{{opacity:0,filter:"blur(8px)",duration:0.22,ease:"power2.in",immediateRender:false}},{t_out:.4f});')
        return bid

    else:
        # style == 'lower_third'
        lt_id = c.uid('chlt')
        num_html = f'<div class="num">{esc(num_str)}</div>' if num_str else ''
        title_font = 'var(--ev2-arabic)' if is_ar else 'var(--ev1-sans)'
        title_dir = ' dir="rtl"' if is_ar else ''
        title_html = f'<div class="title"{title_dir} style="font-family:{title_font}">{bidi_text(title)}</div>'

        sub_html = ''
        if subtitle:
            sub_dir = ' dir="rtl"' if has_arabic(subtitle) else ''
            sub_font = 'var(--ev2-arabic)' if has_arabic(subtitle) else 'var(--ev1-sans)'
            sub_html = f'<div{sub_dir} style="font:500 22px {sub_font};color:#B0B7C3">{bidi_text(subtitle)}</div>'

        if is_ar:
            pos_style = 'right:80px;top:100px;border-right:6px solid var(--ev1-red);border-left:none;direction:rtl;text-align:right;'
            slide_from = 'x:80'
        else:
            pos_style = 'left:80px;top:100px;border-left:6px solid var(--ev1-red);'
            slide_from = 'x:-80'

        inner = (f'<div id="{lt_id}" class="ev2-chapter" style="{pos_style}">'
                 f'{num_html}{title_html}{sub_html}</div>')
        c.clip(t0, t1, inner, z, cls='', style='position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none')

        c.pre.append(f'gsap.set("#{lt_id}",{{{slide_from},opacity:0}});')
        c.at(f'tl.fromTo("#{lt_id}",{{{slide_from},opacity:0}},{{x:0,opacity:1,duration:0.28,ease:"power3.out",immediateRender:false}},{t0:.4f});')

        t_out = max(t0 + 0.35, t1 - 0.22)
        c.at(f'tl.fromTo("#{lt_id}",{{x:0,opacity:1}},{{{slide_from},opacity:0,duration:0.22,ease:"power3.in",immediateRender:false}},{t_out:.4f});')

        sfx(c, t0, 'click_soft')
        return lt_id


# ------------------------------------------------------------------ 4. FLOW DIAGRAM
def flow_diagram(c, t0, t1, nodes, edges=(), z=10, title=''):
    """Architectural node graph with dark glass cards, glowing borders, SVG arrows, and BiDi labels.

    nodes = [('id1', 'Omarchy Screencast', 360, 540), ('id2', 'Faster-Whisper INT8', 960, 540), ...]
    edges = [('id1', 'id2', 0.3), ('id2', 'id3', 0.7)]
    title = optional top header title.
    Nodes pop in on onset with 'click' SFX.
    """
    t0, t1 = fr(t0), fr(t1)
    gid = c.uid('flow')

    parsed_nodes = []
    node_pos = {}
    for k, n in enumerate(nodes):
        if isinstance(n, dict):
            nid = str(n['id'])
            label = n.get('label', '')
            x, y = n['x'], n['y']
            onset = n.get('onset', k * 0.16)
        elif len(n) == 4:
            nid, label, x, y = str(n[0]), n[1], n[2], n[3]
            onset = k * 0.16
        elif len(n) >= 5:
            nid, label, x, y, onset = str(n[0]), n[1], n[2], n[3], n[4]
        else:
            nid, label, x, y = str(n[0]), n[1], n[2], n[3]
            onset = k * 0.16
        parsed_nodes.append((nid, label, x, y, onset))
        node_pos[nid] = (x, y)

    # SVG arrows
    svg_arrows = [
        '<svg style="position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none;z-index:25">',
        '<defs><marker id="ev2-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="rgba(255,255,255,0.7)"/></marker></defs>'
    ]

    edge_entries = []
    for ed in edges:
        u, v = str(ed[0]), str(ed[1])
        ed_onset = ed[2] if len(ed) > 2 else 0.25
        if u in node_pos and v in node_pos:
            x1, y1 = node_pos[u]
            x2, y2 = node_pos[v]
            # Offset endpoints toward edges of cards
            dx, dy = x2 - x1, y2 - y1
            dist = math.hypot(dx, dy) or 1
            ox1 = x1 + (dx / dist) * 110
            oy1 = y1 + (dy / dist) * 45
            ox2 = x2 - (dx / dist) * 110
            oy2 = y2 - (dy / dist) * 45
            eid = c.uid('farr')
            svg_arrows.append(f'<path id="{eid}" d="M {ox1:.1f} {oy1:.1f} L {ox2:.1f} {oy2:.1f}" '
                              f'stroke="rgba(255,255,255,0.4)" stroke-width="3" stroke-dasharray="6 4" '
                              f'marker-end="url(#ev2-arr)" fill="none" opacity="0"/>')
            edge_entries.append((eid, ed_onset))
    svg_arrows.append('</svg>')

    # Node cards HTML
    node_cards = []
    node_dom_ids = []
    for nid, label, x, y, onset in parsed_nodes:
        dom_nid = c.uid('fnode')
        node_dom_ids.append((dom_nid, onset))
        is_ar = has_arabic(label)
        n_dir = ' dir="rtl"' if is_ar else ''
        n_font = 'var(--ev2-arabic)' if is_ar else 'var(--ev1-sans)'
        node_cards.append(
            f'<div id="{dom_nid}" class="ev2-flow-node"{n_dir} '
            f'style="left:{x}px;top:{y}px;transform:translate(-50%, -50%);font-family:{n_font};opacity:0">'
            f'{bidi_text(label)}</div>'
        )

    title_html = ''
    if title:
        t_ar = has_arabic(title)
        t_dir = ' dir="rtl"' if t_ar else ''
        t_font = 'var(--ev2-arabic)' if t_ar else 'var(--ev1-sans)'
        title_html = (f'<div{t_dir} style="position:absolute;left:0;top:80px;width:1920px;text-align:center;'
                      f'font:700 42px/1.2 {t_font};color:var(--ev1-white);letter-spacing:-0.02em;'
                      f'text-shadow:0 4px 20px rgba(0,0,0,0.6)">{bidi_text(title)}</div>')

    inner = (f'<div class="ev1-layer ev1-black"><div class="ev1-vignette"></div>'
             f'{title_html}{"".join(svg_arrows)}{"".join(node_cards)}</div>')
    c.clip(t0, t1, inner, z, cid=gid)

    # Animate nodes
    for dom_nid, onset in node_dom_ids:
        tn = t0 + onset
        c.pre.append(f'gsap.set("#{dom_nid}",{{scale:0.75,opacity:0}});')
        c.at(f'tl.fromTo("#{dom_nid}",{{scale:0.75,opacity:0}},{{scale:1.0,opacity:1,duration:0.25,ease:"back.out(1.5)",immediateRender:false}},{tn:.4f});')
        sfx(c, tn, 'click')

    # Animate edges
    for eid, ed_onset in edge_entries:
        te = t0 + ed_onset
        c.pre.append(f'gsap.set("#{eid}",{{opacity:0}});')
        c.at(f'tl.fromTo("#{eid}",{{opacity:0}},{{opacity:1,duration:0.2,ease:"power2.out",immediateRender:false}},{te:.4f});')
        sfx(c, te, 'click_soft')

    return gid


# ------------------------------------------------------------------ 5. SPLIT COMPARE
def split_compare(c, t0, t1, left, right, z=10, vs_label='VS'):
    """Side-by-side comparison screen with animated slide-in, center badge, and staggered bullets.

    left = {'title': 'Before / Manuel', 'items': ['Cutting silence by hand', 'Misheard English terms'], 'accent': '#FF5252'}
    right = {'title': 'Editor V2', 'items': ['Auto silence + retake trim', 'Darija + Tech dictionary'], 'accent': '#4ADE80'}
    vs_label = center badge text ('VS').
    """
    t0, t1 = fr(t0), fr(t1)
    gid = c.uid('split')
    lid = c.uid('spltl')
    rid = c.uid('spltr')
    vs_id = c.uid('vs')

    l_acc = left.get('accent', '#FF5252')
    r_acc = right.get('accent', '#4ADE80')

    l_title = left.get('title', '')
    r_title = right.get('title', '')
    l_items = left.get('items', [])
    r_items = right.get('items', [])

    # Format left items
    l_item_html = []
    l_ids = []
    for it in l_items:
        iid = c.uid('lbi')
        l_ids.append(iid)
        is_ar = has_arabic(it)
        i_dir = ' dir="rtl"' if is_ar else ''
        i_font = 'var(--ev2-arabic)' if is_ar else 'var(--ev1-sans)'
        icon = f'<span style="color:{l_acc};font-weight:900;font-size:26px;margin:0 12px">&#10005;</span>'
        content = f'{icon}<span>{bidi_text(it)}</span>' if not is_ar else f'<span>{bidi_text(it)}</span>{icon}'
        l_item_html.append(
            f'<div id="{iid}"{i_dir} style="display:flex;align-items:center;padding:16px 20px;border-radius:10px;'
            f'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);font:600 26px/1.3 {i_font};'
            f'color:var(--ev1-white);opacity:0">{content}</div>'
        )

    # Format right items
    r_item_html = []
    r_ids = []
    for it in r_items:
        iid = c.uid('rbi')
        r_ids.append(iid)
        is_ar = has_arabic(it)
        i_dir = ' dir="rtl"' if is_ar else ''
        i_font = 'var(--ev2-arabic)' if is_ar else 'var(--ev1-sans)'
        icon = f'<span style="color:{r_acc};font-weight:900;font-size:26px;margin:0 12px">&#10003;</span>'
        content = f'{icon}<span>{bidi_text(it)}</span>' if not is_ar else f'<span>{bidi_text(it)}</span>{icon}'
        r_item_html.append(
            f'<div id="{iid}"{i_dir} style="display:flex;align-items:center;padding:16px 20px;border-radius:10px;'
            f'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);font:600 26px/1.3 {i_font};'
            f'color:var(--ev1-white);opacity:0">{content}</div>'
        )

    # Left pane header
    lt_ar = has_arabic(l_title)
    lt_dir = ' dir="rtl"' if lt_ar else ''
    lt_font = 'var(--ev2-arabic)' if lt_ar else 'var(--ev1-sans)'
    left_header = (f'<div{lt_dir} style="font:800 38px/1.2 {lt_font};color:var(--ev1-white);letter-spacing:-0.02em;'
                   f'border-bottom:3px solid {l_acc};padding-bottom:14px;margin-bottom:32px;display:inline-block">'
                   f'{bidi_text(l_title)}</div>')

    # Right pane header
    rt_ar = has_arabic(r_title)
    rt_dir = ' dir="rtl"' if rt_ar else ''
    rt_font = 'var(--ev2-arabic)' if rt_ar else 'var(--ev1-sans)'
    right_header = (f'<div{rt_dir} style="font:800 38px/1.2 {rt_font};color:var(--ev1-white);letter-spacing:-0.02em;'
                    f'border-bottom:3px solid {r_acc};padding-bottom:14px;margin-bottom:32px;display:inline-block">'
                    f'{bidi_text(r_title)}</div>')

    inner = (
        f'<div class="ev1-layer ev1-black"><div class="ev1-vignette"></div>'
        f'<div class="ev2-split">'
        f'<div id="{lid}" class="ev2-split-pane" style="background:linear-gradient(180deg,#160C0F 0%,#0C0708 100%);padding:140px 80px 80px 100px;box-sizing:border-box">'
        f'{left_header}<div style="display:flex;flex-direction:column;gap:18px">{"".join(l_item_html)}</div></div>'
        f'<div id="{rid}" class="ev2-split-pane" style="background:linear-gradient(180deg,#09160E 0%,#050C07 100%);padding:140px 100px 80px 80px;box-sizing:border-box">'
        f'{right_header}<div style="display:flex;flex-direction:column;gap:18px">{"".join(r_item_html)}</div></div>'
        f'</div>'
        f'<div class="ev2-split-divider" style="left:50%;transform:translateX(-50%)"></div>'
        f'<div id="{vs_id}" style="position:absolute;left:50%;top:50%;transform:translate(-50%, -50%);width:76px;height:76px;border-radius:50%;background:#121214;border:3px solid var(--ev1-white);display:flex;align-items:center;justify-content:center;font:900 24px var(--ev1-sans);color:var(--ev1-white);box-shadow:0 0 28px rgba(0,0,0,0.85);z-index:30">'
        f'{esc(vs_label)}</div></div>'
    )
    c.clip(t0, t1, inner, z, cid=gid)

    # Animate panels sliding in
    c.pre.append(f'gsap.set("#{lid}",{{x:-960,opacity:0}});')
    c.pre.append(f'gsap.set("#{rid}",{{x:960,opacity:0}});')
    c.pre.append(f'gsap.set("#{vs_id}",{{scale:0,opacity:0}});')

    c.at(f'tl.fromTo("#{lid}",{{x:-960,opacity:0}},{{x:0,opacity:1,duration:0.35,ease:"power3.out",immediateRender:false}},{t0:.4f});')
    c.at(f'tl.fromTo("#{rid}",{{x:960,opacity:0}},{{x:0,opacity:1,duration:0.35,ease:"power3.out",immediateRender:false}},{t0:.4f});')
    c.at(f'tl.fromTo("#{vs_id}",{{scale:0,opacity:0}},{{scale:1,opacity:1,duration:0.25,ease:"back.out(2)",immediateRender:false}},{t0 + 0.15:.4f});')

    # Stagger bullets
    base_t = t0 + 0.35
    for k, iid in enumerate(l_ids):
        tb = base_t + k * 0.18
        c.pre.append(f'gsap.set("#{iid}",{{x:-30,opacity:0}});')
        c.at(f'tl.fromTo("#{iid}",{{x:-30,opacity:0}},{{x:0,opacity:1,duration:0.2,ease:"power2.out",immediateRender:false}},{tb:.4f});')
        sfx(c, tb, 'click_soft')

    r_base_t = base_t + len(l_ids) * 0.18
    for k, iid in enumerate(r_ids):
        tb = r_base_t + k * 0.18
        c.pre.append(f'gsap.set("#{iid}",{{x:30,opacity:0}});')
        c.at(f'tl.fromTo("#{iid}",{{x:30,opacity:0}},{{x:0,opacity:1,duration:0.2,ease:"power2.out",immediateRender:false}},{tb:.4f});')
        sfx(c, tb, 'click_soft')

    return gid


# ------------------------------------------------------------------ 6. OMARCHY WEBCAM PIP
def omarchy_cam_pip(c, t0, t1, src, media_start=0.0, webcam_box=(1380, 500, 480, 540), z=50, style='', is_cropped=False):
    """Crops and pins the Omarchy 8:9 webcam region as a clean rounded card with subtle shadow and border.

    webcam_box = (wx, wy, ww, wh) where default matches Omarchy medium overlay at 1920x1080.
    src = full screencast video (is_cropped=False) or extracted cam crop (is_cropped=True).
    Returns (container_id, video_id).
    """
    wx, wy, ww, wh = webcam_box
    t0, t1 = fr(t0), fr(t1)
    cid = c.uid('omcam')
    vid = c.uid('omcamv')

    card_style = (f"position:absolute;left:{wx}px;top:{wy}px;width:{ww}px;height:{wh}px;"
                  f"border-radius:18px;overflow:hidden;box-shadow:0 16px 48px rgba(0,0,0,0.65);"
                  f"border:2px solid rgba(255,255,255,0.22);background:#000;z-index:{z};{style}")

    if is_cropped:
        video_style = "position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover;display:block"
    else:
        video_style = f"position:absolute;left:{-wx}px;top:{-wy}px;width:1920px;height:1080px;max-width:none;display:block"

    # The card is an untimed wrapper (HyperFrames: never time a wrapper AND its video); it is hidden
    # by default and shown only for [t0, t1) by the timeline, or the empty card stays on screen.
    c.at(f'tl.set("#{cid}",{{visibility:"visible"}},{t0:.4f});tl.set("#{cid}",{{visibility:"hidden"}},{t1:.4f});')
    c.els.append(
        f'<div id="{cid}" style="{card_style};visibility:hidden">'
        f'<video id="{vid}" class="clip" src="{src}" muted playsinline '
        f'data-start="{t0:.4f}" data-duration="{dstr(t0, t1)}" data-media-start="{media_start:.4f}" '
        f'style="{video_style}"></video>'
        f'</div>'
    )
    return cid, vid
