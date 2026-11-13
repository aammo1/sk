#!/usr/bin/env python3
"""inputs.py — turn an `ev2 rec` log into work/inputs.json: clicks, typing spans, shortcuts and
the cursor path in SOURCE seconds and cam_raw.mp4 pixels (1920x1080).

    inputs.py <video-dir> [--recording ORIGINAL.mp4] [--log LOG.json] [--offset S]

The log is found by the recording's file name (~/.local/share/editor-v2/inputs/<name>.json).
Time: the log's clock is aligned to the video by matching cursor movement to where the screen
changes under the cursor (searched +-1.5 s around the recorder's start); --offset forces it.
Without click data (no access to /dev/input) clicks are inferred: the cursor stops, then the
screen changes right under it. Inferred clicks drive the zooms but draw no ripple.
"""
import argparse, glob, json, os, subprocess, sys

try:
    import cv2
    import numpy as np
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SK, 'components'))
LOG_DIR = os.path.expanduser('~/.local/share/editor-v2/inputs')
W, H = 1920, 1080


def find_log(vd, recording=None, log=None):
    if log:
        return log
    names = []
    if recording:
        names.append(os.path.splitext(os.path.basename(recording))[0])
    rp = os.path.join(vd, 'work', 'recording.json')
    if os.path.isfile(rp):
        names.append(os.path.splitext(os.path.basename(json.load(open(rp)).get('path', '')))[0])
    for n in names:
        p = os.path.join(LOG_DIR, n + '.json')
        if n and os.path.isfile(p):
            return p
    return None


def mapper(log, vd):
    """logical global (x, y) -> cam_raw (x, y)."""
    import ev2_pro as P
    ox, oy, cw, ch = P.content_rect(vd)
    tgt = log.get('target') or {}
    mons = log.get('monitors') or []
    if 'region' in tgt:
        rx, ry, rw, rh = tgt['region']

        def f(x, y):
            return ox + (x - rx) / rw * cw, oy + (y - ry) / rh * ch
        return f
    mon = None
    if 'monitor' in tgt:
        mon = next((m for m in mons if m.get('name') == tgt['monitor']), None)
    if mon is None and mons:
        mon = next((m for m in mons if m.get('focused')), mons[0])
    if mon is None:
        return None
    sc = float(mon.get('scale') or 1.0)
    lw, lh = mon['width'] / sc, mon['height'] / sc
    if mon.get('transform', 0) in (1, 3, 5, 7):
        lw, lh = lh, lw

    def f(x, y):
        return ox + (x - mon['x']) / lw * cw, oy + (y - mon['y']) / lh * ch
    return f


def diff_frames(vd, seconds=120.0, fps=10):
    cam = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-t', f'{seconds:.1f}', '-i', cam, '-vf',
                          f'fps={fps},scale=480:270', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    frames = []
    while True:
        b = p.stdout.read(480 * 270)
        if len(b) < 480 * 270:
            break
        frames.append(np.frombuffer(b, np.uint8).reshape(270, 480).astype(np.int16))
    p.wait()
    if len(frames) < 3:
        return None
    return np.array([np.abs(frames[k] - frames[k - 1]) for k in range(1, len(frames))], np.uint8)


def cursor_at(cur, t):
    """Interpolated cursor (x, y) at log times t (array) from samples [[t, x, y], ...]."""
    ct, cx, cy = cur[:, 0], cur[:, 1], cur[:, 2]
    return np.interp(t, ct, cx), np.interp(t, ct, cy)


def align(log, vd, f_map, t0_guess):
    """Offset (log wall time of video t=0) that best matches cursor motion to screen diffs."""
    cur = np.array(log.get('cursor') or [], float)
    if len(cur) < 20:
        return t0_guess, 0.0
    D = diff_frames(vd)
    if D is None:
        return t0_guess, 0.0
    fps = 10
    tv = np.arange(1, len(D) + 1) / fps            # video time of diff k (between frame k-1 and k)
    best, scores = None, []
    for d in np.arange(-1.5, 1.501, 0.05):
        t_log = tv + t0_guess + d
        x1, y1 = cursor_at(cur, t_log)
        x0, y0 = cursor_at(cur, t_log - 1 / fps)
        mx, my = f_map(x1, y1)
        mv = np.hypot(x1 - x0, y1 - y0) > 3
        if mv.sum() < 5:
            scores.append(0.0)
            continue
        px = np.clip((mx / 4).astype(int), 6, 480 - 7)
        py = np.clip((my / 4).astype(int), 6, 270 - 7)
        s_in = np.array([D[k, py[k] - 6:py[k] + 7, px[k] - 6:px[k] + 7].mean() for k in np.nonzero(mv)[0]])
        scores.append(float(s_in.mean()))
    scores = np.array(scores)
    k = int(np.argmax(scores))
    conf = float((scores[k] - np.median(scores)) / (scores.std() + 1e-6))
    return t0_guess + (-1.5 + 0.05 * k), conf


def infer_clicks(cur_v, D, fps=10):
    """Clicks guessed from a stop of the cursor followed by a screen change right under it."""
    if D is None or len(cur_v) < 10:
        return []
    out, last = [], -9
    t = cur_v[:, 0]
    for k in range(2, len(D) - 6):
        tk = (k + 1) / fps
        x1, y1 = np.interp(tk, t, cur_v[:, 1]), np.interp(tk, t, cur_v[:, 2])
        x0, y0 = np.interp(tk - 0.2, t, cur_v[:, 1]), np.interp(tk - 0.2, t, cur_v[:, 2])
        if np.hypot(x1 - x0, y1 - y0) > 4 or tk - last < 0.8:
            continue
        px, py = int(np.clip(x1 / 4, 30, 449)), int(np.clip(y1 / 4, 30, 239))
        before = D[k, py - 30:py + 30, px - 30:px + 30].mean()
        after = D[k + 1:k + 6, py - 30:py + 30, px - 30:px + 30].mean(axis=(1, 2)).max()
        if after > 6 and after > 4 * (before + 0.5):
            out.append({'t': round(tk, 3), 'x': round(float(x1), 1), 'y': round(float(y1), 1), 'btn': 'left', 'inferred': True})
            last = tk
    return out


def convert(vd, log_path, offset=None):
    log = json.load(open(log_path))
    f_map = mapper(log, vd)
    if f_map is None:
        raise SystemExit('inputs: the log has no monitor/region information')
    t0 = log.get('video_seen_wall') or log.get('started_wall')
    if offset is not None:
        t0, conf, method = float(offset), 1.0, 'forced'
    else:
        t0, conf = align(log, vd, f_map, t0)
        method = 'cursor-motion' if conf >= 3 else 'recorder-start (cursor match unclear)'
    cur = np.array(log.get('cursor') or [], float)
    cur_v = np.zeros((0, 3))
    if len(cur):
        x, y = f_map(cur[:, 1], cur[:, 2])
        cur_v = np.stack([cur[:, 0] - t0, x, y], axis=1)
        cur_v = cur_v[cur_v[:, 0] >= 0]
    clicks = []
    for t, btn in log.get('clicks') or []:
        tv = t - t0
        if tv < 0:
            continue
        if len(cur):
            cx, cy = cursor_at(cur, np.array([t]))
            x, y = f_map(cx[0], cy[0])
        else:
            continue
        clicks.append({'t': round(tv, 3), 'x': round(float(x), 1), 'y': round(float(y), 1), 'btn': btn})
    inferred = False
    if not log.get('input_devices') and not clicks:
        clicks = infer_clicks(cur_v, diff_frames(vd, seconds=1e6))
        inferred = True
    typing, keys = [], [t - t0 for t in log.get('keys') or [] if t >= t0]
    if keys:
        s = e = keys[0]
        n = 1
        for t in keys[1:]:
            if t - e < 1.2:
                e, n = t, n + 1
            else:
                if n >= 3:
                    typing.append([round(s, 3), round(e, 3)])
                s = e = t
                n = 1
        if n >= 3:
            typing.append([round(s, 3), round(e, 3)])
    combos, last = [], -9
    for t, names in log.get('combos') or []:
        tv = t - t0
        if tv < 0 or tv - last < 2.5:
            continue
        combos.append({'t': round(tv, 3), 'combo': names})
        last = tv
    step = max(1, len(cur_v) // max(1, int((cur_v[-1, 0] if len(cur_v) else 0) * 15)))
    out = {'log': log_path, 'offset_wall': t0, 'align': {'method': method, 'confidence': round(conf, 2)},
           'clicks_inferred': inferred, 'clicks': clicks, 'typing': typing, 'keys': combos,
           'cursor': [[round(a, 3), round(b, 1), round(c, 1)] for a, b, c in cur_v[::step].tolist()]}
    json.dump(out, open(os.path.join(vd, 'work', 'inputs.json'), 'w'))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--recording')
    ap.add_argument('--log')
    ap.add_argument('--offset', type=float, help='log wall-clock time of video t=0 (skip the automatic alignment)')
    a = ap.parse_args()
    vd = os.path.abspath(a.video_dir)
    if a.recording:
        json.dump({'path': os.path.abspath(a.recording)}, open(os.path.join(vd, 'work', 'recording.json'), 'w'))
    lp = find_log(vd, a.recording, a.log)
    if not lp:
        print('inputs: no input log for this recording (record with `ev2 rec install` running to get exact clicks); '
              'zooms will follow screen activity')
        return 0
    out = convert(vd, lp, a.offset)
    print(f'inputs: {len(out["clicks"])} clicks{" (inferred)" if out["clicks_inferred"] else ""}, '
          f'{len(out["typing"])} typing spans, {len(out["keys"])} shortcuts, {len(out["cursor"])} cursor points; '
          f'aligned by {out["align"]["method"]} (confidence {out["align"]["confidence"]}) -> work/inputs.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
