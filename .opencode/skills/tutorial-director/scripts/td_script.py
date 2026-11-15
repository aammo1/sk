#!/usr/bin/env python3
"""td_script.py — load, validate, hash, and scaffold tutorial-director script.json files."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from typing import Any

DEFAULTS: dict[str, Any] = {
    'lang': 'darija',
    'voice': {'engine': 'golha', 'ref': None, 'speed': 1.0},
    'screen': {'monitor': 'auto', 'workspace': 9},
    'studio': {
        'font_px': 18,
        'browser_zoom': 1.25,
        'wallpaper': 'plain',
        'hide_bar': True,
        'cursor_px': 32,
    },
    'pace': {'cps': 10, 'settle_after': 1.0, 'pre_click': 0.25},
    'layout': {},
    'face': None,  # reserved, unused (no webcam/avatar in v1)
    'setup': [],
    'cleanup': [],
}

VALID_ENGINES = ('golha', 'lahgtna')
VALID_RECIPES = ('flow', 'steps', 'checklist', 'compare', 'stat', 'statement', 'screens')
VALID_BUTTONS = ('left', 'right', 'middle')
VALID_ACTIONS = (
    'key',
    'type',
    'move',
    'click',
    'scroll',
    'drag',
    'wait',
    'wait_for',
    'focus',
    'workspace',
    'launch',
    'move_window',
    'shell',
    'check',
)

SECRET_RE = re.compile(
    r'(?i:api[_-]?key|token|secret|password|passwd)'
    r'|(?i:\b(?:pwd|bearer)\b\s*[:=]\s*[\'"]?[^\s\'"]{6,})'
    r'|\bsk-(?:ant-|proj-|svcacct-)?[A-Za-z0-9_-]{16,}\b'
    r'|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b'
    r'|\bgithub_pat_[A-Za-z0-9_]{20,}\b'
    r'|\bAKIA[0-9A-Z]{16}\b'
    r'|\bxox[baprs]-[A-Za-z0-9-]{10,}\b'
    r'|\bAIza[0-9A-Za-z_-]{30,}\b'
    r'|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'
)

SAY_MAX_CHARS = 220
CHAPTER_MAX_CHARS = 40
CALLOUT_MAX_CHARS = 40
SENTENCE_TIP_MAX_WORDS = 15
INSERT_GAP_TIP_MAX_S = 90.0
RECAP_KEYWORDS = (
    'recap',
    'summary',
    'wrap',
    'ملخص',
    'الخلاصة',
    'خلاصة',
    'نلخصو',
    'نلخص',
    'تذكير',
    'ختام',
)
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')


def td_home() -> str:
    """Return the base tutorial-director directory (TD_HOME or ~/tutorial-director)."""
    return os.path.abspath(os.path.expanduser(os.environ.get('TD_HOME') or '~/tutorial-director'))


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_nonempty_str(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def resolve_run(run_or_path: str) -> str:
    """Resolve a run name, run directory path, or script.json path to an absolute run directory."""
    raw = os.path.expanduser(run_or_path)
    if os.path.isfile(raw):
        return os.path.dirname(os.path.abspath(raw))
    if os.path.isdir(raw):
        return os.path.abspath(raw)
    if not os.path.isabs(raw):
        sk_cand = os.path.join(SKILL_DIR, raw)
        if os.path.isfile(sk_cand):
            return os.path.dirname(os.path.abspath(sk_cand))
        if os.path.isdir(sk_cand):
            return os.path.abspath(sk_cand)
    if raw.endswith('.json'):
        return os.path.dirname(os.path.abspath(raw))
    if os.sep in raw or (os.altsep and os.altsep in raw):
        return os.path.abspath(raw)
    return os.path.join(td_home(), 'runs', raw)


def _script_file_for(run_or_path: str) -> str:
    raw = os.path.expanduser(run_or_path)
    if os.path.isfile(raw):
        return os.path.abspath(raw)
    if not os.path.isabs(raw):
        sk_cand = os.path.join(SKILL_DIR, raw)
        if os.path.isfile(sk_cand):
            return os.path.abspath(sk_cand)
    if raw.endswith('.json') and (os.sep in raw or not os.path.isdir(raw)):
        return os.path.abspath(raw)
    return os.path.join(resolve_run(run_or_path), 'script.json')


def apply_defaults(script: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of script with DEFAULTS merged for omitted optional fields."""
    out = copy.deepcopy(script)
    for key, default_val in DEFAULTS.items():
        if key not in out or out[key] is None and key != 'face':
            out[key] = copy.deepcopy(default_val)
        elif isinstance(default_val, dict) and isinstance(out.get(key), dict):
            merged = copy.deepcopy(default_val)
            merged.update(out[key])
            out[key] = merged
    return out


def load_script(run_or_path: str, merge_defaults: bool = True) -> dict[str, Any]:
    """Load script.json from a run name, run directory, or script.json path."""
    path = _script_file_for(run_or_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f'script.json not found: {path}')
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'{path}: top-level JSON value must be an object')
    return apply_defaults(data) if merge_defaults else data


def script_sha(script_or_path: dict[str, Any] | str) -> str:
    """Return deterministic SHA-256 hex digest of a script dict or script.json path/run."""
    if isinstance(script_or_path, dict):
        payload = json.dumps(apply_defaults(script_or_path), sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(payload).hexdigest()
    path = _script_file_for(str(script_or_path))
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        parsed = json.loads(raw.decode('utf-8'))
        if isinstance(parsed, dict):
            parsed = apply_defaults(parsed)
        payload = json.dumps(parsed, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(payload).hexdigest()
    except (UnicodeDecodeError, ValueError):
        return hashlib.sha256(raw).hexdigest()


def _validate_rect(val: Any, who: str, probs: list[str]) -> None:
    if not isinstance(val, list) or len(val) != 4 or not all(_is_num(x) for x in val):
        probs.append(f'{who}: expected [x, y, w, h] with 4 numbers')
        return
    if val[2] <= 0 or val[3] <= 0:
        probs.append(f'{who}: width and height must be > 0')


def _validate_target(tgt: Any, who: str, probs: list[str]) -> None:
    if isinstance(tgt, list):
        if len(tgt) != 2 or not all(_is_num(x) for x in tgt):
            probs.append(f'{who}: coordinate target must be [x, y]')
        return
    if isinstance(tgt, dict):
        if 'window' in tgt:
            if not _is_nonempty_str(tgt.get('window')):
                probs.append(f'{who}: target "window" must be a non-empty string')
            if 'at' in tgt:
                at = tgt['at']
                if not isinstance(at, list) or len(at) != 2 or not all(_is_num(x) and 0.0 <= x <= 1.0 for x in at):
                    probs.append(f'{who}: target "at" must be [fx, fy] with values in 0..1')
            return
        if 'image' in tgt:
            if not _is_nonempty_str(tgt.get('image')):
                probs.append(f'{who}: target "image" must be a non-empty path')
            return
        if 'text' in tgt:
            if not _is_nonempty_str(tgt.get('text')):
                probs.append(f'{who}: target "text" must be a non-empty string')
            return
    probs.append(f'{who}: target must be [x, y] or {{"window"|"image"|"text": ...}}')


def _validate_action(act: Any, who: str, probs: list[str]) -> None:
    if not isinstance(act, dict):
        probs.append(f'{who}: action must be an object')
        return
    do = act.get('do')
    if do not in VALID_ACTIONS:
        probs.append(f'{who}: unknown action {do!r} (valid: {", ".join(VALID_ACTIONS)})')
        return

    if do == 'key':
        if not _is_nonempty_str(act.get('combo')):
            probs.append(f'{who} (key): "combo" must be a non-empty string')
    elif do == 'type':
        text = act.get('text')
        if not isinstance(text, str) or not text:
            probs.append(f'{who} (type): "text" must be a non-empty string')
        elif SECRET_RE.search(text):
            probs.append(f'{who} (type): text matches secret/credential pattern — never type secrets on screen')
        if 'cps' in act and (not _is_num(act['cps']) or act['cps'] <= 0):
            probs.append(f'{who} (type): "cps" must be > 0')
        if 'paste' in act and not isinstance(act['paste'], bool):
            probs.append(f'{who} (type): "paste" must be true or false')
    elif do == 'move':
        if 'to' not in act:
            probs.append(f'{who} (move): "to" is required')
        else:
            _validate_target(act['to'], f'{who} (move)', probs)
    elif do == 'click':
        if 'to' in act and act['to'] is not None:
            _validate_target(act['to'], f'{who} (click)', probs)
        btn = act.get('button', 'left')
        if btn not in VALID_BUTTONS:
            probs.append(f'{who} (click): "button" must be one of {", ".join(VALID_BUTTONS)}')
        if 'double' in act and not isinstance(act['double'], bool):
            probs.append(f'{who} (click): "double" must be true or false')
    elif do == 'scroll':
        if not _is_num(act.get('dy')):
            probs.append(f'{who} (scroll): "dy" must be a number')
        if 'to' in act and act['to'] is not None:
            _validate_target(act['to'], f'{who} (scroll)', probs)
    elif do == 'drag':
        if 'from' not in act:
            probs.append(f'{who} (drag): "from" is required')
        else:
            _validate_target(act['from'], f'{who} (drag) from', probs)
        if 'to' not in act:
            probs.append(f'{who} (drag): "to" is required')
        else:
            _validate_target(act['to'], f'{who} (drag) to', probs)
    elif do == 'wait':
        if not _is_num(act.get('s')) or act['s'] < 0:
            probs.append(f'{who} (wait): "s" must be a number >= 0')
    elif do == 'wait_for':
        if not any(_is_nonempty_str(act.get(k)) for k in ('window', 'image', 'text')):
            probs.append(f'{who} (wait_for): provide one of "window", "image", or "text"')
        if 'timeout' in act and (not _is_num(act['timeout']) or act['timeout'] <= 0):
            probs.append(f'{who} (wait_for): "timeout" must be > 0')
    elif do == 'focus':
        if not _is_nonempty_str(act.get('window')):
            probs.append(f'{who} (focus): "window" must be a non-empty string')
    elif do == 'workspace':
        if not _is_int(act.get('n')) or act['n'] < 1:
            probs.append(f'{who} (workspace): "n" must be an integer >= 1')
    elif do == 'launch':
        if not _is_nonempty_str(act.get('cmd')):
            probs.append(f'{who} (launch): "cmd" must be a non-empty string')
        if 'window' in act and act['window'] is not None and not _is_nonempty_str(act['window']):
            probs.append(f'{who} (launch): "window" must be a non-empty string')
    elif do == 'move_window':
        if not _is_nonempty_str(act.get('window')):
            probs.append(f'{who} (move_window): "window" must be a non-empty string')
        if 'to' not in act:
            probs.append(f'{who} (move_window): "to" [x, y, w, h] is required')
        else:
            _validate_rect(act['to'], f'{who} (move_window) "to"', probs)
    elif do == 'shell':
        if not _is_nonempty_str(act.get('cmd')):
            probs.append(f'{who} (shell): "cmd" must be a non-empty string')
    elif do == 'check':
        if not any(_is_nonempty_str(act.get(k)) for k in ('expect', 'image', 'text')):
            probs.append(f'{who} (check): provide "expect" (or "image"/"text")')


def validate_script(script: Any) -> list[str]:
    """Validate a parsed script.json dictionary. Returns a list of FIX messages (empty = ready)."""
    probs: list[str] = []
    if not isinstance(script, dict):
        return ['script.json: top-level JSON must be an object']

    if not _is_nonempty_str(script.get('title')):
        probs.append('title: required non-empty string')
    if not _is_nonempty_str(script.get('promise')):
        probs.append('promise: required non-empty string')

    voice = script.get('voice')
    if voice is not None:
        if not isinstance(voice, dict):
            probs.append('voice: must be an object')
        else:
            eng = voice.get('engine')
            if eng not in VALID_ENGINES:
                probs.append(f'voice.engine: got {eng!r}, must be one of {", ".join(VALID_ENGINES)}')
            if 'speed' in voice and (not _is_num(voice['speed']) or not 0.5 <= voice['speed'] <= 2.0):
                probs.append('voice.speed: must be a number in 0.5..2.0')
    else:
        probs.append('voice: required object with "engine" ("golha" or "lahgtna")')

    screen = script.get('screen')
    if screen is not None:
        if not isinstance(screen, dict):
            probs.append('screen: must be an object')
        elif 'workspace' in screen and (not _is_int(screen['workspace']) or screen['workspace'] < 1):
            probs.append('screen.workspace: must be an integer >= 1')

    pace = script.get('pace')
    if pace is not None:
        if not isinstance(pace, dict):
            probs.append('pace: must be an object')
        else:
            if 'cps' in pace and (not _is_num(pace['cps']) or pace['cps'] <= 0):
                probs.append('pace.cps: must be > 0')
            for k in ('settle_after', 'pre_click'):
                if k in pace and (not _is_num(pace[k]) or pace[k] < 0):
                    probs.append(f'pace.{k}: must be >= 0')

    layout = script.get('layout') or {}
    if not isinstance(layout, dict):
        probs.append('layout: must be an object mapping slot names to [x, y, w, h]')
        layout = {}
    else:
        for slot, rect in layout.items():
            _validate_rect(rect, f'layout.{slot}', probs)

    for hook_list in ('setup', 'cleanup'):
        items = script.get(hook_list)
        if items is not None:
            if not isinstance(items, list):
                probs.append(f'{hook_list}: must be a list of actions')
            else:
                for i, act in enumerate(items, 1):
                    _validate_action(act, f'{hook_list} #{i}', probs)

    steps = script.get('steps')
    if not isinstance(steps, list) or not steps:
        probs.append('steps: required non-empty list of step objects')
        return probs

    seen_ids: set[str] = set()
    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            probs.append(f'step #{idx}: must be an object')
            continue

        sid = step.get('id')
        if not _is_nonempty_str(sid):
            probs.append(f'step #{idx}: "id" is required')
            label = f'step #{idx}'
        else:
            if sid in seen_ids:
                probs.append(f'step "{sid}": duplicate id')
            seen_ids.add(sid)
            label = f'step "{sid}"'

        say = step.get('say')
        if not _is_nonempty_str(say):
            probs.append(f'{label}: missing or empty "say"')
        elif len(say) > SAY_MAX_CHARS:
            probs.append(f'{label}: "say" is {len(say)} chars (keep <= {SAY_MAX_CHARS})')

        if 'chapter' in step and step['chapter'] is not None:
            ch = step['chapter']
            if not _is_nonempty_str(ch):
                probs.append(f'{label}: "chapter" must be a non-empty string')
            else:
                if len(ch) > CHAPTER_MAX_CHARS:
                    probs.append(f'{label}: chapter "{ch}" is {len(ch)} chars (keep <= {CHAPTER_MAX_CHARS})')
                parts = ch.split(' — ')
                if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                    probs.append(f'{label}: chapter "{ch}" must use one " — " separator (e.g. "Intro — المقدمة")')

        actions = step.get('actions')
        if not isinstance(actions, list) or not actions:
            probs.append(f'{label}: "actions" must be a non-empty list (>= 1 action)')
        else:
            for a_idx, act in enumerate(actions, 1):
                _validate_action(act, f'{label} action #{a_idx}', probs)

        if 'layout' in step and step['layout'] is not None:
            sl = step['layout']
            if not isinstance(sl, dict) or not _is_nonempty_str(sl.get('window')) or not _is_nonempty_str(sl.get('slot')):
                probs.append(f'{label}: "layout" must be {{"window": "...", "slot": "..."}}')
            elif sl['slot'] not in layout:
                probs.append(f'{label}: layout slot {sl["slot"]!r} is not defined in top-level "layout"')

        if 'callout' in step and step['callout'] is not None:
            co = step['callout']
            if not isinstance(co, dict) or not _is_nonempty_str(co.get('text')):
                probs.append(f'{label}: callout must be an object with non-empty "text"')
            else:
                if len(co['text']) > CALLOUT_MAX_CHARS:
                    probs.append(f'{label}: callout text is {len(co["text"])} chars (keep <= {CALLOUT_MAX_CHARS})')
                if 'at_action' in co:
                    aa = co['at_action']
                    n_act = len(actions) if isinstance(actions, list) else 0
                    if not _is_int(aa) or aa < 0 or (n_act and aa >= n_act):
                        probs.append(f'{label}: callout.at_action {aa!r} out of range for {n_act} action(s)')
                if 'dur' in co and (not _is_num(co['dur']) or not 1.0 <= co['dur'] <= 8.0):
                    probs.append(f'{label}: callout.dur must be 1..8 seconds')

        if 'insert' in step and step['insert'] is not None:
            ins = step['insert']
            if not isinstance(ins, dict):
                probs.append(f'{label}: "insert" must be an object')
            else:
                rec = ins.get('recipe')
                if rec not in VALID_RECIPES:
                    probs.append(f'{label}: insert.recipe {rec!r} invalid (use one of {", ".join(VALID_RECIPES)})')
                if 'dur' in ins and (not _is_num(ins['dur']) or not 1.5 <= ins['dur'] <= 30.0):
                    probs.append(f'{label}: insert.dur must be 1.5..30 seconds')
                if not isinstance(ins.get('data'), dict):
                    probs.append(f'{label}: insert.data must be an object')

        if 'pause_after' in step and step['pause_after'] is not None:
            if not _is_num(step['pause_after']) or step['pause_after'] < 0:
                probs.append(f'{label}: "pause_after" must be >= 0')

    return probs


def _load_voice_durs(run_dir: str | None) -> dict[str, float]:
    """Load rendered step durations from `<run_dir>/voice/index.json` if present."""
    if not run_dir:
        return {}
    idx_path = os.path.join(run_dir, 'voice', 'index.json')
    if not os.path.isfile(idx_path):
        return {}
    try:
        with open(idx_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, list):
        return {}
    durs: dict[str, float] = {}
    for entry in raw:
        if isinstance(entry, dict) and entry.get('id') and _is_num(entry.get('dur')) and entry['dur'] > 0:
            durs[str(entry['id'])] = float(entry['dur'])
    return durs


def _estimate_step_dur(step: dict[str, Any], voice_durs: dict[str, float]) -> float:
    """Estimate step duration in seconds from voice/index.json or word count + waits."""
    sid = str(step.get('id') or '')
    if sid in voice_durs:
        voice_s = voice_durs[sid]
    else:
        say = step.get('say')
        words = len(say.split()) if isinstance(say, str) else 0
        voice_s = max(0.5, words / 2.3) if words > 0 else 0.0
    actions = step.get('actions')
    wait_s = 0.0
    if isinstance(actions, list):
        for act in actions:
            if isinstance(act, dict) and act.get('do') == 'wait' and _is_num(act.get('s')):
                wait_s += max(0.0, float(act['s']))
    pause_after = float(step['pause_after']) if _is_num(step.get('pause_after')) else 0.4
    return max(voice_s, wait_s) + max(0.0, pause_after)


def collect_tips(script: Any, run_dir: str | None = None) -> list[str]:
    """Return non-blocking quality TIP messages for a script.json dictionary."""
    if not isinstance(script, dict):
        return []
    steps = script.get('steps')
    if not isinstance(steps, list) or not steps:
        return []

    tips: list[str] = []
    step_dicts = [s for s in steps if isinstance(s, dict)]
    if not step_dicts:
        return []

    # 1. No chapters
    if not any(_is_nonempty_str(s.get('chapter')) for s in step_dicts):
        tips.append('no chapters defined — add "chapter" (e.g. "Intro — المقدمة") on key steps')

    # 2. > 90 s without an insert
    voice_durs = _load_voice_durs(run_dir)
    since_insert = 0.0
    total_dur = 0.0
    has_insert = False
    for idx, step in enumerate(step_dicts, 1):
        label = f'step "{step["id"]}"' if _is_nonempty_str(step.get('id')) else f'step #{idx}'
        dur = _estimate_step_dur(step, voice_durs)
        total_dur += dur
        if isinstance(step.get('insert'), dict):
            if since_insert > INSERT_GAP_TIP_MAX_S:
                tips.append(f'~{since_insert:.0f}s before insert at {label} (> 90s without an explainer insert)')
            has_insert = True
            since_insert = 0.0
        else:
            since_insert += dur
    if not has_insert and total_dur > INSERT_GAP_TIP_MAX_S:
        tips.append(f'estimated duration ~{total_dur:.0f}s with no inserts (> 90s without an explainer insert)')
    elif has_insert and since_insert > INSERT_GAP_TIP_MAX_S:
        tips.append(f'~{since_insert:.0f}s after last insert (> 90s without an explainer insert)')

    # 3. Sentence > 15 words, and 4. launch without step layout
    for idx, step in enumerate(step_dicts, 1):
        label = f'step "{step["id"]}"' if _is_nonempty_str(step.get('id')) else f'step #{idx}'
        say = step.get('say')
        if isinstance(say, str) and say.strip():
            for seg in re.split(r'[.!?؟\n]+', say):
                words = [w for w in seg.strip().split() if w]
                if len(words) > SENTENCE_TIP_MAX_WORDS:
                    tips.append(f'{label}: sentence has {len(words)} words (aim <= {SENTENCE_TIP_MAX_WORDS} words)')

        actions = step.get('actions')
        if isinstance(actions, list):
            if any(isinstance(a, dict) and a.get('do') == 'launch' for a in actions) and not step.get('layout'):
                tips.append(f'{label}: launches a window without step "layout" — assign a layout slot')

    # 5. No recap step at the end
    last = step_dicts[-1]
    hay = ' '.join(str(last.get(k) or '') for k in ('id', 'chapter', 'say')).lower()
    if not any(kw in hay for kw in RECAP_KEYWORDS):
        tips.append('no recap step at the end — add a short 1-step recap/summary at the end')

    return tips


def _template_script(name: str) -> dict[str, Any]:
    tmpl_path = os.path.join(SKILL_DIR, 'templates', 'script.json')
    if os.path.isfile(tmpl_path):
        try:
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                data['title'] = f'TODO: {name}'
                data['promise'] = f'TODO: Learn *{name}* step by step'
                return data
        except (OSError, ValueError):
            pass
    return {
        'title': f'TODO: {name}',
        'promise': f'TODO: Learn *{name}* step by step',
        'lang': 'darija',
        'voice': {'engine': 'golha', 'ref': None, 'speed': 1.0},
        'screen': {'monitor': 'auto', 'workspace': 9},
        'studio': {
            'font_px': 18,
            'browser_zoom': 1.25,
            'wallpaper': 'plain',
            'hide_bar': True,
            'cursor_px': 32,
        },
        'pace': {'cps': 10, 'settle_after': 1.0, 'pre_click': 0.25},
        'layout': {
            'terminal': [160, 90, 1600, 900],
            'browser': [0, 0, 1920, 1080],
        },
        'setup': [],
        'steps': [
            {
                'id': 's01',
                'chapter': 'Intro — المقدمة',
                'say': 'TODO: سلام، اليوم غادي نشوفو كيفاش نخدمو بهاد الأداة.',
                'actions': [{'do': 'wait', 's': 0.5}],
            },
            {
                'id': 's02',
                'chapter': 'Demo — التطبيق',
                'say': 'TODO: دابا غادي نحلو التيرمينال ونكتبو الأمر اللول.',
                'actions': [
                    {'do': 'key', 'combo': 'super+Return'},
                    {'do': 'wait_for', 'window': 'class:Alacritty', 'timeout': 5},
                ],
                'callout': {'text': 'TODO: Terminal', 'at_action': 0},
            },
        ],
        'cleanup': [{'do': 'key', 'combo': 'Escape'}],
    }


def cmd_new(name: str) -> int:
    if not RUN_NAME_RE.match(name):
        print(f'new: invalid run name {name!r} (use letters, digits, ., _, -)', file=sys.stderr)
        return 2
    run_dir = os.path.join(td_home(), 'runs', name)
    script_path = os.path.join(run_dir, 'script.json')
    if os.path.exists(script_path):
        print(f'new: {script_path} already exists', file=sys.stderr)
        return 1
    for sub in ('voice', 'dry', 'rec', 'handoff'):
        os.makedirs(os.path.join(run_dir, sub), exist_ok=True)
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(_template_script(name), f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'new: created {run_dir}')
    print(f'  edit {script_path}, then run: td check {name}')
    return 0


def cmd_check(target: str) -> int:
    path = _script_file_for(target)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            script = json.load(f)
    except FileNotFoundError:
        print(f'check: {path} not found', file=sys.stderr)
        return 1
    except ValueError as e:
        print(f'  FIX   {path}: invalid JSON ({e})')
        print('check: 1 problem(s)')
        return 1

    probs = validate_script(script)
    run_dir = os.path.dirname(os.path.abspath(path))
    tips = collect_tips(script, run_dir=run_dir)
    for p in probs:
        print(f'  FIX   {p}')
    for t in tips:
        print(f'  TIP   {t}')
    print(f'check: {"ready" if not probs else str(len(probs)) + " problem(s)"}')
    return 1 if probs else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='td', description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_new = sub.add_parser('new', help='create a new run directory with template script.json')
    p_new.add_argument('name', help='run name (under $TD_HOME/runs/<name>)')

    p_check = sub.add_parser('check', help='validate script.json')
    p_check.add_argument('run', help='run name, run directory, or path to script.json')

    args = ap.parse_args(argv)
    if args.cmd == 'new':
        return cmd_new(args.name)
    if args.cmd == 'check':
        return cmd_check(args.run)
    return 2


if __name__ == '__main__':
    sys.exit(main())
