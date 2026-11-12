#!/usr/bin/env python3
"""matte.py — cut the speaker out of camera footage for the hero beat (the world changes behind
them, the big red word sits behind their head).

Supports full-frame plates and cropped Omarchy webcam overlays, with three backends in priority order:
  1. rembg (ONNX u2net_human_seg) if installed in the venv.
  2. torch / RobustVideoMatting (mobilenetv3) if PyTorch is installed.
  3. OpenCV GrabCut / elliptical portrait feathering (zero-download CPU fallback, guaranteed to work offline).

    python3 matte.py --plate assets/media/cam_raw.mp4 --start 15.5 --dur 4.4 \
        --out assets/media/matte_a.webm [--crop-box x,y,w,h] [--scale-to-hero]

Writes a VP9 video with an alpha channel (yuva420p), RGB premultiplied over black.
Frame 0 of the webm = plate time --start.
"""
import argparse, json, os, subprocess, sys

# Auto-locate environment Python if launched from bare interpreter lacking numpy/cv2
try:
    import cv2, numpy as np
except ImportError:
    ev2_py = os.environ.get('EV2_PY', os.path.expanduser('~/.cache/editor-v2/venv/bin/python'))
    if os.path.isfile(ev2_py) and os.path.realpath(ev2_py) != os.path.realpath(sys.executable):
        os.execv(ev2_py, [ev2_py] + sys.argv)
    raise

OUT_W, OUT_H, FPS = 1920, 1080, 30


def probe_video(path):
    """Probe video dimensions and framerate using ffprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate',
            '-of', 'json', path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        stream = data['streams'][0]
        w = int(stream['width'])
        h = int(stream['height'])
        r_fps = stream.get('r_frame_rate', '30/1')
        fps_parts = r_fps.split('/')
        if len(fps_parts) == 2 and float(fps_parts[1]) != 0:
            fps = round(float(fps_parts[0]) / float(fps_parts[1]), 2)
        else:
            fps = float(fps_parts[0])
        return w, h, fps
    except Exception:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = round(float(cap.get(cv2.CAP_PROP_FPS) or 30.0), 2)
        cap.release()
        return w, h, fps


def portrait_elliptical_mask(h, w):
    """Smooth elliptical portrait prior for human head and torso."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # Head ellipse
    d_head = np.sqrt(((xx - w * 0.5) / (w * 0.32)) ** 2 + ((yy - h * 0.38) / (h * 0.30)) ** 2)
    # Torso trapezoid / ellipse widening downwards
    torso_w = w * (0.34 + 0.16 * (yy / max(1, h)))
    d_torso = np.sqrt(((xx - w * 0.5) / torso_w) ** 2 + ((yy - h * 0.85) / (h * 0.45)) ** 2)
    d = np.minimum(d_head, d_torso)
    alpha = np.clip(1.0 - (d - 0.70) / 0.30, 0.0, 1.0)
    ksize = max(5, int(min(w, h) * 0.08) | 1)
    return cv2.GaussianBlur(alpha, (ksize, ksize), 0)


def main():
    ap = argparse.ArgumentParser(description='Speaker background matting and alpha cut-out')
    ap.add_argument('--plate', required=True, help='Source plate video (e.g. cam_raw.mp4 or screenrecording.mp4)')
    ap.add_argument('--start', type=float, required=True, help='Start time in seconds')
    ap.add_argument('--dur', type=float, required=True, help='Duration in seconds')
    ap.add_argument('--out', required=True, help='Output WebM path (yuva420p)')
    ap.add_argument('--crop-box', default=None, help='x,y,w,h bounding box to crop from plate')
    ap.add_argument('--scale-to-hero', action='store_true', default=False,
                    help='Scale the speaker cutout up to center-bottom hero size in the 1920x1080 canvas')
    ap.add_argument('--downsample', type=float, default=0.4,
                    help='Downsample ratio for RVM model (0.4 default for CPU)')
    ap.add_argument('--harden', type=float, default=0.04,
                    help='Alpha below this -> 0, rescaled; 0 = off')
    ap.add_argument('--device', default='auto', choices=['auto', 'cpu', 'mps', 'cuda'],
                    help='Computation device for ML backends')
    a = ap.parse_args()

    plate_w, plate_h, plate_fps = probe_video(a.plate)

    # Determine crop coordinates
    if a.crop_box:
        cx, cy, cw, ch = map(int, a.crop_box.split(','))
        cx = max(0, min(cx, plate_w - 1))
        cy = max(0, min(cy, plate_h - 1))
        cw = max(1, min(cw, plate_w - cx))
        ch = max(1, min(ch, plate_h - cy))
    else:
        cx, cy = 0, 0
        cw, ch = plate_w, plate_h

    n = int(round(a.dur * FPS))
    if n <= 0:
        raise ValueError(f"Invalid duration: {a.dur}s (n={n} frames)")

    # ── Select backend in priority order ──────────────────────────────────────
    backend = None
    rembg_session = None
    torch_model = None
    torch_dev = None

    # Priority 1: rembg
    try:
        import rembg
        rembg_session = rembg.new_session('u2net_human_seg')
        backend = 'rembg'
    except Exception:
        rembg_session = None

    # Priority 2: torch / RobustVideoMatting
    if backend is None:
        try:
            import torch
            dev = a.device
            if dev == 'auto':
                dev = 'cuda' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu')
            torch_model = torch.hub.load('PeterL1n/RobustVideoMatting', 'mobilenetv3', trust_repo=True).eval().to(dev)
            torch_dev = dev
            backend = 'torch'
        except Exception:
            torch_model = None

    # Priority 3: OpenCV CPU fallback (zero-download, always available)
    if backend is None:
        backend = 'opencv'

    print(f'matte: backend={backend} on crop {cw}x{ch} (hero={a.scale_to_hero})', file=sys.stderr)

    # ── FFmpeg decode & encode pipelines ──────────────────────────────────────
    vf_dec = []
    if a.crop_box:
        vf_dec.append(f'crop={cw}:{ch}:{cx}:{cy}')
    vf_dec.append('fps=30')
    vf_dec_str = ','.join(vf_dec)

    dec_cmd = [
        'ffmpeg', '-nostdin', '-v', 'error',
        '-ss', f'{a.start:.4f}',
        '-i', a.plate,
        '-frames:v', str(n),
        '-vf', vf_dec_str,
        '-f', 'rawvideo',
        '-pix_fmt', 'rgb24',
        '-'
    ]
    dec = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE)

    parent_out = os.path.dirname(os.path.abspath(a.out))
    if parent_out:
        os.makedirs(parent_out, exist_ok=True)

    enc_cmd = [
        'ffmpeg', '-nostdin', '-v', 'error', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{OUT_W}x{OUT_H}',
        '-r', str(FPS), '-i', '-',
        '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
        '-b:v', '0', '-crf', '28',
        '-row-mt', '1', '-deadline', 'good', '-cpu-used', '4',
        '-auto-alt-ref', '0', '-g', '30', a.out
    ]
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

    # State variables for recurrent or progressive models
    rec = [None] * 4 if backend == 'torch' else None
    gc_mask = None
    bgdModel = np.zeros((1, 65), np.float64)
    fgdModel = np.zeros((1, 65), np.float64)
    gc_rect = (int(cw * 0.08), int(ch * 0.05), max(1, int(cw * 0.84)), max(1, int(ch * 0.93)))

    k = 0
    frame_bytes = cw * ch * 3

    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break

            rgb = np.frombuffer(buf, np.uint8).reshape(ch, cw, 3)

            # ── Compute alpha matte ───────────────────────────────────────────
            if backend == 'rembg':
                from PIL import Image
                import rembg
                pil_im = Image.fromarray(rgb)
                mask_im = rembg.remove(pil_im, session=rembg_session, only_mask=True)
                al = np.array(mask_im).astype(np.float32) / 255.0

            elif backend == 'torch':
                import torch
                x = torch.from_numpy(rgb).to(torch_dev).permute(2, 0, 1)[None].float() / 255.0
                for _ in range(3 if k == 0 else 1):  # warm-up on frame 0
                    _, pha, *rec = torch_model(x, *rec, downsample_ratio=a.downsample)
                al = pha[0, 0].clamp(0, 1).cpu().numpy()

            else:  # opencv GrabCut / elliptical portrait feathering
                if gc_mask is None:
                    gc_mask = np.zeros((ch, cw), dtype=np.uint8)
                    cv2.grabCut(rgb, gc_mask, gc_rect, bgdModel, fgdModel, 2, cv2.GC_INIT_WITH_RECT)
                else:
                    cv2.grabCut(rgb, gc_mask, gc_rect, bgdModel, fgdModel, 1, cv2.GC_INIT_WITH_MASK)

                fg = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), 1.0, 0.0).astype(np.float32)
                total_area = ch * cw
                fg_ratio = fg.sum() / max(1, total_area)

                if 0.08 < fg_ratio < 0.92:
                    ksize = max(5, int(min(cw, ch) * 0.06) | 1)
                    fg = cv2.GaussianBlur(fg, (ksize, ksize), 0)
                    ell = portrait_elliptical_mask(ch, cw)
                    al = np.clip(fg * ell, 0.0, 1.0)
                else:
                    al = portrait_elliptical_mask(ch, cw)

            # ── Alpha hardening ───────────────────────────────────────────────
            if a.harden > 0:
                al = np.clip((al - a.harden) / (1 - 2 * a.harden), 0.0, 1.0)

            # ── Scale & composite to 1920x1080 canvas ──────────────────────────
            canvas_rgb = np.zeros((OUT_H, OUT_W, 3), dtype=np.uint8)
            canvas_al = np.zeros((OUT_H, OUT_W), dtype=np.float32)

            if a.scale_to_hero:
                aspect = cw / max(1, ch)
                if aspect < 1.0:
                    hero_h = OUT_H
                    hero_w = min(OUT_W, round(hero_h * aspect))
                else:
                    hero_w = min(OUT_W, round(OUT_H * aspect))
                    hero_h = min(OUT_H, round(hero_w / aspect))

                hero_x = (OUT_W - hero_w) // 2
                hero_y = OUT_H - hero_h

                interp = cv2.INTER_LANCZOS4 if hero_w > cw else cv2.INTER_AREA
                scaled_rgb = cv2.resize(rgb, (hero_w, hero_h), interpolation=interp)
                scaled_al = cv2.resize(al, (hero_w, hero_h), interpolation=cv2.INTER_LINEAR)

                canvas_rgb[hero_y:hero_y + hero_h, hero_x:hero_x + hero_w] = scaled_rgb
                canvas_al[hero_y:hero_y + hero_h, hero_x:hero_x + hero_w] = scaled_al

            else:
                if a.crop_box:
                    canvas_rgb[cy:cy + ch, cx:cx + cw] = rgb
                    canvas_al[cy:cy + ch, cx:cx + cw] = al
                else:
                    if cw == OUT_W and ch == OUT_H:
                        canvas_rgb = rgb
                        canvas_al = al
                    else:
                        canvas_rgb = cv2.resize(rgb, (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)
                        canvas_al = cv2.resize(al, (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)

            # Pre-multiplied RGB over black + alpha channel
            pre = (canvas_rgb.astype(np.float32) * canvas_al[..., None] + 0.5).astype(np.uint8)
            a8 = (canvas_al * 255.0 + 0.5).astype(np.uint8)
            rgba = np.dstack([pre, a8])

            enc.stdin.write(rgba.tobytes())
            k += 1

            if k % 30 == 0:
                print(f'  {k}/{n} frames', file=sys.stderr)

    finally:
        enc.stdin.close()
        enc.wait()
        dec.wait()

    print(f'matte: {k} frames ({backend}) -> {a.out}  (frame 0 = plate {a.start:.3f}s)')


if __name__ == '__main__':
    main()
