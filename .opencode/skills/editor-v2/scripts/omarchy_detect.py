#!/usr/bin/env python3
"""omarchy_detect.py — Omarchy screen-recording geometry detector.

Computes the exact WebcamOverlay dimensions based on Omarchy Linux placement logic
(/usr/bin/omarchy-capture-webcam-resize) and inspects the video to auto-detect whether
a webcam overlay is present and which size preset (small, medium, large, or none) was used.

    python3 omarchy_detect.py <video.mp4> [--size auto|small|medium|large|none|fullscreen] \
        [--out-json work/omarchy.json] [--extract-cam assets/media/cam_crop.mp4]
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


def probe_video(path):
    """Probe video dimensions and framerate using ffprobe with OpenCV fallback."""
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
        # Fallback to OpenCV
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = round(float(cap.get(cv2.CAP_PROP_FPS) or 30.0), 2)
        cap.release()
        return w, h, fps


def compute_boxes(W, H):
    """Replicate the exact integer math from /usr/bin/omarchy-capture-webcam-resize.

    Given video width W and height H:
      MARGIN = round(40 * (H / 1080))
      small:  h = (H * 9 + 25) // 50,  w = (h * 8 + 4) // 9
      medium: h = (H + 2) // 4,        w = (h * 8 + 4) // 9
      large:  h = (H * 27 + 40) // 80, w = (h * 8 + 4) // 9
      x = W - w - MARGIN, y = H - h - MARGIN
    """
    margin = round(40 * (H / 1080))
    scale_height = H
    available_width = W - 2 * margin
    if available_width > 0 and (scale_height * 3) // 10 > available_width:
        scale_height = (available_width * 10) // 3

    # small
    h_s = (scale_height * 9 + 25) // 50
    w_s = (h_s * 8 + 4) // 9
    box_small = [int(W - w_s - margin), int(H - h_s - margin), int(w_s), int(h_s)]

    # medium (Omarchy default)
    h_m = (scale_height + 2) // 4
    w_m = (h_m * 8 + 4) // 9
    box_medium = [int(W - w_m - margin), int(H - h_m - margin), int(w_m), int(h_m)]

    # large
    h_l = (scale_height * 27 + 40) // 80
    w_l = (h_l * 8 + 4) // 9
    box_large = [int(W - w_l - margin), int(H - h_l - margin), int(w_l), int(h_l)]

    return {
        'small': box_small,
        'medium': box_medium,
        'large': box_large
    }


def detect_webcam_size(video_path, W, H, num_frames=5):
    """Inspect the first num_frames frames using OpenCV edge/gradient detection

    along candidate borders to detect whether WebcamOverlay is present and which
    preset (small, medium, large, or none) was used.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 'none', None

    frames = []
    for _ in range(num_frames):
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    if not frames:
        return 'none', None

    boxes = compute_boxes(W, H)
    scores = {}
    coverages = {}

    for preset in ['small', 'medium', 'large']:
        bx, by, bw, bh = boxes[preset]
        if bx < 0 or by < 0 or bx + bw > W or by + bh > H:
            scores[preset] = 0.0
            coverages[preset] = 0.0
            continue

        frame_top_scores = []
        frame_left_scores = []
        frame_top_cov = []
        frame_left_cov = []

        for fr in frames:
            gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            sobel_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
            sobel_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))

            # Top horizontal boundary
            y_min = max(0, by - 2)
            y_max = min(H, by + 3)
            x_min = max(0, bx)
            x_max = min(W, bx + bw)
            top_strip = sobel_y[y_min:y_max, x_min:x_max]
            top_vals = top_strip.max(axis=0) if top_strip.size > 0 else np.array([0])

            # Left vertical boundary
            x_lmin = max(0, bx - 2)
            x_lmax = min(W, bx + 3)
            y_lmin = max(0, by)
            y_lmax = min(H, by + bh)
            left_strip = sobel_x[y_lmin:y_lmax, x_lmin:x_lmax]
            left_vals = left_strip.max(axis=1) if left_strip.size > 0 else np.array([0])

            frame_top_scores.append(float(np.mean(top_vals)))
            frame_left_scores.append(float(np.mean(left_vals)))
            frame_top_cov.append(float(np.mean(top_vals > 40.0)))
            frame_left_cov.append(float(np.mean(left_vals > 40.0)))

        mean_top = np.mean(frame_top_scores)
        mean_left = np.mean(frame_left_scores)
        mean_top_cov = np.mean(frame_top_cov)
        mean_left_cov = np.mean(frame_left_cov)

        # Top and left boundaries uniquely identify the window edge
        score = (mean_top + mean_left) / 2.0
        cov = (mean_top_cov + mean_left_cov) / 2.0

        scores[preset] = score
        coverages[preset] = cov

    # Evaluate best candidate
    best_preset = max(scores, key=scores.get)
    best_score = scores[best_preset]
    best_cov = coverages[best_preset]

    # Threshold: significant edge strength and minimum edge continuity
    if best_score >= 35.0 and best_cov >= 0.25:
        return best_preset, boxes[best_preset]

    # If scores are moderate but distinct from competitors
    sorted_presets = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if sorted_presets[0][1] >= 25.0 and (sorted_presets[0][1] > sorted_presets[1][1] * 1.5):
        detected = sorted_presets[0][0]
        return detected, boxes[detected]

    return 'none', None


def extract_cam_crop(video_path, box, out_crop_path):
    """Extract standalone webcam crop stream using FFmpeg."""
    parent = os.path.dirname(os.path.abspath(out_crop_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    x, y, w, h = box
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'error', '-y',
        '-i', video_path,
        '-vf', f'crop={w}:{h}:{x}:{y}',
        '-c:v', 'libx264', '-crf', '17', '-preset', 'fast',
        '-an',
        out_crop_path
    ]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description='Omarchy screen-recording geometry detector')
    ap.add_argument('video', help='Input video file (e.g. screenrecording-*.mp4)')
    ap.add_argument('--size', default='auto', choices=['auto', 'small', 'medium', 'large', 'none', 'fullscreen'],
                    help='Overlay size preset (auto, small, medium, large, none, fullscreen)')
    ap.add_argument('--out-json', default=None, help='Output path for omarchy.json metadata')
    ap.add_argument('--extract-cam', default=None, help='Output path to extract cropped webcam video')
    args = ap.parse_args()

    W, H, fps = probe_video(args.video)
    boxes = compute_boxes(W, H)

    if args.size == 'auto':
        preset, box = detect_webcam_size(args.video, W, H)
        has_overlay = (preset != 'none')
    elif args.size == 'none':
        has_overlay = False
        preset = 'none'
        box = None
    elif args.size == 'fullscreen':
        has_overlay = True
        preset = 'fullscreen'
        box = [0, 0, W, H]
    else:
        has_overlay = True
        preset = args.size
        box = boxes.get(args.size)

    result = {
        'width': W,
        'height': H,
        'fps': fps,
        'has_webcam_overlay': has_overlay,
        'webcam_size': preset,
        'webcam_box': box
    }

    # Extract webcam if requested
    if args.extract_cam:
        if has_overlay and box:
            extract_cam_crop(args.video, box, args.extract_cam)
            print(f'extracted webcam crop ({box[2]}x{box[3]}) -> {args.extract_cam}', file=sys.stderr)
        else:
            print('warning: no webcam overlay detected; skipping --extract-cam', file=sys.stderr)

    # Write output JSON
    json_str = json.dumps(result, indent=2)
    if args.out_json:
        parent = os.path.dirname(os.path.abspath(args.out_json))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.out_json, 'w') as f:
            f.write(json_str + '\n')

    print(json_str)


if __name__ == '__main__':
    main()
