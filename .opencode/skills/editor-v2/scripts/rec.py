#!/usr/bin/env python3
"""rec.py — log the cursor, clicks and shortcuts WHILE you record, so the edit knows exactly
where and when you clicked (zoom-to-click, click ripples, shortcut pills).

    ev2 rec install      run the watcher as a systemd user service (starts at login), then record as usual
    ev2 rec uninstall    stop and remove the service
    ev2 rec status       is the watcher running; can it see clicks/keys; the last logs
    ev2 rec watch        the watcher itself (foreground): logs while a screen recording runs
    ev2 rec test [S]     log for S seconds (default 10) and print what it saw: click and type to try it
    ev2 rec cam on [--device D] [--size WxH] [--fps N] [--audio SRC]
                         also record the laptop webcam + microphone alongside every screen recording
    ev2 rec cam off      disable companion webcam + mic recording
    ev2 rec cam status   show camera config, v4l2 devices, and recent camera recordings
    ev2 rec cam test [S] record a short test clip (default 5s) and verify video + audio streams

What is logged, only while gpu-screen-recorder / wf-recorder runs:
  - cursor position, 60 Hz, from Hyprland's socket (no permission needed)
  - mouse button presses, from /dev/input (needs your user in the "input" group:
    `sudo usermod -aG input $USER`, then log out and in). Without it, clicks are inferred later.
  - keyboard: NEVER the characters. Only the time of each key press (for "typing" spans) and
    shortcuts with Ctrl/Alt/Super held (e.g. "Ctrl + S"), for the shortcut pills.
Logs: ~/.local/share/editor-v2/inputs/<recording-name>.json (`ev2 init` picks it up).
Camera files (when `cam` is on): ~/.local/share/editor-v2/cams/<recording-name>.mkv.
"""
import argparse, glob, json, os, select, shutil, socket, struct, subprocess, sys, time

LOG_DIR = os.path.expanduser('~/.local/share/editor-v2/inputs')
CAM_DIR = os.path.expanduser('~/.local/share/editor-v2/cams')
CONF = os.path.expanduser('~/.config/editor-v2/rec.json')
DEFAULT_CONF = {
    'cam': False,
    'device': '/dev/video0',
    'size': '1920x1080',
    'fps': 30,
    'input_format': 'mjpeg',
    'audio': 'default',
}
RUNTIME = os.environ.get('XDG_RUNTIME_DIR') or os.path.expanduser('~/.local/state/omarchy')
REC_FILE = os.path.join(RUNTIME, 'omarchy-screenrecord-filename')
SERVICE = os.path.expanduser('~/.config/systemd/user/ev2-rec.service')

EV_KEY = 1
BTN = {0x110: 'left', 0x111: 'right', 0x112: 'middle'}
MODS = {29: 'Ctrl', 97: 'Ctrl', 56: 'Alt', 100: 'AltGr', 125: 'Super', 126: 'Super', 42: 'Shift', 54: 'Shift'}
KEYNAMES = {1: 'Esc', 14: 'Backspace', 15: 'Tab', 28: 'Enter', 57: 'Space', 103: 'Up', 108: 'Down', 105: 'Left',
            106: 'Right', 102: 'Home', 107: 'End', 104: 'PgUp', 109: 'PgDn', 111: 'Delete', 110: 'Insert',
            12: '-', 13: '=', 26: '[', 27: ']', 39: ';', 40: "'", 41: '`', 43: '\\', 51: ',', 52: '.', 53: '/'}
for i, ch in enumerate('1234567890'):
    KEYNAMES[2 + i] = ch
for code, ch in zip([16, 17, 18, 19, 20, 21, 22, 23, 24, 25], 'QWERTYUIOP'):
    KEYNAMES[code] = ch
for code, ch in zip([30, 31, 32, 33, 34, 35, 36, 37, 38], 'ASDFGHJKL'):
    KEYNAMES[code] = ch
for code, ch in zip([44, 45, 46, 47, 48, 49, 50], 'ZXCVBNM'):
    KEYNAMES[code] = ch
for i in range(10):
    KEYNAMES[59 + i] = f'F{i + 1}'
KEYNAMES[87], KEYNAMES[88] = 'F11', 'F12'
EVFMT = 'llHHi'
EVSIZE = struct.calcsize(EVFMT)


# ------------------------------------------------------------------ Hyprland
def hypr_sock():
    sig = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')
    if not sig:
        cands = sorted(glob.glob(os.path.join(RUNTIME, 'hypr', '*', '.socket.sock')), key=os.path.getmtime)
        return cands[-1] if cands else None
    p = os.path.join(RUNTIME, 'hypr', sig, '.socket.sock')
    return p if os.path.exists(p) else None


def hypr(cmd, sock):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(0.5)
    try:
        s.connect(sock)
        s.sendall(cmd.encode())
        out = b''
        while True:
            d = s.recv(65536)
            if not d:
                break
            out += d
        return out.decode(errors='replace')
    finally:
        s.close()


def cursor(sock):
    try:
        x, y = hypr('cursorpos', sock).split(',')
        return float(x), float(y)
    except Exception:
        return None


# ------------------------------------------------------------------ evdev (raw, no library)
def input_devices():
    """(path, kind) for every readable event device that has keys or mouse buttons."""
    out, unreadable = [], 0
    try:
        txt = open('/proc/bus/input/devices').read()
    except OSError:
        return out, 0
    for block in txt.strip().split('\n\n'):
        lines = block.splitlines()
        handlers = next((l for l in lines if l.startswith('H: Handlers=')), '')
        ev = next((l for l in lines if l.startswith('B: EV=')), '')
        key = next((l for l in lines if l.startswith('B: KEY=')), '')
        name = next((l.split('=', 1)[1].strip('"') for l in lines if l.startswith('N: Name=')), '')
        evs = [h for h in handlers.split('=', 1)[-1].split() if h.startswith('event')]
        if not evs or not ev:
            continue
        evbits = int(ev.split('=', 1)[1], 16)
        if not evbits & (1 << EV_KEY):
            continue
        words = key.split('=', 1)[1].split() if key else []
        bits = 0
        for w in words:
            bits = (bits << 64) | int(w, 16)
        kind = 'mouse' if bits >> 0x110 & 1 else ('keyboard' if bits >> 30 & 1 else None)
        if not kind:
            continue
        path = '/dev/input/' + evs[0]
        if os.access(path, os.R_OK):
            out.append((path, kind, name))
        else:
            unreadable += 1
    return out, unreadable


class InputReader:
    def __init__(self):
        self.devs, self.unreadable = input_devices()
        self.fds = {}
        for p, kind, name in self.devs:
            try:
                self.fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = kind
            except OSError:
                pass
        self.mods = set()

    def poll(self, timeout):
        """[(wall_time, 'click', btn) | (wall, 'key', None) | (wall, 'combo', [names])]"""
        if not self.fds:
            time.sleep(timeout)
            return []
        r, _, _ = select.select(list(self.fds), [], [], timeout)
        out = []
        for fd in r:
            try:
                data = os.read(fd, EVSIZE * 64)
            except (BlockingIOError, OSError):
                continue
            for k in range(0, len(data) - EVSIZE + 1, EVSIZE):
                sec, usec, typ, code, val = struct.unpack(EVFMT, data[k:k + EVSIZE])
                if typ != EV_KEY:
                    continue
                t = sec + usec / 1e6
                if code in BTN:
                    if val == 1:
                        out.append((t, 'click', BTN[code]))
                    continue
                if code in MODS:
                    (self.mods.add if val else self.mods.discard)(MODS[code])
                    continue
                if val != 1:
                    continue
                hard = {'Ctrl', 'Alt', 'Super'} & self.mods
                if hard:
                    order = [m for m in ('Super', 'Ctrl', 'Alt', 'Shift') if m in self.mods]
                    out.append((t, 'combo', order + [KEYNAMES.get(code, f'#{code}')]))
                else:
                    out.append((t, 'key', None))
        return out

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass


# ------------------------------------------------------------------ recorder detection
def recorder_pid():
    for name in ('gpu-screen-reco', 'gpu-screen-recorder', 'wf-recorder'):
        r = subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', name], capture_output=True, text=True)
        for line in r.stdout.split():
            try:
                exe = os.path.basename(os.readlink(f'/proc/{line}/exe')).replace(' (deleted)', '')
            except OSError:
                continue
            if exe in ('gpu-screen-recorder', 'wf-recorder'):
                return int(line)
    return None


def capture_target(pid):
    """What the recorder captures: {'monitor': name} | {'region': [x, y, w, h]} (logical px) | {}."""
    try:
        args = open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\0')
    except OSError:
        return {}
    args = [a.decode(errors='replace') for a in args]
    for flag in ('-w', '-o', '-g'):
        if flag in args:
            v = args[args.index(flag) + 1]
            import re
            m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', v)
            if m:
                w, h, x, y = map(int, m.groups())
                return {'region': [x, y, w, h]}
            m = re.match(r'^(-?\d+),(-?\d+) (\d+)x(\d+)$', v)
            if m:
                x, y, w, h = map(int, m.groups())
                return {'region': [x, y, w, h]}
            if v != 'portal':
                return {'monitor': v}
    return {}


# ------------------------------------------------------------------ camera config & capture
def load_conf():
    conf = dict(DEFAULT_CONF)
    if os.path.isfile(CONF):
        try:
            with open(CONF, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                conf.update(data)
        except (OSError, ValueError):
            pass
    return conf


def save_conf(conf):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, 'w', encoding='utf-8') as f:
        json.dump(conf, f, indent=2)


def _venc():
    cpu_args = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import gpu
        return gpu.venc(cpu_args, 20)
    except Exception:
        return list(cpu_args)


def _cam_cmd(conf, path):
    venc = _venc()
    return [
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'v4l2', '-input_format', conf['input_format'], '-framerate', str(conf['fps']),
        '-video_size', conf['size'], '-thread_queue_size', '512', '-i', conf['device'],
        '-f', 'pulse', '-thread_queue_size', '512', '-i', conf['audio'],
        '-map', '0:v', '-map', '1:a', *venc, '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '160k', path,
    ]


def _read_text(path):
    try:
        with open(path, 'r', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def _last_log_line(path):
    lines = [ln.strip() for ln in _read_text(path).splitlines() if ln.strip()]
    return lines[-1] if lines else ''


def _notify_cam_error(err):
    if shutil.which('notify-send'):
        try:
            subprocess.run(
                ['notify-send', '-u', 'critical', 'ev2 rec', f'camera not recording: {err}'],
                capture_output=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def cam_start(conf):
    os.makedirs(CAM_DIR, exist_ok=True)
    path = os.path.join(CAM_DIR, f'session-{int(time.time())}.mkv')
    cmd = _cam_cmd(conf, path)
    started = time.time()
    log_path = path + '.log'
    with open(log_path, 'w') as log_f:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_f)
    return {
        'proc': p,
        'file': path,
        'log_file': log_path,
        'started_wall': started,
        'device': conf['device'],
        'size': conf['size'],
        'fps': conf['fps'],
        'checked': False,
        'failed': False,
    }


def cam_stop(c):
    p = c['proc']
    if p.poll() is None:
        try:
            p.stdin.write(b'q')
            p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
    return p.returncode


def session(sock, pid=None, seconds=None, verbose=False):
    """Log until the recorder exits (or for `seconds`). Returns the log dict."""
    log = {'version': 1, 'started_wall': time.time(), 'pid': pid, 'cursor': [], 'clicks': [], 'keys': [], 'combos': []}
    try:
        log['monitors'] = json.loads(hypr('j/monitors', sock)) if sock else []
    except Exception:
        log['monitors'] = []
    if pid:
        log['target'] = capture_target(pid)
    cam = None
    if pid:
        conf = load_conf()
        if conf.get('cam'):
            try:
                cam = cam_start(conf)
            except OSError as e:
                err = str(e)
                log['cam'] = {'ok': False, 'error': err}
                _notify_cam_error(err)
    rd = InputReader()
    log['input_devices'] = len(rd.fds)
    log['input_unreadable'] = rd.unreadable
    video, last = None, None
    t_end = time.time() + seconds if seconds else None
    try:
        while True:
            now = time.time()
            if t_end and now >= t_end:
                break
            if pid and not os.path.exists(f'/proc/{pid}'):
                break
            if cam and not cam['checked'] and (now - cam['started_wall']) >= 2.0:
                cam['checked'] = True
                if cam['proc'].poll() is not None:
                    err = _last_log_line(cam['log_file']) or f'ffmpeg exited with {cam["proc"].returncode}'
                    cam['failed'] = True
                    log['cam'] = {'ok': False, 'error': err}
                    _notify_cam_error(err)
            if video is None and os.path.isfile(REC_FILE):
                try:
                    v = open(REC_FILE).read().strip()
                    if v and os.path.exists(v):
                        video = v
                        log['video'] = v
                        log['video_seen_wall'] = now
                        log['video_ctime'] = os.stat(v).st_mtime
                except OSError:
                    pass
            for t, kind, val in rd.poll(1 / 60):
                if kind == 'click':
                    log['clicks'].append([round(t, 4), val])
                    if verbose:
                        print(f'  click {val}')
                elif kind == 'key':
                    log['keys'].append(round(t, 4))
                else:
                    log['combos'].append([round(t, 4), val])
                    if verbose:
                        print(f'  shortcut {" + ".join(val)}')
            if sock:
                p = cursor(sock)
                if p and p != last:
                    log['cursor'].append([round(time.time(), 4), p[0], p[1]])
                    last = p
    finally:
        rd.close()
        if cam:
            rc = cam_stop(cam)
            if not cam['failed']:
                ok_size = os.path.isfile(cam['file']) and os.path.getsize(cam['file']) >= 10240
                if rc == 0 and ok_size:
                    log['cam'] = {
                        'ok': True,
                        'file': cam['file'],
                        'started_wall': cam['started_wall'],
                        'device': cam['device'],
                        'size': cam['size'],
                        'fps': cam['fps'],
                    }
                else:
                    err = _last_log_line(cam['log_file']) or (
                        f'ffmpeg exited with {rc}' if rc != 0 else 'camera file missing or too small'
                    )
                    log['cam'] = {'ok': False, 'error': err}
                    _notify_cam_error(err)
    log['ended_wall'] = time.time()
    return log


def save(log):
    os.makedirs(LOG_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(log.get('video') or f'session-{int(log["started_wall"])}'))[0]
    cam = log.get('cam')
    if isinstance(cam, dict) and cam.get('ok'):
        src = cam.get('file')
        if src and os.path.isfile(src):
            dst = os.path.join(CAM_DIR, f'{base}.mkv')
            n = 2
            while os.path.exists(dst) and os.path.abspath(dst) != os.path.abspath(src):
                dst = os.path.join(CAM_DIR, f'{base}-{n}.mkv')
                n += 1
            if os.path.abspath(dst) != os.path.abspath(src):
                os.replace(src, dst)
                if os.path.isfile(src + '.log'):
                    os.replace(src + '.log', dst + '.log')
                cam['file'] = dst
    p = os.path.join(LOG_DIR, base + '.json')
    with open(p, 'w') as f:
        json.dump(log, f)
    return p


# ------------------------------------------------------------------ commands
def cmd_watch():
    sock = hypr_sock()
    print(f'ev2 rec: watching for screen recordings (cursor via {"Hyprland" if sock else "nothing: no Hyprland socket"})', flush=True)
    while True:
        pid = recorder_pid()
        if pid:
            print(f'ev2 rec: recording started (pid {pid}), logging', flush=True)
            log = session(sock or hypr_sock(), pid)
            p = save(log)
            cam_info = ''
            if 'cam' in log:
                if log['cam'].get('ok'):
                    cam_info = f', camera {log["cam"]["file"]}'
                else:
                    cam_info = f', camera FAILED ({log["cam"].get("error", "unknown")})'
            print(f'ev2 rec: saved {p} ({len(log["cursor"])} cursor samples, {len(log["clicks"])} clicks, '
                  f'{len(log["keys"])} key presses, {len(log["combos"])} shortcuts){cam_info}', flush=True)
        time.sleep(0.25)


def cmd_test(seconds):
    sock = hypr_sock()
    devs, unreadable = input_devices()
    print(f'ev2 rec test: {seconds:g}s. Move the mouse, click, type, press a shortcut (e.g. Ctrl+S in a text field)...')
    log = session(sock, None, seconds, verbose=True)
    print(f'\ncursor samples: {len(log["cursor"])}  {"OK" if log["cursor"] else "NONE (no Hyprland socket?)"}')
    print(f'clicks: {len(log["clicks"])}  key presses: {len(log["keys"])}  shortcuts: {len(log["combos"])}')
    if not devs:
        print('\nclicks/keys: NOT VISIBLE. Your user cannot read /dev/input. Run once:\n'
              '    sudo usermod -aG input $USER\n'
              'then log out and back in. (Without it, clicks are guessed from the cursor and the screen.)')
    return 0


def service_text():
    ev2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ev2')
    return f'''[Unit]
Description=Editor V2 input logger (cursor, clicks, shortcuts while a screen recording runs)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/env bash {ev2} rec watch
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
'''


def cmd_install():
    os.makedirs(os.path.dirname(SERVICE), exist_ok=True)
    open(SERVICE, 'w').write(service_text())
    subprocess.run(['systemctl', '--user', 'daemon-reload'])
    r = subprocess.run(['systemctl', '--user', 'enable', '--now', 'ev2-rec.service'], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr.strip())
        return 1
    print(f'ev2 rec: installed and started {SERVICE}')
    devs, _ = input_devices()
    if not devs:
        print('ev2 rec: cursor is logged; for exact clicks and shortcuts also run once:\n'
              '    sudo usermod -aG input $USER     (then log out and in, and `ev2 rec install` again)')
    print('ev2 rec: now record with Omarchy as usual. `ev2 init` picks up the log automatically.')
    return 0


def cmd_uninstall():
    subprocess.run(['systemctl', '--user', 'disable', '--now', 'ev2-rec.service'], capture_output=True)
    if os.path.isfile(SERVICE):
        os.remove(SERVICE)
    subprocess.run(['systemctl', '--user', 'daemon-reload'])
    print('ev2 rec: removed')
    return 0


def cmd_status():
    r = subprocess.run(['systemctl', '--user', 'is-active', 'ev2-rec.service'], capture_output=True, text=True)
    devs, unreadable = input_devices()
    print(f'watcher service: {r.stdout.strip() or "not installed"}')
    print(f'cursor (Hyprland socket): {"yes" if hypr_sock() else "no"}')
    print(f'clicks/keys (/dev/input): {"yes, " + str(len(devs)) + " devices" if devs else "no (sudo usermod -aG input $USER, then re-login)"}')
    logs = sorted(glob.glob(os.path.join(LOG_DIR, '*.json')), key=os.path.getmtime)[-5:]
    for p in logs:
        try:
            d = json.load(open(p))
            print(f'  {os.path.basename(p)}: {len(d.get("clicks", []))} clicks, {len(d.get("cursor", []))} cursor samples')
        except ValueError:
            pass
    return 0


def _parse_fps(rate):
    if not rate:
        return 0.0
    s = str(rate)
    if '/' not in s:
        try:
            return float(s)
        except ValueError:
            return 0.0
    num, den = s.split('/', 1)
    try:
        n, d = float(num), float(den)
        return round(n / d, 2) if d else 0.0
    except ValueError:
        return 0.0


def _fmt_size(nbytes):
    if nbytes < 1024:
        return f'{nbytes} B'
    if nbytes < 1024 * 1024:
        return f'{nbytes / 1024:.1f} KB'
    return f'{nbytes / (1024 * 1024):.1f} MB'


def cmd_cam_on(argv):
    p = argparse.ArgumentParser(prog='ev2 rec cam on')
    p.add_argument('--device', help='v4l2 device (e.g. /dev/video0)')
    p.add_argument('--size', help='capture size WxH (e.g. 1920x1080)')
    p.add_argument('--fps', type=int, help='capture framerate (e.g. 30)')
    p.add_argument('--audio', help='PulseAudio/PipeWire source (e.g. default)')
    args = p.parse_args(argv)
    if args.fps is not None and args.fps <= 0:
        print('ev2 rec cam on: --fps must be > 0', file=sys.stderr)
        return 2
    conf = load_conf()
    conf['cam'] = True
    if args.device:
        conf['device'] = args.device
    if args.size:
        conf['size'] = args.size
    if args.fps is not None:
        conf['fps'] = args.fps
    if args.audio:
        conf['audio'] = args.audio
    save_conf(conf)
    print(f'ev2 rec: camera recording ON ({conf["device"]}, {conf["size"]}@{conf["fps"]}, mic {conf["audio"]}). '
          f'Record without the Omarchy webcam overlay.')
    r = subprocess.run(['systemctl', '--user', 'is-active', 'ev2-rec.service'], capture_output=True, text=True)
    if r.stdout.strip() != 'active':
        print('ev2 rec: warning: ev2-rec.service is not active (run ev2 rec install)', file=sys.stderr)
    return 0


def cmd_cam_off(argv):
    p = argparse.ArgumentParser(prog='ev2 rec cam off')
    p.parse_args(argv)
    conf = load_conf()
    conf['cam'] = False
    save_conf(conf)
    print('ev2 rec: camera recording OFF')
    return 0


def cmd_cam_status(argv):
    p = argparse.ArgumentParser(prog='ev2 rec cam status')
    p.parse_args(argv)
    conf = load_conf()
    print(f'camera config ({CONF}):')
    print(json.dumps(conf, indent=2))
    if shutil.which('v4l2-ctl'):
        r = subprocess.run(['v4l2-ctl', '--list-devices'], capture_output=True, text=True)
        out = (r.stdout or '').strip()
        print('v4l2 devices:')
        print(out if out else '  (none)')
    cams = sorted(glob.glob(os.path.join(CAM_DIR, '*.mkv')), key=os.path.getmtime)[-5:]
    print(f'recent camera recordings ({CAM_DIR}):')
    if not cams:
        print('  (none)')
    for path in cams:
        try:
            sz = _fmt_size(os.path.getsize(path))
        except OSError:
            sz = '?'
        print(f'  {os.path.basename(path)} ({sz})')
    return 0


def cmd_cam_test(argv):
    p = argparse.ArgumentParser(prog='ev2 rec cam test')
    p.add_argument('seconds', nargs='?', type=float, default=5.0, help='duration in seconds (default 5)')
    args = p.parse_args(argv)
    if args.seconds <= 0:
        print('ev2 rec cam test: duration must be > 0', file=sys.stderr)
        return 2
    conf = load_conf()
    out_dir = '/tmp/opencode'
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'ev2-cam-test.mkv')
    log_path = path + '.log'
    cmd = _cam_cmd(conf, path)
    print(f'ev2 rec cam test: recording {args.seconds:g}s ({conf["device"]}, {conf["size"]}@{conf["fps"]}, mic {conf["audio"]}) -> {path}')
    try:
        with open(log_path, 'w') as log_f:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_f)
    except OSError as e:
        print(f'ev2 rec cam test: failed to start ffmpeg: {e}', file=sys.stderr)
        return 1
    try:
        proc.wait(timeout=args.seconds)
    except subprocess.TimeoutExpired:
        pass
    rc = cam_stop({'proc': proc})
    if rc != 0 or not os.path.isfile(path) or os.path.getsize(path) < 10240:
        err_text = _read_text(log_path)
        last_line = _last_log_line(log_path) or f'ffmpeg exited with {rc}'
        print(f'ev2 rec cam test: failed ({last_line})', file=sys.stderr)
        if 'device or resource busy' in err_text.lower():
            print('the webcam is in use (Omarchy webcam overlay or another app): close it', file=sys.stderr)
        return 1
    probe = subprocess.run(
        [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels',
            '-show_entries', 'format=duration,size',
            '-of', 'json', path,
        ],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        print(f'ev2 rec cam test: ffprobe failed: {probe.stderr.strip()}', file=sys.stderr)
        return 1
    info = json.loads(probe.stdout or '{}')
    streams = info.get('streams', [])
    v = next((s for s in streams if s.get('codec_type') == 'video'), None)
    a = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    if v:
        fps = _parse_fps(v.get('avg_frame_rate')) or _parse_fps(v.get('r_frame_rate'))
        print(f'video: {v.get("width")}x{v.get("height")} @ {fps:g} fps ({v.get("codec_name")})')
    else:
        print('video: none')
    if a:
        print(f'audio: yes ({a.get("codec_name")}, {a.get("sample_rate")} Hz, {a.get("channels")} ch)')
    else:
        print('audio: no')
    return 0


def cmd_cam(argv):
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print('Usage: ev2 rec cam <on|off|status|test> [options]')
        return 0 if argv else 2
    sub, rest = argv[0], argv[1:]
    if sub == 'on':
        return cmd_cam_on(rest)
    if sub == 'off':
        return cmd_cam_off(rest)
    if sub == 'status':
        return cmd_cam_status(rest)
    if sub == 'test':
        return cmd_cam_test(rest)
    print(f'ev2 rec cam: unknown subcommand {sub!r} (on | off | status | test)', file=sys.stderr)
    return 2


def main(argv):
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    c = argv[0]
    if c == 'watch':
        return cmd_watch()
    if c == 'test':
        return cmd_test(float(argv[1]) if len(argv) > 1 else 10.0)
    if c == 'install':
        return cmd_install()
    if c == 'uninstall':
        return cmd_uninstall()
    if c == 'status':
        return cmd_status()
    if c == 'cam':
        return cmd_cam(argv[1:])
    print(f'ev2 rec: unknown command {c!r} (install | uninstall | status | watch | test | cam)', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
