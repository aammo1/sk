#!/usr/bin/env python3
"""check.py — check everything the agent writes BEFORE spending minutes on renders.

    ev2 check <video-dir>

Reads work/timeline.json (chapters, inserts + recipes, callouts, keys), work/hook.json and
work/look.json, and prints each problem as one plain sentence saying what to change.
Exit 0 = ready to render, 1 = fix the listed problems first.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'components'))
import ev2_timeline as TL  # noqa: E402


def main():
    vd = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
    probs, notes = [], []
    try:
        tl = TL.load(vd)
    except (TL.TimelineError, ValueError) as e:
        print(f'check: work/timeline.json: {e}')
        return 1
    hs = TL.frames(tl['hook_split']) / TL.FPS
    body = TL.body_duration(tl)
    chs = sorted(tl.get('chapters') or [], key=lambda c: float(c['src_t']))
    if len(chs) < 3:
        probs.append(f'chapters: {len(chs)} in work/timeline.json; YouTube needs at least 3 (one per topic, the first at the start of the body)')
    for c in chs:
        if len(c['title']) > 40:
            probs.append(f'chapter "{c["title"]}": {len(c["title"])} chars, keep titles <= 40')
    try:
        TL.insert_ranges(tl)
    except TL.TimelineError as e:
        probs.append(str(e))
    import ev2_recipes as R
    for e in tl.get('inserts') or []:
        if e.get('recipe'):
            probs += R.validate(e)
        elif not os.path.isfile(os.path.join(vd, 'inserts.py')):
            probs.append(f'insert "{e.get("name")}": no "recipe" (use one of {", ".join(R.RECIPES)})')
    n_ins = len(tl.get('inserts') or [])
    if body > 240 and n_ins == 0:
        notes.append(f'the body is {body / 60:.0f} min with no explainer insert: 1 insert per 2-3 minutes keeps it lively')
    if body > 120 and not tl.get('callouts'):
        notes.append('no callouts: point at 2-5 key buttons ("callouts" in work/timeline.json)')
    try:
        TL.key_ranges(tl)
    except TL.TimelineError as e:
        probs.append(str(e))
    hp = os.path.join(vd, 'work', 'hook.json')
    if hs > 0:
        if not os.path.isfile(hp):
            probs.append('work/hook.json missing: run `ev2 hook <dir> --init`, then write its "promise"')
        else:
            import ev2_hook
            try:
                cfg = ev2_hook.load_cfg(vd)
                probs += ['hook.json: ' + p for p in ev2_hook.check_cfg(cfg, tl)]
            except ev2_hook.HookError as e:
                probs.append(str(e))
        if hs > 32:
            notes.append(f'the hook is {hs:.0f}s: 15-30 s works best (`ev2 clean <dir> --hook-split S`)')
    lp = os.path.join(vd, 'work', 'look.json')
    if os.path.isfile(lp):
        try:
            look = json.load(open(lp))
            if look.get('frame', 'inset') not in ('inset', 'full'):
                probs.append('look.json: frame must be "inset" or "full"')
            if not 1.2 <= float(look.get('max_zoom', 1.6)) <= 2.0:
                probs.append('look.json: max_zoom must be 1.2-2.0 (1.6 reads best)')
        except ValueError as e:
            probs.append(f'look.json is not valid JSON: {e}')
    if not os.path.isfile(os.path.join(vd, 'work', 'inputs.json')):
        notes.append('no input log: zooms follow screen activity, no click ripples (record with `ev2 rec install` running next time)')
    for p in probs:
        print(f'  FIX   {p}')
    for n in notes:
        print(f'  TIP   {n}')
    print(f'check: {"ready" if not probs else str(len(probs)) + " problem(s) to fix"}')
    return 1 if probs else 0


if __name__ == '__main__':
    sys.exit(main())
