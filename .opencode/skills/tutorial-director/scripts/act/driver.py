"""Desktop action Driver, keycode mapping, safety checks, and JSONL event log."""

from __future__ import annotations

import json
import os
import random
import re
import shlex
import shutil
import subprocess
import time
from typing import Any, Callable, Sequence

from . import hypr, mouse, targets

# Linux input-event-codes.h keycodes -> (code, display_name)
_KEY_TABLE: dict[str, tuple[int, str]] = {
    "esc": (1, "Esc"),
    "escape": (1, "Esc"),
    "1": (2, "1"),
    "2": (3, "2"),
    "3": (4, "3"),
    "4": (5, "4"),
    "5": (6, "5"),
    "6": (7, "6"),
    "7": (8, "7"),
    "8": (9, "8"),
    "9": (10, "9"),
    "0": (11, "0"),
    "-": (12, "-"),
    "minus": (12, "-"),
    "=": (13, "="),
    "equal": (13, "="),
    "backspace": (14, "Backspace"),
    "bs": (14, "Backspace"),
    "tab": (15, "Tab"),
    "q": (16, "Q"),
    "w": (17, "W"),
    "e": (18, "E"),
    "r": (19, "R"),
    "t": (20, "T"),
    "y": (21, "Y"),
    "u": (22, "U"),
    "i": (23, "I"),
    "o": (24, "O"),
    "p": (25, "P"),
    "[": (26, "["),
    "leftbrace": (26, "["),
    "]": (27, "]"),
    "rightbrace": (27, "]"),
    "enter": (28, "Enter"),
    "return": (28, "Enter"),
    "ctrl": (29, "Ctrl"),
    "control": (29, "Ctrl"),
    "lctrl": (29, "Ctrl"),
    "leftctrl": (29, "Ctrl"),
    "a": (30, "A"),
    "s": (31, "S"),
    "d": (32, "D"),
    "f": (33, "F"),
    "g": (34, "G"),
    "h": (35, "H"),
    "j": (36, "J"),
    "k": (37, "K"),
    "l": (38, "L"),
    ";": (39, ";"),
    "semicolon": (39, ";"),
    "'": (40, "'"),
    "apostrophe": (40, "'"),
    "`": (41, "`"),
    "grave": (41, "`"),
    "shift": (42, "Shift"),
    "lshift": (42, "Shift"),
    "leftshift": (42, "Shift"),
    "\\": (43, "\\"),
    "backslash": (43, "\\"),
    "z": (44, "Z"),
    "x": (45, "X"),
    "c": (46, "C"),
    "v": (47, "V"),
    "b": (48, "B"),
    "n": (49, "N"),
    "m": (50, "M"),
    ",": (51, ","),
    "comma": (51, ","),
    ".": (52, "."),
    "dot": (52, "."),
    "period": (52, "."),
    "/": (53, "/"),
    "slash": (53, "/"),
    "rshift": (54, "Shift"),
    "rightshift": (54, "Shift"),
    "alt": (56, "Alt"),
    "lalt": (56, "Alt"),
    "leftalt": (56, "Alt"),
    "space": (57, "Space"),
    "capslock": (58, "CapsLock"),
    "f1": (59, "F1"),
    "f2": (60, "F2"),
    "f3": (61, "F3"),
    "f4": (62, "F4"),
    "f5": (63, "F5"),
    "f6": (64, "F6"),
    "f7": (65, "F7"),
    "f8": (66, "F8"),
    "f9": (67, "F9"),
    "f10": (68, "F10"),
    "kpminus": (74, "-"),
    "kpplus": (78, "+"),
    "plus": (78, "+"),
    "f11": (87, "F11"),
    "f12": (88, "F12"),
    "kpenter": (96, "Enter"),
    "rctrl": (97, "Ctrl"),
    "rightctrl": (97, "Ctrl"),
    "sysrq": (99, "SysRq"),
    "ralt": (100, "AltGr"),
    "rightalt": (100, "AltGr"),
    "altgr": (100, "AltGr"),
    "home": (102, "Home"),
    "up": (103, "Up"),
    "pageup": (104, "PgUp"),
    "pgup": (104, "PgUp"),
    "prior": (104, "PgUp"),
    "left": (105, "Left"),
    "right": (106, "Right"),
    "end": (107, "End"),
    "down": (108, "Down"),
    "pagedown": (109, "PgDn"),
    "pgdn": (109, "PgDn"),
    "next": (109, "PgDn"),
    "insert": (110, "Insert"),
    "ins": (110, "Insert"),
    "delete": (111, "Delete"),
    "del": (111, "Delete"),
    "mute": (113, "Mute"),
    "volumedown": (114, "VolDown"),
    "volumeup": (115, "VolUp"),
    "pause": (119, "Pause"),
    "super": (125, "Super"),
    "meta": (125, "Super"),
    "win": (125, "Super"),
    "mod4": (125, "Super"),
    "lsuper": (125, "Super"),
    "leftmeta": (125, "Super"),
    "rsuper": (126, "Super"),
    "rmeta": (126, "Super"),
    "rightmeta": (126, "Super"),
    "menu": (139, "Menu"),
    "playpause": (164, "PlayPause"),
    "f13": (183, "F13"),
    "f14": (184, "F14"),
    "f15": (185, "F15"),
    "f16": (186, "F16"),
    "f17": (187, "F17"),
    "f18": (188, "F18"),
    "f19": (189, "F19"),
    "f20": (190, "F20"),
    "f21": (191, "F21"),
    "f22": (192, "F22"),
    "f23": (193, "F23"),
    "f24": (194, "F24"),
    "print": (210, "Print"),
    "printscreen": (210, "Print"),
}

_MOD_CODES = {29, 97, 56, 100, 42, 54, 125, 126}
_MOD_ORDER = ("Super", "Ctrl", "Alt", "AltGr", "Shift")
ALL_MODIFIER_KEYCODES = (29, 97, 56, 100, 42, 54, 125, 126)

TERMINAL_CLASSES = {
    "alacritty",
    "kitty",
    "foot",
    "footclient",
    "ghostty",
    "com.mitchellh.ghostty",
    "wezterm",
    "org.wezfurlong.wezterm",
    "konsole",
    "gnome-terminal",
    "gnome-terminal-server",
    "xfce4-terminal",
    "tilix",
    "rio",
    "st",
    "st-256color",
    "urxvt",
    "xterm",
}

DEFAULT_PACE: dict[str, float] = {
    "pre_click": 0.25,
    "settle_after": 1.0,
    "cps": 10.0,
}

SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:ant-|proj-|svcacct-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|"
        r"secret[_-]?key|client[_-]?secret|token|secret|password|passwd|pwd|bearer)"
        r"\b\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    ),
)


class ActionError(RuntimeError):
    """Base exception for desktop action failures."""


class StopRequested(ActionError):
    """Raised when `td stop` flag file is detected (caller should exit 130)."""

    exit_code = 130


class StepTimeoutError(ActionError):
    """Raised when a single step exceeds max_step_s (default 60s)."""


class SecretRefusedError(ActionError):
    """Raised when text to type matches a secret/credential pattern."""


class CheckFailed(ActionError):
    """Raised when a `check` action fails its image or text expectation."""


class WaitTimeoutError(ActionError):
    """Raised when `wait_for` times out."""


class ShellError(ActionError):
    """Raised when a `shell` action fails."""


def stop_file_path(override: str | None = None) -> str:
    if override:
        return override
    if os.environ.get("TD_STOP_FILE"):
        return os.environ["TD_STOP_FILE"]
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/td-runtime-{os.getuid()}"
    return os.path.join(rt, "td.stop")


def clear_stop(override: str | None = None) -> None:
    p = stop_file_path(override)
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass


def contains_secret(text: str) -> bool:
    """Return True if `text` matches any credential/API key/secret pattern."""
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            return True
    return False


def parse_combo(combo: str) -> tuple[list[tuple[int, str]], str]:
    """Parse `'super+alt+space'` into `([(125, 'Super'), ...], 'Super + Alt + Space')`."""
    raw = combo.strip()
    if not raw:
        raise ActionError("Empty key combo")

    # Support trailing '+' as plus key (e.g. 'ctrl++')
    parts: list[str] = []
    if raw.endswith("++"):
        prefix = raw[:-2].split("+")
        parts = [p for p in prefix if p] + ["+"]
    else:
        parts = [p.strip() for p in raw.split("+") if p.strip()]

    if not parts:
        raise ActionError(f"Invalid key combo: {combo!r}")

    parsed: list[tuple[int, str]] = []
    for tok in parts:
        key = tok.lower()
        if key not in _KEY_TABLE:
            raise ActionError(f"Unknown key name {tok!r} in combo {combo!r}")
        parsed.append(_KEY_TABLE[key])

    mods = [name for code, name in parsed if code in _MOD_CODES]
    keys = [name for code, name in parsed if code not in _MOD_CODES]
    ordered_mods = [m for m in _MOD_ORDER if m in mods]
    display = " + ".join(ordered_mods + keys)
    return parsed, display


def place(
    window: str,
    slot: Sequence[int] | str,
    *,
    layout: dict[str, Sequence[int]] | None = None,
    tol: int = 4,
    wait_s: float = 0.3,
    runner: hypr.CommandRunner | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[int, int, int, int]:
    """Float, resize, move `window` to `slot` (`[x, y, w, h]` or slot key in `layout`) and verify ±4 px."""
    return hypr.place(
        window,
        slot,
        layout=layout,
        tol=tol,
        wait_s=wait_s,
        runner=runner,
        sleep_fn=sleep_fn,
    )


def _default_tool_runner(
    cmd: Sequence[str],
    *,
    input_text: str | None = None,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class Driver:
    """Executes tutorial-director desktop action dicts with safety and JSONL event logging."""

    def __init__(
        self,
        *,
        event_log_path: str | None = None,
        checks_dir: str | None = None,
        calib: mouse.Calibration | None = None,
        calib_path: str | None = None,
        monitor: dict[str, Any] | None = None,
        pace: dict[str, float] | None = None,
        layout: dict[str, Sequence[int]] | None = None,
        max_step_s: float = 60.0,
        stop_file: str | None = None,
        dry_run: bool = False,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        ydotool_runner: hypr.CommandRunner | None = None,
        hypr_runner: hypr.CommandRunner | None = None,
        tool_runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.event_log_path = event_log_path
        self._log_fp = None
        if event_log_path:
            os.makedirs(os.path.dirname(os.path.abspath(event_log_path)), exist_ok=True)
            self._log_fp = open(event_log_path, "a", encoding="utf-8")

        self.checks_dir = checks_dir
        self._check_counts: dict[str, int] = {}
        self.calib = calib if calib is not None else mouse.load_calibration(calib_path)
        self._monitor = monitor
        self.pace = {**DEFAULT_PACE, **(pace or {})}
        self.layout = dict(layout or {})
        self.max_step_s = float(max_step_s)
        self.stop_file = stop_file_path(stop_file)
        self.dry_run = dry_run
        self.rng = rng or random.Random()
        self._clock = clock
        self._sleep = sleep_fn
        self._ydotool_runner = ydotool_runner
        self._hypr_runner = hypr_runner
        self._tool_runner = tool_runner

        self._ydotool_env: dict[str, str] | None = None
        self._held_keys: list[int] = []
        self._held_buttons: set[str] = set()
        self._cursor: tuple[float, float] | None = None

    def __enter__(self) -> Driver:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._log_fp is not None:
            try:
                self._log_fp.flush()
                self._log_fp.close()
            finally:
                self._log_fp = None

    def _get_ydotool_env(self) -> dict[str, str]:
        if self._ydotool_env is None:
            self._ydotool_env = mouse.ensure_ydotool(
                runner=self._ydotool_runner,
                sleep_fn=self._sleep,
            )
        return self._ydotool_env

    def _get_monitor(self) -> dict[str, Any] | None:
        if self._monitor is None:
            try:
                self._monitor = hypr.focused_monitor(runner=self._hypr_runner)
            except hypr.HyprError:
                self._monitor = None
        return self._monitor

    def _screen_xy(self, lx: float, ly: float) -> tuple[float, float]:
        mon = self._get_monitor()
        if mon is not None:
            mx, my, _, _ = hypr.monitor_logical_rect(mon)
            return round(lx - mx, 1), round(ly - my, 1)
        return round(lx, 1), round(ly, 1)

    def _log(self, event_type: str, **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {"t": round(self._clock(), 6), "type": event_type}
        entry.update(fields)
        if self._log_fp is not None:
            self._log_fp.write(json.dumps(entry) + "\n")
            self._log_fp.flush()
        return entry

    def check_stop(self) -> None:
        if os.path.exists(self.stop_file):
            raise StopRequested(f"Stop requested via {self.stop_file}")

    def _check_abort(self, deadline: float) -> None:
        self.check_stop()
        if self._clock() > deadline:
            raise StepTimeoutError(f"Step exceeded maximum duration of {self.max_step_s}s")

    def _sleep_checked(self, seconds: float, deadline: float) -> None:
        if seconds <= 0:
            self._check_abort(deadline)
            return
        end = self._clock() + seconds
        slept = 0.0
        while slept < seconds:
            self._check_abort(deadline)
            now = self._clock()
            rem = min(end - now, seconds - slept)
            if rem <= 0:
                break
            dt = min(0.05, rem)
            self._sleep(dt)
            after = self._clock()
            slept += (after - now) if after > now else dt

    def release_all(self) -> None:
        """Best-effort release of all pressed keys, modifiers, and mouse buttons."""
        try:
            env = self._get_ydotool_env()
        except Exception:
            self._held_keys.clear()
            self._held_buttons.clear()
            return

        # Release tracked non-modifier keys first, then all modifiers
        key_ups: list[str] = []
        seen: set[int] = set()
        for code in reversed(self._held_keys):
            if code not in seen:
                key_ups.append(f"{code}:0")
                seen.add(code)
        for code in ALL_MODIFIER_KEYCODES:
            if code not in seen:
                key_ups.append(f"{code}:0")
                seen.add(code)

        if key_ups:
            try:
                mouse.run_ydotool("key", *key_ups, runner=self._ydotool_runner, env=env)
            except Exception:
                pass

        btn_ups = [mouse.BUTTON_UP[b] for b in ("left", "right", "middle")]
        try:
            mouse.run_ydotool("click", *btn_ups, runner=self._ydotool_runner, env=env)
        except Exception:
            pass

        self._held_keys.clear()
        self._held_buttons.clear()

    def _current_cursor(self) -> tuple[float, float]:
        if self._cursor is not None:
            return self._cursor
        try:
            pos = hypr.cursor_pos(runner=self._hypr_runner)
            self._cursor = pos
            return pos
        except Exception:
            mon = self._get_monitor()
            if mon is not None:
                mx, my, lw, lh = hypr.monitor_logical_rect(mon)
                self._cursor = (mx + lw / 2.0, my + lh / 2.0)
            else:
                self._cursor = (0.0, 0.0)
            return self._cursor

    def _move_to(self, target: Any, deadline: float) -> tuple[float, float]:
        lx, ly = targets.resolve(
            target,
            monitor=self._get_monitor(),
            runner=self._tool_runner,
            hypr_runner=self._hypr_runner,
        )
        start = self._current_cursor()
        env = self._get_ydotool_env()

        def on_sample(t_s: float, x: float, y: float) -> None:
            sx, sy = self._screen_xy(x, y)
            entry = {"t": round(t_s, 6), "type": "move", "x": sx, "y": sy}
            if self._log_fp is not None:
                self._log_fp.write(json.dumps(entry) + "\n")
                self._log_fp.flush()

        ex, ey = mouse.move_cursor(
            start,
            (lx, ly),
            calib=self.calib,
            mon=self._get_monitor(),
            rng=self.rng,
            runner=self._ydotool_runner,
            env=env,
            clock=self._clock,
            sleep_fn=self._sleep,
            check_abort=lambda: self._check_abort(deadline),
            on_sample=on_sample,
        )
        self._cursor = (ex, ey)
        return ex, ey

    def _mouse_down(self, button: str, lx: float, ly: float) -> None:
        if button not in mouse.BUTTON_DOWN:
            raise ActionError(f"Unsupported mouse button: {button!r}")
        env = self._get_ydotool_env()
        self._held_buttons.add(button)
        mouse.run_ydotool("click", mouse.BUTTON_DOWN[button], runner=self._ydotool_runner, env=env)
        sx, sy = self._screen_xy(lx, ly)
        self._log("down", x=sx, y=sy, button=button)

    def _mouse_up(self, button: str, lx: float, ly: float) -> None:
        if button not in mouse.BUTTON_UP:
            raise ActionError(f"Unsupported mouse button: {button!r}")
        env = self._get_ydotool_env()
        mouse.run_ydotool("click", mouse.BUTTON_UP[button], runner=self._ydotool_runner, env=env)
        self._held_buttons.discard(button)
        sx, sy = self._screen_xy(lx, ly)
        self._log("up", x=sx, y=sy, button=button)

    def _press_combo(self, combo: str, deadline: float, *, log_event: bool = True) -> str:
        parsed, display = parse_combo(combo)
        env = self._get_ydotool_env()
        self._check_abort(deadline)

        codes = [code for code, _ in parsed]
        downs = [f"{c}:1" for c in codes]
        ups = [f"{c}:0" for c in reversed(codes)]

        self._held_keys.extend(codes)
        mouse.run_ydotool("key", *downs, runner=self._ydotool_runner, env=env)
        self._sleep_checked(0.03, deadline)
        mouse.run_ydotool("key", *ups, runner=self._ydotool_runner, env=env)
        for c in reversed(codes):
            if c in self._held_keys:
                self._held_keys.remove(c)

        if log_event:
            self._log("key", keys=display)
        return display

    def _run_wtype_char(self, ch: str) -> None:
        run = self._tool_runner or _default_tool_runner
        if self._tool_runner is None and not shutil.which("wtype"):
            raise ActionError("wtype not found. Install it with: sudo pacman -S wtype")

        if ch in ("\n", "\r"):
            cmd = ["wtype", "-k", "Return"]
        elif ch == "\t":
            cmd = ["wtype", "-k", "Tab"]
        else:
            cmd = ["wtype", "--", ch]

        res = run(cmd, timeout=5.0)
        if res.returncode != 0:
            # Never include typed characters in error logs
            raise ActionError(f"wtype exited with status {res.returncode}")

    def _run_wl_copy(self, text: str) -> None:
        run = self._tool_runner or _default_tool_runner
        if self._tool_runner is None and not shutil.which("wl-copy"):
            raise ActionError("wl-copy not found. Install it with: sudo pacman -S wl-clipboard")

        if self._tool_runner is not None:
            res = run(["wl-copy"], input_text=text, timeout=5.0)
        else:
            res = subprocess.run(
                ["wl-copy"],
                input=text,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        if res.returncode != 0:
            raise ActionError(f"wl-copy exited with status {res.returncode}")

    def _is_terminal_focused(self) -> bool:
        try:
            win = hypr.active_window(runner=self._hypr_runner)
        except hypr.HyprError:
            return False
        cls = str(win.get("class") or "").lower()
        icls = str(win.get("initialClass") or "").lower()
        return cls in TERMINAL_CLASSES or icls in TERMINAL_CLASSES

    def _type_chars(self, text: str, cps: float, deadline: float) -> None:
        base = 1.0 / max(1.0, float(cps))
        for idx, ch in enumerate(text):
            self._check_abort(deadline)
            self._run_wtype_char(ch)
            if idx < len(text) - 1:
                delay = base * self.rng.uniform(0.75, 1.25)
                if ch in (" ", ".", ",", ";", ":", "!", "?"):
                    delay *= 1.35
                self._sleep_checked(delay, deadline)

    def _exec_type(self, action: dict[str, Any], deadline: float) -> None:
        text = str(action.get("text", ""))
        if contains_secret(text):
            raise SecretRefusedError("Refused to type text matching a credential/secret pattern")

        cps = float(action.get("cps", self.pace.get("cps", 10.0)))
        paste = bool(action.get("paste", False))

        self._log("type_start")
        try:
            if paste and len(text) > 5:
                prefix_len = min(len(text), self.rng.randint(3, 5))
                prefix, rest = text[:prefix_len], text[prefix_len:]
                self._type_chars(prefix, cps, deadline)
                self._run_wl_copy(rest)
                self._sleep_checked(0.05, deadline)
                paste_combo = "ctrl+shift+v" if self._is_terminal_focused() else "ctrl+v"
                self._press_combo(paste_combo, deadline, log_event=False)
            elif text:
                self._type_chars(text, cps, deadline)
        finally:
            self._log("type_end")

        self._sleep_checked(float(self.pace.get("settle_after", 1.0)), deadline)

    def _exec_click(self, action: dict[str, Any], deadline: float) -> None:
        if action.get("to") is not None:
            lx, ly = self._move_to(action["to"], deadline)
        else:
            lx, ly = self._current_cursor()

        button = str(action.get("button", "left")).lower()
        double = bool(action.get("double", False))

        pre_click = float(self.pace.get("pre_click", 0.25))
        settle = max(pre_click, mouse.settle_duration(self.rng) if action.get("to") is not None else pre_click)
        self._sleep_checked(settle, deadline)

        clicks = 2 if double else 1
        for i in range(clicks):
            self._check_abort(deadline)
            self._mouse_down(button, lx, ly)
            self._sleep_checked(mouse.click_hold_duration(self.rng), deadline)
            self._mouse_up(button, lx, ly)
            if i + 1 < clicks:
                self._sleep_checked(self.rng.uniform(0.06, 0.09), deadline)

        self._sleep_checked(float(self.pace.get("settle_after", 1.0)), deadline)

    def _exec_scroll(self, action: dict[str, Any], deadline: float) -> None:
        if action.get("to") is not None:
            lx, ly = self._move_to(action["to"], deadline)
            self._sleep_checked(float(self.pace.get("pre_click", 0.25)), deadline)
        else:
            lx, ly = self._current_cursor()

        dy = int(action.get("dy", 0))
        env = self._get_ydotool_env()
        self._check_abort(deadline)
        mouse.run_ydotool("mousemove", "-w", "-x", "0", "-y", str(dy), runner=self._ydotool_runner, env=env)
        sx, sy = self._screen_xy(lx, ly)
        self._log("scroll", x=sx, y=sy, dy=dy)
        self._sleep_checked(float(self.pace.get("settle_after", 1.0)), deadline)

    def _exec_drag(self, action: dict[str, Any], deadline: float) -> None:
        fx, fy = self._move_to(action["from"], deadline)
        self._sleep_checked(float(self.pace.get("pre_click", 0.25)), deadline)
        self._mouse_down("left", fx, fy)
        self._sleep_checked(0.08, deadline)
        tx, ty = self._move_to(action["to"], deadline)
        self._sleep_checked(0.08, deadline)
        self._mouse_up("left", tx, ty)
        self._sleep_checked(float(self.pace.get("settle_after", 1.0)), deadline)

    def _exec_wait_for(self, action: dict[str, Any], deadline: float) -> None:
        timeout = float(action.get("timeout", 10.0))
        wait_deadline = min(deadline, self._clock() + timeout)
        mon = self._get_monitor()

        while True:
            self._check_abort(deadline)
            if "window" in action and action["window"]:
                if hypr.find_client(str(action["window"]), runner=self._hypr_runner) is not None:
                    return
            elif "image" in action and action["image"]:
                try:
                    targets.resolve(
                        {"image": action["image"], "threshold": action.get("threshold", 0.85)},
                        monitor=mon,
                        runner=self._tool_runner,
                        hypr_runner=self._hypr_runner,
                    )
                    return
                except targets.TargetNotFoundError:
                    pass
            elif "text" in action and action["text"]:
                try:
                    spec: dict[str, Any] = {"text": action["text"]}
                    if "lang" in action:
                        spec["lang"] = action["lang"]
                    targets.resolve(
                        spec,
                        monitor=mon,
                        runner=self._tool_runner,
                        hypr_runner=self._hypr_runner,
                    )
                    return
                except targets.TargetNotFoundError:
                    pass
            else:
                raise ActionError(f"wait_for requires window, image, or text: {action!r}")

            if self._clock() >= wait_deadline:
                raise WaitTimeoutError(f"wait_for timed out after {timeout}s: {action!r}")
            self._sleep_checked(min(0.2, max(0.01, wait_deadline - self._clock())), deadline)

    def _exec_shell(self, action: dict[str, Any], deadline: float) -> str:
        cmd = str(action.get("cmd", ""))
        if not cmd:
            raise ActionError("shell action missing 'cmd'")
        self._check_abort(deadline)

        if self._tool_runner is not None:
            rem = max(0.1, deadline - self._clock())
            res = self._tool_runner(["sh", "-c", cmd], timeout=rem)
            if res.returncode != 0:
                detail = (res.stderr or res.stdout or "").strip()
                raise ShellError(f"shell command exited {res.returncode}: {detail}")
            return res.stdout

        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            while proc.poll() is None:
                try:
                    self._check_abort(deadline)
                except ActionError:
                    proc.terminate()
                    try:
                        proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    raise
                self._sleep(0.05)
            out, err = proc.communicate()
            if proc.returncode != 0:
                detail = (err or out or "").strip()
                raise ShellError(f"shell command exited {proc.returncode}: {detail}")
            return out
        finally:
            if proc.poll() is None:
                proc.kill()

    def _exec_check(self, action: dict[str, Any], step_id: str, deadline: float) -> dict[str, Any]:
        self._check_abort(deadline)
        expect = str(action.get("expect", ""))
        n = self._check_counts.get(step_id, 0) + 1
        self._check_counts[step_id] = n

        checks_dir = self.checks_dir or os.path.join(os.getcwd(), "checks")
        os.makedirs(checks_dir, exist_ok=True)
        safe_step = re.sub(r"[^A-Za-z0-9_.-]+", "_", step_id)
        shot_path = os.path.join(checks_dir, f"{safe_step}-{n}.png")
        txt_path = os.path.join(checks_dir, f"{safe_step}-{n}.txt")
        manifest_path = os.path.join(checks_dir, "checks.jsonl")

        _, mon = targets.capture_screenshot(
            shot_path,
            monitor=self._get_monitor(),
            runner=self._tool_runner,
            hypr_runner=self._hypr_runner,
        )
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(expect + "\n")

        ok = True
        err_msg: str | None = None
        try:
            if action.get("image"):
                targets.resolve(
                    {"image": action["image"], "threshold": action.get("threshold", 0.85)},
                    monitor=mon,
                    screenshot_path=shot_path,
                    runner=self._tool_runner,
                    hypr_runner=self._hypr_runner,
                )
            if action.get("text"):
                spec: dict[str, Any] = {"text": action["text"]}
                if "lang" in action:
                    spec["lang"] = action["lang"]
                targets.resolve(
                    spec,
                    monitor=mon,
                    screenshot_path=shot_path,
                    runner=self._tool_runner,
                    hypr_runner=self._hypr_runner,
                )
        except targets.TargetNotFoundError as exc:
            ok = False
            err_msg = str(exc)

        record = {
            "step": step_id,
            "n": n,
            "screenshot": shot_path,
            "expect": expect,
            "image": action.get("image"),
            "text": action.get("text"),
            "ok": ok,
            "error": err_msg,
        }
        with open(manifest_path, "a", encoding="utf-8") as mf:
            mf.write(json.dumps(record) + "\n")

        if not ok:
            raise CheckFailed(f"Check failed for {step_id}#{n} (expect={expect!r}): {err_msg}")
        return record

    def place(
        self,
        window: str,
        slot: Sequence[int] | str,
        *,
        tol: int = 4,
        wait_s: float = 0.3,
    ) -> tuple[int, int, int, int]:
        return place(
            window,
            slot,
            layout=self.layout,
            tol=tol,
            wait_s=wait_s,
            runner=self._hypr_runner,
            sleep_fn=self._sleep,
        )

    def execute(self, action: dict[str, Any], *, step_id: str = "step") -> dict[str, Any]:
        """Execute a single validated action dict within `max_step_s`, releasing inputs on failure."""
        if not isinstance(action, dict):
            raise ActionError(f"Action must be a dict, got {type(action).__name__}")

        kind = action.get("do") or action.get("type")
        if not kind:
            raise ActionError(f"Action dict missing 'do'/'type': {action!r}")

        deadline = self._clock() + self.max_step_s
        self._check_abort(deadline)

        result: dict[str, Any] = {"type": kind, "step_id": step_id}
        try:
            if kind == "move":
                lx, ly = self._move_to(action["to"], deadline)
                result["x"], result["y"] = lx, ly
            elif kind == "click":
                self._exec_click(action, deadline)
            elif kind == "scroll":
                self._exec_scroll(action, deadline)
            elif kind == "drag":
                self._exec_drag(action, deadline)
            elif kind == "key":
                display = self._press_combo(str(action["combo"]), deadline, log_event=True)
                result["keys"] = display
                self._sleep_checked(float(self.pace.get("settle_after", 1.0)), deadline)
            elif kind == "type":
                self._exec_type(action, deadline)
            elif kind == "wait":
                self._sleep_checked(float(action.get("s", 0.0)), deadline)
            elif kind == "wait_for":
                self._exec_wait_for(action, deadline)
            elif kind == "focus":
                self._check_abort(deadline)
                hypr.focus_window(str(action["window"]), runner=self._hypr_runner)
                self._sleep_checked(0.15, deadline)
            elif kind == "workspace":
                self._check_abort(deadline)
                hypr.workspace(action["n"], runner=self._hypr_runner)
                self._sleep_checked(0.2, deadline)
            elif kind == "launch":
                self._check_abort(deadline)
                hypr.launch(str(action["cmd"]), runner=self._hypr_runner)
                if action.get("window"):
                    self._exec_wait_for(
                        {"window": action["window"], "timeout": action.get("timeout", 15.0)},
                        deadline,
                    )
                self._sleep_checked(float(self.pace.get("settle_after", 1.0)), deadline)
            elif kind == "move_window":
                self._check_abort(deadline)
                target_slot = action.get("to") if action.get("to") is not None else action.get("rect")
                if target_slot is None:
                    target_slot = action.get("slot")
                if target_slot is None:
                    raise ActionError(f"move_window requires 'to', 'rect', or 'slot': {action!r}")
                self.place(str(action["window"]), target_slot)
            elif kind == "shell":
                result["stdout"] = self._exec_shell(action, deadline)
            elif kind == "check":
                result["check"] = self._exec_check(action, step_id, deadline)
            else:
                raise ActionError(f"Unsupported action type: {kind!r}")
        except BaseException:
            self.release_all()
            raise

        return result
