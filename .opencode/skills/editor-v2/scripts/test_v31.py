#!/usr/bin/env python3
"""test_v31.py — tests for every v3.1 feature + v3.0 parity run.

    test_v31.py [--keep] [--skip-gpu]
"""
import argparse
import glob
import json
import os
import re
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
import ev2_pro as P  # noqa: E402
import ev2_timeline as TL  # noqa: E402

os.environ['EV2_NO_BEAUTY'] = '1'

PERIOD, ON = 2.3, 1.5


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


def probe_frames(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0',
         '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', path],
        capture_output=True, text=True,
    )
    val = (r.stdout or '').strip().splitlines()
    return int(val[0].rstrip(',')) if val and val[0].rstrip(',').isdigit() else 0


def probe_video(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'format=duration:stream=width,height', '-of', 'json', path],
        capture_output=True, text=True,
    )
    d = json.loads(r.stdout)
    st = (d.get('streams') or [{}])[0]
    return {
        'duration': float(d.get('format', {}).get('duration') or 0.0),
        'width': int(st.get('width') or 0),
        'height': int(st.get('height') or 0),
    }


def make_fake_words(dur):
    words, t, k = [], 0.0, 0
    rt = 10
    while t + ON < dur:
        if k == rt:
            words += [{'w': 'كنقولو', 's': round(t + 0.05, 3), 'e': round(t + 0.70, 3)},
                      {'w': 'بلي', 's': round(t + 0.75, 3), 'e': round(t + ON - 0.05, 3)}]
        elif k == rt + 1:
            words += [{'w': 'كنقولو', 's': round(t + 0.05, 3), 'e': round(t + 0.60, 3)},
                      {'w': 'بلي', 's': round(t + 0.65, 3), 'e': round(t + 1.05, 3)},
                      {'w': 'هادشي', 's': round(t + 1.10, 3), 'e': round(t + ON - 0.05, 3)}]
        else:
            words.append({'w': 'كلمة', 's': round(t + 0.05, 3), 'e': round(t + ON - 0.05, 3)})
        t += PERIOD
        k += 1
    return words


def load_frame_hashes(prefix):
    hashes = {}
    for p in sorted(glob.glob(f'{prefix}.*')):
        with open(p, encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    hashes[int(parts[0])] = parts[1]
    return hashes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--skip-gpu', action='store_true')
    a = ap.parse_args()

    base = os.path.join(os.path.expanduser('~/.cache/editor-v2'), 'test')
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix='ev2-v31-', dir=base)
    print(f'test_v31: {root}')

    try:
        # 1. gpu helper
        print('\n[1] gpu helper')
        env_off = dict(os.environ, EV2_GPU='0')
        cpu_args = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-g', '60']
        r = sh([PY, os.path.join(HERE, 'gpu.py'), 'status'], env=env_off)
        check('gpu off (EV2_GPU=0)' in r.stdout, f'EV2_GPU=0 status: {r.stdout.strip()}')

        venc_code = (
            f"import json, sys; sys.path.insert(0, {HERE!r}); import gpu; "
            f"print(json.dumps(gpu.venc({cpu_args!r}, 18)))"
        )
        r = sh([PY, '-c', venc_code], env=env_off)
        check(json.loads(r.stdout) == cpu_args, 'EV2_GPU=0 venc returns cpu_args unchanged')

        gpu_present = False
        if not a.skip_gpu:
            r_on = subprocess.run([PY, os.path.join(HERE, 'gpu.py'), 'on'], capture_output=True, text=True)
            gpu_present = (r_on.returncode == 0)
            if gpu_present:
                r = sh([PY, '-c', venc_code])
                nv_args = json.loads(r.stdout)
                check('h264_nvenc' in nv_args and nv_args[-2:] == ['-g', '60'],
                      f'GPU venc uses h264_nvenc and preserves -g 60: {nv_args}')
            else:
                print('  skip GPU-on check (no working GPU/NVENC detected)')
        else:
            print('  skip GPU-on check (--skip-gpu)')

        # 2. camsync measure
        print('\n[2] camsync measure')
        screen = os.path.join(root, 'screen.mp4')
        cam = os.path.join(root, 'cam.mp4')
        cam_neg = os.path.join(root, 'cam_neg.mp4')
        screen_drift = os.path.join(root, 'screen_drift.mp4')
        cam_drift = os.path.join(root, 'cam_drift.mp4')

        dur = 75.0
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y',
            '-f', 'lavfi', '-i', f'testsrc2=size=640x360:rate=30:duration={dur}',
            '-f', 'lavfi', '-i', f'anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration={dur}:seed=7',
            '-af', f"volume='if(lt(mod(t,{PERIOD}),{ON}),1,0)':eval=frame",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', screen])

        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y',
            '-f', 'lavfi', '-i', 'color=c=0x884422:size=640x360:rate=30:duration=80',
            '-f', 'lavfi', '-i', f'anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration={dur}:seed=7',
            '-f', 'lavfi', '-i', 'anoisesrc=color=white:amplitude=0.02:sample_rate=48000:duration=80:seed=19',
            '-filter_complex',
            f"[1:a]volume='if(lt(mod(t,{PERIOD}),{ON}),1,0)':eval=frame,adelay=2345|2345[p];"
            f"[p][2:a]amix=inputs=2:duration=longest:normalize=0,atrim=end=80[a]",
            '-map', '0:v', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', cam])

        r = sh([PY, os.path.join(HERE, 'camsync.py'), 'measure', screen, cam])
        m_pos = json.loads(r.stdout)
        check(m_pos['ok'] and abs(m_pos['offset'] - 2.345) <= 1.0 / 30.0,
              f"camsync positive offset={m_pos['offset']} (expected 2.345, conf={m_pos['confidence']})")

        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y',
            '-f', 'lavfi', '-i', 'color=c=0x884422:size=640x360:rate=30:duration=73.5',
            '-f', 'lavfi', '-i', f'anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration={dur}:seed=7',
            '-f', 'lavfi', '-i', 'anoisesrc=color=white:amplitude=0.02:sample_rate=48000:duration=73.5:seed=23',
            '-filter_complex',
            f"[1:a]volume='if(lt(mod(t,{PERIOD}),{ON}),1,0)':eval=frame,atrim=start=1.5,asetpts=PTS-STARTPTS[p];"
            f"[p][2:a]amix=inputs=2:duration=first:normalize=0[a]",
            '-map', '0:v', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', cam_neg])

        r = sh([PY, os.path.join(HERE, 'camsync.py'), 'measure', screen, cam_neg])
        m_neg = json.loads(r.stdout)
        check(m_neg['ok'] and abs(m_neg['offset'] - (-1.5)) <= 1.0 / 30.0,
              f"camsync negative offset={m_neg['offset']} (expected -1.5, conf={m_neg['confidence']})")

        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y',
            '-f', 'lavfi', '-i', 'color=c=black:size=64x64:rate=10:duration=180',
            '-f', 'lavfi', '-i', 'anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration=180:seed=7',
            '-af', f"volume='if(lt(mod(t,{PERIOD}),{ON}),1,0)':eval=frame",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', screen_drift])

        tempo = 1.0 / 1.0005
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y',
            '-f', 'lavfi', '-i', 'color=c=black:size=64x64:rate=10:duration=180',
            '-f', 'lavfi', '-i', 'anoisesrc=color=pink:amplitude=0.4:sample_rate=48000:duration=180:seed=7',
            '-f', 'lavfi', '-i', 'anoisesrc=color=white:amplitude=0.02:sample_rate=48000:duration=180:seed=29',
            '-filter_complex',
            f"[1:a]volume='if(lt(mod(t,{PERIOD}),{ON}),1,0)':eval=frame,atempo={tempo:.10f}[p];"
            f"[p][2:a]amix=inputs=2:duration=first:normalize=0[a]",
            '-map', '0:v', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', cam_drift])

        r = sh([PY, os.path.join(HERE, 'camsync.py'), 'measure', screen_drift, cam_drift])
        m_drift = json.loads(r.stdout)
        expected_drift_ms = 0.0005 * 120.0 * 1000.0
        check(m_drift['ok'] and abs(m_drift['drift_ms'] - expected_drift_ms) <= 40.0,
              f"camsync drift_ms={m_drift['drift_ms']} (expected ~{expected_drift_ms:.1f} +-40, rate={m_drift['rate']})")

        # 3. init with a camera
        print('\n[3] init with a camera')
        sh(['bash', os.path.join(HERE, 'new-video.sh'), screen, 'vcam', '--dir', root, '--cam', cam])
        vcam = os.path.join(root, 'vcam')
        cam_json = json.load(open(os.path.join(vcam, 'work', 'camera.json'), encoding='utf-8'))
        check(cam_json.get('mode') == 'separate' and abs(cam_json['offset'] - 2.345) <= 1.0 / 30.0,
              f"camera.json separate offset={cam_json.get('offset')}")
        n_raw = probe_frames(os.path.join(vcam, 'assets', 'media', 'cam_raw.mp4'))
        n_face = probe_frames(os.path.join(vcam, 'assets', 'media', 'cam_face.mp4'))
        check(n_raw > 0 and n_face == n_raw, f'cam_face frames ({n_face}) == cam_raw frames ({n_raw})')
        csrc = P.camera_source(vcam)
        check(csrc.get('pip_rect') == (1560, 680, 320, 360), f"camera_source pip_rect={csrc.get('pip_rect')}")

        sh(['bash', os.path.join(HERE, 'new-video.sh'), screen, 'vcam_off', '--dir', root,
            '--cam', cam, '--cam-offset', '1.0'])
        off_json = json.load(open(os.path.join(root, 'vcam_off', 'work', 'camera.json'), encoding='utf-8'))
        check(off_json.get('method') == 'forced' and off_json.get('offset') == 1.0,
              f"forced offset: method={off_json.get('method')}, offset={off_json.get('offset')}")

        sh(['bash', os.path.join(HERE, 'new-video.sh'), screen, 'vcam_voice', '--dir', root,
            '--cam', cam, '--voice', 'cam'])
        vv = os.path.join(root, 'vcam_voice')
        import soundfile as sf
        vo_screen = os.path.join(vv, 'assets', 'media', 'vo_screen.wav')
        vo_wav = os.path.join(vv, 'assets', 'media', 'vo.wav')
        vv_raw_n = probe_frames(os.path.join(vv, 'assets', 'media', 'cam_raw.mp4'))
        check(os.path.isfile(vo_screen) and sf.info(vo_wav).frames == vv_raw_n * 1600,
              f'--voice cam keeps vo_screen.wav and writes vo.wav ({sf.info(vo_wav).frames} == {vv_raw_n * 1600})')

        # 4. jobs identity
        print('\n[4] jobs identity + chunk cache')
        sh(['bash', os.path.join(HERE, 'new-video.sh'), screen, 'vplain', '--dir', root])
        vplain = os.path.join(root, 'vplain')
        words = make_fake_words(dur)
        json.dump(words, open(os.path.join(vplain, 'work', 'tx', 'words.json'), 'w'), ensure_ascii=False)
        sh([PY, os.path.join(HERE, 'snap-onsets.py'), vplain])
        sh([PY, os.path.join(HERE, 'clean-retakes.py'), vplain, '--hook-split', '10'])

        # Snapshot fresh post-clean directory for step 7 (draft) before adding callouts / running finish
        vdraft = os.path.join(root, 'vdraft')
        shutil.copytree(vplain, vdraft, symlinks=True)

        tl = TL.load(vplain)
        hs = tl['hook_split']
        tl['chapters'] = [{'src_t': 14, 'title': 'Setup'}, {'src_t': 35, 'title': 'Core'}, {'src_t': 58, 'title': 'Demo'}]
        tl['callouts'] = [
            {'src_t': 16.0, 'text': 'First callout', 'dur': 2.0, 'x': 960, 'y': 540},
            {'src_t': 52.0, 'text': 'Second callout', 'dur': 2.0, 'x': 960, 'y': 540},
        ]
        TL.save(vplain, tl)
        n_body = round(TL.body_duration(tl) * TL.FPS)

        h1_prefix = os.path.join(root, 'h1')
        h4_prefix = os.path.join(root, 'h4')
        sh([PY, os.path.join(HERE, 'body_render.py'), vplain, '--force', '--jobs', '1'],
           env=dict(os.environ, EV2_FRAME_HASHES=h1_prefix))
        sh([PY, os.path.join(HERE, 'body_render.py'), vplain, '--force', '--jobs', '4'],
           env=dict(os.environ, EV2_FRAME_HASHES=h4_prefix))
        d1 = load_frame_hashes(h1_prefix)
        d4 = load_frame_hashes(h4_prefix)
        check(len(d1) == n_body and d1 == d4, f'--jobs 1 and --jobs 4 produce identical frame hashes ({len(d1)}/{n_body})')
        body_vid_n = probe_frames(os.path.join(vplain, 'work', 'body_video.mp4'))
        check(body_vid_n == n_body, f'body_video.mp4 frame count ({body_vid_n}) == {n_body}')

        tl['callouts'][1]['text'] = 'Second callout edited'
        TL.save(vplain, tl)
        r = sh([PY, os.path.join(HERE, 'body_render.py'), vplain, '--jobs', '4'])
        m_ch = re.search(r'\b(\d+)\s+chunks rendered,\s+(\d+)\s+reused\s+\(4 jobs\)', r.stdout)
        check(bool(m_ch) and int(m_ch.group(1)) in (1, 2) and int(m_ch.group(2)) >= 1,
              f"callout edit re-rendered only affected chunk(s): {m_ch.group(0) if m_ch else r.stdout.strip()}")

        # 5. separate PiP
        print('\n[5] separate PiP')
        json.dump(words, open(os.path.join(vcam, 'work', 'tx', 'words.json'), 'w'), ensure_ascii=False)
        sh([PY, os.path.join(HERE, 'snap-onsets.py'), vcam])
        sh([PY, os.path.join(HERE, 'clean-retakes.py'), vcam, '--hook-split', '10'])
        sh([PY, os.path.join(HERE, 'body_render.py'), vcam, '--jobs', '2'])
        bvj = json.load(open(os.path.join(vcam, 'work', 'body_video.json'), encoding='utf-8'))
        check(bvj.get('pip') is True and bvj.get('pip_source') == 'camera',
              f"body_video.json pip={bvj.get('pip')}, pip_source={bvj.get('pip_source')}")

        pip_png = os.path.join(root, 'pip_frame.png')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', '10.0',
            '-i', os.path.join(vcam, 'work', 'body_video.mp4'), '-frames:v', '1', pip_png])
        import cv2
        img = cv2.imread(pip_png)
        px, py, pw, ph = csrc['pip_rect']
        crop = img[py + 20:py + ph - 20, px + 20:px + pw - 20]
        mean_bgr = crop.mean(axis=(0, 1))
        target_bgr = (34.0, 68.0, 136.0)
        check(all(abs(mean_bgr[i] - target_bgr[i]) <= 25.0 for i in range(3)),
              f'separate PiP mean BGR {[round(float(x), 1) for x in mean_bgr]} close to {target_bgr}')

        # 6. finish with jobs
        print('\n[6] finish with jobs')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            f'color=c=0x223344:size=1920x1080:rate=30:duration={hs:.6f}',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            os.path.join(vplain, 'out', 'render.mp4')])
        idx_html = os.path.join(vplain, 'index.html')
        if os.path.exists(idx_html):
            os.remove(idx_html)
        open(os.path.join(vplain, 'sfx-cues.txt'), 'w').write('0.500  ev1kit/click_3  0.42\n2.000  ev1kit/impact_1  0.24\n')
        json.dump({'placeholders': [], 'missing': [], 'final': True},
                  open(os.path.join(vplain, 'work', 'build.json'), 'w'))
        json.dump([{'time': 0, 'title': 'Hook'}],
                  open(os.path.join(vplain, 'work', 'hook_chapters.json'), 'w'))
        sh([PY, os.path.join(HERE, 'finish.py'), vplain, '--jobs', '2', '--editor', 'none', '--no-open', '--preset', 'ultrafast'])
        vj = json.load(open(os.path.join(vplain, 'out', 'verify.json'), encoding='utf-8'))
        fj = json.load(open(os.path.join(vplain, 'work', 'finish.json'), encoding='utf-8'))
        check(vj['verdict'].startswith('DONE'), f"finish --jobs 2 verify verdict: {vj['verdict']}")
        check('jobs' in fj and 'gpu' in fj, f"finish.json records jobs={fj.get('jobs')}, gpu={fj.get('gpu')}")

        # 7. draft
        print('\n[7] draft')
        tl_path = os.path.join(vdraft, 'work', 'timeline.json')
        tl_bytes_before = open(tl_path, 'rb').read()
        tl_draft = TL.load(vdraft)
        expected_draft_dur = tl_draft['hook_split'] + TL.body_duration(tl_draft)

        sh([PY, os.path.join(HERE, 'draft.py'), vdraft, '--no-open'])
        draft_mp4 = os.path.join(vdraft, 'out', 'draft.mp4')
        info_d = probe_video(draft_mp4)
        check(info_d['width'] == 1280 and info_d['height'] == 720,
              f"draft.mp4 size {info_d['width']}x{info_d['height']} == 1280x720")
        check(abs(info_d['duration'] - expected_draft_dur) <= 0.15,
              f"draft.mp4 duration {info_d['duration']:.3f}s == {expected_draft_dur:.3f}s (+-0.15)")
        check(not os.path.exists(os.path.join(vdraft, 'out', 'final.mp4')), 'draft leaves out/final.mp4 absent')
        check(open(tl_path, 'rb').read() == tl_bytes_before, 'draft leaves work/timeline.json untouched')

        sh([PY, os.path.join(HERE, 'draft.py'), vdraft, '--retakes', '--no-open'])
        info_dr = probe_video(draft_mp4)
        check(info_dr['duration'] < info_d['duration'] - 0.5,
              f"draft --retakes shorter ({info_dr['duration']:.3f}s < {info_d['duration']:.3f}s)")

        # 8. parity
        print('\n[8] v3.0 parity (test_pipeline.py)')
        tp_args = [PY, os.path.join(HERE, 'test_pipeline.py')]
        r_cpu = subprocess.run(tp_args, capture_output=True, text=True, env=env_off)
        if r_cpu.returncode != 0:
            print(r_cpu.stdout[-3000:], r_cpu.stderr[-3000:])
        check(r_cpu.returncode == 0, 'test_pipeline.py passes with EV2_GPU=0')

        if not a.skip_gpu and gpu_present:
            r_gpu = subprocess.run(tp_args, capture_output=True, text=True)
            if r_gpu.returncode != 0:
                print(r_gpu.stdout[-3000:], r_gpu.stderr[-3000:])
            check(r_gpu.returncode == 0, 'test_pipeline.py passes with GPU on')
        else:
            print('  skip GPU parity run')

        print('\ntest_v31: ALL PASSED')
    finally:
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print(f'kept: {root}')


if __name__ == '__main__':
    main()
