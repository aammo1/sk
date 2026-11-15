#!/usr/bin/env python3
"""tts/base.py — Shared TTS interface, text overrides, and ffmpeg audio normalization."""

from __future__ import annotations

import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

VALID_ENGINES = ("golha", "lahgtna")

TARGET_SR = 48000
TARGET_CHANNELS = 2
TARGET_CODEC = "pcm_s24le"
SPEED_MIN = 0.8
SPEED_MAX = 1.25

_MODEL_DIRS = {
    "golha": "golha-darija-tts",
    "lahgtna": "lahgtna-omnivoice-v2",
}


class TTSError(RuntimeError):
    """Actionable error raised when a TTS engine is misconfigured or fails."""


def skill_dir() -> Path:
    """Return the root tutorial-director skill directory."""
    return Path(__file__).resolve().parent.parent.parent


def td_home() -> str:
    """Return TD_HOME (default ~/tutorial-director)."""
    return os.path.abspath(os.path.expanduser(os.environ.get("TD_HOME") or "~/tutorial-director"))


def td_cache() -> str:
    """Return TD_CACHE (default ~/.cache/tutorial-director)."""
    return os.path.abspath(os.path.expanduser(os.environ.get("TD_CACHE") or "~/.cache/tutorial-director"))


def td_models() -> str:
    """Return TD_MODELS (default ~/Models)."""
    return os.path.abspath(os.path.expanduser(os.environ.get("TD_MODELS") or "~/Models"))


def venv_dir(engine: str) -> str:
    """Return per-engine virtualenv directory under ~/.cache/tutorial-director/venvs/<engine>."""
    if engine not in VALID_ENGINES:
        raise ValueError(f"Unknown TTS engine {engine!r} (valid: {', '.join(VALID_ENGINES)})")
    return os.path.join(td_cache(), "venvs", engine)


def venv_python(engine: str) -> str:
    """Return path to the Python interpreter inside the engine's dedicated venv."""
    return os.path.join(venv_dir(engine), "bin", "python")


def model_dir(engine: str) -> str:
    """Return expected local model directory for an engine under TD_MODELS."""
    if engine not in _MODEL_DIRS:
        raise ValueError(f"Unknown TTS engine {engine!r} (valid: {', '.join(VALID_ENGINES)})")
    return os.path.join(td_models(), _MODEL_DIRS[engine])


def setup_command(engine: str) -> str:
    """Return the exact shell command to set up an engine's virtualenv."""
    setup_sh = skill_dir() / "scripts" / "tts" / "setup.sh"
    return f"bash {setup_sh} {engine}"


def pronounce_path() -> str:
    """Return path to pronounce.json (TD_PRONOUNCE_PATH or ~/.config/tutorial-director/pronounce.json)."""
    override = os.environ.get("TD_PRONOUNCE_PATH")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    cfg_root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(cfg_root, "tutorial-director", "pronounce.json")


def load_pronounce_overrides(engine: str, path: str | None = None) -> dict[str, str]:
    """Load per-engine pronunciation overrides from pronounce.json.

    Supports both per-engine format:
        {"lahgtna": {"Omarchy": "أومارشي"}, "golha": {}}
    and flat word-map format:
        {"Omarchy": "أومارشي"}
    """
    cfg_path = path or pronounce_path()
    if not os.path.isfile(cfg_path):
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise TTSError(f"Failed to parse {cfg_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise TTSError(f"{cfg_path}: expected top-level JSON object")

    merged: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and k not in VALID_ENGINES:
            merged[k] = v

    engine_section = data.get(engine)
    if isinstance(engine_section, dict):
        for k, v in engine_section.items():
            if isinstance(k, str) and isinstance(v, str):
                merged[k] = v
    return merged


def apply_pronounce(text: str, engine: str, overrides: dict[str, str] | None = None) -> str:
    """Apply pronunciation word/phrase overrides for the target engine."""
    mapping = load_pronounce_overrides(engine) if overrides is None else overrides
    if not mapping or not text:
        return text

    out = text
    # Longest keys first so multi-word phrases like "Omarchy menu" beat "Omarchy".
    for src in sorted(mapping.keys(), key=len, reverse=True):
        if not src:
            continue
        dst = mapping[src]
        prefix = r"(?<![A-Za-z0-9_])" if re.match(r"^[A-Za-z0-9_]", src) else ""
        suffix = r"(?![A-Za-z0-9_])" if re.search(r"[A-Za-z0-9_]$", src) else ""
        flags = re.IGNORECASE if src.isascii() else 0
        out = re.sub(f"{prefix}{re.escape(src)}{suffix}", lambda _m, d=dst: d, out, flags=flags)
    return out


def clamp_speed(speed: Any, engine: str = "tts") -> float:
    """Clamp voice.speed to the supported atempo range [0.8, 1.25]."""
    if speed is None:
        return 1.0
    try:
        val = float(speed)
    except (TypeError, ValueError) as exc:
        raise TTSError(f"Invalid voice.speed {speed!r}: must be a number") from exc
    if val < SPEED_MIN or val > SPEED_MAX:
        clamped = max(SPEED_MIN, min(SPEED_MAX, val))
        print(
            f"[{engine}] note: clamping voice.speed {val:.2f} to [{SPEED_MIN}, {SPEED_MAX}] -> {clamped:.2f}",
            file=sys.stderr,
        )
        return clamped
    return val


def wav_duration(path: str) -> float:
    """Return WAV duration in seconds using stdlib wave with ffprobe fallback."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            frames = w.getnframes()
            if rate > 0:
                return frames / float(rate)
    except (wave.Error, OSError):
        pass

    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0 or not res.stdout.strip():
        raise TTSError(f"Failed to probe audio duration for {path}: {res.stderr.strip()}")
    return float(res.stdout.strip())


def probe_wav(path: str) -> dict[str, Any]:
    """Return basic WAV stream metadata via ffprobe."""
    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,bits_per_sample:format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise TTSError(f"ffprobe failed on {path}: {res.stderr.strip()}")
    data = json.loads(res.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    return {
        "codec_name": stream.get("codec_name"),
        "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
        "bits_per_sample": int(stream["bits_per_sample"]) if stream.get("bits_per_sample") else None,
        "duration": float(fmt["duration"]) if fmt.get("duration") else wav_duration(path),
    }


def _run_ffmpeg_norm(raw_wav: str, tmp_out: str, af: str) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        raw_wav,
        "-af",
        af,
        "-ar",
        str(TARGET_SR),
        "-ac",
        str(TARGET_CHANNELS),
        "-c:a",
        TARGET_CODEC,
        tmp_out,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise TTSError(f"ffmpeg audio normalization failed: {res.stderr.strip()}")


def normalize_wav(raw_wav: str, out_wav: str, speed: float = 1.0) -> float:
    """Normalize raw TTS audio to 48 kHz, 24-bit stereo WAV, ~-20 LUFS, <= 80 ms edge silence.

    Returns the final duration in seconds.
    """
    if not os.path.isfile(raw_wav) or os.path.getsize(raw_wav) == 0:
        raise TTSError(f"Raw TTS output missing or empty: {raw_wav}")

    spd = clamp_speed(speed)
    out_abs = os.path.abspath(out_wav)
    out_dir = os.path.dirname(out_abs)
    os.makedirs(out_dir, exist_ok=True)

    chain: list[str] = []
    if abs(spd - 1.0) > 1e-4:
        chain.append(f"atempo={spd:.4f}")
    chain.extend(
        [
            f"aresample={TARGET_SR}",
            "aformat=channel_layouts=stereo",
            "loudnorm=I=-20:TP=-1.5:LRA=11",
            f"aresample={TARGET_SR}",
        ]
    )
    base_af = ",".join(chain)
    # 50 ms kept after -45 dB crossing yields ~40 ms actual edge silence (strictly <= 80 ms).
    trim_af = (
        "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-45dB:start_silence=0.05,"
        "areverse,"
        "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-45dB:start_silence=0.05,"
        "areverse"
    )

    fd, tmp_out = tempfile.mkstemp(prefix=".norm_", suffix=".wav", dir=out_dir)
    os.close(fd)
    try:
        _run_ffmpeg_norm(raw_wav, tmp_out, f"{base_af},{trim_af}")
        dur = wav_duration(tmp_out)
        if dur <= 0.001:
            # Fallback if silenceremove stripped an ultra-quiet clip completely.
            _run_ffmpeg_norm(raw_wav, tmp_out, base_af)
            dur = wav_duration(tmp_out)
            if dur <= 0.001:
                raise TTSError(f"TTS audio contained no audible signal: {raw_wav}")
        os.replace(tmp_out, out_abs)
        return dur
    finally:
        if os.path.exists(tmp_out):
            try:
                os.unlink(tmp_out)
            except OSError:
                pass


def concat_wavs(wav_blobs: list[bytes], out_wav: str) -> None:
    """Concatenate one or more WAV byte payloads into a single WAV file."""
    if not wav_blobs:
        raise TTSError("No audio chunks to concatenate")
    if len(wav_blobs) == 1:
        with open(out_wav, "wb") as f:
            f.write(wav_blobs[0])
        return

    params: tuple[int, int, int] | None = None
    frames: list[bytes] = []
    compatible = True
    for blob in wav_blobs:
        try:
            with wave.open(io.BytesIO(blob), "rb") as w:
                cur = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                if params is None:
                    params = cur
                elif cur != params:
                    compatible = False
                    break
                frames.append(w.readframes(w.getnframes()))
        except wave.Error:
            compatible = False
            break

    if compatible and params is not None:
        nch, sw, sr = params
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(nch)
            w.setsampwidth(sw)
            w.setframerate(sr)
            w.writeframes(b"".join(frames))
        return

    # Fallback: let ffmpeg concat heterogeneous formats cleanly.
    with tempfile.TemporaryDirectory(prefix="td_concat_") as td:
        list_path = os.path.join(td, "list.txt")
        with open(list_path, "w", encoding="utf-8") as lf:
            for idx, blob in enumerate(wav_blobs):
                part_path = os.path.join(td, f"p{idx}.wav")
                with open(part_path, "wb") as pf:
                    pf.write(blob)
                lf.write(f"file '{part_path}'\n")
        res = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_wav],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise TTSError(f"ffmpeg concat failed: {res.stderr.strip()}")


def get_backend(engine: str):
    """Import and return the backend module for `engine` ('golha' or 'lahgtna')."""
    if engine not in VALID_ENGINES:
        raise TTSError(f"Unsupported TTS engine {engine!r} (valid: {', '.join(VALID_ENGINES)})")
    return importlib.import_module(f"tts.{engine}")


def synth(text: str, out_wav: str, voice: dict[str, Any] | None = None) -> float:
    """Synthesize `text` to normalized `out_wav` using `voice['engine']` and return duration in seconds."""
    v = dict(voice or {})
    engine = v.get("engine") or "golha"
    backend = get_backend(engine)
    return backend.synth(text, out_wav, v)


def synth_batch(items: list[dict[str, Any]], voice: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Synthesize multiple `{id, text, out_wav}` items, reusing model/server across the batch."""
    v = dict(voice or {})
    engine = v.get("engine") or "golha"
    backend = get_backend(engine)
    return backend.synth_batch(items, v)
