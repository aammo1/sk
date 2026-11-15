#!/usr/bin/env python3
"""td_handoff.py — Build <run>/handoff/ for `ev2 init --from-director`."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import td_script  # noqa: E402
import words_align  # noqa: E402

TARGET_W = 1920
TARGET_H = 1080
TARGET_SR = 48000
TARGET_CHANNELS = 2
TARGET_CODEC = "pcm_s24le"
CURSOR_HZ = 15.0
KEY_PILL_DUR = 2.5
INSERT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class HandoffError(RuntimeError):
    """Actionable error raised when a run cannot be exported to handoff/."""


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


def probe_duration(media_path: Path) -> float:
    """Return media duration in seconds via ffprobe."""
    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15.0,
    )
    if res.returncode != 0 or not res.stdout.strip():
        raise HandoffError(f"ffprobe failed on {media_path}: {res.stderr.strip()}")
    return float(res.stdout.strip())


def _coord_mapper(start_meta: dict[str, Any], steps_data: dict[str, Any]) -> Callable[[float, float], tuple[float, float]]:
    """Map monitor-relative logical coords (sx, sy) -> 1920x1080 cam_raw pixels."""
    lw = steps_data.get("logical_width")
    lh = steps_data.get("logical_height")
    if not lw or not lh:
        mw = start_meta.get("monitor_width")
        mh = start_meta.get("monitor_height")
        scale = float(steps_data.get("monitor_scale") or 1.0)
        if mw and mh and scale > 0:
            lw = float(mw) / scale
            lh = float(mh) / scale
        else:
            lw, lh = float(TARGET_W), float(TARGET_H)
    lw = float(lw)
    lh = float(lh)
    if abs(lw - TARGET_W) < 1e-3 and abs(lh - TARGET_H) < 1e-3:
        return lambda x, y: (round(float(x), 1), round(float(y), 1))

    fit = min(TARGET_W / lw, TARGET_H / lh)
    ox = (TARGET_W - lw * fit) / 2.0
    oy = (TARGET_H - lh * fit) / 2.0

    def _map(x: float, y: float) -> tuple[float, float]:
        return round(ox + float(x) * fit, 1), round(oy + float(y) * fit, 1)

    return _map


def _to_rel_time(raw_t: float, rec_start: float, times_relative: bool) -> float:
    return float(raw_t) if times_relative else float(raw_t) - rec_start


def build_vo_wav(
    screen_dur: float,
    step_placements: list[tuple[Path, float]],
    out_wav: Path,
) -> Path:
    """Mix per-step voice WAVs onto a silence bed of `screen_dur` seconds (48 kHz 24-bit stereo)."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    dur_s = max(0.05, float(screen_dur))
    tmp_wav = out_wav.with_name(f".{out_wav.stem}.tmp.wav")
    if tmp_wav.exists():
        tmp_wav.unlink()

    valid = [(p, max(0.0, float(off))) for p, off in step_placements if p.is_file()]
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-t",
        f"{dur_s:.6f}",
        "-i",
        f"anullsrc=r={TARGET_SR}:cl=stereo",
    ]

    if not valid:
        cmd.extend(["-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS), "-c:a", TARGET_CODEC, str(tmp_wav)])
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            tmp_wav.unlink(missing_ok=True)
            raise HandoffError(f"ffmpeg vo.wav silence generation failed: {res.stderr.strip()}")
        os.replace(tmp_wav, out_wav)
        return out_wav

    filter_parts: list[str] = []
    mix_labels = ["[0:a]"]
    for idx, (wav_path, offset_s) in enumerate(valid, 1):
        cmd.extend(["-i", str(wav_path)])
        delay_ms = max(0, int(round(offset_s * 1000.0)))
        lbl = f"[a{idx}]"
        filter_parts.append(
            f"[{idx}:a]aresample={TARGET_SR},aformat=channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}{lbl}"
        )
        mix_labels.append(lbl)

    filter_parts.append(
        f"{''.join(mix_labels)}amix=inputs={len(valid) + 1}:"
        f"duration=first:dropout_transition=0:normalize=0[out]"
    )
    filter_script_str = ";".join(filter_parts)

    cmd.extend(
        [
            "-filter_complex",
            filter_script_str,
            "-map",
            "[out]",
            "-ar",
            str(TARGET_SR),
            "-ac",
            str(TARGET_CHANNELS),
            "-c:a",
            TARGET_CODEC,
            str(tmp_wav),
        ]
    )
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if res.returncode != 0:
        tmp_wav.unlink(missing_ok=True)
        raise HandoffError(f"ffmpeg vo.wav mix failed: {res.stderr.strip()}")

    os.replace(tmp_wav, out_wav)
    return out_wav


def convert_events_to_inputs(
    events_path: Path,
    rec_start: float,
    map_xy: Callable[[float, float], tuple[float, float]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Convert `rec/events.jsonl` to editor-v2 `work/inputs.json` format.

    Returns `(inputs_dict, key_events_for_plan)`.
    """
    events: list[dict[str, Any]] = []
    if events_path.is_file():
        for ln in events_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if isinstance(ev, dict) and "t" in ev and "type" in ev:
                events.append(ev)

    events.sort(key=lambda e: float(e["t"]))

    clicks: list[dict[str, Any]] = []
    typing: list[list[float]] = []
    key_combos: list[dict[str, Any]] = []
    plan_keys: list[dict[str, Any]] = []
    raw_moves: list[tuple[float, float, float]] = []

    active_type_start: float | None = None

    for ev in events:
        tv = float(ev["t"]) - rec_start
        if tv < -1e-6:
            continue
        tv = max(0.0, tv)
        etype = ev.get("type")

        if etype == "move":
            if "x" in ev and "y" in ev:
                cx, cy = map_xy(float(ev["x"]), float(ev["y"]))
                raw_moves.append((tv, cx, cy))
        elif etype == "down":
            if "x" in ev and "y" in ev:
                cx, cy = map_xy(float(ev["x"]), float(ev["y"]))
                btn = str(ev.get("button") or "left").lower()
                if btn not in ("left", "right", "middle"):
                    btn = "left"
                clicks.append({"t": round(tv, 3), "x": cx, "y": cy, "btn": btn})
                raw_moves.append((tv, cx, cy))
        elif etype == "up":
            if "x" in ev and "y" in ev:
                cx, cy = map_xy(float(ev["x"]), float(ev["y"]))
                raw_moves.append((tv, cx, cy))
        elif etype == "scroll":
            if "x" in ev and "y" in ev:
                cx, cy = map_xy(float(ev["x"]), float(ev["y"]))
                raw_moves.append((tv, cx, cy))
        elif etype == "type_start":
            if active_type_start is None:
                active_type_start = tv
        elif etype == "type_end":
            if active_type_start is not None:
                t0 = round(active_type_start, 3)
                t1 = round(max(active_type_start, tv), 3)
                typing.append([t0, t1])
                active_type_start = None
        elif etype == "key":
            keys_str = str(ev.get("keys") or "").strip()
            if keys_str:
                parts = [p.strip() for p in keys_str.split("+") if p.strip()]
                if parts:
                    src_t = round(tv, 3)
                    key_combos.append({"t": src_t, "combo": parts})
                    if 1 <= len(parts) <= 4 and all(len(p) <= 12 for p in parts):
                        # Debounce plan key pills so back-to-back shortcuts do not overlap in ev2_timeline.key_ranges
                        if not plan_keys or src_t >= plan_keys[-1]["src_t"] + plan_keys[-1]["dur"]:
                            plan_keys.append({"src_t": src_t, "keys": " + ".join(parts), "dur": KEY_PILL_DUR})

    if active_type_start is not None and events:
        last_tv = max(active_type_start, float(events[-1]["t"]) - rec_start)
        typing.append([round(active_type_start, 3), round(last_tv, 3)])

    # Subsample cursor path to ~15 Hz while preserving sequence endpoints
    cursor: list[list[float]] = []
    min_dt = 1.0 / CURSOR_HZ
    last_kept_t = -1e9
    for idx, (tv, cx, cy) in enumerate(raw_moves):
        is_last = idx == len(raw_moves) - 1
        next_gap = (raw_moves[idx + 1][0] - tv) if not is_last else 999.0
        if (tv - last_kept_t) >= min_dt - 1e-6 or is_last or next_gap > 0.15:
            sample = [round(tv, 3), cx, cy]
            if not cursor or cursor[-1] != sample:
                cursor.append(sample)
                last_kept_t = tv

    inputs_doc: dict[str, Any] = {
        "source": "tutorial-director",
        "aligned": "exact",
        "log": None,
        "offset_wall": 0.0,
        "align": {"method": "director", "confidence": 1.0},
        "clicks_inferred": False,
        "clicks": clicks,
        "typing": typing,
        "keys": key_combos,
        "cursor": cursor,
    }
    return inputs_doc, plan_keys


def _sanitize_insert_name(step_id: str, recipe: str, used: set[str]) -> str:
    raw = f"{step_id}-{recipe}".lower()
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"i-{cleaned}".strip("-")
    base = cleaned[:40].rstrip("-") or "insert"
    cand = base
    n = 2
    while cand in used or not INSERT_NAME_RE.match(cand):
        suffix = f"-{n}"
        cand = (base[: 40 - len(suffix)].rstrip("-") or "i") + suffix
        n += 1
    used.add(cand)
    return cand


def build_plan(
    script: dict[str, Any],
    steps_data: dict[str, Any],
    rec_start: float,
    screen_dur: float,
    plan_keys: list[dict[str, Any]],
    map_xy: Callable[[float, float], tuple[float, float]],
) -> dict[str, Any]:
    """Build `<run>/handoff/plan.json` editorial suggestions in source seconds."""
    times_rel = bool(steps_data.get("times_relative", False))
    settle_after = float((script.get("pace") or {}).get("settle_after", 1.0))
    step_meta_by_id = {
        str(s["id"]): s for s in (steps_data.get("steps") or []) if isinstance(s, dict) and s.get("id")
    }

    chapters: list[dict[str, Any]] = []
    inserts: list[dict[str, Any]] = []
    callouts: list[dict[str, Any]] = []
    used_insert_names: set[str] = set()

    for step in script.get("steps") or []:
        sid = str(step["id"])
        rec_step = step_meta_by_id[sid]
        vs_rel = max(0.0, _to_rel_time(float(rec_step["voice_start"]), rec_start, times_rel))

        if step.get("chapter"):
            chapters.append({"src_t": round(vs_rel, 3), "title": str(step["chapter"])})

        actions_rec = rec_step.get("actions") or []

        if step.get("insert"):
            ins = step["insert"]
            recipe = str(ins["recipe"])
            dur = float(ins.get("dur", 12.0))
            last_screen_end = rec_step.get("last_screen_action_end")
            if last_screen_end is not None:
                base_t = max(0.0, _to_rel_time(float(last_screen_end), rec_start, times_rel))
            elif actions_rec:
                base_t = max(0.0, _to_rel_time(float(actions_rec[-1]["end"]), rec_start, times_rel))
            else:
                base_t = vs_rel
            src_t = base_t + settle_after
            if screen_dur > 0.2:
                src_t = min(src_t, max(0.0, screen_dur - 0.1))
            inserts.append(
                {
                    "name": _sanitize_insert_name(sid, recipe, used_insert_names),
                    "src_t": round(src_t, 3),
                    "dur": round(dur, 3),
                    "recipe": recipe,
                    "data": dict(ins.get("data") or {}),
                }
            )

        if step.get("callout"):
            co = step["callout"]
            at_idx = int(co.get("at_action", 0))
            co_dur = float(co.get("dur", 3.0))
            if 0 <= at_idx < len(actions_rec):
                act_rec = actions_rec[at_idx]
                raw_at = act_rec.get("event_t", act_rec["start"])
                co_t = max(0.0, _to_rel_time(float(raw_at), rec_start, times_rel))
                co_entry: dict[str, Any] = {
                    "src_t": round(co_t, 3),
                    "text": str(co["text"]),
                    "dur": round(co_dur, 3),
                }
                if act_rec.get("x") is not None and act_rec.get("y") is not None:
                    cx, cy = map_xy(float(act_rec["x"]), float(act_rec["y"]))
                    co_entry["x"] = cx
                    co_entry["y"] = cy
            else:
                co_entry = {
                    "src_t": round(vs_rel, 3),
                    "text": str(co["text"]),
                    "dur": round(co_dur, 3),
                }
            callouts.append(co_entry)

    # Check inserts do not overlap
    inserts.sort(key=lambda item: item["src_t"])
    for a, b in zip(inserts, inserts[1:]):
        if b["src_t"] < a["src_t"] + a["dur"] - 1e-6:
            raise HandoffError(
                f'inserts "{a["name"]}" ({a["src_t"]:.2f}s + {a["dur"]:.2f}s = {a["src_t"] + a["dur"]:.2f}s) '
                f'and "{b["name"]}" ({b["src_t"]:.2f}s) overlap; shorten dur or add pause_after'
            )

    return {
        "title": str(script["title"]),
        "promise": str(script["promise"]),
        "chapters": chapters,
        "inserts": inserts,
        "callouts": callouts,
        "keys": plan_keys,
    }


def run_handoff(
    run: str,
    *,
    use_whisper: bool = True,
    model: str | None = None,
    transcribe_fn=None,
) -> Path:
    """Validate recorded artifacts and write all 6 files into `<run>/handoff/`."""
    run_dir = Path(td_script.resolve_run(run)).resolve()
    script = td_script.load_script(str(run_dir))
    probs = td_script.validate_script(script)
    if probs:
        raise HandoffError("script.json failed validation:\n  " + "\n  ".join(probs))

    rec_dir = run_dir / "rec"
    rec_screen = rec_dir / "screen.mp4"
    start_path = rec_dir / "start.json"
    steps_path = rec_dir / "steps.json"
    events_path = rec_dir / "events.jsonl"

    if not rec_screen.is_file() or rec_screen.stat().st_size == 0:
        raise HandoffError(f"Recorded video missing or empty: {rec_screen} (run `td record` first)")
    if not start_path.is_file():
        raise HandoffError(f"Recording start metadata missing: {start_path}")
    if not steps_path.is_file():
        raise HandoffError(f"Recording step log missing: {steps_path}")

    start_meta = json.loads(start_path.read_text(encoding="utf-8"))
    steps_data = json.loads(steps_path.read_text(encoding="utf-8"))

    if steps_data.get("ok") is not True:
        detail = steps_data.get("error") or f"failed_step={steps_data.get('failed_step')}"
        raise HandoffError(f"Refusing handoff: recording did not succeed ({detail})")

    rec_steps = steps_data.get("steps") or []
    rec_by_id = {str(s["id"]): s for s in rec_steps if isinstance(s, dict) and s.get("id")}
    for step in script["steps"]:
        sid = str(step["id"])
        rs = rec_by_id.get(sid)
        if rs is None or rs.get("ok") is not True:
            raise HandoffError(f"Refusing handoff: step {sid!r} missing or failed in rec/steps.json")
        wav = run_dir / "voice" / f"{sid}.wav"
        if not wav.is_file() or wav.stat().st_size <= 44:
            raise HandoffError(f"Missing rendered voice WAV for step {sid!r}: {wav}")

    rec_start = float(steps_data.get("rec_start_monotonic") or start_meta.get("monotonic_time") or 0.0)
    times_rel = bool(steps_data.get("times_relative", False))
    screen_dur = probe_duration(rec_screen)

    handoff_dir = run_dir / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    # Validate inputs + plan first so overlap errors fail fast before copying/mixing media
    map_xy = _coord_mapper(start_meta, steps_data)
    inputs_doc, plan_keys = convert_events_to_inputs(events_path, rec_start, map_xy)
    plan_doc = build_plan(script, steps_data, rec_start, screen_dur, plan_keys, map_xy)

    # 1. screen.mp4
    out_screen = handoff_dir / "screen.mp4"
    tmp_screen = handoff_dir / ".screen.tmp.mp4"
    shutil.copy2(rec_screen, tmp_screen)
    os.replace(tmp_screen, out_screen)

    # 2. vo.wav
    placements: list[tuple[Path, float]] = []
    for step in script["steps"]:
        sid = str(step["id"])
        rs = rec_by_id[sid]
        vs_rel = max(0.0, _to_rel_time(float(rs["voice_start"]), rec_start, times_rel))
        placements.append((run_dir / "voice" / f"{sid}.wav", vs_rel))
    build_vo_wav(screen_dur, placements, handoff_dir / "vo.wav")

    # 3. inputs.json
    _atomic_write_json(handoff_dir / "inputs.json", inputs_doc)

    # 4. words.json
    words, words_meta = words_align.align_words(
        run_dir,
        steps_data=steps_data,
        script=script,
        use_whisper=use_whisper,
        model=model,
        transcribe_fn=transcribe_fn,
    )
    words_align.write_words(handoff_dir / "words.json", words)

    # 5. plan.json
    _atomic_write_json(handoff_dir / "plan.json", plan_doc)

    # 6. director.json
    director_steps: list[dict[str, Any]] = []
    for step in script["steps"]:
        sid = str(step["id"])
        rs = rec_by_id[sid]
        director_steps.append(
            {
                "id": sid,
                "start": round(max(0.0, _to_rel_time(float(rs["start"]), rec_start, times_rel)), 4),
                "end": round(max(0.0, _to_rel_time(float(rs["end"]), rec_start, times_rel)), 4),
                "voice_start": round(max(0.0, _to_rel_time(float(rs["voice_start"]), rec_start, times_rel)), 4),
                "voice_end": round(max(0.0, _to_rel_time(float(rs["voice_end"]), rec_start, times_rel)), 4),
                "ok": bool(rs.get("ok", False)),
            }
        )

    director_doc = {
        "engine": str((script.get("voice") or {}).get("engine") or steps_data.get("engine") or "golha"),
        "script_sha": td_script.script_sha(str(run_dir)),
        "user": str(steps_data.get("user") or getpass.getuser()),
        "words_source": words_meta.get("source", "script"),
        "words_align_method": words_meta.get("method"),
        "screen_duration": round(screen_dur, 4),
        "steps": director_steps,
    }
    _atomic_write_json(handoff_dir / "director.json", director_doc)

    return handoff_dir


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build <run>/handoff/ for editor-v2")
    ap.add_argument("run", help="Run name under $TD_HOME/runs/<name> or path to run dir")
    ap.add_argument("--model", default=None, help="Override EV2_WHISPER_MODEL for word alignment")
    ap.add_argument("--no-whisper", action="store_true", help="Use proportional word alignment without Whisper")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        out_dir = run_handoff(args.run, use_whisper=not args.no_whisper, model=args.model)
    except (HandoffError, FileNotFoundError, ValueError) as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 1
    print(f"handoff: ready -> {out_dir}")
    print(f"  next: ev2 init --from-director {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
