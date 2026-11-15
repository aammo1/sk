#!/usr/bin/env python3
"""camsync.py — line up a separately recorded camera with the screen recording (by audio).

    camsync.py measure <screen-media> <cam-media> [--guess S] [--window S]
    camsync.py import <video-dir> --cam FILE [--offset S] [--voice screen|cam] [--guess S] [--source import|ev2-rec]
    camsync.py find <recording> [--vd DIR]  # prints the ev2 rec camera file and guess offset, if any
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

try:
    import numpy as np
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402
import gpu  # noqa: E402


def load_audio(path, sr=8000):
    """Mono float32 at sr Hz via ffmpeg (first audio stream). Empty array if none."""
    p = subprocess.run(
        ['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-map', '0:a:0',
         '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
        capture_output=True,
    )
    return np.frombuffer(p.stdout, np.float32).copy() if p.returncode == 0 else np.zeros(0, np.float32)


def envelope(x, sr, out_sr=1000):
    """Onset-ish envelope: |x| smoothed and decimated to out_sr, then high-passed (minus a 0.5 s
    moving average) and normalised, so loudness differences between mics do not matter."""
    if len(x) == 0:
        return np.zeros(0, np.float32)
    step = max(1, int(round(sr / out_sr)))
    n = (len(x) // step) * step
    if n == 0:
        return np.zeros(0, np.float32)
    e = np.abs(x[:n].astype(np.float32)).reshape(-1, step).mean(axis=1)
    w = max(1, int(round(0.5 * out_sr)))
    if w > 1 and len(e) >= 2:
        pad_l = w // 2
        pad_r = w - 1 - pad_l
        padded = np.pad(e, (pad_l, pad_r), mode='edge')
        cs = np.cumsum(np.insert(padded.astype(np.float64), 0, 0.0))
        ma = ((cs[w:] - cs[:-w]) / w).astype(np.float32)
        e = e - ma
    std = float(np.std(e))
    if std < 1e-8:
        return np.zeros_like(e)
    return ((e - float(np.mean(e))) / std).astype(np.float32)


def xcorr_lag(ref, cam, sr, lo, hi):
    """Best lag L in seconds (lo <= L <= hi) maximising sum ref[t] * cam[t + L], via FFT
    (np.fft.rfft, zero-padded to next power of 2 >= len(ref)+len(cam)). Returns (L, peak, score)
    where score = (peak - median) / std of the correlation inside [lo, hi]."""
    if len(ref) == 0 or len(cam) == 0:
        return (float(lo), 0.0, 0.0)
    r = ref.astype(np.float32, copy=False)
    c = cam.astype(np.float32, copy=False)
    r = r - float(np.mean(r))
    c = c - float(np.mean(c))
    nfft = 1 << (len(r) + len(c) - 1).bit_length()
    cc = np.fft.irfft(np.conj(np.fft.rfft(r, nfft)) * np.fft.rfft(c, nfft), nfft)
    d_lo = max(int(np.floor(lo * sr)), -(len(r) - 1))
    d_hi = min(int(np.ceil(hi * sr)), len(c) - 1)
    if d_lo > d_hi:
        return (float(lo), 0.0, 0.0)
    lags = np.arange(d_lo, d_hi + 1)
    vals = cc[lags % nfft]
    idx = int(np.argmax(vals))
    peak = float(vals[idx])
    med = float(np.median(vals))
    std = float(np.std(vals))
    score = (peak - med) / std if std > 1e-9 else 0.0
    return (float(lags[idx]) / sr, peak, float(score))


def _loudest_window(audio, sr, start_s, end_s, dur_s=30.0):
    """Return (ex_start_idx, ex_end_idx) for a dur_s slice around the loudest part in [start_s, end_s]."""
    i0 = max(0, int(round(start_s * sr)))
    i1 = min(len(audio), int(round(end_s * sr)))
    win = max(1, int(round(dur_s * sr)))
    if i1 - i0 <= win:
        return i0, i1
    seg = audio[i0:i1]
    blk = min(len(seg), max(1, int(sr)))
    sq = seg.astype(np.float64) ** 2
    cs = np.cumsum(np.insert(sq, 0, 0.0))
    e1s = cs[blk:] - cs[:-blk]
    peak_idx = int(np.argmax(e1s)) + blk // 2
    rel = min(max(0, peak_idx - win // 2), len(seg) - win)
    return i0 + rel, i0 + rel + win


def _refine_lag(ref_8k, cam_8k, env_ref, env_cam, sr, env_sr, start_s, end_s, center_guess, radius):
    """Find refined lag on a 30 s excerpt in [start_s, end_s] around center_guess +- radius."""
    i0, i1 = _loudest_window(ref_8k, sr, start_s, end_s, dur_s=30.0)
    t_start = i0 / sr
    t_center = 0.5 * (i0 + i1) / sr
    if radius > 0.05:
        ei0 = min(len(env_ref), int(round(t_start * env_sr)))
        ei1 = min(len(env_ref), max(ei0 + 1, int(round((i1 / sr) * env_sr))))
        e_start = ei0 / env_sr
        l_rel, _, _ = xcorr_lag(
            env_ref[ei0:ei1], env_cam, env_sr,
            center_guess - radius + e_start,
            center_guess + radius + e_start,
        )
        l_env = l_rel - e_start
    else:
        l_env = center_guess
    l_8k_rel, _, score_8k = xcorr_lag(
        ref_8k[i0:i1], cam_8k, sr,
        l_env - 0.05 + t_start,
        l_env + 0.05 + t_start,
    )
    l_8k = l_8k_rel - t_start
    # Keep 8 kHz sub-ms lag when waveform phase correlates cleanly; fall back to 1 kHz envelope
    # (1 ms precision) when WSOLA/atempo or room reverb scrambles carrier phase.
    lag = l_8k if score_8k >= 3.5 else l_env
    return lag, t_center


def measure(ref_audio, cam_audio, sr=8000, guess=None, window=None):
    """-> {'offset', 'rate', 'confidence', 'drift_ms', 'method', 'ok'}"""
    if len(ref_audio) == 0 or len(cam_audio) == 0:
        return {
            'offset': 0.0, 'rate': 1.0, 'confidence': 0.0,
            'drift_ms': 0.0, 'method': 'audio-xcorr', 'ok': False,
        }
    env_sr = 1000
    env_ref = envelope(ref_audio, sr, out_sr=env_sr)
    env_cam = envelope(cam_audio, sr, out_sr=env_sr)
    if len(env_ref) == 0 or len(env_cam) == 0 or np.all(env_ref == 0) or np.all(env_cam == 0):
        return {
            'offset': 0.0, 'rate': 1.0, 'confidence': 0.0,
            'drift_ms': 0.0, 'method': 'audio-xcorr', 'ok': False,
        }
    len_ref_s = len(ref_audio) / sr
    len_cam_s = len(cam_audio) / sr
    if guess is not None:
        w = 10.0 if window is None else float(window)
        lo, hi = float(guess) - w, float(guess) + w
    else:
        lim = min(300.0, max(len_cam_s, len_ref_s))
        lo, hi = -lim, min(300.0, len_cam_s)

    l0, _, score = xcorr_lag(env_ref, env_cam, env_sr, lo, hi)
    confidence = min(1.0, max(0.0, score / 20.0))
    ok = confidence >= 0.25

    l_refined, _ = _refine_lag(
        ref_audio, cam_audio, env_ref, env_cam, sr, env_sr,
        0.0, len_ref_s, l0, 0.05,
    )

    a, b, drift_ms = l_refined, 1.0, 0.0
    if ok and len_ref_s > 120.0:
        l1, t1 = _refine_lag(
            ref_audio, cam_audio, env_ref, env_cam, sr, env_sr,
            0.0, 60.0, l_refined, 1.0,
        )
        l2, t2 = _refine_lag(
            ref_audio, cam_audio, env_ref, env_cam, sr, env_sr,
            len_ref_s - 60.0, len_ref_s, l_refined, 1.0,
        )
        drift_ms = (l2 - l1) * 1000.0
        if abs(l2 - l1) > 1.0 / TL.FPS and abs(t2 - t1) > 1.0:
            b = 1.0 + (l2 - l1) / (t2 - t1)
            a = l1 + t1 - b * t1
        else:
            b = 1.0
            a = l_refined

    return {
        'offset': round(float(a), 4),
        'rate': round(float(b), 7),
        'confidence': round(float(confidence), 4),
        'drift_ms': round(float(drift_ms), 1),
        'method': 'audio-xcorr',
        'ok': bool(ok),
    }


def _probe_frames(path):
    """Return exact frame count of stream v:0 via ffprobe."""
    p = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0',
         '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', path],
        capture_output=True, text=True,
    )
    if p.returncode == 0:
        val = (p.stdout or '').strip().splitlines()
        if val and val[0].isdigit():
            return int(val[0])
    p2 = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
        capture_output=True, text=True,
    )
    try:
        return int(round(float((p2.stdout or '').strip()) * TL.FPS))
    except ValueError:
        return 0


def _probe_video_size(path):
    """Return display (width, height) of stream v:0, accounting for rotation metadata."""
    p = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height:stream_tags=rotate:stream_side_data=rotation',
         '-of', 'json', path],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise SystemExit(f'camsync: ffprobe failed on {path}: {(p.stderr or "").strip()}')
    try:
        info = json.loads(p.stdout)
        st = (info.get('streams') or [])[0]
        w, h = int(st['width']), int(st['height'])
    except (ValueError, KeyError, IndexError, TypeError):
        raise SystemExit(f'camsync: no video stream in {path}')
    rot = 0
    tags = st.get('tags') or {}
    if 'rotate' in tags:
        try:
            rot = int(float(tags['rotate']))
        except ValueError:
            pass
    for sd in st.get('side_data_list') or []:
        if 'rotation' in sd:
            try:
                rot = int(round(float(sd['rotation'])))
            except ValueError:
                pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    if w <= 0 or h <= 0:
        raise SystemExit(f'camsync: invalid camera dimensions {w}x{h} in {path}')
    return w, h


def _has_audio(path):
    p = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
         '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
        capture_output=True, text=True,
    )
    return p.returncode == 0 and 'audio' in (p.stdout or '')


def _render_cam_face(cam_src, out_path, n_frames, ow, oh, a, b):
    """Write assets/media/cam_face.mp4 aligned to screen frames 0..n_frames-1."""
    stop_dur = max(600.0, n_frames / TL.FPS + 60.0)
    inp = ['-ss', f'{a:.6f}', '-i', cam_src] if a >= 0 else ['-i', cam_src]
    vf_parts = [f'setpts=(PTS-STARTPTS)/{b:.8f}']
    if a < 0:
        vf_parts.append(f'tpad=start_duration={-a / b:.4f}:start_mode=clone')
    vf_parts.append(
        f'fps={TL.FPS},scale={ow}:{oh},setsar=1,format=yuv420p,'
        f'tpad=stop_mode=clone:stop_duration={stop_dur:.1f},trim=end_frame={n_frames}'
    )
    enc = gpu.venc(['-c:v', 'libx264', '-preset', 'fast', '-crf', '16'], 16)
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'error', '-y',
        *inp,
        '-vf', ','.join(vf_parts),
        *enc,
        '-g', str(TL.FPS), '-pix_fmt', 'yuv420p', '-an',
        '-color_range', 'tv', '-colorspace', 'bt709',
        '-color_primaries', 'bt709', '-color_trc', 'bt709',
        out_path,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f'camsync: ffmpeg failed encoding cam_face.mp4: {(p.stderr or "").strip()}')
    got = _probe_frames(out_path)
    if got != n_frames:
        raise SystemExit(f'camsync: cam_face.mp4 frame count mismatch: got {got}, expected {n_frames}')


def _render_cam_voice(cam_src, vo_wav, vo_screen, n_frames, a, b):
    """Replace vo.wav with aligned camera voice (48 kHz 24-bit stereo, N * 1600 samples)."""
    if not _has_audio(cam_src):
        raise SystemExit(f'camsync: --voice cam requested but {cam_src} has no audio stream')
    if not os.path.isfile(vo_screen) and os.path.isfile(vo_wav):
        os.replace(vo_wav, vo_screen)
    inp = ['-ss', f'{a:.6f}', '-i', cam_src] if a >= 0 else ['-i', cam_src]
    af_parts = [f'aresample={TL.SR}']
    if abs(b - 1.0) > 1e-9:
        tempo = min(2.0, max(0.5, b))
        af_parts.append(f'atempo={tempo:.8f}')
    if a < 0:
        delay_ms = max(0, int(round((-a / b) * 1000.0)))
        if delay_ms > 0:
            af_parts.append(f'adelay={delay_ms}:all=1')
    target_samples = n_frames * TL.SAMPLES_PER_FRAME
    af_parts.extend(['apad', f'atrim=end_sample={target_samples}'])
    tmp_wav = vo_wav + '.tmp.wav'
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'error', '-y',
        *inp, '-map', '0:a:0',
        '-af', ','.join(af_parts),
        '-ac', '2', '-ar', str(TL.SR), '-c:a', 'pcm_s24le',
        tmp_wav,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        if os.path.exists(tmp_wav):
            os.unlink(tmp_wav)
        raise SystemExit(f'camsync: ffmpeg failed extracting camera voice: {(p.stderr or "").strip()}')
    os.replace(tmp_wav, vo_wav)


def cmd_measure(args):
    ref = load_audio(args.screen)
    cam = load_audio(args.cam)
    res = measure(ref, cam, guess=args.guess, window=args.window)
    print(json.dumps(res, indent=2))
    return 0


def cmd_import(args):
    vd = os.path.abspath(args.video_dir)
    cam_in = os.path.abspath(args.cam)
    if not os.path.isfile(cam_in):
        raise SystemExit(f'camsync: camera file not found: {cam_in}')

    media_dir = os.path.join(vd, 'assets', 'media')
    work_dir = os.path.join(vd, 'work')
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    cam_raw = os.path.join(media_dir, 'cam_raw.mp4')
    if not os.path.isfile(cam_raw):
        raise SystemExit(f'camsync: {cam_raw} not found')
    n_frames = _probe_frames(cam_raw)
    if n_frames <= 0:
        raise SystemExit(f'camsync: could not read frame count from {cam_raw}')

    vo_wav = os.path.join(media_dir, 'vo.wav')
    vo_screen = os.path.join(media_dir, 'vo_screen.wav')
    ref_wav = vo_screen if os.path.isfile(vo_screen) else vo_wav
    if (args.offset is None or args.voice == 'screen') and not os.path.isfile(ref_wav):
        raise SystemExit(f'camsync: {ref_wav} not found')

    ext = os.path.splitext(cam_in)[1].lower() or '.mp4'
    rel_src = f'assets/media/cam_src{ext}'
    dst = os.path.join(vd, rel_src)
    if os.path.realpath(cam_in) != os.path.realpath(dst):
        if os.path.lexists(dst):
            os.unlink(dst)
        try:
            os.link(cam_in, dst)
        except OSError:
            shutil.copy2(cam_in, dst)

    if args.offset is not None:
        a = float(args.offset)
        b = 1.0
        conf = 1.0
        drift_ms = 0.0
        method = 'forced'
    else:
        cam_audio = load_audio(dst)
        if len(cam_audio) == 0:
            if args.guess is not None:
                a, b, conf, drift_ms, method = float(args.guess), 1.0, 0.0, 0.0, 'wallclock'
                print('camsync: WARNING camera file has no audio; using wallclock guess offset', file=sys.stderr)
            else:
                raise SystemExit('camsync: the camera file has no audio: pass --cam-offset S (cam_t = screen_t + S)')
        else:
            ref_audio = load_audio(ref_wav)
            res = measure(ref_audio, cam_audio, guess=args.guess)
            if not res['ok']:
                if args.guess is not None:
                    a = float(args.guess)
                    b = 1.0
                    conf = res['confidence']
                    drift_ms = 0.0
                    method = 'wallclock'
                    print(f'camsync: WARNING audio sync confidence {conf:.2f} too low; using wallclock guess {a:+.3f} s',
                          file=sys.stderr)
                else:
                    raise SystemExit(
                        f'camsync: could not sync by audio (confidence {res["confidence"]:.2f}): pass --cam-offset S'
                    )
            else:
                a = res['offset']
                b = res['rate']
                conf = res['confidence']
                drift_ms = res['drift_ms']
                method = res['method']

    cw, ch = _probe_video_size(dst)
    s = min(1920.0 / cw, 1080.0 / ch, 1.0)
    ow = max(2, 2 * int(round(cw * s / 2.0)))
    oh = max(2, 2 * int(round(ch * s / 2.0)))

    rel_face = 'assets/media/cam_face.mp4'
    cam_face = os.path.join(vd, rel_face)
    _render_cam_face(dst, cam_face, n_frames, ow, oh, a, b)

    if args.voice == 'cam':
        _render_cam_voice(dst, vo_wav, vo_screen, n_frames, a, b)
        print('camsync: voice track replaced from camera -> assets/media/vo.wav (kept screen voice at assets/media/vo_screen.wav); run `ev2 transcribe`')

    cam_meta = {
        'mode': 'separate',
        'source': args.source,
        'src': rel_src,
        'file': rel_face,
        'width': ow,
        'height': oh,
        'offset': round(a, 4),
        'rate': round(b, 7),
        'confidence': round(conf, 4),
        'method': method,
        'voice': args.voice,
        'drift_ms': round(drift_ms, 1),
    }
    cam_json_path = os.path.join(work_dir, 'camera.json')
    tmp_json = cam_json_path + '.tmp'
    with open(tmp_json, 'w', encoding='utf-8') as f:
        json.dump(cam_meta, f, indent=2)
        f.write('\n')
    os.replace(tmp_json, cam_json_path)

    print(
        f'camsync: camera {a:+.3f} s (rate {b:.7f}, drift {drift_ms:.0f} ms, '
        f'confidence {conf:.2f}, {method}) -> {rel_face} {ow}x{oh}'
    )
    return 0


def cmd_find(args):
    base = os.path.splitext(os.path.basename(args.recording))[0]
    if not base:
        return 1
    log_path = os.path.join(os.path.expanduser('~/.local/share/editor-v2/inputs'), base + '.json')
    if not os.path.isfile(log_path):
        return 1
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            log = json.load(f)
    except (OSError, ValueError):
        return 1
    if not isinstance(log, dict):
        return 1
    cam = log.get('cam')
    if not isinstance(cam, dict) or not cam.get('ok'):
        return 1
    cam_file = cam.get('file')
    started_wall = cam.get('started_wall')
    if not isinstance(cam_file, str) or not cam_file or not os.path.isfile(cam_file):
        return 1
    if not isinstance(started_wall, (int, float)) or isinstance(started_wall, bool):
        return 1

    offset_wall = None
    if args.vd:
        inp_path = os.path.join(os.path.abspath(args.vd), 'work', 'inputs.json')
        if os.path.isfile(inp_path):
            try:
                with open(inp_path, 'r', encoding='utf-8') as f:
                    inp = json.load(f)
                v = inp.get('offset_wall') if isinstance(inp, dict) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    offset_wall = float(v)
            except (OSError, ValueError):
                pass

    if offset_wall is None:
        for k in ('video_seen_wall', 'started_wall'):
            v = log.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                offset_wall = float(v)
                break
    if offset_wall is None:
        return 1

    guess = offset_wall - float(started_wall)
    print(cam_file)
    print(f'{guess:.4f}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='camsync.py', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd')

    p_m = sub.add_parser('measure')
    p_m.add_argument('screen')
    p_m.add_argument('cam')
    p_m.add_argument('--guess', type=float, default=None)
    p_m.add_argument('--window', type=float, default=None)

    p_i = sub.add_parser('import')
    p_i.add_argument('video_dir')
    p_i.add_argument('--cam', required=True)
    p_i.add_argument('--offset', type=float, default=None)
    p_i.add_argument('--voice', choices=('screen', 'cam'), default='screen')
    p_i.add_argument('--guess', type=float, default=None)
    p_i.add_argument('--source', choices=('import', 'ev2-rec'), default='import')

    p_f = sub.add_parser('find')
    p_f.add_argument('recording')
    p_f.add_argument('--vd', default=None)

    args = ap.parse_args(argv)
    if args.cmd == 'measure':
        return cmd_measure(args)
    if args.cmd == 'import':
        return cmd_import(args)
    if args.cmd == 'find':
        return cmd_find(args)
    ap.print_help(sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
