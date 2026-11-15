#!/usr/bin/env python3
"""tts/golha.py — Golha Darija+French TTS backend (resident FastAPI server on port 8020)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from tts.base import (
    TTSError,
    apply_pronounce,
    concat_wavs,
    model_dir,
    normalize_wav,
    setup_command,
    td_cache,
    venv_python,
)

DEFAULT_URL = "http://127.0.0.1:8020"
REQUIRED_BASE_FILES = ("ve.pt", "s3gen.pt", "conds.pt", "t3_mtl23ls_v2.safetensors")


def server_url() -> str:
    """Return configured Golha TTS server URL."""
    return (os.environ.get("TD_GOLHA_URL") or DEFAULT_URL).rstrip("/")


def _http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _http_bytes(url: str, payload: dict[str, Any], timeout: float = 120.0) -> bytes:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _probe_health(base_url: str) -> dict[str, Any] | None:
    try:
        data = _http_json(f"{base_url}/health", timeout=2.0)
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _pid_alive(pid_file: str) -> int | None:
    if not os.path.isfile(pid_file):
        return None
    try:
        with open(pid_file, "r", encoding="utf-8") as pf:
            pid = int(pf.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _tail_log(log_file: str, lines: int = 20) -> str:
    if not os.path.isfile(log_file):
        return ""
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-lines:]
        return "".join(tail).strip()
    except OSError:
        return ""


def _check_prereqs() -> tuple[str, str]:
    mdir = model_dir("golha")
    if not os.path.isdir(mdir) or not os.path.isfile(os.path.join(mdir, "tts_server.py")):
        raise TTSError(
            f"Golha model repo not found at {mdir}. "
            f"Clone Oussamamaat/golha-darija-tts there or set TD_MODELS."
        )
    if not os.path.isfile(os.path.join(mdir, "adapter_config.json")):
        raise TTSError(f"Golha adapter_config.json missing in {mdir}.")

    py = venv_python("golha")
    if not os.path.isfile(py) or not os.access(py, os.X_OK):
        raise TTSError(f"Golha virtualenv not installed ({py}). Fix: {setup_command('golha')}")

    pdir = os.path.join(mdir, "pretrained_models")
    missing_base = [name for name in REQUIRED_BASE_FILES if not os.path.isfile(os.path.join(pdir, name))]
    if missing_base:
        fetch_script = os.path.join(mdir, "fetch_base_model.py")
        raise TTSError(
            f"Golha base model incomplete in {pdir} (missing: {', '.join(missing_base)}). "
            f"Fix: {py} {fetch_script}"
        )
    return mdir, py


def ensure_server() -> str:
    """Ensure the Golha HTTP server is running and ready; return its base URL."""
    base_url = server_url()
    health = _probe_health(base_url)
    if health and health.get("ready"):
        return base_url

    mdir, py = _check_prereqs()
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8020
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise TTSError(f"Remote Golha server {base_url} is not reachable (/health failed)")

    cache_dir = td_cache()
    os.makedirs(cache_dir, exist_ok=True)
    log_file = os.path.join(cache_dir, "golha-server.log")
    pid_file = os.path.join(cache_dir, "golha-server.pid")

    proc: subprocess.Popen[bytes] | None = None
    existing_pid = _pid_alive(pid_file)
    if existing_pid is None:
        print(f"[golha] starting tts_server.py on {base_url} (first load takes ~1-2 min)...", file=sys.stderr)
        log_fh = open(log_file, "ab")
        try:
            proc = subprocess.Popen(
                [py, os.path.join(mdir, "tts_server.py"), "--host", host, "--port", str(port)],
                cwd=mdir,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_fh.close()
        with open(pid_file, "w", encoding="utf-8") as pf:
            pf.write(f"{proc.pid}\n")
    else:
        print(f"[golha] waiting for starting tts_server.py (pid {existing_pid})...", file=sys.stderr)

    timeout_s = int(os.environ.get("TD_GOLHA_START_TIMEOUT") or "240")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        health = _probe_health(base_url)
        if health and health.get("ready"):
            return base_url
        if proc is not None and proc.poll() is not None:
            tail = _tail_log(log_file)
            raise TTSError(
                f"Golha tts_server.py exited during startup (code {proc.returncode}).\n"
                f"Log ({log_file}):\n{tail}\n"
                f"Fix: {setup_command('golha')}"
            )
        time.sleep(1.0)

    tail = _tail_log(log_file)
    raise TTSError(
        f"Timed out after {timeout_s}s waiting for Golha server at {base_url}.\n"
        f"Log ({log_file}):\n{tail}"
    )


def _synth_one_raw(base_url: str, text: str, voice: dict[str, Any], raw_wav: str) -> float:
    t0 = time.perf_counter()
    try:
        prep = _http_json(
            f"{base_url}/prepare",
            {
                "text": text,
                "split_sentences": True,
                "tag_french": True,
                "normalize_numbers": True,
            },
            timeout=15.0,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise TTSError(f"Golha /prepare request failed: {exc}") from exc

    parts = prep.get("parts") or []
    if not parts:
        raise TTSError(f"Golha /prepare returned no parts for text: {text!r}")

    blobs: list[bytes] = []
    for part in parts:
        payload = {
            "text": part["text"],
            "language_id": part.get("language_id", "ar"),
            "temperature": float(voice.get("temperature", 0.8)),
            "cfg_weight": float(voice.get("cfg_weight", 0.5)),
            "exaggeration": float(voice.get("exaggeration", 0.5)),
            "repetition_penalty": float(voice.get("repetition_penalty", 2.0)),
        }
        try:
            blobs.append(_http_bytes(f"{base_url}/synth", payload, timeout=120.0))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TTSError(f"Golha /synth returned HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TTSError(f"Golha /synth request failed: {exc}") from exc

    gen_s = time.perf_counter() - t0
    concat_wavs(blobs, raw_wav)
    return gen_s


def _note_ignored_ref(voice: dict[str, Any]) -> None:
    ref = voice.get("ref")
    if ref:
        print(
            f"[golha] note: ignoring voice.ref ({ref!r}) — golha uses its built-in Darija voice",
            file=sys.stderr,
        )


def synth_batch(items: list[dict[str, Any]], voice: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Synthesize a batch of `{id, text, out_wav}` items via Golha and normalize each WAV."""
    if not items:
        return []
    v = dict(voice or {})
    _note_ignored_ref(v)
    base_url = ensure_server()
    speed = v.get("speed", 1.0)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="td_golha_") as td:
        for idx, item in enumerate(items):
            sid = str(item.get("id", idx))
            out_wav = str(item["out_wav"])
            raw_wav = os.path.join(td, f"raw_{idx}.wav")
            prep_text = apply_pronounce(str(item["text"]), "golha")
            gen_s = _synth_one_raw(base_url, prep_text, v, raw_wav)
            dur = normalize_wav(raw_wav, out_wav, speed=speed)
            results.append(
                {
                    "id": sid,
                    "out_wav": out_wav,
                    "dur": dur,
                    "gen_seconds": gen_s,
                }
            )
    return results


def synth(text: str, out_wav: str, voice: dict[str, Any] | None = None) -> float:
    """Synthesize `text` to normalized `out_wav` via Golha and return duration in seconds."""
    res = synth_batch([{"id": "0", "text": text, "out_wav": out_wav}], voice=voice)
    return float(res[0]["dur"])
