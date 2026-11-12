#!/usr/bin/env python3
"""clean-retakes.py — silence trimming + spoken-retake detection; writes work/timeline.json.

Only the BODY is cut. The hook is source [0, hook_split): its voice plays uncut under the
HyperFrames render, so captions keyed to word onsets stay in sync. The body is source
[hook_split, end) minus trimmed silences (and minus retakes you enable).

Algorithms:
  1. Hook split: --hook-split (default 45 s) snapped to the middle of the nearest pause
     within +-2 s, so the hook ends between sentences. Then quantized to the 30 fps frame.
  2. Silence trimming (body only), gentle and screen-aware: a pause longer than --max-silence
     (0.6 s) is shortened to --keep (0.30 s) of air, NOT removed. If the screen is busy during
     the pause (page loading, scrolling, a menu opening: see body_render.pause_busy), it keeps
     --busy-keep (1.2 s) so viewers see what happened. A kept piece shorter than --min-keep
     (0.5 s) between two cuts is not cut out of its pause (fewer, calmer jump cuts).
  3. Retake candidates (body only): adjacent phrases (split at >= 0.25 s pauses, <= 6 s
     apart) sharing a 2+ word normalized prefix, or one being an aborted prefix of the next.
     Candidates are only REPORTED by default (enabled: false) because a shared prefix is
     often a deliberate repetition in Darija. Pass --retakes to enable them all, or flip
     "enabled" per item in work/cuts.json and re-run.
  4. Keep segments are frame-quantized and written to work/timeline.json (chapters and other
     hand-edited fields there are preserved).

Outputs:
  work/timeline.json   the shared timeline (hook_split, segments, chapters)
  work/cuts.json       detection detail: silences, retake candidates + enabled flags
  work/cuts-report.md  human-readable report for the PLAN gate

Usage:
  clean-retakes.py <video-dir> [--hook-split 45] [--max-silence 0.6] [--keep 0.3] [--pad 0.08] [--retakes]
"""
import argparse, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev2_timeline as TL  # noqa: E402


def normalize_darija(w):
    """Normalize a word for retake prefix comparison."""
    if not w:
        return ""
    w = w.lower().strip()
    w = re.sub(r'^[^\w\u0600-\u06FF]+|[^\w\u0600-\u06FF]+$', '', w)
    w = re.sub(r'[\u064B-\u065F\u0670ـ]', '', w)
    w = re.sub(r'[إأآ]', 'ا', w)
    w = re.sub(r'ة', 'ه', w)
    w = re.sub(r'ى', 'ي', w)
    return w.strip()


def retake_key(r):
    norm = lambda t: ' '.join(n for n in (normalize_darija(w) for w in (t or '').split()) if n)
    return norm(r.get('dropped_text')) + ' | ' + norm(r.get('kept_text'))


def get_duration(p):
    try:
        res = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
                             check=True, capture_output=True, text=True)
        return float(res.stdout.strip())
    except Exception:
        return None


def fmt_time(seconds):
    m, s = int(seconds // 60), seconds % 60
    return f"{m}m {s:02.0f}s ({seconds:.2f}s)" if m > 0 else f"{seconds:.2f}s"


def fmt_ts(seconds):
    return f"{int(seconds // 60):02d}:{seconds % 60:06.3f}"


def detect_silences(media_path, db=-38.0, min_dur=0.12):
    res = subprocess.run(['ffmpeg', '-nostdin', '-v', 'info', '-i', media_path,
                          '-af', f'silencedetect=noise={db}dB:d={min_dur}', '-f', 'null', '-'],
                         capture_output=True, text=True)
    st = [float(x) for x in re.findall(r'silence_start:\s*(-?[\d.]+)', res.stderr)]
    en = [float(x) for x in re.findall(r'silence_end:\s*(-?[\d.]+)', res.stderr)]
    return [(max(0.0, s), max(0.0, e)) for s, e in zip(st, en)]


def load_silences(vd, media_path, words):
    sil_file = os.path.join(vd, 'work', 'silences.txt')
    if os.path.isfile(sil_file) and media_path and os.path.getmtime(sil_file) >= os.path.getmtime(media_path):
        sil = []
        for line in open(sil_file, encoding='utf-8'):
            p = line.split()
            if len(p) >= 2:
                try:
                    sil.append((float(p[0]), float(p[1])))
                except ValueError:
                    pass
        return sil
    if media_path:
        print(f"clean-retakes: detecting silences in {os.path.relpath(media_path, vd)}...")
        sil = detect_silences(media_path)
    else:
        print("clean-retakes: WARNING no audio found; deriving pauses from word gaps")
        sil = [(words[i]['e'], words[i + 1]['s']) for i in range(len(words) - 1)
               if words[i + 1]['s'] - words[i]['e'] >= 0.12]
    with open(sil_file, 'w', encoding='utf-8') as f:
        for s, e in sil:
            f.write(f'{s:.3f} {e:.3f}\n')
    return sil


def phrases_of(words):
    out, cur = [], []
    for w in words:
        if cur and w['s'] - cur[-1]['e'] >= 0.25:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    res = []
    for ws in out:
        res.append({'start': ws[0]['s'], 'end': ws[-1]['e'], 'text': ' '.join(x['w'] for x in ws),
                    'norm': [n for n in (normalize_darija(x['w']) for x in ws) if n]})
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--hook-split', type=float, default=None,
                    help='Hook length in source seconds (default: keep the current one, else 45). 0 = no hook.')
    ap.add_argument('--no-snap', action='store_true', help='Do not snap the hook split to the nearest pause')
    ap.add_argument('--max-silence', type=float, default=0.6, help='Pauses longer than this are shortened (s)')
    ap.add_argument('--keep', type=float, default=0.30, help='Air kept in a shortened pause (s)')
    ap.add_argument('--busy-keep', type=float, default=1.2, help='Air kept when the screen is busy in the pause (s)')
    ap.add_argument('--min-keep', type=float, default=0.5, help='Never leave a kept piece shorter than this (s)')
    ap.add_argument('--pad', type=float, default=0.08, help='Air kept before a retake restart (s)')
    ap.add_argument('--no-screen', action='store_true', help='Ignore screen activity when cutting pauses')
    ap.add_argument('--retakes', action='store_true', help='Enable every detected retake cut (default: report only)')
    ap.add_argument('--apply', action='store_true', help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.apply:
        sys.exit("clean-retakes: --apply was removed. Cuts are applied by `ev2 finish` from work/timeline.json.")

    vd = os.path.abspath(a.video_dir)
    work = os.path.join(vd, 'work')
    os.makedirs(work, exist_ok=True)

    words_file = os.path.join(work, 'tx', 'words.json')
    if not os.path.isfile(words_file):
        sys.exit(f"clean-retakes: no transcript at {words_file}: run `ev2 transcribe {vd}` first")
    words = sorted(json.load(open(words_file, encoding='utf-8')), key=lambda w: w['s'])
    if not words:
        sys.exit("clean-retakes: words.json is empty")

    media = None
    for rel in ['assets/media/vo.wav', 'assets/media/src.mp4']:
        if os.path.isfile(os.path.join(vd, rel)):
            media = os.path.join(vd, rel)
            break
    source = None
    for ext in ('mp4', 'mov', 'mkv', 'webm'):
        if os.path.isfile(os.path.join(vd, 'assets', 'media', f'src.{ext}')):
            source = f'assets/media/src.{ext}'
            break

    duration = get_duration(media) if media else None
    cam = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    if duration and os.path.isfile(cam):
        cd = get_duration(cam)
        if cd:
            duration = min(duration, cd)   # never cut past the last picture frame
    if not duration:
        duration = words[-1]['e'] + 0.5
    duration = int(duration * TL.FPS + 1e-6) / TL.FPS  # floor to the frame grid

    silences = load_silences(vd, media, words)

    old_tl = TL.load(vd, required=False) if os.path.isfile(TL.tl_path(vd)) else None

    # 1. Hook split
    if a.hook_split is not None:
        hs = a.hook_split
    elif old_tl:
        hs = float(old_tl['hook_split'])
        a.no_snap = True  # keep the previously chosen split exactly
    else:
        hs = 45.0
    hs = max(0.0, min(hs, duration))
    snapped_from = None
    if hs > 0 and not a.no_snap:
        best = None
        for s, e in silences:
            mid = (s + e) / 2
            if abs(mid - hs) <= 2.0 and (best is None or abs(mid - hs) < abs(best - hs)):
                best = mid
        if best is not None:
            snapped_from, hs = hs, best
    hs = TL.q(hs)

    # 2. Retake candidates (body only)
    phr = [p for p in phrases_of(words) if p['start'] >= hs]
    cands = []
    for i in range(len(phr) - 1):
        p, n = phr[i], phr[i + 1]
        gap = n['start'] - p['end']
        if 0.0 <= gap <= 6.0 and p['norm'] and n['norm']:
            L = min(len(p['norm']), len(n['norm']))
            k = 0
            while k < L and p['norm'][k] == n['norm'][k]:
                k += 1
            if k >= 2 or (k == len(p['norm']) and len(n['norm']) > len(p['norm'])):
                cands.append({'start': round(p['start'], 3), 'end': round(p['end'], 3),
                              'next_start': round(n['start'], 3),
                              'dropped_text': p['text'], 'kept_text': n['text'],
                              'enabled': bool(a.retakes)})

    cuts_path = os.path.join(work, 'cuts.json')
    if os.path.isfile(cuts_path) and not a.retakes:
        try:
            old = json.load(open(cuts_path, encoding='utf-8'))
            # match by what was said first (survives re-transcription and timing changes), then by time
            by_text, by_time = {}, {}
            for r in old.get('retakes_detected', []):
                on = bool(r.get('enabled', False))
                by_text.setdefault(retake_key(r), on)
                by_time[round(r['start'], 2)] = on
            for r in cands:
                k = retake_key(r)
                r['enabled'] = by_text[k] if k in by_text else by_time.get(round(r['start'], 2), r['enabled'])
        except Exception as e:
            print(f"clean-retakes: WARNING could not read previous {cuts_path}: {e}", file=sys.stderr)

    # 3. Cut intervals (body only)
    retake_cuts = [(max(hs, r['start'] - a.pad), max(hs, r['next_start'] - a.pad)) for r in cands if r['enabled']]
    act = None
    if not a.no_screen and os.path.isfile(os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')):
        try:
            import body_render
            act = body_render.analyze(vd)
        except Exception as ex:
            print(f"clean-retakes: WARNING screen analysis failed ({ex}); cutting pauses on audio only", file=sys.stderr)
    silence_cuts, sil_report, n_busy = [], [], 0
    for s, e in silences:
        if e - s <= a.max_silence:
            continue
        keep = a.keep
        if act is not None and body_render.pause_busy(act, s, e):
            keep, n_busy = a.busy_keep, n_busy + 1
        if e - s <= keep + 0.1:
            continue
        ts, te = max(s + keep / 2, hs), e - keep / 2
        if te - ts < 1.0 / TL.FPS:
            continue
        if any(rs <= ts and te <= re_ for rs, re_ in retake_cuts):
            continue
        silence_cuts.append((ts, te))
        sil_report.append({'start': round(s, 3), 'end': round(e, 3), 'saved': round(te - ts, 3)})

    def is_silent(t0, t1, tol=0.02):
        return any(s - tol <= t0 and t1 <= e + tol for s, e in silences)

    # [start, end, is_retake]. A sliver (< --min-keep) between two cuts is avoided, but an
    # enabled retake is never dropped for it: the sliver is merged away when it is pure pause,
    # otherwise the neighbouring PAUSE cut gives way.
    cuts = sorted([(cs, ce, True) for cs, ce in retake_cuts] + [(cs, ce, False) for cs, ce in silence_cuts])
    merged = []
    for cs, ce, rt in cuts:
        cs, ce = max(hs, cs), min(duration, ce)
        if ce <= cs:
            continue
        if merged and cs <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], ce)
            merged[-1][2] = merged[-1][2] or rt
        elif merged and cs - merged[-1][1] < a.min_keep:
            prev = merged[-1]
            if not rt and not prev[2]:
                continue   # two pause cuts: keep this pause instead of leaving a sliver
            if is_silent(prev[1], cs):
                prev[1], prev[2] = max(prev[1], ce), True
            elif not prev[2]:
                prev[1] = cs - a.min_keep          # shrink the pause cut before the retake
                if prev[1] - prev[0] < 1.0 / TL.FPS:
                    merged.pop()
                merged.append([cs, ce, True])
            elif not rt:
                continue   # a pause cut right after a retake: keep the pause
            else:
                merged.append([cs, ce, True])      # two retakes: both are cut
        else:
            merged.append([cs, ce, rt])
    for r in cands:
        if r['enabled']:
            rs, re_ = max(hs, r['start'] - a.pad), max(hs, r['next_start'] - a.pad)
            if not any(m[0] - 1e-6 <= rs and re_ <= m[1] + 1e-6 for m in merged):
                sys.exit(f"clean-retakes: internal error: enabled retake at {r['start']:.2f}s is not cut")

    # 4. Keep segments, frame-quantized
    segs, cur = [], hs
    for cs, ce, _ in merged:
        if cs > cur:
            segs.append((cur, cs))
        cur = max(cur, ce)
    if cur < duration:
        segs.append((cur, duration))
    segments = []
    for s, e in segs:
        fs, fe = TL.frames(s), TL.frames(e)
        if segments and fs <= TL.frames(segments[-1]['src_end']):
            fs = TL.frames(segments[-1]['src_end'])
        if fe - fs >= 2:  # drop slivers shorter than 2 frames
            segments.append({'src_start': fs / TL.FPS, 'src_end': fe / TL.FPS})

    tl = dict(old_tl) if old_tl else {}
    tl.update({'schema': TL.SCHEMA, 'fps': TL.FPS, 'source': source or tl.get('source'),
               'source_duration': round(duration, 3), 'hook_split': hs, 'segments': segments})
    tl.setdefault('chapters', [])
    tl.setdefault('hook_title', 'Intro')
    TL.save(vd, tl)

    body = TL.body_duration(tl)
    final = hs + body
    saved = (duration - hs) - body
    json.dump({'hook_split_time': hs, 'hook_split_snapped_from': snapped_from,
               'original_duration': round(duration, 3), 'body_duration': round(body, 3),
               'final_duration': round(final, 3), 'silences_trimmed': sil_report,
               'retakes_detected': cands, 'retakes_default': 'enabled' if a.retakes else 'report-only'},
              open(cuts_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)

    n_on = sum(1 for r in cands if r['enabled'])
    lines = ["# Cuts Report", "",
             "| Metric | Value |", "| --- | --- |",
             f"| Source length | {fmt_time(duration)} |",
             f"| Hook (uncut) | 0 → {fmt_time(hs)}" + (f" (snapped from {snapped_from:.2f}s to a pause)" if snapped_from else "") + " |",
             f"| Body before cleaning | {fmt_time(duration - hs)} |",
             f"| Body after cleaning | {fmt_time(body)} |",
             f"| Removed from body | {fmt_time(saved)} |",
             f"| **Final video length** | **{fmt_time(final)}** |",
             f"| Pauses shortened | {len(sil_report)} (pauses > {a.max_silence}s kept at {a.keep}s; {n_busy} busy-screen pauses kept at {a.busy_keep}s) |",
             f"| Retake candidates | {len(cands)} found, {n_on} enabled |", "",
             "## Retake candidates", ""]
    if cands:
        lines += ["| # | Start | Dropped (said first) | Kept (said again) | Cut? |", "| - | - | - | - | - |"]
        for i, r in enumerate(cands, 1):
            lines.append(f"| {i} | {fmt_ts(r['start'])} | {r['dropped_text'].replace('|', '/')} | "
                         f"{r['kept_text'].replace('|', '/')} | {'**yes**' if r['enabled'] else 'no'} |")
    else:
        lines.append("_No retake candidates in the body._")
    lines += ["", "## How to change cuts",
              "- Enable/disable one retake: set `\"enabled\"` in `work/cuts.json`, then `ev2 clean <video-dir>`.",
              "- Enable all retakes: `ev2 clean <video-dir> --retakes`.",
              "- Move the hook split: `ev2 clean <video-dir> --hook-split 15` (then rebuild the hook).",
              "- Add YouTube chapters: edit `chapters` in `work/timeline.json` (`{\"src_t\": <source s>, \"title\": ...}`).",
              ""]
    open(os.path.join(work, 'cuts-report.md'), 'w', encoding='utf-8').write('\n'.join(lines))

    print(f"clean-retakes: hook 0-{hs:.2f}s | body {duration - hs:.1f}s -> {body:.1f}s "
          f"({len(sil_report)} pauses shortened, {n_busy} busy-screen, {n_on}/{len(cands)} retakes cut) | final ≈ {fmt_time(final)}")
    print(f"  -> {TL.tl_path(vd)}\n  -> {cuts_path}\n  -> {os.path.join(work, 'cuts-report.md')}")


if __name__ == '__main__':
    main()
