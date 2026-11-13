"""build.py — Editor V2 HOOK composition, keyed to the speaker's word onsets.

This file builds ONLY the hook: source [0, hook_split) from work/timeline.json, rendered by
HyperFrames over the uncut voice. The tutorial body is not composed here: `ev2 finish`
appends the cleaned screencast from timeline.json, with automatic zooms, the webcam PiP and
chapter cards (body_render.py). Aim for a 15-25 s hook: `ev2 clean <dir> --hook-split S`.
The beats below are template examples: each example() call marks one, and FINAL=1 refuses
until every example is replaced by a real beat from PLAN.md.

Workflow (or just `ev2 build <video-dir>`):
    $EV2_PY build.py         -> index.html, sfx-cues.txt, work/shots.json,
                                work/hook_chapters.json, work/build.json (placeholder status)
    hf lint .
    hf render . -q standard -f 30 -o out/render.mp4
    FINAL=1 $EV2_PY build.py -> refuses while any placeholder or missing asset remains
Assets are looked up by key in work/assets.json: {"open_still": "assets/img/x.jpg", ...}.
"""
import json, os, sys

KIT = json.load(open('kit.json'))['skill']
sys.path.insert(0, os.path.join(KIT, 'components'))
from ev2_tutorial import *          # noqa: every device (see reference/devices.md) + Darija BiDi helpers

PASS = int(os.environ.get('PASS', '1'))
FINAL = os.environ.get('FINAL') == '1'          # FINAL=1 refuses to write while placeholders remain

# 1. Transcript words & cuts
W_ = json.load(open('work/tx/words.json')) if os.path.exists('work/tx/words.json') else []
WORDS = [(w['w'], w['s']) for w in W_]
VO_END = W_[-1]['e'] if W_ else 45.0

TLINE = json.load(open('work/timeline.json')) if os.path.exists('work/timeline.json') else {}
if not TLINE:
    sys.exit('build.py: work/timeline.json missing: run `ev2 transcribe <video-dir>` first')
HOOK_SPLIT = float(TLINE['hook_split'])

# Duration of the rendered Hook composition
DUR = fr(HOOK_SPLIT)

# 2. Omarchy webcam overlay metadata
OM = json.load(open('work/omarchy.json')) if os.path.exists('work/omarchy.json') else {}
HAS_CAM = OM.get('has_webcam_overlay', False)
CAM_BOX = OM.get('webcam_box', (1380, 500, 480, 540))


def norm(w):
    return w.strip('.,:;?!"').lower()


def find(word, after=0.0):
    """Onset of the first `word` at or after `after` seconds."""
    for w, t in WORDS:
        if norm(w) == norm(word) and t >= after - 1e-6:
            return t
    raise KeyError(word)


def span(first, last, after=0.0):
    """[(word, onset)] from `first` to `last`: one caption group."""
    out, on = [], False
    for w, t in WORDS:
        if not on and norm(w) == norm(first) and t >= after - 1e-6:
            on = True
        if on:
            out.append((w, t))
            if norm(w) == norm(last):
                return out
    raise KeyError(first)


A = json.load(open('work/assets.json')) if os.path.exists('work/assets.json') else {}
SIL = [tuple(map(float, l.split())) for l in open('work/silences.txt')] if os.path.exists('work/silences.txt') else []

c = Comp(DUR, caption_mode='darija-ar', hook_end=HOOK_SPLIT)
F1 = 1 / FPS
MISSING, PLACEHOLDERS, SHOTS = [], [], []


def has(*ks):
    bad = [k for k in ks if k not in A or not os.path.exists(A[k])]
    MISSING.extend(bad)
    return not bad


def example(label):
    """Marks template sample content. FINAL=1 refuses while any remains: replace the beat with
    the real one from PLAN.md and delete its example() call."""
    PLACEHOLDERS.append(f'template example: {label}')


def ph(t0, t1, label, z=1):
    """Loud magenta placeholder for a beat whose asset isn't sourced yet (never ships: FINAL=1 refuses)."""
    PLACEHOLDERS.append(label)
    c.clip(t0, t1, f'<div class="ev1-layer" style="background:#2a2a2a"><div style="position:absolute;left:80px;top:80px;'
                   f'font:700 60px var(--ev1-sans);color:#f0f">{esc(label)}</div></div>', z)


def shot(t0, t1, name):
    SHOTS.append((fr(t0), fr(t1), name))


def face(t0, t1, punch=None, z=1):
    """Speaker on camera RAW (no grade, no LUT, no vignette): one more picture in the stream."""
    v = broll(c, t0, t1, 'assets/media/cam_raw.mp4', z=z, rate=0.012, media_start=fr(t0),
              punches=[punch] if punch else ())
    shot(t0, t1, 'face')
    return v


# ============================================================ BEATS — one block per PLAN.md line
# Example hook structure: replace with your real beats from PLAN.md (and delete the example() calls).

# Beat 1 — Opening hook: tile_reveal from black onto hero still/clip + Moroccan Darija BiDi caption
b, e = 0.0, fr(WORDS[min(3, len(WORDS) - 1)][1]) if len(WORDS) >= 3 else 1.4
if has('open_still', 'open_clip'):
    tend = tile_reveal(c, b, A['open_still'], z=2, seed=3, size=(1920, 1080))
    c.clip(b, tend, '<div class="ev1-layer ev1-black"></div>', z=1)
    broll(c, tend, e, A['open_clip'], z=1, rate=0.07)
else:
    ph(b, e, 'beat 1: open_still + open_clip')
shot(b, e, 'open')
if WORDS:
    captions(c, [(WORDS[:min(3, len(WORDS))], e)])
else:
    captions(c, [([('هاد', 0.10), ('الفيديو', 0.35), ('بـ', 0.65), ('Editor V2', 0.95)], e)])
    example('beat 1 caption text (no transcript)')

# Beat 2 — Keyboard shortcut or CLI command demonstration
b2, e2 = e, min(DUR, fr(e + 2.0))
if b2 < DUR:
    c.clip(b2, e2, '<div class="ev1-layer ev1-black"><div class="ev1-vignette"></div></div>', z=1)
    shortcut_pill(c, b2 + 0.1, e2 - 0.1, ['Super', 'Shift', 'R'], 'Omarchy Record', z=65)
    example('beat 2 shortcut pill keys/label')
    shot(b2, e2, 'shortcut')

# Beat 3 — Screencast dynamic zoom into ROI with highlight box & pinned webcam
b3, e3 = e2, min(DUR, fr(e2 + 3.0))
if b3 < DUR:
    cam_kwargs = {'webcam_box': CAM_BOX} if HAS_CAM else {}
    screen_zoom(c, b3, e3, 'assets/media/cam_raw.mp4', roi=(200, 150, 1200, 800),
                z=1, media_start=b3, highlight_box=(300, 250, 600, 120), **cam_kwargs)
    example('beat 3 zoom roi/highlight box')
    shot(b3, e3, 'zoom_demo')

# Beat 4 — Transition to Screencast Tutorial Body via Chapter Banner
b4 = e3
if b4 < DUR:
    chapter_banner(c, b4, DUR, '01', 'إعداد بيئة العمل', 'Development Environment Setup', z=70, style='card')
    example('beat 4 chapter title')
    shot(b4, DUR, 'chapter_01')

# Sound outro on final frame of Hook
sfx(c, DUR - 0.2, 'outro', 0.8)

# Subtle vignette / film grain across the hook
finish(c, 0, DUR, z=80, grid=False, vignette=True)

json.dump({'placeholders': PLACEHOLDERS, 'missing': sorted(set(MISSING)), 'final': FINAL,
           'hook_split': HOOK_SPLIT}, open('work/build.json', 'w'), indent=2, ensure_ascii=False)
if FINAL and (PLACEHOLDERS or MISSING):
    sys.exit(f'build.py: FINAL refused — placeholders {PLACEHOLDERS}, missing assets {sorted(set(MISSING))}')

c.write('index.html', 'assets/ev1/tokens.css', title='Editor V2 Tutorial')
c.write_cues('sfx-cues.txt')
c.write_chapters(None, 'work/hook_chapters.json')   # hook chapters only; finish.py adds the body's
json.dump(sorted(SHOTS), open('work/shots.json', 'w'))

print(f'Editor V2: PASS {PASS} | dur {DUR:.2f}s | cues {len(c.cues)} | shots {len(SHOTS)} | '
      f'placeholders {len(PLACEHOLDERS)} | missing {sorted(set(MISSING))}')
