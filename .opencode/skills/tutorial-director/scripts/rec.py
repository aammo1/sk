#!/usr/bin/env python3
"""rec.py — Screen recorder wrapper for tutorial-director.

Wraps gpu-screen-recorder (no audio; TTS voice is mixed later), waits until the
recording file grows, writes rec/start.json with wall-clock and monotonic
timestamps, stops cleanly on SIGINT, and normalizes to 1920x1080 30 fps CFR MP4.

Importable API:
    from rec import Recorder, pick_monitor, normalize_1080p30
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any


DEFAULT_FPS = 30
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_START_TIMEOUT = 3.0


def _runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base)
    p = Path(f"/tmp/td-runtime-{os.getuid()}")
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)
    return p


def _pid_file() -> Path:
    return _runtime_dir() / "td-rec.json"


def _load_script(script: dict[str, Any] | str | Path | None) -> dict[str, Any]:
    if script is None:
        return {}
    if isinstance(script, (str, Path)):
        return json.loads(Path(script).read_text(encoding="utf-8"))
    if isinstance(script, dict):
        return script
    screen = getattr(script, "screen", None)
    if screen is not None:
        monitor = getattr(screen, "monitor", None)
        return {"screen": {"monitor": monitor}}
    return {}


def _run_hyprctl_monitors() -> list[dict[str, Any]]:
    res = subprocess.run(
        ["hyprctl", "monitors", "-j"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5.0,
    )
    data = json.loads(res.stdout)
    if not isinstance(data, list) or not data:
        raise RuntimeError("hyprctl monitors -j returned no monitors")
    return data


def _normalize_monitor_name(val: Any) -> str | None:
    """Return explicit monitor name, or None when unset/'auto' (auto-detect)."""
    if not isinstance(val, str):
        return None
    cleaned = val.strip()
    if not cleaned or cleaned.lower() == "auto":
        return None
    return cleaned


def pick_monitor(script: dict[str, Any] | str | Path | None = None) -> dict[str, Any]:
    """Select target monitor from script.screen.monitor or the focused monitor."""
    cfg = _load_script(script)
    requested = _normalize_monitor_name((cfg.get("screen") or {}).get("monitor"))
    monitors = _run_hyprctl_monitors()

    if requested:
        for mon in monitors:
            if mon.get("name") == requested:
                if mon.get("disabled"):
                    raise RuntimeError(f"Requested monitor {requested!r} is disabled")
                return mon
        avail = ", ".join(str(m.get("name")) for m in monitors)
        raise RuntimeError(f"Requested monitor {requested!r} not found (available: {avail})")

    for mon in monitors:
        if mon.get("focused") and not mon.get("disabled"):
            return mon
    for mon in monitors:
        if not mon.get("disabled"):
            return mon
    return monitors[0]


def probe_video(path: str | Path) -> dict[str, Any]:
    """Return basic video stream metadata using ffprobe."""
    p = Path(path)
    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,duration,nb_frames",
            "-of",
            "json",
            str(p),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15.0,
    )
    info = json.loads(res.stdout)
    streams = info.get("streams") or []
    if not streams:
        raise RuntimeError(f"No video stream found in {p}")
    return streams[0]


def normalize_1080p30(
    src: str | Path,
    dst: str | Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> Path:
    """Normalize recording to width x height, fps CFR H.264 MP4 (no audio)."""
    src_path = Path(src).resolve()
    dst_path = Path(dst).resolve()
    if not src_path.is_file() or src_path.stat().st_size == 0:
        raise FileNotFoundError(f"Source recording missing or empty: {src_path}")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dst_path.with_name(f".{dst_path.stem}.norm.tmp.mp4")
    if tmp_path.exists():
        tmp_path.unlink()

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={fps}"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src_path),
        "-vf",
        vf,
        "-fps_mode",
        "cfr",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-an",
        "-movflags",
        "+faststart",
        str(tmp_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()
        raise RuntimeError(f"ffmpeg normalization failed ({res.returncode}): {res.stderr.strip()}")

    os.replace(tmp_path, dst_path)
    return dst_path


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Recorder:
    """Manage a gpu-screen-recorder session and post-normalize to 1080p 30fps CFR."""

    def __init__(
        self,
        out_dir: str | Path,
        script: dict[str, Any] | str | Path | None = None,
        monitor: str | None = None,
        fps: int = DEFAULT_FPS,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        start_timeout: float = DEFAULT_START_TIMEOUT,
    ) -> None:
        self.out_dir = Path(out_dir).resolve()
        self.script = _load_script(script)
        self.monitor = monitor
        self.fps = int(fps)
        self.width = int(width)
        self.height = int(height)
        self.start_timeout = float(start_timeout)

        self.raw_path = self.out_dir / "raw.mp4"
        self.screen_path = self.out_dir / "screen.mp4"
        self.start_json_path = self.out_dir / "start.json"
        self.log_path = self.out_dir / "recorder.log"

        self._proc: subprocess.Popen[bytes] | None = None
        self._log_file = None
        self._start_meta: dict[str, Any] | None = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> dict[str, Any]:
        """Start gpu-screen-recorder, wait for file growth, and write start.json."""
        if self.is_running():
            raise RuntimeError("Recorder is already running")

        if not shutil.which("gpu-screen-recorder"):
            raise FileNotFoundError("gpu-screen-recorder not found on PATH")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        for p in (self.raw_path, self.start_json_path):
            if p.exists():
                p.unlink()

        explicit_monitor = _normalize_monitor_name(self.monitor)
        if explicit_monitor:
            mon_info = {"name": explicit_monitor}
            try:
                for m in _run_hyprctl_monitors():
                    if m.get("name") == explicit_monitor:
                        mon_info = m
                        break
            except Exception:
                pass
        else:
            mon_info = pick_monitor(self.script)

        mon_name = str(mon_info["name"])
        cmd = [
            "gpu-screen-recorder",
            "-w",
            mon_name,
            "-f",
            str(self.fps),
            "-k",
            "h264",
            "-c",
            "mp4",
            "-fm",
            "cfr",
            "-o",
            str(self.raw_path),
        ]

        self._log_file = open(self.log_path, "wb")
        launch_wall = time.time()
        launch_mono = time.monotonic()
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        # Wait until raw.mp4 appears and grows (within <= start_timeout).
        deadline = launch_mono + self.start_timeout
        prev_size = 0
        first_nonzero_mono: float | None = None
        grew = False
        while time.monotonic() <= deadline:
            if self._proc.poll() is not None:
                self._close_log()
                log_tail = self._read_log_tail()
                raise RuntimeError(
                    f"gpu-screen-recorder exited prematurely ({self._proc.returncode}): {log_tail}"
                )
            if self.raw_path.exists():
                try:
                    size = self.raw_path.stat().st_size
                except OSError:
                    size = 0
                if size > 0:
                    if first_nonzero_mono is None:
                        first_nonzero_mono = time.monotonic()
                    if prev_size > 0 and size > prev_size:
                        grew = True
                        break
                    if prev_size > 0 and (time.monotonic() - first_nonzero_mono) >= 0.25:
                        grew = True
                        break
                    prev_size = size
            time.sleep(0.05)

        if not grew:
            self._terminate_process()
            self._close_log()
            log_tail = self._read_log_tail()
            raise TimeoutError(
                f"Recording file {self.raw_path} did not grow within {self.start_timeout:.1f}s"
                + (f": {log_tail}" if log_tail else "")
            )

        ready_wall = time.time()
        ready_mono = time.monotonic()
        meta: dict[str, Any] = {
            "wall_time": ready_wall,
            "monotonic_time": ready_mono,
            "iso_time": datetime.fromtimestamp(ready_wall, tz=timezone.utc).isoformat(),
            "launch_wall_time": launch_wall,
            "launch_monotonic_time": launch_mono,
            "monitor": mon_name,
            "monitor_width": mon_info.get("width"),
            "monitor_height": mon_info.get("height"),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "pid": self._proc.pid,
            "raw_file": str(self.raw_path),
            "screen_file": str(self.screen_path),
        }
        _atomic_write_json(self.start_json_path, meta)
        _atomic_write_json(
            _pid_file(),
            {
                "pid": self._proc.pid,
                "out_dir": str(self.out_dir),
                "raw_file": str(self.raw_path),
                "screen_file": str(self.screen_path),
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
            },
        )
        self._start_meta = meta
        return meta

    def stop(self, normalize: bool = True, keep_raw: bool = True) -> Path:
        """Send SIGINT to gpu-screen-recorder, wait for flush, and normalize to 1080p30 CFR."""
        try:
            self._terminate_process()
        finally:
            self._close_log()
            pf = _pid_file()
            if pf.exists():
                try:
                    pf_data = json.loads(pf.read_text(encoding="utf-8"))
                    if self._proc is None or pf_data.get("pid") == self._proc.pid:
                        pf.unlink()
                except Exception:
                    pass

        if not self.raw_path.is_file() or self.raw_path.stat().st_size == 0:
            raise RuntimeError(f"Raw recording missing or empty: {self.raw_path}")

        if not normalize:
            return self.raw_path

        out = normalize_1080p30(
            self.raw_path,
            self.screen_path,
            width=self.width,
            height=self.height,
            fps=self.fps,
        )
        if not keep_raw and self.raw_path.exists():
            self.raw_path.unlink()
        return out

    def _terminate_process(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            return
        self._proc.send_signal(signal.SIGINT)
        try:
            self._proc.wait(timeout=10.0)
            return
        except subprocess.TimeoutExpired:
            pass
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3.0)
            return
        except subprocess.TimeoutExpired:
            pass
        self._proc.kill()
        self._proc.wait(timeout=3.0)

    def _close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    def _read_log_tail(self) -> str:
        try:
            txt = self.log_path.read_text(encoding="utf-8", errors="replace").strip()
            return txt.splitlines()[-1] if txt else ""
        except OSError:
            return ""

    def __enter__(self) -> Recorder:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._proc is not None or self.raw_path.exists():
            self.stop(normalize=True)


def stop_active_recording(out_dir: str | Path | None = None, normalize: bool = True) -> Path | None:
    """Stop a background recording started via `rec.py start` (used by `td stop`)."""
    pf = _pid_file()
    if not pf.is_file():
        return None
    data = json.loads(pf.read_text(encoding="utf-8"))
    pid = int(data["pid"])
    raw_path = Path(data["raw_file"])
    screen_path = Path(out_dir).resolve() / "screen.mp4" if out_dir else Path(data["screen_file"])

    for sig, wait_s in ((signal.SIGINT, 10.0), (signal.SIGTERM, 3.0), (signal.SIGKILL, 3.0)):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            continue
        break

    try:
        pf.unlink()
    except OSError:
        pass

    if not raw_path.is_file() or raw_path.stat().st_size == 0:
        raise RuntimeError(f"Raw recording missing or empty: {raw_path}")

    if normalize:
        return normalize_1080p30(
            raw_path,
            screen_path,
            width=int(data.get("width", DEFAULT_WIDTH)),
            height=int(data.get("height", DEFAULT_HEIGHT)),
            fps=int(data.get("fps", DEFAULT_FPS)),
        )
    return raw_path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="tutorial-director screen recorder wrapper")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("start", "record"):
        sp = sub.add_parser(name, help=f"{name} a screen recording")
        sp.add_argument("--out", required=True, help="Output directory (stores raw.mp4, start.json, screen.mp4)")
        sp.add_argument("--monitor", default=None, help="Monitor name (default: script.screen.monitor or focused)")
        sp.add_argument("--script", default=None, help="Path to script.json")
        sp.add_argument("--fps", type=int, default=DEFAULT_FPS)
        if name == "record":
            sp.add_argument("--duration", type=float, default=5.0, help="Recording duration in seconds")

    sp_stop = sub.add_parser("stop", help="Stop an active background recording and normalize")
    sp_stop.add_argument("--out", default=None, help="Optional output directory override")
    sp_stop.add_argument("--no-normalize", action="store_true")

    sp_norm = sub.add_parser("normalize", help="Normalize an existing video to 1920x1080 30fps CFR")
    sp_norm.add_argument("src")
    sp_norm.add_argument("dst")
    sp_norm.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    sp_norm.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    sp_norm.add_argument("--fps", type=int, default=DEFAULT_FPS)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "start":
        rec = Recorder(args.out, script=args.script, monitor=args.monitor, fps=args.fps)
        meta = rec.start()
        print(json.dumps(meta, indent=2))
        return 0
    if args.cmd == "record":
        with Recorder(args.out, script=args.script, monitor=args.monitor, fps=args.fps) as rec:
            time.sleep(max(0.1, float(args.duration)))
        print(str(rec.screen_path))
        return 0
    if args.cmd == "stop":
        out = stop_active_recording(out_dir=args.out, normalize=not args.no_normalize)
        if out is None:
            print("No active recording found", file=sys.stderr)
            return 1
        print(str(out))
        return 0
    if args.cmd == "normalize":
        out = normalize_1080p30(args.src, args.dst, width=args.width, height=args.height, fps=args.fps)
        print(str(out))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
