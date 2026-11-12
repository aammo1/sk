#!/usr/bin/env python3
"""keys-suggest.py — suggest key-press pills from the spoken key names in the transcript.

Scans the transcript for key names said out loud (Latin, Arabic script or French) and groups
them into shortcuts ("سوبر سبيس" -> Super + Space, "shift plus enter" -> Shift + Enter).
It only SUGGESTS: work/timeline.json is never touched. Copy the entries you want into
"keys" in work/timeline.json, then run ev2 finish <dir>.

Usage:
    keys-suggest.py <video-dir> [--gap 1.2]

Reads:  work/tx/words.json (SOURCE seconds), work/timeline.json (optional: hook_split, keys)
Writes: work/keys-suggest.json, work/keys-suggest.md
"""
import argparse, json, os, re, sys, unicodedata

# normalized word -> key name. Extend here.
KEY_WORDS = {
    # Latin
    'super': 'Super', 'shift': 'Shift', 'ctrl': 'Ctrl', 'control': 'Ctrl', 'alt': 'Alt',
    'space': 'Space', 'enter': 'Enter', 'return': 'Enter', 'tab': 'Tab', 'esc': 'Esc',
    'escape': 'Esc', 'backspace': 'Backspace', 'delete': 'Delete', 'del': 'Delete',
    'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right',
    # Arabic script (Darija transcripts)
    'سوبر': 'Super', 'شيفت': 'Shift', 'شفت': 'Shift',
    'كنترول': 'Ctrl', 'كونترول': 'Ctrl', 'كترل': 'Ctrl',
    'ألت': 'Alt', 'آلت': 'Alt', 'الت': 'Alt',
    'سبيس': 'Space', 'سپيس': 'Space', 'إنتر': 'Enter', 'انتر': 'Enter',
    'تاب': 'Tab', 'إسكيب': 'Esc', 'اسكيب': 'Esc',
    # French
    'entrée': 'Enter', 'espace': 'Space',
}
KEY_WORDS.update({f'f{i}': f'F{i}' for i in range(1, 13)})

# letters and digits count only right after another key word ("super 1", "ctrl shift t")
WEAK_KEYS = {c: c.upper() for c in 'abcdefghijklmnopqrstuvwxyz0123456789'}

# words allowed between two keys of the same shortcut (fillers included)
CONNECTORS = {'+', 'plus', 'و', 'with', 'et', 'مع', 'touche'}

# a shortcut of a single key is only suggested for these
SOLO_OK = {'Super', 'Enter', 'Esc', 'Tab'} | {f'F{i}' for i in range(1, 13)}

ALREADY_WINDOW = 1.5
CONTEXT_WORDS = 4
DEFAULT_DUR = 2.5


def norm(w):
    w = unicodedata.normalize('NFC', w).lower()
    w = ''.join(c for c in w if unicodedata.category(c) != 'Mn' and c != '\u0640')  # tashkeel, tatweel
    return ''.join(c for c in w if c.isalnum() or c == '+')


def classify(raw):
    """-> ('conn', None) | ('key', [names]) | ('weak', [name]) | (None, None)"""
    w = norm(raw)
    if w in CONNECTORS or (w and set(w) == {'+'}):
        return 'conn', None
    if not w:
        return None, None
    if '+' in w:  # one token like "ctrl+shift+t"
        parts = [p for p in w.split('+') if p]
        names = []
        for p in parts:
            n = lookup(p)
            if n is None:
                n = WEAK_KEYS.get(p)
            if n is None:
                return None, None
            names.append(n)
        if not any(lookup(p) for p in parts):
            return None, None
        return 'key', names
    n = lookup(w)
    if n:
        return 'key', [n]
    if w in WEAK_KEYS:
        return 'weak', [WEAK_KEYS[w]]
    return None, None


def lookup(w):
    if w in KEY_WORDS:
        return KEY_WORDS[w]
    cands = [w]
    if w.startswith('و') and len(w) > 2:  # attached "and"
        cands.append(w[1:])
    for c in list(cands):
        if c.startswith('ال') and len(c) > 3:
            cands.append(c[2:])
    for c in cands:
        if c in KEY_WORDS:
            return KEY_WORDS[c]
    return None


def find_combos(words, gap):
    tags = [classify(str(x.get('w', ''))) for x in words]
    combos, cur, pend = [], None, []  # cur = {'idx': [word indexes], 'keys': [...], 'last': kind}

    def close():
        nonlocal cur
        if cur:
            combos.append(cur)
        cur = None

    for i, (kind, names) in enumerate(tags):
        if cur is not None:
            prev_e = float(words[(pend[-1] if pend else cur['idx'][-1])]['e'])
            if float(words[i]['s']) - prev_e > gap:
                close()
                pend = []
        if kind == 'conn':
            if cur is not None:
                pend.append(i)
            continue
        if kind == 'key':
            if cur is None:
                cur = {'idx': [i], 'keys': list(names), 'last': 'key'}
            else:
                cur['idx'].append(i)
                cur['keys'].extend(names)
                cur['last'] = 'key'
            pend = []
            continue
        if kind == 'weak' and cur is not None and cur['last'] == 'key':
            cur['idx'].append(i)
            cur['keys'].extend(names)
            cur['last'] = 'weak'
            pend = []
            continue
        close()
        pend = []
    close()

    out = []
    for c in combos:
        keys = []
        for k in c['keys']:
            if k not in keys:
                keys.append(k)
        if len(keys) == 1 and keys[0] not in SOLO_OK:
            continue
        a, b = c['idx'][0], c['idx'][-1]
        out.append({'a': a, 'b': b, 'keys': keys})
    return out


def die(msg):
    print(f'keys: {msg}')
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="keys-suggest.py — suggest key pills from spoken key names (never edits the timeline).")
    ap.add_argument('video_dir', help="Video project directory")
    ap.add_argument('--gap', type=float, default=1.2,
                    help="Max seconds between the words of one shortcut (default: 1.2)")
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)
    wp = os.path.join(vd, 'work', 'tx', 'words.json')
    if not os.path.isfile(wp):
        die(f'work/tx/words.json missing: run ev2 transcribe {a.video_dir} first')
    try:
        with open(wp, encoding='utf-8') as f:
            words = json.load(f)
    except (OSError, ValueError) as e:
        die(f'work/tx/words.json unreadable ({e}): run ev2 transcribe {a.video_dir} again')
    words = [x for x in words if isinstance(x, dict) and 's' in x and 'e' in x]

    hook_split, existing = None, []
    tp = os.path.join(vd, 'work', 'timeline.json')
    if os.path.isfile(tp):
        try:
            with open(tp, encoding='utf-8') as f:
                tl = json.load(f)
        except (OSError, ValueError) as e:
            die(f'work/timeline.json unreadable ({e}): fix it or run ev2 cut {a.video_dir}')
        if isinstance(tl, dict):
            if tl.get('hook_split') is not None:
                hook_split = float(tl['hook_split'])
            for k in tl.get('keys') or []:
                if isinstance(k, dict) and k.get('src_t') is not None:
                    existing.append(float(k['src_t']))

    sugg = []
    for c in find_combos(words, a.gap):
        first = words[c['a']]
        if hook_split is not None and float(first['s']) < hook_split:
            continue
        src_t = round(max(0.0, float(first['s']) - 0.1), 2)
        ctx = ([str(x['w']) for x in words[max(0, c['a'] - CONTEXT_WORDS):c['a']]] + ['['] +
               [str(x['w']) for x in words[c['a']:c['b'] + 1]] + [']'] +
               [str(x['w']) for x in words[c['b'] + 1:c['b'] + 1 + CONTEXT_WORDS]])
        sugg.append({
            'src_t': src_t,
            'keys': ' + '.join(c['keys']),
            'label': '',
            'dur': DEFAULT_DUR,
            'heard': ' '.join(str(x['w']) for x in words[c['a']:c['b'] + 1]),
            'context': ' '.join(ctx).replace('[ ', '[').replace(' ]', ']'),
            'already': any(abs(src_t - t) <= ALREADY_WINDOW for t in existing),
        })

    os.makedirs(os.path.join(vd, 'work'), exist_ok=True)
    jp = os.path.join(vd, 'work', 'keys-suggest.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump({'suggestions': sugg}, f, ensure_ascii=False, indent=2)
        f.write('\n')

    def cell(s):
        return str(s).replace('|', '\\|').replace('\n', ' ')

    md = ['# Key pill suggestions', '',
          'Spoken key names found in the transcript (source seconds). Nothing was added to the timeline.', '']
    if sugg:
        md += ['| # | src_t | keys | heard | context | status |', '|---|---|---|---|---|---|']
        for i, s in enumerate(sugg, 1):
            md.append(f"| {i} | {s['src_t']:.2f} | {cell(s['keys'])} | {cell(s['heard'])} | "
                      f"{cell(s['context'])} | {'already' if s['already'] else 'new'} |")
    else:
        md.append('_No spoken shortcuts found._')
    md += ['', '## How to use', '',
           '1. Copy the entries you want (without `heard`, `context`, `already`) from '
           '`work/keys-suggest.json` into `"keys"` in `work/timeline.json`, e.g.',
           '   `{"src_t": 46.0, "keys": "Super + Space", "label": "", "dur": 2.5}`.',
           '2. Add a `label` if useful (e.g. "then type the name"); adjust `src_t` to the moment the keys are pressed.',
           f'3. Run `ev2 finish {a.video_dir}`.', '']
    with open(os.path.join(vd, 'work', 'keys-suggest.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    n_already = sum(1 for s in sugg if s['already'])
    print(f'keys: {len(sugg)} suggestions ({n_already} already in the timeline) -> work/keys-suggest.md')


if __name__ == '__main__':
    main()
