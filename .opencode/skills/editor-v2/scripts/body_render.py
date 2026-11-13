#!/usr/bin/env python3
"""body_render.py — the polished tutorial body: auto zooms, styled webcam, chapter cards, captions.

    body_render.py <video-dir> [--no-zoom] [--no-cam] [--captions] [--no-keys] [--plan-only]

1. analyze(): screen activity of assets/media/cam_raw.mp4 at 5 fps (what changes where:
   typing, pointing, menus, page loads) + where the Omarchy webcam is (face tracking at 1 fps,
   starting from work/omarchy.json). Cached in work/activity.npz.
2. plan the camera on the cleaned body timeline (work/timeline.json) -> work/zoom_plan.json:
   with an input log (work/inputs.json from `ev2 rec`) zoom on clicks and typing, Screen Studio
   style; without one, zoom where the screen activity stays in a small area. Eased 0.73 s
   smootherstep moves, capped by work/look.json max_zoom (default 1.6x).
3. render(): the screen sits as a rounded card on the video's backdrop (look.frame "inset",
   or "full"), the burned-in webcam is painted out and the speaker re-drawn as a PiP at the
   same spot as in the hook, click ripples (input log), callouts ("callouts" in timeline.json),
   chapter lower-thirds in the accent colour, key pills (timeline "keys" + shortcuts from the
   input log), optional captions. Explainer inserts replace the picture with a zoom-through
   (full; the PiP fades out unless "cam": true) or sit over a dimmed screen (over).
   -> work/body_video.mp4 (silent, exact frame count, cached) + work/body_fx_cues.txt (the
   body's own sounds: clicks, chapter whooshes, insert whooshes, callout pops).
"""
import argparse, hashlib, json, math, os, subprocess, sys

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

W, H, FPS = 1920, 1080, TL.FPS
AF = 5                      # analysis fps
AS = 4                      # analysis downscale (480x270)
AW, AH = W // AS, H // AS
FONT_AR = os.path.join(SK, 'assets', 'fonts', 'Cairo-Var.ttf')      # full Cairo (OFL), weight axis set to 700
FONT_LAT = os.path.join(SK, 'assets', 'fonts', 'Inter-700.woff2')
PLAN_VERSION = 6


def log(msg):
    print(f'body: {msg}', flush=True)


# ------------------------------------------------------------------ webcam box
def default_cam_box(vd):
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


def read_frames(path, fps, w, h, gray=True):
    pix = 'gray' if gray else 'bgr24'
    ch = 1 if gray else 3
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vf', f'fps={fps},scale={w}:{h}',
                          '-pix_fmt', pix, '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    n = w * h * ch
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(h, w) if gray else np.frombuffer(b, np.uint8).reshape(h, w, 3)
    p.wait()


YUNET = os.path.expanduser('~/.cache/editor-v2/models/yunet.onnx')
YUNET_URL = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'


def face_detector():
    if not os.path.isfile(YUNET):
        return None
    os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')
    return cv2.FaceDetectorYN.create(YUNET, '', (960, 540), 0.6)


# ------------------------------------------------------------------ 1. analysis
def analyze(vd, force=False):
    cam_path = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    out = os.path.join(vd, 'work', 'activity.npz')
    st = os.stat(cam_path)
    key = f'{st.st_size}-{int(st.st_mtime)}-{PLAN_VERSION}'
    if not force and os.path.isfile(out):
        d = np.load(out, allow_pickle=False)
        if str(d['key']) == key:
            return {k: d[k] for k in d.files}
    log('analyzing screen activity (5 fps) ...')
    masks, prev = [], None
    for g in read_frames(cam_path, AF, AW, AH):
        g = cv2.GaussianBlur(g, (3, 3), 0)
        if prev is None:
            masks.append(np.zeros((AH, AW), bool))
        else:
            masks.append(cv2.absdiff(g, prev) > 14)
        prev = g
    masks = np.array(masks)
    n = len(masks)

    # webcam tracking: faces at 1 fps on 960x540, kept near the Omarchy default box and live
    dbox = default_cam_box(vd)
    cam = np.full((n, 4), -1.0)
    if dbox is not None:
        log('tracking the webcam (1 fps) ...')
        det = face_detector()
        faces = []
        if det is not None:
            for g in read_frames(cam_path, 1, 960, 540, gray=False):
                _, f = det.detect(np.ascontiguousarray(g))
                faces.append([tuple(float(v) * 2 for v in r[:4]) for r in f] if f is not None else [])
        else:
            log('WARNING face model missing (ev2 doctor downloads it): webcam assumed fixed at omarchy.json box')
        bx, by, bw, bh = dbox
        inside = [r for fs in faces for r in fs
                  if bx <= r[0] + r[2] / 2 <= bx + bw and by <= r[1] + r[3] / 2 <= by + bh]
        if inside:
            fw = float(np.median([r[2] for r in inside]))
            fcx = float(np.median([r[0] + r[2] / 2 for r in inside])) - bx
            fcy = float(np.median([r[1] + r[3] / 2 for r in inside])) - by
            ratio_w, ratio_h, rel_x, rel_y = bw / fw, bh / fw, fcx / bw, fcy / bh
        else:
            ratio_w = ratio_h = rel_x = rel_y = None
        cur, pending, live = list(dbox), None, masks.reshape(n, -1)
        for sec, fs in enumerate(faces):
            pick = None
            if fs:
                ccx, ccy = cur[0] + cur[2] / 2, cur[1] + cur[3] / 2
                pick = min(fs, key=lambda r: (r[0] + r[2] / 2 - ccx) ** 2 + (r[1] + r[3] / 2 - ccy) ** 2)
                pcx, pcy = pick[0] + pick[2] / 2, pick[1] + pick[3] / 2
                in_cur = cur[0] - cur[2] * .3 <= pcx <= cur[0] + cur[2] * 1.3 and cur[1] - cur[3] * .3 <= pcy <= cur[1] + cur[3] * 1.3
                if not in_cur and ratio_w:
                    nb = [pcx - rel_x * pick[2] * ratio_w, pcy - rel_y * pick[2] * ratio_h, pick[2] * ratio_w, pick[2] * ratio_h]
                    a0, a1 = sec * AF, min(n, sec * AF + AF)
                    x0, y0 = int(max(0, nb[0]) / AS), int(max(0, nb[1]) / AS)
                    x1, y1 = int(min(W, nb[0] + nb[2]) / AS), int(min(H, nb[1] + nb[3]) / AS)
                    alive = a1 > a0 and x1 > x0 and y1 > y0 and masks[a0:a1, y0:y1, x0:x1].mean() > 0.01
                    if alive and pending and abs(pending[0] - nb[0]) < 60 and abs(pending[1] - nb[1]) < 60:
                        cur, pending = nb, None
                    else:
                        pending = nb if alive else None
                else:
                    pending = None
            for k in range(sec * AF, min(n, sec * AF + AF)):
                cam[k] = cur
        cam[cam[:, 0] < 0] = cur
        # backfill: the tracker waits for proof before following a moved webcam, so each switch
        # is moved back to the first second the face was already at its new place
        changes = [k for k in range(1, n) if (cam[k] != cam[k - 1]).any()]
        for k in changes:
            nx, ny, nw, nh = cam[k]
            sec = k // AF
            s0 = sec
            while s0 - 1 >= 0 and s0 - 1 < len(faces) and any(
                    nx - nw * .3 <= r[0] + r[2] / 2 <= nx + nw * 1.3 and ny - nh * .3 <= r[1] + r[3] / 2 <= ny + nh * 1.3
                    for r in faces[s0 - 1]):
                s0 -= 1
            if s0 < sec:
                cam[s0 * AF:k] = cam[k]
        cam = refine_cam(cam_path, cam)
    # activity with the webcam (and a margin) masked out
    frac = np.zeros(n)
    bbox = np.full((n, 4), -1.0)
    for k in range(n):
        m = masks[k].copy()
        if cam[k][0] >= 0:
            x, y, bw, bh = cam[k]
            m[max(0, int(y / AS) - 12):int((y + bh) / AS) + 12, max(0, int(x / AS) - 12):int((x + bw) / AS) + 12] = False
        ys, xs = np.nonzero(m)
        frac[k] = len(xs) / m.size
        if len(xs) >= 4:
            x0, x1 = np.percentile(xs, [2, 98]) if len(xs) > 40 else (xs.min(), xs.max())
            y0, y1 = np.percentile(ys, [2, 98]) if len(ys) > 40 else (ys.min(), ys.max())
            bbox[k] = (x0 * AS, y0 * AS, (x1 + 1) * AS, (y1 + 1) * AS)
    np.savez_compressed(out, key=key, frac=frac, bbox=bbox, cam=cam)
    log(f'{n} samples analyzed -> work/activity.npz')
    return {'key': key, 'frac': frac, 'bbox': bbox, 'cam': cam}


def refine_cam(cam_path, cam):
    """Snap each tracked webcam position to the overlay's real rectangle. The overlay border is the
    one edge that stays put in every frame while the desktop behind it changes, so for each
    position we average thresholded gradients over up to 40 frames and pick the most persistent
    column/row near each side of the tracked box. (omarchy.json's box is computed for scale 1;
    on a scaled monitor the real overlay is bigger.)"""
    out = cam.copy()
    keys = [tuple(np.round(r).astype(int)) for r in cam]
    vc = cv2.VideoCapture(cam_path)
    for key in sorted(set(keys)):
        idx = [i for i, k in enumerate(keys) if k == key]
        if len(idx) < 10 or key[0] < 0:
            continue
        x, y, bw, bh = key
        ex = ey = None
        n = 0
        for i in idx[::max(1, len(idx) // 40)][:40]:
            vc.set(cv2.CAP_PROP_POS_MSEC, i / AF * 1000.0)
            ok, f = vc.read()
            if not ok:
                continue
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
            sx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) > 40
            sy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) > 40
            ex, ey = (sx.astype(np.float32), sy.astype(np.float32)) if ex is None else (ex + sx, ey + sy)
            n += 1
        if n < 5:
            continue
        ex, ey = ex / n, ey / n
        y0, y1 = max(0, int(y + bh * .2)), min(H, int(y + bh * .8))
        x0, x1 = max(0, int(x + bw * .2)), min(W, int(x + bw * .8))

        def best_col(lo, hi, default, edge_ok):
            lo, hi = max(0, int(lo)), min(W - 1, int(hi))
            if hi <= lo:
                return default
            prof = ex[y0:y1, lo:hi + 1].mean(axis=0)
            cands = np.nonzero(prof > 0.6)[0]
            if not len(cands):
                return edge_ok if edge_ok is not None else default
            return lo + int(cands[np.argmin(np.abs(lo + cands - default))])

        def best_row(lo, hi, default, edge_ok):
            lo, hi = max(0, int(lo)), min(H - 1, int(hi))
            if hi <= lo:
                return default
            prof = ey[lo:hi + 1, x0:x1].mean(axis=1)
            cands = np.nonzero(prof > 0.6)[0]
            if not len(cands):
                return edge_ok if edge_ok is not None else default
            return lo + int(cands[np.argmin(np.abs(lo + cands - default))])

        left = best_col(x - bw * .6, x + bw * .3, x, None)
        right = best_col(x + bw * .7, x + bw * 1.6, x + bw, W)
        top = best_row(y - bh * .6, y + bh * .3, y, None)
        bottom = best_row(y + bh * .7, y + bh * 1.6, y + bh, H)
        nb = (left + 1, top + 1, max(20, right - left - 1), max(20, bottom - top - 1))
        if 0.5 < nb[2] / bw < 2.5 and 0.5 < nb[3] / bh < 2.5:
            out[idx] = nb
    vc.release()
    return out


def pause_busy(act, s, e, thr=0.002):
    """True when the screen visibly changes during source [s, e] (page load, scroll, menu)."""
    s, e = s + 0.25, e - 0.25          # the edges belong to the speech around the pause
    if e <= s:
        return False
    a, b = int(math.ceil(s * AF)), int(e * AF) + 1
    fr = act['frac'][a:b]
    return len(fr) > 0 and float((fr > thr).mean()) >= 0.4


# ------------------------------------------------------------------ 2. camera plan
def body_src_frames(segs):
    return np.concatenate([np.arange(s['f_start'], s['f_end']) for s in segs]) if segs else np.zeros(0, np.int64)


def src_to_body_frame(segs, t):
    """Body frame of source time t, or None when t was cut."""
    f = int(round(t * FPS))
    for s in segs:
        if s['f_start'] <= f < s['f_end']:
            return int(round(s['out_start'] * FPS)) + f - s['f_start']
    return None


def plan_camera(tl, act, max_zoom=1.6, content=(0, 0, W, H)):
    """Activity-driven zooms (used when there is no input log): zoom where the action stays in a
    small area, follow it, zoom out on page changes or quiet spells."""
    segs = TL.body_segments(tl)
    n_out = sum(s['f_end'] - s['f_start'] for s in segs)
    src_f = body_src_frames(segs)
    step = FPS // AF
    ticks = list(range(0, n_out, step))
    na = len(act['frac'])
    ai = np.clip((src_f[ticks] / step).round().astype(int), 0, na - 1)
    frac, bbox = act['frac'][ai], act['bbox'][ai]
    scene = frac > 0.20
    ox, oy, cw, ch = content
    LOOK, MIN_START, QUIET_OUT, SCENE_HOLD, MIN_WIDE, MIN_HOLD, CLEAR_AHEAD = 8, 6, 30, 5, 7, 13, 13
    targets, cur, since_scene, quiet, stable, last_change = [], None, 99, 0, 0, -99

    def window_box(j):
        bs = [bbox[k] for k in range(j, min(len(ticks), j + LOOK)) if not scene[k] and bbox[k][0] >= 0 and frac[k] > 0.00004]
        if len(bs) < 2:
            return None
        b = np.array(bs)
        return b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()

    def zoom_for(b):
        bw, bh = b[2] - b[0] + 260, b[3] - b[1] + 190
        if bw * bh > 0.30 * cw * ch:
            return None
        z = min(max_zoom, 0.92 * min(cw / bw, ch / bh))
        return z if z >= 1.25 else None

    def fits(b, t):
        cx, cy, z = t
        hw, hh = cw / (2 * z), ch / (2 * z)
        return b[0] >= cx - hw + 40 and b[2] <= cx + hw - 40 and b[1] >= cy - hh + 30 and b[3] <= cy + hh - 30

    for j in range(len(ticks)):
        since_scene = 0 if any(scene[j:j + 2]) else since_scene + 1
        b = window_box(j)
        z = zoom_for(b) if b is not None else None
        if since_scene < SCENE_HOLD:
            if cur is not None and (since_scene == 0 or j - last_change >= MIN_HOLD):
                cur, last_change = None, j
            stable = 0
        elif cur is None:
            stable = stable + 1 if z else 0
            if stable >= MIN_START and j - last_change >= MIN_WIDE and not scene[j:j + CLEAR_AHEAD].any():
                cur = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, z)
                last_change, quiet = j, 0
        else:
            if b is None or frac[j] < 0.00004:
                quiet += 1
                if quiet >= QUIET_OUT and j - last_change >= MIN_HOLD:
                    cur, last_change, stable = None, j, 0
            else:
                quiet = 0
                if not fits(b, cur) and j - last_change >= MIN_HOLD:
                    if z:
                        cur, last_change = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, z), j
                    elif j - last_change >= MIN_HOLD:
                        cur, last_change, stable = None, j, 0
        targets.append(cur)
    targets = targets[2:] + [targets[-1]] * 2 if len(targets) > 2 else targets
    keys, prev = [], 'none'
    for j, t in enumerate(targets):
        tt = None if t is None else (round(t[0], 1), round(t[1], 1), round(t[2], 3))
        if tt != prev:
            keys.append({'f': ticks[j], 'cx': ox + cw / 2 if tt is None else tt[0], 'cy': oy + ch / 2 if tt is None else tt[1],
                         'z': 1.0 if tt is None else tt[2]})
            prev = tt
    return {'n_frames': int(n_out), 'keys': keys, 'source': 'activity',
            'zoomed_share': float(np.mean([t is not None for t in targets])) if targets else 0}


def load_inputs(vd):
    p = os.path.join(vd, 'work', 'inputs.json')
    if not os.path.isfile(p):
        return None
    try:
        d = json.load(open(p))
    except ValueError:
        return None
    return d if d.get('clicks') or d.get('typing') else None


def plan_camera_inputs(tl, inp, max_zoom=1.6, content=(0, 0, W, H)):
    """Click/typing-driven zooms (Screen Studio style): ease in on a click a little before it
    lands, stay while the next clicks/typing are close, pan to a near target, zoom out when
    the action moves far away or stops for a while."""
    segs = TL.body_segments(tl)
    n_out = sum(s['f_end'] - s['f_start'] for s in segs)
    ox, oy, cw, ch = content
    pts = []
    last_click = None
    for c in sorted(inp.get('clicks') or [], key=lambda c: c['t']):
        f = src_to_body_frame(segs, c['t'])
        if f is not None:
            pts.append((f - 18, f + 66, c['x'], c['y']))
    clicks_sorted = sorted(inp.get('clicks') or [], key=lambda c: c['t'])
    for t0, t1 in inp.get('typing') or []:
        prior = [c for c in clicks_sorted if c['t'] <= t0 and t0 - c['t'] < 30]
        if not prior:
            continue
        last_click = prior[-1]
        f0, f1 = src_to_body_frame(segs, t0), src_to_body_frame(segs, t1)
        if f0 is None:
            continue
        f1 = f1 if f1 is not None else f0 + 30
        pts.append((f0 - 9, f1 + 36, last_click['x'], last_click['y']))
    pts.sort()
    groups = []
    for a, b, x, y in pts:
        if groups:
            g = groups[-1]
            xs, ys = g['xs'] + [x], g['ys'] + [y]
            bw, bh = max(xs) - min(xs) + 420, max(ys) - min(ys) + 280
            if a <= g['b'] + 36 and min(cw / bw, ch / bh) * 0.92 >= 1.25:
                g.update(b=max(g['b'], b), xs=xs, ys=ys)
                continue
        groups.append({'a': max(0, a), 'b': b, 'xs': [x], 'ys': [y]})
    keys, zoomed = [{'f': 0, 'cx': ox + cw / 2, 'cy': oy + ch / 2, 'z': 1.0}], 0
    for i, g in enumerate(groups):
        bw, bh = max(g['xs']) - min(g['xs']) + 420, max(g['ys']) - min(g['ys']) + 280
        z = min(max_zoom, 0.92 * min(cw / bw, ch / bh))
        if z < 1.2:
            continue
        cx, cy = (max(g['xs']) + min(g['xs'])) / 2, (max(g['ys']) + min(g['ys'])) / 2
        if keys[-1]['f'] >= g['a']:
            keys[-1].update(cx=cx, cy=cy, z=z)
        else:
            keys.append({'f': int(g['a']), 'cx': cx, 'cy': cy, 'z': round(z, 3)})
        nxt = groups[i + 1]['a'] if i + 1 < len(groups) else n_out
        end = min(int(g['b']), n_out)
        if nxt - end > 45:
            keys.append({'f': end, 'cx': ox + cw / 2, 'cy': oy + ch / 2, 'z': 1.0})
        zoomed += max(0, min(nxt, n_out) - g['a']) if nxt - end <= 45 else end - g['a']
    keys = [k for k in keys if k['f'] < n_out]
    return {'n_frames': int(n_out), 'keys': keys, 'source': 'inputs', 'zoomed_share': min(1.0, zoomed / max(1, n_out))}


def camera_curve(plan, content=(0, 0, W, H), ease_frames=22):
    """Per-frame (cx, cy, z): smootherstep moves in log-zoom, the view kept inside the content."""
    n = plan['n_frames']
    ox, oy, cw, ch = content
    cx, cy, lz = np.full(n, ox + cw / 2.0), np.full(n, oy + ch / 2.0), np.zeros(n)
    c = (ox + cw / 2.0, oy + ch / 2.0, 0.0)
    keys = plan['keys'] + [{'f': n}]
    for i in range(len(keys) - 1):
        k = keys[i]
        tgt = (k['cx'], k['cy'], math.log(max(1.0, k['z'])))
        a, b = k['f'], keys[i + 1]['f']
        for f in range(a, min(b, n)):
            u = min(1.0, (f - a) / ease_frames)
            e = u * u * u * (u * (u * 6 - 15) + 10)
            cx[f], cy[f], lz[f] = (c[0] + (tgt[0] - c[0]) * e, c[1] + (tgt[1] - c[1]) * e, c[2] + (tgt[2] - c[2]) * e)
        if b > a:
            c = (cx[min(b, n) - 1], cy[min(b, n) - 1], lz[min(b, n) - 1])
    z = np.exp(lz)
    hw, hh = cw / (2 * z), ch / (2 * z)
    return np.clip(cx, ox + hw, ox + cw - hw), np.clip(cy, oy + hh, oy + ch - hh), z


# ------------------------------------------------------------------ 3. overlays
_FONTS = {}


def font(size, latin=False):
    k = (size, latin)
    if k not in _FONTS:
        f = ImageFont.truetype(FONT_LAT if latin else FONT_AR, size)
        if not latin:
            f.set_variation_by_axes([700, 0])
        _FONTS[k] = f
    return _FONTS[k]


def _is_ar(ch):
    o = ord(ch)
    return 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF


class Mixed:
    """Darija + Latin text: Arabic runs in Cairo (shaped RTL by raqm), Latin runs in Inter,
    runs laid out in visual order (right-to-left when the line starts with Arabic)."""
    def __init__(self, text, size):
        self.size = size
        words = text.split()
        runs = []
        for w in words:
            ar = any(_is_ar(c) for c in w)
            if runs and runs[-1][0] == ar:
                runs[-1][1].append(w)
            else:
                runs.append((ar, [w]))
        self.rtl = bool(runs) and runs[0][0]
        self.runs = [(ar, ' '.join(ws)) for ar, ws in runs]
        if self.rtl:
            self.runs = self.runs[::-1]
        d = ImageDraw.Draw(Image.new('L', (1, 1)))
        self.gap = d.textlength(' ', font=font(size, True))
        self.widths = [d.textlength(t, font=font(size, not ar), direction='rtl' if ar else 'ltr') for ar, t in self.runs]
        self.width = sum(self.widths) + self.gap * max(0, len(self.runs) - 1)

    def draw(self, d, x, y, fill):
        for (ar, t), w in zip(self.runs, self.widths):
            d.text((x, y + (0 if ar else self.size * 0.18)), t, font=font(self.size, not ar), fill=fill,
                   direction='rtl' if ar else 'ltr')
            x += w + self.gap


def rounded_mask(w, h, r):
    m = Image.new('L', (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return np.asarray(m, np.float32) / 255.0


def to_rgba_np(img):
    a = np.asarray(img.convert('RGBA'), np.float32)
    return a[..., [2, 1, 0]], a[..., 3:4] / 255.0      # BGR, alpha


def chapter_card(number, title, accent=(242, 3, 10)):
    f_n = font(24, True)
    mt = Mixed(title, 50)
    tw = int(mt.width)
    w, h = max(tw + 110, 360), 150
    pad = 40
    ac = tuple(accent) + (255,)
    img = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 8, pad + w, pad + h + 8), 22, fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, pad + w, pad + h), 22, fill=(14, 14, 20, 228), outline=(255, 255, 255, 40), width=2)
    d.rounded_rectangle((pad + 22, pad + 26, pad + 30, pad + h - 26), 4, fill=ac)
    d.text((pad + 52, pad + 26), f'CHAPTER {number}', font=f_n, fill=ac)
    mt.draw(d, pad + 52, pad + 52, (255, 255, 255, 255))
    return img


PILL_PAD = 36                # transparent margin around the pill for its shadow


def key_pill(keys, label='', max_w=1000):
    """Dark glass pill: keycaps joined by "+", optional label (left of the keys when Darija)."""
    ks, ps, ls = 34, 26, 30
    while True:
        fk, fp = font(ks, True), font(ps, True)
        d = ImageDraw.Draw(Image.new('L', (1, 1)))
        caps = [(k, d.textlength(k, font=fk)) for k in keys]
        plus_w = d.textlength('+', font=fp)
        cap_h = ks + 2 * 10 + 6
        keys_w = sum(w + 36 for _, w in caps) + (len(caps) - 1) * (plus_w + 24)
        ml = Mixed(label, ls) if label else None
        content_w = keys_w + (18 + ml.width if ml else 0)
        w, h = int(content_w) + 2 * 22, cap_h + 2 * 16
        if w <= max_w or ks <= 20:
            break
        ks, ps, ls = ks - 2, ps - 2, ls - 2
    pad = PILL_PAD
    img = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 8, pad + w, pad + h + 8), 22, fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(16)))
    box = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle((pad, pad, pad + w, pad + h), 22, fill=(14, 14, 20, 225),
                                          outline=(255, 255, 255, 40), width=2)
    img = Image.alpha_composite(img, box)
    # translucent caps and text go on their own layers: ImageDraw replaces RGBA pixels, it does not blend
    cap_l, txt_l = Image.new('RGBA', img.size, (0, 0, 0, 0)), Image.new('RGBA', img.size, (0, 0, 0, 0))
    dc, dt = ImageDraw.Draw(cap_l), ImageDraw.Draw(txt_l)
    cy = pad + h / 2
    x = pad + 22
    if ml and ml.rtl:
        ml.draw(dt, x, cy - ls * 0.92, (229, 231, 235, 255))
        x += ml.width + 18
    for j, (k, kw) in enumerate(caps):
        if j:
            dt.text((x + 12 + plus_w / 2, cy), '+', font=fp, fill=(255, 255, 255, 115), anchor='mm')
            x += plus_w + 24
        dc.rounded_rectangle((x, cy - cap_h / 2, x + kw + 36, cy + cap_h / 2), 10,
                             fill=(255, 255, 255, 26), outline=(255, 255, 255, 70), width=2)
        dt.text((x + 18 + kw / 2, cy), k, font=fk, fill=(255, 255, 255, 255), anchor='mm')
        x += kw + 36
    if ml and not ml.rtl:
        ml.draw(dt, x + 18, cy - ls * 0.92, (229, 231, 235, 255))
    return Image.alpha_composite(Image.alpha_composite(img, cap_l), txt_l)


def pill_y(pill_h, pos, captions):
    """Top of the pill image (shadow margin included) for its position."""
    if pos == 'top':
        return 90 - PILL_PAD
    return H - (230 if captions else 110) - (pill_h - 2 * PILL_PAD) - PILL_PAD


def caption_img(text, max_w=1380, size=46):
    lines, cur = [], ''
    for wd in text.split():
        t = (cur + ' ' + wd).strip()
        if cur and Mixed(t, size).width > max_w:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    ms = [Mixed(l, size) for l in lines[:2]]
    lh = 66
    w, h = int(max(m.width for m in ms)) + 56, lh * len(ms) + 26
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    dd.rounded_rectangle((0, 0, w - 1, h - 1), 16, fill=(0, 0, 0, 170))
    for i, m in enumerate(ms):
        m.draw(dd, (w - m.width) / 2, 6 + i * lh, (255, 255, 255, 255))
    return img


def caption_groups(words, max_chars=48, max_dur=3.6, gap=0.6):
    groups, cur = [], []
    for w in words:
        if cur and (w['s'] - cur[-1]['e'] > gap or len(' '.join(x['w'] for x in cur + [w])) > max_chars
                    or w['e'] - cur[0]['s'] > max_dur):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return [(g[0]['s'], g[-1]['e'], ' '.join(x['w'] for x in g)) for g in groups]


def final_words(vd, tl):
    """Transcript words in FINAL-video time (hook words as is, body words through the cuts)."""
    p = os.path.join(vd, 'work', 'tx', 'words.json')
    if not os.path.isfile(p):
        return []
    hs = TL.frames(tl['hook_split']) / FPS
    segs = TL.body_segments(tl)
    out = []
    for w in json.load(open(p, encoding='utf-8')):
        if w['s'] < hs:
            if w['e'] <= hs:
                out.append(dict(w))
            continue
        for s in segs:
            if s['src_start'] <= w['s'] < s['src_end']:
                d = hs + s['out_start'] - s['src_start']
                out.append({'w': w['w'], 's': w['s'] + d, 'e': min(w['e'], s['src_end']) + d})
                break
    return out


def blend(frame, bgr, alpha, x, y, opacity=1.0):
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sb, sa = bgr[y0 - y:y1 - y, x0 - x:x1 - x], alpha[y0 - y:y1 - y, x0 - x:x1 - x] * opacity
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (roi * (1 - sa) + sb * sa).astype(np.uint8)


class CamPiP:
    """The webcam, cut from the ORIGINAL frame and re-composited at a fixed spot on the stage
    (ev2_pro.pip_rect: the same spot the hook uses), rounded, bordered, with a soft shadow."""
    def __init__(self, rect, radius=22):
        self.rect, self.radius = rect, radius
        x, y, w, h = rect
        pad = 34
        img = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((pad, pad + 10, pad + w, pad + h + 10), radius, fill=(0, 0, 0, 170))
        img = img.filter(ImageFilter.GaussianBlur(16))
        ImageDraw.Draw(img).rounded_rectangle((pad - 3, pad - 3, pad + w + 2, pad + h + 2), radius + 3,
                                              outline=(255, 255, 255, 230), width=3)
        self.sb, self.sa = to_rgba_np(img)
        self.m = rounded_mask(w, h, radius)[..., None]
        self.pad = pad

    def draw(self, frame, src, box, opacity=1.0):
        bx, by, bw, bh = [int(round(v)) for v in box]
        if bw < 20 or bh < 20 or opacity <= 0.01:
            return
        crop = src[max(0, by + 3):by + bh - 3, max(0, bx + 3):bx + bw - 3]
        if crop.size == 0:
            return
        x, y, w, h = self.rect
        blend(frame, self.sb, self.sa, x - self.pad, y - self.pad, opacity)
        big = cv2.resize(crop, (w, h), interpolation=cv2.INTER_CUBIC)
        blend(frame, big.astype(np.float32), self.m, x, y, opacity)


def paint_out_fast(frame, box, pad=10):
    """Paint the burned-in webcam out of the source frame (in place), so no second face shows
    when the screen is zoomed or inset."""
    x, y, w, h = [int(round(v)) for v in box]
    hh, ww = frame.shape[:2]
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(ww, x + w + pad), min(hh, y + h + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return
    r = 18
    X0, Y0, X1, Y1 = max(0, x0 - r), max(0, y0 - r), min(ww, x1 + r), min(hh, y1 + r)
    reg = frame[Y0:Y1, X0:X1]
    m = np.zeros(reg.shape[:2], np.uint8)
    m[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = 255
    sw, sh = max(4, (X1 - X0) // 3), max(4, (Y1 - Y0) // 3)
    small = cv2.resize(reg, (sw, sh), interpolation=cv2.INTER_AREA)
    ms = cv2.resize(m, (sw, sh), interpolation=cv2.INTER_NEAREST)
    fill = cv2.inpaint(small, ms, 4, cv2.INPAINT_TELEA)
    fill = cv2.GaussianBlur(cv2.resize(fill, (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_LINEAR), (0, 0), 4)
    reg[m > 0] = fill[m > 0]


# ------------------------------------------------------------------ 4. render
class InsertReader:
    def __init__(self, path, n, alpha):
        pix, ch = ('bgra', 4) if alpha else ('bgr24', 3)
        self.p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-frames:v', str(n),
                                   '-vf', f'scale={W}:{H}', '-pix_fmt', pix, '-f', 'rawvideo', '-'],
                                  stdout=subprocess.PIPE)
        self.size, self.ch, self.name = W * H * ch, ch, path

    def read(self):
        b = self.p.stdout.read(self.size)
        if len(b) < self.size:
            raise SystemExit(f'body: {self.name} ended early (re-run `ev2 inserts`)')
        return np.frombuffer(b, np.uint8).reshape(H, W, self.ch)

    def close(self):
        self.p.stdout.close()
        self.p.wait()


def _scale_about_center(img, s):
    if abs(s - 1.0) < 1e-3:
        return img
    M = np.array([[s, 0, W / 2 * (1 - s)], [0, s, H / 2 * (1 - s)]], np.float32)
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def composite_insert(out_f, fr, mode, a, entering=True):
    """Full inserts arrive with a zoom-through: the screen pushes in and blurs while the scene
    settles from slightly larger. 'over' inserts sit on a dimmed, blurred screen."""
    if mode == 'full':
        if a >= 0.999:
            return fr[..., :3].copy()
        e = a * a * (3 - 2 * a)
        base = _scale_about_center(out_f, 1.0 + 0.10 * e)
        k = int(1 + 14 * e) | 1
        base = cv2.GaussianBlur(base, (k, k), 0) if k > 1 else base
        top = _scale_about_center(fr[..., :3], 1.06 - 0.06 * e)
        return (base.astype(np.float32) * (1 - e) + top.astype(np.float32) * e).astype(np.uint8)
    small = cv2.resize(out_f, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    bg = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6), (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32) * 0.45
    base = out_f.astype(np.float32) * (1 - a) + bg * a
    al = (fr[..., 3:4].astype(np.float32) / 255.0) * a
    return (base * (1 - al) + fr[..., :3].astype(np.float32) * al).astype(np.uint8)


# ------------------------------------------------------------------ the stage (inset framing)
class Stage:
    """The screen as a rounded card on the video's backdrop (look.frame = inset), or edge to edge."""
    def __init__(self, vd, look, content):
        import ev2_pro as P
        self.content = content
        x, y, w, h, r = P.stage_geometry(look, content)
        self.rect, self.r = (x, y, w, h), r
        self.inset = r > 0
        if self.inset:
            bg = cv2.imread(os.path.join(vd, 'assets', 'pro', 'bg.png'))
            if bg is None or bg.shape[:2] != (H, W):
                bg = np.zeros((H, W, 3), np.uint8)
            # soft shadow + a hairline rim, painted into the backdrop once
            sh = Image.new('L', (W, H), 0)
            ImageDraw.Draw(sh).rounded_rectangle((x, y + 22, x + w, y + h + 22), r + 6, fill=150)
            sh = np.asarray(sh.filter(ImageFilter.GaussianBlur(34)), np.float32)[..., None] / 255.0
            bg = (bg.astype(np.float32) * (1 - sh * 0.85)).astype(np.uint8)
            rim = Image.new('L', (W, H), 0)
            ImageDraw.Draw(rim).rounded_rectangle((x - 2, y - 2, x + w + 1, y + h + 1), r + 2, outline=255, width=2)
            rim = np.asarray(rim, np.float32)[..., None] / 255.0 * 0.22
            self.bg = (bg.astype(np.float32) * (1 - rim) + 255 * rim).astype(np.uint8)
            m = rounded_mask(w, h, r)
            self.corners = []
            for (cx0, cy0) in ((0, 0), (w - r, 0), (0, h - r), (w - r, h - r)):
                self.corners.append((cx0, cy0, m[cy0:cy0 + r, cx0:cx0 + r][..., None]))

    def view(self, cx, cy, z):
        """(x0, y0, k): the source view's top-left and the source->stage scale."""
        ox, oy, cw, ch = self.content if self.inset else (0, 0, W, H)
        vw, vh = cw / z, ch / z
        x0, y0 = cx - vw / 2, cy - vh / 2
        return x0, y0, self.rect[2] / vw

    def to_stage(self, px, py, v):
        x0, y0, k = v
        return self.rect[0] + (px - x0) * k, self.rect[1] + (py - y0) * k

    def compose(self, src, v):
        x0, y0, k = v
        x, y, w, h = self.rect
        M = np.array([[k, 0, -x0 * k], [0, k, -y0 * k]], np.float32)
        card = cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if not self.inset:
            return card
        out = self.bg.copy()
        out[y:y + h, x:x + w] = card
        r = self.r
        for cx0, cy0, m in self.corners:
            sl = (slice(y + cy0, y + cy0 + r), slice(x + cx0, x + cx0 + r))
            out[sl] = (card[cy0:cy0 + r, cx0:cx0 + r].astype(np.float32) * m
                       + self.bg[sl].astype(np.float32) * (1 - m)).astype(np.uint8)
        return out


def draw_ripple(frame, x, y, e, color, scale=1.0):
    """A click: an accent ring that expands and fades (e: 0 -> 1), with a soft core."""
    R = int(70 * scale) + 4
    x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = max(0, x - R), max(0, y - R), min(W, x + R), min(H, y + R)
    if x1 <= x0 or y1 <= y0:
        return
    patch = frame[y0:y1, x0:x1]
    over = patch.copy()
    eo = 1 - (1 - e) ** 3
    rad = int((12 + 46 * eo) * scale)
    cv2.circle(over, (x - x0, y - y0), rad, color, max(2, int(4 * scale)), cv2.LINE_AA)
    if e < 0.6:
        cv2.circle(over, (x - x0, y - y0), max(2, int(14 * scale * (1 - e / 0.6))), (255, 255, 255), -1, cv2.LINE_AA)
    a = 0.85 * (1 - e) ** 1.4
    frame[y0:y1, x0:x1] = cv2.addWeighted(over, a, patch, 1 - a, 0)


def callout_img(text, accent):
    """An accent pill with the callout text (Darija/French), and its pointer dot position."""
    size = 36
    mt = Mixed(text, size)
    w, h = int(mt.width) + 56, size + 40
    pad = 30
    img = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 8, pad + w, pad + h + 8), h // 2, fill=(0, 0, 0, 140))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, pad + w, pad + h), h // 2, fill=tuple(accent) + (255,))
    mt.draw(d, pad + 28, pad + 8, (255, 255, 255, 255))
    return img


def resolve_callouts(tl, inp, act, segs):
    """Callouts from timeline.json -> [(f0, n, x, y, text)] in body frames + SOURCE coords. The
    target is the given x/y, else the click nearest the moment, else the action at that moment."""
    out = []
    clicks = sorted((inp or {}).get('clicks') or [], key=lambda c: c['t'])
    for c in tl.get('callouts') or []:
        f0 = src_to_body_frame(segs, float(c['src_t']))
        if f0 is None:
            bt = TL.src_to_body(tl, float(c['src_t']))
            if bt is None:
                continue
            f0 = int(round(bt * FPS))
        x, y = c.get('x'), c.get('y')
        if x is None or y is None:
            near = [k for k in clicks if -1.0 <= k['t'] - c['src_t'] <= 3.0]
            if near:
                x, y = near[0]['x'], near[0]['y']
            else:
                k = int(min(len(act['bbox']) - 1, max(0, round(float(c['src_t']) * AF))))
                bb = act['bbox'][k:k + 10]
                bb = bb[bb[:, 0] >= 0]
                if not len(bb):
                    continue
                x, y = float(np.median((bb[:, 0] + bb[:, 2]) / 2)), float(np.median((bb[:, 1] + bb[:, 3]) / 2))
        out.append((f0, int(round(float(c.get('dur', 3.0)) * FPS)), float(x), float(y), str(c['text'])))
    return out


def auto_pills(inp, segs, user_pills):
    """Shortcut pills from the input log (modifier combos), where the timeline has none."""
    out = []
    for k in (inp or {}).get('keys') or []:
        f0 = src_to_body_frame(segs, float(k['t']))
        if f0 is None:
            continue
        n = int(2.2 * FPS)
        if any(not (f0 + n <= p['f0'] or f0 >= p['f0'] + p['n']) for p in user_pills + out):
            continue
        out.append({'i': -1, 'keys': list(k['combo']), 'label': k.get('label', ''), 'f0': f0, 'n': n,
                    'body_t': f0 / FPS, 'dur': n / FPS, 'sfx': True, 'pos': 'bottom', 'src_t': float(k['t'])})
    return out


def write_fx_cues(vd, cues):
    """work/body_fx_cues.txt: the body's own sounds (clicks, chapter whooshes, insert whooshes,
    callout pops) in body time, mixed by finish.py."""
    sys.path.insert(0, os.path.join(SK, 'components'))
    from ev1_devices import SND
    lines = ['# body fx in body time (written by body_render.py)']
    for t, role, g in sorted(cues):
        name, gain, pre = SND[role]
        lines.append(f'{max(0.0, t - pre):.3f}  {name}  {gain * g:.3f}')
    open(os.path.join(vd, 'work', 'body_fx_cues.txt'), 'w').write('\n'.join(lines) + '\n')
    return len(cues)


RENDER_VERSION = 7


def render(vd, zoom=True, cam=True, captions=False, force=False, preset='veryfast', crf=16, keys=True, preview=None):
    """preview=(t0, t1) body seconds: render only that range to work/body_preview.mp4 (no cache)."""
    sys.path.insert(0, os.path.join(SK, 'components'))
    import ev2_pro as P
    tl = TL.load(vd)
    segs = TL.body_segments(tl)
    look, th = P.ensure_look(vd)
    accent_rgb = P.hex2rgb(th['accent'])
    accent_bgr = tuple(int(v) for v in accent_rgb[::-1])
    content = P.view_rect(vd, look)
    try:
        pills = TL.key_ranges(tl) if keys else []
    except TL.TimelineError as e:
        raise SystemExit(f'body: {e} (edit "keys" in work/timeline.json, or run with --no-keys)')
    ins_list = TL.insert_ranges(tl)
    ins_paths = [TL.insert_render_path(vd, ins) for ins in ins_list]
    for ins, p in zip(ins_list, ins_paths):
        if not os.path.isfile(p):
            raise SystemExit(f'body: insert "{ins["name"]}" has no render ({p}): run `ev2 inserts <video-dir>`')
    act = analyze(vd)
    inp = load_inputs(vd)
    stage = Stage(vd, look, content)
    if not zoom:
        plan = {'n_frames': sum(s['f_end'] - s['f_start'] for s in segs), 'keys': [], 'zoomed_share': 0, 'source': 'off'}
    elif inp:
        plan = plan_camera_inputs(tl, inp, look['max_zoom'], content if stage.inset else (0, 0, W, H))
    else:
        plan = plan_camera(tl, act, look['max_zoom'], content if stage.inset else (0, 0, W, H))
    plan['max_zoom'] = look['max_zoom']
    json.dump(plan, open(os.path.join(vd, 'work', 'zoom_plan.json'), 'w'), indent=1)
    hs = TL.frames(tl['hook_split']) / FPS
    chapters = [(t - hs, title) for t, title in TL.final_chapters(tl, hs) if t >= hs - 1e-6]
    caps = []
    if captions:
        caps = [(s - hs, e - hs, txt) for s, e, txt in caption_groups(final_words(vd, tl)) if s >= hs]
    if keys and inp and look.get('auto_keys', True):
        pills = sorted(pills + auto_pills(inp, segs, pills), key=lambda p: p['f0'])
    clicks = []
    if inp and look.get('click_fx', True):
        for c in inp.get('clicks') or []:
            f = src_to_body_frame(segs, float(c['t']))
            if f is not None:
                clicks.append((f, float(c['x']), float(c['y'])))
    callouts = resolve_callouts(tl, inp, act, segs)
    out = os.path.join(vd, 'work', 'body_video.mp4')
    stamp_p = os.path.join(vd, 'work', 'body_video.json')
    st = os.stat(os.path.join(vd, 'assets', 'media', 'cam_raw.mp4'))
    parts = [RENDER_VERSION, TL.cut_signature(tl), plan['keys'], chapters, caps, cam, st.st_size, int(st.st_mtime),
             look, clicks, callouts, str(act['key'])]
    if ins_list:
        parts.append([(ins, os.path.getsize(p), int(os.path.getmtime(p))) for ins, p in zip(ins_list, ins_paths)])
    if pills:
        parts.append(['pills', pills])
    key = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # the body's own sounds (always rewritten: cheap, and finish mixes them)
    cues = []
    if look.get('click_sfx', True):
        last = -99
        for f, _, _ in clicks:
            if f - last >= 4:
                cues.append((f / FPS, 'click_soft', 0.55))
                last = f
    if look.get('chapter_sfx', True):
        for t, _ in chapters:
            if t > 0.5:
                cues.append((t, 'swish', 0.6))
    for f0, n, *_ in callouts:
        cues.append((f0 / FPS, 'click', 0.6))
    for pl in pills:
        if pl.get('i') == -1:
            cues.append((pl['body_t'], 'key_click', 0.8))
    for ins in ins_list:
        if ins['mode'] == 'full':
            cues.append((ins['body_t'] + 0.05, 'swish', 0.7))
            cues.append((ins['body_t'] + ins['dur'] - 0.12, 'swish', 0.5))
    write_fx_cues(vd, cues)

    if preview is None and not force and os.path.isfile(out) and os.path.isfile(stamp_p) and json.load(open(stamp_p)).get('key') == key:
        log(f'body_video.mp4 is up to date ({plan["zoomed_share"] * 100:.0f}% zoomed)')
        return plan
    i_from, i_to = 0, plan['n_frames']
    if preview is not None:
        i_from = max(0, int(preview[0] * FPS))
        i_to = min(plan['n_frames'], int(preview[1] * FPS))
        out = os.path.join(vd, 'work', 'body_preview.mp4')
    cx, cy, z = camera_curve(plan, content if stage.inset else (0, 0, W, H))
    n = plan['n_frames']
    src_list = body_src_frames(segs)
    na = len(act['cam'])
    cam_ok = act['cam'][:, 0] >= 0
    med_box = tuple(np.median(act['cam'][cam_ok], axis=0)) if cam_ok.any() else None
    pip = CamPiP(P.pip_rect(med_box)) if (cam and med_box is not None) else None

    hc = os.path.join(vd, 'work', 'hook_chapters.json')   # body cards continue the hook's numbering
    first = 1 + (sum(1 for x in json.load(open(hc, encoding='utf-8')) if float(x.get('time', 0)) > 0.05)
                 if os.path.isfile(hc) else 0)
    ch_imgs = [(t, to_rgba_np(chapter_card(f'{first + i:02d}', title, accent_rgb))) for i, (t, title) in enumerate(chapters)]
    cap_imgs = [(s, e, to_rgba_np(caption_img(txt))) for s, e, txt in caps]
    pill_imgs = []
    for pl in pills:
        img = key_pill(pl['keys'], pl['label'])
        pill_imgs.append((pl, (W - img.width) // 2, pill_y(img.height, pl['pos'], captions), to_rgba_np(img)))
    co_imgs = [(f0, nn, x, y, to_rgba_np(callout_img(txt, accent_rgb))) for f0, nn, x, y, txt in callouts]

    enc = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                            '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', preset,
                            '-crf', str(crf), '-pix_fmt', 'yuv420p', '-g', str(FPS * 2), '-r', str(FPS), out + '.tmp.mp4'],
                           stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(os.path.join(vd, 'assets', 'media', 'cam_raw.mp4'))
    cur_src, frame = -1, None
    if i_from > 0:
        start_src = int(src_list[i_from])
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start_src - 1))
        cur_src = max(0, start_src - 1) - 1
    log(f'rendering {i_to - i_from} of {n} frames ({n / FPS:.1f}s): {"inset stage" if stage.inset else "full frame"}, '
        f'{plan["zoomed_share"] * 100:.0f}% zoomed ({plan.get("source")}), {len(ch_imgs)} chapter cards, '
        f'{len(clicks)} click ripples, {len(co_imgs)} callouts, {len(cap_imgs)} captions, webcam PiP {"on" if pip else "off"}'
        + (f', {len(ins_list)} inserts' if ins_list else '') + (f', {len(pills)} key pills' if pills else ''))
    ii, reader, pi = 0, None, 0
    ci = 0
    for i in range(i_from, i_to):
        sf_ = int(src_list[i])
        while cur_src < sf_:
            ok = cap.grab()
            if not ok:
                raise SystemExit(f'body: cam_raw.mp4 ended at frame {cur_src}, needed {sf_}')
            cur_src += 1
            if cur_src == sf_:
                ok, frame = cap.retrieve()
        src = frame
        box = act['cam'][min(na - 1, int(sf_ / (FPS // AF)))]
        work = src
        if box[0] >= 0 and (stage.inset or z[i] > 1.001 or pip is not None):
            work = src.copy()
            paint_out_fast(work, box)
        v = stage.view(cx[i], cy[i], z[i])
        out_f = stage.compose(work, v)
        # clicks
        while ci < len(clicks) and clicks[ci][0] + 16 < i:
            ci += 1
        k = ci
        while k < len(clicks) and clicks[k][0] <= i:
            f, x, y = clicks[k]
            if i - f < 16:
                sx, sy = stage.to_stage(x, y, v)
                draw_ripple(out_f, sx, sy, (i - f) / 16, accent_bgr, min(1.4, v[2]))
            k += 1
        # callouts follow their target through the zooms
        for f0, nn, x, y, (bgr, al) in co_imgs:
            if f0 <= i < f0 + nn:
                kk = i - f0
                a = min(1.0, (kk + 1) / 7, (nn - kk) / 7)
                sx, sy = stage.to_stage(x, y, v)
                pulse = 0.5 + 0.5 * math.sin(kk / FPS * 2 * math.pi * 1.2)
                draw_ripple(out_f, sx, sy, 0.25 + 0.35 * pulse, accent_bgr, 1.0)
                ph, pw = bgr.shape[:2]
                px = int(min(W - pw - 20, max(20, sx - pw / 2)))
                py = int(sy - ph - 40) if sy - ph - 40 > 20 else int(sy + 40)
                py += int(round(18 * (1 - min(1.0, (kk + 1) / 7)) ** 3))
                blend(out_f, bgr, al, px, py, a)
        t = i / FPS
        while ii < len(ins_list) and i >= ins_list[ii]['f0'] + ins_list[ii]['n']:
            ii += 1
        cur = ins_list[ii] if ii < len(ins_list) and ins_list[ii]['f0'] <= i else None
        pip_a = 1.0
        if cur is not None:
            if reader is None:
                reader = InsertReader(ins_paths[ii], cur['n'], cur['mode'] == 'over')
                for _ in range(i - cur['f0']):
                    reader.read()
            kk = i - cur['f0']
            a = min(1.0, (kk + 1) / 10, (cur['n'] - kk) / 10)
            out_f = composite_insert(out_f, reader.read(), cur['mode'], a)
            if not cur['cam']:
                pip_a = 1.0 - a
            if kk == cur['n'] - 1:
                reader.close()
                reader = None
        if pip is not None and box[0] >= 0:
            pip.draw(out_f, src, box, pip_a)
        while pi < len(pill_imgs) and i >= pill_imgs[pi][0]['f0'] + pill_imgs[pi][0]['n']:
            pi += 1
        if pi < len(pill_imgs) and pill_imgs[pi][0]['f0'] <= i:
            pl, px, py, (bgr, al) = pill_imgs[pi]
            kk, pn = i - pl['f0'], pl['n']
            u = min(1.0, (kk + 1) / 5)
            a = min(u, (pn - kk) / 5)
            blend(out_f, bgr, al, px, py + int(round(14 * (1 - u) ** 3)), a)
        for ct, (bgr, al) in ch_imgs:
            dt = t - ct
            if -0.01 <= dt <= 3.6:
                a = min(1.0, dt / 0.35, (3.6 - dt) / 0.35)
                e = 1 - (1 - min(1.0, dt / 0.45)) ** 3
                blend(out_f, bgr, al, int(40 - 50 * (1 - e)), H - 70 - bgr.shape[0] + 40, max(0.0, a))
        for s_, e_, (bgr, al) in cap_imgs:
            if s_ <= t < e_:
                blend(out_f, bgr, al, (W - bgr.shape[1]) // 2 - 120, H - 60 - bgr.shape[0])
        enc.stdin.write(out_f.tobytes())
        if i % (FPS * 30) == 0 and i:
            log(f'  {i / FPS:6.0f}s / {n / FPS:.0f}s')
    enc.stdin.close()
    if enc.wait():
        raise SystemExit('body: encoding body_video.mp4 failed')
    os.replace(out + '.tmp.mp4', out)
    if preview is not None:
        log(f'-> {out} (preview {i_from / FPS:.1f}-{i_to / FPS:.1f}s)')
        return plan
    stamp = {'key': key, 'frames': n, 'zoomed_share': plan['zoomed_share'], 'zoom_source': plan.get('source'),
             'max_zoom': float(np.max(z)) if len(z) else 1.0, 'frame': look.get('frame'), 'clicks': len(clicks),
             'callouts': len(co_imgs), 'inserts': [ins['name'] for ins in ins_list], 'pip': pip is not None}
    if pills:
        stamp['pills'] = len(pills)
    json.dump(stamp, open(stamp_p, 'w'))
    log(f'-> work/body_video.mp4 ({n} frames)')
    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--no-zoom', action='store_true')
    ap.add_argument('--no-cam', action='store_true')
    ap.add_argument('--captions', action='store_true', help='Burn captions into the body (check the transcript first)')
    ap.add_argument('--no-keys', action='store_true', help='Skip the key pills from timeline.json for this run')
    ap.add_argument('--plan-only', action='store_true')
    ap.add_argument('--preview', metavar='T0,T1', help='render only body seconds T0-T1 to work/body_preview.mp4')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    vd = os.path.abspath(a.video_dir)
    if a.plan_only:
        sys.path.insert(0, os.path.join(SK, 'components'))
        import ev2_pro as P
        look, _ = P.ensure_look(vd)
        content = P.view_rect(vd, look)
        tl, inp = TL.load(vd), load_inputs(vd)
        p = plan_camera_inputs(tl, inp, look['max_zoom'], content) if inp else plan_camera(tl, analyze(vd), look['max_zoom'], content)
        json.dump(p, open(os.path.join(vd, 'work', 'zoom_plan.json'), 'w'), indent=1)
        print(f'{len(p["keys"])} camera moves ({p["source"]}), {p["zoomed_share"] * 100:.0f}% of the body zoomed')
        return
    pv = tuple(float(x) for x in a.preview.split(',')) if a.preview else None
    render(vd, zoom=not a.no_zoom, cam=not a.no_cam, captions=a.captions, force=a.force, keys=not a.no_keys, preview=pv)


if __name__ == '__main__':
    main()
