#!/usr/bin/env python3
"""td_voice.py — `td voice test` and `td voice render <run>` CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import td_script  # noqa: E402
from tts.base import (  # noqa: E402
    VALID_ENGINES,
    TTSError,
    apply_pronounce,
    setup_command,
    synth_batch,
    td_home,
    wav_duration,
)

TEST_SENTENCES = [
    ("darija", "السلام عليكم، اليوم غادي نشوفو كيفاش نبدلو الإعدادات ديال النظام بطريقة ساهلة."),
    ("darija+fr", "قبل ما تبدا الخدمة، خاصك تفتح le terminal وتتحقق من la configuration ديال النظام."),
    ("darija+en", "ضغط على Super مع Space باش تحل Omarchy menu وتكتب theme."),
]

_SAFE_STEP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _step_sha(say: str, prepared_text: str, voice: dict[str, Any]) -> str:
    ref = voice.get("ref")
    ref_sig: dict[str, Any] | None = None
    if isinstance(ref, str) and ref.strip():
        ref_abs = os.path.abspath(os.path.expanduser(ref))
        if os.path.isfile(ref_abs):
            st = os.stat(ref_abs)
            ref_sig = {"path": ref, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        else:
            ref_sig = {"path": ref}

    payload = {
        "say": say,
        "prepared": prepared_text,
        "engine": voice.get("engine", "golha"),
        "speed": float(voice.get("speed", 1.0)),
        "ref": ref_sig,
        "ref_text": voice.get("ref_text"),
        "instruct": voice.get("instruct"),
        "language": voice.get("language"),
        "dialect": voice.get("dialect"),
        "num_step": voice.get("num_step"),
        "temperature": voice.get("temperature"),
        "cfg_weight": voice.get("cfg_weight"),
        "exaggeration": voice.get("exaggeration"),
        "repetition_penalty": voice.get("repetition_penalty"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_json_atomic(path: str, data: Any) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def cmd_test(args: argparse.Namespace) -> int:
    engines = list(VALID_ENGINES) if args.engine == "both" else [args.engine]
    out_dir = os.path.join(td_home(), "voice-test")
    os.makedirs(out_dir, exist_ok=True)

    if args.text is not None:
        text = args.text.strip()
        if not text:
            print("ERROR: --text must not be empty", file=sys.stderr)
            return 2
        samples = [("custom", text)]
    else:
        samples = TEST_SENTENCES

    any_failed = False
    produced_files: list[str] = []

    for engine in engines:
        voice: dict[str, Any] = {"engine": engine, "speed": args.speed}
        if args.ref:
            voice["ref"] = args.ref

        items = [
            {
                "id": str(idx),
                "label": label,
                "text": txt,
                "out_wav": os.path.join(out_dir, f"{engine}-{idx}.wav"),
            }
            for idx, (label, txt) in enumerate(samples, 1)
        ]

        print(f"== {engine} ==")
        try:
            results = synth_batch(items, voice=voice)
        except TTSError as exc:
            any_failed = True
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue
        except Exception as exc:
            any_failed = True
            print(f"  ERROR: {exc}\n  Fix: {setup_command(engine)}", file=sys.stderr)
            continue

        for item, res in zip(items, results):
            dur = float(res["dur"])
            gen = float(res["gen_seconds"])
            rtf = (gen / dur) if dur > 0 else 0.0
            produced_files.append(res["out_wav"])
            print(
                f"  [{item['id']}] {item['label']:9s} dur={dur:.2f}s  gen={gen:.2f}s  "
                f"RTF={rtf:.2f}  -> {res['out_wav']}"
            )

    if produced_files:
        print(f"\nSamples saved under {out_dir} (not auto-played — listen and pick your engine).")
    return 1 if any_failed else 0


def _load_prev_index(index_path: str) -> dict[str, dict[str, Any]]:
    if not os.path.isfile(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            out[entry["id"]] = entry
    return out


def cmd_render(args: argparse.Namespace) -> int:
    try:
        run_dir = td_script.resolve_run(args.run)
        script = td_script.load_script(args.run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    voice = dict(script.get("voice") or {})
    engine = voice.get("engine") or "golha"
    if engine not in VALID_ENGINES:
        print(f"ERROR: voice.engine must be one of {', '.join(VALID_ENGINES)} (got {engine!r})", file=sys.stderr)
        return 1
    voice["engine"] = engine

    steps = script.get("steps")
    if not isinstance(steps, list) or not steps:
        print(f"ERROR: {run_dir}/script.json has no steps", file=sys.stderr)
        return 1

    voice_dir = os.path.join(run_dir, "voice")
    os.makedirs(voice_dir, exist_ok=True)
    index_path = os.path.join(voice_dir, "index.json")
    prev_by_id = {} if args.force else _load_prev_index(index_path)

    plan: list[dict[str, Any]] = []
    todo: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            print(f"ERROR: step #{idx} must be a JSON object", file=sys.stderr)
            return 1
        sid = step.get("id")
        if not isinstance(sid, str) or not _SAFE_STEP_ID_RE.match(sid):
            print(f"ERROR: step #{idx} has invalid id {sid!r}", file=sys.stderr)
            return 1
        if sid in seen_ids:
            print(f"ERROR: duplicate step id {sid!r}", file=sys.stderr)
            return 1
        seen_ids.add(sid)

        say = step.get("say")
        if not isinstance(say, str) or not say.strip():
            print(f"ERROR: step {sid!r} has empty 'say' text", file=sys.stderr)
            return 1

        prepared = apply_pronounce(say, engine)
        sha = _step_sha(say, prepared, voice)
        wav_path = os.path.join(voice_dir, f"{sid}.wav")
        rel_file = os.path.join("voice", f"{sid}.wav")

        prev = prev_by_id.get(sid)
        cached_ok = (
            prev is not None
            and prev.get("text_sha") == sha
            and os.path.isfile(wav_path)
            and os.path.getsize(wav_path) > 44
        )
        if cached_ok:
            dur_val = prev.get("dur")
            dur = float(dur_val) if isinstance(dur_val, (int, float)) and dur_val > 0 else wav_duration(wav_path)
            plan.append({"id": sid, "file": rel_file, "dur": round(dur, 4), "text_sha": sha, "cached": True})
        else:
            plan.append({"id": sid, "file": rel_file, "dur": None, "text_sha": sha, "cached": False})
            todo.append({"id": sid, "text": say, "out_wav": wav_path})

    if todo:
        try:
            rendered = synth_batch(todo, voice=voice)
        except TTSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        dur_by_id = {str(r["id"]): float(r["dur"]) for r in rendered}
        for entry in plan:
            if not entry["cached"]:
                entry["dur"] = round(dur_by_id[entry["id"]], 4)

    index_entries = [
        {"id": e["id"], "file": e["file"], "dur": e["dur"], "text_sha": e["text_sha"]}
        for e in plan
    ]
    _write_json_atomic(index_path, index_entries)

    n_rendered = len(todo)
    n_cached = len(plan) - n_rendered
    total_dur = sum(float(e["dur"] or 0.0) for e in index_entries)
    print(
        f"voice render ({engine}): rendered={n_rendered}, cached={n_cached}, "
        f"total_dur={total_dur:.2f}s -> {index_path}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="td voice", description="TTS engine testing and per-step rendering")
    sub = ap.add_subparsers(dest="subcmd", required=True)

    p_test = sub.add_parser("test", help="Synthesize test sentences with golha & lahgtna for comparison")
    p_test.add_argument("--text", default=None, help="Custom single text to synthesize with selected engine(s)")
    p_test.add_argument(
        "--engine",
        choices=("both", *VALID_ENGINES),
        default="both",
        help="Which TTS engine(s) to test (default: both)",
    )
    p_test.add_argument("--ref", default=None, help="Optional reference voice WAV path")
    p_test.add_argument("--speed", type=float, default=1.0, help="Speech tempo (0.8..1.25)")
    p_test.set_defaults(func=cmd_test)

    p_ren = sub.add_parser("render", help="Incrementally render per-step voice/<id>.wav + voice/index.json")
    p_ren.add_argument("run", help="Run name under TD_HOME/runs/<name> or path to run dir / script.json")
    p_ren.add_argument("--force", action="store_true", help="Re-render all steps ignoring cached text_sha")
    p_ren.set_defaults(func=cmd_render)
    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
