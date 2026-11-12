"""ev2_timeline.py — the single source of truth for an Editor V2 video's timeline.

Every stage that needs to know "where is what in time" reads work/timeline.json through
this module: clean-retakes.py writes it, finish.py assembles from it, concat-gen.py and
kdenlive-gen.py lay out editor projects from it, and verify.py checks the result against it.

Schema (version 1), all times in seconds of the SOURCE recording, quantized to the frame:

    {
      "schema": 1,
      "fps": 30,
      "source": "assets/media/src.mp4",       # original recording (has audio)
      "source_duration": 418.0,
      "hook_split": 45.0,                       # hook = source [0, hook_split); body starts here
      "segments": [                             # body keep segments, ascending, all >= hook_split
        {"src_start": 45.0, "src_end": 61.2},
        ...
      ],
      "chapters": [                             # body chapters, by SOURCE time (edit freely)
        {"src_t": 52.3, "title": "Setup"}
      ],
      "hook_title": "Intro",                    # chapter name for 00:00
      "inserts": [                              # optional explainer inserts (animated scenes)
        {"name": "order-flow", "src_t": 135.2, "dur": 8.0, "mode": "over", "cam": true}
      ],
      "body_music": false,                      # optional: quiet music under the whole body (ev2 finish --body-music)
      "updated": "2026-11-11T14:00:00"
    }

Insert keys: name (^[a-z0-9][a-z0-9-]{0,39}$, unique), src_t (SOURCE seconds, >= hook_split),
dur (FINAL-video seconds, 1.5-30; it covers that much of the cut body, even across cut
boundaries), mode ("full" opaque scene | "over" transparent over the screencast; default
"full"), cam (webcam PiP stays on top; default true).

Final-video time of a body source time t (t inside a kept segment):
    final_t = hook_duration + out_start(segment) + (t - segment.src_start)
"""
import datetime
import hashlib
import json
import os
import re

SCHEMA = 1
FPS = 30
SR = 48000
SAMPLES_PER_FRAME = SR // FPS  # 1600


class TimelineError(Exception):
    pass


def tl_path(vd):
    return os.path.join(vd, 'work', 'timeline.json')


def q(t, fps=FPS):
    """Quantize a time to the frame grid."""
    return round(round(float(t) * fps) / fps, 6)


def frames(t, fps=FPS):
    return int(round(float(t) * fps))


def load(vd, required=True):
    p = tl_path(vd)
    if not os.path.isfile(p):
        if required:
            raise TimelineError(f'{p} not found: run `ev2 transcribe <video-dir>` (clean-retakes.py writes it)')
        return None
    with open(p, 'r', encoding='utf-8') as f:
        tl = json.load(f)
    validate(tl)
    return tl


def save(vd, tl):
    tl['schema'] = SCHEMA
    tl['updated'] = datetime.datetime.now().replace(microsecond=0).isoformat()
    validate(tl)
    p = tl_path(vd)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(tl, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, p)
    return p


def validate(tl):
    if tl.get('schema') != SCHEMA:
        raise TimelineError(f'timeline.json schema {tl.get("schema")!r} != {SCHEMA}; re-run `ev2 clean <video-dir>`')
    fps = tl.get('fps', FPS)
    if fps != FPS:
        raise TimelineError(f'timeline.json fps {fps} unsupported (pipeline is {FPS} fps)')
    hs = float(tl.get('hook_split', -1))
    if hs < 0:
        raise TimelineError('timeline.json: hook_split missing or negative')
    segs = tl.get('segments') or []
    prev_end = hs - 1e-6
    for i, s in enumerate(segs):
        a, b = float(s['src_start']), float(s['src_end'])
        if b <= a:
            raise TimelineError(f'timeline.json: segment {i} has end <= start ({a} -> {b})')
        if a < prev_end - 1e-6:
            raise TimelineError(f'timeline.json: segment {i} starts at {a}, before previous end/hook_split {prev_end}')
        prev_end = b
    for c in tl.get('chapters') or []:
        if 'src_t' not in c or 'title' not in c:
            raise TimelineError(f'timeline.json: chapter entries need "src_t" and "title": {c}')
    _validate_inserts(tl, hs)


INSERT_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
INSERT_MODES = ('full', 'over')
INSERT_DUR_MIN, INSERT_DUR_MAX = 1.5, 30.0


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_inserts(tl, hs):
    if not isinstance(tl.get('body_music', False), bool):
        raise TimelineError('timeline.json: "body_music" must be true or false')
    inserts = tl.get('inserts') or []
    if not isinstance(inserts, list):
        raise TimelineError('timeline.json: "inserts" must be a list')
    seen = set()
    for i, ins in enumerate(inserts):
        if not isinstance(ins, dict):
            raise TimelineError(f'timeline.json: insert #{i} must be an object')
        name = ins.get('name')
        if not isinstance(name, str) or not INSERT_NAME_RE.match(name):
            raise TimelineError(f'timeline.json: insert "{name}": name must match ^[a-z0-9][a-z0-9-]{{0,39}}$ '
                                '(lowercase letters, digits, dashes)')
        if name in seen:
            raise TimelineError(f'timeline.json: insert "{name}": duplicate name, rename one')
        seen.add(name)
        if not _num(ins.get('src_t')):
            raise TimelineError(f'timeline.json: insert "{name}": "src_t" (source seconds) is required and must be a number')
        if ins['src_t'] < hs - 1e-6:
            raise TimelineError(f'timeline.json: insert "{name}": src_t {ins["src_t"]} is inside the hook '
                                f'(< hook_split {hs}); move it into the body')
        if not _num(ins.get('dur')):
            raise TimelineError(f'timeline.json: insert "{name}": "dur" (seconds) is required and must be a number')
        if not INSERT_DUR_MIN <= ins['dur'] <= INSERT_DUR_MAX:
            raise TimelineError(f'timeline.json: insert "{name}": dur {ins["dur"]:g} out of range '
                                f'({INSERT_DUR_MIN:g}-{INSERT_DUR_MAX:g} s)')
        mode = ins.get('mode', 'full')
        if mode not in INSERT_MODES:
            raise TimelineError(f'timeline.json: insert "{name}": unknown mode {mode!r} (use "full" or "over")')
        if not isinstance(ins.get('cam', True), bool):
            raise TimelineError(f'timeline.json: insert "{name}": "cam" must be true or false')


def cut_signature(tl):
    """Hash of everything that changes the assembled picture/sound (not chapters)."""
    key = json.dumps({'source': tl.get('source'), 'hook_split': tl['hook_split'],
                      'segments': tl.get('segments', [])}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def body_segments(tl):
    """Segments with out_start/out_end (body-relative) added, frame-exact."""
    out, pos = [], 0
    for s in tl.get('segments') or []:
        a, b = frames(s['src_start']), frames(s['src_end'])
        n = b - a
        if n <= 0:
            continue
        out.append({'src_start': a / FPS, 'src_end': b / FPS,
                    'f_start': a, 'f_end': b,
                    'out_start': pos / FPS, 'out_end': (pos + n) / FPS})
        pos += n
    return out


def body_duration(tl):
    return sum(frames(s['src_end']) - frames(s['src_start']) for s in tl.get('segments') or [])/FPS


def src_to_body(tl, t):
    """Body-relative output time of source time t; snaps forward into the next kept segment
    when t falls inside a cut. None when t is after the last kept segment."""
    for s in body_segments(tl):
        if t < s['src_start']:
            return s['out_start']
        if t < s['src_end']:
            return s['out_start'] + (t - s['src_start'])
    return None


def final_chapters(tl, hook_dur, hook_chapters=None):
    """[(final_t, title)] sorted: hook chapters (already in final time, < hook_dur) + body chapters."""
    out = []
    for t, title in hook_chapters or []:
        if 0 <= t < hook_dur - 1e-6:
            out.append((float(t), title))
    if not any(t < 0.05 for t, _ in out):
        out.append((0.0, tl.get('hook_title') or 'Intro'))
    for c in tl.get('chapters') or []:
        bt = src_to_body(tl, float(c['src_t']))
        if bt is not None:
            out.append((hook_dur + bt, c['title']))
    out.sort(key=lambda x: x[0])
    return out


def insert_ranges(tl):
    """Inserts in BODY frames, sorted: [{'name','mode','cam','f0','n','body_t','dur','src_t'}].
    f0 = first body frame (0 = first frame after the hook), n = frame count."""
    total = sum(s['f_end'] - s['f_start'] for s in body_segments(tl))
    out = []
    for ins in tl.get('inserts') or []:
        name = ins['name']
        bt = src_to_body(tl, float(ins['src_t']))
        if bt is None:
            raise TimelineError(f'insert "{name}" starts after the last kept segment: move src_t earlier')
        f0, n = frames(bt), frames(ins['dur'])
        if f0 + n > total:
            raise TimelineError(f'insert "{name}" runs past the end of the body (ends at {(f0 + n) / FPS:.2f} s, '
                                f'body is {total / FPS:.2f} s): shorten dur or move src_t')
        out.append({'name': name, 'mode': ins.get('mode', 'full'), 'cam': ins.get('cam', True),
                    'f0': f0, 'n': n, 'body_t': f0 / FPS, 'dur': n / FPS, 'src_t': float(ins['src_t'])})
    out.sort(key=lambda r: r['f0'])
    for a, b in zip(out, out[1:]):
        if b['f0'] < a['f0'] + a['n']:
            raise TimelineError(f'inserts "{a["name"]}" and "{b["name"]}" overlap: move one or shorten dur')
    return out


def insert_render_path(vd, ins):
    return os.path.join(vd, 'work', 'inserts', ins['name'] + ('.mov' if ins.get('mode', 'full') == 'over' else '.mp4'))


def insert_signature(vd, tl):
    """Hash of insert timing/mode/cam and of the render files (size, mtime): changes when anything
    about the inserts changed since the last `ev2 finish`."""
    ranges = insert_ranges(tl)
    renders = {}
    for r in ranges:
        p = insert_render_path(vd, r)
        renders[r['name']] = [os.path.getsize(p), int(os.path.getmtime(p))] if os.path.isfile(p) else None
    key = json.dumps({'ranges': ranges, 'renders': renders}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def fmt_ts(seconds):
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m:02d}:{sec:02d}'


def youtube_chapter_problems(chapters, total):
    """YouTube shows chapters only if: first at 00:00, >= 3 chapters, each >= 10 s."""
    probs = []
    if not chapters or chapters[0][0] > 0.5:
        probs.append('first chapter must start at 00:00')
    if len(chapters) < 3:
        probs.append(f'only {len(chapters)} chapter(s); YouTube needs at least 3')
    for i, (t, title) in enumerate(chapters):
        end = chapters[i + 1][0] if i + 1 < len(chapters) else total
        if end - t < 10:
            probs.append(f'chapter "{title}" at {fmt_ts(t)} is {end - t:.1f}s long; YouTube needs >= 10s')
    return probs


def chapter_signature(vd, tl):
    """Hash of everything that changes chapters: timeline chapters, hook title, hook chapters."""
    hc = os.path.join(vd, 'work', 'hook_chapters.json')
    hook = open(hc, encoding='utf-8').read() if os.path.isfile(hc) else ''
    key = json.dumps({'chapters': tl.get('chapters') or [], 'hook_title': tl.get('hook_title'), 'hook': hook},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# words.json is the working transcript: tools write it, and the creator corrects it by hand.
# words.auto.json remembers the hash of the last automatic write, so a hand edit is detectable.
def words_paths(vd):
    tx = os.path.join(vd, 'work', 'tx')
    return os.path.join(tx, 'words.json'), os.path.join(tx, 'words.auto.json')


def stamp_words(vd):
    wp, sp = words_paths(vd)
    with open(sp, 'w') as f:
        json.dump({'sha': sha256_file(wp)}, f)


def words_edited(vd):
    """True: words.json changed since the last automatic write. False: untouched.
    None: no words.json. 'unknown': words.json exists but was never stamped (older project)."""
    wp, sp = words_paths(vd)
    if not os.path.isfile(wp):
        return None
    if not os.path.isfile(sp):
        return 'unknown'
    try:
        return json.load(open(sp)).get('sha') != sha256_file(wp)
    except (ValueError, OSError):
        return 'unknown'


def sha256_file(p, limit=None):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:16]
