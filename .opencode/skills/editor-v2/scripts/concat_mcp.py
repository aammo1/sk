"""concat_mcp.py — minimal client for Concat's built-in MCP server (`concat --mcp headless`).

Used to prove a generated concat.json really opens in Concat: the engine migrates, parses
and "settles" the document exactly as the editor window would, and reports the timeline.

    from concat_mcp import concat_bin, open_and_read
    state = open_and_read('/path/to/project-folder')   # dict from timeline_read
"""
import json
import os
import shutil
import subprocess


def concat_bin():
    for c in [os.environ.get('EV2_CONCAT_BIN'), shutil.which('concat'), '/usr/bin/concat',
              os.path.expanduser('~/.local/share/concat/concat')]:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


class ConcatMCP:
    def __init__(self, binary=None, roots=None, timeout=60):
        self.bin = binary or concat_bin()
        if not self.bin:
            raise RuntimeError('Concat not found (install it or set EV2_CONCAT_BIN)')
        env = dict(os.environ)
        if roots:
            env['CONCAT_MCP_ROOTS'] = ':'.join(roots)
        self.p = subprocess.Popen([self.bin, '--mcp', 'headless'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        self.timeout = timeout
        self.i = 0
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                    'clientInfo': {'name': 'editor-v2', 'version': '2'}})
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + '\n')
        self.p.stdin.flush()

    def request(self, method, params=None):
        self.i += 1
        self._send({'jsonrpc': '2.0', 'id': self.i, 'method': method, 'params': params or {}})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError('Concat MCP server exited')
            m = json.loads(line)
            if m.get('id') == self.i:
                if 'error' in m:
                    raise RuntimeError(f'{method}: {m["error"].get("message")}')
                return m['result']

    def tool(self, name, args):
        res = self.request('tools/call', {'name': name, 'arguments': args})
        text = ''.join(c.get('text', '') for c in res.get('content', []) if c.get('type') == 'text')
        if res.get('isError'):
            raise RuntimeError(f'{name}: {text[:400]}')
        if 'structuredContent' in res:
            return res['structuredContent']
        try:
            return json.loads(text)
        except ValueError:
            return {'text': text}

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def open_and_read(folder):
    folder = os.path.abspath(folder)
    c = ConcatMCP(roots=[os.path.dirname(folder), os.path.expanduser('~')])
    try:
        c.tool('project_open', {'path': folder})
        state = c.tool('timeline_read', {'path': folder})
        c.tool('project_close', {'path': folder, 'save': False})
        return state
    finally:
        c.close()


def count_clips(state):
    """Best-effort count of clips in a timeline_read reply (shape varies by build)."""
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get('clips'), list):
                return len(o['clips'])
            for v in o.values():
                n = walk(v)
                if n is not None:
                    return n
        elif isinstance(o, list):
            for v in o:
                n = walk(v)
                if n is not None:
                    return n
        return None
    return walk(state)
