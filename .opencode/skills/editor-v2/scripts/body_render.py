#!/usr/bin/env python3
"""body_render.py — the polished tutorial body: auto zooms, styled webcam, chapter cards, captions.

    body_render.py <video-dir> [--no-zoom] [--no-cam] [--captions] [--plan-only]

1. analyze(): screen activity of assets/media/cam_raw.mp4 at 5 fps (what changes where:
   typing, pointing, menus, page loads) + where the Omarchy webcam is (face tracking at 1 fps,
   starting from work/omarchy.json). Cached in work/activity.npz.
2. plan_camera(): on the cleaned body timeline (work/timeline.json), zoom in where the
   activity is localized (<= 30% of the screen) for >= 1.2 s, follow it, zoom out on page
   changes or after a quiet spell. Eased 0.5 s moves, max zoom 2.0x. -> work/zoom_plan.json
3. render(): every kept body frame is zoomed (sub-pixel), the webcam is re-composited as a
   larger rounded PiP that never zooms away, chapter lower-thirds slide in at each chapter
   from timeline.json, optional burned-in captions. Explainer inserts (timeline.json "inserts",
   renders in work/inserts/) replace the picture (full) or are drawn over a dimmed, blurred
   picture (over), with the webcam PiP kept on top. -> work/body_video.mp4 (silent, exact
   frame count), cached against all of its inputs.
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
PLAN_VERSION = 5


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
def plan_camera(tl, act, max_zoom=2.0):
    segs = TL.body_segments(tl)
    n_out = sum(s['f_end'] - s['f_start'] for s in segs)
    src_f = np.empty(n_out, np.int64)
    pos = 0
    for s in segs:
        k = s['f_end'] - s['f_start']
        src_f[pos:pos + k] = np.arange(s['f_start'], s['f_end'])
        pos += k
    step = FPS // AF
    ticks = list(range(0, n_out, step))
    na = len(act['frac'])
    ai = np.clip((src_f[ticks] / step).round().astype(int), 0, na - 1)
    frac, bbox = act['frac'][ai], act['bbox'][ai]
    scene = frac > 0.20
    LOOK, MIN_START, QUIET_OUT, SCENE_HOLD, MIN_WIDE, MIN_HOLD, CLEAR_AHEAD = 8, 6, 30, 5, 7, 13, 13
    targets, cur, since_scene, quiet, stable, last_change = [], None, 99, 0, 0, -99

    def window_box(j):
        bs = [bbox[k] for k in range(j, min(len(ticks), j + LOOK)) if not scene[k] and bbox[k][0] >= 0 and frac[k] > 0.00004]
        if len(bs) < 2:
            return None
        b = np.array(bs)
        return b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()

    def zoom_for(b):
        bw, bh = b[2] - b[0] + 220, b[3] - b[1] + 160
        if bw * bh > 0.30 * W * H:
            return None
        z = min(max_zoom, 0.92 * min(W / bw, H / bh))
        return z if z >= 1.3 else None

    def fits(b, t):
        cx, cy, z = t
        hw, hh = W / (2 * z), H / (2 * z)
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
    # shift every change 2 ticks (0.4 s) earlier so the move starts as the action does
    targets = targets[2:] + [targets[-1]] * 2 if len(targets) > 2 else targets
    keys = []
    prev = 'none'
    for j, t in enumerate(targets):
        tt = None if t is None else (round(t[0], 1), round(t[1], 1), round(t[2], 3))
        if tt != prev:
            keys.append({'f': ticks[j], 'cx': W / 2 if tt is None else tt[0], 'cy': H / 2 if tt is None else tt[1],
                         'z': 1.0 if tt is None else tt[2]})
            prev = tt
    return {'n_frames': int(n_out), 'keys': keys, 'zoomed_share': float(np.mean([t is not None for t in targets])) if targets else 0}


def camera_curve(plan, ease_frames=15):
    n = plan['n_frames']
    cx, cy, lz = np.full(n, W / 2), np.full(n, H / 2), np.zeros(n)
    c = (W / 2, H / 2, 0.0)
    keys = plan['keys'] + [{'f': n}]
    for i in range(len(keys) - 1):
        k = keys[i]
        tgt = (k['cx'], k['cy'], math.log(max(1.0, k['z'])))
        a, b = k['f'], keys[i + 1]['f']
        for f in range(a, min(b, n)):
            u = min(1.0, (f - a) / ease_frames)
            e = u * u * (3 - 2 * u)
            cx[f], cy[f], lz[f] = (c[0] + (tgt[0] - c[0]) * e, c[1] + (tgt[1] - c[1]) * e, c[2] + (tgt[2] - c[2]) * e)
        if b > a:
            c = (cx[min(b, n) - 1], cy[min(b, n) - 1], lz[min(b, n) - 1])
    z = np.exp(lz)
    hw, hh = W / (2 * z), H / (2 * z)
    return np.clip(cx, hw, W - hw), np.clip(cy, hh, H - hh), z


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


def chapter_card(number, title):
    f_n = font(24, True)
    mt = Mixed(title, 50)
    tw = int(mt.width)
    w, h = max(tw + 110, 360), 150
    pad = 40
    img = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 8, pad + w, pad + h + 8), 22, fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, pad + w, pad + h), 22, fill=(14, 14, 20, 225), outline=(255, 255, 255, 40), width=2)
    d.rounded_rectangle((pad + 22, pad + 26, pad + 30, pad + h - 26), 4, fill=(242, 3, 10, 255))
    d.text((pad + 52, pad + 26), f'CHAPTER {number}', font=f_n, fill=(242, 3, 10, 255))
    mt.draw(d, pad + 52, pad + 52, (255, 255, 255, 255))
    return img


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
    """The webcam, cut from the ORIGINAL frame and re-composited larger, rounded, bordered."""
    def __init__(self, scale=1.35, radius=20):
        self.scale, self.radius, self.cache = scale, radius, {}

    def place(self, box):
        x, y, bw, bh = box
        nw, nh = int(bw * self.scale) // 2 * 2, int(bh * self.scale) // 2 * 2
        right, bottom = x + bw / 2 > W / 2, y + bh / 2 > H / 2
        nx = min(W - 28 - nw, x + bw - nw + 6) if right else max(28, x - 6)
        ny = min(H - 28 - nh, y + bh - nh + 6) if bottom else max(28, y - 6)
        return int(nx), int(ny), nw, nh

    def layers(self, nw, nh):
        k = (nw, nh)
        if k not in self.cache:
            pad = 30
            img = Image.new('RGBA', (nw + 2 * pad, nh + 2 * pad), (0, 0, 0, 0))
            ImageDraw.Draw(img).rounded_rectangle((pad, pad + 6, pad + nw, pad + nh + 6), self.radius, fill=(0, 0, 0, 160))
            img = img.filter(ImageFilter.GaussianBlur(14))
            ImageDraw.Draw(img).rounded_rectangle((pad - 3, pad - 3, pad + nw + 2, pad + nh + 2), self.radius + 3,
                                                  outline=(255, 255, 255, 220), width=3)
            sb, sa = to_rgba_np(img)
            self.cache[k] = (sb, sa, rounded_mask(nw, nh, self.radius)[..., None], pad)
        return self.cache[k]

    def draw(self, frame, src, box, cover=True):
        x, y, bw, bh = [int(round(v)) for v in box]
        if bw < 20 or bh < 20:
            return
        crop = src[max(0, y + 2):y + bh - 2, max(0, x + 2):x + bw - 2]
        if crop.size == 0:
            return
        nx, ny, nw, nh = self.place(box)
        if cover:
            # paint over the original webcam with the desktop colour around it, so no edge peeks out
            ring = np.concatenate([src[max(0, y - 14):max(0, y - 9), max(0, x):x + bw].reshape(-1, 3),
                                   src[max(0, y):y + bh, max(0, x - 14):max(0, x - 9)].reshape(-1, 3)])
            fill = np.median(ring, axis=0) if len(ring) else np.array([10, 10, 12])
            frame[max(0, y - 7):min(H, y + bh + 7), max(0, x - 7):min(W, x + bw + 7)] = fill.astype(np.uint8)
        sb, sa, m, pad = self.layers(nw, nh)
        blend(frame, sb, sa, nx - pad, ny - pad)
        big = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_CUBIC)
        blend(frame, big.astype(np.float32), m, nx, ny)


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


def composite_insert(out_f, fr, mode, a):
    if mode == 'full':
        return (out_f * (1 - a) + fr * a).astype(np.uint8)
    small = cv2.resize(out_f, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    bg = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6), (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32) * 0.45
    base = out_f.astype(np.float32) * (1 - a) + bg * a
    al = (fr[..., 3:4].astype(np.float32) / 255.0) * a
    return (base * (1 - al) + fr[..., :3].astype(np.float32) * al).astype(np.uint8)


def render(vd, zoom=True, cam=True, captions=False, force=False, preset='veryfast', crf=16):
    tl = TL.load(vd)
    segs = TL.body_segments(tl)
    ins_list = TL.insert_ranges(tl)
    ins_paths = [TL.insert_render_path(vd, ins) for ins in ins_list]
    for ins, p in zip(ins_list, ins_paths):
        if not os.path.isfile(p):
            raise SystemExit(f'body: insert "{ins["name"]}" has no render ({p}): run `ev2 inserts <video-dir>`')
    act = analyze(vd)
    plan = plan_camera(tl, act) if zoom else {'n_frames': sum(s['f_end'] - s['f_start'] for s in segs), 'keys': [], 'zoomed_share': 0}
    json.dump(plan, open(os.path.join(vd, 'work', 'zoom_plan.json'), 'w'), indent=1)
    hs = TL.frames(tl['hook_split']) / FPS
    chapters = [(t - hs, title) for t, title in TL.final_chapters(tl, hs) if t >= hs - 1e-6]
    caps = []
    if captions:
        caps = [(s - hs, e - hs, txt) for s, e, txt in caption_groups(final_words(vd, tl)) if s >= hs]
    out = os.path.join(vd, 'work', 'body_video.mp4')
    stamp_p = os.path.join(vd, 'work', 'body_video.json')
    st = os.stat(os.path.join(vd, 'assets', 'media', 'cam_raw.mp4'))
    parts = [PLAN_VERSION, TL.cut_signature(tl), plan['keys'], chapters, caps, cam, st.st_size, int(st.st_mtime)]
    if ins_list:
        parts.append([(ins, os.path.getsize(p), int(os.path.getmtime(p))) for ins, p in zip(ins_list, ins_paths)])
    key = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]
    if not force and os.path.isfile(out) and os.path.isfile(stamp_p) and json.load(open(stamp_p)).get('key') == key:
        log(f'body_video.mp4 is up to date ({plan["zoomed_share"] * 100:.0f}% zoomed)')
        return plan
    cx, cy, z = camera_curve(plan)
    n = plan['n_frames']
    src_list = np.concatenate([np.arange(s['f_start'], s['f_end']) for s in segs])
    na = len(act['cam'])

    pip = CamPiP() if cam else None
    hc = os.path.join(vd, 'work', 'hook_chapters.json')   # body cards continue the hook's numbering
    first = 1 + (sum(1 for x in json.load(open(hc, encoding='utf-8')) if float(x.get('time', 0)) > 0.05)
                 if os.path.isfile(hc) else 0)
    ch_imgs = [(t, to_rgba_np(chapter_card(f'{first + i:02d}', title))) for i, (t, title) in enumerate(chapters)]
    cap_imgs = [(s, e, to_rgba_np(caption_img(txt))) for s, e, txt in caps]

    enc = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                            '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', preset,
                            '-crf', str(crf), '-pix_fmt', 'yuv420p', '-g', str(FPS * 2), '-r', str(FPS), out + '.tmp.mp4'],
                           stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(os.path.join(vd, 'assets', 'media', 'cam_raw.mp4'))
    cur_src, frame = -1, None
    log(f'rendering {n} frames ({n / FPS:.1f}s): {plan["zoomed_share"] * 100:.0f}% zoomed, '
        f'{len(ch_imgs)} chapter cards, {len(cap_imgs)} captions, webcam PiP {"on" if pip else "off"}'
        + (f', {len(ins_list)} inserts' if ins_list else ''))
    ii, reader = 0, None
    for i in range(n):
        sf = int(src_list[i])
        while cur_src < sf:
            ok = cap.grab()
            if not ok:
                raise SystemExit(f'body: cam_raw.mp4 ended at frame {cur_src}, needed {sf}')
            cur_src += 1
            if cur_src == sf:
                ok, frame = cap.retrieve()
        src = frame
        if z[i] > 1.001:
            M = np.array([[z[i], 0, W / 2 - z[i] * cx[i]], [0, z[i], H / 2 - z[i] * cy[i]]])
            out_f = cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        else:
            out_f = src.copy()
        t = i / FPS
        while ii < len(ins_list) and i >= ins_list[ii]['f0'] + ins_list[ii]['n']:
            ii += 1
        cur = ins_list[ii] if ii < len(ins_list) and ins_list[ii]['f0'] <= i else None
        if cur is not None:
            if reader is None:
                reader = InsertReader(ins_paths[ii], cur['n'], cur['mode'] == 'over')
            k = i - cur['f0']
            a = min(1.0, (k + 1) / 9, (cur['n'] - k) / 9)
            out_f = composite_insert(out_f, reader.read(), cur['mode'], a)
            if k == cur['n'] - 1:
                reader.close()
                reader = None
        if pip is not None and (cur is None or cur['cam']):
            box = act['cam'][min(na - 1, int(sf / (FPS // AF)))]
            if box[0] >= 0:
                if cur is None:
                    pip.draw(out_f, src, box)
                else:
                    pip.draw(out_f, src, box, cover=False)
        for ct, (bgr, al) in ch_imgs:
            dt = t - ct
            if -0.01 <= dt <= 3.6:
                a = min(1.0, dt / 0.35, (3.6 - dt) / 0.35)
                e = 1 - (1 - min(1.0, dt / 0.45)) ** 3
                blend(out_f, bgr, al, int(40 - 50 * (1 - e)), H - 70 - bgr.shape[0] + 40, max(0.0, a))
        for s, e, (bgr, al) in cap_imgs:
            if s <= t < e:
                blend(out_f, bgr, al, (W - bgr.shape[1]) // 2 - 120, H - 60 - bgr.shape[0])
        enc.stdin.write(out_f.tobytes())
        if i % (FPS * 30) == 0 and i:
            log(f'  {i / FPS:6.0f}s / {n / FPS:.0f}s')
    enc.stdin.close()
    if enc.wait():
        raise SystemExit('body: encoding body_video.mp4 failed')
    os.replace(out + '.tmp.mp4', out)
    json.dump({'key': key, 'frames': n, 'zoomed_share': plan['zoomed_share'],
               'inserts': [ins['name'] for ins in ins_list]}, open(stamp_p, 'w'))
    log(f'-> work/body_video.mp4 ({n} frames)')
    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--no-zoom', action='store_true')
    ap.add_argument('--no-cam', action='store_true')
    ap.add_argument('--captions', action='store_true', help='Burn captions into the body (check the transcript first)')
    ap.add_argument('--plan-only', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    vd = os.path.abspath(a.video_dir)
    if a.plan_only:
        p = plan_camera(TL.load(vd), analyze(vd))
        json.dump(p, open(os.path.join(vd, 'work', 'zoom_plan.json'), 'w'), indent=1)
        print(f'{len(p["keys"])} camera moves, {p["zoomed_share"] * 100:.0f}% of the body zoomed')
        return
    render(vd, zoom=not a.no_zoom, cam=not a.no_cam, captions=a.captions, force=a.force)


if __name__ == '__main__':
    main()
