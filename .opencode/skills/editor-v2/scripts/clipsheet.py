#!/usr/bin/env python3
"""clipsheet.py — build numbered multi-frame contact sheets from video clips.

    python clipsheet.py <out.jpg> <video1.mp4> [video2.mp4 ...]

Samples frames across each video clip with safe handling for short clips (<0.5s),
rendering a labeled contact sheet showing filenames, duration, and frame timestamps.
"""
import glob, json, os, subprocess, sys
from io import BytesIO

# Re-exec under editor-v2 private venv if PIL is not installed in ambient python
try:
    from PIL import Image, ImageDraw
except ImportError:
    venv_py = os.path.expanduser('~/.cache/editor-v2/venv/bin/python')
    if os.path.exists(venv_py) and sys.executable != venv_py:
        os.execv(venv_py, [venv_py] + sys.argv)
    else:
        raise

if len(sys.argv) < 3:
    print('usage: clipsheet.py <out.jpg> <video1> [video2 ...]', file=sys.stderr)
    sys.exit(1)

out = sys.argv[1]
fs = sys.argv[2:]
rows = []
n = 8

for f in fs:
    if not os.path.exists(f):
        print(f'warning: file not found: {f}', file=sys.stderr)
        continue
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f],
            capture_output=True, text=True
        )
        d = float(probe.stdout.strip() or 0)
    except Exception:
        d = 0.0

    # Safe timestamp sampling for short clips (<0.5s) vs normal clips
    if d < 0.5:
        if d <= 0:
            ts = [0.0] * n
        else:
            step = d / n
            ts = [min(max(0.0, k * step), max(0.0, d - 0.001)) for k in range(n)]
    else:
        ts = [d * (k + 0.5) / n for k in range(n)]

    ims = []
    for t in ts:
        # For short clips (<0.5s), place -i before -ss for frame-accurate decoding;
        # otherwise use fast keyframe seeking with -ss before -i.
        if d < 0.5:
            cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-i', f, '-ss', f'{t:.4f}',
                   '-vframes', '1', '-vf', 'scale=240:-2', '-f', 'image2pipe', '-vcodec', 'png', '-']
        else:
            cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(t), '-i', f,
                   '-vframes', '1', '-vf', 'scale=240:-2', '-f', 'image2pipe', '-vcodec', 'png', '-']
        r = subprocess.run(cmd, capture_output=True)
        im = None
        if r.stdout:
            try:
                im = Image.open(BytesIO(r.stdout)).convert('RGB')
            except Exception:
                im = None

        # Fallback for short clips or seek failures: capture the first available frame
        if im is None:
            fallback = subprocess.run(
                ['ffmpeg', '-nostdin', '-v', 'error', '-i', f, '-vframes', '1',
                 '-vf', 'scale=240:-2', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                capture_output=True
            )
            if fallback.stdout:
                try:
                    im = Image.open(BytesIO(fallback.stdout)).convert('RGB')
                except Exception:
                    im = None

        if im is None:
            im = Image.new('RGB', (240, 135), (20, 20, 20))

        ims.append((t, im))
    rows.append((os.path.basename(f), d, ims))

H = 135 + 16
out_h = max(1, len(rows)) * (H + 14)
S = Image.new('RGB', (240 * n, out_h), (20, 20, 20))
dr = ImageDraw.Draw(S)

for i, (name, d, ims) in enumerate(rows):
    y = i * (H + 14)
    dur_label = f'{d:.2f}s' if d < 0.5 else f'{d:.1f}s'
    dr.text((4, y), f'{name}  {dur_label}', fill=(255, 220, 0))
    for k, (t, im) in enumerate(ims):
        im = im.resize((240, 135))
        S.paste(im, (k * 240, y + 14))
        t_label = f'{t:.2f}' if d < 0.5 else f'{t:.1f}'
        dr.text((k * 240 + 3, y + 16), t_label, fill=(120, 255, 120))

os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
S.save(out, quality=80)
print(out, S.size)
