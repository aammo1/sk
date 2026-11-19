#!/usr/bin/env python3
"""GPU detection, caching, and FFmpeg/Whisper settings for editor-v2 (stdlib only)."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

CACHE = os.path.expanduser('~/.cache/editor-v2/gpu.json')


def _default_sessions_for_vram(vram_mb) -> int:
    """Conservative NVENC session cap for VRAM (<= 8 GB e.g. RTX 2070 -> 3; > 8 GB -> 6)."""
    if isinstance(vram_mb, (int, float)) and vram_mb > 0:
        return 3 if vram_mb <= 8500 else 6
    return 6


def max_sessions(vram_mb=None) -> int:
    """Maximum concurrent NVENC sessions allowed (env EV2_NVENC_SESSIONS overrides VRAM heuristic)."""
    env = os.environ.get('EV2_NVENC_SESSIONS', '').strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    if vram_mb is None:
        vram_mb = _cached_vram_mb()
    return _default_sessions_for_vram(vram_mb)


def _cached_vram_mb():
    if os.path.isfile(CACHE):
        try:
            st = json.load(open(CACHE, 'r', encoding='utf-8')).get('status') or {}
            v = st.get('vram_mb')
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
        except (OSError, ValueError):
            pass
    return None


def _off(reason, name=None, driver=None, vram_mb=None):
    return {
        'on': False,
        'reason': reason,
        'name': name,
        'driver': driver,
        'vram_mb': vram_mb,
        'nvenc': False,
        'sessions': max_sessions(vram_mb),
    }


def _ffmpeg_version_line():
    if not shutil.which('ffmpeg'):
        return None
    try:
        p = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True, text=True, timeout=5,
        )
        if p.returncode == 0 and p.stdout:
            return p.stdout.splitlines()[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _query_nvidia_smi():
    if not shutil.which('nvidia-smi'):
        return None, None, None, 'no NVIDIA GPU (nvidia-smi not found)'
    try:
        p = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, None, None, f'nvidia-smi failed: {e}'
    if p.returncode != 0 or not p.stdout.strip():
        err = (p.stderr or '').strip().splitlines()
        msg = err[-1] if err else f'exit {p.returncode}'
        return None, None, None, f'nvidia-smi failed: {msg}'
    line = p.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in line.split(',')]
    name = parts[0] if len(parts) >= 1 and parts[0] else None
    driver = parts[1] if len(parts) >= 2 and parts[1] else None
    vram_mb = None
    if len(parts) >= 3:
        try:
            vram_mb = int(float(parts[2]))
        except ValueError:
            vram_mb = None
    return name, driver, vram_mb, None


def busy_compute_procs() -> list:
    """List active GPU compute processes (pid, name, used_mb) to avoid VRAM collisions."""
    if not shutil.which('nvidia-smi'):
        return []
    try:
        p = subprocess.run(
            ['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if p.returncode != 0 or not p.stdout.strip():
        return []
    procs = []
    for line in p.stdout.strip().splitlines():
        parts = [x.strip() for x in line.split(',')]
        if len(parts) >= 3:
            try:
                procs.append({'pid': int(parts[0]), 'name': os.path.basename(parts[1]), 'used_mb': int(float(parts[2]))})
            except ValueError:
                continue
    return procs


def _read_cache(key):
    if not os.path.isfile(CACHE):
        return None
    try:
        with open(CACHE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get('key') == key and isinstance(data.get('status'), dict):
            st = dict(data['status'])
            st['sessions'] = max_sessions(st.get('vram_mb'))
            return st
    except (OSError, ValueError):
        return None
    return None


def _write_cache(key, st):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        payload = {
            'key': key,
            'status': st,
            'checked': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


def _probe_nvenc(name, driver, vram_mb=None):
    if not shutil.which('ffmpeg'):
        return _off('ffmpeg not found', name=name, driver=driver, vram_mb=vram_mb)
    try:
        enc = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _off(f'ffmpeg -encoders failed: {e}', name=name, driver=driver, vram_mb=vram_mb)
    if 'h264_nvenc' not in (enc.stdout or ''):
        return _off('ffmpeg has no h264_nvenc', name=name, driver=driver, vram_mb=vram_mb)

    try:
        test = subprocess.run(
            [
                'ffmpeg', '-nostdin', '-v', 'error',
                '-f', 'lavfi', '-i', 'color=c=black:s=256x144:r=30:d=0.3',
                '-c:v', 'h264_nvenc', '-f', 'null', '-',
            ],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _off(f'NVENC test encode failed: {e}', name=name, driver=driver, vram_mb=vram_mb)
    if test.returncode != 0:
        lines = [ln.strip() for ln in (test.stderr or '').splitlines() if ln.strip()]
        msg = lines[-1] if lines else f'exit {test.returncode}'
        return _off(f'NVENC test encode failed: {msg}', name=name, driver=driver, vram_mb=vram_mb)

    return {
        'on': True,
        'reason': 'ok',
        'name': name,
        'driver': driver,
        'vram_mb': vram_mb,
        'nvenc': True,
        'sessions': max_sessions(vram_mb),
    }


def status(refresh=False) -> dict:
    """Return cached GPU/NVENC availability dict."""
    env = os.environ.get('EV2_GPU', '').strip()
    if env == '0':
        return _off('EV2_GPU=0')
    if env == '1':
        refresh = True

    name, driver, vram_mb, smi_err = _query_nvidia_smi()
    if smi_err is not None:
        return _off(smi_err)

    key = {'driver': driver, 'vram_mb': vram_mb, 'ffmpeg': _ffmpeg_version_line()}
    if not refresh:
        cached = _read_cache(key)
        if cached is not None:
            return cached

    st = _probe_nvenc(name, driver, vram_mb=vram_mb)
    _write_cache(key, st)
    return st


def vram_mb():
    """Detected GPU VRAM in MiB, or None."""
    return status().get('vram_mb')


def recommended_jobs() -> int:
    """Safe parallel worker count for body_render / chunked encodes."""
    cpus = os.cpu_count() or 4
    base = max(1, min(4, cpus // 2))
    st = status()
    if st.get('on'):
        return max(1, min(base, max_sessions(st.get('vram_mb')) - 1))
    return base


def enabled() -> bool:
    """Return True when the GPU/NVENC path is active."""
    return bool(status()['on'])


def venc(cpu_args, cq):
    """Return NVENC encoder args at constant quality `cq` when on, else `list(cpu_args)`."""
    if not enabled():
        return list(cpu_args)
    out = [
        '-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq',
        '-rc', 'vbr', '-cq', str(int(cq)), '-b:v', '0',
        '-spatial-aq', '1', '-temporal-aq', '1', '-bf', '0',
    ]
    drop = {'-c:v', '-vcodec', '-preset', '-crf', '-tune', '-x264-params', '-keyint_min'}
    args = list(cpu_args)
    i = 0
    while i + 1 < len(args):
        if args[i] not in drop:
            out.extend([args[i], args[i + 1]])
        i += 2
    if i < len(args) and args[i] not in drop:
        out.append(args[i])
    return out


def whisper_device():
    """Return ('cuda', 'float16') when GPU is on, else ('cpu', 'int8')."""
    return ('cuda', 'float16') if enabled() else ('cpu', 'int8')


def _format_label(st) -> str:
    if st['on']:
        vram = f", {st['vram_mb'] // 1024}GB VRAM" if st.get('vram_mb') else ''
        sess = f", max {st.get('sessions', max_sessions())} NVENC" if st.get('sessions') else ''
        if st.get('name') and st.get('driver'):
            return f"gpu on ({st['name']}{vram}, driver {st['driver']}{sess})"
        if st.get('name'):
            return f"gpu on ({st['name']}{vram}{sess})"
        return f'gpu on{sess}'
    return f"gpu off ({st.get('reason', 'unknown')})"


def label() -> str:
    """Human-readable one-line GPU status."""
    return _format_label(status())


def main(argv=None):
    parser = argparse.ArgumentParser(prog='gpu.py')
    sub = parser.add_subparsers(dest='cmd')

    p_status = sub.add_parser('status')
    p_status.add_argument('--refresh', action='store_true')
    p_status.add_argument('--json', action='store_true')

    sub.add_parser('on')

    args = parser.parse_args(argv)
    if args.cmd == 'on':
        is_on = enabled()
        print('on' if is_on else 'off')
        return 0 if is_on else 1

    if args.cmd == 'status':
        st = status(refresh=args.refresh)
        if args.json:
            print(json.dumps(st, indent=2))
        else:
            print(_format_label(st))
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
