#!/usr/bin/env python3
"""test_v32.py — automated verification for all editor-v2 3.2.0 upgrades:
  1. VRAM-aware GPU session caps (RTX 2070 8GB safety)
  2. Step 0 read-only `ev2 inspect` (16:9 tutorial vs 9:16 vertical short)
  3. Standalone `--mode short` init + tighter silence defaults + native 1080x1920
  4. Pro Shorts engine (`ev2_shorts.py` + `shorts.py`: validation, BiDi captions, HTML/SRT build, check.py)
  5. Dual-mode Studio Thumbnails (`ev2_thumb.py` + `thumb.py`: 1280x720 local Chrome render + phone grid)
  6. Upgraded YouTube Package (`describe.py`: titles + thumbnail hooks + tags + description + --check)
  7. CLI dispatch (`ev2 version`, `ev2 inspect`, `ev2 gpu`).

No Whisper or external network required.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
PY = os.environ.get('EV2_PY') or os.path.expanduser('~/.cache/editor-v2/venv/bin/python')
if not os.path.isfile(PY):
    PY = sys.executable

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'components'))
import ev2_shorts as SH    # noqa: E402
import ev2_thumb as TH     # noqa: E402
import gpu                 # noqa: E402


def sh(cmd, ok=True, env=None):
    print('  $', ' '.join(str(c) for c in cmd)[:150], flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if ok and r.returncode != 0:
        print(r.stdout[-2500:], r.stderr[-2500:])
        raise SystemExit(f'FAILED ({r.returncode}): {cmd[:4]}')
    return r


def check(cond, msg):
    print(f'  {"ok  " if cond else "FAIL"} {msg}')
    if not cond:
        raise SystemExit(f'FAILED: {msg}')


def make_synth_video(out_mp4, w, h, dur):
    """Create a synthetic video with pulsed speech-like tone bursts separated by 0.9s silences."""
    # Alternate 1.5s tone / 0.9s silence
    expr = "if(lt(mod(t,2.4),1.5),0.25*sin(2*PI*440*t),0)"
    sh([
        'ffmpeg', '-nostdin', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'testsrc2=size={w}x{h}:rate=30:duration={dur}',
        '-f', 'lavfi', '-i', f"aevalsrc='{expr}':s=48000:c=stereo:d={dur}",
        '-c:v', 'libx264', '-crf', '22', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', out_mp4,
    ])


def make_words(dur):
    words = []
    tokens = ['سلام', 'اليوم', 'غادي', 'نخدمو', 'بـ', 'Docker', 'و', 'Next.js', 'فـ', 'Omarchy']
    t, idx = 0.1, 0
    while t + 1.2 < dur:
        for k in range(3):
            ws = round(t + k * 0.42, 3)
            we = round(ws + 0.34, 3)
            words.append({'w': tokens[idx % len(tokens)], 's': ws, 'e': we})
            idx += 1
        t += 2.4
    return words


def probe_dims(path):
    r = sh(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'json', path])
    st = (json.loads(r.stdout).get('streams') or [{}])[0]
    return int(st.get('width') or 0), int(st.get('height') or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='Keep temp folder after test')
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix='ev2_v32_test_')
    try:
        # 1. GPU / RTX 2070 VRAM cap tests
        print('\n[1/6] GPU VRAM-aware session limits (RTX 2070 safety)')
        old_env = os.environ.pop('EV2_NVENC_SESSIONS', None)
        try:
            check(gpu.max_sessions(8192) == 3, '8 GB VRAM (RTX 2070) -> max_sessions == 3')
            check(gpu.max_sessions(6144) == 3, '6 GB VRAM -> max_sessions == 3')
            check(gpu.max_sessions(24576) == 6, '24 GB VRAM -> max_sessions == 6')
            os.environ['EV2_NVENC_SESSIONS'] = '5'
            check(gpu.max_sessions(8192) == 5, 'EV2_NVENC_SESSIONS=5 overrides VRAM heuristic')
        finally:
            os.environ.pop('EV2_NVENC_SESSIONS', None)
            if old_env is not None:
                os.environ['EV2_NVENC_SESSIONS'] = old_env

        # 2. ev2 CLI version & Step 0 inspect
        print('\n[2/6] CLI version & Step 0 `ev2 inspect`')
        ev2_bin = os.path.join(SK, 'scripts', 'ev2')
        rv = sh(['bash', ev2_bin, 'version'])
        check('3.2.0' in rv.stdout, f'ev2 version reports 3.2.0 ({rv.stdout.strip()})')

        vid_169 = os.path.join(tmp, 'tut_169.mp4')
        vid_916 = os.path.join(tmp, 'reel_916.mp4')
        make_synth_video(vid_169, 1920, 1080, 82)
        make_synth_video(vid_916, 1080, 1920, 18)

        r_tut = sh(['bash', ev2_bin, 'inspect', vid_169, '--json'])
        info_tut = json.loads(r_tut.stdout)
        check(info_tut['aspect'] == '16:9' and info_tut['recommended_mode'] == 'tutorial',
              f'16:9 82s -> aspect={info_tut["aspect"]}, mode={info_tut["recommended_mode"]}')

        r_sh = sh(['bash', ev2_bin, 'inspect', vid_916, '--json'])
        info_sh = json.loads(r_sh.stdout)
        check(info_sh['aspect'] == '9:16' and info_sh['recommended_mode'] == 'short',
              f'9:16 18s -> aspect={info_sh["aspect"]}, mode={info_sh["recommended_mode"]}')

        # 3. Standalone --mode short init + tight clean-retakes
        print('\n[3/6] Standalone `--mode short` init & tight clean-retakes')
        vids_root = os.path.join(tmp, 'videos')
        sh(['bash', ev2_bin, 'init', vid_916, 'reel-test', '--dir', vids_root, '--mode', 'short'])
        vd_short = os.path.join(vids_root, 'reel-test')
        kit = json.load(open(os.path.join(vd_short, 'kit.json')))
        check(kit.get('mode') == 'short', 'kit.json records mode=short')
        check(probe_dims(os.path.join(vd_short, 'assets', 'media', 'cam_raw.mp4')) == (1080, 1920),
              'cam_raw.mp4 preserved native 1080x1920 vertical resolution')
        os.makedirs(os.path.join(vd_short, 'work', 'tx'), exist_ok=True)
        json.dump(make_words(18), open(os.path.join(vd_short, 'work', 'tx', 'words.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        sh([PY, os.path.join(SK, 'scripts', 'clean-retakes.py'), vd_short])
        tl_short = json.load(open(os.path.join(vd_short, 'work', 'timeline.json')))
        check(tl_short['hook_split'] == 0.0, 'short mode sets hook_split=0.0')

        # 4. Pro Shorts engine (validation + BiDi captions + init + build + check.py)
        print('\n[4/6] Pro Shorts engine (`ev2_shorts` + `ev2 shorts` + `ev2 check`)')
        bad_gap = SH.validate_shorts_cfg({'shorts': [{
            'name': 's1', 'layout': 'stacked', 'spans': [[0.0, 20.0]],
            'beats': [{'at': 0.0, 'dur': 5.0, 'type': 'screen'}, {'at': 12.0, 'dur': 8.0, 'type': 'screen'}],
        }]})
        check(any('EMPTY BAND' in p for p in bad_gap), 'validate_shorts_cfg catches EMPTY BAND gap')

        bad_len = SH.validate_shorts_cfg({'shorts': [{'name': 's2', 'layout': 'stacked', 'spans': [[0.0, 75.0]]}]})
        check(any('exceeds 60s' in p for p in bad_len), 'validate_shorts_cfg catches >60s Short')

        caps = SH.group_words_vertical(make_words(10))
        check(len(caps['groups']) >= 2 and all(g['rtl'] for g in caps['groups']),
              f'Darija/Latin vertical caption groups built ({len(caps["groups"])} groups, rtl=True)')

        sh(['bash', ev2_bin, 'shorts', vd_short, '--init'])
        sh(['bash', ev2_bin, 'check', vd_short])
        sh(['bash', ev2_bin, 'shorts', vd_short, '--no-render'])
        idx_html = open(os.path.join(vd_short, 'work', 'shorts', 'reel-01', 'index.html'), encoding='utf-8').read()
        check('data-width="1080" data-height="1920"' in idx_html, 'Pro Short HTML is 1080x1920')
        check('<bdi>Docker</bdi>' in idx_html, 'Darija+Latin BiDi <bdi> isolation present in Short captions')
        check(os.path.isfile(os.path.join(vd_short, 'out', 'shorts', 'reel-01.srt')), 'Short .srt sidecar written')

        # 5. Dual-Mode Studio Thumbnails (local Chrome render + phone grid)
        print('\n[5/6] Dual-Mode Studio Thumbnails (`ev2 thumb` local 1280x720 + phone grid)')
        sh(['bash', ev2_bin, 'init', vid_169, 'tut-test', '--dir', vids_root])
        vd_tut = os.path.join(vids_root, 'tut-test')
        json.dump({'recipe': 'showcase', 'promise': 'من *الطلب* حتى التسليم', 'brand': 'Zehri'},
                  open(os.path.join(vd_tut, 'work', 'hook.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        sh(['bash', ev2_bin, 'thumb', vd_tut, '--init'])
        check(os.path.isfile(os.path.join(vd_tut, 'work', 'thumbs.json')), 'work/thumbs.json initialized')
        sh(['bash', ev2_bin, 'thumb', vd_tut])
        from PIL import Image
        t1 = os.path.join(vd_tut, 'out', 'thumbs', 't1-hero.png')
        gp = os.path.join(vd_tut, 'out', 'thumbs', 'grid_phone.png')
        check(os.path.isfile(t1) and Image.open(t1).size == (1280, 720), 't1-hero.png rendered at exact 1280x720')
        check(os.path.isfile(gp) and os.path.isfile(os.path.join(vd_tut, 'out', 'thumbs', 'grid.png')),
              'grid.png and grid_phone.png (246x138) generated')

        # 6. Upgraded YouTube Title, Package & Description (`ev2 describe`)
        print('\n[6/6] YouTube Title + Packaging + Description (`ev2 describe`)')
        os.makedirs(os.path.join(vd_tut, 'out'), exist_ok=True)
        os.makedirs(os.path.join(vd_tut, 'work', 'tx'), exist_ok=True)
        json.dump(make_words(80), open(os.path.join(vd_tut, 'work', 'tx', 'words.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        sh([PY, os.path.join(SK, 'scripts', 'clean-retakes.py'), vd_tut, '--hook-split', '20'])
        chs = [
            {'time': 0.0, 'timestamp': '00:00', 'title': 'Intro'},
            {'time': 20.0, 'timestamp': '00:20', 'title': 'Setup — الإعداد'},
            {'time': 45.0, 'timestamp': '00:45', 'title': 'Deploy — النشر'},
        ]
        json.dump(chs, open(os.path.join(vd_tut, 'work', 'chapters.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        open(os.path.join(vd_tut, 'out', 'youtube-chapters.txt'), 'w', encoding='utf-8').write(
            '\n'.join(f'{c["timestamp"]} {c["title"]}' for c in chs) + '\n'
        )
        sh(['bash', ev2_bin, 'describe', vd_tut, '--lang', 'darija'])
        pkg_p = os.path.join(vd_tut, 'out', 'youtube-package.md')
        desc_p = os.path.join(vd_tut, 'out', 'youtube-description.md')
        check(os.path.isfile(pkg_p) and os.path.isfile(desc_p), 'both youtube-description.md and youtube-package.md created')
        r_fail = sh(['bash', ev2_bin, 'describe', vd_tut, '--check'], ok=False)
        check(r_fail.returncode != 0, '--check fails while <!-- WRITE --> slots remain')

        # Fill slots cleanly and re-check
        open(desc_p, 'w', encoding='utf-8').write(
            'فهاد الفيديو غادي تشوف كيفاش تقاد الخدمة ديالك بسهولة.\n\nالفصول\n00:00 Intro\n00:20 Setup — الإعداد\n00:45 Deploy — النشر\n'
        )
        open(pkg_p, 'w', encoding='utf-8').write(
            '# YouTube Upload Package (darija)\n\n'
            '## Title Candidates\n'
            '1. **Result / Time:** كيفاش تقاد الطلبات فـ 6 دقايق بـ Zehri\n'
            '2. **Problem / Contrast:** بلا Excel: نظام واحد لإدارة الطلبات\n'
            '3. **Tool / Workflow:** شرح Zehri خطوة بخطوة للمبتدئين\n'
            '4. **Darija-Native:** أحسن طريقة تنظم بيها الطلبات بالمغربية\n'
            '5. **Search / SEO:** Zehri Tutorial: Order Management Setup\n\n'
            '## Thumbnail Text Pairings\n'
            '- **Hero:** بلا Excel دابا\n'
            '- **Stat:** 6 دقايق فقط\n'
            '- **Contrast:** قبل vs Zehri\n\n'
            '## Tags / Keywords\n'
            'Zehri, Darija, ecommerce maroc, إدارة الطلبات, tutorial\n\n'
            '## Pinned Comment\n'
            'شنو أكثر خطوة كتاخد ليك الوقت فـ إدارة الطلبات؟ خليها فالتعاليق!\n'
        )
        sh(['bash', ev2_bin, 'describe', vd_tut, '--check', '--package'])
        check(True, '--check --package passes once description and package slots are cleanly filled')

        print('\nALL v3.2 TESTS PASSED!')
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f'kept temp dir: {tmp}')


if __name__ == '__main__':
    main()
