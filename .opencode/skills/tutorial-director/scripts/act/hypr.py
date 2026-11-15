"""Hyprland (`hyprctl`) helpers for tutorial-director."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Sequence

CommandRunner = Callable[..., subprocess.CompletedProcess]


class HyprError(RuntimeError):
    """Raised when a hyprctl command or window operation fails."""


def _default_runner(
    cmd: Sequence[str],
    *,
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def hypr_cmd(
    *args: str,
    timeout: float = 5.0,
    runner: CommandRunner | None = None,
) -> str:
    """Run `hyprctl <args...>` and return stdout."""
    run = runner or _default_runner
    if runner is None and not shutil.which("hyprctl"):
        raise HyprError("hyprctl not found in PATH; Hyprland session is required")
    try:
        res = run(["hyprctl", *args], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise HyprError(f"hyprctl {' '.join(args)} timed out after {timeout}s") from exc
    except OSError as exc:
        raise HyprError(f"hyprctl {' '.join(args)} failed: {exc}") from exc
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise HyprError(f"hyprctl {' '.join(args)} exited {res.returncode}: {detail}")
    return res.stdout


def hypr_json(
    *args: str,
    timeout: float = 5.0,
    runner: CommandRunner | None = None,
) -> Any:
    """Run `hyprctl <args...> -j` and parse JSON output."""
    out = hypr_cmd(*args, "-j", timeout=timeout, runner=runner)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise HyprError(f"Invalid JSON from hyprctl {' '.join(args)} -j: {exc}") from exc


def monitors(runner: CommandRunner | None = None) -> list[dict[str, Any]]:
    """Return list of monitors from `hyprctl monitors -j`."""
    data = hypr_json("monitors", runner=runner)
    if not isinstance(data, list):
        raise HyprError(f"Expected list from monitors -j, got {type(data).__name__}")
    return data


def monitor_logical_rect(mon: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return (x, y, width, height) in logical pixels for a monitor dict."""
    scale = float(mon.get("scale") or 1.0)
    if scale <= 0:
        scale = 1.0
    lw = float(mon["width"]) / scale
    lh = float(mon["height"]) / scale
    if mon.get("transform", 0) in (1, 3, 5, 7):
        lw, lh = lh, lw
    return float(mon.get("x", 0)), float(mon.get("y", 0)), lw, lh


def focused_monitor(
    name: str | None = None,
    runner: CommandRunner | None = None,
) -> dict[str, Any] | None:
    """Return the named monitor, else the focused monitor, else the first monitor."""
    mons = monitors(runner=runner)
    if not mons:
        return None
    if name:
        for m in mons:
            if m.get("name") == name:
                return m
    for m in mons:
        if m.get("focused"):
            return m
    return mons[0]


def clients(runner: CommandRunner | None = None) -> list[dict[str, Any]]:
    """Return list of windows from `hyprctl clients -j`."""
    data = hypr_json("clients", runner=runner)
    if not isinstance(data, list):
        raise HyprError(f"Expected list from clients -j, got {type(data).__name__}")
    return data


def active_window(runner: CommandRunner | None = None) -> dict[str, Any]:
    """Return the currently active window dict from `hyprctl activewindow -j`."""
    data = hypr_json("activewindow", runner=runner)
    if not isinstance(data, dict):
        return {}
    return data


def cursor_pos(runner: CommandRunner | None = None) -> tuple[float, float]:
    """Return current logical cursor position `(x, y)` via `hyprctl cursorpos`."""
    out = hypr_cmd("cursorpos", runner=runner).strip()
    if out.startswith("{"):
        data = json.loads(out)
        return float(data["x"]), float(data["y"])
    parts = [p.strip() for p in out.split(",")]
    if len(parts) != 2:
        raise HyprError(f"Unexpected cursorpos output: {out!r}")
    return float(parts[0]), float(parts[1])


def dispatch(*args: str, runner: CommandRunner | None = None) -> str:
    """Run `hyprctl dispatch <args...>`."""
    return hypr_cmd("dispatch", *args, runner=runner)


def _match_field(val: str, pattern: str) -> int:
    """Return match score (2=exact, 1=regex, 0=none)."""
    if not val:
        return 0
    if val == pattern:
        return 2
    try:
        if re.search(pattern, val):
            return 1
    except re.error:
        if pattern.lower() in val.lower():
            return 1
    return 0


def find_client(
    window_spec: str,
    runner: CommandRunner | None = None,
) -> dict[str, Any] | None:
    """Find a Hyprland client matching `class:X`, `title:X`, `address:X`, `pid:N`, or bare `X`."""
    win_list = clients(runner=runner)
    spec = window_spec.strip()
    if ":" in spec:
        prefix, val = spec.split(":", 1)
    else:
        prefix, val = "", spec

    best_score = -1
    best_client: dict[str, Any] | None = None
    for c in win_list:
        score = 0
        if prefix == "class":
            s1 = _match_field(str(c.get("class", "")), val)
            s2 = _match_field(str(c.get("initialClass", "")), val)
            score = max(s1 * 2, s2)
        elif prefix == "initialClass":
            score = _match_field(str(c.get("initialClass", "")), val) * 2
        elif prefix == "title":
            score = _match_field(str(c.get("title", "")), val) * 2
        elif prefix == "initialTitle":
            score = _match_field(str(c.get("initialTitle", "")), val) * 2
        elif prefix == "address":
            score = 4 if str(c.get("address", "")).lower() == val.lower() else 0
        elif prefix == "pid":
            score = 4 if str(c.get("pid", "")) == val else 0
        else:
            s_cls = _match_field(str(c.get("class", "")), spec)
            s_icls = _match_field(str(c.get("initialClass", "")), spec)
            s_tit = _match_field(str(c.get("title", "")), spec)
            score = max(s_cls * 2, s_icls, s_tit)

        if score <= 0:
            continue
        # Prefer mapped / focused windows on ties
        bonus = (1 if c.get("mapped", True) else 0) + (1 if c.get("focusHistoryID") == 0 else 0)
        total = score * 10 + bonus
        if total > best_score:
            best_score = total
            best_client = c

    return best_client


def window_rect(
    window_spec: str,
    runner: CommandRunner | None = None,
) -> tuple[int, int, int, int]:
    """Return `(x, y, w, h)` in logical px for the matching window."""
    client = find_client(window_spec, runner=runner)
    if client is None:
        raise HyprError(f"Window not found: {window_spec!r}")
    at = client.get("at") or [0, 0]
    size = client.get("size") or [0, 0]
    return int(at[0]), int(at[1]), int(size[0]), int(size[1])


def focus_window(window_spec: str, runner: CommandRunner | None = None) -> str:
    """Focus a window via `hyprctl dispatch focuswindow`."""
    return dispatch("focuswindow", window_spec, runner=runner)


def workspace(n: int | str, runner: CommandRunner | None = None) -> str:
    """Switch to workspace `n` via `hyprctl dispatch workspace`."""
    return dispatch("workspace", str(n), runner=runner)


def launch(cmd: str, runner: CommandRunner | None = None) -> str:
    """Launch a command via `hyprctl dispatch exec`."""
    return dispatch("exec", cmd, runner=runner)


def empty_workspace(runner: CommandRunner | None = None) -> int:
    """Pick an unoccupied workspace number (preferring 9, 8, 7... or above max)."""
    used = {
        int(c["workspace"]["id"])
        for c in clients(runner=runner)
        if isinstance(c.get("workspace"), dict) and isinstance(c["workspace"].get("id"), int)
    }
    for cand in range(9, 1, -1):
        if cand not in used:
            return cand
    ws = 10
    while ws in used:
        ws += 1
    return ws


def place(
    window: str,
    slot: Sequence[int] | str,
    *,
    layout: dict[str, Sequence[int]] | None = None,
    tol: int = 4,
    wait_s: float = 0.3,
    runner: CommandRunner | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[int, int, int, int]:
    """Float, resize, move `window` to `slot` (`[x, y, w, h]` or key in `layout`) and verify ±`tol` px."""
    if isinstance(slot, str):
        if not layout or slot not in layout:
            raise HyprError(f"Unknown layout slot: {slot!r}")
        rect = layout[slot]
    else:
        rect = slot
    if len(rect) != 4:
        raise HyprError(f"Layout slot must be [x, y, w, h], got {rect!r}")
    x, y, w, h = (int(round(v)) for v in rect)

    client = find_client(window, runner=runner)
    if client is None:
        raise HyprError(f"Cannot place window {window!r}: not found")
    target = f"address:{client['address']}" if client.get("address") else window

    focus_window(target, runner=runner)
    if not client.get("floating", False):
        dispatch("setfloating", target, runner=runner)
    dispatch("resizewindowpixel", f"exact {w} {h},{target}", runner=runner)
    dispatch("movewindowpixel", f"exact {x} {y},{target}", runner=runner)

    if wait_s > 0:
        sleep_fn(wait_s)

    ax, ay, aw, ah = window_rect(target, runner=runner)
    if (
        abs(ax - x) > tol
        or abs(ay - y) > tol
        or abs(aw - w) > tol
        or abs(ah - h) > tol
    ):
        raise HyprError(
            f"Window {window!r} geometry mismatch after place: "
            f"expected ({x}, {y}, {w}, {h}) ±{tol}px, got ({ax}, {ay}, {aw}, {ah})"
        )
    return ax, ay, aw, ah
