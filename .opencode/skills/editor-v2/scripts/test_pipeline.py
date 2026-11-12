#!/usr/bin/env python3
"""test_pipeline.py — end-to-end test of the Editor V2 assembly path on a synthetic recording.

    test_pipeline.py [--keep] [--editor both]

Builds a 75 s fake recording (test pattern + noise bursts separated by pauses), a fake
transcript (one word per burst) and a fake hook render, then runs:
    new-video.sh -> snap-onsets.py -> clean-retakes.py -> finish.py (both editors) -> verify.py
and asserts: verify says DONE; final.mp4 = hook + cleaned body; the voice lands where the
timeline says; the Concat project opens headless; Kdenlive V1 == A1.
Then the failure paths: a stale timeline must FAIL verify, a hook render of the wrong
length must make finish exit non-zero. No HyperFrames / Whisper / network needed.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
PY = os.environ.get('EV2_PY') or os.path.expanduser('~/.cache/editor-v2/venv/bin/python')
if not os.path.isfile(PY):
    PY = sys.executable
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

PERIOD, ON = 2.3, 1.5   # a 1.5 s "word burst" every 2.3 s -> 0.8 s pauses (> 0.6 s: shortened)


def sh(cmd, ok=True, **kw):
    print('  $', ' '.join(str(c) for c in cmd)[:160], flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if ok and r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit(f'FAILED: {cmd[0:3]}')
    return r


def check(cond, msg):
    print(f'  {"ok  " if cond else "FAIL"} {msg}')
    if not cond:
        raise SystemExit(f'FAILED: {msg}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--editor', default='both')
    a = ap.parse_args()

    base = os.path.join(os.path.expanduser('~/.cache/editor-v2'), 'test')
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix='ev2-test-', dir=base)
    print(f'test_pipeline: {root}')
    rec = os.path.join(root, 'rec.mp4')
    dur = 75.0
    # a static "desktop" with a small panel that changes only while speaking (like typing)
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'color=c=0x202830:size=1918x1028:rate=60:duration={dur},drawgrid=w=120:h=90:t=2:c=0x3a4450',
        '-f', 'lavfi', '-i', f'testsrc2=size=360x200:rate=60:duration={dur}',
        '-f', 'lavfi', '-i', f'anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration={dur}:seed=7',
        '-filter_complex', f"[0:v][1:v]overlay=420:300:enable='lt(mod(t,{PERIOD}),{ON})'[v];"
                           f"[2:a]volume='if(lt(mod(t,{PERIOD}),{ON}),1,0)':eval=frame[a]",
        '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', rec])

    print('\n[1] init')
    sh(['bash', os.path.join(HERE, 'new-video.sh'), rec, 'vid', '--dir', root])
    vd = os.path.join(root, 'vid')

    print('\n[2] fake transcript, snap, clean')
    words, t, k = [], 0.0, 0
    RT = 10                      # bursts 10/11: an aborted phrase, then the full restart (a retake)
    while t + ON < dur:
        if k == RT:
            words += [{'w': 'كنقولو', 's': round(t + 0.05, 3), 'e': round(t + 0.70, 3)},
                      {'w': 'بلي', 's': round(t + 0.75, 3), 'e': round(t + ON - 0.05, 3)}]
        elif k == RT + 1:
            words += [{'w': 'كنقولو', 's': round(t + 0.05, 3), 'e': round(t + 0.60, 3)},
                      {'w': 'بلي', 's': round(t + 0.65, 3), 'e': round(t + 1.05, 3)},
                      {'w': 'هادشي', 's': round(t + 1.10, 3), 'e': round(t + ON - 0.05, 3)}]
        else:
            words.append({'w': 'كلمة', 's': round(t + 0.05, 3), 'e': round(t + ON - 0.05, 3)})
        t += PERIOD
        k += 1
    json.dump(words, open(os.path.join(vd, 'work/tx/words.json'), 'w'), ensure_ascii=False)
    sh([PY, os.path.join(HERE, 'snap-onsets.py'), vd])

    r = sh([PY, os.path.join(HERE, 'transcribe.py'), vd], ok=False)
    check(r.returncode != 0 and 'hand corrections' in (r.stdout + r.stderr),
          'transcribe refuses to overwrite an unstamped (possibly hand-corrected) words.json')

    dropped_t = RT * PERIOD + 0.9          # inside the aborted first attempt
    kept = lambda tl_, x: any(s['src_start'] <= x < s['src_end'] for s in tl_['segments'])
    sh([PY, os.path.join(HERE, 'clean-retakes.py'), vd, '--hook-split', '10', '--retakes'])
    cuts = json.load(open(os.path.join(vd, 'work/cuts.json')))
    check(len(cuts['retakes_detected']) == 1, f'one retake candidate detected ({len(cuts["retakes_detected"])})')
    check(not kept(TL.load(vd), dropped_t), 'an enabled retake right after a long pause IS cut (no sliver drop)')
    cuts['retakes_detected'][0]['enabled'] = False
    json.dump(cuts, open(os.path.join(vd, 'work/cuts.json'), 'w'), ensure_ascii=False)
    sh([PY, os.path.join(HERE, 'clean-retakes.py'), vd])
    check(kept(TL.load(vd), dropped_t), 'disabling the retake in cuts.json keeps it (choice survives re-clean)')
    tl = TL.load(vd)
    hs = tl['hook_split']
    check(abs(hs - 10) <= 2.0 and abs(hs * 30 - round(hs * 30)) < 1e-6, f'hook split snapped to a pause on the frame grid ({hs})')
    check(len(tl['segments']) > 20, f'{len(tl["segments"])} body segments after silence trimming')
    check(tl['segments'][0]['src_start'] >= hs, 'body starts at/after the hook split')
    tl['chapters'] = [{'src_t': 14, 'title': 'Setup'}, {'src_t': 35, 'title': 'Core'}, {'src_t': 58, 'title': 'Demo'}]
    TL.save(vd, tl)

    print('\n[3] fake hook render')
    def render(seconds):
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            f'color=c=0x223344:size=1920x1080:rate=30:duration={seconds:.6f}', '-c:v', 'libx264',
            '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', os.path.join(vd, 'out/render.mp4')])
    render(hs)
    if os.path.exists(os.path.join(vd, 'index.html')):
        os.remove(os.path.join(vd, 'index.html'))
    open(os.path.join(vd, 'sfx-cues.txt'), 'w').write('0.500  ev1kit/click_3  0.42\n2.000  ev1kit/impact_1  0.24\n')
    json.dump({'placeholders': [], 'missing': [], 'final': True}, open(os.path.join(vd, 'work/build.json'), 'w'))
    json.dump([{'time': 0, 'title': 'Hook'}], open(os.path.join(vd, 'work/hook_chapters.json'), 'w'))

    print('\n[4] finish')
    r = subprocess.run([PY, os.path.join(HERE, 'finish.py'), vd, '--editor', a.editor, '--no-open', '--preset', 'ultrafast'],
                       capture_output=True, text=True)
    print(r.stdout[-2500:], r.stderr[-1500:])
    check(r.returncode == 0, 'finish exits 0')
    v = json.load(open(os.path.join(vd, 'out/verify.json')))
    check(v['verdict'].startswith('DONE'), f'verify verdict: {v["verdict"]}')
    passed = {x['check'] for x in v['results'] if x['level'] == 'PASS'}
    for need in ['final.mp4 length', 'A/V length', 'voice sync', 'picture sync', 'hook.mp4', 'hook build', 'short.mp4',
                 'YouTube chapters', 'body polish', 'captions.srt', 'loudness']:
        check(need in passed, f'verify PASS: {need}')
    if a.editor in ('both', 'concat'):
        check('Concat project' in passed, 'verify PASS: Concat project')
    if a.editor in ('both', 'kdenlive'):
        check('Kdenlive project' in passed, 'verify PASS: Kdenlive project')
    zp = json.load(open(os.path.join(vd, 'work/zoom_plan.json')))
    check(zp['zoomed_share'] > 0.2, f'auto zoom engaged on the active panel ({zp["zoomed_share"] * 100:.0f}% zoomed)')
    zk = [k for k in zp['keys'] if k['z'] > 1.2]
    check(bool(zk) and all(300 < k['cx'] < 1000 and 200 < k['cy'] < 700 for k in zk),
          f'zooms aim at the panel (centers {[(round(k["cx"]), round(k["cy"])) for k in zk[:3]]})')
    chapters = open(os.path.join(vd, 'out/youtube-chapters.txt')).read().split('\n')
    check(chapters[0].startswith('00:00') and len([c for c in chapters if c]) == 4, f'chapters: {chapters[:4]}')

    print('\n[5] failure paths')
    verify = lambda: subprocess.run([PY, os.path.join(HERE, 'verify.py'), vd], capture_output=True, text=True)
    bj = os.path.join(vd, 'work/build.json')
    json.dump({'placeholders': [], 'missing': [], 'final': False}, open(bj, 'w'))
    r = verify()
    check(r.returncode == 1 and 'FAIL  hook build' in r.stdout, 'verify FAILs when the hook was not built with --final')
    json.dump({'placeholders': [], 'missing': [], 'final': True}, open(bj, 'w'))

    tl = TL.load(vd)
    tl['chapters'][0]['title'] = 'Setup (renamed)'
    TL.save(vd, tl)
    r = verify()
    check(r.returncode == 1 and 'stale chapters' in r.stdout, 'verify FAILs when chapters changed after finish')
    tl['chapters'][0]['title'] = 'Setup'
    TL.save(vd, tl)

    fin = os.path.join(vd, 'out/final.mp4')
    good = os.path.join(vd, 'out/final_good.mp4')
    shutil.copyfile(fin, good)
    n_frames = TL.frames(hs) + round(TL.body_duration(TL.load(vd)) * 30)
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', good, '-map', '0:v', '-map', '0:a', '-c:a', 'copy',
        '-vf', f'tpad=start=3:start_mode=clone,trim=end_frame={n_frames}', '-c:v', 'libx264', '-preset', 'ultrafast', fin])
    r = verify()
    check(r.returncode == 1 and 'FAIL  picture sync' in r.stdout and '+3 frames' in r.stdout,
          'verify FAILs when the picture is 3 frames late (voice still in place)')
    os.replace(good, fin)

    bad = os.path.join(vd, 'out/final_desync.mp4')
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', fin, '-map', '0:v', '-map', '0:a', '-c:v', 'copy',
        '-af', 'adelay=100:all=1,atrim=end=' + str(TL.frames(hs) / 30 + TL.body_duration(TL.load(vd))),
        '-c:a', 'aac', bad])
    os.replace(bad, fin)
    r = subprocess.run([PY, os.path.join(HERE, 'verify.py'), vd], capture_output=True, text=True)
    check(r.returncode == 1 and 'FAIL  voice sync' in r.stdout, 'verify FAILs when the voice is 100 ms late')
    tl = TL.load(vd)
    tl['segments'] = tl['segments'][:-1]
    TL.save(vd, tl)
    r = subprocess.run([PY, os.path.join(HERE, 'verify.py'), vd], capture_output=True, text=True)
    check(r.returncode == 1 and 'stale' in r.stdout, 'verify FAILs when timeline.json changed after finish')
    render(hs + 1.0)
    r = subprocess.run([PY, os.path.join(HERE, 'finish.py'), vd, '--editor', 'none', '--no-open', '--preset', 'ultrafast', '--raw-body'],
                       capture_output=True, text=True)
    check(r.returncode == 1 and 'hook render is' in r.stderr, 'finish refuses a hook render of the wrong length')

    print('\n[5] optional body music')
    import soundfile as sf
    render(hs)
    fin_cmd = [PY, os.path.join(HERE, 'finish.py'), vd, '--editor', 'none', '--no-open', '--preset', 'ultrafast', '--raw-body', '--no-short']
    subprocess.run(fin_cmd, capture_output=True, text=True)
    check(not os.path.exists(os.path.join(vd, 'work/body_music.wav')), 'body music is OFF by default')
    r = subprocess.run(fin_cmd + ['--body-music'], capture_output=True, text=True)
    bm, bv = os.path.join(vd, 'work/body_music.wav'), os.path.join(vd, 'work/body_voice.wav')
    check(os.path.exists(bm) and 'quiet music under the whole body' in r.stdout, '--body-music writes work/body_music.wav')
    check(sf.info(bm).frames == sf.info(bv).frames, 'body music keeps the body audio length exactly')
    check(json.load(open(os.path.join(vd, 'work/finish.json')))['body_music'] is True, 'finish.json records body_music')
    tl = TL.load(vd); tl['body_music'] = True; TL.save(vd, tl)
    subprocess.run(fin_cmd, capture_output=True, text=True)
    check(os.path.exists(bm), 'timeline "body_music": true turns it on without the flag')
    subprocess.run(fin_cmd + ['--no-body-music'], capture_output=True, text=True)
    check(not os.path.exists(bm), '--no-body-music forces it off and removes the stale file')
    tl['body_music'] = 'yes'
    try:
        TL.save(vd, tl); check(False, 'non-boolean body_music is rejected')
    except TL.TimelineError:
        check(True, 'non-boolean body_music is rejected')

    print('\n[6] key pills')
    wp = os.path.join(vd, 'work/tx/words.json')
    tlp = os.path.join(vd, 'work/timeline.json')
    words_bak = open(wp, 'rb').read()
    tl_bytes = open(tlp, 'rb').read()
    said = 15 * PERIOD + ON + 0.05         # inside the pause after burst 15
    ws = json.loads(words_bak) + [{'w': 'سوبر', 's': round(said, 3), 'e': round(said + 0.25, 3)},
                                  {'w': 'سبيس', 's': round(said + 0.3, 3), 'e': round(said + 0.55, 3)}]
    ws.sort(key=lambda x: x['s'])
    json.dump(ws, open(wp, 'w'), ensure_ascii=False)
    sh([PY, os.path.join(HERE, 'keys-suggest.py'), vd])
    sg = json.load(open(os.path.join(vd, 'work/keys-suggest.json')))['suggestions']
    check(any(s['keys'] == 'Super + Space' and abs(s['src_t'] - said) < 0.5 for s in sg),
          f'keys-suggest finds "سوبر سبيس" -> Super + Space near {said:.2f} ({[(s["keys"], s["src_t"]) for s in sg]})')
    check(open(tlp, 'rb').read() == tl_bytes, 'keys-suggest leaves work/timeline.json untouched')
    open(wp, 'wb').write(words_bak)

    probe = lambda p: float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
                                           capture_output=True, text=True).stdout.strip())
    dur_before = probe(fin)
    tl = TL.load(vd)
    tl['keys'] = [{'src_t': 17 * PERIOD + 0.3, 'keys': 'Super + Space', 'label': 'test'}]
    TL.save(vd, tl)
    r = subprocess.run(fin_cmd + ['--no-keys'], capture_output=True, text=True)
    check(r.returncode == 0, 'finish --no-keys --raw-body exits 0')
    check(json.load(open(os.path.join(vd, 'work/finish.json'))).get('keys_drawn') is False, '--no-keys: keys_drawn false')
    check('WARN  key pills' in r.stdout, 'verify WARNs when pills are listed but not drawn')

    poly_cmd = [PY, os.path.join(HERE, 'finish.py'), vd, '--editor', 'none', '--no-open', '--preset', 'ultrafast', '--no-short']
    r = subprocess.run(poly_cmd, capture_output=True, text=True)
    print(r.stdout[-1200:], r.stderr[-1200:])
    check(r.returncode == 0, 'finish with one key pill exits 0')
    fj = json.load(open(os.path.join(vd, 'work/finish.json')))
    check(fj.get('key_pills') == 1 and fj.get('keys_drawn') is True, f'finish.json: key_pills 1, keys_drawn ({fj.get("key_pills")}, {fj.get("keys_drawn")})')
    check('key_click' in open(os.path.join(vd, 'work/body_cues.txt')).read(), 'body_cues.txt has the key click')
    check(json.load(open(os.path.join(vd, 'work/body_video.json'))).get('pills') == 1, 'body_video.json records 1 pill drawn')
    dur_after = probe(fin)
    check(abs(dur_after - dur_before) < 0.05, f'final.mp4 length unchanged by the pill ({dur_before:.3f} -> {dur_after:.3f} s)')
    check('PASS  key pills' in r.stdout, 'verify PASS: key pills')
    v0 = json.load(open(os.path.join(vd, 'out/verify.json')))['verdict']

    tl = TL.load(vd)
    tl['keys'][0]['dur'] = 2.0
    TL.save(vd, tl)
    r = verify()
    check(r.returncode == 1 and 'FAIL  stale keys' in r.stdout, 'verify FAILs stale keys when a pill changed after finish')
    del tl['keys'][0]['dur']
    TL.save(vd, tl)

    print('\n[7] description')
    describe = lambda *x: subprocess.run([PY, os.path.join(HERE, 'describe.py'), vd, *x], capture_output=True, text=True)
    dp = os.path.join(vd, 'out/youtube-description.md')
    r = describe('--lang', 'en')
    check(r.returncode == 0 and os.path.isfile(dp), f'describe writes out/youtube-description.md ({r.stdout.strip()[-200:]})')
    text = open(dp, encoding='utf-8').read()
    ch_lines = [l.rstrip() for l in open(os.path.join(vd, 'out/youtube-chapters.txt'), encoding='utf-8') if l.strip()]
    check(all(l in text.splitlines() for l in ch_lines), 'description contains the exact chapter lines')
    check(describe('--check').returncode == 1, 'describe --check exits 1 while WRITE slots remain')
    r = verify()
    check(any(l.strip().startswith(('WARN  description', 'PASS  description')) for l in r.stdout.splitlines()),
          'verify reports a description line')
    check(json.load(open(os.path.join(vd, 'out/verify.json')))['verdict'].startswith('DONE') == v0.startswith('DONE'),
          'open description slots do not change DONE / NOT DONE')
    import re
    open(dp, 'w', encoding='utf-8').write(re.sub(r'<!-- WRITE.*?-->', 'A sentence written by hand.', text, flags=re.S))
    r = describe('--check')
    check(r.returncode == 0, f'describe --check exits 0 once the slots are filled ({r.stdout.strip()[-200:]})')
    r = verify()
    check('PASS  description' in r.stdout, 'verify PASS: description')
    check(json.load(open(os.path.join(vd, 'out/verify.json')))['verdict'] == v0, f'verify verdict unaffected ({v0})')
    r = describe()
    check(r.returncode == 1 and 'edited' in r.stdout, 'describe refuses to overwrite a hand-edited description')
    check(describe('--force').returncode == 0, 'describe --force regenerates it')
    tl = TL.load(vd)
    tl.pop('keys', None)
    TL.save(vd, tl)

    print('\n[8] calm style')
    vc = os.path.join(root, 'vid_calm')
    shutil.copytree(vd, vc, symlinks=True)
    tpl, tpl_calm = os.path.join(SK, 'template/build.py'), os.path.join(SK, 'template/build_calm.py')
    same = lambda p, q: open(p, 'rb').read() == open(q, 'rb').read()
    style = lambda d: json.load(open(os.path.join(d, 'kit.json'))).get('style')
    sh(['bash', os.path.join(HERE, 'set-style.sh'), vc, 'calm'])
    check(same(os.path.join(vc, 'build.py'), tpl_calm) and style(vc) == 'calm', 'set-style calm: calm build.py, kit.json style calm')
    for f in ['index.html', 'work/build.json']:
        if os.path.exists(os.path.join(vc, f)):
            os.remove(os.path.join(vc, f))
    r = subprocess.run([PY, 'build.py'], cwd=vc, capture_output=True, text=True)
    print(r.stdout[-600:], r.stderr[-600:])
    check(r.returncode == 0, 'calm build.py exits 0')
    bjc = os.path.join(vc, 'work/build.json')
    check(os.path.isfile(os.path.join(vc, 'index.html')) and os.path.isfile(bjc), 'calm build.py writes index.html and work/build.json')
    check(bool(json.load(open(bjc))['placeholders']), 'calm build.json lists the template placeholders')
    r = subprocess.run([PY, 'build.py'], cwd=vc, capture_output=True, text=True, env=dict(os.environ, FINAL='1'))
    check(r.returncode != 0, 'calm FINAL=1 refuses while examples remain')
    open(os.path.join(vc, 'build.py'), 'a').write('\n# hand edit\n')
    sh(['bash', os.path.join(HERE, 'set-style.sh'), vc, 'documentary'])
    import glob
    check(bool(glob.glob(os.path.join(vc, 'build.py.bak-*'))), 'set-style backs up a hand-edited build.py')
    check(same(os.path.join(vc, 'build.py'), tpl) and style(vc) == 'documentary', 'set-style documentary: template build.py back')
    sh(['bash', os.path.join(HERE, 'new-video.sh'), rec, 'vid_calm_init', '--dir', root, '--style', 'calm'])
    vi = os.path.join(root, 'vid_calm_init')
    check(style(vi) == 'calm' and same(os.path.join(vi, 'build.py'), tpl_calm), 'new-video.sh --style calm: calm build.py and kit.json style')
    check(style(vd) == 'documentary' and same(os.path.join(vd, 'build.py'), tpl), 'default video stays documentary')

    print('\ntest_pipeline: ALL PASSED')
    if not a.keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f'kept: {root}')


if __name__ == '__main__':
    main()
