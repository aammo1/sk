#!/usr/bin/env python3
"""asr-check.py — measure transcript accuracy (word error rate) against your own reference.

Every cut, retake flag, onset snap and caption depends on the transcript, so measure it.
Type what you really said for a stretch of the recording (Darija in Arabic script, tech
terms in Latin, as you want them captioned) into a text file, then:

    asr-check.py <video-dir> --ref ref.txt [--from 60 --to 180] [--words work/tx/words.json]

Prints WER (substitutions + deletions + insertions / reference words), the worst
confusions, and writes work/tx/asr-check.md. Run it once per model to choose one, e.g.
    ev2 transcribe <dir> --model small   ; ev2 asr-check <dir> --ref ref.txt --from 60 --to 180
    ev2 transcribe <dir> --model large-v3-turbo ; (same check)
Recurring confusions belong in ~/.config/editor-v2/darija-terms.json.
"""
import argparse, collections, json, os, re, sys


def norm(t):
    t = t.lower().strip()
    t = re.sub(r'[\u064B-\u065F\u0670ـ]', '', t)
    t = re.sub(r'[إأآ]', 'ا', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'ى', 'ي', t)
    t = re.sub(r'[^\w\u0600-\u06FF.+#-]', '', t)
    return t.strip('.-')


def tokens(text):
    return [n for n in (norm(w) for w in text.split()) if n]


def align(ref, hyp):
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, ops = n, m, []
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(('=' if ref[i - 1] == hyp[j - 1] else 'S', ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append(('D', ref[i - 1], ''))
            i -= 1
        else:
            ops.append(('I', '', hyp[j - 1]))
            j -= 1
    return ops[::-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--ref', required=True, help='Text file with what was really said in the window')
    ap.add_argument('--from', dest='t0', type=float, default=0.0)
    ap.add_argument('--to', dest='t1', type=float, default=None)
    ap.add_argument('--words', default='work/tx/words.json')
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)
    wp = a.words if os.path.isabs(a.words) else os.path.join(vd, a.words)
    words = json.load(open(wp, encoding='utf-8'))
    hyp_words = [w['w'] for w in words if w['s'] >= a.t0 and (a.t1 is None or w['s'] < a.t1)]
    ref, hyp = tokens(open(a.ref, encoding='utf-8').read()), tokens(' '.join(hyp_words))
    if not ref:
        sys.exit('asr-check: reference is empty')
    ops = align(ref, hyp)
    c = collections.Counter(o[0] for o in ops)
    wer = (c['S'] + c['D'] + c['I']) / len(ref)
    conf = collections.Counter((r, h) for o, r, h in ops if o == 'S').most_common(15)
    eng = os.path.join(vd, 'work', 'tx', 'engine.json')
    engine = json.load(open(eng)).get('engine', '?') if os.path.isfile(eng) else '?'

    lines = [f'# ASR check ({engine})', '',
             f'Window {a.t0:.0f}s – {a.t1 if a.t1 is not None else "end"}s · reference {len(ref)} words · transcript {len(hyp)} words', '',
             f'**WER {wer * 100:.1f}%**  (substitutions {c["S"]}, deletions {c["D"]}, insertions {c["I"]})', '',
             '| said | heard | times |', '|---|---|---|']
    lines += [f'| {r} | {h} | {k} |' for (r, h), k in conf]
    out = os.path.join(vd, 'work', 'tx', 'asr-check.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print(f'\n-> {out}')
    if wer > 0.30:
        print('asr-check: WER above 30%: captions and retake detection will need a manual pass; '
              'try a larger --model and add recurring fixes to ~/.config/editor-v2/darija-terms.json')


if __name__ == '__main__':
    main()
