"""build.py (calm style) — Editor V2 HOOK as a calm title card, then the screencast itself.

The calm style is for plain walkthrough videos: instead of the fast documentary montage, the
hook is a simple title card (brand, title, subtitle, one or two screenshots), then the original
screencast plays as recorded while the speaker introduces the video. The webcam/screencast in the
hook is NOT zoomed or pinned: zooms, the webcam PiP and chapter cards start with the body
(`ev2 finish`, body_render.py). Keep the hook short: the end of the spoken intro, 5-15 s, via
`ev2 clean <dir> --hook-split S`. Switch styles with `ev2 style <dir> calm|documentary`.
The title texts below are template examples: each example() call marks one, and FINAL=1 refuses
until every example is replaced by the real text from PLAN.md.

Workflow (or just `ev2 build <video-dir>`):
    $EV2_PY build.py         -> index.html, sfx-cues.txt, work/shots.json,
                                work/hook_chapters.json, work/build.json (placeholder status)
    hf lint .
    hf render . -q standard -f 30 -o out/render.mp4
    FINAL=1 $EV2_PY build.py -> refuses while any placeholder or missing asset remains
Assets are looked up by key in work/assets.json: {"thumb1": "assets/img/x.jpg", ...}.
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


def shot(t0, t1, name):
    SHOTS.append((fr(t0), fr(t1), name))


# ============================================================ BEATS — calm: title card, then the screencast
CARD_END = fr(max(F1, min(4.5, HOOK_SPLIT - 0.5)))
TITLE = 'عنوان الفيديو'; example('title card title')
SUBTITLE = 'Omarchy'; example('title card subtitle')
BRAND = 'My channel'; example('title card brand')
# optional screenshots (work/assets.json keys thumb1/thumb2): checked directly, never "missing"
thumbs = [A[k] for k in ('thumb1', 'thumb2') if k in A and os.path.exists(A[k])]
title_card(c, 0, CARD_END, TITLE, SUBTITLE, BRAND, thumbs, z=40)
shot(0, CARD_END, 'title_card')

v0 = max(0.0, fr(CARD_END - 0.4))
c.video(v0, DUR, 'assets/media/cam_raw.mp4', v0, z=10)   # the screencast itself, as recorded
shot(v0, DUR, 'screencast')

# optional beats over the screencast, e.g.:
# shortcut_pill(c, find('سوبر'), find('سوبر') + 2.5, 'Super + Space', 'then type the name')

# The hook is one chapter
c.chapters.append((0.0, TLINE.get('hook_title') or 'Intro'))

json.dump({'placeholders': PLACEHOLDERS, 'missing': sorted(set(MISSING)), 'final': FINAL,
           'hook_split': HOOK_SPLIT}, open('work/build.json', 'w'), indent=2, ensure_ascii=False)
if FINAL and (PLACEHOLDERS or MISSING):
    sys.exit(f'build.py: FINAL refused — placeholders {PLACEHOLDERS}, missing assets {sorted(set(MISSING))}')

c.write('index.html', 'assets/ev1/tokens.css', title='Editor V2 Tutorial')
c.write_cues('sfx-cues.txt')
c.write_chapters(None, 'work/hook_chapters.json')   # hook chapters only; finish.py adds the body's
json.dump(sorted(SHOTS), open('work/shots.json', 'w'))

print(f'Editor V2 (calm): PASS {PASS} | dur {DUR:.2f}s | cues {len(c.cues)} | shots {len(SHOTS)} | '
      f'placeholders {len(PLACEHOLDERS)} | missing {sorted(set(MISSING))}')
