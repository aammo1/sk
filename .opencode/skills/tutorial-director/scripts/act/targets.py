"""Target resolution (coords, window fraction, OpenCV image match, Tesseract OCR) for tutorial-director."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Callable, Sequence

from . import hypr

TESSERACT_INSTALL_MSG = (
    "tesseract not found or missing language data. Install with: "
    "sudo pacman -S tesseract tesseract-data-eng tesseract-data-fra tesseract-data-ara"
)


class TargetError(RuntimeError):
    """Base error for target resolution failures."""


class TargetNotFoundError(TargetError):
    """Raised when an image or text target cannot be found on screen."""


def _default_runner(
    cmd: Sequence[str],
    *,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def _find_cv2_python() -> str | None:
    for cand in (
        os.environ.get("TD_PY"),
        os.environ.get("EV2_PY"),
        os.path.expanduser("~/.cache/editor-v2/venv/bin/python"),
    ):
        if cand and os.path.isfile(cand):
            return cand
    return None


def _png_dimensions(path: str) -> tuple[int, int] | None:
    """Read (width, height) from a PNG header without external dependencies."""
    try:
        with open(path, "rb") as f:
            sig = f.read(24)
        if len(sig) >= 24 and sig[:8] == b"\x89PNG\r\n\x1a\n" and sig[12:16] == b"IHDR":
            w, h = struct.unpack(">II", sig[16:24])
            return int(w), int(h)
    except OSError:
        pass
    return None


def capture_screenshot(
    out_path: str,
    *,
    monitor: dict[str, Any] | None = None,
    runner: hypr.CommandRunner | None = None,
    hypr_runner: hypr.CommandRunner | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Capture a PNG screenshot via `grim` (scoped to focused monitor when available)."""
    run = runner or _default_runner
    if runner is None and not shutil.which("grim"):
        raise TargetError("grim not found. Install it with: sudo pacman -S grim")

    if monitor is None:
        try:
            monitor = hypr.focused_monitor(runner=hypr_runner)
        except hypr.HyprError:
            monitor = None

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cmd = ["grim"]
    if monitor and monitor.get("name"):
        cmd.extend(["-o", str(monitor["name"])])
    cmd.append(out_path)

    res = run(cmd, timeout=10.0)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise TargetError(f"grim failed (exit {res.returncode}): {detail}")
    return out_path, monitor


def _pixel_to_logical(
    px: float,
    py: float,
    img_size: tuple[int, int] | None,
    monitor: dict[str, Any] | None,
) -> tuple[float, float]:
    if monitor is None:
        return float(px), float(py)
    mx, my, lw, lh = hypr.monitor_logical_rect(monitor)
    if img_size and img_size[0] > 0 and img_size[1] > 0:
        return mx + (px / img_size[0]) * lw, my + (py / img_size[1]) * lh
    scale = float(monitor.get("scale") or 1.0)
    return mx + px / scale, my + py / scale


def match_image(
    screenshot_path: str,
    template_path: str,
    *,
    threshold: float = 0.85,
) -> tuple[float, float, float, tuple[int, int]]:
    """Run OpenCV `matchTemplate` (`TM_CCOEFF_NORMED`).

    Returns `(center_x_px, center_y_px, score, (img_w, img_h))`.
    Raises `TargetNotFoundError` if `score < threshold`.
    """
    if not os.path.isfile(template_path):
        raise TargetError(f"Template image not found: {template_path}")

    try:
        import cv2  # type: ignore
    except ImportError:
        cv2 = None

    if cv2 is not None:
        screen = cv2.imread(screenshot_path, cv2.IMREAD_COLOR)
        tmpl = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if screen is None:
            raise TargetError(f"Could not read screenshot: {screenshot_path}")
        if tmpl is None:
            raise TargetError(f"Could not read template image: {template_path}")
        sh, sw = screen.shape[:2]
        th, tw = tmpl.shape[:2]
        if th > sh or tw > sw:
            raise TargetNotFoundError(
                f"Template {template_path} ({tw}x{th}) is larger than screenshot ({sw}x{sh})"
            )
        res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        score = float(max_val)
        cx = float(max_loc[0]) + tw / 2.0
        cy = float(max_loc[1]) + th / 2.0
        img_size = (int(sw), int(sh))
    else:
        py = _find_cv2_python()
        if not py:
            raise TargetError(
                "OpenCV (cv2) is not available in current Python and no TD_PY/EV2_PY venv was found"
            )
        code = (
            "import json, sys, cv2\n"
            "s = cv2.imread(sys.argv[1], cv2.IMREAD_COLOR)\n"
            "t = cv2.imread(sys.argv[2], cv2.IMREAD_COLOR)\n"
            "if s is None or t is None:\n"
            "    print(json.dumps({'err': 'imread failed'})); sys.exit(2)\n"
            "sh, sw = s.shape[:2]; th, tw = t.shape[:2]\n"
            "if th > sh or tw > sw:\n"
            "    print(json.dumps({'err': 'template larger than screen'})); sys.exit(3)\n"
            "r = cv2.matchTemplate(s, t, cv2.TM_CCOEFF_NORMED)\n"
            "_, v, _, loc = cv2.minMaxLoc(r)\n"
            "print(json.dumps({'score': float(v), 'cx': loc[0] + tw / 2.0, 'cy': loc[1] + th / 2.0, 'sw': int(sw), 'sh': int(sh)}))\n"
        )
        proc = subprocess.run(
            [py, "-c", code, screenshot_path, template_path],
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        if proc.returncode != 0:
            detail = (proc.stdout or proc.stderr or "").strip()
            if proc.returncode == 3:
                raise TargetNotFoundError(detail)
            raise TargetError(f"OpenCV template match failed: {detail}")
        info = json.loads(proc.stdout)
        score = float(info["score"])
        cx = float(info["cx"])
        cy = float(info["cy"])
        img_size = (int(info["sw"]), int(info["sh"]))

    if score < threshold:
        raise TargetNotFoundError(
            f"Image target {template_path!r} not found (best match {score:.3f} < {threshold:.2f})"
        )
    return cx, cy, score, img_size


def _installed_tesseract_langs(runner: hypr.CommandRunner) -> set[str]:
    try:
        res = runner(["tesseract", "--list-langs"], timeout=5.0)
        if res.returncode != 0:
            return set()
        lines = [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]
        return {ln for ln in lines[1:] if not ln.startswith("List of")}
    except Exception:
        return set()


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F" for ch in text)


def _run_tesseract_tsv(
    screenshot_path: str,
    query: str,
    langs: str,
    *,
    runner: hypr.CommandRunner | None = None,
) -> str:
    run = runner or _default_runner
    if runner is None and not shutil.which("tesseract"):
        raise TargetError(TESSERACT_INSTALL_MSG)

    cmd = ["tesseract", screenshot_path, "-", "-l", langs, "tsv"]
    res = run(cmd, timeout=15.0)
    if res.returncode == 0:
        return res.stdout

    stderr = (res.stderr or res.stdout or "").strip()
    if "Error opening data file" in stderr or "Failed loading language" in stderr:
        installed = _installed_tesseract_langs(run)
        wanted = [l.strip() for l in langs.split("+") if l.strip()]
        avail = [l for l in wanted if l in installed]
        if _has_arabic(query) and "ara" not in installed:
            raise TargetError(TESSERACT_INSTALL_MSG)
        if avail:
            res2 = run(["tesseract", screenshot_path, "-", "-l", "+".join(avail), "tsv"], timeout=15.0)
            if res2.returncode == 0:
                return res2.stdout
            stderr = (res2.stderr or res2.stdout or "").strip()
        raise TargetError(f"{TESSERACT_INSTALL_MSG} ({stderr})")

    raise TargetError(f"tesseract failed (exit {res.returncode}): {stderr}")


def parse_tesseract_tsv(tsv_text: str, query: str) -> tuple[float, float, float]:
    """Find `query` in Tesseract TSV output. Returns `(cx_px, cy_px, confidence)`."""
    q_norm = " ".join(query.strip().split()).lower()
    if not q_norm:
        raise TargetError("OCR target text must not be empty")
    q_tokens = q_norm.split()

    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    words: list[dict[str, Any]] = []
    for row in reader:
        txt = (row.get("text") or "").strip()
        if not txt:
            continue
        try:
            conf = float(row.get("conf", -1))
            left = float(row["left"])
            top = float(row["top"])
            width = float(row["width"])
            height = float(row["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if conf < 0:
            continue
        words.append(
            {
                "line_key": (
                    row.get("page_num"),
                    row.get("block_num"),
                    row.get("par_num"),
                    row.get("line_num"),
                ),
                "text": txt,
                "norm": txt.lower(),
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "conf": conf,
            }
        )

    candidates: list[tuple[int, float, float, float]] = []
    n_tok = len(q_tokens)

    if n_tok == 1:
        needle = q_tokens[0]
        for w in words:
            if w["norm"] == needle:
                score_tier = 2
            elif needle in w["norm"]:
                score_tier = 1
            else:
                continue
            cx = (w["left"] + w["right"]) / 2.0
            cy = (w["top"] + w["bottom"]) / 2.0
            candidates.append((score_tier, w["conf"], cx, cy))
    else:
        for i in range(0, len(words) - n_tok + 1):
            span = words[i : i + n_tok]
            if len({w["line_key"] for w in span}) != 1:
                continue
            joined = " ".join(w["norm"] for w in span)
            if joined == q_norm:
                score_tier = 2
            elif q_norm in joined:
                score_tier = 1
            else:
                continue
            left = min(w["left"] for w in span)
            top = min(w["top"] for w in span)
            right = max(w["right"] for w in span)
            bottom = max(w["bottom"] for w in span)
            avg_conf = sum(w["conf"] for w in span) / n_tok
            candidates.append((score_tier, avg_conf, (left + right) / 2.0, (top + bottom) / 2.0))

    if not candidates:
        raise TargetNotFoundError(f"Text target {query!r} not found via OCR")

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    _, best_conf, cx, cy = candidates[0]
    return cx, cy, best_conf


def find_text(
    screenshot_path: str,
    query: str,
    *,
    langs: str = "eng+fra+ara",
    runner: hypr.CommandRunner | None = None,
) -> tuple[float, float, float, tuple[int, int] | None]:
    """Run Tesseract TSV OCR on `screenshot_path` and locate `query`."""
    tsv = _run_tesseract_tsv(screenshot_path, query, langs=langs, runner=runner)
    cx, cy, conf = parse_tesseract_tsv(tsv, query)
    return cx, cy, conf, _png_dimensions(screenshot_path)


def resolve(
    target: Sequence[float] | dict[str, Any],
    *,
    monitor: dict[str, Any] | None = None,
    screenshot_path: str | None = None,
    runner: hypr.CommandRunner | None = None,
    hypr_runner: hypr.CommandRunner | None = None,
) -> tuple[float, float]:
    """Resolve a target spec to logical global `(x, y)` coordinates.

    Supported forms:
    - `[x, y]`
    - `{"window": "class:X", "at": [fx, fy]}`
    - `{"image": "path.png", "threshold": 0.85}`
    - `{"text": "Save", "lang": "eng+fra+ara"}`
    """
    if isinstance(target, (list, tuple)):
        if len(target) != 2:
            raise TargetError(f"Coordinate target must have 2 elements, got {target!r}")
        return float(target[0]), float(target[1])

    if not isinstance(target, dict):
        raise TargetError(f"Unsupported target spec: {target!r}")

    if "window" in target:
        wx, wy, ww, wh = hypr.window_rect(str(target["window"]), runner=hypr_runner)
        at = target.get("at", [0.5, 0.5])
        if len(at) != 2:
            raise TargetError(f"Window 'at' fraction must have 2 elements, got {at!r}")
        fx, fy = float(at[0]), float(at[1])
        return wx + fx * ww, wy + fy * wh

    if "image" in target or "text" in target:
        tmp_dir: str | None = None
        shot = screenshot_path
        mon = monitor
        if shot is None:
            tmp_dir = tempfile.mkdtemp(prefix="td-target-")
            shot = os.path.join(tmp_dir, "shot.png")
            _, mon = capture_screenshot(shot, monitor=monitor, runner=runner, hypr_runner=hypr_runner)
        try:
            if "image" in target:
                thresh = float(target.get("threshold", 0.85))
                cx, cy, _, img_size = match_image(shot, str(target["image"]), threshold=thresh)
                return _pixel_to_logical(cx, cy, img_size, mon)
            langs = str(target.get("lang", "eng+fra+ara"))
            cx, cy, _, img_size = find_text(shot, str(target["text"]), langs=langs, runner=runner)
            return _pixel_to_logical(cx, cy, img_size, mon)
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    raise TargetError(f"Unknown target dict keys: {list(target.keys())!r}")
