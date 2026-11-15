#!/usr/bin/env python3
"""stage.py — Prepare and restore a clean desktop stage for tutorial-director.

Handles Do-Not-Disturb, workspace isolation (default 9, must be empty),
studio look (terminal font override, browser zoom helper, plain theme-matched
wallpaper, hiding the top bar, larger cursor), and guaranteed idempotent
restore in finally blocks, signal handlers, and `td stop`.

Importable API:
    from stage import Stage, prepare, restore, terminal_launch_cmd, browser_launch_cmd
"""

from __future__ import annotations

import argparse
import atexit
import binascii
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
from typing import Any
import warnings
import zlib


DEFAULT_WORKSPACE = 9
DEFAULT_STUDIO: dict[str, Any] = {
    "font_px": 18,
    "browser_zoom": 1.25,
    "wallpaper": "plain",
    "hide_bar": True,
    "cursor_px": 32,
}


def _runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base)
    p = Path(f"/tmp/td-runtime-{os.getuid()}")
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)
    return p


def default_state_path() -> Path:
    return _runtime_dir() / "td-stage.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _load_script(script: dict[str, Any] | str | Path | None) -> dict[str, Any]:
    if script is None:
        return {}
    if isinstance(script, (str, Path)):
        return json.loads(Path(script).read_text(encoding="utf-8"))
    if isinstance(script, dict):
        return script
    out: dict[str, Any] = {}
    screen = getattr(script, "screen", None)
    if screen is not None:
        out["screen"] = {
            "workspace": getattr(screen, "workspace", DEFAULT_WORKSPACE),
            "monitor": getattr(screen, "monitor", None),
        }
    studio = getattr(script, "studio", None)
    if studio is not None:
        out["studio"] = {
            "font_px": getattr(studio, "font_px", DEFAULT_STUDIO["font_px"]),
            "browser_zoom": getattr(studio, "browser_zoom", DEFAULT_STUDIO["browser_zoom"]),
            "wallpaper": getattr(studio, "wallpaper", DEFAULT_STUDIO["wallpaper"]),
            "hide_bar": getattr(studio, "hide_bar", DEFAULT_STUDIO["hide_bar"]),
            "cursor_px": getattr(studio, "cursor_px", DEFAULT_STUDIO["cursor_px"]),
        }
    return out


def _run(cmd: list[str], check: bool = True, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)


def _hyprctl_json(subcmd: str) -> Any:
    res = _run(["hyprctl", subcmd, "-j"])
    return json.loads(res.stdout)


def _proc_running(name: str) -> bool:
    if not shutil.which("pgrep"):
        return False
    res = subprocess.run(["pgrep", "-x", name], capture_output=True)
    return res.returncode == 0


def _resolve_theme_bg_hex() -> str:
    if shutil.which("omarchy-theme-color"):
        try:
            res = _run(["omarchy-theme-color", "background"], check=False, timeout=3.0)
            val = res.stdout.strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", val):
                return val
        except Exception:
            pass
    return "#11111b"


def _write_solid_png(path: Path, hex_color: str, width: int = 1920, height: int = 1080) -> Path:
    """Write a solid-color RGB PNG using only Python stdlib."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    row = b"\x00" + bytes((r, g, b)) * width
    raw = row * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw, level=1)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def _detect_cursor_info() -> tuple[str, int]:
    theme = (os.environ.get("HYPRCURSOR_THEME") or os.environ.get("XCURSOR_THEME") or "").strip()
    size_raw = (os.environ.get("HYPRCURSOR_SIZE") or os.environ.get("XCURSOR_SIZE") or "").strip()

    if (not theme or not size_raw) and shutil.which("gsettings"):
        if not theme:
            try:
                res = _run(["gsettings", "get", "org.gnome.desktop.interface", "cursor-theme"], check=False)
                t = res.stdout.strip().strip("'\"")
                if t:
                    theme = t
            except Exception:
                pass
        if not size_raw:
            try:
                res = _run(["gsettings", "get", "org.gnome.desktop.interface", "cursor-size"], check=False)
                s = res.stdout.strip()
                if s.isdigit():
                    size_raw = s
            except Exception:
                pass

    if not theme:
        theme = "default"
    try:
        size = int(size_raw) if size_raw else 24
    except ValueError:
        size = 24
    return theme, size


def _find_swaybg_cmdlines() -> list[list[str]]:
    cmds: list[list[str]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return cmds
    uid = os.getuid()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
            if comm != "swaybg":
                continue
            raw = (entry / "cmdline").read_bytes()
            argv = [a.decode("utf-8", errors="replace") for a in raw.split(b"\x00") if a]
            if argv:
                cmds.append(argv)
        except OSError:
            continue
    return cmds


def _studio_from_state_or_defaults(
    studio: dict[str, Any] | None = None, state_path: str | Path | None = None
) -> dict[str, Any]:
    merged = dict(DEFAULT_STUDIO)
    sp = Path(state_path) if state_path else default_state_path()
    if sp.is_file():
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
            if st.get("active") and isinstance(st.get("studio"), dict):
                merged.update(st["studio"])
        except Exception:
            pass
    if studio:
        merged.update({k: v for k, v in studio.items() if v is not None})
    return merged


def detect_terminal() -> str:
    """Detect the user's configured Wayland terminal (ghostty/alacritty/kitty/foot)."""
    xdg_list = Path.home() / ".config/xdg-terminals.list"
    mapping = {
        "ghostty": "ghostty",
        "alacritty": "alacritty",
        "kitty": "kitty",
        "foot": "foot",
    }
    if xdg_list.is_file():
        for line in xdg_list.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            low = line.lower()
            for key, exe in mapping.items():
                if key in low and shutil.which(exe):
                    return exe
    for exe in ("ghostty", "alacritty", "kitty", "foot"):
        if shutil.which(exe):
            return exe
    raise FileNotFoundError("No supported terminal found (ghostty, alacritty, kitty, foot)")


def _foot_font_family() -> str:
    ini = Path.home() / ".config/foot/foot.ini"
    if ini.is_file():
        for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if s.startswith("font="):
                val = s.split("=", 1)[1].strip()
                family = re.sub(r":size=[^:,]+", "", val).strip()
                if family:
                    return family
    return "monospace"


def prepare_terminal_override(font_px: int, override_dir: Path | None = None) -> dict[str, str]:
    """Write temporary terminal config overrides (without touching ~/.config) and return paths."""
    d = override_dir or (_runtime_dir() / "td-stage-overrides")
    d.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    alacritty_cfg = Path.home() / ".config/alacritty/alacritty.toml"
    ala_lines = []
    if alacritty_cfg.is_file():
        ala_lines.append(f'general.import = [ "{alacritty_cfg}" ]')
    ala_lines.extend(["[font]", f"size = {int(font_px)}"])
    ala_out = d / "alacritty.toml"
    ala_out.write_text("\n".join(ala_lines) + "\n", encoding="utf-8")
    paths["alacritty"] = str(ala_out)

    ghostty_cfg = Path.home() / ".config/ghostty/config"
    gh_lines = []
    if ghostty_cfg.is_file():
        gh_lines.append(f'config-file = ?"{ghostty_cfg}"')
    gh_lines.append(f"font-size = {int(font_px)}")
    gh_out = d / "ghostty.conf"
    gh_out.write_text("\n".join(gh_lines) + "\n", encoding="utf-8")
    paths["ghostty"] = str(gh_out)

    kitty_cfg = Path.home() / ".config/kitty/kitty.conf"
    ki_lines = []
    if kitty_cfg.is_file():
        ki_lines.append(f"include {kitty_cfg}")
    ki_lines.append(f"font_size {float(font_px)}")
    ki_out = d / "kitty.conf"
    ki_out.write_text("\n".join(ki_lines) + "\n", encoding="utf-8")
    paths["kitty"] = str(ki_out)

    foot_cfg = Path.home() / ".config/foot/foot.ini"
    fo_lines = ["[main]"]
    if foot_cfg.is_file():
        fo_lines.append(f"include={foot_cfg}")
    fo_lines.append(f"font={_foot_font_family()}:size={int(font_px)}")
    fo_out = d / "foot.ini"
    fo_out.write_text("\n".join(fo_lines) + "\n", encoding="utf-8")
    paths["foot"] = str(fo_out)

    return paths


def terminal_launch_cmd(
    cmd: list[str] | str | None = None,
    font_px: int | None = None,
    terminal: str | None = None,
    cwd: str | Path | None = None,
    state_path: str | Path | None = None,
) -> list[str]:
    """Build a command list to launch an Omarchy terminal with studio font_px."""
    if font_px is None:
        font_px = int(_studio_from_state_or_defaults(state_path=state_path)["font_px"])
    else:
        font_px = int(font_px)

    term = terminal or detect_terminal()
    cwd_str = str(Path(cwd).expanduser()) if cwd else None

    cmd_args: list[str] = []
    if isinstance(cmd, str):
        cmd_args = ["bash", "-lc", cmd]
    elif cmd:
        cmd_args = [str(x) for x in cmd]

    if term == "ghostty":
        argv = ["ghostty", f"--font-size={font_px}"]
        if cwd_str:
            argv.append(f"--working-directory={cwd_str}")
        if cmd_args:
            argv.extend(["-e", *cmd_args])
        return argv

    if term == "alacritty":
        argv = ["alacritty", "-o", f"font.size={font_px}"]
        if cwd_str:
            argv.extend(["--working-directory", cwd_str])
        if cmd_args:
            argv.extend(["-e", *cmd_args])
        return argv

    if term == "kitty":
        argv = ["kitty", "-o", f"font_size={float(font_px)}"]
        if cwd_str:
            argv.extend(["--directory", cwd_str])
        if cmd_args:
            argv.extend(cmd_args)
        return argv

    if term == "foot":
        argv = ["foot", "-o", f"main.font={_foot_font_family()}:size={font_px}"]
        if cwd_str:
            argv.append(f"--working-directory={cwd_str}")
        if cmd_args:
            argv.extend(cmd_args)
        return argv

    raise ValueError(f"Unsupported terminal: {term}")


def detect_browser() -> str:
    """Detect the default Chromium-family (or system) browser executable."""
    if shutil.which("omarchy-cmd-default-browser"):
        try:
            desktop = _run(["omarchy-cmd-default-browser"], check=False).stdout.strip()
            if desktop:
                data_dirs = [
                    os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")),
                    *(os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")),
                ]
                for dd in data_dirs:
                    p = Path(dd) / "applications" / desktop
                    if p.is_file():
                        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                            if line.startswith("Exec="):
                                exe = line.split("=", 1)[1].strip().split()[0]
                                if shutil.which(exe):
                                    return exe
                        break
        except Exception:
            pass

    for exe in (
        "chromium",
        "google-chrome",
        "google-chrome-stable",
        "brave",
        "brave-browser",
        "vivaldi",
        "microsoft-edge",
    ):
        if shutil.which(exe):
            return exe
    raise FileNotFoundError("No Chromium-family browser found on PATH")


def browser_launch_cmd(
    url: str | None = None,
    zoom: float | None = None,
    browser: str | None = None,
    extra_args: list[str] | None = None,
    state_path: str | Path | None = None,
) -> list[str]:
    """Build a command list to launch Chromium with --force-device-scale-factor=<zoom>."""
    if zoom is None:
        zoom = float(_studio_from_state_or_defaults(state_path=state_path)["browser_zoom"])
    else:
        zoom = float(zoom)

    exe = browser or detect_browser()
    base = os.path.basename(exe).lower()
    argv = [exe]
    if any(name in base for name in ("chromium", "chrome", "brave", "vivaldi", "edge")):
        argv.append(f"--force-device-scale-factor={zoom:g}")
    else:
        warnings.warn(
            f"Browser {exe!r} is not Chromium-based; --force-device-scale-factor may be ignored",
            RuntimeWarning,
        )
    if extra_args:
        argv.extend(extra_args)
    if url:
        argv.append(url)
    return argv


def _check_workspace_empty(workspace: int | str) -> None:
    clients = _hyprctl_json("clients")
    ws_str = str(workspace)
    occupied: list[str] = []
    for c in clients:
        if not c.get("mapped", True):
            continue
        ws = c.get("workspace") or {}
        if str(ws.get("id")) == ws_str or str(ws.get("name")) == ws_str:
            cls = c.get("class") or "?"
            title = c.get("title") or "?"
            addr = c.get("address") or "?"
            occupied.append(f"{cls} — {title} ({addr})")
    if occupied:
        details = "\n  ".join(occupied)
        raise RuntimeError(f"Target workspace {ws_str} is not empty:\n  {details}")


def prepare(
    script: dict[str, Any] | str | Path | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare the desktop stage and save prior state to $XDG_RUNTIME_DIR/td-stage.json."""
    sp = Path(state_path) if state_path else default_state_path()
    if sp.is_file():
        try:
            existing = json.loads(sp.read_text(encoding="utf-8"))
            if existing.get("active"):
                restore(sp)
        except Exception:
            pass

    cfg = _load_script(script)
    screen = cfg.get("screen") or {}
    workspace = screen.get("workspace", DEFAULT_WORKSPACE)
    studio = _studio_from_state_or_defaults(cfg.get("studio"))

    # Check emptiness before changing anything.
    _check_workspace_empty(workspace)
    active_ws = _hyprctl_json("activeworkspace")
    prior_ws = active_ws.get("id") if active_ws.get("id") is not None else active_ws.get("name")

    state: dict[str, Any] = {
        "active": True,
        "pid": os.getpid(),
        "workspace": workspace,
        "prior_workspace": prior_ws,
        "studio": studio,
        "dnd": None,
        "bar": None,
        "wallpaper": None,
        "cursor": None,
        "override_dir": None,
    }
    _atomic_write_json(sp, state)

    try:
        # 1. Switch to target workspace.
        _run(["hyprctl", "dispatch", "workspace", str(workspace)])

        # 2. Do-not-disturb.
        if shutil.which("makoctl") and _proc_running("mako"):
            modes_res = _run(["makoctl", "mode"], check=False)
            modes = modes_res.stdout.split() if modes_res.returncode == 0 else []
            was_dnd = "do-not-disturb" in modes
            if not was_dnd:
                _run(["makoctl", "mode", "-a", "do-not-disturb"])
            state["dnd"] = {"backend": "mako", "was_enabled": was_dnd}
        elif shutil.which("omarchy-shell") and _proc_running("quickshell"):
            dnd_res = _run(["omarchy-shell", "notifications", "isDnd"], check=False)
            if dnd_res.returncode == 0 and dnd_res.stdout.strip() in ("on", "off"):
                was_dnd = dnd_res.stdout.strip() == "on"
                if not was_dnd:
                    _run(["omarchy-shell", "notifications", "setDnd", "on"])
                    _run(["omarchy-shell", "-q", "omarchy.indicators", "refresh"], check=False)
                state["dnd"] = {"backend": "omarchy", "was_enabled": was_dnd}
            else:
                warnings.warn("Notification daemon is not mako; DND could not be toggled", RuntimeWarning)
                state["dnd"] = {"backend": "none"}
        else:
            warnings.warn("Notification daemon is not mako; DND skipped", RuntimeWarning)
            state["dnd"] = {"backend": "none"}
        _atomic_write_json(sp, state)

        # 3. Hide bar.
        if studio.get("hide_bar", True):
            if shutil.which("omarchy-toggle-bar") and _proc_running("quickshell"):
                flag = Path.home() / ".local/state/omarchy/toggles/bar-off"
                was_hidden = flag.exists()
                if not was_hidden:
                    _run(["omarchy-toggle-bar", "on"])
                state["bar"] = {"backend": "omarchy", "was_hidden": was_hidden}
            elif _proc_running("waybar") and shutil.which("pkill"):
                _run(["pkill", "-SIGUSR1", "-x", "waybar"])
                state["bar"] = {"backend": "waybar", "toggled": True}
            else:
                state["bar"] = {"backend": "none"}
            _atomic_write_json(sp, state)

        # 4. Wallpaper.
        wp = studio.get("wallpaper", "plain")
        if wp and wp != "keep":
            temp_bg: Path | None = None
            if wp == "plain":
                temp_bg = _runtime_dir() / "td-stage-bg.png"
                _write_solid_png(temp_bg, _resolve_theme_bg_hex())
                bg_path = str(temp_bg)
            else:
                p = Path(str(wp)).expanduser().resolve()
                if not p.is_file():
                    raise FileNotFoundError(f"Wallpaper file not found: {p}")
                bg_path = str(p)

            if shutil.which("omarchy-theme-bg-set"):
                cur_link = Path.home() / ".local/state/omarchy/current/background"
                prior_bg = os.path.realpath(cur_link) if (cur_link.exists() or cur_link.is_symlink()) else None
                _run(["omarchy-theme-bg-set", bg_path])
                state["wallpaper"] = {
                    "backend": "omarchy",
                    "prior_bg": prior_bg,
                    "temp_file": str(temp_bg) if temp_bg else None,
                }
            elif shutil.which("swaybg"):
                prior_cmds = _find_swaybg_cmdlines()
                if prior_cmds and shutil.which("pkill"):
                    _run(["pkill", "-x", "swaybg"], check=False)
                proc = subprocess.Popen(
                    ["swaybg", "-i", bg_path, "-m", "fill"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                state["wallpaper"] = {
                    "backend": "swaybg",
                    "pid": proc.pid,
                    "prior_cmds": prior_cmds,
                    "temp_file": str(temp_bg) if temp_bg else None,
                }
            else:
                if temp_bg and temp_bg.exists():
                    temp_bg.unlink()
                state["wallpaper"] = {"backend": "none"}
            _atomic_write_json(sp, state)

        # 5. Cursor size.
        cursor_px = int(studio.get("cursor_px", 32))
        theme, prior_size = _detect_cursor_info()
        _run(["hyprctl", "setcursor", theme, str(cursor_px)])
        state["cursor"] = {
            "theme": theme,
            "prior_size": prior_size,
            "studio_size": cursor_px,
        }
        _atomic_write_json(sp, state)

        # 6. Prepare temporary terminal override configs (non-destructive).
        override_dir = _runtime_dir() / "td-stage-overrides"
        prepare_terminal_override(int(studio.get("font_px", 18)), override_dir=override_dir)
        state["override_dir"] = str(override_dir)
        _atomic_write_json(sp, state)
    except Exception:
        restore(sp)
        raise

    return state


def restore(state_path: str | Path | None = None) -> dict[str, Any]:
    """Restore desktop state saved in td-stage.json. Idempotent and safe in finally blocks."""
    sp = Path(state_path) if state_path else default_state_path()
    if not sp.is_file():
        return {"restored": False, "errors": []}

    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"restored": False, "errors": [f"Failed to read {sp}: {exc}"]}

    if not state.get("active"):
        return {"restored": False, "errors": []}

    errors: list[str] = []

    # 1. Restore cursor.
    cursor = state.get("cursor")
    if isinstance(cursor, dict) and cursor.get("theme") and cursor.get("prior_size"):
        try:
            _run(["hyprctl", "setcursor", str(cursor["theme"]), str(cursor["prior_size"])])
        except Exception as exc:
            errors.append(f"cursor restore: {exc}")

    # 2. Restore wallpaper.
    wp = state.get("wallpaper")
    if isinstance(wp, dict):
        try:
            backend = wp.get("backend")
            if backend == "omarchy" and wp.get("prior_bg") and shutil.which("omarchy-theme-bg-set"):
                if Path(wp["prior_bg"]).exists():
                    _run(["omarchy-theme-bg-set", str(wp["prior_bg"])])
            elif backend == "swaybg":
                pid = wp.get("pid")
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                for cmd in wp.get("prior_cmds") or []:
                    if cmd:
                        subprocess.Popen(
                            cmd,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
        except Exception as exc:
            errors.append(f"wallpaper restore: {exc}")
        temp_file = wp.get("temp_file")
        if temp_file:
            try:
                Path(temp_file).unlink(missing_ok=True)
            except Exception as exc:
                errors.append(f"temp wallpaper cleanup: {exc}")

    # 3. Restore bar.
    bar = state.get("bar")
    if isinstance(bar, dict):
        try:
            backend = bar.get("backend")
            if backend == "omarchy" and not bar.get("was_hidden") and shutil.which("omarchy-toggle-bar"):
                _run(["omarchy-toggle-bar", "off"])
            elif backend == "waybar" and bar.get("toggled") and _proc_running("waybar"):
                _run(["pkill", "-SIGUSR1", "-x", "waybar"])
        except Exception as exc:
            errors.append(f"bar restore: {exc}")

    # 4. Restore DND.
    dnd = state.get("dnd")
    if isinstance(dnd, dict) and not dnd.get("was_enabled"):
        try:
            backend = dnd.get("backend")
            if backend == "mako" and shutil.which("makoctl"):
                _run(["makoctl", "mode", "-r", "do-not-disturb"])
            elif backend == "omarchy" and shutil.which("omarchy-shell"):
                _run(["omarchy-shell", "notifications", "setDnd", "off"])
                _run(["omarchy-shell", "-q", "omarchy.indicators", "refresh"], check=False)
        except Exception as exc:
            errors.append(f"dnd restore: {exc}")

    # 5. Restore workspace.
    prior_ws = state.get("prior_workspace")
    if prior_ws is not None:
        try:
            _run(["hyprctl", "dispatch", "workspace", str(prior_ws)])
        except Exception as exc:
            errors.append(f"workspace restore: {exc}")

    # 6. Clean up terminal override directory.
    override_dir = state.get("override_dir")
    if override_dir:
        try:
            shutil.rmtree(override_dir, ignore_errors=True)
        except Exception as exc:
            errors.append(f"override cleanup: {exc}")

    try:
        sp.unlink(missing_ok=True)
    except Exception as exc:
        errors.append(f"state file cleanup: {exc}")

    if errors:
        print("stage.restore warnings:\n  " + "\n  ".join(errors), file=sys.stderr)
    return {"restored": True, "errors": errors}


class Stage:
    """Context manager guaranteeing desktop stage restore on exit, error, or signal."""

    def __init__(
        self,
        script: dict[str, Any] | str | Path | None = None,
        state_path: str | Path | None = None,
        install_signal_handlers: bool = True,
    ) -> None:
        self.script = script
        self.state_path = Path(state_path) if state_path else default_state_path()
        self.install_signal_handlers = install_signal_handlers
        self.state: dict[str, Any] | None = None
        self._prev_handlers: dict[int, Any] = {}
        self._atexit_registered = False

    def _on_signal(self, signum: int, frame: Any) -> None:
        self.restore()
        self._restore_signal_handlers()
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    def _install_signal_handlers(self) -> None:
        if not self.install_signal_handlers:
            return
        if threading.current_thread() is not threading.main_thread():
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._on_signal)
            except Exception:
                pass
        if not self._atexit_registered:
            atexit.register(self.restore)
            self._atexit_registered = True

    def _restore_signal_handlers(self) -> None:
        for sig, prev in list(self._prev_handlers.items()):
            try:
                signal.signal(sig, prev)
            except Exception:
                pass
        self._prev_handlers.clear()
        if self._atexit_registered:
            try:
                atexit.unregister(self.restore)
            except Exception:
                pass
            self._atexit_registered = False

    def prepare(self) -> dict[str, Any]:
        self.state = prepare(self.script, state_path=self.state_path)
        return self.state

    def restore(self) -> dict[str, Any]:
        return restore(state_path=self.state_path)

    def __enter__(self) -> Stage:
        self._install_signal_handlers()
        try:
            self.prepare()
        except Exception:
            self.restore()
            self._restore_signal_handlers()
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            self.restore()
        finally:
            self._restore_signal_handlers()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="tutorial-director desktop stage prepare/restore")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_prep = sub.add_parser("prepare", help="Prepare clean desktop stage")
    sp_prep.add_argument("--script", default=None, help="Path to script.json")
    sp_prep.add_argument("--state", default=None, help="Override state file path")

    sp_rest = sub.add_parser("restore", help="Restore desktop stage from state file")
    sp_rest.add_argument("--state", default=None, help="Override state file path")

    sp_term = sub.add_parser("terminal-cmd", help="Print studio terminal launch argv as JSON")
    sp_term.add_argument("--font-px", type=int, default=None)
    sp_term.add_argument("--terminal", default=None)
    sp_term.add_argument("--cwd", default=None)
    sp_term.add_argument("command", nargs="*")

    sp_br = sub.add_parser("browser-cmd", help="Print studio browser launch argv as JSON")
    sp_br.add_argument("--zoom", type=float, default=None)
    sp_br.add_argument("--browser", default=None)
    sp_br.add_argument("url", nargs="?", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "prepare":
        st = prepare(args.script, state_path=args.state)
        print(json.dumps(st, indent=2))
        return 0
    if args.cmd == "restore":
        res = restore(state_path=args.state)
        print(json.dumps(res, indent=2))
        return 1 if res.get("errors") else 0
    if args.cmd == "terminal-cmd":
        print(json.dumps(terminal_launch_cmd(args.command or None, font_px=args.font_px, terminal=args.terminal, cwd=args.cwd)))
        return 0
    if args.cmd == "browser-cmd":
        print(json.dumps(browser_launch_cmd(url=args.url, zoom=args.zoom, browser=args.browser)))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
