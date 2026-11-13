#!/usr/bin/env python3
"""rec.py — log the cursor, clicks and shortcuts WHILE you record, so the edit knows exactly
where and when you clicked (zoom-to-click, click ripples, shortcut pills).

    ev2 rec install      run the watcher as a systemd user service (starts at login), then record as usual
    ev2 rec uninstall    stop and remove the service
    ev2 rec status       is the watcher running; can it see clicks/keys; the last logs
    ev2 rec watch        the watcher itself (foreground): logs while a screen recording runs
    ev2 rec test [S]     log for S seconds (default 10) and print what it saw: click and type to try it

What is logged, only while gpu-screen-recorder / wf-recorder runs:
  - cursor position, 60 Hz, from Hyprland's socket (no permission needed)
  - mouse button presses, from /dev/input (needs your user in the "input" group:
    `sudo usermod -aG input $USER`, then log out and in). Without it, clicks are inferred later.
  - keyboard: NEVER the characters. Only the time of each key press (for "typing" spans) and
    shortcuts with Ctrl/Alt/Super held (e.g. "Ctrl + S"), for the shortcut pills.
Logs: ~/.local/share/editor-v2/inputs/<recording-name>.json (`ev2 init` picks it up).
"""
import glob, json, os, select, socket, struct, subprocess, sys, time

LOG_DIR = os.path.expanduser('~/.local/share/editor-v2/inputs')
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


def session(sock, pid=None, seconds=None, verbose=False):
    """Log until the recorder exits (or for `seconds`). Returns the log dict."""
    log = {'version': 1, 'started_wall': time.time(), 'pid': pid, 'cursor': [], 'clicks': [], 'keys': [], 'combos': []}
    try:
        log['monitors'] = json.loads(hypr('j/monitors', sock)) if sock else []
    except Exception:
        log['monitors'] = []
    if pid:
        log['target'] = capture_target(pid)
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
    log['ended_wall'] = time.time()
    return log


def save(log):
    os.makedirs(LOG_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(log.get('video') or f'session-{int(log["started_wall"])}'))[0]
    p = os.path.join(LOG_DIR, base + '.json')
    json.dump(log, open(p, 'w'))
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
            print(f'ev2 rec: saved {p} ({len(log["cursor"])} cursor samples, {len(log["clicks"])} clicks, '
                  f'{len(log["keys"])} key presses, {len(log["combos"])} shortcuts)', flush=True)
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
    print(f'ev2 rec: unknown command {c!r} (install | uninstall | status | watch | test)', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
