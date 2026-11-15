#!/usr/bin/env python3
"""Unit tests for td_script.py validation, TIP checks, templates, and example scripts."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import td_script  # noqa: E402


def _minimal_valid_script() -> dict:
    return {
        "title": "Test Video",
        "promise": "Test *promise*",
        "voice": {"engine": "golha", "ref": None, "speed": 1.0},
        "layout": {"terminal": [0, 0, 1280, 720]},
        "steps": [
            {
                "id": "s01",
                "chapter": "Intro — المقدمة",
                "say": "سلام، اليوم غادي نشوفو مثال بسيط.",
                "actions": [{"do": "wait", "s": 0.5}],
            },
            {
                "id": "s02-recap",
                "say": "ملخص سريع: كلشي خدام مزيان.",
                "actions": [{"do": "wait", "s": 0.3}],
            },
        ],
    }


class TestScriptTipsAndResolution(unittest.TestCase):
    def test_minimal_good_script_has_no_errors_and_no_tips(self) -> None:
        s = _minimal_valid_script()
        self.assertEqual(td_script.validate_script(s), [])
        self.assertEqual(td_script.collect_tips(s), [])

    def test_tip_no_chapters(self) -> None:
        s = _minimal_valid_script()
        del s["steps"][0]["chapter"]
        tips = td_script.collect_tips(s)
        self.assertTrue(any("chapter" in t.lower() for t in tips), tips)

    def test_tip_over_90s_without_insert(self) -> None:
        s = _minimal_valid_script()
        s["steps"].insert(
            1,
            {
                "id": "s01b",
                "say": "خطوة طويلة شوية.",
                "actions": [{"do": "wait", "s": 95.0}],
            },
        )
        tips = td_script.collect_tips(s)
        self.assertTrue(any("90s" in t for t in tips), tips)

    def test_tip_over_90s_from_voice_index_without_insert(self) -> None:
        s = _minimal_valid_script()
        with tempfile.TemporaryDirectory() as td:
            vdir = Path(td) / "voice"
            vdir.mkdir()
            (vdir / "index.json").write_text(
                json.dumps([{"id": "s01", "dur": 55.0}, {"id": "s02-recap", "dur": 40.0}]),
                encoding="utf-8",
            )
            tips = td_script.collect_tips(s, run_dir=td)
            self.assertTrue(any("90s" in t for t in tips), tips)

    def test_tip_sentence_over_15_words(self) -> None:
        s = _minimal_valid_script()
        s["steps"][0]["say"] = " ".join(["كلمة"] * 16) + "."
        self.assertEqual(td_script.validate_script(s), [])
        tips = td_script.collect_tips(s)
        self.assertTrue(any("16 words" in t for t in tips), tips)

    def test_tip_launch_without_layout(self) -> None:
        s = _minimal_valid_script()
        s["steps"][0]["actions"] = [{"do": "launch", "cmd": "ghostty"}]
        tips = td_script.collect_tips(s)
        self.assertTrue(any("layout" in t for t in tips), tips)

        s["steps"][0]["layout"] = {"window": "class:ghostty", "slot": "terminal"}
        tips_with_layout = td_script.collect_tips(s)
        self.assertFalse(any("launches a window" in t for t in tips_with_layout), tips_with_layout)

    def test_tip_missing_recap_step(self) -> None:
        s = _minimal_valid_script()
        s["steps"][-1] = {
            "id": "s02",
            "say": "دابا كملنا التجربة.",
            "actions": [{"do": "wait", "s": 0.3}],
        }
        tips = td_script.collect_tips(s)
        self.assertTrue(any("recap" in t.lower() for t in tips), tips)

    def test_cmd_check_emits_tips_without_failing(self) -> None:
        s = _minimal_valid_script()
        del s["steps"][0]["chapter"]
        with tempfile.TemporaryDirectory() as td:
            spath = Path(td) / "script.json"
            spath.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = td_script.cmd_check(str(td))
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("TIP", out)
            self.assertIn("check: ready", out)

    def test_resolve_run_relative_to_skill_dir_from_other_cwd(self) -> None:
        old_cwd = os.getcwd()
        try:
            os.chdir("/tmp")
            resolved = td_script.resolve_run("examples/omarchy-menu")
            self.assertEqual(resolved, os.path.join(SKILL_DIR, "examples", "omarchy-menu"))
            self.assertEqual(td_script.cmd_check("examples/omarchy-menu"), 0)
            self.assertEqual(td_script.cmd_check("templates/script.json"), 0)
        finally:
            os.chdir(old_cwd)

    def test_example_and_template_have_zero_errors_and_zero_tips(self) -> None:
        for rel in ("examples/omarchy-menu/script.json", "templates/script.json"):
            path = os.path.join(SKILL_DIR, rel)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(td_script.validate_script(data), [], f"{rel} has validation errors")
            self.assertEqual(td_script.collect_tips(data, run_dir=os.path.dirname(path)), [], f"{rel} has TIPs")

    def test_cmd_new_uses_template_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_home = os.environ.get("TD_HOME")
            os.environ["TD_HOME"] = td
            try:
                rc = td_script.cmd_new("my-demo")
                self.assertEqual(rc, 0)
                created = Path(td) / "runs" / "my-demo" / "script.json"
                self.assertTrue(created.is_file())
                data = json.loads(created.read_text(encoding="utf-8"))
                self.assertEqual(data["title"], "TODO: my-demo")
                self.assertEqual(td_script.validate_script(data), [])
                self.assertEqual(td_script.collect_tips(data), [])
            finally:
                if old_home is None:
                    os.environ.pop("TD_HOME", None)
                else:
                    os.environ["TD_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
