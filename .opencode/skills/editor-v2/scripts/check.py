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


def _kept_words(vd, tl):
    wp = os.path.join(vd, 'work', 'tx', 'words.json')
    if not os.path.isfile(wp):
        return []
    try:
        raw = json.load(open(wp, encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    segs = [s for s in TL.body_segments(tl) if not s.get('card')]
    out = []
    si = 0
    for w in sorted((x for x in raw if isinstance(x, dict) and 's' in x and 'w' in x), key=lambda x: float(x['s'])):
        s = float(w['s'])
        e = float(w.get('e', s))
        while si < len(segs) and s >= segs[si]['src_end']:
            si += 1
        if si >= len(segs):
            break
        seg = segs[si]
        if s < seg['src_start'] - 1e-6:
            continue
        bt = seg['out_start'] + max(0.0, s - seg['src_start'])
        prev = out[-1] if out else None
        is_start = (
            prev is None
            or si != prev['si']
            or (s - prev['e']) >= 0.3
            or prev['w'].rstrip().endswith(('.', '!', '?', '؟', '…'))
        )
        out.append({'w': str(w['w']), 's': s, 'e': e, 'bt': bt, 'si': si, 'start': is_start})
    return out


def _body_to_src(tl, bt):
    segs = [s for s in TL.body_segments(tl) if not s.get('card')]
    for s in segs:
        if bt < s['out_start']:
            return s['src_start']
        if bt < s['out_end']:
            return s['src_start'] + (bt - s['out_start'])
    return segs[-1]['src_end'] if segs else float(tl['hook_split'])


def _suggest_at(tl, kwords, bt_target, lo_bt, hi_bt):
    in_range = [(i, kw) for i, kw in enumerate(kwords) if lo_bt <= kw['bt'] < hi_bt]
    starts = [(i, kw) for i, kw in in_range if kw['start']]
    pool = starts or in_range
    if pool:
        idx, kw = min(pool, key=lambda item: abs(item[1]['bt'] - bt_target))
        snippet = ' '.join(x['w'] for x in kwords[idx:idx + 8])
        return kw['s'], snippet
    return _body_to_src(tl, bt_target), ''


def _fmt_gap(gap):
    sec = int(round(gap))
    if sec >= 60:
        return f'{sec // 60}m{sec % 60:02d}s'
    return f'{sec}s'


def _explainer_tips(vd, tl, chs, body, ins_ranges, insert_every):
    if insert_every == 0:
        return []
    if ins_ranges is None:
        ins_ranges = []
        for ins in tl.get('inserts') or []:
            if isinstance(ins, dict) and isinstance(ins.get('src_t'), (int, float)) and isinstance(ins.get('dur'), (int, float)):
                bt = TL.src_to_body(tl, float(ins['src_t']))
                if bt is not None:
                    ins_ranges.append({'body_t': bt, 'dur': float(ins['dur'])})
        ins_ranges.sort(key=lambda r: r['body_t'])
    intervals = [(r['body_t'], r['body_t'] + r['dur']) for r in ins_ranges]
    kwords = _kept_words(vd, tl)
    tips = []
    cur = 0.0
    gaps = []
    for b0, b1 in intervals:
        if b0 > cur:
            gaps.append((cur, b0))
        cur = max(cur, b1)
    if body > cur:
        gaps.append((cur, body))
    for g0, g1 in gaps:
        gap = g1 - g0
        if gap > insert_every * 1.25:
            src_t, snippet = _suggest_at(tl, kwords, (g0 + g1) / 2.0, g0, g1)
            tail = f' — "{snippet}"' if snippet else ''
            tips.append(f'explainer gap {_fmt_gap(gap)} (body {TL.fmt_ts(g0)}-{TL.fmt_ts(g1)}): '
                        f'suggest one near source {TL.fmt_ts(src_t)}{tail}')
    cards = {round(c['out_start'], 4): c['out_end'] for c in TL.card_segments(tl)}
    body_chs = []
    for c in chs:
        bt = TL.src_to_body(tl, float(c['src_t']))
        if bt is not None:
            body_chs.append((bt, c))
    for i, (ch_start, c) in enumerate(body_chs):
        ch_end = body_chs[i + 1][0] if i + 1 < len(body_chs) else body
        if ch_end - ch_start >= 30.0:
            if not any(ch_start <= b0 <= ch_start + 25.0 for b0, _ in intervals):
                content_start = cards.get(round(ch_start, 4), ch_start)
                hi = min(ch_end, ch_start + 25.0)
                if content_start < hi:
                    src_t, snippet = _suggest_at(tl, kwords, content_start + 0.5, content_start, hi)
                else:
                    src_t, snippet = _suggest_at(tl, kwords, ch_start, ch_start, ch_end)
                tail = f' — "{snippet}"' if snippet else ''
                tips.append(f'chapter "{c["title"]}" has no explainer near its start: '
                            f'suggest source {TL.fmt_ts(src_t)}{tail}')
    if tips:
        k = len(tl.get('inserts') or [])
        m = max(1, round(body / insert_every))
        tips.append(f'explainers: {k} planned, ~{m} suggested for one every {insert_every}s')
    return tips


def main():
    vd = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
    probs, notes = [], []
    try:
        tl = TL.load(vd)
    except (TL.TimelineError, ValueError) as e:
        print(f'check: work/timeline.json: {e}')
        return 1
    import ev2_pro as P
    insert_every = P.LOOK_DEFAULTS['insert_every']
    insert_hold = P.LOOK_DEFAULTS['insert_hold']
    lp = os.path.join(vd, 'work', 'look.json')
    if os.path.isfile(lp):
        try:
            look = json.load(open(lp))
            if look.get('frame', 'inset') not in ('inset', 'full'):
                probs.append('look.json: frame must be "inset" or "full"')
            if not 1.2 <= float(look.get('max_zoom', 1.6)) <= 2.0:
                probs.append('look.json: max_zoom must be 1.2-2.0 (1.6 reads best)')
            if look.get('insert_every') is not None:
                ie = int(round(float(look['insert_every'])))
                insert_every = 0 if ie == 0 else max(30, min(300, ie))
            if look.get('insert_hold') is not None:
                insert_hold = float(look['insert_hold'])
        except (ValueError, TypeError) as e:
            probs.append(f'look.json is not valid JSON: {e}')
    hs = TL.frames(tl['hook_split']) / TL.FPS
    body = TL.body_duration(tl)
    chs = sorted(tl.get('chapters') or [], key=lambda c: float(c['src_t']))
    if len(chs) < 3:
        probs.append(f'chapters: {len(chs)} in work/timeline.json; YouTube needs at least 3 (one per topic, the first at the start of the body)')
    for c in chs:
        if len(c['title']) > 40:
            probs.append(f'chapter "{c["title"]}": {len(c["title"])} chars, keep titles <= 40')
    ins_ranges = None
    try:
        ins_ranges = TL.insert_ranges(tl)
    except TL.TimelineError as e:
        probs.append(str(e))
    import ev2_recipes as R
    for e in tl.get('inserts') or []:
        if e.get('recipe'):
            probs += R.validate(e)
            if e['recipe'] in R.RECIPES:
                dur = float(e['dur'])
                need = R.min_dur(e['recipe'], e.get('data') or {}, insert_hold)
                if dur < need:
                    n = R.count_items(e['recipe'], e.get('data') or {})
                    probs.append(f'insert "{e["name"]}": dur {dur:g}s is too short for {n} items: use dur >= {need:g} (12 s recommended)')
        elif not os.path.isfile(os.path.join(vd, 'inserts.py')):
            probs.append(f'insert "{e.get("name")}": no "recipe" (use one of {", ".join(R.RECIPES)})')
    notes += _explainer_tips(vd, tl, chs, body, ins_ranges, insert_every)
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
