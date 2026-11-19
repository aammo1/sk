#!/usr/bin/env python3
"""shorts.py — Pro 9:16 Shorts & Reels generator for Editor V2.

    ev2 shorts <dir> --init [--force]             Suggest work/shorts.json + face centering check sheets
    ev2 shorts <dir> [--final] [--only NAME]      Render Pro 1080x1920 Shorts -> out/shorts/<name>.mp4 + .srt
                     [--nudge PX] [--no-render] [--deband] [--no-hold]

Supports both:
  - Extracting 1-3 punchy 30-59s Shorts from a 16:9 tutorial (stacked: zoomed live screen + recipe cards
    on top, Darija/BiDi word-highlighted captions on the seam, native-res face band on bottom).
  - Standalone Short/Reel workspaces (`ev2 init <file> --mode short`), vertical 9:16 or 16:9.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    for cand in [os.environ.get('EV2_PY'), os.path.expanduser('~/.cache/editor-v2/venv/bin/python')]:
        if cand and os.path.isfile(cand) and os.path.realpath(cand) != os.path.realpath(sys.executable):
            os.execv(cand, [cand] + sys.argv)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SK, 'components'))
import ev2_pro as P        # noqa: E402
import ev2_shorts as SH    # noqa: E402
import ev2_timeline as TL  # noqa: E402
import gpu                 # noqa: E402

FPS, SR, SPF = TL.FPS, TL.SR, TL.SAMPLES_PER_FRAME


def run(cmd, what, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or '').strip().splitlines()[-15:]
        raise RuntimeError(f'{what} failed (exit {r.returncode}):\n  ' + '\n  '.join(tail))
    return r


def probe(path):
    r = run(['ffprobe', '-v', 'error',
             '-show_entries', 'format=duration:stream=codec_type,width,height,r_frame_rate',
             '-of', 'json', path], f'ffprobe {path}')
    d = json.loads(r.stdout)
    info = {'duration': float((d.get('format') or {}).get('duration') or 0.0), 'width': 0, 'height': 0}
    for s in d.get('streams') or []:
        if s.get('codec_type') == 'video' and not info['width']:
            info['width'] = int(s.get('width') or 0)
            info['height'] = int(s.get('height') or 0)
    return info


def slugify(text, fallback='short'):
    s = re.sub(r'[^a-z0-9]+', '-', str(text or '').lower()).strip('-')
    return (s[:28].rstrip('-')) or fallback


def load_theme(vd):
    lp = os.path.join(vd, 'work', 'look.json')
    look = {}
    if os.path.isfile(lp):
        try:
            look = json.load(open(lp, encoding='utf-8'))
        except (OSError, ValueError):
            look = {}
    acc = look.get('resolved_accent') or look.get('accent')
    if not acc or acc == 'auto':
        acc = P.DEFAULT_ACCENT
    return P.make_theme(acc), look


def load_words(vd):
    wp = os.path.join(vd, 'work', 'tx', 'words.json')
    if not os.path.isfile(wp):
        return []
    raw = json.load(open(wp, encoding='utf-8'))
    return raw.get('words', []) if isinstance(raw, dict) else raw


def detect_mode_and_cam(vd):
    kit = {}
    kp = os.path.join(vd, 'kit.json')
    if os.path.isfile(kp):
        try:
            kit = json.load(open(kp, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    om = {}
    op = os.path.join(vd, 'work', 'omarchy.json')
    if os.path.isfile(op):
        try:
            om = json.load(open(op, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    cam = P.camera_source(vd)
    cam_raw = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    info = probe(cam_raw) if os.path.isfile(cam_raw) else {'width': 1920, 'height': 1080, 'duration': 0.0}
    is_vert = bool(om.get('vertical_source') or (info['height'] > info['width'] > 0))
    return {
        'kit_mode': kit.get('mode', 'tutorial'),
        'vertical_source': is_vert,
        'cam': cam,
        'cam_raw_info': info,
    }


def _kept_pieces_in_spans(tl, spans):
    """Intersect user spans [[a, b], ...] with kept segments (and hook [0, hs)) on source timeline."""
    hs = float(tl.get('hook_split') or 0.0)
    kept = []
    if hs > 0:
        kept.append((0.0, hs))
    for s in tl.get('segments') or []:
        kept.append((float(s['src_start']), float(s['src_end'])))
    if not kept:
        kept = [(float(a), float(b)) for a, b in spans]

    pieces = []
    for a, b in spans:
        a, b = float(a), float(b)
        for ks, ke in kept:
            lo, hi = max(a, ks), min(b, ke)
            fs, fe = TL.frames(lo), TL.frames(hi)
            if fe - fs >= 2:
                pieces.append({'f_start': fs, 'f_end': fe, 'src_start': fs / FPS, 'src_end': fe / FPS})
    if not pieces:
        for a, b in spans:
            fs, fe = TL.frames(float(a)), TL.frames(float(b))
            if fe - fs >= 2:
                pieces.append({'f_start': fs, 'f_end': fe, 'src_start': fs / FPS, 'src_end': fe / FPS})

    out_t = 0.0
    for p in pieces:
        dur = (p['f_end'] - p['f_start']) / FPS
        p['out_start'] = out_t
        p['out_end'] = out_t + dur
        out_t += dur
    return pieces, out_t


def _map_words_to_pieces(words, pieces):
    out = []
    for p in pieces:
        for w in words:
            ws, we = float(w['s']), float(w.get('e', w['s']))
            if we > p['src_start'] + 0.02 and ws < p['src_end'] - 0.02:
                ls = p['out_start'] + max(0.0, ws - p['src_start'])
                le = p['out_start'] + min(p['src_end'] - p['src_start'], max(ws - p['src_start'] + 0.05, we - p['src_start']))
                out.append({'w': str(w['w']), 's': round(ls, 3), 'e': round(le, 3)})
    return out


def _suggest_screen_moves(vd, pieces, total_dur):
    """Build smooth zoom moves from work/inputs.json clicks if available, else a clean centered wide framing."""
    ip = os.path.join(vd, 'work', 'inputs.json')
    moves = [{'t': 0.0, 'rect': [120, 60, 1680, 945], 'dur': 0.0}]
    if not os.path.isfile(ip):
        return moves
    try:
        inp = json.load(open(ip, encoding='utf-8'))
    except (OSError, ValueError):
        return moves
    clicks = inp.get('clicks') or []
    last_t = -99.0
    for c in clicks:
        ct = float(c.get('t', -1))
        cx, cy = float(c.get('x', 960)), float(c.get('y', 540))
        for p in pieces:
            if p['src_start'] <= ct <= p['src_end']:
                lt = p['out_start'] + (ct - p['src_start'])
                if lt - last_t >= 3.2 and lt < total_dur - 1.5:
                    rw, rh = 960, 540
                    rx = max(0, min(1920 - rw, int(cx - rw / 2)))
                    ry = max(0, min(1080 - rh, int(cy - rh / 2)))
                    moves.append({'t': round(max(0.2, lt - 0.35), 2), 'rect': [rx, ry, rw, rh], 'dur': 0.65})
                    last_t = lt
                break
        if len(moves) >= 6:
            break
    return moves


def _face_crop_box(env, nudge=0):
    """Compute native pixel crop (x, y, w, h, src_path) for the bottom 1080x740 face band."""
    cam = env['cam']
    bw, bh = 1080, 740
    if cam['mode'] == 'separate':
        fw, fh = cam['size']
        fb = cam.get('face_box')
        cx = (fb[0] + fb[2] / 2.0) if fb else fw / 2.0
        cy = (fb[1] + fb[3] / 2.0) if fb else fh * 0.42
        cw = min(fw, bw)
        ch = min(fh, int(round(cw * bh / bw)))
        x0 = max(0, min(fw - cw, int(round(cx - cw / 2.0 + nudge))))
        y0 = max(0, min(fh - ch, int(round(cy - ch * 0.42))))
        return cam['path'], (x0, y0, cw, ch)
    if cam['mode'] == 'overlay':
        bx, by, obw, obh = [int(round(v)) for v in cam['box']]
        return None, (max(0, bx + nudge), max(0, by), max(64, obw), max(64, obh))
    return None, None


def _write_face_check(vd, name, src_video, crop_box, t_start, dur, out_png):
    """Write a 3-frame face centering verification sheet (start/middle/end with red center line)."""
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    x, y, w, h = crop_box
    tiles = []
    for k, frac in enumerate((0.1, 0.5, 0.85)):
        tt = t_start + dur * frac
        tf = out_png[:-4] + f'_t{k}.png'
        tiles.append(tf)
        vf = (f'crop={w}:{h}:{x}:{y},scale=540:370:force_original_aspect_ratio=increase,crop=540:370,'
              f'drawbox=x=269:y=0:w=2:h=370:color=red@0.85:t=fill')
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', f'{tt:.3f}', '-i', src_video,
             '-frames:v', '1', '-vf', vf, tf], 'face check tile')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y',
         '-i', tiles[0], '-i', tiles[1], '-i', tiles[2],
         '-filter_complex', 'hstack=inputs=3', out_png], 'face check sheet')
    for tf in tiles:
        if os.path.isfile(tf):
            os.remove(tf)
    return out_png


# ------------------------------------------------------------------ --init
def init_shorts(vd, force=False, nudge=0):
    sp = os.path.join(vd, 'work', 'shorts.json')
    if os.path.isfile(sp) and not force:
        print(f'shorts: {sp} already exists (pass --force to regenerate)')
        return 0
    tl = TL.load(vd)
    env = detect_mode_and_cam(vd)
    hk = {}
    hp = os.path.join(vd, 'work', 'hook.json')
    if os.path.isfile(hp):
        try:
            hk = json.load(open(hp, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    brand = str(hk.get('brand') or '').strip()
    promise = str(hk.get('promise') or '').strip()
    has_cam = env['cam']['mode'] in ('separate', 'overlay')
    default_layout = ('talking-head' if env['vertical_source']
                      else ('stacked' if has_cam else 'screen-only'))

    shorts = []
    if env['kit_mode'] == 'short':
        segs = tl.get('segments') or []
        t0 = float(segs[0]['src_start']) if segs else 0.0
        t1 = float(segs[-1]['src_end']) if segs else min(58.0, float(tl.get('source_duration') or 30.0))
        pieces, tot = _kept_pieces_in_spans(tl, [[t0, t1]])
        if tot > 58.0:
            t1 = t0 + 58.0
            pieces, tot = _kept_pieces_in_spans(tl, [[t0, t1]])
        beats = []
        if default_layout in ('stacked', 'screen-only'):
            beats.append({'at': 0.0, 'dur': round(tot, 2), 'type': 'screen', 'max_zoom': 1.75,
                          'moves': _suggest_screen_moves(vd, pieces, tot)})
        shorts.append({
            'name': 'reel-01',
            'layout': default_layout,
            'spans': [[round(t0, 2), round(t1, 2)]],
            'nudge': nudge,
            'hook_kicker': brand,
            'captions': True,
            'music': True,
            'beats': beats,
        })
    else:
        # Tutorial mode: suggest up to 2 high-value candidates (1: hook/opening, 2: first body chapter)
        hs = float(tl.get('hook_split') or 0.0)
        src_dur = float(tl.get('source_duration') or 0.0)
        cands = []
        if 12.0 <= hs <= 55.0:
            cands.append(('s1-hook', 0.0, hs, promise or 'Hook'))
        chs = sorted(tl.get('chapters') or [], key=lambda c: float(c['src_t']))
        if chs:
            for idx, ch in enumerate(chs[:2], 1):
                c0 = float(ch['src_t'])
                c_next = float(chs[idx]['src_t']) if idx < len(chs) else src_dur
                c1 = min(c_next, c0 + 48.0)
                if c1 - c0 >= 15.0:
                    cands.append((f's{len(cands) + 1}-{slugify(ch["title"], f"ch{idx}")}', c0, c1, ch['title']))
        if not cands:
            segs = tl.get('segments') or []
            s0 = float(segs[0]['src_start']) if segs else hs
            s1 = min(src_dur, s0 + 45.0)
            cands.append(('s1-highlight', s0, s1, promise or 'Highlight'))

        for name, a, b, label in cands[:3]:
            pieces, tot = _kept_pieces_in_spans(tl, [[a, b]])
            if tot < 3.0:
                continue
            if tot > 58.0:
                b = a + 58.0
                pieces, tot = _kept_pieces_in_spans(tl, [[a, b]])
            beats = []
            if default_layout in ('stacked', 'screen-only'):
                opener = min(3.2, tot * 0.25)
                if label and tot > 8.0:
                    beats.append({'at': 0.0, 'dur': round(opener, 2), 'type': 'card', 'recipe': 'title',
                                  'data': {'kicker': brand or 'Tutorial', 'title': label[:50]}})
                    beats.append({'at': round(opener, 2), 'dur': round(tot - opener, 2), 'type': 'screen',
                                  'max_zoom': 1.8, 'moves': _suggest_screen_moves(vd, pieces, tot)})
                else:
                    beats.append({'at': 0.0, 'dur': round(tot, 2), 'type': 'screen',
                                  'max_zoom': 1.8, 'moves': _suggest_screen_moves(vd, pieces, tot)})
            shorts.append({
                'name': name,
                'layout': default_layout,
                'spans': [[round(a, 2), round(b, 2)]],
                'nudge': nudge,
                'hook_kicker': brand,
                'captions': True,
                'music': True,
                'beats': beats,
            })

    os.makedirs(os.path.join(vd, 'work'), exist_ok=True)
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump({'shorts': shorts}, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'shorts: wrote {len(shorts)} candidate(s) -> {sp}')

    # Generate face-check sheet for stacked layouts
    cam_src, box = _face_crop_box(env, nudge=nudge)
    cam_raw = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    face_vid = cam_src or (cam_raw if box else None)
    for sh in shorts:
        a, b = sh['spans'][0]
        print(f'  - {sh["name"]} ({sh["layout"]}, {a:.1f}-{b:.1f}s)')
        if sh['layout'] == 'stacked' and face_vid and box and os.path.isfile(face_vid):
            chk = os.path.join(vd, 'out', 'shorts', f'{sh["name"]}_face_check.png')
            _write_face_check(vd, sh['name'], face_vid, box, a, b - a, chk)
            print(f'    face check -> {os.path.relpath(chk, vd)} (adjust "nudge" in work/shorts.json if off center)')
    return 0


# ------------------------------------------------------------------ media slicing & final export
def _write_short_audio(vo_path, pieces, out_wav):
    vo, sr = sf.read(vo_path, dtype='float32', always_2d=True)
    if sr != SR:
        raise RuntimeError(f'{vo_path} is {sr} Hz, expected {SR}')
    if vo.shape[1] == 1:
        vo = np.repeat(vo, 2, axis=1)
    vo = vo[:, :2]
    fade = int(0.010 * SR)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    parts = []
    prev_end = None
    for p in pieces:
        a, b = p['f_start'] * SPF, p['f_end'] * SPF
        x = vo[a:b]
        if len(x) < b - a:
            x = np.pad(x, ((0, b - a - len(x)), (0, 0)))
        x = x.copy()
        if prev_end is not None and p['f_start'] != prev_end:
            cf = min(fade, len(x))
            x[:cf] *= ramp[:cf]
            if parts:
                pf = min(fade, len(parts[-1]))
                parts[-1][-pf:] *= ramp[::-1][-pf:]
        prev_end = p['f_end']
        parts.append(x)
    data = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
    sf.write(out_wav, data, SR, subtype='PCM_24')
    return len(data) / SR


def _slice_video(src_video, pieces, out_mp4, vf_extra=''):
    """Frame-exact concat of kept source pieces into out_mp4."""
    chains = []
    for i, p in enumerate(pieces):
        s, e = p['src_start'], p['src_end']
        extra = f',{vf_extra}' if vf_extra else ''
        chains.append(f'[0:v]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS{extra}[v{i}]')
    concat = ''.join(f'[v{i}]' for i in range(len(pieces))) + f'concat=n={len(pieces)}:v=1:a=0[v]'
    fg = ';'.join(chains + [concat])
    venc = gpu.venc(['-c:v', 'libx264', '-crf', '14', '-preset', 'fast'], 14)
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src_video,
         '-filter_complex', fg, '-map', '[v]', *venc, '-pix_fmt', 'yuv420p', '-r', str(FPS), '-an', out_mp4],
        f'slice {os.path.basename(out_mp4)}')


def _sync_lag_ms(a_wav, b_mp4, tmp_dir):
    bw = os.path.join(tmp_dir, '_sync_out.wav')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', b_mp4, '-ac', '1', '-ar', '8000', bw], 'sync extract')
    aw = os.path.join(tmp_dir, '_sync_ref.wav')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', a_wav, '-ac', '1', '-ar', '8000', aw], 'sync ref')
    a, _ = sf.read(aw, dtype='float32')
    b, _ = sf.read(bw, dtype='float32')
    if a.ndim > 1:
        a = a.mean(axis=1)
    if b.ndim > 1:
        b = b.mean(axis=1)
    dur = min(len(a), len(b)) / 8000.0
    if dur < 2.0:
        return [0.0]
    probes = [dur * f for f in (0.15, 0.4, 0.65, 0.82)]
    lags = []
    win = int(min(2.0, dur * 0.25) * 8000)
    m = int(0.25 * 8000)
    for t0 in probes:
        i = int(t0 * 8000)
        if i + win >= min(len(a), len(b)):
            continue
        ref = a[i:i + win] - a[i:i + win].mean()
        sig = b[i:i + win] - b[i:i + win].mean()
        if np.std(ref) < 1e-4 or np.std(sig) < 1e-4:
            continue
        c = np.correlate(np.pad(sig, (m, m)), ref, mode='valid')
        k = int(np.argmax(c))
        lags.append(round((k - m) / 8.0, 1))
    return lags or [0.0]


def _srt_ts(t):
    ms = int(round(max(0.0, t) * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def _loudnorm_finalize(raw_mp4, audio_wav, out_mp4, hold=1.0, deband=False):
    # 1. Measure loudness on audio_wav
    r = run(['ffmpeg', '-nostdin', '-hide_banner', '-i', audio_wav,
             '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'], 'short loudnorm measure')
    m = json.loads(r.stderr[r.stderr.rindex('{'):r.stderr.rindex('}') + 1])
    ln = (f'loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}'
          f':measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true,'
          f'alimiter=limit=0.66:level=disabled:latency=1,volume=0.3dB,aresample=48000')
    dur = probe(raw_mp4)['duration']
    v_filters = []
    a_filters = [ln]
    if hold > 0:
        T = dur + hold
        v_filters.append(f'tpad=stop_mode=clone:stop_duration={hold:.3f},fade=t=out:st={max(0.1, T - 0.7):.3f}:d=0.7')
        a_filters.append(f'apad=pad_dur={hold:.3f},afade=t=out:st={max(0.1, T - 0.7):.3f}:d=0.7')
    if deband:
        v_filters.append('deband=1thr=0.012:2thr=0.012:3thr=0.012:range=24:blur=1,noise=alls=3:allf=u')

    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', raw_mp4, '-i', audio_wav,
           '-map', '0:v:0', '-map', '1:a:0']
    if v_filters:
        venc = gpu.venc(['-c:v', 'libx264', '-crf', '16', '-preset', 'medium'], 16)
        cmd += ['-vf', ','.join(v_filters), *venc, '-pix_fmt', 'yuv420p', '-r', str(FPS)]
    else:
        cmd += ['-c:v', 'copy']
    cmd += ['-af', ','.join(a_filters), '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart']
    if hold > 0:
        cmd += ['-t', f'{dur + hold:.3f}']
    cmd.append(out_mp4)
    run(cmd, 'short final encode')


def render_short(vd, spec, tl, env, theme, words, args):
    name = spec['name']
    layout = spec.get('layout', 'stacked')
    nudge = args.nudge if args.nudge is not None else int(spec.get('nudge', 0))
    proj = os.path.join(vd, 'work', 'shorts', name)
    os.makedirs(proj, exist_ok=True)
    os.makedirs(os.path.join(vd, 'out', 'shorts'), exist_ok=True)

    # Copy bundled offline fonts & gsap
    for sub in ('fonts', 'vendor'):
        src_sub = os.path.join(SK, 'assets', sub)
        dst_sub = os.path.join(proj, sub)
        if os.path.isdir(src_sub):
            shutil.copytree(src_sub, dst_sub, dirs_exist_ok=True)

    pieces, dur = _kept_pieces_in_spans(tl, spec['spans'])
    if dur < 1.0:
        raise RuntimeError(f'short "{name}": effective duration {dur:.2f}s is too short')
    if dur > 60.5:
        raise RuntimeError(f'short "{name}": effective duration {dur:.2f}s exceeds 60s Short limit')

    vo_src = os.path.join(vd, 'work', 'vo_clean.wav')
    if not os.path.isfile(vo_src):
        vo_src = os.path.join(vd, 'assets', 'media', 'vo.wav')
    audio_wav = os.path.join(proj, 'audio.wav')
    _write_short_audio(vo_src, pieces, audio_wav)

    cam_raw = os.path.join(vd, 'assets', 'media', 'cam_raw.mp4')
    has_screen = layout in ('stacked', 'screen-only')
    has_face = layout in ('stacked', 'talking-head')

    if has_screen:
        _slice_video(cam_raw, pieces, os.path.join(proj, 'screen.mp4'))

    if has_face:
        if layout == 'talking-head':
            vf = '' if env['vertical_source'] else 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'
            _slice_video(cam_raw, pieces, os.path.join(proj, 'face.mp4'), vf_extra=vf)
        else:
            cam_src, box = _face_crop_box(env, nudge=nudge)
            face_vid = cam_src or cam_raw
            if box:
                x, y, w, h = box
                vf = f'crop={w}:{h}:{x}:{y},scale=1080:740:force_original_aspect_ratio=increase,crop=1080:740'
                _slice_video(face_vid, pieces, os.path.join(proj, 'face.mp4'), vf_extra=vf)
                chk = os.path.join(vd, 'out', 'shorts', f'{name}_face_check.png')
                _write_face_check(vd, name, face_vid, box, pieces[0]['src_start'], dur, chk)
            else:
                has_face = False

    local_words = _map_words_to_pieces(words, pieces)
    punch_times = [p['out_start'] for p in pieces[1:]] if layout == 'talking-head' else []
    built = SH.build_short_html(proj, spec, dur, local_words, theme,
                                has_screen=has_screen, has_face=has_face, punch_times=punch_times)
    print(f'shorts: built {name} ({layout}, {dur:.2f}s, {len(built["caption_groups"])} caption groups) -> {proj}/index.html')

    # Write .srt sidecar
    srt_path = os.path.join(vd, 'out', 'shorts', f'{name}.srt')
    with open(srt_path, 'w', encoding='utf-8') as f:
        for idx, g in enumerate(built['caption_groups'], 1):
            f.write(f'{idx}\n{_srt_ts(g["s"])} --> {_srt_ts(g["e"])}\n{g["text"]}\n\n')

    if args.no_render:
        return {'name': name, 'html': built['html'], 'srt': srt_path, 'duration': dur}

    # Lint + Render via HyperFrames
    run([sys.executable, os.path.join(HERE, 'hf_lint.py'), proj], f'hf lint {name}')
    hf_ver = os.environ.get('HF_VERSION', '0.8.181')
    qual = 'standard' if args.final else 'draft'
    raw_mp4 = os.path.join(proj, f'{name}_raw.mp4')
    if os.path.isfile(raw_mp4):
        os.remove(raw_mp4)
    t0 = time.time()
    run(['npx', '-y', f'hyperframes@{hf_ver}', 'render', '.', '-q', qual, '-f', str(FPS), '-o', raw_mp4],
        f'hf render {name}', cwd=proj)

    # Mix subtle music bed if enabled
    mix_wav = audio_wav
    if spec.get('music', True):
        bed_out = os.path.join(proj, 'audio_music.wav')
        try:
            run([sys.executable, os.path.join(HERE, 'bed-mix.py'), '--voice', audio_wav,
                 '--song', 'auto', '--under', '20', '--dur', f'{dur:.6f}', '--fade-in', '0.6', '--ring-out', '1.0',
                 '--out', bed_out], f'bed-mix {name}')
            mix_wav = bed_out
        except Exception as e:
            print(f'shorts: WARNING music bed skipped for {name}: {e}', file=sys.stderr)

    out_mp4 = os.path.join(vd, 'out', 'shorts', f'{name}.mp4')
    hold = 0.0 if args.no_hold else 1.0
    _loudnorm_finalize(raw_mp4, mix_wav, out_mp4, hold=hold, deband=args.deband)

    # Contact sheet for visual QA (8 frames across the Short)
    rev_jpg = os.path.join(vd, 'out', 'shorts', f'{name}_review.jpg')
    step_fps = max(0.1, 8.0 / max(1.0, dur))
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', out_mp4,
                    '-vf', f'fps={step_fps:.4f},scale=270:480,tile=4x2', '-frames:v', '1', '-update', '1', rev_jpg],
                   capture_output=True)

    lags = _sync_lag_ms(audio_wav, out_mp4, proj)
    max_lag = max(abs(x) for x in lags)
    out_info = probe(out_mp4)
    print(f'shorts: {out_mp4} ({out_info["width"]}x{out_info["height"]}, {out_info["duration"]:.2f}s, '
          f'sync {lags} ms, rendered in {time.time() - t0:.0f}s)')
    if max_lag > 35.0:
        print(f'  WARNING sync lag {max_lag:.1f} ms exceeds 1 frame — check {out_mp4}', file=sys.stderr)
    return {'name': name, 'mp4': out_mp4, 'srt': srt_path, 'review': rev_jpg, 'lags_ms': lags}


def main():
    ap = argparse.ArgumentParser(description='Pro 9:16 Shorts & Reels generator for Editor V2.')
    ap.add_argument('video_dir')
    ap.add_argument('--init', action='store_true', help='Suggest work/shorts.json + face centering check sheets')
    ap.add_argument('--force', action='store_true', help='Overwrite existing work/shorts.json on --init')
    ap.add_argument('--final', action='store_true', help='Render at standard/final quality')
    ap.add_argument('--only', default=None, help='Render only the named short')
    ap.add_argument('--nudge', type=int, default=None, help='Override horizontal face crop nudge in px')
    ap.add_argument('--no-render', action='store_true', help='Build HTML/assets/SRT only (skip HyperFrames render)')
    ap.add_argument('--deband', action='store_true', help='Apply deband + static grain on final encode')
    ap.add_argument('--no-hold', action='store_true', help='Skip 1s end-frame fade hold')
    a = ap.parse_args()

    vd = os.path.abspath(a.video_dir)
    if a.init:
        return init_shorts(vd, force=a.force, nudge=a.nudge or 0)

    sp = os.path.join(vd, 'work', 'shorts.json')
    if not os.path.isfile(sp):
        sys.exit(f'shorts: {sp} not found — run `ev2 shorts {a.video_dir} --init` first')
    try:
        cfg = json.load(open(sp, encoding='utf-8'))
    except ValueError as e:
        sys.exit(f'shorts: invalid JSON in {sp}: {e}')
    probs = SH.validate_shorts_cfg(cfg)
    if probs:
        print('shorts: fix these in work/shorts.json:')
        for p in probs:
            print(f'  FIX  {p}')
        return 1

    tl = TL.load(vd)
    env = detect_mode_and_cam(vd)
    theme, _ = load_theme(vd)
    words = load_words(vd)

    items = cfg['shorts']
    if a.only:
        items = [s for s in items if s['name'] == a.only]
        if not items:
            sys.exit(f'shorts: no short named {a.only!r} in {sp}')

    for spec in items:
        render_short(vd, spec, tl, env, theme, words, a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
