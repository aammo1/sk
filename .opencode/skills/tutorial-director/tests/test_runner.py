#!/usr/bin/env python3
"""Unit and integration tests for td_run.py, td_handoff.py, and words_align.py."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import td_handoff  # noqa: E402
import td_run  # noqa: E402
import td_script  # noqa: E402
import words_align  # noqa: E402
from act.driver import CheckFailed, Driver, StopRequested  # noqa: E402
from act.mouse import Calibration  # noqa: E402
from tts.base import probe_wav  # noqa: E402


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += max(0.0, float(dt))


class FakeStage:
    events: list[str] = []

    def __init__(self, script=None, **kwargs) -> None:
        self.script = script

    def __enter__(self):
        FakeStage.events.append("prepare")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        FakeStage.events.append("restore")


def _make_tone_wav(path: Path, dur_s: float, freq_hz: float = 440.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-t",
            f"{dur_s:.3f}",
            "-i",
            f"sine=frequency={freq_hz}:sample_rate=48000",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(path),
        ],
        check=True,
    )


def _make_test_mp4(path: Path, dur_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-t",
            f"{dur_s:.3f}",
            "-i",
            "color=c=#11111b:s=1920x1080:r=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-an",
            str(path),
        ],
        check=True,
    )


def _rms_window(wav_path: Path, start_s: float, dur_s: float) -> float:
    """Measure peak normalized amplitude in [start_s, start_s + dur_s] of a 24-bit stereo WAV."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{start_s:.3f}",
            "-t",
            f"{dur_s:.3f}",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    if not raw:
        return 0.0
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    return max(abs(s) for s in samples) / 32768.0


def _example_script() -> dict:
    return {
        "title": "Omarchy menu f 3 dqayq",
        "promise": "Learn the *Omarchy menu* in 3 minutes",
        "lang": "darija",
        "voice": {"engine": "golha", "ref": None, "speed": 1.0},
        "screen": {"monitor": "auto", "workspace": 9},
        "studio": {"font_px": 18, "browser_zoom": 1.25, "wallpaper": "plain", "hide_bar": True, "cursor_px": 32},
        "pace": {"cps": 10, "settle_after": 1.0, "pre_click": 0.25},
        "layout": {"terminal": [160, 90, 1600, 900], "browser": [0, 0, 1920, 1080]},
        "setup": [{"do": "shell", "cmd": "true"}],
        "steps": [
            {
                "id": "s01",
                "chapter": "Intro — المقدمة",
                "say": "سلام، اليوم غادي نشوفو Omarchy menu.",
                "layout": {"window": "class:Alacritty", "slot": "terminal"},
                "actions": [
                    {"do": "click", "to": [320, 240]},
                    {"do": "check", "expect": "terminal visible"},
                ],
            },
            {
                "id": "s02",
                "chapter": "Menu — اللائحة",
                "say": "ضغط على Super و Alt و Space باش تحل المينيو.",
                "actions": [
                    {"do": "key", "combo": "super+alt+space"},
                    {"do": "click", "to": [960, 540]},
                    {"do": "check", "expect": "menu is open"},
                ],
                "callout": {"text": "Omarchy menu", "at_action": 1, "dur": 3},
                "insert": {
                    "recipe": "steps",
                    "dur": 12,
                    "data": {
                        "title": "Omarchy Menu",
                        "steps": [{"label": "Open menu"}, {"label": "Search theme"}],
                    },
                },
            },
            {
                "id": "s03",
                "say": "اكتب theme وضغط Enter باش تبدل الستايل.",
                "actions": [
                    {"do": "click", "to": [800, 420]},
                    {"do": "type", "text": "theme", "cps": 10},
                    {"do": "key", "combo": "Return"},
                ],
                "pause_after": 0.6,
            },
        ],
        "cleanup": [{"do": "key", "combo": "Escape"}],
    }


def _make_fake_run(root: Path, script: dict, durs: dict[str, float]) -> Path:
    run_dir = root / "runs" / "demo"
    for sub in ("voice", "dry", "rec", "handoff"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")

    index = []
    for step in script["steps"]:
        sid = step["id"]
        wav_path = run_dir / "voice" / f"{sid}.wav"
        _make_tone_wav(wav_path, durs[sid], freq_hz=440.0)
        index.append({"id": sid, "file": f"voice/{sid}.wav", "dur": durs[sid], "text_sha": "test"})
    (run_dir / "voice" / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return run_dir


def _make_mock_driver_factory(
    clock: FakeClock,
    *,
    stop_file: str,
    fail_check_step: str | None = None,
    stop_at_step: str | None = None,
):
    win = {"address": "0x1", "class": "Alacritty", "at": [160, 90], "size": [1600, 900], "floating": True, "mapped": True}
    mon = {"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1.0, "focused": True}

    def hypr_runner(cmd, **kwargs):
        if cmd[1] == "monitors":
            return _ok(json.dumps([mon]))
        if cmd[1] == "clients":
            return _ok(json.dumps([win]))
        if cmd[1] == "activewindow":
            return _ok(json.dumps(win))
        if cmd[1] == "cursorpos":
            return _ok("960, 540\n")
        return _ok()

    def ydo_runner(cmd, **kwargs):
        return _ok()

    def tool_runner(cmd, **kwargs):
        if cmd[0] == "grim":
            out = cmd[-1]
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            # Minimal valid 1x1 PNG bytes
            Path(out).write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
                b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            return _ok()
        return _ok()

    def factory(**kwargs):
        kwargs["clock"] = clock.now
        kwargs["sleep_fn"] = clock.sleep
        kwargs["monitor"] = mon
        kwargs["calib"] = Calibration()
        kwargs["stop_file"] = stop_file
        kwargs["ydotool_runner"] = ydo_runner
        kwargs["hypr_runner"] = hypr_runner
        kwargs["tool_runner"] = tool_runner
        drv = Driver(**kwargs)
        orig_exec = drv.execute

        def wrapped_exec(action, *, step_id="step"):
            if stop_at_step and step_id == stop_at_step:
                Path(drv.stop_file).parent.mkdir(parents=True, exist_ok=True)
                Path(drv.stop_file).write_text("stop\n", encoding="utf-8")
            if fail_check_step and step_id == fail_check_step and (action.get("do") == "check" or action.get("type") == "check"):
                raise CheckFailed(f"Simulated check failure at {step_id}")
            return orig_exec(action, step_id=step_id)

        drv.execute = wrapped_exec  # type: ignore[method-assign]
        return drv

    return factory


class TestWordsAlign(unittest.TestCase):
    def test_difflib_alignment_preserves_script_and_monotonic(self) -> None:
        say = "ضغط على Super و Alt و Space باش تحل Omarchy menu."
        asr = [
            ("ضغط", 0.10, 0.35),
            ("على", 0.38, 0.55),
            ("سوبر", 0.60, 0.90),  # Whisper transliterated Super
            ("و", 0.92, 1.00),
            ("Alt", 1.02, 1.25),
            ("و", 1.27, 1.35),
            ("Space", 1.37, 1.70),
            ("باش", 1.72, 1.95),
            ("تحل", 1.98, 2.25),
            ("اومارشي", 2.28, 2.75),  # matched via _AR_TO_LATIN_HINTS
            ("مينيو", 2.78, 3.10),
        ]
        words, method = words_align.align_step_words(say, asr, voice_start=5.0, voice_end=8.5)
        self.assertEqual(method, "difflib")
        final = words_align.enforce_monotonic(words)
        self.assertEqual(" ".join(w["w"] for w in final), " ".join(say.split()))
        for i, w in enumerate(final):
            self.assertGreaterEqual(w["s"], 5.0)
            self.assertGreaterEqual(w["e"], w["s"])
            if i > 0:
                self.assertGreaterEqual(w["s"], final[i - 1]["e"])

    def test_proportional_fallback_when_whisper_missing(self) -> None:
        say = "سلام، اليوم غادي نشوفو Omarchy menu."
        words, method = words_align.align_step_words(say, None, voice_start=1.2, voice_end=3.7)
        self.assertEqual(method, "proportional")
        final = words_align.enforce_monotonic(words)
        self.assertEqual(" ".join(w["w"] for w in final), " ".join(say.split()))
        self.assertAlmostEqual(final[0]["s"], 1.2, places=3)
        self.assertAlmostEqual(final[-1]["e"], 3.7, places=3)
        for i in range(1, len(final)):
            self.assertGreaterEqual(final[i]["s"], final[i - 1]["e"])


class TestRunnerDryRecordHandoff(unittest.TestCase):
    def test_launch_wrapping_studio_settings(self) -> None:
        script = {"studio": {"font_px": 20, "browser_zoom": 1.5}}
        act_term = td_run._wrap_launch_action({"do": "launch", "cmd": "alacritty -e htop"}, script)
        self.assertIn("font.size=20", act_term["cmd"])
        act_br = td_run._wrap_launch_action({"do": "launch", "cmd": "chromium https://example.com"}, script)
        self.assertIn("--force-device-scale-factor=1.5", act_br["cmd"])

    def test_dry_run_example_script_writes_report_and_screenshots(self) -> None:
        FakeStage.events = []
        clock = FakeClock(500.0)
        script = _example_script()
        durs = {"s01": 2.0, "s02": 3.0, "s03": 2.5}

        with tempfile.TemporaryDirectory() as td:
            stop_file = os.path.join(td, "td.stop")
            run_dir = _make_fake_run(Path(td), script, durs)
            with mock.patch.dict(os.environ, {"TD_STOP_FILE": stop_file}):
                rc = td_run.run_dry(
                    str(run_dir),
                    clock=clock.now,
                    sleep_fn=clock.sleep,
                    driver_factory=_make_mock_driver_factory(clock, stop_file=stop_file),
                    stage_factory=FakeStage,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(FakeStage.events, ["prepare", "restore"])

            status = json.loads((run_dir / "dry" / "status.json").read_text(encoding="utf-8"))
            self.assertTrue(status["ok"])
            self.assertEqual(status["script_sha"], td_script.script_sha(str(run_dir)))
            self.assertEqual(len(status["screenshots"]), 2)

            report = (run_dir / "dry" / "report.md").read_text(encoding="utf-8")
            self.assertIn("PASS", report)
            self.assertIn("s01-1.png", report)
            self.assertIn("s02-1.png", report)

    def test_dry_run_failure_stops_at_first_failure_and_restores(self) -> None:
        FakeStage.events = []
        clock = FakeClock(500.0)
        script = _example_script()
        durs = {"s01": 1.5, "s02": 2.0, "s03": 1.5}

        with tempfile.TemporaryDirectory() as td:
            stop_file = os.path.join(td, "td.stop")
            run_dir = _make_fake_run(Path(td), script, durs)
            with mock.patch.dict(os.environ, {"TD_STOP_FILE": stop_file}):
                rc = td_run.run_dry(
                    str(run_dir),
                    clock=clock.now,
                    sleep_fn=clock.sleep,
                    driver_factory=_make_mock_driver_factory(clock, stop_file=stop_file, fail_check_step="s02"),
                    stage_factory=FakeStage,
                )
            self.assertEqual(rc, 1)
            self.assertEqual(FakeStage.events, ["prepare", "restore"])
            status = json.loads((run_dir / "dry" / "status.json").read_text(encoding="utf-8"))
            self.assertFalse(status["ok"])
            self.assertEqual(status["failed_step"], "s02")
            steps_data = json.loads((run_dir / "dry" / "steps.json").read_text(encoding="utf-8"))
            self.assertEqual([s["id"] for s in steps_data["steps"]], ["s01", "s02"])

    def test_record_refuses_without_matching_passing_dry_run(self) -> None:
        clock = FakeClock(500.0)
        script = _example_script()
        durs = {"s01": 1.0, "s02": 1.0, "s03": 1.0}

        with tempfile.TemporaryDirectory() as td:
            run_dir = _make_fake_run(Path(td), script, durs)
            # 1. Missing dry run
            self.assertEqual(td_run.run_record(str(run_dir)), 1)

            # 2. Failed dry run
            (run_dir / "dry" / "status.json").write_text(
                json.dumps({"ok": False, "script_sha": td_script.script_sha(str(run_dir))}),
                encoding="utf-8",
            )
            self.assertEqual(td_run.run_record(str(run_dir)), 1)

            # 3. Stale script_sha
            (run_dir / "dry" / "status.json").write_text(
                json.dumps({"ok": True, "script_sha": "deadbeef"}),
                encoding="utf-8",
            )
            self.assertEqual(td_run.run_record(str(run_dir)), 1)

    def test_full_record_and_handoff_alignment_and_words(self) -> None:
        clock = FakeClock(1000.0)
        script = _example_script()
        durs = {"s01": 1.8, "s02": 2.4, "s03": 2.0}

        class FakeRecorder:
            def __init__(self, out_dir, **kwargs) -> None:
                self.out_dir = Path(out_dir)
                self.raw_path = self.out_dir / "raw.mp4"
                self.screen_path = self.out_dir / "screen.mp4"
                self.start_json_path = self.out_dir / "start.json"
                self._running = False
                self._start_t = 0.0

            def is_running(self) -> bool:
                return self._running

            def start(self) -> dict:
                self._running = True
                self._start_t = clock.now()
                meta = {
                    "wall_time": 1700000000.0,
                    "monotonic_time": self._start_t,
                    "monitor": "DP-1",
                    "monitor_width": 1920,
                    "monitor_height": 1080,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                }
                self.start_json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                return meta

            def stop(self, normalize: bool = True, keep_raw: bool = True) -> Path:
                self._running = False
                total_dur = max(2.0, clock.now() - self._start_t)
                _make_test_mp4(self.screen_path, total_dur)
                return self.screen_path

        with tempfile.TemporaryDirectory() as td:
            stop_file = os.path.join(td, "td.stop")
            run_dir = _make_fake_run(Path(td), script, durs)
            mon_1080p = {"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1.0, "focused": True}

            with (
                mock.patch.dict(os.environ, {"TD_STOP_FILE": stop_file}),
                mock.patch.object(td_run, "_resolve_monitor", return_value=mon_1080p),
            ):
                # Passing dry run first
                rc_dry = td_run.run_dry(
                    str(run_dir),
                    clock=clock.now,
                    sleep_fn=clock.sleep,
                    driver_factory=_make_mock_driver_factory(clock, stop_file=stop_file),
                    stage_factory=FakeStage,
                )
                self.assertEqual(rc_dry, 0)

                # Real record (mocked recorder + driver, real clock progression)
                rc_rec = td_run.run_record(
                    str(run_dir),
                    clock=clock.now,
                    sleep_fn=clock.sleep,
                    driver_factory=_make_mock_driver_factory(clock, stop_file=stop_file),
                    stage_factory=FakeStage,
                    recorder_factory=FakeRecorder,
                )
            self.assertEqual(rc_rec, 0)
            self.assertTrue((run_dir / "rec" / "screen.mp4").is_file())

            # Run handoff with real ffmpeg mixing + mocked Whisper alignment
            def fake_whisper(items):
                # Return ASR tokens for s02 to exercise difflib alignment, empty for s01/s03 to exercise fallback
                return (
                    {
                        "s02": [
                            ("ضغط", 0.10, 0.30),
                            ("على", 0.32, 0.50),
                            ("Super", 0.52, 0.78),
                            ("و", 0.80, 0.90),
                            ("Alt", 0.92, 1.15),
                            ("و", 1.17, 1.25),
                            ("Space", 1.27, 1.55),
                            ("باش", 1.57, 1.78),
                            ("تحل", 1.80, 2.05),
                            ("المينيو", 2.08, 2.35),
                        ]
                    },
                    None,
                )

            handoff_dir = td_handoff.run_handoff(str(run_dir), use_whisper=True, transcribe_fn=fake_whisper)
            self.assertEqual(handoff_dir, run_dir / "handoff")

            # Check all 6 files exist
            for fname in ("screen.mp4", "vo.wav", "inputs.json", "words.json", "plan.json", "director.json"):
                self.assertTrue((handoff_dir / fname).is_file(), f"missing {fname}")

            # Verify vo.wav format & voice placement at real step start times
            vo_info = probe_wav(str(handoff_dir / "vo.wav"))
            self.assertEqual(vo_info["codec_name"], "pcm_s24le")
            self.assertEqual(vo_info["sample_rate"], 48000)
            self.assertEqual(vo_info["channels"], 2)
            self.assertEqual(vo_info["bits_per_sample"], 24)

            director = json.loads((handoff_dir / "director.json").read_text(encoding="utf-8"))
            self.assertEqual(director["engine"], "golha")
            self.assertEqual(director["words_source"], "script")
            self.assertEqual(len(director["steps"]), 3)
            # Check silence before first step (1.0 s still) and audio present during each step's voice window
            self.assertLess(_rms_window(handoff_dir / "vo.wav", 0.05, 0.8), 0.01)
            for st in director["steps"]:
                self.assertGreater(_rms_window(handoff_dir / "vo.wav", st["voice_start"] + 0.1, 0.5), 0.05)

            # Verify inputs.json exact format + spot-check all 3 clicks within 1 frame (1/30s = 0.0333s)
            inputs = json.loads((handoff_dir / "inputs.json").read_text(encoding="utf-8"))
            self.assertEqual(inputs["source"], "tutorial-director")
            self.assertEqual(inputs["aligned"], "exact")
            self.assertFalse(inputs["clicks_inferred"])
            self.assertEqual(len(inputs["clicks"]), 3)
            self.assertEqual((inputs["clicks"][0]["x"], inputs["clicks"][0]["y"]), (320.0, 240.0))
            self.assertEqual((inputs["clicks"][1]["x"], inputs["clicks"][1]["y"]), (960.0, 540.0))
            self.assertEqual((inputs["clicks"][2]["x"], inputs["clicks"][2]["y"]), (800.0, 420.0))

            # Compare clicks against raw events.jsonl timestamps
            rec_start = json.loads((run_dir / "rec" / "start.json").read_text(encoding="utf-8"))["monotonic_time"]
            raw_downs = [
                json.loads(ln)
                for ln in (run_dir / "rec" / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if ln.strip() and json.loads(ln).get("type") == "down"
            ]
            for click, ev in zip(inputs["clicks"], raw_downs):
                self.assertLess(abs(click["t"] - (ev["t"] - rec_start)), 1.0 / 30.0)
            self.assertEqual(len(inputs["typing"]), 1)
            self.assertGreaterEqual(len(inputs["keys"]), 2)
            self.assertGreater(len(inputs["cursor"]), 5)

            # Verify words.json equals script text verbatim and times are monotonic
            words = json.loads((handoff_dir / "words.json").read_text(encoding="utf-8"))
            expected_text = " ".join(" ".join(st["say"].split()) for st in script["steps"])
            self.assertEqual(" ".join(w["w"] for w in words), expected_text)
            for idx, w in enumerate(words):
                self.assertGreaterEqual(w["s"], 0.0)
                self.assertGreaterEqual(w["e"], w["s"])
                if idx > 0:
                    self.assertGreaterEqual(w["s"], words[idx - 1]["e"])

            # Verify plan.json ("show, then explain" insert placement + callout target + keys)
            plan = json.loads((handoff_dir / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(len(plan["chapters"]), 2)
            self.assertEqual(len(plan["inserts"]), 1)
            ins = plan["inserts"][0]
            self.assertEqual(ins["name"], "s02-steps")
            s02_voice_start = director["steps"][1]["voice_start"]
            self.assertGreater(ins["src_t"], s02_voice_start + 1.0)  # strictly after action + settle, not voice start

            self.assertEqual(len(plan["callouts"]), 1)
            co = plan["callouts"][0]
            self.assertEqual((co["x"], co["y"]), (960.0, 540.0))
            self.assertLess(abs(co["src_t"] - inputs["clicks"][1]["t"]), 0.25)

    def test_handoff_refuses_failed_recording_and_overlapping_inserts(self) -> None:
        clock = FakeClock(1000.0)
        script = _example_script()
        script["steps"][0]["insert"] = {"recipe": "statement", "dur": 12, "data": {"text": "First"}}
        durs = {"s01": 1.0, "s02": 1.0, "s03": 1.0}

        with tempfile.TemporaryDirectory() as td:
            run_dir = _make_fake_run(Path(td), script, durs)
            # Failed recording -> handoff refuses
            (run_dir / "dry" / "status.json").write_text(
                json.dumps({"ok": True, "script_sha": td_script.script_sha(str(run_dir))}),
                encoding="utf-8",
            )
            _make_test_mp4(run_dir / "rec" / "screen.mp4", 3.0)
            (run_dir / "rec" / "start.json").write_text(json.dumps({"monotonic_time": 1000.0}), encoding="utf-8")
            (run_dir / "rec" / "steps.json").write_text(
                json.dumps({"ok": False, "failed_step": "s02", "steps": []}),
                encoding="utf-8",
            )
            with self.assertRaises(td_handoff.HandoffError):
                td_handoff.run_handoff(str(run_dir), use_whisper=False)

            # Overlapping inserts -> handoff catches and refuses
            steps_ok = {
                "ok": True,
                "rec_start_monotonic": 1000.0,
                "steps": [
                    {
                        "id": "s01",
                        "start": 1001.0,
                        "end": 1003.0,
                        "voice_start": 1001.0,
                        "voice_end": 1002.0,
                        "ok": True,
                        "last_screen_action_end": 1001.5,
                        "actions": [{"index": 0, "do": "click", "start": 1001.2, "end": 1001.5, "x": 100, "y": 100}],
                    },
                    {
                        "id": "s02",
                        "start": 1003.0,
                        "end": 1005.0,
                        "voice_start": 1003.0,
                        "voice_end": 1004.0,
                        "ok": True,
                        "last_screen_action_end": 1003.5,
                        "actions": [
                            {"index": 0, "do": "key", "start": 1003.2, "end": 1003.3},
                            {"index": 1, "do": "click", "start": 1003.4, "end": 1003.5, "x": 200, "y": 200},
                        ],
                    },
                    {
                        "id": "s03",
                        "start": 1005.0,
                        "end": 1007.0,
                        "voice_start": 1005.0,
                        "voice_end": 1006.0,
                        "ok": True,
                        "last_screen_action_end": 1005.5,
                        "actions": [],
                    },
                ],
            }
            (run_dir / "rec" / "steps.json").write_text(json.dumps(steps_ok), encoding="utf-8")
            (run_dir / "rec" / "events.jsonl").write_text("", encoding="utf-8")
            _make_test_mp4(run_dir / "rec" / "screen.mp4", 20.0)
            with self.assertRaises(td_handoff.HandoffError) as ctx:
                td_handoff.run_handoff(str(run_dir), use_whisper=False)
            self.assertIn("overlap", str(ctx.exception))

    def test_handoff_debounces_overlapping_key_pills_while_preserving_input_keys(self) -> None:
        script = _example_script()
        durs = {"s01": 1.0, "s02": 1.0, "s03": 1.0}

        with tempfile.TemporaryDirectory() as td:
            run_dir = _make_fake_run(Path(td), script, durs)
            _make_test_mp4(run_dir / "rec" / "screen.mp4", 10.0)
            (run_dir / "rec" / "start.json").write_text(
                json.dumps({"monotonic_time": 1000.0, "monitor_width": 1920, "monitor_height": 1080}),
                encoding="utf-8",
            )
            steps_ok = {
                "ok": True,
                "rec_start_monotonic": 1000.0,
                "steps": [
                    {
                        "id": "s01",
                        "start": 1001.0,
                        "end": 1002.5,
                        "voice_start": 1001.0,
                        "voice_end": 1002.0,
                        "ok": True,
                        "last_screen_action_end": 1001.5,
                        "actions": [{"index": 0, "do": "click", "start": 1001.1, "end": 1001.4, "x": 320, "y": 240}],
                    },
                    {
                        "id": "s02",
                        "start": 1002.5,
                        "end": 1005.0,
                        "voice_start": 1002.5,
                        "voice_end": 1003.5,
                        "ok": True,
                        "last_screen_action_end": 1004.0,
                        "actions": [
                            {"index": 0, "do": "key", "start": 1002.6, "end": 1002.7},
                            {"index": 1, "do": "click", "start": 1003.8, "end": 1004.0, "x": 960, "y": 540},
                        ],
                    },
                    {
                        "id": "s03",
                        "start": 1005.0,
                        "end": 1007.0,
                        "voice_start": 1005.0,
                        "voice_end": 1006.0,
                        "ok": True,
                        "last_screen_action_end": 1006.5,
                        "actions": [],
                    },
                ],
            }
            (run_dir / "rec" / "steps.json").write_text(json.dumps(steps_ok), encoding="utf-8")

            raw_events = [
                {"t": 1001.0, "type": "key", "keys": "Super + Alt + Space"},
                {"t": 1001.8, "type": "key", "keys": "Ctrl + K"},
                {"t": 1002.9, "type": "key", "keys": "Return"},
                {"t": 1003.6, "type": "key", "keys": "Ctrl + S"},
                {"t": 1004.4, "type": "key", "keys": "Escape"},
            ]
            (run_dir / "rec" / "events.jsonl").write_text(
                "\n".join(json.dumps(ev) for ev in raw_events) + "\n",
                encoding="utf-8",
            )

            handoff_dir = td_handoff.run_handoff(str(run_dir), use_whisper=False)
            inputs = json.loads((handoff_dir / "inputs.json").read_text(encoding="utf-8"))
            plan = json.loads((handoff_dir / "plan.json").read_text(encoding="utf-8"))

            self.assertEqual(len(inputs["keys"]), 5)
            self.assertEqual(
                [k["combo"] for k in inputs["keys"]],
                [["Super", "Alt", "Space"], ["Ctrl", "K"], ["Return"], ["Ctrl", "S"], ["Escape"]],
            )

            self.assertEqual(len(plan["keys"]), 2)
            self.assertEqual(plan["keys"][0], {"src_t": 1.0, "keys": "Super + Alt + Space", "dur": 2.5})
            self.assertEqual(plan["keys"][1], {"src_t": 3.6, "keys": "Ctrl + S", "dur": 2.5})
            for prev, nxt in zip(plan["keys"], plan["keys"][1:]):
                self.assertGreaterEqual(nxt["src_t"], prev["src_t"] + prev["dur"])

    def test_record_stop_requested_exits_130_stops_recorder_and_restores_stage(self) -> None:
        FakeStage.events = []
        clock = FakeClock(1000.0)
        script = _example_script()
        durs = {"s01": 1.0, "s02": 1.0, "s03": 1.0}
        rec_events: list[str] = []

        class FakeRec:
            def __init__(self, out_dir, **kwargs) -> None:
                self.out_dir = Path(out_dir)
                self.raw_path = self.out_dir / "raw.mp4"
                self.screen_path = self.out_dir / "screen.mp4"
                self.start_json_path = self.out_dir / "start.json"
                self._running = False

            def is_running(self) -> bool:
                return self._running

            def start(self) -> dict:
                rec_events.append("start")
                self._running = True
                meta = {"wall_time": 1700000000.0, "monotonic_time": clock.now()}
                self.start_json_path.write_text(json.dumps(meta), encoding="utf-8")
                return meta

            def stop(self, normalize: bool = True, keep_raw: bool = True) -> Path:
                rec_events.append("stop")
                self._running = False
                self.screen_path.write_bytes(b"partial")
                return self.screen_path

        with tempfile.TemporaryDirectory() as td:
            stop_file = os.path.join(td, "td.stop")
            run_dir = _make_fake_run(Path(td), script, durs)
            (run_dir / "dry" / "status.json").write_text(
                json.dumps({"ok": True, "script_sha": td_script.script_sha(str(run_dir))}),
                encoding="utf-8",
            )
            FakeStage.events = []
            with mock.patch.dict(os.environ, {"TD_STOP_FILE": stop_file}):
                rc = td_run.run_record(
                    str(run_dir),
                    clock=clock.now,
                    sleep_fn=clock.sleep,
                    driver_factory=_make_mock_driver_factory(clock, stop_file=stop_file, stop_at_step="s02"),
                    stage_factory=FakeStage,
                    recorder_factory=FakeRec,
                )
            self.assertEqual(rc, 130)
            self.assertEqual(FakeStage.events, ["prepare", "restore"])
            self.assertEqual(rec_events, ["start", "stop"])
            steps_data = json.loads((run_dir / "rec" / "steps.json").read_text(encoding="utf-8"))
            self.assertFalse(steps_data["ok"])
            self.assertEqual(steps_data["failed_step"], "s02")
            self.assertFalse((run_dir / "handoff" / "director.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
