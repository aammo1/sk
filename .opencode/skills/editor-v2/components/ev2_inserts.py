"""Explainer inserts: scene registry and per-insert HyperFrames builds (see `ev2 help inserts`)."""
import json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
import ev2_timeline as TL
from ev1_devices import Comp, esc

_SCENES = {}
_STATE = {'placeholders': [], 'missing': []}
_CACHE = {}


def scene(name):
    def deco(fn):
        _SCENES[name] = fn
        return fn
    return deco


def _tl():
    if 'tl' not in _CACHE:
        _CACHE['tl'] = TL.load('.')
    return _CACHE['tl']


def _words():
    if 'words' not in _CACHE:
        p = os.path.join('work', 'tx', 'words.json')
        _CACHE['words'] = json.load(open(p)) if os.path.exists(p) else []
    return _CACHE['words']


def words(ins):
    segs = TL.body_segments(_tl())
    out = []
    for w in _words():
        s = w['s']
        for seg in segs:
            if seg['src_start'] <= s < seg['src_end']:
                local = seg['out_start'] + (s - seg['src_start']) - ins['body_t']
                if 0 <= local < ins['dur']:
                    out.append((w['w'], round(local, 3)))
                break
    return out


def asset(key):
    if 'assets' not in _CACHE:
        p = os.path.join('work', 'assets.json')
        _CACHE['assets'] = json.load(open(p)) if os.path.exists(p) else {}
    path = _CACHE['assets'].get(key)
    if path and os.path.exists(path):
        return path
    _STATE['missing'].append(key)
    return None


def ph(c, t0, t1, label, z=1):
    _STATE['placeholders'].append(label)
    c.clip(t0, t1, '<div class="ev1-layer" style="background:#2a2a2a"><div style="position:absolute;left:80px;top:80px;'
           f'font:700 60px var(--ev1-sans);color:#f0f">{esc(label)}</div></div>', z)


def example(label):
    _STATE['placeholders'].append(f'template example: {label}')


def hype_slide(deck, slide, width=1920):
    out = os.path.join('assets', 'img', 'hype', f'{os.path.splitext(os.path.basename(deck))[0]}-{slide}.png')
    tag = f'hype:{deck}#{slide}'
    if os.path.exists(out) and os.path.exists(deck) and os.path.getmtime(out) >= os.path.getmtime(deck):
        return out
    if not shutil.which('hype'):
        print('inserts: hype is not installed; cannot render slide', file=sys.stderr)
    elif not os.path.exists(deck):
        print(f'inserts: Hype deck not found: {deck}', file=sys.stderr)
    else:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        r = subprocess.run(['hype', 'render', deck, '--slide', str(slide), '-o', out, '--width', str(width), '--json'],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            return out
        print(f'inserts: hype render failed for {deck}#{slide}: {(r.stderr or r.stdout).strip()}', file=sys.stderr)
    _STATE['missing'].append(tag)
    return None


def run(vd='.'):
    final = os.environ.get('FINAL') == '1'
    try:
        tl = TL.load(vd)
        ranges = TL.insert_ranges(tl)
    except TL.TimelineError as e:
        sys.exit(f'inserts: ERROR {e}')
    raw = {e['name']: e for e in tl.get('inserts') or []}
    if not ranges:
        print('inserts: no inserts in work/timeline.json')
        return
    names = [r['name'] for r in ranges]
    only = [n for n in os.environ.get('EV2_ONLY', '').split(',') if n]
    if only:
        bad = [n for n in only if n not in names]
        if bad:
            sys.exit(f'inserts: unknown insert {", ".join(bad)} (in work/timeline.json: {", ".join(names)})')
        ranges = [r for r in ranges if r['name'] in only]
    import ev2_recipes as R
    problems = []
    for n in names:
        if raw[n].get('recipe'):
            problems += R.validate(raw[n])
            if raw[n].get('mode', 'full') != 'full':
                problems.append(f'insert "{n}": recipes are full-screen scenes: set "mode": "full" (or remove mode)')
        elif n not in _SCENES:
            sys.exit(f'inserts: insert "{n}" has no "recipe" and inserts.py has no @scene("{n}"): '
                     f'give it a recipe ({", ".join(R.RECIPES)}) in work/timeline.json')
    if problems:
        sys.exit('inserts: fix these in work/timeline.json:\n  - ' + '\n  - '.join(problems))
    for n in _SCENES:
        if n not in names:
            print(f'inserts: warning: @scene("{n}") is not in work/timeline.json; skipped')
    theme = None
    os.makedirs(os.path.join(vd, 'work', 'inserts'), exist_ok=True)
    refused = []
    for ins in ranges:
        name = ins['name']
        _STATE['placeholders'], _STATE['missing'] = [], []
        c = Comp(ins['dur'], cid=f'insert-{name}')
        if raw[name].get('recipe'):
            if theme is None:
                import ev2_pro as P
                _, theme = P.ensure_look(os.path.abspath(vd))
            R.build(c, ins, raw[name], R.Ctx(theme, words=words(ins), vd=vd))
        else:
            _SCENES[name](c, ins)
        ph_list, missing = list(_STATE['placeholders']), sorted(set(_STATE['missing']))
        clean = not ph_list and not missing
        status = {'placeholders': ph_list, 'missing': missing, 'final': bool(final and clean),
                  'dur': ins['dur'], 'mode': ins['mode']}
        json.dump(status, open(os.path.join(vd, 'work', 'inserts', f'{name}.json'), 'w'), indent=2)
        if final and not clean:
            refused.append(f'{name}: placeholders {ph_list} missing {missing}')
            continue
        c.write(os.path.join(vd, f'insert-{name}.html'), 'assets/ev1/tokens.css',
                title=f'Insert {name}', transparent=(ins['mode'] == 'over'))
        cues = os.path.join(vd, 'work', 'inserts', f'{name}.cues.txt')
        c.write_cues(cues)
        n_cues = sum(1 for l in open(cues) if l.strip() and not l.lstrip().startswith('#')) if os.path.exists(cues) else 0
        kind = f'recipe {raw[name]["recipe"]}' if raw[name].get('recipe') else 'scene'
        print(f'inserts: {name} {kind} {ins["mode"]} {ins["dur"]}s | cues {n_cues} | placeholders {len(ph_list)} | missing {len(missing)}')
    if refused:
        sys.exit('inserts: FINAL refused — ' + '; '.join(refused))


if __name__ == '__main__':
    run('.')
