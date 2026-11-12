#!/usr/bin/env python3
"""snap-onsets.py — put the first word after each real pause on the frame the voice starts.

The speech engine can report the first word after a pause 60-220 ms EARLY, so a caption
or a cut keyed to it lands before the sound. This finds the real pauses with ffmpeg
silencedetect (default noise -38 dB, at least 0.12 s) and moves only the FIRST word after
each pause to the pause's end. Shorter dips are plosive closures inside words: snapping
to those moves words onto the wrong syllable, so they are left alone.

Usage:
    $EV1_PY snap-onsets.py <video-dir> [--db -38] [--min 0.12] [--src vo.wav]

Reads:  assets/media/vo.wav (or --src) and work/tx/words.json
Writes: work/tx/words.json (snapped IN PLACE: idempotent, keeps your manual text corrections)
        work/silences.txt ("start end" per pause)
The pristine transcription stays in work/tx/words_raw.json (written by transcribe.py).
"""
import argparse, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev2_timeline as TL  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="snap-onsets.py — snap first word after each pause to the real voice onset.")
    ap.add_argument('video_dir', help="Video project directory")
    ap.add_argument('--db', type=float, default=-38.0, help="Noise threshold in dB (default: -38)")
    ap.add_argument('--min', type=float, default=0.12, help="Minimum silence duration in seconds (default: 0.12)")
    ap.add_argument('--src', default=None, help="Audio file path (default: assets/media/vo.wav)")
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)

    # Determine audio source path
    if a.src:
        if os.path.isabs(a.src) or os.path.isfile(a.src):
            wav = a.src
        else:
            wav = os.path.join(vd, a.src)
    else:
        wav = os.path.join(vd, 'assets', 'media', 'vo.wav')

    if not os.path.isfile(wav):
        alt_paths = [
            os.path.join(vd, 'work', 'vo.wav'),
            os.path.join(vd, 'vo.wav'),
            os.path.join(vd, 'assets', 'media', 'src.mp4'),
        ]
        found = False
        for alt in alt_paths:
            if os.path.isfile(alt):
                wav = alt
                found = True
                break
        if not found:
            sys.exit(f'snap-onsets: no such audio file: {wav}')

    wp = os.path.join(vd, 'work', 'tx', 'words.json')
    if not os.path.isfile(wp):
        sys.exit(f'snap-onsets: no transcript words found at {wp}: run transcribe.py first')

    untouched = TL.words_edited(vd) is False   # only then may this automatic write be re-stamped
    with open(wp, 'r', encoding='utf-8') as f:
        words = sorted(json.load(f), key=lambda item: item['s'])

    if not words:
        print('snap-onsets: words list is empty, nothing to snap.')
        return

    # Run ffmpeg silencedetect
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'info',
        '-i', wav,
        '-af', f'silencedetect=noise={a.db}dB:d={a.min}',
        '-f', 'null', '-'
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    err = res.stderr

    st = [float(x) for x in re.findall(r'silence_start:\s*(-?[\d.]+)', err)]
    en = [float(x) for x in re.findall(r'silence_end:\s*(-?[\d.]+)', err)]

    # Pair starts and ends
    sil = []
    for s, e in zip(st, en):
        sil.append((max(0.0, s), max(0.0, e)))

    os.makedirs(os.path.join(vd, 'work'), exist_ok=True)
    sil_file = os.path.join(vd, 'work', 'silences.txt')
    with open(sil_file, 'w', encoding='utf-8') as f:
        for s, e in sil:
            f.write(f'{s:.3f} {e:.3f}\n')

    used, moved = set(), []
    for s, e in sil:
        # The first word that starts inside this pause (or just before it) is the early one
        for i, w in enumerate(words):
            if w['s'] >= s - 0.05 and i not in used:
                if w['s'] < e and e < w['e'] - 0.04 and (i + 1 == len(words) or e < words[i + 1]['s']):
                    moved.append((w['w'], w['s'], round(e, 3)))
                    w['s'] = round(e, 3)
                used.add(i)
                break

    words.sort(key=lambda item: item['s'])
    for i in range(1, len(words)):
        if words[i]['s'] < words[i - 1]['s']:
            words[i]['s'] = words[i - 1]['s']

    with open(wp, 'w', encoding='utf-8') as f:
        json.dump(words, f, indent=2, ensure_ascii=False)
    if untouched:
        TL.stamp_words(vd)

    print(f'snap-onsets: {len(sil)} pauses, {len(moved)} words moved later -> {wp}')
    for w, s0, s1 in moved:
        print(f'  {w:<20} {s0:7.3f} -> {s1:7.3f}  (+{(s1 - s0) * 1000:.0f} ms)')


if __name__ == '__main__':
    main()
