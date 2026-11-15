"""Human-like mouse paths, ydotool wrapper, and calibration for tutorial-director."""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Callable, Sequence

from . import hypr

BUTTON_DOWN = {"left": "0x40", "right": "0x41", "middle": "0x42"}
BUTTON_UP = {"left": "0x80", "right": "0x81", "middle": "0x82"}

YDOTOOL_INSTALL_MSG = (
    "ydotool not found. Install it with: sudo pacman -S ydotool "
    "(and ensure your user is in the input group: sudo usermod -aG input $USER)"
)


class YdotoolError(RuntimeError):
    """Raised when ydotool/ydotoold is missing, unreachable, or fails."""


@dataclass
class Calibration:
    """Affine per-axis mapping between ydotool absolute coords and logical screen px."""

    ax: float = 1.0
    bx: float = 0.0
    ay: float = 1.0
    by: float = 0.0
    monitor_name: str = ""
    monitor_scale: float = 1.0
    residual_px: float = 0.0
    calibrated_at: float = 0.0

    def to_ydotool(self, lx: float, ly: float) -> tuple[int, int]:
        yx = (lx - self.bx) / (self.ax if abs(self.ax) > 1e-9 else 1.0)
        yy = (ly - self.by) / (self.ay if abs(self.ay) > 1e-9 else 1.0)
        return int(round(yx)), int(round(yy))

    def to_logical(self, yx: float, yy: float) -> tuple[float, float]:
        return self.ax * yx + self.bx, self.ay * yy + self.by


def calib_path(path: str | None = None) -> str:
    if path:
        return path
    if os.environ.get("TD_CALIB_PATH"):
        return os.environ["TD_CALIB_PATH"]
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(cfg, "tutorial-director", "calib.json")


def load_calibration(path: str | None = None) -> Calibration | None:
    p = calib_path(path)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.loads(f.read())
        return Calibration(
            ax=float(data.get("ax", 1.0)),
            bx=float(data.get("bx", 0.0)),
            ay=float(data.get("ay", 1.0)),
            by=float(data.get("by", 0.0)),
            monitor_name=str(data.get("monitor_name", "")),
            monitor_scale=float(data.get("monitor_scale", 1.0)),
            residual_px=float(data.get("residual_px", 0.0)),
            calibrated_at=float(data.get("calibrated_at", 0.0)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_calibration(calib: Calibration, path: str | None = None) -> str:
    p = calib_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(asdict(calib), f, indent=2)
    return p


def ydotool_socket() -> str:
    if os.environ.get("YDOTOOL_SOCKET"):
        return os.environ["YDOTOOL_SOCKET"]
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(rt, ".ydotool_socket")


def _socket_alive(sock_path: str) -> bool:
    if not os.path.exists(sock_path):
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.25)
    try:
        s.connect(sock_path)
        return True
    except OSError:
        return False
    finally:
        s.close()


def ensure_ydotool(
    *,
    runner: hypr.CommandRunner | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Ensure `ydotool` is installed and per-user `ydotoold` socket is running."""
    env = os.environ.copy()
    sock = ydotool_socket()
    env["YDOTOOL_SOCKET"] = sock

    if runner is not None:
        return env

    if not shutil.which("ydotool"):
        raise YdotoolError(YDOTOOL_INSTALL_MSG)

    if _socket_alive(sock):
        return env

    if not shutil.which("ydotoold"):
        raise YdotoolError(YDOTOOL_INSTALL_MSG)

    os.makedirs(os.path.dirname(sock), exist_ok=True)
    if os.path.exists(sock):
        try:
            os.unlink(sock)
        except OSError:
            pass

    proc = subprocess.Popen(
        ["ydotoold", f"--socket-path={sock}", "--socket-perm=0600"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace").strip()
            raise YdotoolError(
                f"ydotoold failed to start ({err or 'exit ' + str(proc.returncode)}). "
                "Check /dev/uinput permissions (sudo usermod -aG input $USER)."
            )
        if _socket_alive(sock):
            return env
        sleep_fn(0.05)

    raise YdotoolError(
        f"ydotoold did not create socket {sock} within 2.5s. "
        "Check /dev/uinput permissions (sudo usermod -aG input $USER)."
    )


def run_ydotool(
    *args: str,
    runner: hypr.CommandRunner | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> subprocess.CompletedProcess:
    """Execute `ydotool <args...>` using the per-user socket."""
    if env is None:
        env = ensure_ydotool(runner=runner)
    cmd = ["ydotool", *args]
    if runner is not None:
        res = runner(cmd, timeout=timeout, env=env)
    else:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise YdotoolError(f"ydotool {' '.join(args)} timed out after {timeout}s") from exc
        except OSError as exc:
            raise YdotoolError(f"ydotool {' '.join(args)} failed: {exc}") from exc
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise YdotoolError(f"ydotool {' '.join(args)} exited {res.returncode}: {detail}")
    return res


def _fit_axis(pairs: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Ordinary least squares fit `logical = a * ydotool + b`."""
    n = len(pairs)
    if n < 2:
        return 1.0, 0.0
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den = sum((x - mx) ** 2 for x in xs)
    if abs(den) < 1e-9:
        return 1.0, 0.0
    a = num / den
    b = my - a * mx
    return a, b


def fit_calibration(
    samples: Sequence[tuple[tuple[float, float], tuple[float, float]]],
) -> tuple[float, float, float, float, float]:
    """Fit `(ax, bx, ay, by, max_residual_px)` from `[((yx, yy), (lx, ly)), ...]`."""
    ax, bx = _fit_axis([(s[0][0], s[1][0]) for s in samples])
    ay, by = _fit_axis([(s[0][1], s[1][1]) for s in samples])
    max_err = 0.0
    for (yx, yy), (lx, ly) in samples:
        px = ax * yx + bx
        py = ay * yy + by
        err = math.hypot(px - lx, py - ly)
        if err > max_err:
            max_err = err
    return ax, bx, ay, by, max_err


def calibrate(
    *,
    runner: hypr.CommandRunner | None = None,
    hypr_runner: hypr.CommandRunner | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    path: str | None = None,
) -> Calibration:
    """Move to 4 corners, read `hyprctl cursorpos`, fit scale/offset, and save calib.json."""
    env = ensure_ydotool(runner=runner, sleep_fn=sleep_fn)
    mon = hypr.focused_monitor(runner=hypr_runner)
    if mon is None:
        raise YdotoolError("No monitor found via hyprctl monitors -j")
    mx, my, lw, lh = hypr.monitor_logical_rect(mon)
    scale = float(mon.get("scale") or 1.0)
    mon_name = str(mon.get("name") or "")

    def probe_corners(max_x: float, max_y: float, off_x: float, off_y: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        fracs = [(0.15, 0.15), (0.85, 0.15), (0.85, 0.85), (0.15, 0.85)]
        out = []
        for fx, fy in fracs:
            yx = int(round(off_x + fx * max_x))
            yy = int(round(off_y + fy * max_y))
            run_ydotool("mousemove", "--absolute", "-x", str(yx), "-y", str(yy), runner=runner, env=env)
            sleep_fn(0.08)
            lx, ly = hypr.cursor_pos(runner=hypr_runner)
            out.append(((float(yx), float(yy)), (lx, ly)))
        return out

    # Try physical pixel coordinates first; if cursor barely moves, probe 0..32767 space.
    samples = probe_corners(lw * scale, lh * scale, mx * scale, my * scale)
    xs = [s[1][0] for s in samples]
    ys = [s[1][1] for s in samples]
    if (max(xs) - min(xs)) < 20 or (max(ys) - min(ys)) < 20:
        samples = probe_corners(32767.0, 32767.0, 0.0, 0.0)

    ax, bx, ay, by, max_err = fit_calibration(samples)
    calib = Calibration(
        ax=ax,
        bx=bx,
        ay=ay,
        by=by,
        monitor_name=mon_name,
        monitor_scale=scale,
        residual_px=round(max_err, 3),
        calibrated_at=time.time(),
    )

    # Verify accuracy at screen center
    cx, cy = mx + lw * 0.5, my + lh * 0.5
    cyx, cyy = calib.to_ydotool(cx, cy)
    run_ydotool("mousemove", "--absolute", "-x", str(cyx), "-y", str(cyy), runner=runner, env=env)
    sleep_fn(0.08)
    acx, acy = hypr.cursor_pos(runner=hypr_runner)
    center_err = math.hypot(acx - cx, acy - cy)
    calib.residual_px = round(max(max_err, center_err), 3)

    save_calibration(calib, path=path)
    return calib


def logical_to_ydotool(
    lx: float,
    ly: float,
    *,
    calib: Calibration | None = None,
    mon: dict | None = None,
) -> tuple[int, int]:
    """Convert logical global `(lx, ly)` to ydotool `--absolute` integer coordinates."""
    if calib is not None:
        return calib.to_ydotool(lx, ly)
    if mon is not None:
        scale = float(mon.get("scale") or 1.0)
        return int(round(lx * scale)), int(round(ly * scale))
    return int(round(lx)), int(round(ly))


def ease_in_out(u: float) -> float:
    """Quintic smoothstep ease-in-out on [0, 1]."""
    u = max(0.0, min(1.0, u))
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


def move_duration(dist: float) -> float:
    """Duration clamp(0.25 + dist/1800, 0.3, 1.1) seconds."""
    return max(0.3, min(1.1, 0.25 + dist / 1800.0))


def settle_duration(rng: random.Random | None = None) -> float:
    """Random pre-click settle duration in [0.12, 0.22] s."""
    r = rng or random
    return r.uniform(0.12, 0.22)


def click_hold_duration(rng: random.Random | None = None) -> float:
    """Random mouse down-to-up duration in [0.070, 0.110] s."""
    r = rng or random
    return r.uniform(0.070, 0.110)


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    mt = 1.0 - t
    mt2 = mt * mt
    t2 = t * t
    a = mt2 * mt
    b = 3.0 * mt2 * t
    c = 3.0 * mt * t2
    d = t2 * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def generate_bezier_path(
    start: tuple[float, float],
    target: tuple[float, float],
    *,
    rng: random.Random | None = None,
    hz: int = 120,
    overshoot_threshold: float = 150.0,
) -> list[tuple[float, float, float]]:
    """Return `[(t_offset_s, x, y), ...]` at `hz` steps using cubic Bézier + ease-in-out.

    Control points use a random perpendicular offset in 5-15% of distance.
    Moves >= `overshoot_threshold` px include a tiny overshoot (<= 6 px) before settling on target.
    """
    r = rng or random.Random()
    x0, y0 = float(start[0]), float(start[1])
    x1, y1 = float(target[0]), float(target[1])
    dx = x1 - x0
    dy = y1 - y0
    dist = math.hypot(dx, dy)

    if dist < 1.0:
        return [(0.0, x1, y1)]

    dur = move_duration(dist)
    ux, uy = dx / dist, dy / dist
    px, py = -uy, ux

    sign = 1.0 if r.random() < 0.5 else -1.0
    off1 = r.uniform(0.05, 0.15) * dist * sign
    off2 = r.uniform(0.05, 0.15) * dist * sign
    p0 = (x0, y0)
    p1 = (x0 + 0.33 * dx + off1 * px, y0 + 0.33 * dy + off1 * py)
    p2 = (x0 + 0.67 * dx + off2 * px, y0 + 0.67 * dy + off2 * py)

    do_overshoot = dist >= overshoot_threshold
    if do_overshoot:
        ov_mag = r.uniform(2.0, 6.0)
        lat = r.uniform(-1.0, 1.0)
        # Keep total overshoot magnitude strictly <= 6.0 px
        ov_x = ux * ov_mag + px * lat
        ov_y = uy * ov_mag + py * lat
        ov_norm = math.hypot(ov_x, ov_y)
        if ov_norm > 6.0:
            scale = 6.0 / ov_norm
            ov_x *= scale
            ov_y *= scale
        ov_pt = (x1 + ov_x, y1 + ov_y)
        split = 0.88
    else:
        ov_pt = (x1, y1)
        split = 1.0

    n_steps = max(2, int(round(dur * hz)))
    points: list[tuple[float, float, float]] = []
    for i in range(n_steps + 1):
        frac = i / n_steps
        t_off = frac * dur
        if not do_overshoot:
            u = ease_in_out(frac)
            bx, by = _cubic_bezier(p0, p1, p2, (x1, y1), u)
        elif frac <= split:
            u = ease_in_out(frac / split)
            bx, by = _cubic_bezier(p0, p1, p2, ov_pt, u)
        else:
            # Smoothly pull back from overshoot peak to exact target
            u = ease_in_out((frac - split) / (1.0 - split))
            bx = ov_pt[0] + (x1 - ov_pt[0]) * u
            by = ov_pt[1] + (y1 - ov_pt[1]) * u
        points.append((t_off, bx, by))

    points[-1] = (dur, x1, y1)
    return points


def move_cursor(
    start: tuple[float, float],
    target: tuple[float, float],
    *,
    calib: Calibration | None = None,
    mon: dict | None = None,
    rng: random.Random | None = None,
    hz: int = 120,
    runner: hypr.CommandRunner | None = None,
    env: dict[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    check_abort: Callable[[], None] | None = None,
    on_sample: Callable[[float, float, float], None] | None = None,
) -> tuple[float, float]:
    """Execute a human Bézier move from `start` to `target`, emitting ~33ms cursor samples."""
    if env is None:
        env = ensure_ydotool(runner=runner, sleep_fn=sleep_fn)

    path = generate_bezier_path(start, target, rng=rng, hz=hz)
    t_start = clock()
    last_log_t = -1e9
    last_check_t = t_start
    last_sent: tuple[int, int] | None = None

    for idx, (t_off, lx, ly) in enumerate(path):
        if check_abort is not None and (idx == 0 or (clock() - last_check_t) >= 0.04):
            check_abort()
            last_check_t = clock()

        now = clock()
        target_wall = t_start + t_off
        while target_wall - now > 0.001:
            dt = min(0.04, target_wall - now)
            sleep_fn(dt)
            if check_abort is not None:
                check_abort()
                last_check_t = clock()
            after = clock()
            if after <= now:
                break
            now = after

        yx, yy = logical_to_ydotool(lx, ly, calib=calib, mon=mon)
        if last_sent != (yx, yy) or idx == len(path) - 1:
            run_ydotool("mousemove", "--absolute", "-x", str(yx), "-y", str(yy), runner=runner, env=env)
            last_sent = (yx, yy)

        sample_t = clock()
        if on_sample is not None and (idx == 0 or idx == len(path) - 1 or (sample_t - last_log_t) >= 0.033):
            on_sample(sample_t, lx, ly)
            last_log_t = sample_t

    return float(target[0]), float(target[1])
