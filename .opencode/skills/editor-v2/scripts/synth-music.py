#!/usr/bin/env python3
"""synth-music.py — synthesize the default tutorial music bed (no samples, no copyright).

    synth-music.py [--out sfx/ev1kit/bed_tutorial.wav] [--bpm 100] [--seed 7]

A warm, calm "tech tutorial" loop in A minor (Am - F - C - G): soft chord pad, a gentle
plucked arpeggio with a stereo echo, a round bass, and a very light beat from bar 5 on.
57.6 s at 100 BPM, rendered so its end wraps into its start (loops without a click).
Deterministic: same seed, same file. bed-mix.py sets how loud it sits under the voice.
"""
import argparse, os
import numpy as np
import soundfile as sf

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, '..', 'sfx', 'ev1kit', 'bed_tutorial.wav'))

PROG = [('A', [57, 60, 64]), ('F', [53, 57, 60]), ('C', [55, 60, 64]), ('G', [55, 59, 62])]  # midi triads
BASS = {'A': 33, 'F': 29, 'C': 36, 'G': 31}
BARS = 24


def hz(m): return 440.0 * 2 ** ((m - 69) / 12)




def lp_fast(x, fc, passes=2):
    from numpy.fft import rfft, irfft
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    H = 1 / (1 + (f / fc) ** 4)
    for _ in range(passes):
        x = irfft(rfft(x) * H, n)
    return x


def hp_fast(x, fc):
    from numpy.fft import rfft, irfft
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return irfft(rfft(x) * (1 - 1 / (1 + (f / fc) ** 4)), len(x))


def add(buf, i, snd, g=1.0):
    j = min(len(buf), i + len(snd))
    if j > i:
        buf[i:j] += snd[:j - i] * g


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--bpm', type=float, default=100.0)
    ap.add_argument('--seed', type=int, default=7)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    beat = 60.0 / a.bpm
    bar = 4 * beat
    total = int(round(BARS * bar * SR))
    tail = int(4 * SR)
    N = total + tail
    L = np.zeros(N, np.float32); R = np.zeros(N, np.float32)
    pad = np.zeros(N, np.float32); pluck = np.zeros(N, np.float32)
    bass = np.zeros(N, np.float32); drums = np.zeros(N, np.float32)

    for b in range(BARS):
        name, notes = PROG[b % 4]
        t0 = int(round(b * bar * SR))
        dur = int((bar + 1.2) * SR)
        t = np.arange(dur) / SR
        # pad: detuned triangle-ish stack, slow attack, long release
        env = np.minimum(1, t / 0.9) * np.minimum(1, np.maximum(0, (bar + 1.2 - t) / 1.2))
        for m in notes + [notes[0] + 12]:
            for det in (-6, 0, 6):
                f = hz(m) * 2 ** (det / 1200)
                ph = rng.random()
                w = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * (f * t + ph)))
                add(pad, t0, (w * env * 0.05).astype(np.float32))
        # bass: soft sine, beats 1 and 3 (+ pickup)
        for bt, ln, g in ((0, 1.6, 1.0), (2, 1.2, 0.8), (3.5, 0.5, 0.6)):
            n = int(ln * beat * SR); tt = np.arange(n) / SR
            e = np.minimum(1, tt / 0.015) * np.exp(-tt / (ln * beat * 0.55))
            f = hz(BASS[name] + (12 if bt == 3.5 else 0))
            add(bass, t0 + int(bt * beat * SR), (np.sin(2 * np.pi * f * tt) * e * 0.5 * g).astype(np.float32))
        # arpeggio: 8th notes, pattern over chord tones, two octaves up
        order = [0, 1, 2, 3, 2, 1, 2, 1]
        tones = [n + 12 for n in notes] + [notes[0] + 24]
        for k in range(8):
            if b < 2 and k % 2:      # sparse intro
                continue
            m = tones[order[k] % len(tones)]
            n = int(0.55 * SR); tt = np.arange(n) / SR
            f = hz(m)
            e = np.exp(-tt / 0.16) * np.minimum(1, tt / 0.004)
            snd = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * tt) * np.exp(-tt / 0.05)
                   + 0.12 * np.sin(2 * np.pi * 3 * f * tt) * np.exp(-tt / 0.03)) * e
            add(pluck, t0 + int(k * beat / 2 * SR), (snd * (0.16 if k % 2 == 0 else 0.11)).astype(np.float32))
        # light beat from bar 5
        if b >= 4:
            for bt in (0, 2.5):
                n = int(0.35 * SR); tt = np.arange(n) / SR
                f = 48 + 70 * np.exp(-tt / 0.03)
                kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.11)
                add(drums, t0 + int(bt * beat * SR), (kick * 0.32).astype(np.float32))
            for bt in (1, 3):  # soft snare-like tick
                n = int(0.18 * SR); tt = np.arange(n) / SR
                nz = hp_fast(rng.standard_normal(n), 1800) * np.exp(-tt / 0.05)
                add(drums, t0 + int(bt * beat * SR), (nz * 0.05).astype(np.float32))
            for k in range(8):
                n = int(0.05 * SR); tt = np.arange(n) / SR
                nz = hp_fast(rng.standard_normal(n), 7000) * np.exp(-tt / 0.012)
                add(drums, t0 + int((k + 0.5) * beat / 2 * SR), (nz * (0.035 if k % 2 else 0.02)).astype(np.float32))

    pad = lp_fast(pad, 1400)
    pluck = lp_fast(pluck, 5000, 1)
    bass = lp_fast(bass, 400)
    drums = lp_fast(drums, 9000, 1)

    # stereo: pad wide via short delay, pluck with ping-pong echo
    d = int(0.017 * SR)
    L += pad + bass + drums; R += pad + bass + drums
    R += np.roll(pad, d) * 0.5; L -= np.roll(pad, d) * 0.0
    e1, e2 = int(beat * 0.75 * SR), int(beat * 1.5 * SR)
    L += pluck + np.roll(pluck, e2) * 0.28
    R += pluck * 0.6 + np.roll(pluck, e1) * 0.4 + np.roll(pluck, e1 + e2) * 0.18

    # light reverb: decaying noise impulse response, mixed in quietly
    ir_n = int(1.8 * SR)
    ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / SR / 0.45)
    ir = lp_fast(ir, 3500, 1).astype(np.float32); ir /= np.abs(ir).sum() / 8
    from numpy.fft import rfft, irfft
    nfft = 1 << int(np.ceil(np.log2(N + ir_n)))
    Fi = rfft(ir, nfft)
    wetL = irfft(rfft(L + pluck * 0.0, nfft) * Fi, nfft)[:N]
    wetR = irfft(rfft(R, nfft) * Fi, nfft)[:N]
    L = L + 0.18 * wetL; R = R + 0.18 * wetR

    # make it loop: fold the tail back onto the start
    st = np.stack([L, R], 1)
    st[:tail] += st[total:total + tail]
    st = st[:total]
    st *= 10 ** (-3 / 20) / (np.abs(st).max() + 1e-9)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sf.write(a.out, st.astype(np.float32), SR, subtype='PCM_24')
    print(f'synth-music: {len(st) / SR:.1f} s, {a.bpm:.0f} BPM, A minor -> {a.out}')


if __name__ == '__main__':
    main()
