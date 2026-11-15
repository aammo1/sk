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


def max_sessions() -> int:
    """Maximum concurrent NVENC sessions allowed (default 8; env EV2_NVENC_SESSIONS)."""
    try:
        return max(1, int(os.environ.get('EV2_NVENC_SESSIONS', '8')))
    except ValueError:
        return 8


def _off(reason, name=None, driver=None):
    return {
        'on': False,
        'reason': reason,
        'name': name,
        'driver': driver,
        'nvenc': False,
        'sessions': max_sessions(),
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
        return None, None, 'no NVIDIA GPU (nvidia-smi not found)'
    try:
        p = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, None, f'nvidia-smi failed: {e}'
    if p.returncode != 0 or not p.stdout.strip():
        err = (p.stderr or '').strip().splitlines()
        msg = err[-1] if err else f'exit {p.returncode}'
        return None, None, f'nvidia-smi failed: {msg}'
    line = p.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in line.split(',', 1)]
    name = parts[0] if parts else None
    driver = parts[1] if len(parts) > 1 else None
    return name, driver, None


def _read_cache(key):
    if not os.path.isfile(CACHE):
        return None
    try:
        with open(CACHE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get('key') == key and isinstance(data.get('status'), dict):
            st = dict(data['status'])
            st['sessions'] = max_sessions()
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


def _probe_nvenc(name, driver):
    if not shutil.which('ffmpeg'):
        return _off('ffmpeg not found', name=name, driver=driver)
    try:
        enc = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _off(f'ffmpeg -encoders failed: {e}', name=name, driver=driver)
    if 'h264_nvenc' not in (enc.stdout or ''):
        return _off('ffmpeg has no h264_nvenc', name=name, driver=driver)

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
        return _off(f'NVENC test encode failed: {e}', name=name, driver=driver)
    if test.returncode != 0:
        lines = [ln.strip() for ln in (test.stderr or '').splitlines() if ln.strip()]
        msg = lines[-1] if lines else f'exit {test.returncode}'
        return _off(f'NVENC test encode failed: {msg}', name=name, driver=driver)

    return {
        'on': True,
        'reason': 'ok',
        'name': name,
        'driver': driver,
        'nvenc': True,
        'sessions': max_sessions(),
    }


def status(refresh=False) -> dict:
    """Return cached GPU/NVENC availability dict."""
    env = os.environ.get('EV2_GPU', '').strip()
    if env == '0':
        return _off('EV2_GPU=0')
    if env == '1':
        refresh = True

    name, driver, smi_err = _query_nvidia_smi()
    if smi_err is not None:
        return _off(smi_err)

    key = {'driver': driver, 'ffmpeg': _ffmpeg_version_line()}
    if not refresh:
        cached = _read_cache(key)
        if cached is not None:
            return cached

    st = _probe_nvenc(name, driver)
    _write_cache(key, st)
    return st


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
        if st.get('name') and st.get('driver'):
            return f"gpu on ({st['name']}, driver {st['driver']})"
        if st.get('name'):
            return f"gpu on ({st['name']})"
        return 'gpu on'
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
