#!/usr/bin/env python3
"""inspect_source.py — Step 0 read-only pre-edit diagnostic & coaching brief.

    ev2 inspect <file|--latest> [--cam FILE] [--json]

Probes a raw recording BEFORE creating a workspace or running slow steps:
  - Video geometry (16:9 vs 9:16, resolution, fps, VFR vs CFR, duration)
  - Audio health (present, sample rate, mean/peak level, clipping or quiet mic)
  - Matching `ev2 rec` input log (exact click zooms + ripples) & companion camera
  - Omarchy corner webcam overlay presence
  - GPU / VRAM / active compute jobs (protects 8 GB VRAM laptops like RTX 2070)
  - Recommended workflow + coaching notes for the agent's Step 0 intake conversation.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gpu  # noqa: E402


def resolve_latest():
    vdir = os.path.expanduser('~/Videos')
    if not os.path.isdir(vdir):
        return None
    for pat in ('screenrecording-*.mp4', '*.mp4', '*.mkv', '*.mov'):
        files = glob.glob(os.path.join(vdir, pat))
        if files:
            return max(files, key=os.path.getmtime)
    return None


def parse_frac(s):
    if not s or '/' not in s:
        try:
            return float(s or 0)
        except ValueError:
            return 0.0
    n, _, d = s.partition('/')
    try:
        dn = float(d)
        return float(n) / dn if dn else 0.0
    except ValueError:
        return 0.0


def probe_media(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'error',
         '-show_entries', 'format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels',
         '-of', 'json', path],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        raise RuntimeError(f'ffprobe failed on {path}: {(r.stderr or "").strip()}')
    d = json.loads(r.stdout)
    fmt = d.get('format') or {}
    dur = float(fmt.get('duration') or 0.0)
    size_mb = round(float(fmt.get('size') or 0) / (1024 * 1024), 1)
    v, a = None, None
    for st in d.get('streams') or []:
        if st.get('codec_type') == 'video' and v is None:
            w, h = int(st.get('width') or 0), int(st.get('height') or 0)
            rfps = parse_frac(st.get('r_frame_rate'))
            afps = parse_frac(st.get('avg_frame_rate'))
            v = {
                'codec': st.get('codec_name'),
                'width': w,
                'height': h,
                'r_fps': round(rfps, 2),
                'avg_fps': round(afps, 2),
                'vfr': abs(rfps - afps) > 0.5 if (rfps > 0 and afps > 0) else False,
            }
        elif st.get('codec_type') == 'audio' and a is None:
            a = {
                'codec': st.get('codec_name'),
                'sample_rate': int(st.get('sample_rate') or 0),
                'channels': int(st.get('channels') or 0),
            }
    return {'duration': round(dur, 2), 'size_mb': size_mb, 'video': v, 'audio': a}


def probe_audio_health(path):
    r = subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-t', '90', '-i', path,
         '-vn', '-af', 'volumedetect', '-f', 'null', '-'],
        capture_output=True, text=True, timeout=30,
    )
    mean_m = re.search(r'mean_volume:\s*(-?[\d.]+)\s*dB', r.stderr)
    max_m = re.search(r'max_volume:\s*(-?[\d.]+)\s*dB', r.stderr)
    mean_db = float(mean_m.group(1)) if mean_m else None
    max_db = float(max_m.group(1)) if max_m else None
    issues = []
    if mean_db is None:
        issues.append('could not measure audio volume')
    else:
        if mean_db < -55.0:
            issues.append(f'audio looks silent ({mean_db:.1f} dB mean) — check mic input')
        elif mean_db < -34.0:
            issues.append(f'mic level is very quiet ({mean_db:.1f} dB mean; voice FX will boost it, expect more room noise)')
        if max_db is not None and max_db >= -0.3:
            issues.append(f'audio peaks hit {max_db:.1f} dB (possible clipping)')
    return {'mean_db': mean_db, 'max_db': max_db, 'issues': issues}


def find_input_log(rec_path):
    log_dir = os.path.expanduser('~/.local/share/editor-v2/inputs')
    if not os.path.isdir(log_dir):
        return None
    stem = os.path.splitext(os.path.basename(rec_path))[0]
    exact = os.path.join(log_dir, f'{stem}.json')
    if os.path.isfile(exact):
        return exact
    # Fallback: closest mtime within 120s
    rec_mt = os.path.getmtime(rec_path)
    best, best_dt = None, 120.0
    for p in glob.glob(os.path.join(log_dir, '*.json')):
        dt = abs(os.path.getmtime(p) - rec_mt)
        if dt < best_dt:
            best, best_dt = p, dt
    return best


def find_companion_cam(rec_path):
    cam_dir = os.path.expanduser('~/.local/share/editor-v2/cams')
    if not os.path.isdir(cam_dir):
        return None
    stem = os.path.splitext(os.path.basename(rec_path))[0]
    for ext in ('mkv', 'mp4', 'mov', 'webm'):
        cand = os.path.join(cam_dir, f'{stem}.{ext}')
        if os.path.isfile(cand):
            return cand
    return None


def classify_aspect(w, h):
    if not w or not h:
        return 'unknown'
    ratio = w / h
    if abs(ratio - 16 / 9) < 0.12:
        return '16:9'
    if abs(ratio - 9 / 16) < 0.12:
        return '9:16'
    if ratio > 2.0:
        return 'ultrawide'
    if h > w:
        return 'vertical'
    return 'landscape'


def fmt_dur(sec):
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}h {m:02d}m {s:02d}s'
    return f'{m}m {s:02d}s' if m else f'{s}s'


def inspect(path, cam_path=None):
    media = probe_media(path)
    v = media['video'] or {}
    a = media['audio']
    aspect = classify_aspect(v.get('width', 0), v.get('height', 0))
    audio_health = probe_audio_health(path) if a else {'mean_db': None, 'max_db': None, 'issues': ['no audio stream found']}
    input_log = find_input_log(path)
    auto_cam = cam_path if (cam_path and os.path.isfile(cam_path)) else find_companion_cam(path)
    gpu_st = gpu.status()
    busy_gpu = gpu.busy_compute_procs()
    rec_jobs = gpu.recommended_jobs()

    # Workflow recommendation
    dur = media['duration']
    if aspect in ('9:16', 'vertical'):
        recommended = 'short'
        reason = f'Vertical recording ({v.get("width")}x{v.get("height")}, {fmt_dur(dur)}) — best edited in standalone Short/Reel mode (`ev2 init --mode short`).'
    elif dur <= 75.0:
        recommended = 'short'
        reason = f'Short clip ({fmt_dur(dur)}) — ideal for a punchy 9:16 Short/Reel (`ev2 init --mode short`) or a calm micro-tutorial.'
    else:
        recommended = 'tutorial'
        reason = f'Landscape recording ({v.get("width")}x{v.get("height")}, {fmt_dur(dur)}) — full YouTube tutorial (hook + body) + optional Pro Shorts, Thumbnails & YT Package.'

    warnings = list(audio_health['issues'])
    if v.get('vfr'):
        warnings.append(f'Variable frame rate detected ({v["avg_fps"]} avg vs {v["r_fps"]} nominal) — `ev2 init` will normalize cleanly to 30 fps CFR.')
    if not input_log and recommended == 'tutorial':
        warnings.append('No `ev2 rec` input log matched — zooms will use screen activity (no click ripples). Run `ev2 rec install` before next recording for Screen-Studio clicks.')
    if busy_gpu:
        names = ', '.join(f"{p['name']} ({p['used_mb']}MB)" for p in busy_gpu[:3])
        warnings.append(f'GPU already busy: {names} — avoid overlapping heavy GPU jobs (especially on 8 GB VRAM).')

    return {
        'path': os.path.abspath(path),
        'filename': os.path.basename(path),
        'duration': dur,
        'duration_fmt': fmt_dur(dur),
        'size_mb': media['size_mb'],
        'aspect': aspect,
        'video': v,
        'audio': a,
        'audio_health': audio_health,
        'input_log': input_log,
        'companion_cam': auto_cam,
        'gpu': gpu_st,
        'gpu_busy': busy_gpu,
        'recommended_jobs': rec_jobs,
        'recommended_mode': recommended,
        'recommended_reason': reason,
        'warnings': warnings,
    }


def print_report(info):
    v = info['video'] or {}
    a = info['audio'] or {}
    ah = info['audio_health']
    print(f"# Pre-Edit Inspection: {info['filename']}\n")
    print(f"- **File:** `{info['path']}` ({info['size_mb']} MB)")
    print(f"- **Video:** {v.get('width', '?')}x{v.get('height', '?')} ({info['aspect']}) @ {v.get('avg_fps', '?')} fps, {info['duration_fmt']} ({v.get('codec', '?')})")
    if a:
        lvl = f", mean {ah['mean_db']:.1f} dB / peak {ah['max_db']:.1f} dB" if ah.get('mean_db') is not None else ""
        print(f"- **Audio:** {a.get('codec', '?')} {a.get('sample_rate', '?')} Hz, {a.get('channels', '?')} ch{lvl}")
    else:
        print("- **Audio:** MISSING")
    print(f"- **Input log (`ev2 rec`):** {'FOUND — `' + os.path.basename(info['input_log']) + '` (exact click zooms + ripples)' if info['input_log'] else 'none (activity-based zooms)'}")
    print(f"- **Separate camera:** {'FOUND — `' + info['companion_cam'] + '`' if info['companion_cam'] else 'none (will check for Omarchy corner overlay on init)'}")
    print(f"- **Hardware:** {gpu._format_label(info['gpu'])} | recommended `--jobs {info['recommended_jobs']}`")
    print(f"\n**Recommended mode:** `{info['recommended_mode']}` — {info['recommended_reason']}")
    if info['warnings']:
        print("\n**Heads-up before editing:**")
        for w in info['warnings']:
            print(f"- {w}")
    print("\n**Suggested choices to confirm with the creator (Step 0):**")
    print("1. Format: Full YouTube Tutorial (16:9) | Tutorial + Pro 9:16 Shorts | Standalone 9:16 Short/Reel")
    print("2. Style: documentary (fast montage hook) | calm (clean title card)")
    print("3. Deliverables: `final.mp4` + Concat/Kdenlive | Pro Shorts (`ev2 shorts`) | Thumbnails (`ev2 thumb`) | YouTube Title/Description/Tags (`ev2 describe`)")
    print("4. Spoken language: darija (default) | en | fr")


def main():
    ap = argparse.ArgumentParser(description='Read-only pre-edit inspection & coaching brief for a recording.')
    ap.add_argument('recording', help='Path to recording file, or --latest')
    ap.add_argument('--cam', default=None, help='Optional separate camera file path')
    ap.add_argument('--json', action='store_true', help='Output JSON instead of markdown')
    a = ap.parse_args()

    rec = resolve_latest() if a.recording == '--latest' else a.recording
    if not rec or not os.path.isfile(rec):
        sys.exit(f'inspect: file not found: {a.recording}')
    try:
        info = inspect(rec, cam_path=a.cam)
    except Exception as e:
        sys.exit(f'inspect: ERROR {e}')

    if a.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print_report(info)
    return 0


if __name__ == '__main__':
    sys.exit(main())
