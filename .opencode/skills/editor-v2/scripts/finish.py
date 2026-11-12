#!/usr/bin/env python3
"""finish.py — assemble every deliverable from work/timeline.json, then verify it.

    finish.py <video-dir> [--editor concat|kdenlive|both|none] [--captions] [--no-zoom] [--no-cam]
                          [--raw-body] [--no-keys] [--no-voice-fx] [--no-bed] [--song FILE] [--bed-under LU] [--body-music] [--body-under LU] [--no-short] [--no-open]

Steps (any failure stops with a non-zero exit; nothing is silently skipped):
  1. Load work/timeline.json (hook_split + body segments + chapters).
  2. Check out/render.mp4 (the HyperFrames hook) exists, is newer than index.html, and is
     hook_split long (+-1.5 frames). A mismatch would put the body out of sync.
  3. Voice cleanup (cached): high-pass, FFT denoise, de-ess, gentle EQ + compression
     -> work/vo_clean.wav. Everything below uses it (--no-voice-fx: the raw voice).
  4. Hook audio: clean voice [0, hook) + procedural bed (bed-mix.py) + SFX cues (mix-sfx.py)
     -> work/hook_audio.wav.
  5. Body: the kept segments of the clean voice, sample-exact, 10 ms fades at every cut
     -> work/body_voice.wav; the picture from body_render.py (auto zooms, styled webcam,
     chapter cards, key pills from "keys" in timeline.json, --captions burned in)
     -> work/body_video.mp4 (--raw-body: plain cuts, no key pills, refused when the timeline has
     inserts; --no-keys: skip the key pills for this run). Insert SFX cues
     (work/inserts/<name>.cues.txt) are shifted to the insert's body time, a soft key click is
     added when each key pill appears, and both are mixed into the body audio -> work/body_mix.wav.
  6. Hook + body audio, two-pass loudness-normalized to -14 LUFS / -1.5 dBTP (YouTube)
     -> work/final_audio.wav; one final video encode of render.mp4 + body_video.mp4 (both
     already encoded once: body_video at CRF 16 to keep the second generation clean)
     -> out/final.mp4; out/hook.mp4; out/captions.srt (upload to YouTube as subtitles).
  7. Chapters -> work/chapters.json + out/youtube-chapters.txt (hook chapters from
     work/hook_chapters.json + body chapters from timeline.json). Never invented.
  8. Editor project: Concat (default; out/concat/concat.json) and/or Kdenlive.
  9. 9:16 Short from the hook -> out/short.mp4.
 10. verify.py -> out/verify.md; its exit code is finish's exit code.

The editor default can be set with EV2_EDITOR=concat|kdenlive|both|none.
"""
import argparse, json, os, shutil, subprocess, sys, time

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ev2_timeline as TL  # noqa: E402

FPS, SPF = TL.FPS, TL.SAMPLES_PER_FRAME


class FinishError(Exception):
    pass


def step(msg):
    print(f'\nfinish: {msg}', flush=True)


def run(cmd, what, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or '').strip().splitlines()[-15:]
        raise FinishError(f'{what} failed (exit {r.returncode}):\n    ' + '\n    '.join(tail))
    return r


def probe(path):
    r = run(['ffprobe', '-v', 'error', '-show_entries',
             'format=duration:stream=codec_type,duration,width,height,r_frame_rate,nb_frames',
             '-of', 'json', path], f'ffprobe {path}')
    d = json.loads(r.stdout)
    info = {'duration': float(d.get('format', {}).get('duration') or 0)}
    for s in d.get('streams', []):
        k = s.get('codec_type')
        if k == 'video' and 'v_dur' not in info:
            info['v_dur'] = float(s.get('duration') or info['duration'])
            info['width'], info['height'] = int(s.get('width', 0)), int(s.get('height', 0))
            n, _, dd = (s.get('r_frame_rate') or '0/1').partition('/')
            info['fps'] = float(n) / float(dd or 1) if float(dd or 1) else 0
        elif k == 'audio' and 'a_dur' not in info:
            info['a_dur'] = float(s.get('duration') or info['duration'])
    return info


def write_body_voice(vo_path, segs, out_path, hook_split):
    vo, sr = sf.read(vo_path, dtype='float32', always_2d=True)
    if sr != TL.SR:
        raise FinishError(f'{vo_path} is {sr} Hz, expected {TL.SR} (re-run `ev2 init`)')
    if vo.shape[1] == 1:
        vo = np.repeat(vo, 2, axis=1)
    vo = vo[:, :2]
    fade = int(0.010 * TL.SR)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    parts = []
    prev_end_f = TL.frames(hook_split)
    for s in segs:
        a, b = s['f_start'] * SPF, s['f_end'] * SPF
        x = vo[a:b]
        if len(x) < b - a:
            x = np.pad(x, ((0, b - a - len(x)), (0, 0)))
        x = x.copy()
        if s['f_start'] != prev_end_f:   # a real cut happened before this segment
            x[:fade] *= ramp
            if parts:
                parts[-1][-fade:] *= ramp[::-1]
        prev_end_f = s['f_end']
        parts.append(x)
    body = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
    sf.write(out_path, body, TL.SR, subtype='PCM_24')
    return len(body)


VOICE_FX = ('highpass=f=80,afftdn=nr=10:nf=-45:tn=1,deesser=i=0.35,'
            'equalizer=f=250:t=q:w=1:g=-2,equalizer=f=4500:t=q:w=1.4:g=2,'
            'acompressor=threshold=-22dB:ratio=3:attack=8:release=160:makeup=3dB,alimiter=limit=0.95')


def clean_voice(src, dst):
    stamp = dst + '.json'
    key = {'src_mtime': int(os.path.getmtime(src)), 'src_size': os.path.getsize(src), 'fx': VOICE_FX}
    if os.path.isfile(dst) and os.path.isfile(stamp) and json.load(open(stamp)) == key:
        print(f'  {dst} up to date')
        return dst
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-af', VOICE_FX, '-ar', str(TL.SR), '-ac', '2',
         '-c:a', 'pcm_s24le', dst], 'voice cleanup')
    json.dump(key, open(stamp, 'w'))
    print(f'  high-pass, denoise, de-ess, EQ, compression -> {dst}')
    return dst


def loudnorm(src, dst, target):
    base = f'loudnorm=I={target}:TP=-1.5:LRA=11'
    r = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', src, '-af', base + ':print_format=json', '-f', 'null', '-'],
            'loudness measure')
    txt = r.stderr
    m = json.loads(txt[txt.rindex('{'):txt.rindex('}') + 1])
    second = (f'{base}:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}:measured_LRA={m["input_lra"]}'
              f':measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-af', second, '-ar', str(TL.SR), '-ac', '2',
         '-c:a', 'pcm_s24le', dst], 'loudness normalize')
    print(f'  measured {m["input_i"]} LUFS -> {target:g} LUFS -> {dst}')


def srt_ts(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def insert_cue_lines(ins_list, cue_dir='work/inserts'):
    out = []
    for ins in ins_list:
        p = os.path.join(cue_dir, ins['name'] + '.cues.txt')
        if not os.path.isfile(p):
            continue
        for line in open(p, encoding='utf-8'):
            f = line.split('#', 1)[0].split()
            if len(f) < 2:
                continue
            t = float(f[0])
            if -0.5 <= t < ins['dur'] + 0.5:
                gain = f[2] if len(f) > 2 else '1.0'
                out.append(f'{max(0.0, ins["body_t"] + t):.3f}  {f[1]}  {gain}')
    return out


def select_expr(segs):
    return '+'.join(f"between(n,{s['f_start']},{s['f_end'] - 1})" for s in segs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('video_dir')
    ap.add_argument('--editor', default=os.environ.get('EV2_EDITOR', 'concat'),
                    choices=['concat', 'kdenlive', 'both', 'none'])
    ap.add_argument('--no-bed', action='store_true', help='Hook voice + SFX only, no music bed')
    ap.add_argument('--song', default='auto', help='Music bed for the hook: a file path, or auto (built-in tutorial music)')
    ap.add_argument('--bed-under', type=float, default=13.0, help='Bed level under the voice in LU (default 13)')
    ap.add_argument('--body-music', dest='body_music', action='store_true', default=None,
                    help='Quiet music under the whole tutorial (default: off, or "body_music" in timeline.json)')
    ap.add_argument('--no-body-music', dest='body_music', action='store_false', help='Force the body music off')
    ap.add_argument('--body-under', type=float, default=20.0, help='Body music level under the voice in LU (default 20)')
    ap.add_argument('--captions', action='store_true', help='Burn captions into the body (check the transcript first)')
    ap.add_argument('--no-zoom', action='store_true', help='No automatic zooms on the body')
    ap.add_argument('--no-cam', action='store_true', help='Leave the webcam as recorded (no styled PiP)')
    ap.add_argument('--raw-body', action='store_true', help='Plain cut screencast: no zooms, PiP, chapter cards')
    ap.add_argument('--no-keys', action='store_true', help='Do not draw the key pills listed in timeline.json for this run')
    ap.add_argument('--no-voice-fx', action='store_true', help='Skip voice cleanup')
    ap.add_argument('--lufs', type=float, default=-14.0, help='Target integrated loudness (default -14, YouTube)')
    ap.add_argument('--no-short', action='store_true')
    ap.add_argument('--no-open', action='store_true', help='Do not open final.mp4 when done')
    ap.add_argument('--allow-stale-render', action='store_true', help='Skip the index.html-newer-than-render check')
    ap.add_argument('--preset', default=os.environ.get('EV2_PRESET', 'fast'), help='x264 preset (default fast)')
    ap.add_argument('--crf', default=os.environ.get('EV2_CRF', '18'))
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)
    os.chdir(vd)
    os.makedirs('out', exist_ok=True)
    t0 = time.time()

    step('loading work/timeline.json')
    tl = TL.load(vd)
    segs = TL.body_segments(tl)
    ins_list = TL.insert_ranges(tl)
    if ins_list and a.raw_body:
        raise FinishError('inserts need the polished body: drop --raw-body (or remove "inserts" from work/timeline.json)')
    try:
        pills = TL.key_ranges(tl)
        keys_sig = TL.keys_signature(tl)
    except TL.TimelineError as e:
        if not a.no_keys:
            raise
        print(f'  key pills skipped (--no-keys; they are invalid: {e})')
        pills, keys_sig = [], None
    draw_keys = bool(pills) and not a.no_keys and not a.raw_body
    if pills and a.raw_body:
        print('  note: key pills are not drawn with --raw-body')
    elif pills and a.no_keys:
        print('  key pills skipped (--no-keys)')
    hs = float(tl['hook_split'])
    has_hook = hs > 0
    if not segs:
        raise FinishError('timeline.json has no body segments: re-run `ev2 clean <video-dir>`')
    body_dur = sum(s['f_end'] - s['f_start'] for s in segs) / FPS
    for p in ['assets/media/vo.wav', 'assets/media/cam_raw.mp4']:
        if not os.path.isfile(p):
            raise FinishError(f'{p} missing: re-run `ev2 init`')
    cam = probe('assets/media/cam_raw.mp4')
    if abs(cam.get('fps', 0) - FPS) > 0.01 or (cam.get('width'), cam.get('height')) != (1920, 1080):
        raise FinishError(f'cam_raw.mp4 must be 1920x1080 @ {FPS} fps (got {cam.get("width")}x{cam.get("height")} @ {cam.get("fps")})')
    last_f = segs[-1]['f_end']
    if last_f > int(cam['v_dur'] * FPS + 0.5):
        raise FinishError(f'timeline ends at frame {last_f} but cam_raw.mp4 has ~{int(cam["v_dur"] * FPS)} frames')
    print(f'  hook 0-{hs:.3f}s | body {len(segs)} segments, {body_dur:.2f}s | expected final {hs + body_dur:.2f}s')

    status = json.load(open('work/build.json')) if os.path.isfile('work/build.json') else {}
    if status.get('placeholders') or status.get('missing'):
        print(f'  WARNING build.py reported placeholders {status.get("placeholders")} / missing assets '
              f'{status.get("missing")}: verify will FAIL until `ev2 build <video-dir> --final` passes')
    elif has_hook and not status.get('final'):
        print('  WARNING the hook was not built with --final: verify will FAIL until `ev2 build <video-dir> --final` passes')

    for ins in ins_list:
        sp = os.path.join('work', 'inserts', ins['name'] + '.json')
        ist = json.load(open(sp)) if os.path.isfile(sp) else {}
        if not ist.get('final') or ist.get('placeholders') or ist.get('missing'):
            print(f'  WARNING insert "{ins["name"]}" is not a FINAL build: verify will FAIL until '
                  f'`ev2 inserts <video-dir> --final` passes')

    voice = 'assets/media/vo.wav'
    if not a.no_voice_fx:
        step('voice cleanup')
        voice = clean_voice(voice, 'work/vo_clean.wav')

    NH = 0
    if has_hook:
        step('checking the hook render (out/render.mp4)')
        if not os.path.isfile('out/render.mp4'):
            raise FinishError('out/render.mp4 missing: run `ev2 build <video-dir>` first')
        if (not a.allow_stale_render and os.path.isfile('index.html')
                and os.path.getmtime('index.html') > os.path.getmtime('out/render.mp4') + 1):
            raise FinishError('index.html is newer than out/render.mp4: the render is stale; run `ev2 build <video-dir>`')
        r = probe('out/render.mp4')
        H = r.get('v_dur', r['duration'])
        NH = int(round(H * FPS))
        if abs(H - hs) > 1.5 / FPS:
            raise FinishError(f'hook render is {H:.3f}s but timeline hook_split is {hs:.3f}s. '
                              f'Rebuild the hook (`ev2 build`) after changing the split, so the body starts where the hook ends.')
        NH = TL.frames(hs)
        print(f'  render {H:.3f}s ({NH} frames) matches hook_split')

        step('hook audio: voice + bed + SFX')
        premix = 'work/premix.wav'
        if a.no_bed:
            run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', voice, '-t', f'{hs:.6f}',
                 '-ac', '2', '-ar', str(TL.SR), '-c:a', 'pcm_f32le', premix], 'voice trim')
        else:
            run([sys.executable, os.path.join(HERE, 'bed-mix.py'), '--voice', voice,
                 '--song', a.song, '--under', str(a.bed_under), '--dur', f'{hs:.6f}', '--out', premix], 'bed-mix.py')
        hook_audio = 'work/hook_audio.wav'
        cues = 'sfx-cues.txt'
        n_cues = 0
        if os.path.isfile(cues):
            n_cues = sum(1 for l in open(cues) if l.split('#', 1)[0].strip())
        if n_cues:
            run([sys.executable, os.path.join(HERE, 'mix-sfx.py'), premix, cues, hook_audio], 'mix-sfx.py')
        else:
            shutil.copyfile(premix, hook_audio)
        print(f'  {"bed" if not a.no_bed else "no bed"}, {n_cues} SFX cues -> {hook_audio}')

    step('body audio: kept voice segments (sample-exact)')
    n = write_body_voice(voice, segs, 'work/body_voice.wav', hs)
    print(f'  {n / TL.SR:.3f}s -> work/body_voice.wav')

    use_music = (tl.get('body_music', False) if a.body_music is None else a.body_music) and not a.no_bed
    body_base = 'work/body_voice.wav'
    if use_music:
        run([sys.executable, os.path.join(HERE, 'bed-mix.py'), '--voice', 'work/body_voice.wav', '--song', a.song,
             '--under', str(a.body_under), '--dur', f'{n / TL.SR:.6f}', '--fade-in', '1.5', '--ring-out', '3',
             '--out', 'work/body_music.wav'], 'bed-mix.py (body music)')
        body_base = 'work/body_music.wav'
        print(f'  quiet music under the whole body ({a.body_under:g} LU under the voice) -> {body_base}')
    for p in (['work/body_music_bed.wav'] if use_music else ['work/body_music.wav', 'work/body_music_bed.wav']):
        if os.path.isfile(p):
            os.remove(p)

    body_audio = body_base
    body_cues = insert_cue_lines(ins_list)
    key_cues = [f'{max(0.0, p["body_t"] - 0.004):.3f}  ev1kit/key_click  {0.36 * 0.8:.3f}'
                for p in pills if p['sfx']] if draw_keys else []
    if body_cues or key_cues:
        header = '# insert SFX in body time\n'
        if key_cues:
            n_ins = len(body_cues)
            body_cues = sorted(body_cues + key_cues, key=lambda l: float(l.split()[0]))
            header = '# insert / key-pill SFX in body time\n'
        with open('work/body_cues.txt', 'w', encoding='utf-8') as f:
            f.write(header + '\n'.join(body_cues) + '\n')
        run([sys.executable, os.path.join(HERE, 'mix-sfx.py'), body_base, 'work/body_cues.txt',
             'work/body_mix.wav'], 'mix-sfx.py (insert SFX)' if not key_cues else 'mix-sfx.py (insert / key-pill SFX)')
        body_audio = 'work/body_mix.wav'
        if key_cues:
            print(f'  {n_ins} insert SFX cues + {len(key_cues)} key clicks -> work/body_mix.wav')
        else:
            print(f'  {len(body_cues)} insert SFX cues -> work/body_mix.wav')
    else:
        for p in ['work/body_mix.wav', 'work/body_cues.txt']:
            if os.path.isfile(p):
                os.remove(p)

    body_v = None
    if not a.raw_body:
        step('body picture: zooms, webcam PiP, chapter cards' + (', key pills' if draw_keys else '')
             + (', captions' if a.captions else ''))
        import body_render
        plan = body_render.render(vd, zoom=not a.no_zoom, cam=not a.no_cam, captions=a.captions, preset=a.preset,
                                  keys=not a.no_keys)
        body_v = 'work/body_video.mp4'
        bi = probe(body_v)
        if abs(bi.get('v_dur', 0) - body_dur) > 1.5 / FPS:
            raise FinishError(f'body_video.mp4 is {bi.get("v_dur")}s, expected {body_dur:.3f}s')

    step(f'final audio: join + loudness to {a.lufs:g} LUFS')
    parts = []
    if has_hook:
        x, _ = sf.read('work/hook_audio.wav', dtype='float32', always_2d=True)
        x = x[:, :2] if x.shape[1] >= 2 else np.repeat(x, 2, axis=1)
        x = np.pad(x, ((0, max(0, NH * SPF - len(x))), (0, 0)))[:NH * SPF]
        parts.append(x)
    y, _ = sf.read(body_audio, dtype='float32', always_2d=True)
    y = y[:, :2] if y.shape[1] >= 2 else np.repeat(y, 2, axis=1)
    y = np.pad(y, ((0, max(0, n - len(y))), (0, 0)))[:n]
    parts.append(y)
    sf.write('work/joined_audio.wav', np.concatenate(parts), TL.SR, subtype='FLOAT')
    loudnorm('work/joined_audio.wav', 'work/final_audio.wav', a.lufs)
    os.remove('work/joined_audio.wav')

    step('encoding out/final.mp4 (single pass)')
    norm_v = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p'
    inputs, chains = [], []
    if has_hook:
        inputs += ['-i', 'out/render.mp4']
        chains.append(f'[0:v]fps={FPS},{norm_v},trim=end_frame={NH},settb=1/{FPS},setpts=N[hv]')
    bi_ = len(inputs) // 2
    if body_v:
        inputs += ['-i', body_v]
        chains.append(f'[{bi_}:v]{norm_v},settb=1/{FPS},setpts=N[bv]')
    else:
        inputs += ['-i', 'assets/media/cam_raw.mp4']
        chains.append(f"[{bi_}:v]select='{select_expr(segs)}',settb=1/{FPS},setpts=N,{norm_v}[bv]")
    ai = len(inputs) // 2
    inputs += ['-i', 'work/final_audio.wav']
    chains.append('[hv][bv]concat=n=2:v=1:a=0[v]' if has_hook else '[bv]null[v]')
    fg_path = 'work/final.filtergraph'
    open(fg_path, 'w').write(';\n'.join(chains))
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-stats', '-y', *inputs, '-/filter_complex', fg_path,
           '-map', '[v]', '-map', f'{ai}:a:0', '-c:v', 'libx264', '-preset', a.preset, '-crf', str(a.crf),
           '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
           '-movflags', '+faststart', 'out/final.mp4']
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise FinishError(f'final encode failed (exit {r.returncode}); filtergraph: {fg_path}')
    if has_hook:
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', 'out/render.mp4', '-i', 'work/final_audio.wav',
             '-map', '0:v:0', '-map', '1:a:0', '-t', f'{NH / FPS:.6f}', '-c:v', 'copy',
             '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', 'out/hook.mp4'], 'hook.mp4 mux')

    step('captions file')
    import body_render
    groups = body_render.caption_groups(body_render.final_words(vd, tl))
    with open('out/captions.srt', 'w', encoding='utf-8') as f:
        for i, (cs, ce, txt) in enumerate(groups, 1):
            f.write(f'{i}\n{srt_ts(cs)} --> {srt_ts(ce)}\n{txt}\n\n')
    print(f'  {len(groups)} captions -> out/captions.srt (upload in YouTube Studio > Subtitles)')

    step('chapters')
    hook_ch = []
    if os.path.isfile('work/hook_chapters.json'):
        hook_ch = [(float(c.get('time', 0)), c.get('title', '')) for c in json.load(open('work/hook_chapters.json'))]
    chapters = TL.final_chapters(tl, NH / FPS if has_hook else 0.0, hook_ch)
    total = NH / FPS + body_dur
    json.dump([{'time': round(t, 3), 'timestamp': TL.fmt_ts(t), 'title': title} for t, title in chapters],
              open('work/chapters.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    with open('out/youtube-chapters.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(f'{TL.fmt_ts(t)} {title}' for t, title in chapters) + '\n')
    for p in TL.youtube_chapter_problems(chapters, total):
        print(f'  WARNING {p} (add chapters to work/timeline.json)')
    print(f'  {len(chapters)} chapters -> out/youtube-chapters.txt')

    editors = {'both': ['concat', 'kdenlive'], 'none': []}.get(a.editor, [a.editor])
    for ed in editors:
        step(f'{ed} project')
        script = 'concat-gen.py' if ed == 'concat' else 'kdenlive-gen.py'
        r = run([sys.executable, os.path.join(HERE, script), vd], script)
        print('  ' + r.stdout.strip().replace('\n', '\n  '))

    if not a.no_short:
        step('9:16 Short')
        src = 'out/hook.mp4' if has_hook else 'out/final.mp4'
        r = run([sys.executable, os.path.join(HERE, 'short-extract.py'), src, 'out/short.mp4', '--framing', 'crop'],
                'short-extract.py')
        print('  ' + r.stdout.strip().splitlines()[-1])

    json.dump({'cut_signature': TL.cut_signature(tl), 'chapter_signature': TL.chapter_signature(vd, tl),
               'insert_signature': TL.insert_signature(vd, tl), 'inserts': [i['name'] for i in ins_list],
               'keys_signature': keys_sig, 'key_pills': len(pills), 'keys_drawn': draw_keys,
               'body_music': bool(use_music), 'hook_duration': NH / FPS, 'body_duration': body_dur,
               'expected_final': total, 'editors': editors, 'short': not a.no_short,
               'finished': time.strftime('%Y-%m-%dT%H:%M:%S'), 'seconds': round(time.time() - t0, 1)},
              open('work/finish.json', 'w'), indent=2)

    step('verifying (definition of done)')
    rc = subprocess.run([sys.executable, os.path.join(HERE, 'verify.py'), vd]).returncode
    if rc == 0 and not a.no_open and sys.platform.startswith('linux') and (
            os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY')):
        subprocess.Popen(['xdg-open', 'out/final.mp4'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return rc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (FinishError, TL.TimelineError) as e:
        print(f'\nfinish: ERROR {e}', file=sys.stderr)
        sys.exit(1)
