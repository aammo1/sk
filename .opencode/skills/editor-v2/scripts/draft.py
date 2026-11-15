#!/usr/bin/env python3
"""draft.py — fast 720p rough cut right after `ev2 transcribe` (before the PLAN gate).

    draft.py <video-dir> [--retakes] [--out out/draft.mp4] [--height 720] [--no-labels] [--no-open]

Builds a quick preview (hook as recorded + body kept segments, cleaned voice, separate-camera
PiP when present, and burned-in source-time / retake / chapter labels) without touching any
final deliverable, timeline.json, cuts.json, or the Concat project.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'components'))
import ev2_pro as P  # noqa: E402
import ev2_timeline as TL  # noqa: E402
import finish as F  # noqa: E402
import gpu  # noqa: E402

FPS = TL.FPS
SPF = TL.SAMPLES_PER_FRAME


def subtract(segs, cuts):
    """Subtract [(f0, f1)] source-frame cut ranges from body segments in memory."""
    out = []
    for s in segs:
        if s.get('card'):
            continue
        pieces = [(s['f_start'], s['f_end'])]
        for c0, c1 in cuts:
            pieces = [p for a, b in pieces for p in ((a, min(b, c0)), (max(a, c1), b)) if p[1] > p[0]]
        out += pieces
    rebuilt, pos = [], 0
    for a, b in out:
        n = b - a
        if n <= 0:
            continue
        rebuilt.append({
            'card': False,
            'src_start': a / FPS,
            'src_end': b / FPS,
            'f_start': a,
            'f_end': b,
            'out_start': pos / FPS,
            'out_end': (pos + n) / FPS,
        })
        pos += n
    return rebuilt


def has_subtitles_filter():
    try:
        r = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, timeout=5)
        return ' subtitles ' in (r.stdout or '')
    except (OSError, subprocess.TimeoutExpired):
        return False


def ff_filter_escape(s):
    """Escape a path for FFmpeg filter option values."""
    for ch in ('\\', ':', "'", '[', ']', ',', ';'):
        s = s.replace(ch, '\\' + ch)
    return s


def ass_ts(t):
    cs = max(0, int(round(float(t) * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def ass_escape(text):
    text = str(text or '').replace('\r\n', ' ').replace('\n', ' ').strip()
    return text.replace('{', r'\{').replace('}', r'\}')


def src_to_draft_t(t, hs, hook_dur, segs):
    """Map source time `t` to draft output time (None if after last kept segment)."""
    if t < hs:
        return max(0.0, float(t))
    for s in segs:
        if s.get('card'):
            continue
        if t < s['src_start']:
            return hook_dur + s['out_start']
        if t < s['src_end']:
            return hook_dur + s['out_start'] + (t - s['src_start'])
    return None


def draft_frame_to_src_t(f, NH, segs):
    """Map draft output frame index `f` to source time in seconds."""
    if f < NH:
        return f / FPS
    bf = f - NH
    pos = 0
    last_src_end = 0.0
    for s in segs:
        if s.get('card'):
            continue
        n = s['f_end'] - s['f_start']
        last_src_end = s['src_end']
        if bf < pos + n:
            return (s['f_start'] + (bf - pos)) / FPS
        pos += n
    return last_src_end


def write_labels_ass(ass_path, hs, NH, segs, cands, chapters, retakes_removed):
    """Write ASS subtitle events (source times, retake markers, chapters, draft badge)."""
    hook_dur = NH / FPS
    body_frames = sum(s['f_end'] - s['f_start'] for s in segs if not s.get('card'))
    total_frames = NH + body_frames
    total_dur = total_frames / FPS

    lines = [
        '[Script Info]',
        'ScriptType: v4.00+',
        'PlayResX: 1280',
        'PlayResY: 720',
        'WrapStyle: 0',
        '',
        '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
        'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding',
        'Style: SrcTime,Inter,24,&H00FFFFFF,&H000000FF,&H48000000,&H48000000,1,0,0,0,100,100,0,0,3,6,0,7,18,18,14,1',
        'Style: Retake,Cairo,24,&H00FFFFFF,&H000000FF,&H202020CC,&H202020CC,1,0,0,0,100,100,0,0,3,8,0,8,24,24,14,1',
        'Style: Cut,Inter,24,&H00FFFFFF,&H000000FF,&H30905018,&H30905018,1,0,0,0,100,100,0,0,3,8,0,8,24,24,14,1',
        'Style: Chapter,Cairo,26,&H00FFFFFF,&H000000FF,&H40000000,&H40000000,1,0,0,0,100,100,0,0,3,8,0,1,20,20,18,1',
        'Style: DraftBadge,Inter,22,&H00E0E0E0,&H000000FF,&H48000000,&H48000000,1,0,0,0,100,100,0,0,3,6,0,9,18,18,14,1',
        '',
        '[Events]',
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]

    def add_ev(layer, t0, t1, style, text):
        if t1 > t0 + 0.01:
            lines.append(f'Dialogue: {layer},{ass_ts(t0)},{ass_ts(t1)},{style},,0,0,0,,{text}')

    # 1. Source time every output second
    n_secs = int(math.ceil(total_dur))
    for sec in range(n_secs):
        t0 = float(sec)
        t1 = min(total_dur, float(sec + 1))
        if t1 <= t0 + 0.01:
            continue
        f = min(total_frames - 1, sec * FPS)
        src_t = draft_frame_to_src_t(f, NH, segs)
        add_ev(0, t0, t1, 'SrcTime', f'src {TL.fmt_ts(src_t)}')

    # 2. Retakes / Cut markers
    if retakes_removed:
        for k, r in enumerate(cands, 1):
            cut_src = max(hs, float(r['start']) - 0.08)
            d0 = src_to_draft_t(cut_src, hs, hook_dur, segs)
            if d0 is None:
                d0 = max(0.0, total_dur - 1.5)
            d1 = min(total_dur, d0 + 1.5)
            add_ev(1, d0, d1, 'Cut', f'CUT #{k}')
    else:
        for k, r in enumerate(cands, 1):
            r_start = max(hs, float(r['start']))
            r_end = max(hs, float(r['next_start']))
            d0 = src_to_draft_t(r_start, hs, hook_dur, segs)
            d1 = src_to_draft_t(r_end, hs, hook_dur, segs)
            if d0 is None:
                continue
            if d1 is None:
                d1 = total_dur
            if d1 > d0 + 0.05:
                dropped = ass_escape((r.get('dropped_text') or '')[:40])
                msg = f'RETAKE? #{k}  (cut: --retakes)'
                if dropped:
                    msg += f'\\N{dropped}'
                add_ev(1, d0, d1, 'Retake', msg)

    # 3. Chapters
    for idx, ch in enumerate(chapters, 1):
        d0 = src_to_draft_t(float(ch['src_t']), hs, hook_dur, segs)
        if d0 is None or d0 >= total_dur:
            continue
        d1 = min(total_dur, d0 + 3.0)
        title = ass_escape(ch.get('title', ''))
        add_ev(1, d0, d1, 'Chapter', f'CH {idx} · {title}')

    # 4. Draft badge (first 3 s)
    if total_dur > 0.05:
        add_ev(2, 0.0, min(total_dur, 3.0), 'DraftBadge', 'DRAFT · not the final look')

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--retakes', action='store_true', help='Preview with every detected retake removed')
    ap.add_argument('--out', default='out/draft.mp4', help='Output path (default out/draft.mp4)')
    ap.add_argument('--height', type=int, default=720, help='Output height in pixels (default 720)')
    ap.add_argument('--no-labels', action='store_true', help='Skip burned-in time/retake/chapter labels')
    ap.add_argument('--no-open', action='store_true', help='Do not open the draft video when done')
    a = ap.parse_args()

    t0 = time.time()
    vd = os.path.abspath(a.video_dir)
    os.chdir(vd)

    tl = TL.load(vd)
    hs = float(tl['hook_split'])
    NH = TL.frames(hs)
    tl_draft = dict(tl)
    tl_draft['_chapter_cards'] = {'style': 'bar', 'hold': 0}
    segs = TL.body_segments(tl_draft)
    if not segs:
        raise SystemExit('draft: no body segments: run ev2 transcribe first')

    for req in ('assets/media/cam_raw.mp4', 'assets/media/vo.wav'):
        if not os.path.isfile(req):
            raise SystemExit(f'draft: {req} missing: run ev2 init first')

    cuts_path = os.path.join(vd, 'work', 'cuts.json')
    cands = []
    if os.path.isfile(cuts_path):
        try:
            cands = json.load(open(cuts_path, encoding='utf-8')).get('retakes_detected') or []
        except (ValueError, OSError):
            cands = []

    if a.retakes and cands:
        cut_ranges = []
        for r in cands:
            rs = max(hs, float(r['start']) - 0.08)
            re_ = max(hs, float(r['next_start']) - 0.08)
            c0, c1 = TL.frames(rs), TL.frames(re_)
            if c1 > c0:
                cut_ranges.append((c0, c1))
        if cut_ranges:
            segs = subtract(segs, cut_ranges)
            if not segs:
                raise SystemExit('draft: no body segments left after removing retakes')

    os.makedirs('work/draft', exist_ok=True)
    out_path = a.out
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # Voice cleanup (shared cache with finish.py) + hook/body concatenation
    voice = F.clean_voice('assets/media/vo.wav', 'work/vo_clean.wav')
    body_voice_path = 'work/draft/body_voice.wav'
    F.write_body_voice(voice, segs, body_voice_path, hs)

    hook_samples = NH * SPF
    if hook_samples > 0:
        v_arr, sr = sf.read(voice, dtype='float32', always_2d=True)
        if sr != TL.SR:
            raise SystemExit(f'draft: {voice} is {sr} Hz, expected {TL.SR}')
        if v_arr.shape[1] == 1:
            v_arr = np.repeat(v_arr, 2, axis=1)
        v_arr = v_arr[:, :2]
        hook_arr = v_arr[:hook_samples]
        if len(hook_arr) < hook_samples:
            hook_arr = np.pad(hook_arr, ((0, hook_samples - len(hook_arr)), (0, 0)))
    else:
        hook_arr = np.zeros((0, 2), np.float32)

    body_arr, _ = sf.read(body_voice_path, dtype='float32', always_2d=True)
    joined_audio = np.concatenate([hook_arr, body_arr]) if len(hook_arr) else body_arr
    audio_path = 'work/draft/audio.wav'
    sf.write(audio_path, joined_audio, TL.SR, subtype='PCM_24')

    # Video select & separate camera PiP
    body_expr = F.select_expr(segs)
    sel = f'between(n,0,{NH - 1})+{body_expr}' if NH > 0 else body_expr

    height = max(2, int(round(a.height / 2) * 2))
    cam_src = P.camera_source(vd)
    use_sep_cam = cam_src.get('mode') == 'separate'

    inputs = ['-i', 'assets/media/cam_raw.mp4']
    chains = [f"[0:v]select='{sel}',setpts=N/{FPS}/TB,scale=-2:{height},setsar=1[scr]"]
    v_tag = 'scr'

    if use_sep_cam:
        inputs += ['-i', cam_src['path']]
        cx, cy, cw, ch = cam_src['crop']
        px, py, pw, ph = cam_src['pip_rect']
        sc = height / 1080.0
        spx = int(round(px * sc))
        spy = int(round(py * sc))
        spw = max(2, int(round(pw * sc / 2) * 2))
        sph = max(2, int(round(ph * sc / 2) * 2))
        chains.append(f"[1:v]select='{sel}',setpts=N/{FPS}/TB,crop={cw}:{ch}:{cx}:{cy},scale={spw}:{sph},setsar=1[pip]")
        chains.append(f"[{v_tag}][pip]overlay=x={spx}:y={spy}:eof_action=pass[comp]")
        v_tag = 'comp'

    if not a.no_labels:
        if has_subtitles_filter():
            ass_path = 'work/draft/labels.ass'
            write_labels_ass(ass_path, hs, NH, segs, cands, tl.get('chapters') or [], a.retakes)
            fonts_dir = ff_filter_escape(os.path.join(SK, 'assets', 'fonts'))
            chains.append(f"[{v_tag}]subtitles=filename='{ass_path}':fontsdir='{fonts_dir}'[lbl]")
            v_tag = 'lbl'
        else:
            print('draft: WARNING ffmpeg lacks subtitles filter; skipping labels', file=sys.stderr)

    ai = len(inputs) // 2
    inputs += ['-i', audio_path]
    chains.append(f'[{ai}:a:0]loudnorm=I=-16:TP=-1.5:LRA=11[a]')

    fg_path = 'work/draft/draft.filtergraph'
    with open(fg_path, 'w', encoding='utf-8') as f:
        f.write(';\n'.join(chains) + '\n')

    enc_args = gpu.venc(['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26'], 28)
    tmp_out = (out_path[:-4] + '.tmp.mp4') if out_path.lower().endswith('.mp4') else (out_path + '.tmp.mp4')
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'error', '-y',
        *inputs,
        '-/filter_complex', fg_path,
        '-map', f'[{v_tag}]', '-map', '[a]',
        *enc_args,
        '-pix_fmt', 'yuv420p', '-r', str(FPS),
        '-c:a', 'aac', '-b:a', '128k', '-ar', str(TL.SR),
        '-movflags', '+faststart', '-f', 'mp4', tmp_out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or '').strip().splitlines()[-15:]
        raise SystemExit(f'draft: ffmpeg failed (exit {r.returncode}):\n    ' + '\n    '.join(tail))
    os.replace(tmp_out, out_path)

    body_dur = sum(s['f_end'] - s['f_start'] for s in segs) / FPS
    hook_dur = NH / FPS
    total_dur = hook_dur + body_dur
    elapsed = round(time.time() - t0, 1)

    meta = {
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'retakes_removed': bool(a.retakes),
        'duration': round(total_dur, 3),
        'hook': round(hook_dur, 3),
        'body': round(body_dur, 3),
        'segments': len(segs),
        'seconds_to_render': elapsed,
        'gpu': gpu.enabled(),
    }
    with open('work/draft/draft.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)
        f.write('\n')

    n_cands = len(cands)
    if a.retakes:
        retake_note = f'{n_cands} retake{"s" if n_cands != 1 else ""} removed'
    else:
        retake_note = f'{n_cands} retake candidate{"s" if n_cands != 1 else ""} shown'
    print(f'draft: {out_path} ({TL.fmt_ts(total_dur)} = hook {TL.fmt_ts(hook_dur)} + body {TL.fmt_ts(body_dur)}, '
          f'{retake_note}) in {elapsed:g} s', flush=True)
    print('Watch it, then fill PLAN.md (ev2 draft --retakes shows the cut with every retake removed)', flush=True)

    if not a.no_open and sys.platform.startswith('linux') and (
            os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY')):
        subprocess.Popen(['xdg-open', out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except TL.TimelineError as e:
        print(f'draft: ERROR {e}', file=sys.stderr)
        sys.exit(1)
