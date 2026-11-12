#!/usr/bin/env python3
"""short-extract.py — 9:16 vertical YouTube Short extractor for Editor V2.

Reframes the hook (15-25 s recommended, at most 60 s) into a 1080x1920 (9:16) vertical YouTube Short (out/short.mp4)
using FFmpeg filter_complex:
  - Darkened, blurred 1080x1920 background
  - Foreground:
    - If --stack-cam and omarchy.json indicates webcam overlay:
      Stacked webcam in bottom third (1080x640) + centered screencast in top two-thirds (1080x1280)
    - Default:
      Full sharp 16:9 frame centered (1080x608, or 8:9 1080x1215 crop) over blurred backdrop
  - Clamps duration to min(input_duration, --dur, 59.0s)

finish.py feeds it out/hook.mp4 (the hook is the most shareable minute). --stack-cam only
makes sense on footage where the webcam sits at omarchy.json's webcam_box (raw screencast).

Usage:
    $EV1_PY short-extract.py <in.mp4> <out/short.mp4> [--dur 58.0] [--omarchy-json work/omarchy.json] [--stack-cam]
"""
import argparse, json, math, os, re, subprocess, sys

# Auto-locate environment Python if launched from bare interpreter
for candidate in [
    os.environ.get('EV2_PY'),
    os.environ.get('EV1_PY'),
    os.path.expanduser('~/.cache/editor-v2/venv/bin/python'),
]:
    if candidate and os.path.isfile(candidate):
        try:
            if os.path.samefile(candidate, sys.executable):
                break
        except OSError:
            pass
        if os.path.realpath(candidate) != os.path.realpath(sys.executable):
            os.execv(candidate, [candidate] + sys.argv)
        break


def probe_video(path):
    """Probe duration, streams, and dimensions of input video."""
    if not path or not os.path.isfile(path):
        return None
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration:stream=codec_type,width,height,duration,r_frame_rate',
            '-of', 'json', path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        dur = 0.0
        if 'format' in data and 'duration' in data['format']:
            try:
                dur = float(data['format']['duration'])
            except (ValueError, TypeError):
                dur = 0.0
        streams = data.get('streams', [])
        v_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
        has_audio = any(s.get('codec_type') == 'audio' for s in streams)
        w, h = 1920, 1080
        if v_stream:
            w = int(v_stream.get('width', 1920))
            h = int(v_stream.get('height', 1080))
            if 'duration' in v_stream:
                try:
                    dur = max(dur, float(v_stream['duration']))
                except (ValueError, TypeError):
                    pass
        return {
            'duration': dur,
            'width': w,
            'height': h,
            'has_audio': has_audio
        }
    except Exception as e:
        print(f"Error: probe failed for {path}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description='9:16 vertical YouTube Short extractor for Editor V2')
    parser.add_argument('input_video', help='Input video file (e.g. out/render.mp4 or out/final.mp4)')
    parser.add_argument('output_short', help='Output short video file (e.g. out/short.mp4)')
    parser.add_argument('--dur', type=float, default=58.0,
                        help='Target short duration in seconds (default: 58.0, clamped to <= 59.0)')
    parser.add_argument('--omarchy-json', default=None,
                        help='Path to omarchy.json metadata (auto-detected if omitted)')
    parser.add_argument('--stack-cam', action='store_true',
                        help='Stack cropped Omarchy webcam in bottom third and screencast in top two-thirds')
    parser.add_argument('--framing', default='fit', choices=['fit', 'crop', '8:9'],
                        help='Framing mode for standard overlay (fit=1080x608, crop/8:9=1080x1215)')
    args = parser.parse_args()

    in_path = os.path.abspath(args.input_video)
    if not os.path.isfile(in_path):
        print(f"Error: input video does not exist: {in_path}", file=sys.stderr)
        sys.exit(1)

    out_path = os.path.abspath(args.output_short)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Probe input video
    info = probe_video(in_path)
    if not info or info['duration'] <= 0:
        print(f"Error: unable to probe video {in_path}", file=sys.stderr)
        sys.exit(1)

    # Clamp duration to min(input_duration, --dur, 59.0s)
    target_dur = min(info['duration'], args.dur, 59.0)
    target_dur = max(0.5, round(target_dur, 3))

    # Locate omarchy.json if requested or available
    omarchy_path = args.omarchy_json
    if not omarchy_path:
        # Check standard relative locations
        candidates = [
            os.path.join(os.path.dirname(in_path), 'work', 'omarchy.json'),
            os.path.join(os.path.dirname(os.path.dirname(in_path)), 'work', 'omarchy.json'),
            os.path.join(out_dir, '..', 'work', 'omarchy.json'),
            'work/omarchy.json',
            'omarchy.json'
        ]
        for c in candidates:
            if os.path.isfile(c):
                omarchy_path = os.path.abspath(c)
                break

    omarchy_data = None
    if omarchy_path and os.path.isfile(omarchy_path):
        try:
            with open(omarchy_path, 'r', encoding='utf-8') as f:
                omarchy_data = json.load(f)
        except Exception as e:
            print(f"Warning: could not read {omarchy_path}: {e}", file=sys.stderr)

    use_stacked_cam = False
    webcam_box = None
    if args.stack_cam:
        if omarchy_data and omarchy_data.get('has_webcam_overlay') and omarchy_data.get('webcam_box'):
            box = omarchy_data['webcam_box']
            if isinstance(box, (list, tuple)) and len(box) == 4:
                webcam_box = box
                use_stacked_cam = True
        if not use_stacked_cam:
            print("Warning: --stack-cam requested, but no valid webcam overlay found in omarchy.json. "
                  "Using centered framing instead.", file=sys.stderr)

    # Build FFmpeg filter_complex
    # 1. Background: scaled/cropped to 1080x1920, blurred and darkened
    bg_filter = (
        "[0:v]scale=w=1080:h=1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "boxblur=25:10,"
        "colorchannelmixer=aa=1.0:rr=0.35:gg=0.35:bb=0.35[bg]"
    )

    if use_stacked_cam:
        bx, by, bw, bh = webcam_box
        fg_filter = (
            f"[0:v]crop=w='min(iw,ih*1080/1280)':h='ih':x='(iw-ow)/2':y=0,scale=1080:1280[screen];"
            f"[0:v]crop=w={bw}:h={bh}:x={bx}:y={by},scale=1080:640:force_original_aspect_ratio=increase,crop=1080:640[cam]"
        )
        comp_filter = (
            "[bg][screen]overlay=0:0[bg_scr];"
            "[bg_scr][cam]overlay=0:1280[v]"
        )
        filter_complex = f"{bg_filter};{fg_filter};{comp_filter}"
    elif args.framing in ['8:9', 'crop']:
        fg_filter = "[0:v]crop=w='min(iw,ih*8/9)':h='min(ih,iw*9/8)':x='(iw-ow)/2':y='(ih-oh)/2',scale=1080:1215[fg]"
        comp_filter = "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2[v]"
        filter_complex = f"{bg_filter};{fg_filter};{comp_filter}"
    else:
        # Default: sharp 16:9 frame centered (1080x608)
        fg_filter = "[0:v]scale=1080:608[fg]"
        comp_filter = "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2[v]"
        filter_complex = f"{bg_filter};{fg_filter};{comp_filter}"

    # Construct ffmpeg command
    cmd = [
        'ffmpeg', '-y',
        '-i', in_path,
        '-filter_complex', filter_complex,
        '-map', '[v]',
    ]

    if info['has_audio']:
        cmd.extend(['-map', '0:a:0?', '-c:a', 'aac', '-b:a', '192k'])

    cmd.extend([
        '-t', str(target_dur),
        '-c:v', 'libx264',
        '-crf', '18',
        '-preset', 'fast',
        '-pix_fmt', 'yuv420p',
        '-r', '30',
        out_path
    ])

    print(f"Extracting 9:16 Short (target duration: {target_dur}s, stacked_cam: {use_stacked_cam})...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"FFmpeg failed:\n{res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)

    print(f"Successfully generated Short: {out_path} ({target_dur}s, 1080x1920)")


if __name__ == '__main__':
    main()
