#!/usr/bin/env python3
"""tts/lahgtna.py — Lahgtna-OmniVoice-v2 TTS backend (Moroccan Darija via dedicated venv worker)."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any

REQUIRED_MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json")


def _select_language(model: Any, requested: str | None) -> str | None:
    supported_ids: set[str] = set()
    if hasattr(model, "supported_language_ids"):
        try:
            supported_ids = set(model.supported_language_ids())
        except Exception:
            supported_ids = set()

    if requested is None or str(requested).strip().lower() in ("", "auto", "darija", "moroccan", "moroccan lahgtna"):
        if "ma" in supported_ids:
            return "ma"
        if "ary" in supported_ids:
            return "ary"
        return "Moroccan Lahgtna"
    return str(requested).strip()


def _extract_audio_array(audio: Any, np_mod: Any) -> Any:
    if isinstance(audio, dict) and "audio" in audio:
        audio = audio["audio"]
    if isinstance(audio, (list, tuple)):
        if not audio:
            raise RuntimeError("OmniVoice.generate() returned an empty list")
        audio = audio[0]
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    arr = np_mod.asarray(audio, dtype=np_mod.float32)
    arr = np_mod.squeeze(arr)
    if arr.ndim > 1:
        arr = arr[0] if arr.shape[0] <= 8 else arr[:, 0]
    return arr


def _run_worker() -> int:
    real_stdout = sys.stdout
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as exc:
        real_stdout.write(json.dumps({"ok": False, "error": f"Invalid worker JSON input: {exc}"}))
        return 1

    model_path = payload["model_dir"]
    voice = payload.get("voice") or {}
    items = payload.get("items") or []

    try:
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import soundfile as sf
            import torch

            try:
                from omnivoice import OmniVoice
            except ImportError as exc:
                raise RuntimeError(
                    f"omnivoice package not installed in lahgtna venv ({exc}). "
                    f"Re-run setup.sh lahgtna."
                ) from exc

            use_cuda = torch.cuda.is_available()
            device_map = os.environ.get("TD_LAHGTNA_DEVICE") or ("cuda:0" if use_cuda else "cpu")
            dtype_env = (os.environ.get("TD_LAHGTNA_DTYPE") or "").strip().lower()
            if dtype_env == "float32":
                dtype = torch.float32
            elif dtype_env == "bfloat16":
                dtype = torch.bfloat16
            elif dtype_env == "float16":
                dtype = torch.float16
            else:
                dtype = torch.float16 if use_cuda else torch.float32

            model = OmniVoice.from_pretrained(model_path, device_map=device_map, dtype=dtype)
            sr = int(getattr(model, "sampling_rate", None) or 24000)
            lang = _select_language(model, voice.get("language") or voice.get("dialect"))
            ref_audio = voice.get("ref")
            ref_text = voice.get("ref_text")
            instruct = voice.get("instruct")
            num_step = int(voice.get("num_step", 32))

            results = []
            for item in items:
                kwargs: dict[str, Any] = {
                    "text": item["text"],
                    "num_step": num_step,
                }
                if lang:
                    kwargs["language"] = lang
                if ref_audio:
                    kwargs["ref_audio"] = ref_audio
                    if ref_text:
                        kwargs["ref_text"] = ref_text
                elif instruct:
                    kwargs["instruct"] = instruct

                t0 = time.perf_counter()
                if use_cuda:
                    torch.cuda.synchronize()
                audio = model.generate(**kwargs)
                if use_cuda:
                    torch.cuda.synchronize()
                gen_s = time.perf_counter() - t0

                arr = _extract_audio_array(audio, np)
                sf.write(item["raw_wav"], arr, sr, subtype="PCM_16")
                results.append(
                    {
                        "id": item["id"],
                        "raw_wav": item["raw_wav"],
                        "raw_dur": float(len(arr) / sr) if sr > 0 else 0.0,
                        "gen_seconds": float(gen_s),
                        "sr": sr,
                    }
                )

        real_stdout.write(json.dumps({"ok": True, "results": results}, ensure_ascii=False))
        return 0
    except Exception as exc:
        real_stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


def _check_prereqs(voice: dict[str, Any]) -> tuple[str, str]:
    from tts.base import TTSError, model_dir, setup_command, venv_python

    mdir = model_dir("lahgtna")
    if not os.path.isdir(mdir):
        raise TTSError(
            f"Lahgtna model directory not found at {mdir}. "
            f"Download oddadmix/lahgtna-omnivoice-v2 there or set TD_MODELS."
        )
    missing = [f for f in REQUIRED_MODEL_FILES if not os.path.isfile(os.path.join(mdir, f))]
    if missing:
        raise TTSError(
            f"Lahgtna model directory {mdir} is incomplete (missing: {', '.join(missing)})."
        )

    py = venv_python("lahgtna")
    if not os.path.isfile(py) or not os.access(py, os.X_OK):
        raise TTSError(f"Lahgtna virtualenv not installed ({py}). Fix: {setup_command('lahgtna')}")

    ref = voice.get("ref")
    if ref:
        ref_abs = os.path.abspath(os.path.expanduser(str(ref)))
        if not os.path.isfile(ref_abs):
            raise TTSError(f"Lahgtna voice.ref audio file not found: {ref_abs}")
    return mdir, py


def synth_batch(items: list[dict[str, Any]], voice: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Synthesize a batch of `{id, text, out_wav}` items via a single lahgtna worker subprocess."""
    if not items:
        return []

    from tts.base import TTSError, apply_pronounce, normalize_wav, setup_command

    v = dict(voice or {})
    mdir, py = _check_prereqs(v)
    worker_voice = dict(v)
    if worker_voice.get("ref"):
        worker_voice["ref"] = os.path.abspath(os.path.expanduser(str(worker_voice["ref"])))

    speed = v.get("speed", 1.0)
    with tempfile.TemporaryDirectory(prefix="td_lahgtna_") as td:
        worker_items = []
        out_map: dict[str, str] = {}
        for idx, item in enumerate(items):
            sid = str(item.get("id", idx))
            raw_wav = os.path.join(td, f"raw_{idx}.wav")
            out_wav = str(item["out_wav"])
            out_map[sid] = out_wav
            worker_items.append(
                {
                    "id": sid,
                    "text": apply_pronounce(str(item["text"]), "lahgtna"),
                    "raw_wav": raw_wav,
                }
            )

        req = {
            "model_dir": mdir,
            "voice": worker_voice,
            "items": worker_items,
        }
        proc = subprocess.run(
            [py, os.path.abspath(__file__), "--worker"],
            input=json.dumps(req, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            resp = json.loads(proc.stdout or "{}")
        except ValueError as exc:
            raise TTSError(
                f"Lahgtna worker produced invalid JSON (exit {proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}\n"
                f"Fix: {setup_command('lahgtna')}"
            ) from exc

        if not resp.get("ok"):
            err = resp.get("error") or proc.stderr.strip() or f"worker exited {proc.returncode}"
            hint = f"\nFix: {setup_command('lahgtna')}" if "omnivoice" in err.lower() or "No module" in err else ""
            raise TTSError(f"Lahgtna synthesis failed: {err}{hint}")

        results: list[dict[str, Any]] = []
        for entry in resp.get("results") or []:
            sid = str(entry["id"])
            out_wav = out_map[sid]
            dur = normalize_wav(entry["raw_wav"], out_wav, speed=speed)
            results.append(
                {
                    "id": sid,
                    "out_wav": out_wav,
                    "dur": dur,
                    "gen_seconds": float(entry.get("gen_seconds", 0.0)),
                }
            )
        return results


def synth(text: str, out_wav: str, voice: dict[str, Any] | None = None) -> float:
    """Synthesize `text` to normalized `out_wav` via Lahgtna and return duration in seconds."""
    res = synth_batch([{"id": "0", "text": text, "out_wav": out_wav}], voice=voice)
    return float(res[0]["dur"])


if __name__ == "__main__":
    if "--worker" in sys.argv[1:]:
        raise SystemExit(_run_worker())
    print("Use td voice test|render or import tts.lahgtna", file=sys.stderr)
    raise SystemExit(2)
