#!/usr/bin/env python3
"""CLI entry point for `td act ...` and `td stop`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from act import hypr, mouse
from act.driver import (
    ActionError,
    Driver,
    StopRequested,
    clear_stop,
    stop_file_path,
)


def _pick_terminal() -> tuple[str, str]:
    """Return `(launch_cmd, window_selector)` for an available Wayland terminal."""
    env_term = os.environ.get("TERMINAL")
    candidates = []
    if env_term:
        candidates.append((env_term, f"class:{os.path.basename(env_term)}"))
    candidates.extend(
        [
            ("alacritty", "class:Alacritty"),
            ("kitty", "class:kitty"),
            ("foot", "class:foot"),
            ("ghostty", "class:com.mitchellh.ghostty"),
        ]
    )
    for cmd, win in candidates:
        bin_name = cmd.split()[0]
        if shutil.which(bin_name):
            return cmd, win
    raise ActionError(
        "No supported terminal emulator found (tried $TERMINAL, alacritty, kitty, foot, ghostty)"
    )


def summarize_event_log(path: str) -> dict:
    events = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    counts = Counter(e.get("type") for e in events)
    dur = (events[-1]["t"] - events[0]["t"]) if len(events) >= 2 else 0.0
    return {
        "path": path,
        "total": len(events),
        "counts": dict(counts),
        "duration_s": round(dur, 3),
    }


def cmd_stop() -> int:
    p = stop_file_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"{time.time():.6f} pid={os.getpid()}\n")

    # Best-effort immediate release of modifiers/mouse buttons
    try:
        Driver(stop_file=p).release_all()
    except Exception:
        pass

    print(f"td stop: signaled stop via {p}")
    return 0


def cmd_calib() -> int:
    calib = mouse.calibrate()
    print(
        f"td calib: saved {mouse.calib_path()} "
        f"(monitor={calib.monitor_name}, scale={calib.monitor_scale}, max_err={calib.residual_px}px)"
    )
    return 0


def cmd_test(log_path: str | None = None) -> int:
    clear_stop()
    mouse.ensure_ydotool()

    calib = mouse.calibrate()
    print(
        f"td act test: calibrated {calib.monitor_name or 'monitor'} "
        f"(scale={calib.monitor_scale}, max_err={calib.residual_px}px) -> {mouse.calib_path()}"
    )

    mon = hypr.focused_monitor()
    if mon is None:
        raise ActionError("No focused monitor found via hyprctl")
    orig_ws = (mon.get("activeWorkspace") or {}).get("id")
    mx, my, lw, lh = hypr.monitor_logical_rect(mon)
    test_ws = hypr.empty_workspace()
    term_cmd, term_win = _pick_terminal()

    if log_path is None:
        tmp_dir = tempfile.mkdtemp(prefix="td-act-test-")
        log_path = os.path.join(tmp_dir, "events.jsonl")

    cx, cy = mx + lw * 0.5, my + lh * 0.5
    half = min(lw, lh) * 0.15
    square = [
        [cx - half, cy - half],
        [cx + half, cy - half],
        [cx + half, cy + half],
        [cx - half, cy + half],
        [cx - half, cy - half],
    ]

    actions = [
        {"type": "workspace", "n": test_ws},
        {"type": "launch", "cmd": term_cmd, "window": term_win, "timeout": 10.0},
        {"type": "focus", "window": term_win},
        *[{"type": "move", "to": pt} for pt in square],
        {"type": "click", "to": [cx, cy]},
        {"type": "type", "text": "echo td ok"},
        {"type": "key", "combo": "Return"},
        {"type": "wait", "s": 0.4},
        {"type": "type", "text": "exit"},
        {"type": "key", "combo": "Return"},
    ]

    drv = Driver(event_log_path=log_path, calib=calib, monitor=mon)
    try:
        for idx, act in enumerate(actions, 1):
            drv.execute(act, step_id=f"test-{idx:02d}")
    except StopRequested:
        drv.release_all()
        print("td act test: aborted via td stop", file=sys.stderr)
        return 130
    finally:
        drv.close()
        if orig_ws is not None:
            try:
                hypr.workspace(orig_ws)
            except Exception:
                pass

    summary = summarize_event_log(log_path)
    print(
        f"td act test: ok — {summary['total']} events over {summary['duration_s']}s "
        f"({summary['counts']}) -> {summary['path']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "act":
        args = args[1:]

    ap = argparse.ArgumentParser(prog="td act", description="Tutorial Director desktop actions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stop", help="Emergency stop: signal running driver and release modifiers/buttons")
    sub.add_parser("calib", help="Calibrate ydotool absolute coordinates against hyprctl cursorpos")
    p_test = sub.add_parser("test", help="Calibrate + run harmless terminal square & typing demo")
    p_test.add_argument("--log", default=None, help="Path for JSONL event log output")

    ns = ap.parse_args(args)
    try:
        if ns.cmd == "stop":
            return cmd_stop()
        if ns.cmd == "calib":
            return cmd_calib()
        if ns.cmd == "test":
            return cmd_test(log_path=ns.log)
    except StopRequested:
        return 130
    except (ActionError, hypr.HyprError, mouse.YdotoolError) as exc:
        print(f"td error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
