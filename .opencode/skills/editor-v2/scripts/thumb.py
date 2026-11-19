#!/usr/bin/env python3
"""thumb.py — Dual-mode YouTube thumbnail studio for Editor V2.

  Mode 1 — Local Free Studio Thumbnails (default, 100% offline, 1280x720):
    ev2 thumb <dir> --init [--face FILE] [--force]   Extract sharpest face + app screen, write work/thumbs.json
    ev2 thumb <dir>                                  Render 3 studio PNGs + grid.png + grid_phone.png (246x138)

  Mode 2 — Optional OpenRouter AI Concepts (opt-in, requires OPENROUTER_API_KEY):
    ev2 thumb <dir> --ai "<brief>" [--face FILE] [--models a,b] [--n 1] [--tag t1]
    ev2 thumb --list-models                          List live OpenRouter image models
"""
import argparse
import base64
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'components'))
import ev2_pro as P       # noqa: E402
import ev2_thumb as TH    # noqa: E402

OR_BASE = 'https://openrouter.ai/api/v1'
DEFAULT_AI_MODELS = [
    'google/gemini-2.5-flash-image-preview',
    'openai/gpt-image-1',
    'black-forest-labs/flux.2-pro',
]


def find_chrome():
    cands = [
        os.environ.get('CHROME_PATH'),
        '/usr/bin/chromium',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    try:
        v = os.environ.get('HF_VERSION', '0.8.181')
        r = subprocess.run(['npx', '-y', f'hyperframes@{v}', 'browser', 'path'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            p = r.stdout.strip().splitlines()[-1].strip()
            if os.path.isfile(p):
                return p
    except Exception:
        pass
    return None


def render_html_to_png(chrome, html_path, out_png, w=1280, h=720):
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    url = 'file://' + os.path.abspath(html_path)
    cmd = [
        chrome,
        '--headless=new',
        '--no-sandbox',
        '--disable-gpu',
        '--hide-scrollbars',
        '--force-device-scale-factor=1',
        f'--window-size={w},{h}',
        '--virtual-time-budget=2000',
        f'--screenshot={os.path.abspath(out_png)}',
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if r.returncode != 0 or not os.path.isfile(out_png):
        raise RuntimeError(f'Chrome screenshot failed: {(r.stderr or r.stdout or "")[-400:]}')
    # Enforce exact 1280x720 dimensions
    im = Image.open(out_png).convert('RGB')
    if im.size != (w, h):
        im = im.resize((w, h), Image.Resampling.LANCZOS)
        im.save(out_png)
    return out_png


def _probe_dur(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def extract_best_face(vd, out_jpg, explicit_face=None):
    """Extract the sharpest speaker portrait frame from cam_face.mp4 or webcam overlay (or copy explicit photo)."""
    os.makedirs(os.path.dirname(out_jpg), exist_ok=True)
    if explicit_face and os.path.isfile(explicit_face):
        Image.open(explicit_face).convert('RGB').save(out_jpg, quality=95)
        return out_jpg

    cam = P.camera_source(vd)
    cam_raw = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    if cam['mode'] == 'separate' and os.path.isfile(cam['path']):
        src, crop_box = cam['path'], None
    elif cam['mode'] == 'overlay' and os.path.isfile(cam_raw):
        src, crop_box = cam_raw, [int(round(v)) for v in cam['box']]
    elif os.path.isfile(cam_raw):
        # Vertical or talking-head recording without overlay metadata
        om_p = os.path.join(vd, 'work', 'omarchy.json')
        vert = os.path.isfile(om_p) and json.load(open(om_p, encoding='utf-8')).get('vertical_source')
        if not vert:
            return None
        src, crop_box = cam_raw, None
    else:
        return None

    dur = _probe_dur(src)
    if dur <= 0:
        return None
    best_score, best_img = -1.0, None
    for frac in (0.15, 0.35, 0.55, 0.75):
        t = dur * frac
        tmp = out_jpg[:-4] + '_cand.jpg'
        vf = f'crop={crop_box[2]}:{crop_box[3]}:{crop_box[0]}:{crop_box[1]}' if crop_box else 'null'
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', src,
                            '-frames:v', '1', '-vf', vf, '-q:v', '2', tmp], capture_output=True)
        if r.returncode != 0 or not os.path.isfile(tmp):
            continue
        im = cv2.imread(tmp)
        os.remove(tmp)
        if im is None:
            continue
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if sharp > best_score:
            best_score, best_img = sharp, im
    if best_img is not None:
        cv2.imwrite(out_jpg, best_img, [cv2.IMWRITE_JPEG_QUALITY, 94])
        return out_jpg
    return None


def extract_best_screen(vd, out_png):
    """Pick an existing clean still from assets/pro/stills/ or extract a crisp frame from cam_raw.mp4."""
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    stills = sorted(glob.glob(os.path.join(vd, 'assets', 'pro', 'stills', '*.png')) +
                    glob.glob(os.path.join(vd, 'assets', 'pro', 'stills', '*.jpg')))
    if stills:
        Image.open(stills[0]).convert('RGB').save(out_png)
        return out_png
    cam_raw = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    if not os.path.isfile(cam_raw):
        return None
    dur = _probe_dur(cam_raw)
    t = max(0.5, dur * 0.45)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', cam_raw,
                        '-frames:v', '1', out_png], capture_output=True)
    return out_png if (r.returncode == 0 and os.path.isfile(out_png)) else None


def build_grids(tiles, out_dir):
    """Build grid.png (640x360 labelled) and grid_phone.png (246x138 mobile feed readability test)."""
    if not tiles:
        return
    fp = os.path.join(SK, 'assets', 'fonts', 'Inter-700.woff2')
    try:
        font = ImageFont.truetype(fp, 20)
    except Exception:
        font = ImageFont.load_default()
    for fname, (tw, th), show_lab in (('grid.png', (640, 360), True), ('grid_phone.png', (246, 138), False)):
        cols = min(3, max(1, len(tiles)))
        rows = (len(tiles) + cols - 1) // cols
        lh = 32 if show_lab else 0
        canvas = Image.new('RGB', (cols * (tw + 14) + 14, rows * (th + lh + 14) + 14), (14, 15, 22))
        dr = ImageDraw.Draw(canvas)
        for idx, (img_path, label) in enumerate(tiles):
            x = 14 + (idx % cols) * (tw + 14)
            y = 14 + (idx // cols) * (th + lh + 14)
            im = Image.open(img_path).convert('RGB').resize((tw, th), Image.Resampling.LANCZOS)
            canvas.paste(im, (x, y))
            if show_lab:
                dr.text((x, y + th + 6), label[:52], fill=(226, 232, 240), font=font)
        canvas.save(os.path.join(out_dir, fname))


def load_theme(vd):
    lp = os.path.join(vd, 'work', 'look.json')
    look = {}
    if os.path.isfile(lp):
        try:
            look = json.load(open(lp, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    acc = look.get('resolved_accent') or look.get('accent')
    if not acc or acc == 'auto':
        acc = P.DEFAULT_ACCENT
    return P.make_theme(acc)


# ------------------------------------------------------------------ Local studio workflow
def init_thumbs(vd, explicit_face=None, force=False):
    tp = os.path.join(vd, 'work', 'thumbs.json')
    if os.path.isfile(tp) and not force:
        print(f'thumb: {tp} already exists (pass --force to overwrite)')
        return 0
    work_dir = os.path.join(vd, 'work', 'thumbs')
    os.makedirs(work_dir, exist_ok=True)
    face_p = extract_best_face(vd, os.path.join(work_dir, 'face_ref.jpg'), explicit_face=explicit_face)
    scr_p = extract_best_screen(vd, os.path.join(work_dir, 'screen_ref.png'))

    hk = {}
    hp = os.path.join(vd, 'work', 'hook.json')
    if os.path.isfile(hp):
        try:
            hk = json.load(open(hp, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    brand = str(hk.get('brand') or '').strip()
    promise = P.plain(str(hk.get('promise') or hk.get('title') or 'Tutorial Guide')).strip()
    short_hl = ' '.join(promise.split()[:4])[:36] or 'Pro Workflow'

    cfg = {
        'face': os.path.relpath(face_p, vd) if face_p else None,
        'screen': os.path.relpath(scr_p, vd) if scr_p else None,
        'concepts': [
            {
                'name': 't1-hero',
                'template': 'split-hero',
                'badge': brand or 'Tutorial',
                'headline': short_hl,
                'sub': promise[:48] if promise != short_hl else '',
            },
            {
                'name': 't2-stat',
                'template': 'big-stat',
                'badge': brand or 'Pro Setup',
                'stat': '10x',
                'headline': short_hl,
            },
            {
                'name': 't3-compare',
                'template': 'compare-vs',
                'badge': brand or 'Before / After',
                'headline': short_hl,
                'left_text': 'الطريقة القديمة',
                'right_text': brand or 'الطريقة الجديدة',
            },
        ],
    }
    with open(tp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'thumb: wrote 3 starter concepts -> {tp}')
    if face_p:
        print(f'  face ref:   {os.path.relpath(face_p, vd)}')
    if scr_p:
        print(f'  screen ref: {os.path.relpath(scr_p, vd)}')
    print(f'Next: edit headlines in work/thumbs.json (2-4 punchy words), then run `ev2 thumb {vd}`')
    return 0


def render_local_thumbs(vd):
    tp = os.path.join(vd, 'work', 'thumbs.json')
    if not os.path.isfile(tp):
        sys.exit(f'thumb: {tp} missing — run `ev2 thumb {vd} --init` first')
    cfg = json.load(open(tp, encoding='utf-8'))
    probs = TH.validate_thumbs_cfg(cfg)
    if probs:
        print('thumb: fix these in work/thumbs.json:')
        for p in probs:
            print(f'  FIX  {p}')
        return 1
    chrome = find_chrome()
    if not chrome:
        sys.exit('thumb: no Chrome/Chromium found (install chromium or set CHROME_PATH)')

    theme = load_theme(vd)
    face_p = os.path.join(vd, cfg['face']) if cfg.get('face') else None
    scr_p = os.path.join(vd, cfg['screen']) if cfg.get('screen') else None
    face_uri = ('file://' + os.path.abspath(face_p)) if (face_p and os.path.isfile(face_p)) else None
    scr_uri = ('file://' + os.path.abspath(scr_p)) if (scr_p and os.path.isfile(scr_p)) else None
    fonts_uri = 'file://' + os.path.abspath(os.path.join(SK, 'assets', 'fonts'))

    work_dir = os.path.join(vd, 'work', 'thumbs')
    out_dir = os.path.join(vd, 'out', 'thumbs')
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    tiles = []
    for c in cfg['concepts']:
        name = c['name']
        html_p = os.path.join(work_dir, f'{name}.html')
        png_p = os.path.join(out_dir, f'{name}.png')
        TH.build_thumb_html(html_p, c, theme, face_uri=face_uri, screen_uri=scr_uri, fonts_dir_uri=fonts_uri)
        render_html_to_png(chrome, html_p, png_p, w=TH.W, h=TH.H)
        tiles.append((png_p, f'{name} ({c.get("template", "split-hero")})'))
        print(f'  rendered {os.path.relpath(png_p, vd)} (1280x720)')

    build_grids(tiles, out_dir)
    print(f'thumb: grids -> {os.path.relpath(os.path.join(out_dir, "grid.png"), vd)} & grid_phone.png (246x138)')
    return 0


# ------------------------------------------------------------------ Optional OpenRouter AI mode
def _or_key():
    k = os.environ.get('OPENROUTER_API_KEY')
    if not k:
        env_p = os.path.expanduser('~/.config/editor-v2/.env')
        if os.path.isfile(env_p):
            for line in open(env_p, encoding='utf-8'):
                if line.strip().startswith('OPENROUTER_API_KEY='):
                    k = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break
    if not k:
        sys.exit('thumb --ai: OPENROUTER_API_KEY not set (env or ~/.config/editor-v2/.env)')
    return k


def _or_req(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        OR_BASE + path, data=data, method=method,
        headers={'Authorization': f'Bearer {_or_key()}', 'Content-Type': 'application/json',
                 'X-Title': 'editor-v2 thumb'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def list_or_models():
    data = _or_req('GET', '/images/models', timeout=30).get('data') or []
    print(f'OpenRouter image models ({len(data)}):')
    for m in data[:40]:
        mods = (m.get('architecture') or {}).get('input_modalities') or []
        tag = 'face-ref OK' if 'image' in mods else 'text-only'
        print(f'  {m.get("id"):45s}  [{tag}]')
    return 0


def render_ai_thumbs(vd, brief, explicit_face=None, models_csv=None, n=1, tag='t1'):
    _or_key()
    env_models = os.environ.get('EV2_OR_IMAGE_MODELS', '').strip()
    models = ([x.strip() for x in models_csv.split(',') if x.strip()] if models_csv
              else ([x.strip() for x in env_models.split(',') if x.strip()] if env_models else DEFAULT_AI_MODELS))
    out_dir = os.path.join(vd, 'out', 'thumbs', f'ai_{tag}')
    os.makedirs(out_dir, exist_ok=True)
    face_p = extract_best_face(vd, os.path.join(vd, 'work', 'thumbs', 'face_ref.jpg'), explicit_face=explicit_face)
    ref = None
    if face_p and os.path.isfile(face_p):
        b64 = base64.b64encode(open(face_p, 'rb').read()).decode()
        ref = {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}

    try:
        takes_image = {m['id'] for m in (_or_req('GET', '/images/models', timeout=30).get('data') or [])
                       if 'image' in (m.get('architecture') or {}).get('input_modalities', [])}
    except Exception:
        takes_image = set(models)

    style = ('A YouTube thumbnail, 16:9, bold and simple: one clear subject, high contrast, readable at phone size. '
             'Any text in the image must be exactly the words given in quotes, spelled exactly, nothing added. ')

    def call_one(model):
        use_face = bool(ref and model in takes_image)
        body = {
            'model': model,
            'prompt': style + ('Keep the person from the reference photo, same face. ' if use_face else '') + brief,
            'aspect_ratio': '16:9',
            'n': n,
        }
        if use_face:
            body['input_references'] = [ref]
        try:
            j = _or_req('POST', '/images', body, timeout=400)
        except Exception as e:
            return model, [], None, use_face, str(e)[:200]
        cost = (j.get('usage') or {}).get('cost')
        with open(os.path.join(vd, 'work', 'costs.jsonl'), 'a', encoding='utf-8') as cf:
            cf.write(json.dumps({'t': round(time.time(), 1), 'step': 'thumb-ai', 'model': model, 'cost': cost}) + '\n')
        files = []
        for idx, img in enumerate(j.get('data') or [], 1):
            ext = (img.get('media_type') or 'image/png').split('/')[-1].replace('jpeg', 'jpg')
            fp = os.path.join(out_dir, f'{re.sub(r"[^a-z0-9]+", "-", model.lower())}_{idx}.{ext}')
            open(fp, 'wb').write(base64.b64decode(img['b64_json']))
            files.append(fp)
        return model, files, cost, use_face, ''

    with ThreadPoolExecutor(max_workers=min(4, len(models))) as ex:
        res = list(ex.map(call_one, models))

    tiles = []
    total_cost = 0.0
    for model, files, cost, use_face, err in res:
        if cost:
            total_cost += float(cost)
        c_str = f'${cost:.3f}' if cost is not None else '$?'
        print(f'  {model:42s} {len(files)} img  {c_str}  {"face-ref" if use_face else "brief-only"}  {err}')
        for fp in files:
            tiles.append((fp, f'{model} {c_str}'))
    build_grids(tiles, out_dir)
    print(f'thumb --ai: total ${total_cost:.3f} -> {os.path.relpath(os.path.join(out_dir, "grid.png"), vd)} & grid_phone.png')
    return 0


def main():
    ap = argparse.ArgumentParser(description='Dual-mode YouTube thumbnail studio for Editor V2.')
    ap.add_argument('video_dir', nargs='?', default=None)
    ap.add_argument('--init', action='store_true', help='Extract face + screen refs and write starter work/thumbs.json')
    ap.add_argument('--force', action='store_true', help='Overwrite existing work/thumbs.json on --init')
    ap.add_argument('--face', default=None, help='Explicit speaker photo path')
    ap.add_argument('--ai', default=None, metavar='BRIEF', help='Opt-in OpenRouter AI thumbnail brief')
    ap.add_argument('--models', default=None, help='Comma-separated OpenRouter image model IDs for --ai')
    ap.add_argument('--n', type=int, default=1, help='Images per AI model (default 1)')
    ap.add_argument('--tag', default='t1', help='Output folder tag for --ai runs')
    ap.add_argument('--list-models', action='store_true', help='List live OpenRouter image models')
    a = ap.parse_args()

    if a.list_models:
        return list_or_models()
    if not a.video_dir:
        ap.error('video_dir is required (unless --list-models)')
    vd = os.path.abspath(a.video_dir)
    if a.ai:
        return render_ai_thumbs(vd, a.ai, explicit_face=a.face, models_csv=a.models, n=a.n, tag=a.tag)
    if a.init:
        return init_thumbs(vd, explicit_face=a.face, force=a.force)
    return render_local_thumbs(vd)


if __name__ == '__main__':
    sys.exit(main())
