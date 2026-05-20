"""Voice in/out via vibevoice.cpp.

vibevoice.cpp ships a single binary (`vibevoice-cli`) that does both TTS
and STT against GGUF models. It has no HTTP server — we drive it as a
subprocess and read its WAV output / stdout transcript.

Environment:
  AGUI_VOICE_CLI        absolute path to the `vibevoice-cli` binary
  AGUI_VOICE_MODEL      path to the GGUF model
  AGUI_VOICE_TOKENIZER  path to the tokenizer GGUF
  AGUI_VOICE_REF_AUDIO  optional .wav reference for voice cloning (1.5B model)
  AGUI_VOICE_VOICE      optional preset name (realtime-0.5B model)

If `AGUI_VOICE_CLI` is unset OR the binary is missing, every call raises
`VoiceUnavailable` with a clear message. The tools / endpoints surface
that as a 503-ish error so the UI can disable mic buttons gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


log = logging.getLogger("huxform.voice")


class VoiceUnavailable(RuntimeError):
    """vibevoice.cpp is not installed / not configured on this host."""


@dataclass
class VoiceConfig:
    cli: str | None
    model: str | None
    tokenizer: str | None
    ref_audio: str | None = None
    voice: str | None = None
    sample_rate: int = 24_000

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        return cls(
            cli=os.environ.get("AGUI_VOICE_CLI") or None,
            model=os.environ.get("AGUI_VOICE_MODEL") or None,
            tokenizer=os.environ.get("AGUI_VOICE_TOKENIZER") or None,
            ref_audio=os.environ.get("AGUI_VOICE_REF_AUDIO") or None,
            voice=os.environ.get("AGUI_VOICE_VOICE") or None,
        )

    def is_ready(self) -> tuple[bool, str | None]:
        if not self.cli:
            return False, "AGUI_VOICE_CLI is not set"
        if not shutil.which(self.cli) and not Path(self.cli).is_file():
            return False, f"vibevoice-cli not found at {self.cli!r}"
        if not self.model:
            return False, "AGUI_VOICE_MODEL is not set"
        if not Path(self.model).is_file():
            return False, f"model file not found: {self.model!r}"
        if self.tokenizer and not Path(self.tokenizer).is_file():
            return False, f"tokenizer file not found: {self.tokenizer!r}"
        return True, None


class VoiceEngine:
    """Async wrapper around the vibevoice-cli subprocess.

    Methods raise `VoiceUnavailable` if the host isn't configured. They
    are subprocess-bound, so heavy synth blocks the worker thread that
    asyncio's subprocess transport runs them in — call from a background
    task if you don't want to stall the FastAPI event loop.
    """

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config

    def _ensure_ready(self) -> None:
        ok, reason = self.config.is_ready()
        if not ok:
            raise VoiceUnavailable(reason or "voice is not configured")

    async def tts(self, text: str, *, voice: str | None = None) -> bytes:
        """Synthesize text → WAV bytes (mono, 24kHz)."""
        self._ensure_ready()
        text = (text or "").strip()
        if not text:
            raise ValueError("voice.tts: empty text")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_f:
            out_path = out_f.name
        try:
            cmd = [
                self.config.cli,  # type: ignore[list-item]
                "--model", self.config.model,  # type: ignore[list-item]
                "--text", text,
                "--out", out_path,
            ]
            if self.config.tokenizer:
                cmd += ["--tokenizer", self.config.tokenizer]
            chosen_voice = voice or self.config.voice
            if chosen_voice:
                cmd += ["--voice", chosen_voice]
            if self.config.ref_audio:
                cmd += ["--ref-audio", self.config.ref_audio]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = (stderr or b"").decode("utf-8", "replace").strip()
                raise RuntimeError(f"vibevoice-cli tts failed ({proc.returncode}): {err[:500]}")
            data = Path(out_path).read_bytes()
            if not data:
                raise RuntimeError("vibevoice-cli produced an empty WAV")
            return data
        finally:
            try:
                Path(out_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def stt(self, wav_path: str) -> str:
        """Transcribe a WAV (mono, 24kHz) → text.

        The CLI prints the transcript to stdout; we strip any header lines.
        Caller is responsible for re-sampling input audio to 24kHz mono.
        """
        self._ensure_ready()
        if not Path(wav_path).is_file():
            raise FileNotFoundError(wav_path)

        cmd = [
            self.config.cli,  # type: ignore[list-item]
            "--model", self.config.model,  # type: ignore[list-item]
            "--audio", wav_path,
        ]
        if self.config.tokenizer:
            cmd += ["--tokenizer", self.config.tokenizer]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"vibevoice-cli stt failed ({proc.returncode}): {err[:500]}")
        text = (stdout or b"").decode("utf-8", "replace").strip()
        # CLI prefixes some progress lines; keep the longest text line as the
        # transcript heuristic (the actual transcript is typically the last
        # non-empty line).
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return ""
        # Drop obvious progress lines
        candidates = [ln for ln in lines if not ln.startswith(("[", "load:", "ggml_"))]
        return (candidates[-1] if candidates else lines[-1]).strip()


async def transcode_to_wav_24k_mono(in_bytes: bytes, in_suffix: str = ".webm") -> bytes:
    """Convert any browser-recorded blob (webm/ogg/mp4) → mono 24kHz WAV.

    Uses ffmpeg from PATH. Returns the WAV bytes. Raises RuntimeError if
    ffmpeg isn't available or the input can't be decoded.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not on PATH — install it or send WAV 24kHz mono directly")

    with tempfile.NamedTemporaryFile(suffix=in_suffix, delete=False) as in_f:
        in_path = in_f.name
        in_f.write(in_bytes)
    out_path = in_path + ".wav"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", in_path,
            "-ac", "1",
            "-ar", "24000",
            out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err[:500]}")
        return Path(out_path).read_bytes()
    finally:
        try:
            Path(in_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass
