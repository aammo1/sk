#!/usr/bin/env python3
"""preview.py — prove the Editor V2 install works end to end: an 8-second test without external media.

    $EV1_PY <skill>/scripts/preview.py [--out ~/editor-v2/_preview]

Builds a self-contained 8.0-second composition combining:
- Documentary devices: tile_reveal, pop_shatter, strobe, neg_flash, keyword, wall3d, frames datamosh, white_flash
- Tutorial devices: shortcut_pill, cmd_toast, flow_diagram, chapter_banner
- RTL Moroccan Darija + English tech BiDi captions (هاد الفيديو بـ Editor V2.)
- Automated sound design: mix-sfx.py laying synthesized SFX cues
- 9:16 Short extraction
It tests the renderer, devices and sound; the full pipeline (timeline, finish, editor
projects, verify) is tested by scripts/test_pipeline.py.
"""
import argparse, json, os, shutil, subprocess, sys

# Auto-locate environment Python if launched from bare interpreter lacking cv2/numpy
try:
    import cv2
    import numpy as np
except ImportError:
    for candidate in [
        os.environ.get('EV2_PY'),
        os.environ.get('EV1_PY'),
        os.path.expanduser('~/.cache/editor-v2/venv/bin/python'),
    ]:
        if candidate and os.path.isfile(candidate) and os.path.realpath(candidate) != os.path.realpath(sys.executable):
            os.execv(candidate, [candidate] + sys.argv)
    raise

SK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(SK, 'components'))
sys.path.insert(0, os.path.join(SK, 'scripts'))
from ev2_tutorial import *          # noqa: every device + Comp + BiDi helpers
import ev1_treat as T

rng = np.random.default_rng(11)


def city(w=2112, h=1188):
    """a skyline at dusk: gradient sky, blocks with lit windows"""
    y = np.linspace(0, 1, h)[:, None, None]
    im = (np.array([90, 60, 40]) * (1 - y) + np.array([40, 110, 200]) * y) * np.ones((h, w, 3))
    x = 0
    while x < w:
        bw = int(rng.integers(90, 260)); bh = int(rng.integers(300, 900))
        im[h - bh:, x:x + bw] = rng.integers(15, 45)
        for wy in range(h - bh + 30, h - 20, 46):
            for wx in range(x + 16, x + bw - 20, 34):
                if rng.random() < 0.45:
                    im[wy:wy + 20, wx:wx + 14] = (120, 210, 250)
        x += bw + int(rng.integers(6, 30))
    return np.clip(im, 0, 255).astype(np.uint8)


def card(w=900, h=620, seed=0):
    """a page: a header bar, a headline block, text lines"""
    r = np.random.default_rng(seed)
    im = np.full((h, w, 3), 244, np.uint8)
    im[:70] = (40, 40, 40)
    cv2.rectangle(im, (50, 120), (w - int(r.integers(120, 300)), 190), (30, 30, 30), -1)
    for k in range(7):
        y = 240 + k * 50
        cv2.rectangle(im, (50, y), (w - int(r.integers(60, 260)), y + 18), (150, 150, 150), -1)
    return im


def circle(seed):
    r = np.random.default_rng(seed)
    im = np.full((1080, 1920, 3), int(r.integers(10, 40)), np.uint8)
    cv2.circle(im, (960 + int(r.integers(-80, 80)), 540 + int(r.integers(-40, 40))), int(r.integers(280, 400)),
               tuple(int(v) for v in r.integers(120, 255, 3)), -1)
    return im


def main():
    ap = argparse.ArgumentParser(description="preview.py — 8.0s end-to-end Editor V2 test")
    ap.add_argument('--out', default=os.path.expanduser('~/editor-v2/_preview'))
    a = ap.parse_args()
    out = os.path.abspath(a.out)

    marker = os.path.join(out, '.ev2-preview')
    if os.path.isdir(out) and os.listdir(out) and not os.path.exists(marker):
        sys.exit(f'preview: {out} exists and is not an ev2 preview folder; refusing to delete it (pick another --out)')
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(f'{out}/assets/img', exist_ok=True)
    open(marker, 'w').write('created by ev2 preview; safe to delete\n')
    os.makedirs(f'{out}/work', exist_ok=True)
    os.makedirs(f'{out}/out', exist_ok=True)

    shutil.copytree(os.path.join(SK, 'assets'), f'{out}/assets/ev1')
    if not os.path.exists(f'{out}/assets/ev1/vendor/gsap.min.js'):
        sys.exit('preview: GSAP missing: run scripts/doctor.sh first')

    os.chdir(out)
    I = lambda n: f'assets/img/{n}.jpg'
    T.treat(city(), I('city'), 'teal', size=(2112, 1188), ht=0.3, vig=0.7)
    T.treat(city(), I('city_deep'), 'deep', size=(1920, 1080), vig=0.6)
    for k in range(3):
        cv2.imwrite(I(f'card{k}'), card(seed=k))
    for k in range(6):
        T.treat(circle(k), I(f'circ{k}'), ['mono', 'warm', 'teal'][k % 3], size=(1920, 1080))
    for k in range(6):
        T.treat(card(1600, 1000, seed=10 + k), I(f'wall{k}'), 'natural', size=(1280, 794))
    g = T.treat(city(), None, 'warm', size=(1920, 1080))
    for k, fimg in enumerate(T.glitch_frames(g, 4)):
        cv2.imwrite(I(f'gl{k}'), fimg)

    c = Comp(8.0)

    # 0.0 - 1.4s: tile_reveal onto skyline + still + BiDi Moroccan Darija caption
    tend = tile_reveal(c, 0.0, I('city'), z=2, seed=3)
    c.clip(0, tend, '<div class="ev1-layer ev1-black"></div>', z=1)
    still(c, tend, 1.4, I('city'), z=1)
    finish(c, 0, 1.4)
    captions(c, [([('هاد', 0.10), ('الفيديو', 0.32), ('بـ', 0.55), ('Editor V2.', 0.80)], 1.4)])

    # 1.4 - 2.6s: pop_shatter cards + shortcut_pill
    pop_shatter(c, 1.4, 2.6, [
        (I('card0'), 520, 520, 620, -4, 1.47),
        (I('card1'), 990, 580, 640, 2, 1.70),
        (I('card2'), 1440, 510, 600, -3, 1.93)
    ], z=1)
    shortcut_pill(c, 1.5, 2.5, ['Super', 'Shift', 'R'], 'Omarchy Record')
    captions(c, [([('Real', 1.47), ('pictures,', 1.70), ('every', 1.93), ('word.', 2.15)], 2.6)])

    # 2.6 - 3.4s: strobe
    strobe(c, 2.6, 3.4, [I(f'circ{k}') for k in range(6)], z=1)

    # 3.4 - 4.4s: neg_flash + keyword('EVERY CUT', kind='shock')
    s = still(c, 3.4, 4.4, I('city_deep'), z=1, push=1.04)
    neg_flash(c, 3.4, [s[1]])
    keyword(c, 3.47, 4.4, 'EVERY CUT', z=10, kind='shock', sound='hit')
    finish(c, 3.4, 4.4)

    # 4.4 - 5.6s: flow_diagram
    flow_diagram(c, 4.4, 5.6,
                 [('n1', 'Omarchy MP4', 360, 540),
                  ('n2', 'Darija ASR', 960, 540),
                  ('n3', 'Concat + Short', 1560, 540)],
                 [('n1', 'n2', 0.2), ('n2', 'n3', 0.5)])

    # 5.6 - 6.8s: wall3d + cmd_toast
    wall3d(c, 5.6, 6.8, [I(f'wall{k}') for k in range(6)], z=1)
    cmd_toast(c, 5.7, 6.7, 'ev2 init --latest')

    # 6.8 - 8.0s: frames datamosh + white_flash + chapter_banner
    t = frames(c, 6.8, [I(f'gl{k}') for k in range(4)], z=1)
    white_flash(c, t)
    chapter_banner(c, 6.9, 8.0, '01', 'Editor V2 Studio', 'Darija + English Tech Edition')

    c.write('index.html', 'assets/ev1/tokens.css', title='Editor V2 preview')
    c.write_cues('sfx-cues.txt')
    c.write_chapters('out/youtube-chapters.txt', 'work/chapters.json')
    if os.path.exists('out/youtube-chapters.txt'):
        shutil.copyfile('out/youtube-chapters.txt', 'youtube-chapters.txt')

    hf = ['npx', '-y', 'hyperframes@' + os.environ.get('HF_VERSION', '0.8.181')]
    lint = subprocess.run(hf + ['lint', '.'], capture_output=True, text=True)
    if lint.stdout:
        print(lint.stdout[-600:])

    print('preview: rendering 8.0s composition via HyperFrames...')
    r = subprocess.run(hf + ['render', '.', '-q', 'standard', '-f', '30', '-o', 'render.mp4'], capture_output=True, text=True)
    if r.returncode or not os.path.exists('render.mp4'):
        sys.exit('preview: render failed\n' + r.stdout[-1500:] + r.stderr[-1500:])

    print('preview: laying synthesized sound cues via mix-sfx.py...')
    subprocess.run([sys.executable, os.path.join(SK, 'scripts', 'mix-sfx.py'), 'render.mp4', 'sfx-cues.txt', 'preview.mp4'], check=True)

    print('preview: generating thumbnail contact sheet preview-sheet.jpg...')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', 'preview.mp4', '-vf',
                    "select='eq(n\\,20)+eq(n\\,55)+eq(n\\,90)+eq(n\\,115)+eq(n\\,150)+eq(n\\,175)+eq(n\\,195)+eq(n\\,225)',scale=480:-2,tile=4x2",
                    '-frames:v', '1', 'preview-sheet.jpg'], check=True)

    print('preview: extracting 9:16 vertical Short...')
    subprocess.run([sys.executable, os.path.join(SK, 'scripts', 'short-extract.py'), 'preview.mp4', 'short.mp4'], check=True)

    cues_lines = [line for line in open('sfx-cues.txt').read().splitlines() if line.strip() and not line.startswith('#')]
    print(f'preview: {out}/preview.mp4  ({len(cues_lines)} sound cues)  sheet: {out}/preview-sheet.jpg')
    if os.path.exists('short.mp4'):
        print(f'preview: {out}/short.mp4 (9:16 Short)')

    if sys.platform == 'darwin':
        subprocess.run(['open', 'preview.mp4'])
    elif sys.platform.startswith('linux') and os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
        subprocess.Popen(['xdg-open', 'preview.mp4'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
