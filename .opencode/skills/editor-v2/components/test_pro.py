#!/usr/bin/env python3
"""test_pro.py — tests for the "pro look" layer: design system, recipes, hook config, timeline
callouts/recipes validation, input-log alignment, the body stage and the beauty check.

    $EV2_PY components/test_pro.py          (~1 min; ffmpeg, no HyperFrames render)
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'scripts'))

import numpy as np  # noqa: E402
import ev2_pro as P  # noqa: E402
import ev2_recipes as R  # noqa: E402
import ev2_timeline as TL  # noqa: E402
from ev1_devices import Comp  # noqa: E402

PASSED = []


def ok(name):
    PASSED.append(name)
    print(f'  ok  {name}')


def ff(*args):
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *args], check=True)


# ------------------------------------------------------------------ design system
def test_theme_and_text():
    th = P.make_theme('#E11D74')
    assert th['accent'].startswith('#') and th['accent'] != th['accent2']
    assert P.make_theme('#808080')['accent'] == P.normalize_accent(P.DEFAULT_ACCENT)   # grey brand -> default
    assert P.short_label('Tableau de bord — نظرة عامة') == 'Tableau de bord'
    assert len(P.short_label('x' * 60)) <= 27
    size, lines = P.fit_text('من الطلب حتى التسليم فـ 6 دقايق', 1500)
    assert len(lines) <= 2 and size >= 56
    if len(lines) == 2:   # balanced: no lonely last word
        assert len(lines[1].split()) >= 2
    assert P.plain('من *الطلب* حتى') == 'من الطلب حتى'
    ok('theme, labels, text fitting')


def test_icons():
    missing = [n for _, n in P.ICON_WORDS if not P.icon_exists(n)]
    assert not missing, missing
    assert P.guess_icon('WhatsApp') == 'brand:whatsapp'
    assert P.guess_icon('Livraison') == 'truck'
    assert P.guess_icon('تأكيد الطلب') == 'circle-check'
    assert P.guess_icon('zzzz qqqq') == 'circle-dot'
    s = P.icon_svg('truck', 40, '#fff')
    assert s.startswith('<svg') and 'path' in s
    assert 'viewBox' in P.icon_svg('brand:github', 40)
    ok('icons (lucide + brands + guessing)')


def test_backdrop_and_accent():
    th = P.make_theme('#3B82F6')
    bg = P.render_bg(th, 192, 108)
    assert bg.shape == (108, 192, 3) and bg.dtype == np.uint8
    f = np.zeros((1080, 1920, 3), np.uint8)
    f[300:700, 400:1400] = (116, 29, 225)          # a big magenta panel (BGR)
    f[:, :12] = (240, 220, 40)                      # a cyan wallpaper strip at the edge: ignored
    acc = P.auto_accent([f, f.copy(), f.copy()])
    h, s, v = P._hsv(acc)
    assert 0.85 < h or h < 0.05, (acc, h)          # magenta/pink, not cyan
    ok('backdrop + auto accent ignores edges')


def test_paint_out():
    f = np.full((1080, 1920, 3), 40, np.uint8)
    f[800:1000, 1600:1800] = 230                    # the "webcam"
    g = P.paint_out(f, (1600, 800, 200, 200))
    assert g[900, 1700].mean() < 120, g[900, 1700]
    ok('webcam paint-out')


# ------------------------------------------------------------------ recipes
EXAMPLES = [
    {'name': 'a', 'recipe': 'flow', 'data': {'title': 'كيفاش *كتدوز*', 'steps': ['Boutique', 'Commande', {'label': 'WhatsApp', 'sub': 'Confirmation'}]}},
    {'name': 'b', 'recipe': 'steps', 'data': {'title': 'Steps', 'steps': [{'label': 'One', 'sub': 'x'}, 'Two', 'Three']}},
    {'name': 'c', 'recipe': 'checklist', 'data': {'title': 'Check', 'items': ['A', 'B', 'C', 'D', 'E']}},
    {'name': 'd', 'recipe': 'compare', 'data': {'title': 'A / B', 'left': {'title': 'A', 'items': ['x', 'y']}, 'right': {'title': 'B', 'items': ['z']}}},
    {'name': 'e', 'recipe': 'stat', 'data': {'value': '-46%', 'label': 'less time', 'items': [{'value': '3', 'label': 'x'}]}},
    {'name': 'f', 'recipe': 'statement', 'data': {'text': 'One *big* idea', 'icon': 'brand:whatsapp'}},
]


def test_recipe_validation():
    for e in EXAMPLES:
        assert R.validate(e) == [], (e['name'], R.validate(e))
    bad = [
        ({'name': 'x', 'recipe': 'nope', 'data': {}}, 'unknown recipe'),
        ({'name': 'x', 'recipe': 'flow', 'data': {'steps': ['only one']}}, 'needs 2-6'),
        ({'name': 'x', 'recipe': 'flow', 'data': {'steps': ['a', 'b' * 50]}}, 'keep labels'),
        ({'name': 'x', 'recipe': 'flow', 'data': {'steps': ['a', {'label': 'b', 'icon': 'not-an-icon-xyz'}]}}, 'not found'),
        ({'name': 'x', 'recipe': 'stat', 'data': {'label': 'x'}}, '"value" is required'),
        ({'name': 'x', 'recipe': 'statement', 'data': {'text': 'w ' * 60}}, 'keep it <= 90'),
        ({'name': 'x', 'recipe': 'compare', 'data': {'left': {'items': []}}}, '"left" needs'),
    ]
    for e, want in bad:
        msgs = R.validate(e)
        assert msgs and any(want in m for m in msgs), (want, msgs)
    ok('recipe validation (plain-language errors)')


def test_recipe_builds():
    th = P.make_theme('#7C5CFF')
    for e in EXAMPLES:
        c = Comp(8.0, cid='t')
        ins = {'name': e['name'], 'dur': 8.0, 'mode': 'full'}
        R.build(c, ins, e, R.Ctx(th, words=[('Commande', 2.0)]))
        html = '\n'.join(c.els)
        assert c.js, e['name']
        for lab in ['Boutique', 'One', 'A', 'less time', 'big']:
            pass
        assert len(html) > 500
        # every element that is revealed later has a starting state (no flash of content at t=0)
        assert any('opacity:0' in p for p in c.pre), e['name']
    t = R.schedule(4, 8.0, said=[None, 3.0, None, None])
    assert all(b - a >= 0.25 for a, b in zip(t, t[1:])) and t[-1] <= 8.0 - 1.2
    ok('recipes build to compositions; schedule is ordered')


# ------------------------------------------------------------------ timeline
def base_tl():
    return {'schema': 1, 'fps': 30, 'hook_split': 20.0,
            'segments': [{'src_start': 20.0, 'src_end': 80.0}, {'src_start': 81.0, 'src_end': 140.0}],
            'chapters': [{'src_t': 20.0, 'title': 'A'}, {'src_t': 60.0, 'title': 'B'}, {'src_t': 100.0, 'title': 'C'}]}


def test_timeline_fields():
    tl = base_tl()
    tl['callouts'] = [{'src_t': 50.0, 'text': 'Click here'}]
    tl['inserts'] = [dict(EXAMPLES[0], src_t=30.0, dur=6)]
    TL.validate(tl)
    assert TL.insert_ranges(tl)[0]['cam'] is False                   # full scenes hide the PiP by default
    for bad, want in [({'src_t': 5.0, 'text': 'x'}, 'after the hook'), ({'src_t': 50.0}, '"text" is required'),
                      ({'src_t': 50.0, 'text': 'x' * 50}, 'max 40'), ({'src_t': 50.0, 'text': 'x', 'dur': 20}, '1-8')]:
        t2 = base_tl()
        t2['callouts'] = [bad]
        try:
            TL.validate(t2)
            raise AssertionError(f'no error for {bad}')
        except TL.TimelineError as e:
            assert want in str(e), (want, str(e))
    t3 = base_tl()
    t3['inserts'] = [{'name': 'x', 'src_t': 30.0, 'dur': 5, 'recipe': 3}]
    try:
        TL.validate(t3)
        raise AssertionError('recipe type not checked')
    except TL.TimelineError:
        pass
    ok('timeline: callouts + recipe fields + cam default')


# ------------------------------------------------------------------ hook pieces
def test_hook_config_and_geometry():
    import ev2_hook as Hk
    tl = base_tl()
    assert any('promise' in p for p in Hk.check_cfg({'promise': ''}, tl))
    assert any('<= 60' in p for p in Hk.check_cfg({'promise': 'x ' * 40}, tl))
    assert any('inside the hook' in p for p in Hk.check_cfg({'promise': 'ok', 'shots': [{'src_t': 3.0}]}, tl))
    assert Hk.check_cfg({'promise': 'Ship it in *5 min*', 'shots': [{'src_t': 40.0, 'label': 'x'}]}, tl) == []
    for D in (8, 15, 22, 30, 45):
        a, c = Hk.phase_lengths(D)
        assert a + c < D and 2 <= Hk.n_shots(D) <= 7
    cam = (1650, 800, 230, 240)
    x, y, w, h = Hk.smart_crop(cam, (300, 200, 600, 500))
    assert x + w <= cam[0] - 10 or y + h <= cam[1] - 10, (x, y, w, h)    # clear of the webcam
    assert abs(w / h - 16 / 9) < 0.01
    ok('hook config checks + crops clear of the webcam')


def test_stage_and_zoom():
    import body_render as B
    look = {'frame': 'inset', 'inset': 0.9, 'max_zoom': 1.6}
    gx, gy, gw, gh, r = P.stage_geometry(look, (0, 25, 1920, 1030))
    assert 0 < gx < 200 and gw < 1920 and r > 0
    assert P.stage_geometry({'frame': 'full'}, (0, 0, 1920, 1080))[:4] == (0, 0, 1920, 1080)
    pr = P.pip_rect((1700, 820, 220, 230))
    assert pr[0] + pr[2] <= 1920 and pr[1] + pr[3] <= 1080 and pr[3] >= 270
    tl = base_tl()
    inp = {'clicks': [{'t': 30.0, 'x': 400, 'y': 300}, {'t': 31.0, 'x': 450, 'y': 320}, {'t': 70.0, 'x': 1500, 'y': 800}],
           'typing': [[31.5, 33.0]]}
    plan = B.plan_camera_inputs(tl, inp, 1.6)
    zs = [k['z'] for k in plan['keys']]
    assert max(zs) <= 1.6 + 1e-6 and max(zs) >= 1.25 and plan['source'] == 'inputs'
    assert plan['keys'][1]['f'] < (30.0 - 20.0) * 30                     # starts moving before the click
    cx, cy, z = B.camera_curve(plan)
    assert len(z) == plan['n_frames'] and z.max() <= 1.6 + 1e-6
    frame = np.zeros((1080, 1920, 3), np.uint8)
    B.draw_ripple(frame, 960, 540, 0.3, (255, 0, 255))
    assert frame.max() > 0
    ok('stage geometry, PiP spot, click-driven zoom plan, ripple')


# ------------------------------------------------------------------ input log alignment (synthetic)
def test_inputs_alignment():
    import inputs as I
    d = tempfile.mkdtemp(prefix='ev2-pro-')
    try:
        os.makedirs(os.path.join(d, 'assets', 'media'))
        os.makedirs(os.path.join(d, 'work'))
        # a white "cursor" square moving in a known path on a dark desktop, 12 s at 30 fps
        expr_x = '200+120*t+60*sin(3*t)'
        expr_y = '300+40*t+50*cos(2*t)'
        ff('-f', 'lavfi', '-i', 'color=c=0x181820:size=1920x1080:rate=30:duration=12',
           '-f', 'lavfi', '-i', 'color=c=white:size=18x18:rate=30:duration=12',
           '-filter_complex', f"[0:v][1:v]overlay=x='{expr_x}':y='{expr_y}'",
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', os.path.join(d, 'assets', 'media', 'cam_raw.mp4'))
        json.dump({'width': 1920, 'height': 1080}, open(os.path.join(d, 'work', 'omarchy.json'), 'w'))
        T0, true_off = 1_000_000.0, 0.6       # the log clock's video t=0 is 0.6 s after what the recorder start suggests
        ts = np.arange(0, 12, 1 / 60)
        cur = [[T0 + true_off + t, 200 + 120 * t + 60 * np.sin(3 * t) + 9, 300 + 40 * t + 50 * np.cos(2 * t) + 9] for t in ts]
        log = {'started_wall': T0, 'video_seen_wall': T0, 'monitors': [{'name': 'X', 'x': 0, 'y': 0, 'width': 1920, 'height': 1080, 'scale': 1.0, 'focused': True}],
               'target': {'monitor': 'X'}, 'cursor': cur, 'clicks': [[T0 + true_off + 5.0, 'left']], 'keys': [], 'combos': [[T0 + true_off + 7, ['Ctrl', 'S']]],
               'input_devices': 2}
        lp = os.path.join(d, 'log.json')
        json.dump(log, open(lp, 'w'))
        out = I.convert(d, lp)
        got = out['offset_wall'] - T0
        assert abs(got - true_off) <= 0.11, (got, out['align'])
        c = out['clicks'][0]
        assert abs(c['t'] - 5.0) < 0.15 and abs(c['x'] - (200 + 600 + 60 * np.sin(15) + 9)) < 25, c
        assert out['keys'][0]['combo'] == ['Ctrl', 'S']
        ok(f'input log aligned to the video by cursor motion (offset {got:.2f}s, true {true_off}s)')
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------ beauty
def test_beauty_detects_bad_hook():
    import beauty
    d = tempfile.mkdtemp(prefix='ev2-beauty-')
    try:
        os.makedirs(os.path.join(d, 'out'))
        os.makedirs(os.path.join(d, 'work'))
        # 2 s of a busy picture, then 3 s black, then a frozen 5 s still
        ff('-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30:duration=2', '-f', 'lavfi', '-i', 'color=c=black:size=1920x1080:rate=30:duration=3',
           '-f', 'lavfi', '-i', 'testsrc=size=1920x1080:rate=30:duration=1',
           '-filter_complex', '[2:v]loop=loop=150:size=1:start=0,setpts=N/30/TB,trim=duration=5[s];[0:v][1:v][s]concat=n=3:v=1[v]',
           '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', os.path.join(d, 'out', 'hook.mp4'))
        tl = dict(base_tl(), hook_split=10.0, segments=[{'src_start': 10.0, 'src_end': 40.0}])
        json.dump(tl, open(os.path.join(d, 'work', 'timeline.json'), 'w'))
        open(os.path.join(d, 'out', 'youtube-description.md'), 'w').write('Great video.\n- stills: assets/img/a.png (Creator Original)\n')
        res = {w: (l, det) for l, w, det in beauty.run(d)}
        assert res['hook: dead air'][0] == 'FAIL', res['hook: dead air']
        assert res['hook: motion'][0] == 'FAIL', res['hook: motion']
        assert res['text: description'][0] == 'FAIL', res['text: description']
        ok('beauty check catches black frames, a frozen hook and leaked notes')
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    tests = [test_theme_and_text, test_icons, test_backdrop_and_accent, test_paint_out, test_recipe_validation,
             test_recipe_builds, test_timeline_fields, test_hook_config_and_geometry, test_stage_and_zoom,
             test_inputs_alignment, test_beauty_detects_bad_hook]
    for t in tests:
        t()
    print(f'\ntest_pro: {len(PASSED)}/{len(tests)} passed')
