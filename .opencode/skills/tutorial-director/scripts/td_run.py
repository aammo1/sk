#!/usr/bin/env python3
"""td_run.py — Execute tutorial-director runs (`td dry`, `td record`, `td handoff`)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import rec as rec_mod  # noqa: E402
import stage as stage_mod  # noqa: E402
import td_handoff  # noqa: E402
import td_script  # noqa: E402
from act import hypr, mouse, targets  # noqa: E402
from act.driver import (  # noqa: E402
    ActionError,
    Driver,
    StopRequested,
    clear_stop,
)
from tts.base import wav_duration  # noqa: E402

SCREEN_CHANGING_ACTIONS = frozenset(
    {
        "key",
        "type",
        "click",
        "scroll",
        "drag",
        "focus",
        "workspace",
        "launch",
        "move_window",
        "shell",
    }
)

TERMINAL_BINS = frozenset({"alacritty", "ghostty", "kitty", "foot"})
CHROMIUM_BINS = frozenset(
    {
        "chromium",
        "google-chrome",
        "google-chrome-stable",
        "brave",
        "brave-browser",
        "vivaldi",
        "microsoft-edge",
    }
)


class RunError(RuntimeError):
    """Actionable pre-flight or runner error."""


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".txt", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _preflight(run: str) -> tuple[Path, dict[str, Any], str, dict[str, float]]:
    """Validate script.json and rendered voice WAVs for a run."""
    run_dir = Path(td_script.resolve_run(run)).resolve()
    script_path = run_dir / "script.json"
    if not script_path.is_file():
        raise RunError(f"script.json not found: {script_path}")

    raw = json.loads(script_path.read_text(encoding="utf-8"))
    probs = td_script.validate_script(raw)
    if probs:
        detail = "\n  ".join(f"FIX  {p}" for p in probs)
        raise RunError(f"script.json failed validation (`td check`):\n  {detail}")

    script = td_script.load_script(str(run_dir))
    sha = td_script.script_sha(str(run_dir))

    voice_dir = run_dir / "voice"
    index_path = voice_dir / "index.json"
    if not index_path.is_file():
        raise RunError(f"Voice index missing: {index_path} — run `td voice render {run}` first")

    try:
        idx_raw = json.loads(index_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RunError(f"Invalid voice/index.json: {exc}") from exc

    idx_by_id = {
        str(e["id"]): e for e in (idx_raw if isinstance(idx_raw, list) else []) if isinstance(e, dict) and e.get("id")
    }

    voice_durs: dict[str, float] = {}
    for step in script["steps"]:
        sid = str(step["id"])
        wav_path = voice_dir / f"{sid}.wav"
        if sid not in idx_by_id:
            raise RunError(f"Step {sid!r} missing from voice/index.json — run `td voice render {run}`")
        if not wav_path.is_file() or wav_path.stat().st_size <= 44:
            raise RunError(f"Missing rendered WAV for step {sid!r}: {wav_path} — run `td voice render {run}`")
        dur_val = idx_by_id[sid].get("dur")
        if isinstance(dur_val, (int, float)) and dur_val > 0:
            voice_durs[sid] = float(dur_val)
        else:
            voice_durs[sid] = wav_duration(str(wav_path))

    return run_dir, script, sha, voice_durs


def _wrap_launch_action(action: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    """Apply studio font_px / browser_zoom flags when launching a terminal or Chromium browser."""
    kind = action.get("do") or action.get("type")
    if kind != "launch":
        return action
    cmd_str = str(action.get("cmd") or "").strip()
    if not cmd_str:
        return action
    try:
        tokens = shlex.split(cmd_str)
    except ValueError:
        return action
    if not tokens:
        return action

    studio = script.get("studio") or {}
    font_px = int(studio.get("font_px", 18))
    zoom = float(studio.get("browser_zoom", 1.25))
    exe = os.path.basename(tokens[0]).lower()
    extra: list[str] = []

    if exe in TERMINAL_BINS:
        if exe == "alacritty" and not any("font.size" in t for t in tokens):
            extra = ["-o", f"font.size={font_px}"]
        elif exe == "ghostty" and not any(t.startswith("--font-size") for t in tokens):
            extra = [f"--font-size={font_px}"]
        elif exe == "kitty" and not any("font_size" in t for t in tokens):
            extra = ["-o", f"font_size={float(font_px)}"]
        elif exe == "foot" and not any("main.font" in t for t in tokens):
            extra = ["-o", f"main.font={stage_mod._foot_font_family()}:size={font_px}"]
    elif exe in CHROMIUM_BINS:
        if not any(t.startswith("--force-device-scale-factor") for t in tokens):
            extra = [f"--force-device-scale-factor={zoom:g}"]

    if not extra:
        return action
    wrapped = dict(action)
    wrapped["cmd"] = shlex.join([tokens[0], *extra, *tokens[1:]])
    return wrapped


def _sleep_until(
    target_t: float,
    driver: Driver,
    clock: Callable[[], float],
    sleep_fn: Callable[[float], None],
) -> None:
    """Sleep until `clock() >= target_t`, polling `driver.check_stop()` periodically."""
    while True:
        driver.check_stop()
        now = clock()
        rem = target_t - now
        if rem <= 0:
            return
        dt = min(0.05, rem)
        sleep_fn(dt)
        after = clock()
        if after <= now and dt > 0:
            # Guard against frozen fake clocks in tests
            return


def _read_new_events(log_path: str | None, offset: int) -> tuple[list[dict[str, Any]], int]:
    if not log_path or not os.path.isfile(log_path):
        return [], offset
    size = os.path.getsize(log_path)
    if size <= offset:
        return [], size
    with open(log_path, "r", encoding="utf-8") as f:
        f.seek(offset)
        chunk = f.read()
        new_off = f.tell()
    events: list[dict[str, Any]] = []
    for ln in chunk.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            ev = json.loads(ln)
            if isinstance(ev, dict):
                events.append(ev)
        except ValueError:
            pass
    return events, new_off


def _extract_action_meta(
    action: dict[str, Any],
    kind: str,
    res: dict[str, Any],
    new_events: list[dict[str, Any]],
    driver: Driver,
) -> dict[str, Any]:
    """Extract event timestamp and target screen (x, y) for callouts."""
    meta: dict[str, Any] = {}
    for ev in new_events:
        if ev.get("type") in ("down", "key", "scroll", "type_start"):
            meta.setdefault("event_t", float(ev["t"]))
        if "x" in ev and "y" in ev:
            meta["x"] = float(ev["x"])
            meta["y"] = float(ev["y"])

    if "x" not in meta and "x" in res and "y" in res:
        sx, sy = driver._screen_xy(float(res["x"]), float(res["y"]))
        meta["x"], meta["y"] = sx, sy

    if "x" not in meta and kind in ("focus", "launch", "move_window") and action.get("window"):
        try:
            wx, wy, ww, wh = hypr.window_rect(str(action["window"]), runner=driver._hypr_runner)
            sx, sy = driver._screen_xy(wx + ww / 2.0, wy + wh / 2.0)
            meta["x"], meta["y"] = sx, sy
        except Exception:
            pass

    if "x" not in meta and kind in ("click", "scroll", "drag", "move") and driver._cursor is not None:
        sx, sy = driver._screen_xy(driver._cursor[0], driver._cursor[1])
        meta["x"], meta["y"] = sx, sy

    return meta


def _run_hook_actions(
    actions: list[dict[str, Any]],
    *,
    step_id: str,
    driver: Driver,
    script: dict[str, Any],
) -> None:
    for act in actions:
        driver.check_stop()
        driver.execute(_wrap_launch_action(act, script), step_id=step_id)


def _execute_step(
    step: dict[str, Any],
    *,
    voice_wav: Path,
    voice_dur: float,
    driver: Driver,
    script: dict[str, Any],
    clock: Callable[[], float],
    sleep_fn: Callable[[float], None],
    listen: bool = False,
) -> dict[str, Any]:
    """Execute one tutorial step following the spread-across-voice timing contract."""
    sid = str(step["id"])
    step_start = clock()

    if step.get("layout"):
        sl = step["layout"]
        driver.place(str(sl["window"]), str(sl["slot"]))

    t0 = clock()
    voice_start = t0
    voice_end = t0 + voice_dur

    pw_proc: subprocess.Popen[bytes] | None = None
    if listen and voice_wav.is_file() and shutil.which("pw-play"):
        pw_proc = subprocess.Popen(
            ["pw-play", str(voice_wav)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    actions = step.get("actions") or []
    n_actions = len(actions)
    action_records: list[dict[str, Any]] = []
    last_screen_action_end: float | None = None

    try:
        for k, raw_act in enumerate(actions):
            driver.check_stop()
            kind = str(raw_act.get("do") or raw_act.get("type") or "")
            if kind not in ("wait_for", "check") and n_actions > 0:
                target_t = t0 + 0.15 + k * (voice_dur * 0.8 / n_actions)
                if clock() < target_t:
                    _sleep_until(target_t, driver, clock, sleep_fn)

            act = _wrap_launch_action(raw_act, script)
            log_offset = (
                os.path.getsize(driver.event_log_path)
                if driver.event_log_path and os.path.isfile(driver.event_log_path)
                else 0
            )
            act_start = clock()
            res = driver.execute(act, step_id=sid)
            act_end = clock()
            new_events, _ = _read_new_events(driver.event_log_path, log_offset)

            rec_act: dict[str, Any] = {
                "index": k,
                "do": kind,
                "start": act_start,
                "end": act_end,
            }
            rec_act.update(_extract_action_meta(act, kind, res, new_events, driver))
            action_records.append(rec_act)
            if kind in SCREEN_CHANGING_ACTIONS:
                last_screen_action_end = act_end

        actions_end = clock()
        pause_after = float(step["pause_after"]) if step.get("pause_after") is not None else 0.4
        target_end = max(voice_end, actions_end) + max(0.0, pause_after)
        if clock() < target_end:
            _sleep_until(target_end, driver, clock, sleep_fn)
    finally:
        if pw_proc is not None:
            if pw_proc.poll() is None:
                try:
                    pw_proc.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    pw_proc.terminate()
                    try:
                        pw_proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pw_proc.kill()
                        pw_proc.wait(timeout=1.0)

    step_end = clock()
    return {
        "id": sid,
        "start": step_start,
        "end": step_end,
        "voice_start": voice_start,
        "voice_end": voice_end,
        "ok": True,
        "last_screen_action_end": last_screen_action_end,
        "actions": action_records,
    }


def _resolve_monitor(script: dict[str, Any], explicit_monitor: str | None = None) -> dict[str, Any] | None:
    req = explicit_monitor or (script.get("screen") or {}).get("monitor")
    name = None if (not req or str(req).strip().lower() == "auto") else str(req).strip()
    try:
        return hypr.focused_monitor(name=name)
    except Exception:
        return None


def _collect_screenshots(checks_dir: Path) -> list[dict[str, Any]]:
    """Gather check results + screenshot paths from `checks/checks.jsonl` and `checks/*.png`."""
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    manifest = checks_dir / "checks.jsonl"
    if manifest.is_file():
        for ln in manifest.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("screenshot"):
                seen_paths.add(os.path.abspath(str(rec["screenshot"])))
                entries.append(rec)
    if checks_dir.is_dir():
        for png in sorted(checks_dir.glob("*.png")):
            ap = os.path.abspath(str(png))
            if ap not in seen_paths:
                entries.append({"step": png.stem, "screenshot": str(png), "expect": "", "ok": True})
    return entries


def _write_dry_report(
    report_path: Path,
    *,
    run_name: str,
    script: dict[str, Any],
    sha: str,
    step_results: list[dict[str, Any]],
    screenshots: list[dict[str, Any]],
    overall_ok: bool,
    failed_step: str | None,
    error_msg: str | None,
    dry_start: float,
) -> None:
    status_label = "PASS" if overall_ok else "FAIL"
    lines = [
        f"# Dry Run Report: {script.get('title', run_name)}",
        "",
        f"- **Run:** `{run_name}`",
        f"- **Status:** **{status_label}**",
        f"- **Script SHA-256:** `{sha}`",
        f"- **Timestamp (UTC):** {datetime.now(timezone.utc).isoformat()}",
    ]
    if failed_step:
        lines.append(f"- **Failed Step:** `{failed_step}` — {error_msg}")
    lines.extend(
        [
            "",
            "## Steps",
            "",
            "| Step | Status | Start (s) | End (s) | Duration (s) | Voice (s) | Notes |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for st in step_results:
        s0 = max(0.0, float(st["start"]) - dry_start)
        s1 = max(s0, float(st["end"]) - dry_start)
        vd = max(0.0, float(st["voice_end"]) - float(st["voice_start"]))
        ok_txt = "OK" if st.get("ok") else "FAIL"
        note = str(st.get("error") or "")
        lines.append(f"| `{st['id']}` | {ok_txt} | {s0:.2f} | {s1:.2f} | {s1 - s0:.2f} | {vd:.2f} | {note} |")

    lines.extend(["", "## Check Screenshots", ""])
    if screenshots:
        for sc in screenshots:
            st_lbl = "PASS" if sc.get("ok", True) else f"FAIL ({sc.get('error', '')})"
            exp = f" — expect: `{sc['expect']}`" if sc.get("expect") else ""
            lines.append(f"- `{sc['screenshot']}` [{st_lbl}]{exp}")
    else:
        lines.append("- *(none — no `check` actions in script)*")
    lines.append("")
    _atomic_write_text(report_path, "\n".join(lines))


def run_dry(
    run: str,
    *,
    listen: bool = False,
    max_step_s: float = 60.0,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    driver_factory: Callable[..., Driver] | None = None,
    stage_factory: Callable[..., Any] | None = None,
) -> int:
    """Execute a dry run (no screen recording) and write dry/report.md + dry/status.json."""
    try:
        run_dir, script, sha, voice_durs = _preflight(run)
    except (RunError, FileNotFoundError, ValueError) as exc:
        print(f"dry: {exc}", file=sys.stderr)
        return 1

    clear_stop()

    dry_dir = run_dir / "dry"
    checks_dir = dry_dir / "checks"
    events_path = dry_dir / "events.jsonl"
    status_path = dry_dir / "status.json"
    report_path = dry_dir / "report.md"
    steps_path = dry_dir / "steps.json"
    dry_dir.mkdir(parents=True, exist_ok=True)
    checks_dir.mkdir(parents=True, exist_ok=True)
    events_path.write_text("", encoding="utf-8")
    (checks_dir / "checks.jsonl").write_text("", encoding="utf-8")

    _atomic_write_json(
        status_path,
        {"ok": False, "status": "running", "script_sha": sha, "timestamp": datetime.now(timezone.utc).isoformat()},
    )

    mon = _resolve_monitor(script)
    make_stage = stage_factory or stage_mod.Stage
    make_driver = driver_factory or Driver

    dry_start = clock()
    step_results: list[dict[str, Any]] = []
    overall_ok = True
    failed_step: str | None = None
    error_msg: str | None = None
    exit_code = 0

    driver = make_driver(
        event_log_path=str(events_path),
        checks_dir=str(checks_dir),
        monitor=mon,
        pace=script.get("pace"),
        layout=script.get("layout"),
        max_step_s=max_step_s,
        dry_run=True,
        clock=clock,
        sleep_fn=sleep_fn,
    )

    try:
        with make_stage(script):
            stop_requested = False
            try:
                setup_actions = script.get("setup") or []
                if setup_actions:
                    _run_hook_actions(setup_actions, step_id="setup", driver=driver, script=script)

                for step in script["steps"]:
                    sid = str(step["id"])
                    wav_path = run_dir / "voice" / f"{sid}.wav"
                    try:
                        res = _execute_step(
                            step,
                            voice_wav=wav_path,
                            voice_dur=voice_durs[sid],
                            driver=driver,
                            script=script,
                            clock=clock,
                            sleep_fn=sleep_fn,
                            listen=listen,
                        )
                        step_results.append(res)
                    except StopRequested as exc:
                        stop_requested = True
                        overall_ok = False
                        failed_step = sid
                        error_msg = str(exc)
                        exit_code = 130
                        now_t = clock()
                        step_results.append(
                            {
                                "id": sid,
                                "start": now_t,
                                "end": now_t,
                                "voice_start": now_t,
                                "voice_end": now_t,
                                "ok": False,
                                "error": error_msg,
                            }
                        )
                        break
                    except Exception as exc:
                        overall_ok = False
                        failed_step = sid
                        error_msg = str(exc)
                        exit_code = 1
                        now_t = clock()
                        step_results.append(
                            {
                                "id": sid,
                                "start": now_t,
                                "end": now_t,
                                "voice_start": now_t,
                                "voice_end": now_t,
                                "ok": False,
                                "error": error_msg,
                            }
                        )
                        break
            except StopRequested as exc:
                stop_requested = True
                overall_ok = False
                failed_step = "setup"
                error_msg = str(exc)
                exit_code = 130
            except Exception as exc:
                overall_ok = False
                failed_step = "setup"
                error_msg = str(exc)
                exit_code = 1
            finally:
                if stop_requested:
                    try:
                        driver.release_all()
                    except Exception:
                        pass
                else:
                    cleanup_actions = script.get("cleanup") or []
                    if cleanup_actions:
                        try:
                            _run_hook_actions(cleanup_actions, step_id="cleanup", driver=driver, script=script)
                        except Exception as exc:
                            print(f"dry: cleanup warning: {exc}", file=sys.stderr)
    finally:
        driver.close()

    screenshots = _collect_screenshots(checks_dir)
    _atomic_write_json(
        steps_path,
        {
            "ok": overall_ok,
            "script_sha": sha,
            "dry_start_monotonic": dry_start,
            "failed_step": failed_step,
            "error": error_msg,
            "steps": step_results,
        },
    )
    _atomic_write_json(
        status_path,
        {
            "ok": overall_ok,
            "status": "passed" if overall_ok else ("stopped" if exit_code == 130 else "failed"),
            "script_sha": sha,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps_ok": sum(1 for s in step_results if s.get("ok")),
            "steps_total": len(script["steps"]),
            "failed_step": failed_step,
            "error": error_msg,
            "screenshots": [sc["screenshot"] for sc in screenshots],
        },
    )
    _write_dry_report(
        report_path,
        run_name=run_dir.name,
        script=script,
        sha=sha,
        step_results=step_results,
        screenshots=screenshots,
        overall_ok=overall_ok,
        failed_step=failed_step,
        error_msg=error_msg,
        dry_start=dry_start,
    )

    if overall_ok:
        print(f"dry: PASS ({len(step_results)}/{len(script['steps'])} steps) -> {report_path}")
        if screenshots:
            print(f"  inspect {len(screenshots)} check screenshot(s) listed in {report_path}")
    else:
        print(f"dry: FAIL at step {failed_step!r}: {error_msg}", file=sys.stderr)
        print(f"  report: {report_path}", file=sys.stderr)
    return exit_code


def _verify_dry_passed(run_dir: Path, sha: str, run_label: str) -> None:
    status_path = run_dir / "dry" / "status.json"
    if not status_path.is_file():
        raise RunError(f"Refusing record: no dry run found ({status_path}). Run `td dry {run_label}` first.")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RunError(f"Refusing record: invalid {status_path}: {exc}") from exc
    if status.get("ok") is not True:
        raise RunError(
            f"Refusing record: latest dry run did not pass (status={status.get('status')!r}). "
            f"Fix issues and run `td dry {run_label}`."
        )
    if status.get("script_sha") != sha:
        raise RunError(
            "Refusing record: script.json changed since the passing dry run. "
            f"Run `td dry {run_label}` again."
        )


def run_record(
    run: str,
    *,
    monitor: str | None = None,
    max_step_s: float = 60.0,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    driver_factory: Callable[..., Driver] | None = None,
    stage_factory: Callable[..., Any] | None = None,
    recorder_factory: Callable[..., Any] | None = None,
) -> int:
    """Execute the real recording after verifying a passing dry run for the same script_sha."""
    try:
        run_dir, script, sha, voice_durs = _preflight(run)
        _verify_dry_passed(run_dir, sha, run)
    except (RunError, FileNotFoundError, ValueError) as exc:
        print(f"record: {exc}", file=sys.stderr)
        return 1

    clear_stop()

    rec_dir = run_dir / "rec"
    checks_dir = rec_dir / "checks"
    events_path = rec_dir / "events.jsonl"
    steps_path = rec_dir / "steps.json"
    rec_dir.mkdir(parents=True, exist_ok=True)
    checks_dir.mkdir(parents=True, exist_ok=True)
    events_path.write_text("", encoding="utf-8")
    (checks_dir / "checks.jsonl").write_text("", encoding="utf-8")

    mon = _resolve_monitor(script, explicit_monitor=monitor)
    lw, lh, mon_scale = 1920.0, 1080.0, 1.0
    if mon is not None:
        _, _, lw, lh = hypr.monitor_logical_rect(mon)
        mon_scale = float(mon.get("scale") or 1.0)

    make_stage = stage_factory or stage_mod.Stage
    make_driver = driver_factory or Driver
    make_recorder = recorder_factory or rec_mod.Recorder

    driver = make_driver(
        event_log_path=str(events_path),
        checks_dir=str(checks_dir),
        monitor=mon,
        pace=script.get("pace"),
        layout=script.get("layout"),
        max_step_s=max_step_s,
        dry_run=False,
        clock=clock,
        sleep_fn=sleep_fn,
    )

    step_results: list[dict[str, Any]] = []
    overall_ok = True
    failed_step: str | None = None
    error_msg: str | None = None
    exit_code = 0
    start_meta: dict[str, Any] = {}
    rec_start_mono: float | None = None

    try:
        with make_stage(script):
            stop_requested = False
            recorder = make_recorder(rec_dir, script=script, monitor=monitor or (script.get("screen") or {}).get("monitor"))
            try:
                setup_actions = script.get("setup") or []
                if setup_actions:
                    _run_hook_actions(setup_actions, step_id="setup", driver=driver, script=script)

                start_meta = recorder.start()
                rec_start_mono = float(start_meta["monotonic_time"])

                # 1.0 s still hold at start of recording
                _sleep_until(clock() + 1.0, driver, clock, sleep_fn)

                for step in script["steps"]:
                    sid = str(step["id"])
                    wav_path = run_dir / "voice" / f"{sid}.wav"
                    try:
                        res = _execute_step(
                            step,
                            voice_wav=wav_path,
                            voice_dur=voice_durs[sid],
                            driver=driver,
                            script=script,
                            clock=clock,
                            sleep_fn=sleep_fn,
                            listen=False,  # Never play TTS aloud during recording
                        )
                        step_results.append(res)
                    except StopRequested as exc:
                        stop_requested = True
                        overall_ok = False
                        failed_step = sid
                        error_msg = str(exc)
                        exit_code = 130
                        now_t = clock()
                        step_results.append(
                            {
                                "id": sid,
                                "start": now_t,
                                "end": now_t,
                                "voice_start": now_t,
                                "voice_end": now_t,
                                "ok": False,
                                "error": error_msg,
                            }
                        )
                        break
                    except Exception as exc:
                        overall_ok = False
                        failed_step = sid
                        error_msg = str(exc)
                        exit_code = 1
                        now_t = clock()
                        step_results.append(
                            {
                                "id": sid,
                                "start": now_t,
                                "end": now_t,
                                "voice_start": now_t,
                                "voice_end": now_t,
                                "ok": False,
                                "error": error_msg,
                            }
                        )
                        break

                if overall_ok:
                    # 1.5 s still hold at end of recording
                    _sleep_until(clock() + 1.5, driver, clock, sleep_fn)
            except StopRequested as exc:
                stop_requested = True
                overall_ok = False
                if failed_step is None:
                    failed_step = "record"
                    error_msg = str(exc)
                exit_code = 130
            except Exception as exc:
                overall_ok = False
                if failed_step is None:
                    failed_step = "record"
                    error_msg = str(exc)
                exit_code = 1
            finally:
                if rec_start_mono is not None or getattr(recorder, "is_running", lambda: False)():
                    try:
                        recorder.stop(normalize=True)
                    except Exception as exc:
                        if overall_ok:
                            overall_ok = False
                            failed_step = "recorder_stop"
                            error_msg = str(exc)
                            exit_code = 1
                        else:
                            print(f"record: recorder stop warning: {exc}", file=sys.stderr)

                if stop_requested:
                    try:
                        driver.release_all()
                    except Exception:
                        pass
                else:
                    cleanup_actions = script.get("cleanup") or []
                    if cleanup_actions:
                        try:
                            _run_hook_actions(cleanup_actions, step_id="cleanup", driver=driver, script=script)
                        except Exception as exc:
                            print(f"record: cleanup warning: {exc}", file=sys.stderr)
    finally:
        driver.close()

    _atomic_write_json(
        steps_path,
        {
            "ok": overall_ok,
            "engine": str((script.get("voice") or {}).get("engine") or "golha"),
            "script_sha": sha,
            "user": getpass.getuser(),
            "rec_start_monotonic": rec_start_mono,
            "rec_start_wall": start_meta.get("wall_time"),
            "logical_width": lw,
            "logical_height": lh,
            "monitor_scale": mon_scale,
            "failed_step": failed_step,
            "error": error_msg,
            "steps": step_results,
        },
    )

    if overall_ok:
        print(f"record: OK ({len(step_results)} steps) -> {rec_dir / 'screen.mp4'}")
        print(f"  next: td handoff {run}")
    else:
        print(f"record: FAILED at {failed_step!r}: {error_msg} (files kept in {rec_dir}; no hand-off)", file=sys.stderr)
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="td", description="tutorial-director pipeline runner")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_dry = sub.add_parser("dry", help="Dry-run steps and checks without recording")
    p_dry.add_argument("run", help="Run name under $TD_HOME/runs/<name> or path to run dir")
    p_dry.add_argument("--listen", action="store_true", help="Play step TTS WAVs aloud via pw-play during dry run")
    p_dry.add_argument("--max-step-s", type=float, default=60.0, help="Per-action timeout in seconds (default 60)")

    p_rec = sub.add_parser("record", help="Record screen and execute steps (requires passing dry run)")
    p_rec.add_argument("run", help="Run name under $TD_HOME/runs/<name> or path to run dir")
    p_rec.add_argument("--monitor", default=None, help="Override Hyprland monitor name")
    p_rec.add_argument("--max-step-s", type=float, default=60.0, help="Per-action timeout in seconds (default 60)")

    p_ho = sub.add_parser("handoff", help="Build <run>/handoff/ for editor-v2")
    p_ho.add_argument("run", help="Run name under $TD_HOME/runs/<name> or path to run dir")
    p_ho.add_argument("--model", default=None, help="Override EV2_WHISPER_MODEL for word alignment")
    p_ho.add_argument("--no-whisper", action="store_true", help="Skip faster-whisper and use proportional timing")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "dry":
        return run_dry(args.run, listen=args.listen, max_step_s=args.max_step_s)
    if args.cmd == "record":
        return run_record(args.run, monitor=args.monitor, max_step_s=args.max_step_s)
    if args.cmd == "handoff":
        return td_handoff.main(
            [args.run]
            + (["--model", args.model] if args.model else [])
            + (["--no-whisper"] if args.no_whisper else [])
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
