"""ev2_hook.py — the automatic "pro" hook: a designed opening built from work/hook.json + the
recording itself. The model writes one promise line; the code picks the moments, crops the
screens, lays out, animates, times the cuts and places every sound.

work/hook.json (only "promise" is required; `ev2 hook <dir> --init` writes a starter):
    {
      "recipe": "showcase",                    # showcase (default) | calm
      "promise": "من *الطلب* حتى التسليم",      # the opening headline, <= 60 chars, *word* = accent
      "brand": "Zehri",                        # small chip above the headline (optional)
      "title": "Zehri — إدارة الطلبات",          # end card title (default: timeline hook_title)
      "shots": [{"src_t": 150.0, "label": "Commandes", "icon": "shopping-bag"}],   # optional, else auto
      "agenda": true                           # chapter chips on the end card
    }

Structure of "showcase" over the spoken intro (the hook's own voice keeps playing):
  1. Title: the promise in kinetic type over a slow 3D wall of the app's screens.
  2. Montage: 3-7 moving screen shots (cropped clear of the webcam), each with an icon + label
     chip, cut with alternating push / zoom-through / rise transitions, a progress row, and the
     speaker live (lip-synced) in a PiP.
  3. End card: brand + title + the chapters as chips, then a zoom into the first body frame in
     the body's own framing, so the hook flows into the tutorial without a hard cut.
"calm": a title card over the live screen, then the screen in the body framing (for plain walkthroughs).
"""
import json, math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'scripts'))
import ev2_pro as P          # noqa: E402
import ev2_timeline as TL    # noqa: E402
from ev1_devices import Comp, sfx, fr, dstr  # noqa: E402

W, H, FPS = 1920, 1080, 30
CARD_W, CARD_H = 1440, 810
CARD_X, CARD_Y = (W - CARD_W) // 2, 128


class HookError(Exception):
    pass


# ------------------------------------------------------------------ config
def load_cfg(vd):
    p = os.path.join(vd, 'work', 'hook.json')
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding='utf-8'))
    except ValueError as e:
        raise HookError(f'work/hook.json is not valid JSON: {e}')


def check_cfg(cfg, tl):
    """Plain-language problems (empty = OK). 'placeholders' = things FINAL refuses."""
    probs = []
    if not isinstance(cfg, dict):
        return ['work/hook.json must be an object']
    if cfg.get('recipe', 'showcase') not in ('showcase', 'calm'):
        probs.append('recipe must be "showcase" or "calm"')
    pr = str(cfg.get('promise', '')).strip()
    if not pr or pr.startswith('<'):
        probs.append('"promise" is empty: write the one-line promise of the video (what the viewer gets), <= 60 chars')
    elif len(P.plain(pr)) > 60:
        probs.append(f'"promise" is {len(P.plain(pr))} chars: keep it <= 60 (one strong line)')
    if cfg.get('brand') and len(str(cfg['brand'])) > 24:
        probs.append('"brand" is longer than 24 chars')
    if cfg.get('title') and len(P.plain(str(cfg['title']))) > 70:
        probs.append('"title" is longer than 70 chars')
    hs = float(tl['hook_split'])
    for i, s in enumerate(cfg.get('shots') or [], 1):
        if not isinstance(s, dict) or not isinstance(s.get('src_t'), (int, float)):
            probs.append(f'shot #{i} needs "src_t" (source seconds)')
            continue
        if s['src_t'] < hs:
            probs.append(f'shot #{i} src_t {s["src_t"]} is inside the hook (< {hs:.1f}); pick a moment from the tutorial body')
        if s.get('label') and len(str(s['label'])) > 28:
            probs.append(f'shot #{i} label is longer than 28 chars')
        if s.get('icon') and not P.icon_exists(str(s['icon'])):
            probs.append(f'shot #{i} icon "{s["icon"]}" not found (Lucide name or brand:<slug>, or leave it out)')
    return probs


# ------------------------------------------------------------------ moments
def _activity(vd):
    p = os.path.join(vd, 'work', 'activity.npz')
    if not os.path.isfile(p):
        import body_render
        body_render.analyze(vd)
    d = np.load(p, allow_pickle=False)
    return {k: d[k] for k in d.files}


def _thumbs(vd):
    """1 fps grayscale 240x135 frames of the recording (cached in work/pro/thumbs.npy)."""
    import cv2
    out = os.path.join(vd, 'work', 'pro', 'thumbs.npy')
    cam = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    stamp = out + '.json'
    st = os.stat(cam)
    key = {'size': st.st_size, 'mtime': int(st.st_mtime)}
    if os.path.isfile(out) and os.path.isfile(stamp) and json.load(open(stamp)) == key:
        return np.load(out)
    import body_render
    fr_ = np.array(list(body_render.read_frames(cam, 1, 240, 136)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    np.save(out, fr_)
    json.dump(key, open(stamp, 'w'))
    return fr_


def _kept(segs, t, dur):
    for s in segs:
        if s['src_start'] <= t and t + dur <= s['src_end']:
            return True
    return False


def pick_moments(vd, tl, n, dur=2.6):
    """n moments of the tutorial body worth showing: one per chapter (spread when there are
    more chapters than shots), each the most detailed, gently active, kept stretch, all different."""
    import cv2
    segs = TL.body_segments(tl)
    if not segs:
        raise HookError('timeline has no body segments')
    act = _activity(vd)
    frac = act['frac']
    th = _thumbs(vd)
    start, end = segs[0]['src_start'], segs[-1]['src_end']
    chs = sorted(float(c['src_t']) for c in tl.get('chapters') or [] if float(c['src_t']) >= start - 1)
    bounds = [max(start, c) for c in chs] or [start]
    if bounds[0] > start + 20:
        bounds = [start] + bounds
    wins = [(bounds[i], bounds[i + 1] if i + 1 < len(bounds) else end) for i in range(len(bounds))]
    if len(wins) > n:
        idx = [round(i * (len(wins) - 1) / max(1, n - 1)) for i in range(n)]
        wins = [wins[i] for i in sorted(set(idx))]
    while len(wins) < n:
        k = max(range(len(wins)), key=lambda i: wins[i][1] - wins[i][0])
        a, b = wins[k]
        wins[k:k + 1] = [(a, (a + b) / 2), ((a + b) / 2, b)]

    def edge(t):
        k = int(min(len(th) - 1, max(0, round(t))))
        g = th[k]
        return float((cv2.Canny(g, 60, 140) > 0).mean()), g

    picks = []
    for a, b in wins:
        best = None
        t = a + 1.5
        while t + dur <= b - 0.5:
            if _kept(segs, t, dur):
                i0, i1 = int(t * 5), int((t + dur) * 5) + 1
                fr_ = frac[i0:i1] if i1 <= len(frac) else frac[i0:]
                mean, peak = (float(fr_.mean()), float(fr_.max())) if len(fr_) else (0.0, 0.0)
                e, g = edge(t + dur / 2)
                if g.mean() < 6:
                    t += 0.5
                    continue
                s = min(1.0, e / 0.06) + min(1.0, mean / 0.004) * 0.8 - (1.5 if peak > 0.25 else 0)
                for _, pg in picks:
                    if np.abs(g.astype(np.float32) - pg).mean() < 10:
                        s -= 1.2
                if best is None or s > best[0]:
                    best = (s, t, g.astype(np.float32))
            t += 0.5
        if best is None:          # a window with no long-enough kept stretch: take its first kept frame
            for s_ in segs:
                if s_['src_end'] > a and s_['src_start'] < b:
                    t0 = max(a, s_['src_start'])
                    best = (0, t0, edge(t0)[1].astype(np.float32))
                    break
        if best is not None:
            picks.append((best[1], best[2]))
    return [round(t, 2) for t, _ in picks]


def label_for(tl, t):
    title = None
    for c in sorted(tl.get('chapters') or [], key=lambda c: float(c['src_t'])):
        if float(c['src_t']) <= t + 0.5:
            title = c['title']
    return P.short_label(title) if title else ''


def starter(vd, tl, n=None):
    """A work/hook.json with auto-picked shots and labels; only the promise is left to write."""
    hs = float(tl['hook_split'])
    n = n or n_shots(hs)
    ts = pick_moments(vd, tl, n)
    shots = []
    for t in ts:
        lab = label_for(tl, t)
        shots.append({'src_t': t, 'label': lab, 'icon': P.guess_icon(lab) if lab else 'circle-dot'})
    return {'recipe': 'showcase', 'promise': '', 'brand': '', 'title': tl.get('hook_title') or '',
            'shots': shots, 'agenda': True}


# ------------------------------------------------------------------ geometry
def n_shots(D):
    a, c = phase_lengths(D)
    return int(min(7, max(2, round((D - a - c) / 2.3))))


def phase_lengths(D):
    a = min(4.2, max(2.6, 0.2 * D))
    c = min(4.8, max(3.0, 0.2 * D))
    if D < a + c + 2.4:
        k = (D - 2.4) / (a + c)
        a, c = max(1.8, a * k), max(2.0, c * k)
    return a, c


def smart_crop(cam, bbox, content=(0, 0, W, H)):
    """A 16:9 crop of the recording (inside its content rect, no letterbox bars) clear of the
    webcam box, as large as possible, centred on the action (bbox) when known."""
    best = None
    ox, oy, ow, oh = content
    full = min(ow / W, oh / H)
    for s in (1.0, 0.86, 0.78, 0.72, 0.66, 0.6, 0.54):
        cw, ch = W * full * s, H * full * s
        cands = []
        for fx in np.linspace(0, 1, 9):
            for fy in np.linspace(0, 1, 7):
                x, y = ox + (ow - cw) * fx, oy + (oh - ch) * fy
                if cam:
                    bx, by, bw, bh = cam
                    if not (x + cw <= bx - 10 or x >= bx + bw + 10 or y + ch <= by - 10 or y >= by + bh + 10):
                        continue
                if bbox is not None:
                    ax, ay = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                    inside = x <= bbox[0] and bbox[2] <= x + cw and y <= bbox[1] and bbox[3] <= y + ch
                    d = math.hypot(x + cw / 2 - ax, y + ch / 2 - ay) - (0 if inside else 600)
                else:
                    d = math.hypot(x + cw / 2 - W / 2, y + ch / 2 - H / 2)
                cands.append((d, (x, y, cw, ch)))
        if cands:
            best = min(cands)[1]
            break
    return best or (ox, oy, W * full, H * full)


def action_bbox(act, t, dur):
    i0, i1 = int(t * 5), int((t + dur) * 5) + 1
    bb = act['bbox'][i0:i1]
    bb = bb[bb[:, 0] >= 0] if len(bb) else bb
    if not len(bb):
        return None
    return (float(np.percentile(bb[:, 0], 20)), float(np.percentile(bb[:, 1], 20)),
            float(np.percentile(bb[:, 2], 80)), float(np.percentile(bb[:, 3], 80)))


# ------------------------------------------------------------------ pieces
def video_card(c, t0, t1, media_t, crop, x, y, w, h, z, cid=None, radius=22, cls='pro-shot'):
    """A card showing part of the recording (crop of the 1920x1080 frame) as live video.
    The card is an untimed wrapper (shown for [t0, t1) by the timeline); returns its id."""
    cid = cid or c.uid('pvc')
    vid = c.uid('pvv')
    cx, cy, cw, ch = crop
    k = w / cw
    c.at(f'tl.set("#{cid}",{{visibility:"visible"}},{fr(t0):.4f});tl.set("#{cid}",{{visibility:"hidden"}},{fr(t1):.4f});')
    c.els.append(
        f'<div id="{cid}" class="{cls}" style="left:{x:.0f}px;top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px;'
        f'border-radius:{radius}px;z-index:{z};visibility:hidden">'
        f'<video id="{vid}" class="clip" src="assets/media/cam_raw.mp4" muted playsinline data-start="{fr(t0):.4f}" '
        f'data-duration="{dstr(t0, t1)}" data-media-start="{max(0.0, media_t):.4f}" '
        f'style="position:absolute;left:{-cx * k:.1f}px;top:{-cy * k:.1f}px;width:{W * k:.1f}px;height:{H * k:.1f}px;'
        f'max-width:none;display:block"></video></div>')
    return cid


def presenter(c, t0, t1, cam, z=60):
    """The speaker, live and lip-synced (the hook's voice is the same source time), exactly where
    the body draws its PiP, so the cut into the body does not move the face."""
    bx, by, bw, bh = cam
    inset = 3
    crop = (bx + inset, by + inset, bw - 2 * inset, bh - 2 * inset)
    x, y, w, h = P.pip_rect(cam)
    pid = video_card(c, t0, t1, t0, crop, x, y, w, h, z, radius=22, cls='pro-abs')
    c.css.append(f'#{pid}{{overflow:hidden;border:3px solid rgba(255,255,255,0.9);box-shadow:0 24px 60px rgba(0,0,0,0.6)}}')
    c.pre.append(f'gsap.set("#{pid}",{{opacity:0,scale:0.8,y:30}});')
    c.at(f'tl.fromTo("#{pid}",{{opacity:0,scale:0.8,y:30}},{{opacity:1,scale:1,y:0,duration:0.5,ease:"back.out(1.6)",immediateRender:false}},{t0 + 0.05:.4f});')
    return pid


def wall(c, t0, t1, stills, z=2):
    """A slow, tilted 3D wall of the app's screens behind the title (dimmed)."""
    gid = c.uid('pwall')
    tiles = []
    cols, tw, gap = 3, 620, 36
    rows = 3
    for r in range(rows):
        for k in range(cols):
            src = stills[(r * cols + k) % len(stills)]
            tiles.append(f'<div class="pro-shot" style="position:absolute;left:{k * (tw + gap) + (r % 2) * 180:.0f}px;'
                         f'top:{r * (tw * 9 / 16 + gap):.0f}px;width:{tw}px;height:{tw * 9 / 16:.0f}px">'
                         f'<img src="{P.esc(src)}" style="width:100%;height:100%;object-fit:cover"></div>')
    inner = (f'<div class="pro-abs" style="left:0;top:0;width:1920px;height:1080px;perspective:1600px">'
             f'<div id="{gid}" class="pro-abs" style="left:240px;top:60px;width:2100px;height:1200px;transform-style:preserve-3d;'
             f'transform:rotateX(24deg) rotateZ(-10deg) translateZ(-200px);opacity:0.30;filter:saturate(0.9)">'
             + ''.join(tiles) + '</div></div>'
             f'<div class="pro-abs" style="inset:0;background:radial-gradient(ellipse 60% 55% at 50% 50%,rgba(5,5,10,0.55),rgba(5,5,10,0.15))"></div>')
    cid = c.clip(t0, t1, inner, z, cls='')
    d = t1 - t0
    c.at(f'tl.fromTo("#{gid}",{{x:0,y:0}},{{x:-260,y:-120,duration:{d:.3f},ease:"none",immediateRender:false}},{t0:.4f});')
    c.pre.append(f'gsap.set("#{cid}",{{opacity:0}});')
    c.at(f'tl.fromTo("#{cid}",{{opacity:0}},{{opacity:1,duration:0.6,ease:"power2.out",immediateRender:false}},{t0:.4f});')
    c.at(f'tl.to("#{cid}",{{opacity:0,duration:0.35,ease:"power2.in"}},{t1 - 0.35:.4f});')
    return cid


ENTERS = [
    ('{x:1500,rotationY:-24,opacity:0,filter:"blur(10px)"}', '{x:0,rotationY:0,opacity:1,filter:"blur(0px)"}',
     '{x:-1500,rotationY:24,opacity:0,filter:"blur(10px)"}'),
    ('{scale:1.35,opacity:0,filter:"blur(18px)"}', '{scale:1,opacity:1,filter:"blur(0px)"}',
     '{scale:0.8,opacity:0,filter:"blur(12px)"}'),
    ('{y:620,rotationX:28,opacity:0,filter:"blur(8px)"}', '{y:0,rotationX:0,opacity:1,filter:"blur(0px)"}',
     '{y:-620,rotationX:-20,opacity:0,filter:"blur(8px)"}'),
]


# ------------------------------------------------------------------ showcase
def showcase(c, vd, tl, cfg, look, th, D):
    a_len, c_len = phase_lengths(D)
    A_end, C0 = a_len, D - c_len
    act = _activity(vd)
    cam = P.tracked_cam_box(vd)
    content = P.view_rect(vd, look)
    P.pro_css(c, th)
    c.css.append('.pro-shot{transform-style:preserve-3d}')
    P.backdrop(c, 0, D, th, 'assets/pro/bg.png', z=1, grain_src='assets/pro/grain.png')

    shots = list(cfg.get('shots') or [])
    n = n_shots(D)
    if len(shots) < n:
        have = {round(s['src_t']) for s in shots}
        for t in pick_moments(vd, tl, n):
            if len(shots) >= n:
                break
            if round(t) not in have:
                lab = label_for(tl, t)
                shots.append({'src_t': t, 'label': lab})
    shots = shots[:7]
    n = len(shots)
    stills = [P.clean_still(vd, s['src_t'] + 1.0) for s in shots]

    # 1. title: brand chip + promise over the wall
    wall(c, 0, A_end + 0.2, stills, z=2)
    brand = str(cfg.get('brand', '')).strip()
    promise = str(cfg.get('promise', '')).strip() or '…'
    size, lines = P.fit_text(promise, 1500, (128, 116, 104, 96, 88, 80, 72, 64, 56), 800, 2)
    hgt = len(lines) * size * 1.1
    ty = (H - hgt) / 2 + (24 if brand else 0)
    html, ids = P.text_block(c, promise, 210, ty, 1500, size, 800, line_h=1.1)
    tid = c.clip(0, A_end + 0.1, html, 20, cls='')
    sfx(c, 0.0, 'subboom', 0.8)
    end_words = P.reveal_words(c, ids, 0.32, min(0.09, 1.1 / max(1, len(ids))), 0.5, 46, 18)
    sfx(c, 0.3, 'swish', 0.8)
    if brand:
        bid = c.uid('pbr')
        c.clip(0, A_end + 0.1, f'<div class="pro-abs" style="left:0;top:{ty - 96:.0f}px;width:1920px;display:flex;justify-content:center">'
                               + P.chip_html(bid, brand, 'sparkles', th, None, 30, 44) + '</div>', 21, cls='')
        P.pop_in(c, bid, 0.12, 0.5, 0.7, 10, 'back.out(1.8)')
        P.fade_out(c, bid, A_end - 0.32, 0.3)
    c.at(f'tl.fromTo("#{tid}",{{scale:1}},{{scale:1.05,duration:{A_end:.3f},ease:"none",immediateRender:false}},0);')
    P.hide_words(c, ids, A_end - 0.3, 0.3, -30)
    sfx(c, min(end_words, A_end - 0.6), 'click_soft', 0.8)

    # 2. montage
    per = (C0 - A_end) / n
    cards = []
    for i, s in enumerate(shots):
        t_in = A_end + i * per
        t_out = t_in + per
        crop = smart_crop(cam, action_bbox(act, s['src_t'], per), content)
        cid = video_card(c, t_in - 0.02, t_out + 0.36, s['src_t'], crop, CARD_X, CARD_Y, CARD_W, CARD_H, 10 + i)
        e_from, e_to, _ = ENTERS[i % 3]
        _, _, x_to = ENTERS[(i + 1) % 3]
        c.pre.append(f'gsap.set("#{cid}",{e_from[:-1]},transformPerspective:1800}});')
        c.at(f'tl.fromTo("#{cid}",{e_from},{e_to[:-1]},duration:0.42,ease:"power3.out",immediateRender:false}},{t_in:.4f});')
        c.at(f'tl.fromTo("#{cid}",{{scale:1}},{{scale:1.045,duration:{per:.3f},ease:"none",immediateRender:false}},{t_in + 0.42:.4f});')
        if i < n - 1:
            c.at(f'tl.to("#{cid}",{x_to[:-1]},duration:0.36,ease:"power3.in"}},{t_out - 0.02:.4f});')
        else:
            c.at(f'tl.to("#{cid}",{{scale:0.86,opacity:0,filter:"blur(14px)",duration:0.4,ease:"power3.in"}},{t_out - 0.02:.4f});')
        sfx(c, t_in, 'swish', 0.6 if i % 2 else 0.75)
        lab = s.get('label') or label_for(tl, s['src_t'])
        if lab:
            chid = c.uid('pch')
            c.clip(t_in, min(D, t_out + 0.1), f'<div class="pro-abs" style="left:{CARD_X + 34}px;top:{CARD_Y - 34}px">'
                                              + P.chip_html(chid, lab, s.get('icon') or P.guess_icon(lab), th, f'{i + 1:02d}', 32, 48) + '</div>', 40, cls='')
            P.pop_in(c, chid, t_in + 0.22, 0.45, 0.6, 14, 'back.out(2)')
            P.fade_out(c, chid, t_out - 0.22, 0.2, 0.9, -8, 4)
            sfx(c, t_in + 0.22, 'click_soft', 0.7)
        cards.append((t_in, t_out))
    # progress row
    dots = []
    dw, gap = 46, 14
    total = n * dw + (n - 1) * gap + 60
    x0 = (W - total) / 2
    row = []
    for i in range(n):
        did = c.uid('pdt')
        dots.append(did)
        row.append(f'<div id="{did}" style="width:{dw}px;height:8px;border-radius:4px;background:rgba(255,255,255,0.22);flex:none"></div>')
    rid = c.uid('prow')
    c.clip(A_end, C0 + 0.2, f'<div id="{rid}" class="pro-abs" style="left:{x0:.0f}px;top:{CARD_Y + CARD_H + 44}px;display:flex;gap:{gap}px">'
                            + ''.join(row) + '</div>', 41, cls='')
    P.pop_in(c, rid, A_end + 0.1, 0.4, 1.0, 10, 'power3.out')
    for i, did in enumerate(dots):
        t_in = cards[i][0]
        c.at(f'tl.fromTo("#{did}",{{width:{dw},background:"rgba(255,255,255,0.22)"}},{{width:{dw + 60},background:"{th["accent"]}",'
             f'duration:0.35,ease:"power3.out",immediateRender:false}},{t_in + 0.1:.4f});')
        if i < n - 1:
            c.at(f'tl.to("#{did}",{{width:{dw},background:"rgba(255,255,255,0.45)",duration:0.3,ease:"power3.out"}},{cards[i][1] + 0.1:.4f});')
    if cam:
        presenter(c, A_end, D, cam)

    # 3. end card: brand + title + agenda, then into the body's own framing
    title = str(cfg.get('title') or tl.get('hook_title') or '').strip()
    k0 = C0 + 0.25
    end_parts, eids = [], []
    tsz, tlines = P.fit_text(title or promise, 1500, (92, 84, 76, 68, 60, 54, 48), 800, 2)
    agenda = [P.short_label(ch['title'], 24) for ch in sorted(tl.get('chapters') or [], key=lambda c: float(c['src_t']))] if cfg.get('agenda', True) else []
    if len(agenda) > 6:
        idx = [round(i * (len(agenda) - 1) / 5) for i in range(6)]
        agenda = [agenda[i] for i in idx]
    ag_h = (70 * math.ceil(len(agenda) / 3) + 20) if agenda else 0
    block = (64 if brand else 0) + len(tlines) * tsz * 1.1 + (40 + ag_h if agenda else 0)
    y = (H - block) / 2 - 30
    if brand:
        bid2 = c.uid('pbr')
        end_parts.append(f'<div class="pro-abs" style="left:0;top:{y:.0f}px;width:1920px;display:flex;justify-content:center">'
                         + P.chip_html(bid2, brand, 'sparkles', th, None, 26, 40) + '</div>')
        y += 84
    th_html, tids = P.text_block(c, title or promise, 210, y, 1500, tsz, 800, line_h=1.1)
    end_parts.append(th_html)
    y += len(tlines) * tsz * 1.1 + 44
    chips = []
    if agenda:
        cids = []
        for i, a in enumerate(agenda):
            ci = c.uid('pag')
            cids.append(ci)
            chips.append(P.chip_html(ci, a, P.guess_icon(a), th, f'{i + 1:02d}', 27, 40))
        end_parts.append(f'<div class="pro-abs" style="left:160px;top:{y:.0f}px;width:1600px;display:flex;flex-wrap:wrap;'
                         f'justify-content:center;gap:16px 18px">' + ''.join(chips) + '</div>')
    gid = c.uid('pend')
    c.clip(C0, D, f'<div id="{gid}" class="pro-abs" style="left:0;top:0;width:1920px;height:1080px">' + ''.join(end_parts) + '</div>', 30, cls='')
    if brand:
        P.pop_in(c, bid2, k0, 0.45, 0.7, 10, 'back.out(1.8)')
    P.reveal_words(c, tids, k0 + 0.12, min(0.07, 0.8 / max(1, len(tids))), 0.45, 34, 14)
    sfx(c, k0, 'swish', 0.7)
    if agenda:
        for i, ci in enumerate(cids):
            t = k0 + 0.55 + i * 0.12
            P.pop_in(c, ci, t, 0.4, 0.7, 16, 'back.out(1.8)')
            sfx(c, t, 'click_soft', 0.55)
    # into the body: the title zooms past the camera while the first body frame settles in
    t_land = D - 0.75
    c.at(f'tl.to("#{gid}",{{scale:1.25,opacity:0,filter:"blur(16px)",duration:0.5,ease:"power3.in"}},{t_land - 0.1:.4f});')
    sfx(c, t_land + 0.25, 'riser', 0.7)
    gx, gy, gw, gh, rad = P.stage_geometry(look, content)
    lid = video_card(c, t_land, D, t_land, content if rad else (0, 0, W, H), gx, gy, gw, gh, 50, radius=rad,
                     cls='pro-abs' if rad == 0 else 'pro-shot')
    c.pre.append(f'gsap.set("#{lid}",{{opacity:0,scale:1.12}});')
    c.at(f'tl.fromTo("#{lid}",{{opacity:0,scale:1.12,filter:"blur(10px)"}},{{opacity:1,scale:1,filter:"blur(0px)",duration:0.55,'
         f'ease:"power3.out",immediateRender:false}},{t_land:.4f});')
    return {'shots': [{'src_t': s['src_t'], 'label': s.get('label', '')} for s in shots], 'phases': [0, A_end, C0, D]}


# ------------------------------------------------------------------ calm
def calm(c, vd, tl, cfg, look, th, D):
    """Title card (4 s) over the live screen, then the screen in the body's framing."""
    P.pro_css(c, th)
    P.backdrop(c, 0, D, th, 'assets/pro/bg.png', z=1, grain_src='assets/pro/grain.png')
    content = P.view_rect(vd, look)
    gx, gy, gw, gh, rad = P.stage_geometry(look, content)
    video_card(c, 0, D, 0.0, content if rad else (0, 0, W, H), gx, gy, gw, gh, 5, radius=rad, cls='pro-abs' if rad == 0 else 'pro-shot')
    cam = P.tracked_cam_box(vd)
    if cam:
        presenter(c, 0, D, cam)
    t1 = min(D, 4.5)
    dim = c.uid('pdim')
    c.clip(0, t1, f'<div id="{dim}" class="pro-abs" style="inset:0;background:rgba(6,6,10,0.78);backdrop-filter:blur(14px)"></div>', 20, cls='')
    title = str(cfg.get('title') or tl.get('hook_title') or cfg.get('promise') or '').strip()
    promise = str(cfg.get('promise', '')).strip()
    size, lines = P.fit_text(title, 1500, (96, 86, 76, 68, 60), 800, 2)
    y = (H - len(lines) * size * 1.1) / 2 - 40
    html, ids = P.text_block(c, title, 210, y, 1500, size, 800, line_h=1.1)
    parts = [html]
    sids = []
    if promise and promise != title:
        sh, sids = P.text_block(c, promise, 310, y + len(lines) * size * 1.1 + 30, 1300, 40, 600, color=th['muted'])
        parts.append(sh)
    gid = c.uid('pcal')
    c.clip(0, t1, f'<div id="{gid}" class="pro-abs" style="inset:0">' + ''.join(parts) + '</div>', 30, cls='')
    P.reveal_words(c, ids, 0.25, 0.06, 0.5, 30, 12)
    if sids:
        P.reveal_words(c, sids, 0.9, 0.04)
    sfx(c, 0.2, 'swish', 0.6)
    c.at(f'tl.to("#{gid}",{{opacity:0,y:-30,filter:"blur(10px)",duration:0.45,ease:"power2.in"}},{t1 - 0.45:.4f});')
    c.at(f'tl.to("#{dim}",{{opacity:0,duration:0.45,ease:"power2.in"}},{t1 - 0.45:.4f});')
    return {'shots': [], 'phases': [0, t1, D]}


# ------------------------------------------------------------------ entry point
def build(vd, final=False):
    """Writes index.html, sfx-cues.txt, work/build.json, work/hook_chapters.json, work/shots.json.
    Returns the status dict. Raises HookError with plain-language problems."""
    vd = os.path.abspath(vd)
    tl = TL.load(vd)
    D = TL.frames(tl['hook_split']) / FPS
    if D <= 0:
        raise HookError('hook_split is 0: there is no hook to build (set one with `ev2 clean <dir> --hook-split S`)')
    cfg = load_cfg(vd)
    created = False
    if cfg is None:
        cfg = starter(vd, tl)
        json.dump(cfg, open(os.path.join(vd, 'work', 'hook.json'), 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        created = True
    probs = check_cfg(cfg, tl)
    look, th = P.ensure_look(vd)
    c = Comp(D, caption_mode='hook-only', hook_end=D)
    recipe = cfg.get('recipe', 'showcase')
    info = (calm if recipe == 'calm' else showcase)(c, vd, tl, cfg, look, th, D)
    warns = []
    if D > 32:
        warns.append(f'the hook is {D:.0f}s long: hooks work best at 15-30s (`ev2 clean <dir> --hook-split S`, then rebuild)')
    status = {'placeholders': probs, 'missing': [], 'final': bool(final and not probs), 'hook_split': float(tl['hook_split']),
              'recipe': recipe, 'auto': True, 'warnings': warns, **info}
    json.dump(status, open(os.path.join(vd, 'work', 'build.json'), 'w'), indent=2, ensure_ascii=False)
    if final and probs:
        raise HookError('FINAL refused, fix work/hook.json: ' + '; '.join(probs))
    os.chdir(vd)
    c.write('index.html', 'assets/ev1/tokens.css', title='Editor V2 hook')
    c.write_cues('sfx-cues.txt')
    c.chapters = []
    c.write_chapters(None, 'work/hook_chapters.json')
    json.dump([[0, fr(D), 'hook']], open('work/shots.json', 'w'))
    status['created_cfg'] = created
    return status


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description='Build the automatic hook (index.html) from work/hook.json')
    ap.add_argument('video_dir')
    ap.add_argument('--final', action='store_true', help='refuse while work/hook.json has problems')
    ap.add_argument('--init', action='store_true', help='write/refresh work/hook.json with auto-picked shots (keeps your promise/brand/title)')
    a = ap.parse_args(argv)
    vd = os.path.abspath(a.video_dir)
    try:
        if a.init:
            tl = TL.load(vd)
            old = load_cfg(vd) or {}
            new = starter(vd, tl)
            for k in ('promise', 'brand', 'title', 'recipe', 'agenda'):
                if old.get(k):
                    new[k] = old[k]
            json.dump(new, open(os.path.join(vd, 'work', 'hook.json'), 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
            print(f'hook: wrote work/hook.json with {len(new["shots"])} auto-picked shots:')
            for s in new['shots']:
                print(f'  {TL.fmt_ts(s["src_t"])}  {s["label"] or "(no label)"}  [{s["icon"]}]')
            if not new.get('promise'):
                print('hook: now write "promise" (one line, <= 60 chars, *word* = accent), then `ev2 hook <dir>`')
            return 0
        st = build(vd, final=a.final)
    except (HookError, TL.TimelineError) as e:
        print(f'hook: ERROR {e}', file=sys.stderr)
        return 1
    if st.get('created_cfg'):
        print('hook: created work/hook.json (auto-picked shots); write its "promise", then build again')
    for p in st['placeholders']:
        print(f'hook: TODO {p}')
    for w in st.get('warnings', []):
        print(f'hook: WARN {w}')
    print(f'hook: {st["recipe"]} | {len(st.get("shots", []))} shots | phases {", ".join(f"{x:.1f}" for x in st["phases"])} | '
          f'{"FINAL" if st["final"] else "draft"} -> index.html')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
