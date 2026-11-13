#!/usr/bin/env python3
"""beauty.py — does the video LOOK and SOUND professional? Measured, not guessed, so it works
even when the agent cannot see images.

    beauty.py <video-dir> [--json]      -> out/beauty.md, out/beauty.json, out/beauty-sheet.jpg

Checks (FAIL = fix before publishing, WARN = worth a look):
  hook   dead air      black or empty frames for > 0.8 s                                  FAIL
         frozen        no visual change for > 3.5 s (> 2.2 s: WARN)                       FAIL/WARN
         pace          fewer than 2 visual cuts per 10 s                                  WARN
         faces         a face cut by the frame edge; two faces at once (burned-in webcam) FAIL/WARN
         length        longer than 32 s                                                   WARN
         sound         fewer than 4 sound effects                                         WARN
  inserts frozen       no visual change for > 4 s (> 2.5 s: WARN)                         FAIL/WARN
  body   zoom          zoomed past 2.0x (past 1.8x: WARN): text gets soft                 FAIL/WARN
         stage         not inset, or no webcam PiP when there is a webcam                 WARN
         monotony      > 50 s of body with no zoom, insert, callout or chapter card       WARN (with where)
         music         no music under the body                                            WARN
  text   description   internal notes/paths left in out/youtube-description.md            FAIL
         captions      the transcript is unreliable (low ASR confidence): do not upload    WARN
         chapters      titles longer than 40 chars, or mixed separators                   WARN
verify.py runs this and copies the lines into out/verify.md.
"""
import json, os, re, subprocess, sys

os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')
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
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

FPS = 30
R = []


def add(level, what, detail):
    R.append((level, what, detail))


def frames(path, fps, w=320, h=180, t0=None, dur=None, gray=False):
    cmd = ['ffmpeg', '-nostdin', '-v', 'error']
    if t0 is not None:
        cmd += ['-ss', f'{t0:.3f}']
    if dur is not None:
        cmd += ['-t', f'{dur:.3f}']
    cmd += ['-i', path, '-vf', f'fps={fps},scale={w}:{h}', '-pix_fmt', 'gray' if gray else 'bgr24', '-f', 'rawvideo', '-']
    r = subprocess.run(cmd, capture_output=True)
    ch = 1 if gray else 3
    n = len(r.stdout) // (w * h * ch)
    a = np.frombuffer(r.stdout[:n * w * h * ch], np.uint8)
    return a.reshape(n, h, w) if gray else a.reshape(n, h, w, 3)


def runs(mask, fps):
    """Longest run of True (seconds) and where it starts."""
    best, cur, start, bstart = 0, 0, 0, 0
    for i, m in enumerate(mask):
        if m:
            if cur == 0:
                start = i
            cur += 1
            if cur > best:
                best, bstart = cur, start
        else:
            cur = 0
    return best / fps, bstart / fps


def motion_profile(g):
    return np.abs(np.diff(g.astype(np.int16), axis=0)).mean(axis=(1, 2)) if len(g) > 1 else np.zeros(0)


def check_hook(vd, tl):
    path = os.path.join(vd, 'out', 'hook.mp4')
    if not os.path.isfile(path):
        path = os.path.join(vd, 'out', 'render.mp4')
    if not os.path.isfile(path):
        return
    D = TL.frames(tl['hook_split']) / FPS
    g = frames(path, 10, gray=True)
    if len(g) < 5:
        return
    mean, std = g.mean(axis=(1, 2)), g.std(axis=(1, 2))
    edges = np.array([(cv2.Canny(x, 60, 140) > 0).mean() for x in g])
    dead = ((mean < 8) & (edges < 0.01)) | (std < 4) | (edges < 0.0012)
    dead[:3] = False
    d, at = runs(dead, 10)
    add('FAIL' if d > 0.8 else 'PASS', 'hook: dead air', f'{d:.1f}s of black/empty frames at {at:.1f}s' if d > 0.8 else 'no black or empty stretch')
    mot = motion_profile(g)
    still, at = runs(mot < 0.35, 10)
    lvl = 'FAIL' if still > 3.5 else ('WARN' if still > 2.2 else 'PASS')
    add(lvl, 'hook: motion', f'longest frozen stretch {still:.1f}s' + (f' at {at:.1f}s' if lvl != 'PASS' else ''))
    cuts = int((mot > 18).sum())
    rate = cuts / max(1.0, D) * 10
    add('WARN' if rate < 2 else 'PASS', 'hook: pace', f'{cuts} visual cuts in {D:.0f}s ({rate:.1f} per 10 s)')
    if D > 32:
        add('WARN', 'hook: length', f'{D:.0f}s: strongest hooks are 15-30 s (`ev2 clean <dir> --hook-split S`)')
    # faces: a face sliced by the frame edge, or two faces at once
    det = None
    yp = os.path.expanduser('~/.cache/editor-v2/models/yunet.onnx')
    if os.path.isfile(yp):
        os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')
        det = cv2.FaceDetectorYN.create(yp, '', (640, 360), 0.7)
    if det is not None:
        col = frames(path, 2, 640, 360)
        cut, two = [], []
        for i, f in enumerate(col):
            _, fs = det.detect(np.ascontiguousarray(f))
            if fs is None:
                continue
            big = [r for r in fs if r[2] > 22]
            for r in big:
                x, y, w, h = r[:4]
                if x < 2 or y < 2 or x + w > 638 or y + h > 358:
                    cut.append(i / 2)
            if len(big) >= 2:
                two.append(i / 2)
        if cut:
            add('FAIL', 'hook: faces', f'a face is cut by the frame edge at {", ".join(f"{t:.1f}s" for t in cut[:4])}')
        elif two:
            add('WARN', 'hook: faces', f'two faces at once at {", ".join(f"{t:.1f}s" for t in two[:4])} (burned-in webcam in a shot?)')
        else:
            add('PASS', 'hook: faces', 'no cut or doubled face')
    cues = os.path.join(vd, 'sfx-cues.txt')
    n = sum(1 for l in open(cues) if l.split('#', 1)[0].strip()) if os.path.isfile(cues) else 0
    add('WARN' if n < 4 else 'PASS', 'hook: sound', f'{n} sound effects')


def check_inserts(vd, tl):
    bad, ok = [], 0
    for ins in TL.insert_ranges(tl):
        p = TL.insert_render_path(vd, ins)
        if not os.path.isfile(p):
            continue
        g = frames(p, 10, gray=True)
        mot = motion_profile(g)
        still, at = runs(mot < 0.12, 10)
        if still > 4:
            bad.append(('FAIL', f'{ins["name"]}: frozen {still:.1f}s from {at:.1f}s'))
        elif still > 2.5:
            bad.append(('WARN', f'{ins["name"]}: frozen {still:.1f}s from {at:.1f}s'))
        else:
            ok += 1
    if bad:
        add('FAIL' if any(b[0] == 'FAIL' for b in bad) else 'WARN', 'inserts: motion', '; '.join(b[1] for b in bad))
    elif ok:
        add('PASS', 'inserts: motion', f'{ok} inserts keep moving')


def check_body(vd, tl):
    st_p = os.path.join(vd, 'work', 'body_video.json')
    st = json.load(open(st_p)) if os.path.isfile(st_p) else None
    if not st:
        return
    mz = st.get('max_zoom')
    if mz is not None:
        lvl = 'FAIL' if mz > 2.05 else ('WARN' if mz > 1.85 else 'PASS')
        add(lvl, 'body: zoom', f'max {mz:.2f}x ({st.get("zoom_source", "?")}-driven, {st.get("zoomed_share", 0) * 100:.0f}% of the body zoomed)')
    om = os.path.join(vd, 'work', 'omarchy.json')
    has_cam = os.path.isfile(om) and json.load(open(om)).get('has_webcam_overlay')
    probs = []
    if st.get('frame', 'full') != 'inset':
        probs.append('the screen is edge to edge (look.frame "inset" looks more finished)')
    if has_cam and st.get('pip') is False:
        probs.append('there is a webcam but no PiP')
    add('WARN' if probs else 'PASS', 'body: stage', '; '.join(probs) if probs else 'inset screen on the backdrop, speaker PiP')
    # monotony: long stretches where nothing new happens on top of the screen
    segs = TL.body_segments(tl)
    n = sum(s['f_end'] - s['f_start'] for s in segs)
    if n <= 0:
        return
    busy = np.zeros(n, bool)
    zp = os.path.join(vd, 'work', 'zoom_plan.json')
    if os.path.isfile(zp):
        for k in json.load(open(zp)).get('keys', []):
            busy[max(0, k['f'] - 15):k['f'] + 45] = True
    for ins in TL.insert_ranges(tl):
        busy[ins['f0']:ins['f0'] + ins['n']] = True
    hs = TL.frames(tl['hook_split']) / FPS
    for t, _ in TL.final_chapters(tl, hs):
        f = int((t - hs) * FPS)
        if f >= 0:
            busy[f:f + 4 * FPS] = True
    for c in tl.get('callouts') or []:
        bt = TL.src_to_body(tl, float(c['src_t']))
        if bt is not None:
            busy[int(bt * FPS):int((bt + c.get('dur', 3)) * FPS)] = True
    act = os.path.join(vd, 'work', 'activity.npz')
    if os.path.isfile(act):
        frac = np.load(act)['frac']
        src = np.concatenate([np.arange(s['f_start'], s['f_end']) for s in segs])
        scene = frac[np.clip(src // 6, 0, len(frac) - 1)] > 0.2      # page changes count as something new
        busy |= scene
    quiet, at = runs(~busy, FPS)
    if quiet > 50:
        add('WARN', 'body: monotony', f'{quiet:.0f}s with nothing new on screen from body {TL.fmt_ts(at)} '
                                      f'(final {TL.fmt_ts(at + hs)}): add an insert, a callout or a chapter there')
    else:
        add('PASS', 'body: monotony', f'longest plain stretch {quiet:.0f}s')
    fin = os.path.join(vd, 'work', 'finish.json')
    if os.path.isfile(fin) and not json.load(open(fin)).get('body_music'):
        add('WARN', 'body: music', 'no music under the tutorial: it feels flat (remove "body_music": false, or drop --no-body-music)')


LEAKS = [r'assets/', r'work/', r'\.png\b', r'\.jpe?g\b', r'\.wav\b', r'identify only', r'Creator Original', r'<!--',
         r'\bTODO\b', r'\bTBD\b', r'placeholder', r'\{\{', r'lorem ipsum']


def check_text(vd, tl):
    p = os.path.join(vd, 'out', 'youtube-description.md')
    if os.path.isfile(p):
        txt = open(p, encoding='utf-8').read()
        hits = sorted({m.group(0) for pat in LEAKS for m in re.finditer(pat, txt, re.I)})
        if hits:
            add('FAIL', 'text: description', f'internal notes left in the description: {", ".join(hits[:6])}; remove those lines')
        else:
            add('PASS', 'text: description', 'no internal notes or paths')
    eng = os.path.join(vd, 'work', 'tx', 'engine.json')
    if os.path.isfile(os.path.join(vd, 'out', 'captions.srt')):
        e = json.load(open(eng)) if os.path.isfile(eng) else {}
        mp, low = e.get('mean_prob'), e.get('low_prob_share')
        edited = TL.words_edited(vd)
        if edited is True:
            add('PASS', 'text: captions', 'transcript corrected by hand')
        elif mp is None:
            add('WARN', 'text: captions', 'captions are raw speech recognition (confidence unknown): read them before uploading')
        elif mp < 0.75 or (low or 0) > 0.2:
            add('WARN', 'text: captions', f'speech recognition is unsure (mean {mp:.2f}, {low * 100:.0f}% of words low): '
                                          f'do not upload captions.srt until it is corrected')
        else:
            add('PASS', 'text: captions', f'speech recognition confident (mean {mp:.2f})')
    titles = [c['title'] for c in tl.get('chapters') or []]
    if titles:
        long = [t for t in titles if len(t) > 40]
        seps = {s for t in titles for s in (' — ', ' - ', ' | ', ': ') if s in t}
        probs = []
        if long:
            probs.append(f'{len(long)} titles over 40 chars')
        if len(seps) > 1:
            probs.append(f'mixed separators {sorted(seps)}')
        add('WARN' if probs else 'PASS', 'text: chapters', '; '.join(probs) if probs else f'{len(titles)} clean titles')


def sheet(vd):
    """out/beauty-sheet.jpg: the hook at 2 fps on top, the whole video at 1 frame / 8 s below."""
    out = os.path.join(vd, 'out', 'beauty-sheet.jpg')
    fin = os.path.join(vd, 'out', 'final.mp4')
    if not os.path.isfile(fin):
        return None
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', fin, '-vf', 'fps=1/8,scale=320:-1,tile=8x8',
                    '-frames:v', '1', '-update', '1', out])
    return out if os.path.isfile(out) else None


def run(vd):
    R.clear()
    tl = TL.load(vd)
    for fn in (check_hook, check_inserts, check_body, check_text):
        try:
            fn(vd, tl)
        except Exception as e:  # a check that crashes must not hide the others
            add('WARN', fn.__name__.replace('check_', '') + ': check error', str(e)[:160])
    sh = sheet(vd)
    os.makedirs(os.path.join(vd, 'out'), exist_ok=True)
    lines = ['# Beauty check', '', '| | Check | Detail |', '|---|---|---|'] + [f'| {l} | {w} | {d} |' for l, w, d in R]
    if sh:
        lines += ['', f'Contact sheet: `{os.path.relpath(sh, vd)}` (hook + 1 frame / 8 s).']
    open(os.path.join(vd, 'out', 'beauty.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    json.dump([dict(level=l, check=w, detail=d) for l, w, d in R], open(os.path.join(vd, 'out', 'beauty.json'), 'w'),
              indent=2, ensure_ascii=False)
    return list(R)


def main():
    vd = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
    res = run(vd)
    for l, w, d in res:
        print(f'  {l:<4}  {w:<20} {d}')
    return 1 if any(l == 'FAIL' for l, _, _ in res) else 0


if __name__ == '__main__':
    sys.exit(main())
