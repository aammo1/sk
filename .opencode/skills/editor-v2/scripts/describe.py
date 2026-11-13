#!/usr/bin/env python3
"""describe.py — the YouTube description frame for a finished video (optional, opt-in).

    describe.py <video-dir> [--lang darija|en|fr] [--apps a,b] [--force] [--check]

Fills every factual part (chapters from out/youtube-chapters.txt, the setup it was shown on,
credited sources from PLAN.md) and leaves `<!-- WRITE ... -->` slots for the prose: a short
summary and one line per chapter. -> out/youtube-description.md
Per-chapter transcript notes for whoever writes the prose -> work/description-notes.md
Stamp (sha256 of the generated text) -> work/description.json; a description edited since it
was generated is never overwritten without --force.

--check reads the existing description only: slots left, length vs YouTube's 5000 limit, and
whether its chapters block equals out/youtube-chapters.txt. Exit 1 if anything is left to do.
"""
import argparse, datetime, glob, hashlib, json, os, re, shutil, subprocess, sys, textwrap

try:
    import numpy  # noqa: F401
    import cv2  # noqa: F401
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

YT_LIMIT = 5000
SLOT = '<!-- WRITE'
HEADINGS = {
    'en': {'shows': 'What the video shows', 'chapters': 'Chapters', 'setup': 'Shown on', 'sources': 'Sources'},
    'fr': {'shows': 'Ce que montre la vidéo', 'chapters': 'Chapitres', 'setup': 'Configuration', 'sources': 'Sources'},
    'darija': {'shows': 'شنو كاين ف الفيديو', 'chapters': 'الفصول', 'setup': 'الجهاز لي خدمت بيه', 'sources': 'المصادر'},
}
MUSIC_LINE = '- Music: original, generated in code by editor-v2 (no third-party audio)'
# PLAN.md template rows the agent is expected to replace: skipped while their Source cell is unchanged.
TEMPLATE_ROWS = {
    'screen': '`assets/media/src.mp4`',
    'sound': '`scripts/synth-sfx.py`',
    'music bed': '`sfx/ev1kit/bed_pulse.wav`',
    'music': '`scripts/synth-music.py`',
    'brand': 'Wikimedia Commons / Official SVG',
    'docs': 'Tool docs / GitHub repository',
}
TS_RE = re.compile(r'^\d{1,2}:\d{2}(:\d{2})?\s')


class DescribeError(Exception):
    pass


def sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_chapters(vd, label):
    txt = os.path.join(vd, 'out', 'youtube-chapters.txt')
    js = os.path.join(vd, 'work', 'chapters.json')
    if not (os.path.isfile(txt) and os.path.isfile(js)):
        raise DescribeError(f'no chapters yet: run ev2 finish {label} first')
    lines = [l.rstrip() for l in open(txt, encoding='utf-8') if l.strip()]
    chapters = json.load(open(js, encoding='utf-8'))
    return lines, chapters


def load_json(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None


def plan_title(vd):
    p = os.path.join(vd, 'PLAN.md')
    if not os.path.isfile(p):
        return None
    for line in open(p, encoding='utf-8'):
        m = re.match(r'^\s*-\s*\*\*Title:\*\*\s*(.*)$', line)
        if m:
            t = m.group(1).strip()
            return None if not t or t.startswith('<!--') else t
    return None


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def plan_sources(vd):
    """Rows of the PLAN.md 'Sources, Assets & Licences' table worth crediting: (item, source, licence)."""
    p = os.path.join(vd, 'PLAN.md')
    if not os.path.isfile(p):
        return []
    rows, in_sec, header = [], False, None
    for line in open(p, encoding='utf-8'):
        if line.startswith('## '):
            in_sec = line.startswith('## Sources, Assets')
            header = None
            continue
        if not in_sec or not line.lstrip().startswith('|'):
            continue
        cells = _cells(line)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r':?-+:?', c) for c in cells if c):
            continue

        def col(word, default):
            for i, h in enumerate(header):
                if word in h:
                    return i
            return default
        ii, si, li = col('item', 0), col('source', 2), col('licen', 3)
        if max(ii, si, li) >= len(cells):
            continue
        item, src, lic = cells[ii], cells[si], cells[li]
        if not lic or not src or '(example)' in item:
            continue
        if TEMPLATE_ROWS.get(item.lower()) == src:
            continue
        # only third-party material needs a credit: the creator's own recording, local file paths
        # and "identify only" brand marks are internal notes, not something a viewer should read
        low = (src + ' ' + lic).lower()
        if any(k in low for k in ('creator original', 'own recording', 'identify only', 'assets/', 'work/',
                                  '.png', '.jpg', 'editor-v2', 'generated in code')):
            continue
        rows.append(tuple(c.replace('`', '') for c in (item, src, lic)))
    return rows


def music_used(vd):
    fin = load_json(os.path.join(vd, 'work', 'finish.json')) or {}
    return bool(fin.get('body_music')) or os.path.isfile(os.path.join(vd, 'work', 'premix_bed.wav'))


def recorded_date(vd):
    srcs = sorted(glob.glob(os.path.join(vd, 'assets', 'media', 'src.*')))
    if not srcs:
        return None
    src = srcs[0]
    if shutil.which('ffprobe'):
        try:
            out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags=creation_time',
                                  '-of', 'default=nw=1:nk=1', src], capture_output=True, text=True, timeout=30).stdout
            m = re.search(r'\d{4}-\d{2}-\d{2}', out)
            if m:
                return m.group(0)
        except (OSError, subprocess.SubprocessError):
            pass
    return datetime.date.fromtimestamp(os.path.getmtime(src)).isoformat()


def system_name():
    if shutil.which('omarchy-version'):
        try:
            v = subprocess.run(['omarchy-version'], capture_output=True, text=True, timeout=10).stdout.strip()
            if v:
                return v if v.lower().startswith('omarchy') else f'Omarchy {v}'
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        for line in open('/etc/os-release', encoding='utf-8'):
            if line.startswith('PRETTY_NAME='):
                return line.split('=', 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return None


def app_versions(apps):
    if not apps or not shutil.which('pacman'):
        return []
    out = []
    for a in apps:
        try:
            r = subprocess.run(['pacman', '-Q', a], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            out.append(r.stdout.strip())
    return out


def setup_line(vd, apps):
    parts = [p for p in [system_name(), ', '.join(app_versions(apps))] if p]
    line = '; '.join(parts)
    date = recorded_date(vd)
    if date:
        line = f'{line}. Recorded {date}.' if line else f'Recorded {date}.'
    elif line:
        line += '.'
    return line


def build_text(vd, lang, apps, ch_lines, chapters):
    h = HEADINGS[lang]
    out = ['<!-- WRITE: 2-3 sentences: what the viewer will be able to do after this video -->', '',
           f'{h["shows"]}:']
    for c in chapters:
        if float(c.get('time', 0)) <= 0.0:
            continue
        out.append(f'{c["title"]}: <!-- WRITE: 1-2 sentences, what is done in this chapter '
                   f'(notes: work/description-notes.md) -->')
    out += ['', h['chapters'], *ch_lines]
    setup = setup_line(vd, apps)
    if setup:
        out += ['', h['setup'], setup]
    src = [f'- {i}: {s} ({l})' for i, s, l in plan_sources(vd)]
    if src:
        out += ['', h['sources'], *src]
    return '\n'.join(out) + '\n'


def write_notes(vd, chapters, title):
    words = []
    tl = TL.load(vd, required=False)
    if tl is not None:
        from body_render import final_words
        words = final_words(vd, tl)
    fin = load_json(os.path.join(vd, 'work', 'finish.json')) or {}
    end_all = float(fin.get('expected_final') or float('inf'))
    out = ['# Description notes', '']
    if title:
        out += [f'Title: {title}', '']
    out += ['What was said in each chapter (final-video time), to summarize in the <!-- WRITE --> slots of',
            'out/youtube-description.md. Rewritten by every `ev2 describe` run.', '']
    for k, c in enumerate(chapters):
        t0 = float(c['time'])
        t1 = float(chapters[k + 1]['time']) if k + 1 < len(chapters) else end_all
        text = ' '.join(w['w'] for w in words if t0 <= w['s'] < t1).strip()
        out.append(f'## {c.get("timestamp") or TL.fmt_ts(t0)} {c["title"]}')
        out += textwrap.wrap(text, 100) if text else ['(no transcript words in this chapter)']
        out.append('')
    p = os.path.join(vd, 'work', 'description-notes.md')
    with open(p, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return p


def chapters_block(text):
    """The timestamp lines that follow a chapters heading (any language)."""
    names = {HEADINGS[l]['chapters'] for l in HEADINGS}
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if l.strip().rstrip(':') in names:
            block = []
            for x in lines[i + 1:]:
                if not TS_RE.match(x.strip() + ' '):
                    break
                block.append(x.rstrip())
            if block:
                return block
    return None


def check(vd, label):
    p = os.path.join(vd, 'out', 'youtube-description.md')
    if not os.path.isfile(p):
        raise DescribeError(f'{p} not found: run ev2 describe {label} first')
    text = open(p, encoding='utf-8').read()
    slots = text.count(SLOT)
    n = len(text)
    ok = True
    print(f'describe: {slots} <!-- WRITE --> slot(s) left' + ('' if slots == 0 else ' (fill them)'))
    ok &= slots == 0
    print(f'describe: {n} / {YT_LIMIT} chars' + (' (too long for YouTube: shorten it)' if n > YT_LIMIT else ''))
    ok &= n <= YT_LIMIT
    txt = os.path.join(vd, 'out', 'youtube-chapters.txt')
    if os.path.isfile(txt):
        want = [l.rstrip() for l in open(txt, encoding='utf-8') if l.strip()]
        have = chapters_block(text)
        same = have == want
        print('describe: chapters block ' + ('matches out/youtube-chapters.txt' if same else
              'differs from out/youtube-chapters.txt (paste the new chapters, or regenerate with ev2 describe --force)'))
        ok &= same
    else:
        print(f'describe: no out/youtube-chapters.txt to compare (run ev2 finish {label})')
        ok = False
    print('describe: ' + ('ready to paste into YouTube' if ok else 'not done yet'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description='Write the YouTube description frame for a finished video.')
    ap.add_argument('video_dir')
    ap.add_argument('--lang', choices=sorted(HEADINGS), default='darija', help='Heading language (default darija)')
    ap.add_argument('--apps', default='', help='Comma-separated packages for the setup line (pacman -Q)')
    ap.add_argument('--force', action='store_true', help='Overwrite a description edited since it was generated')
    ap.add_argument('--check', action='store_true', help='Report what is left in the existing description (no writing)')
    a = ap.parse_args()
    vd = os.path.abspath(a.video_dir)
    try:
        if a.check:
            return check(vd, a.video_dir)
        ch_lines, chapters = read_chapters(vd, a.video_dir)
        out_p = os.path.join(vd, 'out', 'youtube-description.md')
        stamp_p = os.path.join(vd, 'work', 'description.json')
        if os.path.isfile(out_p) and not a.force:
            stamp = load_json(stamp_p) or {}
            if sha256(open(out_p, encoding='utf-8').read()) != stamp.get('sha'):
                raise DescribeError('out/youtube-description.md was edited since it was generated; '
                                    'use --force to regenerate (your edits will be lost)')
        apps = [x.strip() for x in a.apps.split(',') if x.strip()]
        text = build_text(vd, a.lang, apps, ch_lines, chapters)
        with open(out_p, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(stamp_p, 'w', encoding='utf-8') as f:
            json.dump({'sha': sha256(text), 'lang': a.lang,
                       'written': datetime.datetime.now().isoformat(timespec='seconds')}, f, indent=2)
        notes = write_notes(vd, chapters, plan_title(vd))
        print(f'describe: notes -> {os.path.relpath(notes, vd)}')
        print(f'describe: out/youtube-description.md ({len(text)} chars, {text.count(SLOT)} slots to write). '
              f'Next: fill the <!-- WRITE --> slots, then ev2 describe {a.video_dir} --check')
        return 0
    except (DescribeError, TL.TimelineError) as e:
        print(f'describe: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
