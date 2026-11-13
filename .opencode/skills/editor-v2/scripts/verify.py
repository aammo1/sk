#!/usr/bin/env python3
"""verify.py — check an Editor V2 video against its definition of done.

    verify.py <video-dir>          -> out/verify.md + out/verify.json; exit 1 on any FAIL

FAIL (the video is not done):
  - out/final.mp4 missing, not 1920x1080 @ 30 fps, or its length != hook + cleaned body
  - audio and video streams of final.mp4 differ in length (> 0.1 s)
  - voice in final.mp4 is not where timeline.json says (audio cross-correlation against
    assets/media/vo.wav at several body points; > 1 frame off = FAIL)
  - picture in final.mp4 is not where timeline.json says (motion-signal cross-correlation
    against the expected cam_raw.mp4 frames around screen events; > 1 frame off = FAIL)
  - an insert in timeline.json is invalid, has no render, a render of the wrong frame count, a render
    older than its insert-<name>.html, or was not built FINAL (`ev2 inserts --final`)
  - inserts or their renders changed after the last `ev2 finish` (outputs are stale)
  - key pills ("keys" in timeline.json) are invalid, or changed after the last `ev2 finish` (stale keys)
  - the hook was not built FINAL (placeholders, missing assets, or the last build was not
    `ev2 build --final`, or it was built for another hook_split)
  - work/timeline.json cuts or chapters changed after the last `ev2 finish` (outputs are stale)
  - an editor project that finish was asked for is missing, stale, or has the wrong cuts
  - the Short is missing or not 1080x1920 / <= 60 s (unless finish ran with --no-short)
WARN (publishable, but look):
  - YouTube chapter rules not met (00:00 first, >= 3 chapters, each >= 10 s)
  - loudness outside -16..-12 LUFS (finish targets -14, YouTube's reference)
  - a sync check found nothing clear enough to measure
  - key pills are listed but the last finish did not draw them (--no-keys / --raw-body)
Beauty (beauty.py, skipped with EV2_NO_BEAUTY=1): dead air / frozen / cut faces in the hook, frozen
inserts, over-zoom, internal notes left in the description -> FAIL; pace, monotony, no music,
untrustworthy captions -> WARN. Also writes out/beauty.md and out/beauty-sheet.jpg.
Optional checks (only when the extra is used; never FAIL for the description):
  - key pills: drawn and current -> PASS
  - out/youtube-description.md: <!-- WRITE slots left, > 5000 characters, or its chapters block
    differs from out/youtube-chapters.txt -> WARN; otherwise PASS
"""
import json, os, re, subprocess, sys

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

FPS = TL.FPS
RESULTS = []
VOICE = 'assets/media/vo.wav'


def add(level, what, detail=''):
    RESULTS.append((level, what, detail))


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration:stream=codec_type,duration,width,height,r_frame_rate',
                        '-of', 'json', path], capture_output=True, text=True)
    if r.returncode:
        return None
    d = json.loads(r.stdout)
    info = {'duration': float(d['format'].get('duration') or 0)}
    for s in d.get('streams', []):
        if s['codec_type'] == 'video' and 'v_dur' not in info:
            n, _, dd = s.get('r_frame_rate', '0/1').partition('/')
            info.update(v_dur=float(s.get('duration') or info['duration']), width=s.get('width'),
                        height=s.get('height'), fps=float(n) / float(dd or 1))
        elif s['codec_type'] == 'audio' and 'a_dur' not in info:
            info['a_dur'] = float(s.get('duration') or info['duration'])
    return info


def audio_at(path, start, dur, sr=8000):
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{max(0, start):.4f}', '-t', f'{dur:.4f}',
                        '-i', path, '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def lag_of(ref, sig, sr, max_lag=0.5):
    """Seconds by which sig lags ref (positive = sig late), and the normalized peak."""
    n = min(len(ref), len(sig))
    if n < int(sr * 0.6):
        return None, 0.0
    ref, sig = ref[:n] - ref[:n].mean(), sig[:n] - sig[:n].mean()
    if np.std(ref) < 1e-4 or np.std(sig) < 1e-4:
        return None, 0.0
    m = int(max_lag * sr)
    c = np.correlate(np.pad(sig, (m, m)), ref, mode='valid')
    k = int(np.argmax(c))
    peak = c[k] / (np.linalg.norm(ref) * np.linalg.norm(sig) + 1e-9)
    return (k - m) / sr, float(peak)


def gray_frames(path, f0, n, w=160, h=90):
    """n frames from frame index f0 (30 fps CFR), small grayscale, float32 (n, h, w).
    Frame-exact: a coarse seek keeps the file's own timestamps (-copyts) and frames are then
    selected by timestamp (a plain input -ss can land one frame off on B-frame files with audio)."""
    t = (f0 - 0.5) / FPS
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-copyts', '-ss', f'{max(0.0, t - 2.0):.4f}', '-i', path,
                        '-an', '-vf', f"select='gte(t,{t:.5f})',scale={w}:{h},format=gray", '-fps_mode', 'passthrough',
                        '-frames:v', str(n), '-f', 'rawvideo', '-'], capture_output=True)
    x = np.frombuffer(r.stdout, np.uint8)
    k = len(x) // (w * h)
    return x[:k * w * h].reshape(k, h, w).astype(np.float32)


def motion(frames):
    return np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)) if len(frames) > 1 else np.zeros(0)


def best_lag(ref, sig, max_lag):
    """Frames by which sig lags ref (positive = picture late), and its correlation."""
    best = (None, -1.0)
    for lag in range(-max_lag, max_lag + 1):
        a = ref[max(0, -lag):len(ref) - max(0, lag)]
        b = sig[max(0, lag):len(sig) - max(0, -lag)]
        n = min(len(a), len(b))
        if n < 10:
            continue
        a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
        den = np.linalg.norm(a) * np.linalg.norm(b)
        if den < 1e-6:
            continue
        cc = float(a @ b / den)
        if cc > best[1]:
            best = (lag, cc)
    return best


def picture_sync(segs, NH, R=24, L=8, n_pick=5, exclude=()):
    """Check that body PICTURE frames in final.mp4 sit where timeline.json puts them: the motion
    signal (mean frame difference) of final.mp4 around screen events must line up with the
    motion signal of the expected source frames (through the cuts) from cam_raw.mp4. Zooms and
    the redrawn webcam change the picture but not WHEN the screen changes."""
    if not segs or not os.path.isfile('assets/media/cam_raw.mp4'):
        return None, 'no body or no cam_raw.mp4'
    src = np.concatenate([np.arange(s['f_start'], s['f_end']) for s in segs])
    nb = len(src)
    if nb < 4 * R:
        return None, 'body too short to cross-check'
    score = None
    if os.path.isfile('work/activity.npz'):
        frac = np.load('work/activity.npz', allow_pickle=False)['frac']
        step = FPS // 5
        cand = np.arange(R + 1, nb - R - 1, step)
        score = frac[np.clip(src[cand] // step, 0, len(frac) - 1)]
    else:
        cand = np.linspace(R + 1, nb - R - 2, 15).astype(int)
    if len(exclude):
        keep = np.array([not any(f0 - R - 9 <= b <= f0 + n + R + 9 for f0, n in exclude) for b in cand], dtype=bool)
        cand = cand[keep]
        if score is not None:
            score = score[keep]
        if not len(cand):
            return None, 'no screen event outside the inserts to cross-check'
    order = np.argsort(-score) if score is not None else np.arange(len(cand))
    picks = []
    for k in order:
        if score is not None and score[k] < 0.002:
            break
        b = int(cand[k])
        if all(abs(b - p) >= 10 * FPS for p in picks):
            picks.append(b)
        if len(picks) >= n_pick:
            break
    checked, bad = 0, []
    for b in sorted(picks):
        exp_src = src[b - R:b + R + 1]
        lo, hi = int(exp_src.min()), int(exp_src.max())
        cam = gray_frames('assets/media/cam_raw.mp4', lo, hi - lo + 1)
        if len(cam) < hi - lo + 1:
            continue
        d_exp = motion(cam[exp_src - lo])
        d_fin = motion(gray_frames('out/final.mp4', NH + b - R, 2 * R + 1))
        if len(d_fin) < 2 * R or np.std(d_exp) < 0.05:
            continue
        lag, cc = best_lag(d_exp, d_fin, L)
        if lag is None or cc < 0.5:
            continue
        checked += 1
        if abs(lag) > 1:
            bad.append(f'{TL.fmt_ts((NH + b) / FPS)}: picture {lag:+d} frames off (corr {cc:.2f})')
    if bad:
        return False, '; '.join(bad)
    if checked:
        return True, f'{checked} screen events within 1 frame of the timeline'
    return None, 'no screen event clear enough to cross-check'


def check_keys(tl, fin):
    """Key pills: only reported when the timeline lists pills or the last finish drew some."""
    try:
        pills = TL.key_ranges(tl)
    except TL.TimelineError as e:
        add('FAIL', 'key pills', str(e))
        return
    sig = fin.get('keys_signature') if fin else None
    if not pills and (sig is None or sig == TL.keys_signature(dict(tl, keys=[]))):
        return
    if not fin:
        return  # 'finish' already FAILs
    if sig is None:
        add('WARN', 'key pills', 'finish.json predates key pills: run ev2 finish')
    elif sig != TL.keys_signature(tl):
        add('FAIL', 'stale keys', 'key pills changed after the last finish: run ev2 finish again')
    elif pills and not fin.get('keys_drawn'):
        add('WARN', 'key pills', f'{len(pills)} pills listed but not drawn (finish ran with --no-keys or --raw-body)')
    else:
        add('PASS', 'key pills', f'{len(pills)} pills drawn')


DESC_TS = re.compile(r'^\d{1,2}:\d{2}(:\d{2})? ')


def check_description(vd):
    """out/youtube-description.md (from `ev2 describe`): WARN only, never FAIL."""
    text = open('out/youtube-description.md', encoding='utf-8').read()
    slots, n, parts, todo = text.count('<!-- WRITE'), len(text), [], []
    name = os.path.basename(vd)
    if slots:
        parts.append(f'{slots} slots to write')
    if n > 5000:
        parts.append(f'{n} chars (> 5000)')
    lines = [l.strip() for l in text.splitlines()]
    block = []
    for k, l in enumerate(lines):
        if l.startswith('00:00 '):
            for x in lines[k:]:
                if not DESC_TS.match(x):
                    break
                block.append(x)
            break
    if os.path.isfile('out/youtube-chapters.txt'):
        want = [l.strip() for l in open('out/youtube-chapters.txt', encoding='utf-8') if l.strip()]
        if block != want:
            parts.append('chapters outdated')
            todo.append(f'run ev2 describe {name} --force')
    else:
        parts.append('no out/youtube-chapters.txt to compare')
        todo.append('run ev2 finish')
    if slots:
        todo.append(f'fill the <!-- WRITE --> slots, then ev2 describe {name} --check')
    elif n > 5000:
        todo.append(f'shorten it, then ev2 describe {name} --check')
    if parts:
        add('WARN', 'description', '; '.join(parts) + ': ' + '; '.join(todo))
    else:
        add('PASS', 'description', f'ready ({n} chars)')


def main():
    vd = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
    os.chdir(vd)
    try:
        tl = TL.load(vd)
    except TL.TimelineError as e:
        add('FAIL', 'timeline', str(e))
        return report(vd)
    segs = TL.body_segments(tl)
    H = TL.frames(tl['hook_split']) / FPS
    body = sum(s['f_end'] - s['f_start'] for s in segs) / FPS
    expected = H + body
    fin = json.load(open('work/finish.json')) if os.path.isfile('work/finish.json') else None

    if not fin:
        add('FAIL', 'finish', 'work/finish.json missing: run `ev2 finish <video-dir>`')
    elif fin.get('cut_signature') != TL.cut_signature(tl):
        add('FAIL', 'stale', 'work/timeline.json cuts changed after the last finish: run `ev2 finish` again')
    else:
        add('PASS', 'timeline', f'hook {H:.2f}s + body {body:.2f}s ({len(segs)} segments) = {expected:.2f}s')
    if fin:
        if 'chapter_signature' not in fin:
            add('WARN', 'chapters', 'finish.json predates chapter tracking: run `ev2 finish` to be sure chapters are current')
        elif fin['chapter_signature'] != TL.chapter_signature(vd, tl):
            add('FAIL', 'stale chapters', 'chapters changed after the last finish (youtube-chapters.txt and the '
                                          'chapter cards are out of date): run `ev2 finish` again')

    try:
        ins_list = TL.insert_ranges(tl)
    except TL.TimelineError as e:
        add('FAIL', 'inserts', str(e))
        ins_list = []
    if fin and (ins_list or 'insert_signature' in fin):
        if 'insert_signature' not in fin:
            add('WARN', 'inserts', 'finish.json predates insert tracking: run `ev2 finish`')
        elif fin['insert_signature'] != TL.insert_signature(vd, tl):
            add('FAIL', 'stale inserts', 'inserts or their renders changed after the last finish: run `ev2 finish` again')
    if ins_list:
        problems = []
        for ins in ins_list:
            name, why = ins['name'], []
            render = TL.insert_render_path(vd, ins)
            html = f'insert-{name}.html'
            if not os.path.isfile(render):
                why.append('no render (run `ev2 inserts <video-dir>`)')
            else:
                r = subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0',
                                    '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', render],
                                   capture_output=True, text=True)
                try:
                    got = int(r.stdout.strip().split()[0].strip(','))
                except (ValueError, IndexError):
                    got = None
                if got != ins['n']:
                    why.append(f'render has {got} frames, expected {ins["n"]}')
                if os.path.isfile(html) and os.path.getmtime(html) > os.path.getmtime(render) + 1:
                    why.append(f'render is older than {html} (re-run `ev2 inserts`)')
            st = None
            try:
                st = json.load(open(f'work/inserts/{name}.json'))
            except (OSError, ValueError):
                pass
            if not st or not st.get('final') or st.get('placeholders') or st.get('missing'):
                why.append('not a FINAL build (run `ev2 inserts <video-dir> --final`)')
            if why:
                problems.append(f'{name}: ' + ', '.join(why))
        if problems:
            add('FAIL', 'inserts', '; '.join(problems))
        else:
            add('PASS', 'inserts', f'{len(ins_list)} inserts rendered, FINAL, right length')

    check_keys(tl, fin)

    # final.mp4
    info = probe('out/final.mp4') if os.path.isfile('out/final.mp4') else None
    if not info:
        add('FAIL', 'final.mp4', 'missing or unreadable')
        return report(vd)
    v, au = info.get('v_dur', 0), info.get('a_dur')
    if (info.get('width'), info.get('height')) != (1920, 1080) or abs(info.get('fps', 0) - FPS) > 0.01:
        add('FAIL', 'final.mp4 format', f'{info.get("width")}x{info.get("height")} @ {info.get("fps")} fps')
    if abs(v - expected) > 2.0 / FPS:
        add('FAIL', 'final.mp4 length', f'{v:.3f}s, expected {expected:.3f}s (hook + cleaned body)')
    else:
        add('PASS', 'final.mp4 length', f'{v:.3f}s = {TL.fmt_ts(v)} (expected {expected:.3f}s)')
    if au is None:
        add('FAIL', 'final.mp4 audio', 'no audio stream')
    elif abs(au - v) > 0.1:
        add('FAIL', 'A/V length', f'audio {au:.3f}s vs video {v:.3f}s')
    else:
        add('PASS', 'A/V length', f'audio {au:.3f}s vs video {v:.3f}s')

    # voice placement: cross-correlate body windows against the (cleaned) source voice
    sr = 8000
    global VOICE
    VOICE = 'work/vo_clean.wav' if os.path.isfile('work/vo_clean.wav') else 'assets/media/vo.wav'
    long_segs = [s for s in segs if s['out_end'] - s['out_start'] >= 1.0]
    picks = [long_segs[int(len(long_segs) * f)] for f in (0.1, 0.3, 0.5, 0.7, 0.9)] if long_segs else []
    checked, bad = 0, []
    for s in dict((id(x), x) for x in picks).values():
        seg_len = s['src_end'] - s['src_start']
        win = min(2.0, seg_len * 0.8)
        mid = s['src_start'] + (seg_len - win) / 2
        ref = audio_at(VOICE, mid, win, sr)
        ft = H + s['out_start'] + (mid - s['src_start'])
        sig = audio_at('out/final.mp4', ft, win, sr)
        lag, peak = lag_of(ref, sig, sr)
        if lag is None or peak < 0.5:
            continue
        checked += 1
        if abs(lag) > 1.0 / FPS:
            bad.append(f'{TL.fmt_ts(ft)}: voice {lag * 1000:+.0f} ms off (corr {peak:.2f})')
    if bad:
        add('FAIL', 'voice sync', '; '.join(bad))
    elif checked:
        add('PASS', 'voice sync', f'{checked} body points within 1 frame of the source voice')
    else:
        add('WARN', 'voice sync', 'no body window had enough speech to cross-check')

    ok, detail = picture_sync(segs, TL.frames(tl['hook_split']), exclude=[(i['f0'], i['n']) for i in ins_list])
    add({True: 'PASS', False: 'FAIL', None: 'WARN'}[ok], 'picture sync', detail)

    # hook
    zp = 'work/body_video.json'
    if os.path.isfile(zp):
        add('PASS', 'body polish', f'{json.load(open(zp)).get("zoomed_share", 0) * 100:.0f}% of the body zoomed; webcam PiP + chapter cards')
    if os.path.isfile('out/captions.srt'):
        add('PASS', 'captions.srt', f'{open("out/captions.srt", encoding="utf-8").read().count(" --> ")} captions')
    if H > 0:
        hi = probe('out/hook.mp4') if os.path.isfile('out/hook.mp4') else None
        if not hi or abs(hi.get('v_dur', 0) - H) > 2.0 / FPS:
            add('FAIL', 'hook.mp4', f'missing or not {H:.3f}s')
        else:
            add('PASS', 'hook.mp4', f'{hi["v_dur"]:.3f}s')
    st = json.load(open('work/build.json')) if os.path.isfile('work/build.json') else None
    if H > 0:
        if st is None:
            add('FAIL', 'hook build', 'work/build.json missing: cannot confirm the hook is final; run `ev2 build <video-dir> --final`')
        elif st.get('placeholders') or st.get('missing'):
            add('FAIL', 'hook build', f'placeholders {st.get("placeholders")} missing {st.get("missing")}: '
                                      f'source them or cut the beats, then `ev2 build <video-dir> --final`')
        elif not st.get('final'):
            add('FAIL', 'hook build', 'the last hook build was not a FINAL build: run `ev2 build <video-dir> --final`, then `ev2 finish`')
        elif 'hook_split' in st and abs(float(st['hook_split']) - float(tl['hook_split'])) > 0.5 / FPS:
            add('FAIL', 'hook build', f'built for hook_split {st["hook_split"]}s, timeline says {tl["hook_split"]}s: rebuild the hook')
        else:
            add('PASS', 'hook build', 'FINAL build: no placeholders, all assets present')

    # editor projects
    editors = (fin or {}).get('editors', [])
    if 'concat' in editors:
        cj = 'out/concat/concat.json'
        if not os.path.isfile(cj):
            add('FAIL', 'Concat project', f'{cj} missing')
        else:
            d = json.load(open(cj, encoding='utf-8'))
            tlc = (d.get('timelines') or [{}])[0].get('clips', [])
            main = sorted([c for c in tlc if c.get('trackId') == 'T4'], key=lambda c: c['start'])
            want = len(segs) + (1 if H > 0 else 0)
            end = max((c['start'] + c['duration'] for c in main), default=0)
            stamp = json.load(open('work/concat-gen.json')) if os.path.isfile('work/concat-gen.json') else {}
            if len(main) != want or abs(end - expected) > 2.0 / FPS:
                add('FAIL', 'Concat project', f'{len(main)} main clips ending {end:.3f}s, expected {want} ending {expected:.3f}s')
            elif stamp.get('cut_signature') != TL.cut_signature(tl):
                add('FAIL', 'Concat project', 'generated from an older timeline: run `ev2 concat <video-dir>`')
            else:
                add('PASS', 'Concat project', f'{cj}: {len(main)} clips on the main lane, ends {end:.2f}s')
    if 'kdenlive' in editors:
        kp = 'out/project.kdenlive'
        if not os.path.isfile(kp):
            add('FAIL', 'Kdenlive project', f'{kp} missing')
        else:
            import xml.etree.ElementTree as ET
            r = ET.parse(kp).getroot()
            pl = {p.get('id'): p for p in r.findall('playlist')}
            fr = lambda p: sum(int(e.get('out')) - int(e.get('in')) + 1 for e in p.findall('entry')) + \
                sum(int(b.get('length')) for b in p.findall('blank'))
            v1 = fr(pl['playlist_v1'])
            if abs(v1 / FPS - expected) > 2.0 / FPS:
                add('FAIL', 'Kdenlive project', f'V1 {v1} frames, expected {round(expected * FPS)}')
            else:
                add('PASS', 'Kdenlive project', f'V1 {v1} frames (final.mp4 split at the cuts, sound attached)')

    # short
    if (fin or {}).get('short', True):
        si = probe('out/short.mp4') if os.path.isfile('out/short.mp4') else None
        if not si or (si.get('width'), si.get('height')) != (1080, 1920) or si['duration'] > 60.5:
            add('FAIL', 'short.mp4', 'missing, not 1080x1920, or longer than 60 s')
        else:
            add('PASS', 'short.mp4', f'1080x1920, {si["duration"]:.1f}s')

    # chapters
    if os.path.isfile('work/chapters.json'):
        ch = [(c['time'], c['title']) for c in json.load(open('work/chapters.json', encoding='utf-8'))]
        probs = TL.youtube_chapter_problems(ch, v)
        add('WARN' if probs else 'PASS', 'YouTube chapters', '; '.join(probs) if probs else f'{len(ch)} chapters')
    else:
        add('WARN', 'YouTube chapters', 'work/chapters.json missing')

    if os.path.isfile('out/youtube-description.md'):
        check_description(vd)

    # how pro it looks and sounds (beauty.py): its FAILs block DONE like any other
    if os.environ.get('EV2_NO_BEAUTY') != '1':
        try:
            import beauty
            for lvl, what, det in beauty.run(vd):
                add(lvl, what, det)
        except Exception as e:
            add('WARN', 'beauty', f'beauty check could not run: {e}')

    # loudness
    r = subprocess.run(['ffmpeg', '-nostdin', '-i', 'out/final.mp4', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True)
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', r.stderr)
    if m:
        lufs = float(m[-1])
        add('PASS' if -16 <= lufs <= -12 else 'WARN', 'loudness', f'{lufs:.1f} LUFS integrated')
    return report(vd)


def report(vd):
    fails = [r for r in RESULTS if r[0] == 'FAIL']
    warns = [r for r in RESULTS if r[0] == 'WARN']
    verdict = 'NOT DONE' if fails else ('DONE (with warnings)' if warns else 'DONE')
    lines = [f'# Verify: {os.path.basename(vd)}', '', f'**{verdict}**', '', '| | Check | Detail |', '|---|---|---|']
    lines += [f'| {lvl} | {what} | {det} |' for lvl, what, det in RESULTS]
    os.makedirs(os.path.join(vd, 'out'), exist_ok=True)
    open(os.path.join(vd, 'out', 'verify.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    json.dump({'verdict': verdict, 'results': [dict(level=l, check=w, detail=d) for l, w, d in RESULTS]},
              open(os.path.join(vd, 'out', 'verify.json'), 'w'), indent=2, ensure_ascii=False)
    for lvl, what, det in RESULTS:
        print(f'  {lvl:<4}  {what:<18} {det}')
    print(f'\nverify: {verdict}  -> {os.path.join(vd, "out", "verify.md")}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
