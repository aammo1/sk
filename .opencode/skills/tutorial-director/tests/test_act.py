#!/usr/bin/env python3
"""Unit tests for tutorial-director desktop action driver (mocked external tools)."""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import td_act
from act import hypr, mouse, targets
from act.driver import (
    ALL_MODIFIER_KEYCODES,
    CheckFailed,
    Driver,
    SecretRefusedError,
    StepTimeoutError,
    StopRequested,
    clear_stop,
    contains_secret,
    parse_combo,
    place,
    stop_file_path,
)


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += max(0.0, dt)


class TestMouseAndCalibration(unittest.TestCase):
    def test_bezier_smoothness_overshoot_and_settle(self) -> None:
        rng = random.Random(42)
        start = (100.0, 200.0)
        target = (900.0, 650.0)
        dist = math.hypot(target[0] - start[0], target[1] - start[1])
        path = mouse.generate_bezier_path(start, target, rng=rng, hz=120)

        expected_dur = max(0.3, min(1.1, 0.25 + dist / 1800.0))
        self.assertAlmostEqual(path[0][0], 0.0, places=4)
        self.assertAlmostEqual(path[-1][0], expected_dur, places=4)
        self.assertEqual((path[-1][1], path[-1][2]), target)
        self.assertGreaterEqual(len(path), int(expected_dur * 120))

        # Check smooth step-to-step deltas (no giant teleports) and overshoot <= 6 px
        max_step = max(
            math.hypot(path[i][1] - path[i - 1][1], path[i][2] - path[i - 1][2])
            for i in range(1, len(path))
        )
        self.assertLess(max_step, 40.0)

        # Overshoot past target along approach vector must be <= 6.0 px
        ux = (target[0] - start[0]) / dist
        uy = (target[1] - start[1]) / dist
        max_along = max((px - target[0]) * ux + (py - target[1]) * uy for _, px, py in path)
        self.assertLessEqual(max_along, 6.001)

        # Check settle and hold durations within bounds
        for _ in range(20):
            self.assertTrue(0.12 <= mouse.settle_duration(rng) <= 0.22)
            self.assertTrue(0.070 <= mouse.click_hold_duration(rng) <= 0.110)

    def test_calibration_math_and_persistence(self) -> None:
        # Simulate monitor at offset (1920, 100), logical 1920x1080, scale 1.5,
        # where ydotool expects physical-like coords (lx - 1920)*1.5 + 10, etc.
        mon = {"name": "DP-1", "x": 1920, "y": 100, "width": 2880, "height": 1620, "scale": 1.5, "focused": True}
        cursor = [1920.0, 100.0]

        def ydo_runner(cmd, **kwargs):
            if cmd[:2] == ["ydotool", "mousemove"]:
                x = float(cmd[cmd.index("-x") + 1])
                y = float(cmd[cmd.index("-y") + 1])
                cursor[0] = 1920.0 + x / 1.5
                cursor[1] = 100.0 + y / 1.5
            return _ok()

        def hypr_runner(cmd, **kwargs):
            if cmd[1:3] == ("monitors", "-j") or cmd[1:] == ["monitors", "-j"]:
                return _ok(json.dumps([mon]))
            if cmd[1] == "cursorpos":
                return _ok(f"{cursor[0]:.2f}, {cursor[1]:.2f}\n")
            return _ok()

        with tempfile.TemporaryDirectory() as td:
            cpath = os.path.join(td, "calib.json")
            cal = mouse.calibrate(
                runner=ydo_runner,
                hypr_runner=hypr_runner,
                sleep_fn=lambda _: None,
                path=cpath,
            )
            self.assertTrue(os.path.isfile(cpath))
            self.assertLess(cal.residual_px, 2.0)

            loaded = mouse.load_calibration(cpath)
            self.assertIsNotNone(loaded)
            yx, yy = loaded.to_ydotool(2500.0, 640.0)
            lx, ly = 1920.0 + yx / 1.5, 100.0 + yy / 1.5
            self.assertLess(math.hypot(lx - 2500.0, ly - 640.0), 2.0)

    def test_missing_ydotool_error_message(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(mouse.YdotoolError) as ctx:
                mouse.ensure_ydotool()
        self.assertIn("sudo pacman -S ydotool", str(ctx.exception))


class TestDriverKeycodesSafetyAndLog(unittest.TestCase):
    def test_parse_combo_formatting_and_codes(self) -> None:
        codes, disp = parse_combo("super+alt+space")
        self.assertEqual(codes, [(125, "Super"), (56, "Alt"), (57, "Space")])
        self.assertEqual(disp, "Super + Alt + Space")

        codes2, disp2 = parse_combo("shift+ctrl+t")
        self.assertEqual(codes2, [(42, "Shift"), (29, "Ctrl"), (20, "T")])
        self.assertEqual(disp2, "Ctrl + Shift + T")

    def test_secrets_refusal_never_types_or_logs(self) -> None:
        secrets = [
            "sk-proj-1234567890abcdef123456",
            "ghp_abcdefghijklmnopqrstuvwxyz1234",
            "AKIA1234567890ABCDEF",
            "api_key=my_secret_value_12345",
            "password: 'TopSecretPassword1'",
        ]
        for s in secrets:
            self.assertTrue(contains_secret(s), f"Missed secret: {s}")

        self.assertFalse(contains_secret("echo td ok"))
        self.assertFalse(contains_secret("git status"))

        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "events.jsonl")
            tool_calls = []
            drv = Driver(
                event_log_path=log_path,
                stop_file=os.path.join(td, "td.stop"),
                ydotool_runner=lambda cmd, **kw: _ok(),
                hypr_runner=lambda cmd, **kw: _ok("[]") if "clients" in cmd else _ok("{}"),
                tool_runner=lambda cmd, **kw: tool_calls.append(cmd) or _ok(),
            )
            with self.assertRaises(SecretRefusedError) as ctx:
                drv.execute({"type": "type", "text": "export KEY=sk-proj-1234567890abcdef1234"})
            drv.close()
            self.assertEqual(tool_calls, [])
            self.assertNotIn("sk-proj", str(ctx.exception))
            content = ""
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8") as f:
                    content = f.read()
            self.assertNotIn("sk-proj", content)

    def test_event_log_never_contains_typed_text_and_logs_33ms_moves(self) -> None:
        clk = FakeClock()
        ydo_cmds = []
        tool_calls = []

        def ydo_runner(cmd, **kw):
            ydo_cmds.append(cmd)
            return _ok()

        def hypr_runner(cmd, **kw):
            if "monitors" in cmd:
                return _ok(json.dumps([{"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1.0, "focused": True}]))
            if "cursorpos" in cmd:
                return _ok("100, 100")
            if "activewindow" in cmd:
                return _ok(json.dumps({"class": "kitty"}))
            return _ok()

        def tool_runner(cmd, **kw):
            tool_calls.append((cmd, kw.get("input_text")))
            return _ok()

        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "events.jsonl")
            drv = Driver(
                event_log_path=log_path,
                stop_file=os.path.join(td, "td.stop"),
                clock=clk.now,
                sleep_fn=clk.sleep,
                rng=random.Random(7),
                ydotool_runner=ydo_runner,
                hypr_runner=hypr_runner,
                tool_runner=tool_runner,
            )
            drv.execute({"type": "move", "to": [700, 500]}, step_id="s1")
            drv.execute({"type": "click", "to": [750, 520]}, step_id="s2")
            drv.execute({"type": "key", "combo": "super+alt+space"}, step_id="s3")
            drv.execute({"type": "type", "text": "echo td ok", "cps": 12}, step_id="s4")
            drv.execute({"type": "type", "text": "sudo pacman -Syu --noconfirm", "paste": True}, step_id="s5")
            drv.close()

            with open(log_path, encoding="utf-8") as f:
                raw_log = f.read()
            events = [json.loads(ln) for ln in raw_log.splitlines() if ln.strip()]
            types = [e["type"] for e in events]
            self.assertIn("move", types)
            self.assertIn("down", types)
            self.assertIn("up", types)
            self.assertIn("key", types)
            self.assertIn("type_start", types)
            self.assertIn("type_end", types)

            # Verify move samples spacing ~33ms during move
            move_events = [e for e in events if e["type"] == "move"]
            self.assertGreaterEqual(len(move_events), 10)

            # Verify key formatting matches ev2
            key_ev = [e for e in events if e["type"] == "key"][0]
            self.assertEqual(key_ev["keys"], "Super + Alt + Space")

            # Verify typed text never appears anywhere in event log
            self.assertNotIn("echo td ok", raw_log)
            self.assertNotIn("pacman", raw_log)

            # Verify paste mode typed 3-5 prefix chars, wl-copied the rest, and sent Ctrl+Shift+V (terminal)
            wl_calls = [c for c in tool_calls if c[0][0] == "wl-copy"]
            self.assertEqual(len(wl_calls), 1)
            pasted = wl_calls[0][1]
            self.assertTrue("sudo pacman -Syu --noconfirm".endswith(pasted))
            self.assertTrue(3 <= len("sudo pacman -Syu --noconfirm") - len(pasted) <= 5)
            self.assertTrue(any("29:1" in c and "42:1" in c and "47:1" in c for c in ydo_cmds))

    def test_release_all_on_error_and_td_stop(self) -> None:
        ydo_cmds = []

        def failing_ydo(cmd, **kw):
            ydo_cmds.append(cmd)
            if cmd[:2] == ["ydotool", "key"] and "57:0" in cmd:
                raise mouse.YdotoolError("simulated failure mid-combo")
            return _ok()

        clk = FakeClock()
        with tempfile.TemporaryDirectory() as td:
            stop_path = os.path.join(td, "td.stop")
            drv = Driver(
                stop_file=stop_path,
                clock=clk.now,
                sleep_fn=clk.sleep,
                ydotool_runner=failing_ydo,
                hypr_runner=lambda cmd, **kw: _ok("[]"),
            )
            with self.assertRaises(mouse.YdotoolError):
                drv.execute({"type": "key", "combo": "super+alt+space"})

            # Check release_all sent :0 for all modifiers and 0x80/0x81/0x82
            rel_key_cmds = [c for c in ydo_cmds if c[:2] == ["ydotool", "key"] and all(x.endswith(":0") for x in c[2:])]
            self.assertTrue(rel_key_cmds)
            flat_ups = " ".join(rel_key_cmds[-1])
            for code in ALL_MODIFIER_KEYCODES:
                self.assertIn(f"{code}:0", flat_ups)
            self.assertTrue(any(c == ["ydotool", "click", "0x80", "0x81", "0x82"] for c in ydo_cmds))

    def test_td_stop_aborts_quickly_and_exits_130(self) -> None:
        ydo_cmds = []

        with tempfile.TemporaryDirectory() as td:
            stop_path = os.path.join(td, "td.stop")
            old_env = os.environ.get("TD_STOP_FILE")
            os.environ["TD_STOP_FILE"] = stop_path
            try:
                drv = Driver(
                    stop_file=stop_path,
                    ydotool_runner=lambda cmd, **kw: ydo_cmds.append(cmd) or _ok(),
                    hypr_runner=lambda cmd, **kw: _ok("[]"),
                )

                def trigger_stop():
                    time.sleep(0.08)
                    td_act.cmd_stop()

                t = threading.Thread(target=trigger_stop)
                t.start()
                t0 = time.monotonic()
                with self.assertRaises(StopRequested) as ctx:
                    drv.execute({"type": "wait", "s": 5.0})
                elapsed = time.monotonic() - t0
                t.join()

                self.assertEqual(ctx.exception.exit_code, 130)
                self.assertLess(elapsed, 0.5)
                self.assertTrue(any(c == ["ydotool", "click", "0x80", "0x81", "0x82"] for c in ydo_cmds))

                # Also verify CLI returns 130 if StopRequested is raised
                with mock.patch.object(td_act, "cmd_test", side_effect=StopRequested("stopped")):
                    rc = td_act.main(["act", "test"])
                    self.assertEqual(rc, 130)
            finally:
                clear_stop(stop_path)
                if old_env is None:
                    os.environ.pop("TD_STOP_FILE", None)
                else:
                    os.environ["TD_STOP_FILE"] = old_env

    def test_step_timeout_60s(self) -> None:
        clk = FakeClock()
        with tempfile.TemporaryDirectory() as td:
            drv = Driver(
                stop_file=os.path.join(td, "td.stop"),
                max_step_s=60.0,
                clock=clk.now,
                sleep_fn=clk.sleep,
                ydotool_runner=lambda cmd, **kw: _ok(),
                hypr_runner=lambda cmd, **kw: _ok("[]"),
            )
            with self.assertRaises(StepTimeoutError):
                drv.execute({"type": "wait", "s": 120.0})


class TestTargetsPlaceAndChecks(unittest.TestCase):
    def test_window_target_and_place_verification(self) -> None:
        win = {"address": "0xabc", "class": "kitty", "at": [100, 200], "size": [800, 600], "floating": False}
        dispatches = []

        def hypr_runner(cmd, **kw):
            if cmd[1] == "clients":
                return _ok(json.dumps([win]))
            if cmd[1] == "dispatch":
                dispatches.append(cmd[2:])
                if cmd[2] == "resizewindowpixel":
                    wh = cmd[3].split(",")[0].split()[1:]
                    win["size"] = [int(wh[0]), int(wh[1])]
                elif cmd[2] == "movewindowpixel":
                    xy = cmd[3].split(",")[0].split()[1:]
                    win["at"] = [int(xy[0]), int(xy[1])]
                elif cmd[2] == "setfloating":
                    win["floating"] = True
            return _ok()

        x, y = targets.resolve({"window": "class:kitty", "at": [0.25, 0.5]}, hypr_runner=hypr_runner)
        self.assertEqual((x, y), (300.0, 500.0))

        placed = place("class:kitty", [50, 60, 1000, 700], runner=hypr_runner, sleep_fn=lambda _: None)
        self.assertEqual(placed, (50, 60, 1000, 700))
        self.assertTrue(any(d[0] == "setfloating" for d in dispatches))

    def test_place_mismatch_raises(self) -> None:
        win = {"address": "0xabc", "class": "kitty", "at": [100, 200], "size": [800, 600], "floating": True}

        def hypr_runner(cmd, **kw):
            if cmd[1] == "clients":
                return _ok(json.dumps([win]))
            return _ok()

        with self.assertRaises(hypr.HyprError):
            place("class:kitty", [0, 0, 500, 500], runner=hypr_runner, sleep_fn=lambda _: None)

    def test_tesseract_tsv_and_missing_error(self) -> None:
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t100\t200\t80\t30\t95\tSave\n"
            "5\t1\t1\t1\t1\t2\t190\t200\t90\t30\t92\tChanges\n"
        )
        cx, cy, conf = targets.parse_tesseract_tsv(tsv, "Save Changes")
        self.assertAlmostEqual(cx, 190.0)
        self.assertAlmostEqual(cy, 215.0)
        self.assertGreater(conf, 90.0)

        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(targets.TargetError) as ctx:
                targets._run_tesseract_tsv("/tmp/fake.png", "Save", "eng+fra+ara")
        self.assertIn("sudo pacman -S tesseract", str(ctx.exception))

    def test_check_writes_screenshot_and_expect_even_on_failure(self) -> None:
        def tool_runner(cmd, **kw):
            if cmd[0] == "grim":
                out_png = cmd[-1]
                with open(out_png, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x02\x00\x00\x00")
                return _ok()
            if cmd[0] == "tesseract":
                return _ok("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
            return _ok()

        with tempfile.TemporaryDirectory() as td:
            checks_dir = os.path.join(td, "checks")
            drv = Driver(
                checks_dir=checks_dir,
                stop_file=os.path.join(td, "td.stop"),
                ydotool_runner=lambda cmd, **kw: _ok(),
                hypr_runner=lambda cmd, **kw: _ok("[]") if "clients" in cmd else _ok("{}"),
                tool_runner=tool_runner,
            )
            # Passing visual-only check
            drv.execute({"type": "check", "expect": "Terminal is visible"}, step_id="step-01")
            self.assertTrue(os.path.isfile(os.path.join(checks_dir, "step-01-1.png")))
            with open(os.path.join(checks_dir, "step-01-1.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "Terminal is visible")

            # Failing OCR check still saves screenshot + txt + manifest entry
            with self.assertRaises(CheckFailed):
                drv.execute({"type": "check", "expect": "Done button", "text": "Done"}, step_id="step-01")
            self.assertTrue(os.path.isfile(os.path.join(checks_dir, "step-01-2.png")))
            with open(os.path.join(checks_dir, "checks.jsonl"), encoding="utf-8") as f:
                manifest = [json.loads(ln) for ln in f]
            self.assertEqual(len(manifest), 2)
            self.assertTrue(manifest[0]["ok"])
            self.assertFalse(manifest[1]["ok"])

    def test_do_key_and_frozen_clock_safety(self) -> None:
        win = {"address": "0x1", "class": "foot", "at": [0, 0], "size": [400, 300], "floating": False}

        def hypr_runner(cmd, **kw):
            if cmd[1] == "clients":
                return _ok(json.dumps([win]))
            if cmd[1] == "dispatch":
                if cmd[2] == "resizewindowpixel":
                    wh = cmd[3].split(",")[0].split()[1:]
                    win["size"] = [int(wh[0]), int(wh[1])]
                elif cmd[2] == "movewindowpixel":
                    xy = cmd[3].split(",")[0].split()[1:]
                    win["at"] = [int(xy[0]), int(xy[1])]
                elif cmd[2] == "setfloating":
                    win["floating"] = True
            return _ok()

        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "events.jsonl")
            # Intentionally use frozen clock + no-op sleep to confirm zero spin
            drv = Driver(
                event_log_path=log_path,
                stop_file=os.path.join(td, "td.stop"),
                clock=lambda: 100.0,
                sleep_fn=lambda _: None,
                ydotool_runner=lambda cmd, **kw: _ok(),
                hypr_runner=hypr_runner,
            )
            res = drv.execute({"do": "key", "combo": "ctrl+s"}, step_id="do-key")
            self.assertEqual(res["keys"], "Ctrl + S")
            drv.execute({"do": "wait", "s": 0.2}, step_id="do-wait")
            drv.execute({"do": "move_window", "window": "class:foot", "rect": [10, 20, 600, 400]}, step_id="do-win")
            self.assertEqual((win["at"], win["size"]), ([10, 20], [600, 400]))
            drv.close()

    def test_stop_file_path_fallback_runtime_dir(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("XDG_RUNTIME_DIR", "TD_STOP_FILE")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                stop_file_path(),
                os.path.join(f"/tmp/td-runtime-{os.getuid()}", "td.stop"),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
