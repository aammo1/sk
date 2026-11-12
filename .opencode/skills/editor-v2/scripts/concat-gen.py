#!/usr/bin/env python3
"""concat-gen.py — write a Concat project (concat.json) for an Editor V2 video.

Concat (https://github.com/jub0t/Concat) is the default finishing editor. A Concat project
is a folder holding concat.json. This writes <video-dir>/out/concat/concat.json, laid out
from work/timeline.json so it matches out/final.mp4 frame for frame:

  T1  chapters   hidden: one title clip per chapter (markers; show the lane to burn them in)
  T2  captions   hidden: one editable title clip per caption (show the lane to burn them in)
  T3  overlays   empty, for your own titles / B-roll
  T4  main       out/final.mp4 (polished: zooms, webcam PiP, chapter cards, clean audio)
                 split at every cut: the hook, then one clip per kept body segment
  T5  raw cuts   hidden + muted: the same cuts from the ORIGINAL recording (assets/media/src.*);
                 show it to re-trim a cut back into a removed pause
  T6  music      empty
  T7  inserts    hidden + muted: each explainer insert render at its time (already baked into T4; reference only)

Safety:
  - refuses to write while the project is open in Concat (concat.lock held)
  - if you edited concat.json in Concat since the last generation, the old file is kept
    as concat.json.bak-<timestamp> before writing
  - when Concat is installed, the result is opened headless (`concat --mcp headless`) and
    the clip count is checked; a mismatch is an error

Usage:
  concat-gen.py <video-dir> [--out out/concat] [--no-check]
Open it:
  concat --project <video-dir>/out/concat
"""
import argparse, fcntl, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402


def probe_media(path, mid):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate',
                        '-of', 'json', path], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    item = {'id': mid, 'path': os.path.abspath(path), 'name': os.path.basename(path),
            'duration': round(float(d['format'].get('duration') or 0), 6), 'kind': 'video', 'hasAudio': False}
    tracks = []
    for s in d.get('streams', []):
        if s.get('codec_type') == 'video' and 'width' not in item:
            n, _, dd = (s.get('r_frame_rate') or '30/1').partition('/')
            item.update({'width': int(s['width']), 'height': int(s['height']),
                         'frameRate': round(float(n) / float(dd or 1), 3), 'frameRateFraction': f'{n}/{dd or 1}',
                         'videoCodec': s.get('codec_name')})
        elif s.get('codec_type') == 'audio':
            item['hasAudio'] = True
            item.setdefault('audioCodec', s.get('codec_name'))
            tracks.append({'channels': int(s.get('channels') or 2), 'codec': s.get('codec_name'),
                           'index': int(s['index']), 'language': 'und', 'sampleRate': int(s.get('sample_rate') or 48000)})
    if 'width' not in item:
        item['kind'] = 'audio'
    if tracks:
        item['audioTracks'] = tracks
    return item


def clip(cid, track, media, name, start, dur, src_start=0.0, kind='video'):
    return {'id': cid, 'trackId': track, 'mediaId': media, 'name': name, 'kind': kind,
            'start': round(start, 6), 'duration': round(dur, 6), 'sourceStart': round(src_start, 6),
            'volume': 1.0, 'fadeIn': 0.0, 'fadeOut': 0.0, 'scale': 1.0, 'offsetX': 0.0, 'offsetY': 0.0,
            'rotation': 0.0, 'opacity': 1.0, 'speed': 1.0, 'preservePitch': True,
            'filters': [], 'videoEffects': []}


def title_clip(cid, track, text, start, dur):
    c = clip(cid, track, '', text, start, dur, kind='text')
    c['text'] = {'content': text, 'fontFamily': 'Inter', 'fontSize': 0.045, 'fontWeight': 700.0,
                 'italic': False, 'color': '#ffffff', 'align': 'center', 'opacity': 1.0,
                 'strokeWidth': 0.0, 'strokeColor': '#000000', 'shadow': True, 'background': '#000000aa'}
    c['offsetY'] = 0.38
    return c


def locked(folder):
    lock = os.path.join(folder, 'concat.lock')
    if not os.path.exists(lock):
        return False
    try:
        with open(lock, 'a') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--out', default='out/concat', help='Project folder (default out/concat)')
    ap.add_argument('--no-check', action='store_true', help='Skip opening the result in headless Concat')
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)
    tl = TL.load(vd)
    segs = TL.body_segments(tl)
    hs = float(tl['hook_split'])
    folder = a.out if os.path.isabs(a.out) else os.path.join(vd, a.out)
    os.makedirs(folder, exist_ok=True)
    if locked(folder):
        sys.exit(f'concat-gen: {folder} is open in Concat (concat.lock). Close it there first.')

    src = tl.get('source')
    if not src or not os.path.isfile(os.path.join(vd, src)):
        sys.exit(f'concat-gen: source recording {src!r} not found under {vd}')
    final = os.path.join(vd, 'out', 'final.mp4')
    if not os.path.isfile(final):
        sys.exit('concat-gen: out/final.mp4 missing: run `ev2 finish` first')

    media, clips = [], []
    ids = iter(range(1, 100000))
    nid = lambda p: f'{p}{next(ids)}'
    H = TL.frames(hs) / TL.FPS
    media.append(probe_media(final, 'm1'))
    media.append(probe_media(os.path.join(vd, src), 'm2'))
    if hs > 0:
        clips.append(clip(nid('c'), 'T4', 'm1', 'Hook', 0.0, H))
        raw = clip(nid('c'), 'T5', 'm2', 'Hook (raw)', 0.0, H)
        clips.append(raw)
    for i, s in enumerate(segs, 1):
        d = s['out_end'] - s['out_start']
        clips.append(clip(nid('c'), 'T4', 'm1', f'Body {i:03d}', H + s['out_start'], d, H + s['out_start']))
        clips.append(clip(nid('c'), 'T5', 'm2', f'Raw {i:03d}', H + s['out_start'], d, s['src_start']))
    import body_render
    for cs, ce, txt in body_render.caption_groups(body_render.final_words(vd, tl)):
        c = title_clip(nid('c'), 'T2', txt, cs, max(0.3, ce - cs))
        c['text']['fontFamily'], c['text']['fontSize'] = 'Cairo', 0.04
        clips.append(c)
    hook_ch = []
    hc = os.path.join(vd, 'work', 'hook_chapters.json')
    if os.path.isfile(hc):
        hook_ch = [(float(c.get('time', 0)), c.get('title', '')) for c in json.load(open(hc, encoding='utf-8'))]
    chapters = TL.final_chapters(tl, H, hook_ch)
    total = H + TL.body_duration(tl)
    for i, (t, title) in enumerate(chapters):
        nxt = chapters[i + 1][0] if i + 1 < len(chapters) else total
        clips.append(title_clip(nid('c'), 'T1', title, t, max(0.5, min(4.0, nxt - t))))

    ins_list = TL.insert_ranges(tl)
    ins_items = []
    for ins in ins_list:
        render = TL.insert_render_path(vd, ins)
        if not os.path.isfile(render):
            print(f'  note: insert "{ins["name"]}" has no render yet; not on T7')
            continue
        ins_items.append((ins, render))

    def add_inserts(items):
        added = []
        for k, (ins, render) in enumerate(items):
            mid = f'm{3 + k}'
            media.append(probe_media(render, mid))
            added.append(clip(nid('c'), 'T7', mid, f'Insert {ins["name"]}', H + ins['body_t'], ins['dur']))
        return added

    base_media, base_clips = list(media), list(clips)
    clips = base_clips + add_inserts(ins_items)

    video = {'width': 1920, 'height': 1080, 'rateNum': TL.FPS, 'rateDen': 1}
    tracks = [{'id': 'T1', 'visible': False, 'muted': True}, {'id': 'T2', 'visible': False, 'muted': True},
              {'id': 'T3', 'visible': True, 'muted': False}, {'id': 'T4', 'visible': True, 'muted': False},
              {'id': 'T5', 'visible': False, 'muted': True}, {'id': 'T6', 'visible': True, 'muted': False}]
    if ins_items:
        tracks.append({'id': 'T7', 'visible': False, 'muted': True})

    def make_doc():
        timeline = {'id': 'TL1', 'name': 'Editor V2', 'video': video, 'tracks': tracks, 'clips': clips}
        return {'concat': '0.1.0', 'version': 1, 'name': os.path.basename(vd), 'activeTimelineId': 'TL1',
                'media': media, 'fonts': [], 'timelines': [timeline],
                # flat mirror of the active timeline, as Concat itself writes it
                'tracks': tracks, 'clips': clips, 'video': video}

    path = os.path.join(folder, 'concat.json')
    stamp_p = os.path.join(vd, 'work', 'concat-gen.json')
    if os.path.isfile(path):
        last = json.load(open(stamp_p)).get('mtime', 0) if os.path.isfile(stamp_p) else 0
        if os.path.getmtime(path) > last + 1:
            bak = f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
            shutil.copy2(path, bak)
            print(f'concat-gen: concat.json was edited since the last generation; kept a copy: {bak}')

    def write_project():
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(make_doc(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        json.dump({'mtime': os.path.getmtime(path), 'clips': len(clips), 'cut_signature': TL.cut_signature(tl)},
                  open(stamp_p, 'w'))

    write_project()

    n_av = len(segs) + (1 if hs > 0 else 0)
    print(f'concat-gen: {path}')
    n_caps = sum(1 for c in clips if c['trackId'] == 'T2')
    print(f'  T4 main: {"hook + " if hs > 0 else ""}{len(segs)} body cuts, {total:.2f}s | chapters {len(chapters)} | '
          f'captions {n_caps} | T5 raw cuts (hidden)'
          + (f' | inserts {len(ins_items)} (T7, hidden)' if ins_items else ''))

    if not a.no_check:
        from concat_mcp import concat_bin, open_and_read, count_clips
        if not concat_bin():
            print('  note: Concat not installed; skipped the open check')
        else:
            try:
                state = open_and_read(folder)
            except Exception as e:
                sys.exit(f'concat-gen: Concat could not open the project: {e}')
            n = count_clips(state)
            n_mov = sum(1 for ins, _ in ins_items if ins['mode'] == 'over')
            if n != len(clips) and n_mov and n == len(clips) - n_mov:
                print(f'  note: Concat dropped the {n_mov} alpha (.mov) insert clips; leaving "over" inserts off T7')
                ins_items = [(i, r) for i, r in ins_items if i['mode'] != 'over']
                media[:], clips[:] = base_media, base_clips
                clips.extend(add_inserts(ins_items))
                if not ins_items:
                    tracks.pop()
                write_project()
                state = open_and_read(folder)
                n = count_clips(state)
            dur = (state.get('timeline') or {}).get('duration')
            if n != len(clips):
                sys.exit(f'concat-gen: Concat loaded {n} clips, expected {len(clips)} (some were dropped as invalid)')
            if dur is not None and abs(float(dur) - total) > 1.5 / TL.FPS:
                sys.exit(f'concat-gen: Concat timeline is {dur}s, expected {total:.3f}s')
            print(f'  checked: opens in Concat, {n} clips, {float(dur or 0):.2f}s')
    print(f'  open with: concat --project "{folder}"')


if __name__ == '__main__':
    main()
