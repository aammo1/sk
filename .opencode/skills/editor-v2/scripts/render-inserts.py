#!/usr/bin/env python3
"""render-inserts.py: build (inserts.py) and render the explainer inserts with HyperFrames.

  render-inserts.py <video-dir> [--final] [--only NAME[,NAME]] [--force]
"""
import argparse, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ev2_timeline as TL

HF = ['npx', '-y', 'hyperframes@' + os.environ.get('HF_VERSION', '0.8.181')]


def frames_of(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0',
                        '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', path],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip().split(',')[0])
    except ValueError:
        return -1


def pix_fmt(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=pix_fmt', '-of', 'csv=p=0', path], capture_output=True, text=True)
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--only', default='')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()

    vd = os.path.abspath(a.dir)
    os.chdir(vd)
    try:
        ins_list = TL.insert_ranges(TL.load(vd))
    except TL.TimelineError as e:
        print(f'inserts: ERROR {e}')
        return 1
    if not ins_list:
        print('inserts: no inserts in work/timeline.json (add {"name","src_t","dur","mode"} entries)')
        return 0
    raw = {e['name']: e for e in TL.load(vd).get('inserts') or []}
    all_recipes = all(raw.get(i['name'], {}).get('recipe') for i in ins_list)
    if not os.path.exists('inserts.py') and not all_recipes:
        shutil.copy(os.path.join(SK, 'template', 'inserts.py'), 'inserts.py')
        print('inserts: some inserts have no "recipe": created inserts.py from the template. Prefer a recipe '
              '(flow, steps, checklist, compare, stat, statement, screens) in work/timeline.json; '
              'write an @scene only for something no recipe can show')
        return 1

    old = {}
    for i in ins_list:
        h = f'insert-{i["name"]}.html'
        if os.path.exists(h):
            old[h] = (open(h, 'rb').read(), os.path.getmtime(h))
    env = dict(os.environ)
    env['FINAL'] = '1' if a.final else ''
    if a.only:
        env['EV2_ONLY'] = a.only
    py = os.environ.get('EV2_PY') or sys.executable
    if os.path.exists('inserts.py'):
        r = subprocess.run([py, 'inserts.py'], env=env)
    else:
        env['PYTHONPATH'] = os.path.join(SK, 'components') + os.pathsep + env.get('PYTHONPATH', '')
        r = subprocess.run([py, os.path.join(SK, 'components', 'ev2_inserts.py')], env=env)
    if r.returncode:
        print('inserts: build failed')
        return r.returncode

    only = {x for x in a.only.split(',') if x}
    sel = [i for i in ins_list if not only or i['name'] in only]
    unknown = only - {i['name'] for i in ins_list}
    if unknown:
        print('inserts: ERROR --only names not in timeline: ' + ', '.join(sorted(unknown)))
        return 1

    if os.path.exists('inserts.py') and not all_recipes:
        lint = subprocess.run([py, os.path.join(HERE, 'hf_lint.py'), '.'], capture_output=True, text=True)
        if lint.returncode:
            print('inserts: hf lint failed')
            print('\n'.join((lint.stdout + lint.stderr).strip().splitlines()[-30:]))
            return 1

    os.makedirs('work/inserts', exist_ok=True)
    done = fresh = 0
    for ins in sel:
        name, n, mode = ins['name'], ins['n'], ins['mode']
        html = f'insert-{name}.html'
        out = TL.insert_render_path(vd, ins)
        rel = os.path.relpath(out, vd)
        if html in old and open(html, 'rb').read() == old[html][0]:
            os.utime(html, (old[html][1], old[html][1]))
        html_t = os.path.getmtime(html)
        if (not a.force and os.path.exists(out) and os.path.getmtime(out) > html_t
                and frames_of(out) == n):
            print(f'inserts: {name} up to date')
            fresh += 1
            continue
        if mode == 'full':
            cmd = HF + ['render', '.', '-c', html, '-q', 'standard', '-f', '30', '-o', out]
        else:
            cmd = HF + ['render', '.', '-c', html, '--format', 'mov', '-f', '30', '-o', out]
        if subprocess.run(cmd).returncode or not os.path.exists(out):
            print(f'inserts: {name} render failed')
            return 1
        got = frames_of(out)
        if got != n:
            print(f'inserts: {name} rendered {got} frames, expected {n}')
            return 1
        if mode == 'over' and not re.search(r'yuva|rgba|bgra|argb|abgr|gbrap|^ya', pix_fmt(out)):
            print(f'inserts: WARNING {name}.mov has no alpha channel: check the page is transparent')
        print(f'inserts: {name} -> {rel} ({n} frames, {mode})')
        done += 1
    print(f'inserts: {done} rendered, {fresh} up to date. Next: ev2 finish {a.dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
