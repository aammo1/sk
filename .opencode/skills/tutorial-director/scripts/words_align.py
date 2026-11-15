#!/usr/bin/env python3
"""words_align.py — Align script words to TTS step audio for editor-v2 words.json.

Runs faster-whisper (via editor-v2's read-only venv when available) on each step's
rendered WAV to obtain word timestamps, aligns the recognised tokens to the exact
script words using difflib on normalized tokens, and falls back to proportional
character-length distribution across [voice_start, voice_end] whenever Whisper is
unavailable or alignment confidence is too low.

Guarantees:
- Output matches editor-v2's work/tx/words.json array schema: [{"w", "s", "e"}, ...]
- Every word from script.json's `say` fields is preserved verbatim (Darija + Latin)
- Timestamps are non-negative, rounded to 3 decimals, and strictly monotonic
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import td_script  # noqa: E402
from tts.base import wav_duration  # noqa: E402

DEFAULT_EV2_PYTHON = os.path.expanduser("~/.cache/editor-v2/venv/bin/python")
DEFAULT_WHISPER_MODEL = "large-v3-turbo"

# Common Arabic transliterations produced by Whisper for Latin tech words in Darija speech
_AR_TO_LATIN_HINTS: dict[str, str] = {
    "اومارشي": "omarchy",
    "هايبرلاند": "hyprland",
    "لينكس": "linux",
    "دوكر": "docker",
    "بايثون": "python",
    "تيرمينال": "terminal",
    "جيت": "git",
    "جيتهاب": "github",
    "كلود": "claude",
    "فيرسيل": "vercel",
    "نيكست": "next",
    "تايبسكريبت": "typescript",
    "افافامبيج": "ffmpeg",
    "كدينلايف": "kdenlive",
    "داشبورد": "dashboard",
    "مينيو": "menu",
    "ثيم": "theme",
    "ستيل": "style",
    "ستايل": "style",
}

_WHISPER_BATCH_HELPER = r"""
import json, os, sys
from faster_whisper import WhisperModel

req = json.load(sys.stdin)
model_name = req["model"]
device_pref = req.get("device", "auto")

if device_pref == "cuda":
    device, compute = "cuda", "float16"
elif device_pref == "cpu":
    device, compute = "cpu", "int8"
else:
    device, compute = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device, compute = "cuda", "float16"
    except Exception:
        pass

try:
    model = WhisperModel(model_name, device=device, compute_type=compute)
except Exception:
    if device != "cpu":
        device, compute = "cpu", "int8"
        model = WhisperModel(model_name, device=device, compute_type=compute)
    else:
        raise

results = {}
for item in req["items"]:
    sid = item["id"]
    wav = item["wav"]
    lang = item.get("language")
    prompt = item.get("initial_prompt") or None
    kw = {
        "word_timestamps": True,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "beam_size": 5,
    }
    if lang:
        kw["language"] = lang
    if prompt:
        kw["initial_prompt"] = prompt
    segments, _info = model.transcribe(wav, **kw)
    words = []
    for seg in segments:
        if getattr(seg, "words", None):
            for w in seg.words:
                txt = (w.word or "").strip()
                if txt:
                    words.append([txt, float(w.start), float(w.end)])
    results[sid] = words

print(json.dumps({"device": device, "model": model_name, "results": results}, ensure_ascii=False))
"""


def find_ev2_python() -> str | None:
    """Return path to editor-v2's venv Python if present and executable."""
    for cand in (
        os.environ.get("EV2_PY"),
        DEFAULT_EV2_PYTHON,
    ):
        if cand:
            expanded = os.path.abspath(os.path.expanduser(cand))
            if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
                return expanded
    return None


def normalize_token(token: str) -> str:
    """Normalize an Arabic/Darija/Latin token for sequence alignment."""
    if not token:
        return ""
    t = token.strip().lower()
    # Strip leading/trailing punctuation while keeping internal dots/hyphens/Arabic
    t = re.sub(r"^[^\w\u0600-\u06FF]+|[^\w\u0600-\u06FF]+$", "", t)
    # Strip Arabic diacritics and tatweel
    t = re.sub(r"[\u064B-\u065F\u0670ـ]", "", t)
    # Normalize Arabic letters
    t = re.sub(r"[إأآ]", "ا", t)
    t = t.replace("ة", "ه").replace("ى", "ي")
    t = t.strip()
    return _AR_TO_LATIN_HINTS.get(t, t)


def _char_weight(word: str) -> int:
    stripped = re.sub(r"\s+", "", word)
    return max(1, len(stripped))


def distribute_proportional(
    tokens: list[str],
    start_t: float,
    end_t: float,
) -> list[dict[str, Any]]:
    """Distribute `tokens` across `[start_t, end_t]` proportional to character length."""
    if not tokens:
        return []
    s0 = max(0.0, float(start_t))
    e0 = max(s0 + 0.001 * len(tokens), float(end_t))
    span = max(0.0, e0 - s0)
    weights = [_char_weight(w) for w in tokens]
    total_w = float(sum(weights)) or float(len(tokens))

    out: list[dict[str, Any]] = []
    cur = s0
    for idx, (tok, wt) in enumerate(zip(tokens, weights)):
        if idx == len(tokens) - 1:
            nxt = e0
        else:
            nxt = cur + span * (wt / total_w)
        out.append({"w": tok, "s": cur, "e": max(cur, nxt)})
        cur = nxt
    return out


def transcribe_steps_whisper(
    items: list[dict[str, Any]],
    *,
    model: str | None = None,
    ev2_python: str | None = None,
    timeout: float = 300.0,
) -> tuple[dict[str, list[tuple[str, float, float]]], str | None]:
    """Run faster-whisper in editor-v2's venv (read-only) on a batch of step WAVs.

    Each item: {"id": str, "wav": str, "initial_prompt": str, "language": str | None}.
    Returns `(results_by_id, error_message)`.
    """
    py = ev2_python or find_ev2_python()
    if not py:
        return {}, "editor-v2 venv Python not found"

    valid_items = [it for it in items if it.get("wav") and os.path.isfile(str(it["wav"]))]
    if not valid_items:
        return {}, "no WAV files to transcribe"

    model_name = model or os.environ.get("EV2_WHISPER_MODEL") or DEFAULT_WHISPER_MODEL
    device_pref = os.environ.get("EV2_WHISPER_DEVICE", "auto")
    payload = {
        "model": model_name,
        "device": device_pref,
        "items": valid_items,
    }

    try:
        proc = subprocess.run(
            [py, "-c", _WHISPER_BATCH_HELPER],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"faster-whisper invocation failed: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = err[-1] if err else f"exit {proc.returncode}"
        return {}, f"faster-whisper failed ({tail})"

    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        return {}, f"invalid JSON from faster-whisper helper: {exc}"

    raw_results = data.get("results") or {}
    parsed: dict[str, list[tuple[str, float, float]]] = {}
    for sid, wlist in raw_results.items():
        cleaned: list[tuple[str, float, float]] = []
        for entry in wlist:
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                txt = str(entry[0]).strip()
                if txt:
                    s_t = max(0.0, float(entry[1]))
                    e_t = max(s_t, float(entry[2]))
                    cleaned.append((txt, s_t, e_t))
        parsed[str(sid)] = cleaned
    return parsed, None


def align_step_words(
    say: str,
    asr_words: list[tuple[str, float, float]] | None,
    voice_start: float,
    voice_end: float,
) -> tuple[list[dict[str, Any]], str]:
    """Align `say`'s exact tokens to `asr_words` (relative to step start 0.0) and offset by `voice_start`.

    Returns `(word_dicts, method_used)` where `method_used` is `"difflib"` or `"proportional"`.
    """
    script_tokens = say.split()
    if not script_tokens:
        return [], "empty"

    v_start = max(0.0, float(voice_start))
    v_end = max(v_start + 0.001 * len(script_tokens), float(voice_end))
    step_dur = v_end - v_start

    if not asr_words:
        return distribute_proportional(script_tokens, v_start, v_end), "proportional"

    # Clamp ASR timings into [0, step_dur]
    clamped_asr: list[tuple[str, float, float]] = []
    for txt, s_t, e_t in asr_words:
        cs = max(0.0, min(step_dur, float(s_t)))
        ce = max(cs, min(step_dur, float(e_t)))
        clamped_asr.append((txt, cs, ce))

    s_norm = [normalize_token(t) for t in script_tokens]
    a_norm = [normalize_token(w[0]) for w in clamped_asr]

    matcher = difflib.SequenceMatcher(None, s_norm, a_norm, autojunk=False)
    opcodes = matcher.get_opcodes()

    matched_script_tokens = sum((i2 - i1) for tag, i1, i2, _j1, _j2 in opcodes if tag == "equal")
    match_ratio = matched_script_tokens / float(len(script_tokens))

    # If alignment confidence fails, fall back to proportional character-length distribution
    if matched_script_tokens == 0 or (
        match_ratio < 0.2 and abs(len(clamped_asr) - len(script_tokens)) > max(1, int(len(script_tokens) * 0.5))
    ):
        return distribute_proportional(script_tokens, v_start, v_end), "proportional"

    # Assign anchor times from equal blocks; leave gaps as None to interpolate monotonically
    assigned: list[tuple[float, float] | None] = [None] * len(script_tokens)
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                _, s_t, e_t = clamped_asr[j1 + k]
                assigned[i1 + k] = (s_t, max(s_t, e_t))
        elif tag == "replace" and (j2 > j1):
            span_s = clamped_asr[j1][1]
            span_e = max(span_s, clamped_asr[j2 - 1][2])
            if span_e > span_s:
                sub = distribute_proportional(script_tokens[i1:i2], span_s, span_e)
                for k, item in enumerate(sub):
                    assigned[i1 + k] = (item["s"], item["e"])

    # Fill remaining None spans (delete blocks or zero-width replace blocks) between neighbor anchors
    idx = 0
    n = len(script_tokens)
    while idx < n:
        if assigned[idx] is not None:
            idx += 1
            continue
        gap_start_idx = idx
        while idx < n and assigned[idx] is None:
            idx += 1
        gap_end_idx = idx

        left_t = assigned[gap_start_idx - 1][1] if gap_start_idx > 0 and assigned[gap_start_idx - 1] is not None else 0.0
        right_t = assigned[gap_end_idx][0] if gap_end_idx < n and assigned[gap_end_idx] is not None else step_dur
        if right_t <= left_t:
            right_t = min(step_dur, left_t + 0.01 * (gap_end_idx - gap_start_idx))
        sub = distribute_proportional(script_tokens[gap_start_idx:gap_end_idx], left_t, right_t)
        for k, item in enumerate(sub):
            assigned[gap_start_idx + k] = (item["s"], item["e"])

    out: list[dict[str, Any]] = []
    for tok, span in zip(script_tokens, assigned):
        assert span is not None
        out.append({"w": tok, "s": v_start + span[0], "e": v_start + span[1]})
    return out, "difflib"


def enforce_monotonic(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round timestamps to 3 decimals and guarantee monotonic non-overlapping times."""
    out: list[dict[str, Any]] = []
    prev_e = 0.0
    for entry in words:
        w = str(entry["w"])
        s = round(max(prev_e, float(entry["s"])), 3)
        e = round(max(s, float(entry["e"])), 3)
        out.append({"w": w, "s": s, "e": e})
        prev_e = e
    return out


def align_words(
    run_dir: str | Path,
    steps_data: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
    *,
    use_whisper: bool = True,
    model: str | None = None,
    transcribe_fn: Callable[[list[dict[str, Any]]], tuple[dict[str, list[tuple[str, float, float]]], str | None]]
    | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Produce editor-v2 `words.json` list and alignment metadata for a recorded run."""
    run_path = Path(run_dir).resolve()
    if script is None:
        script = td_script.load_script(str(run_path))

    if steps_data is None:
        steps_path = run_path / "rec" / "steps.json"
        if not steps_path.is_file():
            raise FileNotFoundError(f"Recording steps not found: {steps_path}")
        steps_data = json.loads(steps_path.read_text(encoding="utf-8"))

    rec_start = float(steps_data.get("rec_start_monotonic") or 0.0)
    if rec_start == 0.0:
        start_json = run_path / "rec" / "start.json"
        if start_json.is_file():
            rec_start = float(json.loads(start_json.read_text(encoding="utf-8")).get("monotonic_time", 0.0))

    lang_cfg = str(script.get("lang") or "darija").strip().lower()
    whisper_lang = "ar" if lang_cfg in ("darija", "ar", "arabic") else (None if lang_cfg == "auto" else lang_cfg)

    step_meta_by_id = {
        str(s["id"]): s for s in (steps_data.get("steps") or []) if isinstance(s, dict) and s.get("id")
    }

    batch_items: list[dict[str, Any]] = []
    step_timings: list[tuple[dict[str, Any], float, float, Path]] = []

    for step in script.get("steps") or []:
        sid = str(step["id"])
        rec_step = step_meta_by_id.get(sid)
        if rec_step is None:
            raise ValueError(f"Step {sid!r} missing from rec/steps.json")

        wav_path = run_path / "voice" / f"{sid}.wav"
        raw_vs = float(rec_step["voice_start"])
        raw_ve = float(rec_step["voice_end"])
        # Support both raw monotonic timestamps (voice_start >= rec_start) and already-relative timestamps
        if rec_start > 0.0 and raw_vs >= rec_start - 1e-6 and not steps_data.get("times_relative"):
            vs = max(0.0, raw_vs - rec_start)
            ve = max(vs, raw_ve - rec_start)
        else:
            vs = max(0.0, raw_vs)
            ve = max(vs, raw_ve)

        if ve <= vs and wav_path.is_file():
            ve = vs + wav_duration(str(wav_path))

        step_timings.append((step, vs, ve, wav_path))
        if wav_path.is_file():
            batch_items.append(
                {
                    "id": sid,
                    "wav": str(wav_path),
                    "initial_prompt": str(step.get("say") or ""),
                    "language": whisper_lang,
                }
            )

    asr_by_id: dict[str, list[tuple[str, float, float]]] = {}
    whisper_err: str | None = None
    if use_whisper and batch_items:
        fn = transcribe_fn or (lambda items: transcribe_steps_whisper(items, model=model))
        asr_by_id, whisper_err = fn(batch_items)
        if whisper_err:
            print(f"words_align: falling back to proportional timing ({whisper_err})", file=sys.stderr)

    all_words: list[dict[str, Any]] = []
    step_methods: dict[str, str] = {}
    for step, vs, ve, _wav_path in step_timings:
        sid = str(step["id"])
        say = str(step.get("say") or "")
        aligned, method = align_step_words(say, asr_by_id.get(sid), vs, ve)
        step_methods[sid] = method
        all_words.extend(aligned)

    final_words = enforce_monotonic(all_words)
    used_methods = set(step_methods.values())
    overall_method = (
        "faster-whisper+difflib"
        if "difflib" in used_methods and len(used_methods) == 1
        else ("mixed" if "difflib" in used_methods else "proportional")
    )
    meta = {
        "source": "script",
        "method": overall_method,
        "whisper_error": whisper_err,
        "step_methods": step_methods,
        "word_count": len(final_words),
    }
    return final_words, meta


def write_words(path: str | Path, words: list[dict[str, Any]]) -> Path:
    """Atomically write editor-v2 compatible words.json array."""
    out_path = Path(path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(words, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return out_path


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Align script words to TTS voice clips for editor-v2 words.json")
    ap.add_argument("run", help="Run name under $TD_HOME/runs/<name> or path to run dir")
    ap.add_argument("--out", default=None, help="Output JSON path (default: <run>/handoff/words.json)")
    ap.add_argument("--model", default=None, help="Override EV2_WHISPER_MODEL")
    ap.add_argument("--no-whisper", action="store_true", help="Skip faster-whisper and use proportional timing")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_dir = td_script.resolve_run(args.run)
    words, meta = align_words(run_dir, use_whisper=not args.no_whisper, model=args.model)
    out_path = args.out or os.path.join(run_dir, "handoff", "words.json")
    write_words(out_path, words)
    print(f"words_align: {len(words)} words ({meta['method']}, source={meta['source']}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
