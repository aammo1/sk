#!/usr/bin/env python3
"""bed-mix.py — mix voice with a music bed for Editor V2.

    bed-mix.py --voice work/vo.wav --dur 480.0 --hook-end 45.0 --out work/premix.wav

Flags:
  --voice          Voice track (48 kHz mono or stereo WAV).
  --song           Path to music bed, or "auto" (default: sfx/ev1kit/bed_tutorial.wav, made by synth-music.py;
                   the older dark pulse is sfx/ev1kit/bed_pulse.wav, use it with --under 5.5).
  --song-at        Song time aligned with video time 0 (default 0.0).
  --dur            Total duration in seconds.
  --under          Bed sits this many LU under the voice (default 13 LU: music you feel, not hear).
  --ramp           Gain change: s,e,dB[,fade] (e.g. 12.0,14.0,-70,0.015). Repeatable.
  --hook-end       Optional hook duration (seconds). Fades out bed smoothly over 1.2s
                   after hook_end so technical screencast is clean.
  --chapter-swell  Optional swell: s,e[,fade] to bring bed back in during chapter cards.
  --fade-in        Bed fade-in duration at video start (default 0.02s).
  --ring-out       Bed ring-out fade at video end (default 0.9s).
  --voice-end      Measure voice loudness up to this second only (skips silent tail).
  --out            Output premix path (default work/premix.wav).
"""
import argparse, os, re, subprocess, sys, tempfile

# Auto-locate environment Python if launched from bare interpreter lacking numpy/soundfile
try:
    import numpy as np
    import soundfile as sf
except ImportError:
    ev2_py = os.environ.get('EV2_PY', os.path.expanduser('~/.cache/editor-v2/venv/bin/python'))
    if os.path.isfile(ev2_py) and os.path.realpath(ev2_py) != os.path.realpath(sys.executable):
        os.execv(ev2_py, [ev2_py] + sys.argv)
    usr_py = '/usr/bin/python3'
    if os.path.isfile(usr_py) and os.path.realpath(usr_py) != os.path.realpath(sys.executable):
        os.execv(usr_py, [usr_py] + sys.argv)
    raise

SR = 48000
SKILL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DEFAULT_BED = os.path.join(SKILL_DIR, 'sfx', 'ev1kit', 'bed_tutorial.wav')


def lufs(x):
    fd, p = tempfile.mkstemp(suffix='.wav')
    os.close(fd)
    try:
        sf.write(p, x, SR)
        o = subprocess.run(['ffmpeg', '-nostdin', '-i', p, '-af', 'loudnorm=print_format=summary', '-f', 'null', '-'],
                           capture_output=True, text=True).stderr
    finally:
        os.remove(p)
    m = re.search(r'Input Integrated:\s+(-?[\d.]+)', o)
    return float(m.group(1)) if m else -24.0


def loop_crossfade(chunk, target_n, xfade_sec=0.5):
    """Seamlessly loop chunk to target_n samples using xfade_sec equal-power/linear crossfades."""
    if len(chunk) >= target_n:
        return chunk[:target_n]
    xfade_n = min(int(round(xfade_sec * SR)), len(chunk) // 2)
    if xfade_n <= 0:
        reps = int(np.ceil(target_n / len(chunk))) + 1
        return np.tile(chunk, (reps, 1))[:target_n]

    fade_out = np.linspace(1, 0, xfade_n, dtype=np.float32)[:, None]
    fade_in = np.linspace(0, 1, xfade_n, dtype=np.float32)[:, None]

    buf = np.zeros((target_n + len(chunk) + xfade_n, chunk.shape[1]), dtype=np.float32)
    buf[:len(chunk)] = chunk
    curr_end = len(chunk)

    while curr_end < target_n:
        idx = curr_end - xfade_n
        buf[idx:idx + xfade_n] = buf[idx:idx + xfade_n] * fade_out + chunk[:xfade_n] * fade_in
        buf[idx + xfade_n:idx + len(chunk)] = chunk[xfade_n:]
        curr_end = idx + len(chunk)

    return buf[:target_n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--voice', required=True)
    ap.add_argument('--song', default='auto')
    ap.add_argument('--song-at', type=float, default=0.0)
    ap.add_argument('--dur', type=float, required=True)
    ap.add_argument('--under', type=float, default=13.0)
    ap.add_argument('--ramp', action='append', default=[])
    ap.add_argument('--fade-in', type=float, default=0.02)
    ap.add_argument('--ring-out', type=float, default=0.9)
    ap.add_argument('--voice-end', type=float, default=None)
    ap.add_argument('--hook-end', type=float, default=None,
                    help='Seconds when the cold open hook ends. Fades bed out smoothly by hook_end + 1.2s.')
    ap.add_argument('--chapter-swell', action='append', default=[],
                    help='start,end[,fade] to swell the bed back in during chapter cards.')
    ap.add_argument('--out', default='work/premix.wav')
    a = ap.parse_args()

    # Resolve song path
    song_path = a.song
    if not song_path or song_path == 'auto':
        if not os.path.isfile(DEFAULT_BED):
            synth_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'synth-music.py')
            if os.path.isfile(synth_script):
                print(f'bed-mix: {DEFAULT_BED} not found; generating via synth-music.py...')
                subprocess.run([sys.executable, synth_script], check=True)
        if not os.path.isfile(DEFAULT_BED):
            raise SystemExit(f'bed-mix: auto bed not found at {DEFAULT_BED}; run synth-music.py first')
        song_path = DEFAULT_BED

    if not os.path.isfile(song_path):
        raise SystemExit(f'bed-mix: song file not found: {song_path}')

    n = int(round(a.dur * SR))

    # Decode song segment
    cmd = ['ffmpeg', '-nostdin', '-v', 'error']
    if a.song_at > 0:
        cmd += ['-ss', f'{a.song_at:.4f}']
    cmd += ['-i', song_path, '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    bed_raw = np.frombuffer(raw, np.float32).reshape(-1, 2).copy()

    if a.song_at < 0:
        lead_silence = int(round(-a.song_at * SR))
        bed_raw = np.pad(bed_raw, ((lead_silence, 0), (0, 0)))

    if len(bed_raw) == 0:
        bed = np.zeros((n, 2), np.float32)
    elif len(bed_raw) < n:
        print(f'bed-mix: note: looping song ({len(bed_raw)/SR:.2f}s) to match --dur {a.dur:.2f}s with 0.5s crossfade')
        bed = loop_crossfade(bed_raw, n, xfade_sec=0.5)
    else:
        bed = bed_raw[:n]

    # Load voice track
    vo, sr = sf.read(a.voice, dtype='float32', always_2d=True)
    if sr != SR:
        raise SystemExit(f'bed-mix: {a.voice} is {sr} Hz; expected 48000 Hz')
    if vo.shape[1] == 1:
        vo = np.repeat(vo, 2, axis=1)
    vo = np.pad(vo[:, :2], ((0, max(0, n - len(vo))), (0, 0)))[:n]

    t = np.arange(n) / SR
    L_vo = lufs(vo[:int((a.voice_end or a.dur) * SR)])
    L_bed = lufs(bed)
    g = 10 ** ((L_vo - a.under - L_bed) / 20)

    env = np.ones(n, dtype=np.float32)

    # Manual user ramps: s,e,db[,fade]
    for r in a.ramp:
        v = [float(x) for x in r.split(',')]
        s, e, db = v[:3]
        fade = v[3] if len(v) > 3 else 0.015
        m = np.clip(np.minimum((t - s) / fade + 1, (e - t) / fade + 1), 0, 1)
        env *= 10 ** (db * m / 20)

    # Automatic hook-end ducking for tutorial videos
    if a.hook_end is not None:
        fade_dur = 1.2
        fade_mask = np.clip((t - a.hook_end) / fade_dur, 0.0, 1.0)
        smooth_mask = 0.5 - 0.5 * np.cos(np.pi * fade_mask)
        hook_env = 10 ** (-70.0 * smooth_mask / 20.0)

        # Optional chapter swells: s,e[,fade]
        for swell in a.chapter_swell:
            sp = [float(x) for x in swell.split(',')]
            sw_s, sw_e = sp[0], sp[1]
            sw_fade = sp[2] if len(sp) > 2 else 0.8
            sw_m = np.clip(np.minimum((t - sw_s) / sw_fade, (sw_e - t) / sw_fade), 0.0, 1.0)
            sw_m = 0.5 - 0.5 * np.cos(np.pi * sw_m)
            hook_env *= 10 ** (70.0 * sw_m / 20.0)

        env *= hook_env

    # Overall boundary fade in/out
    env *= np.clip(t / max(a.fade_in, 1e-3), 0, 1)
    env *= np.clip((a.dur - t) / max(a.ring_out, 1e-3), 0, 1)

    bed_out = bed * g * env[:, None]
    mix = vo + bed_out

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sf.write(a.out, mix, SR, subtype='FLOAT')
    sf.write(os.path.splitext(a.out)[0] + '_bed.wav', bed_out, SR, subtype='FLOAT')
    print(f'bed-mix: voice {L_vo:.1f} LUFS, bed {L_bed:.1f} -> {L_vo - a.under:.1f} (gain {g:.2f}), '
          f'{len(a.ramp)} ramps, mix {lufs(mix):.1f} LUFS -> {a.out}')


if __name__ == '__main__':
    main()
