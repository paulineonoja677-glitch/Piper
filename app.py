"""
Piper TTS server for Render's free tier.

- GET  /health  -> {"status": "ok"}
- GET  /voices  -> list of known voices + which are downloaded/loaded
- POST /tts     -> {"text": "...", "voice": "en_US-lessac-medium"} -> WAV audio

Designed to be light on memory: voices are downloaded lazily (except the
default voice, which is fetched on startup) and loaded models are cached
in-process so repeat requests are fast without re-reading the .onnx file.
"""

import io
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Dict

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from piper import PiperVoice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("piper-server")

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

MODEL_DIR = Path(os.environ.get("PIPER_MODEL_DIR", "/app/voices"))
DEFAULT_VOICE = os.environ.get("PIPER_DEFAULT_VOICE", "en_US-lessac-medium")
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Registry of known voices -> their path under the piper-voices HF repo.
# Add more entries here to make additional voices selectable; only
# DEFAULT_VOICE is downloaded automatically at startup. Others are
# downloaded lazily on first request.
VOICES: Dict[str, str] = {
    "en_US-lessac-medium": "en/en_US/lessac/medium/en_US-lessac-medium",
    "en_US-amy-medium": "en/en_US/amy/medium/en_US-amy-medium",
    "en_US-ryan-high": "en/en_US/ryan/high/en_US-ryan-high",
    "en_GB-alan-medium": "en/en_GB/alan/medium/en_GB-alan-medium",
}

MAX_TEXT_LENGTH = int(os.environ.get("PIPER_MAX_TEXT_LENGTH", "2000"))

# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = FastAPI(title="Piper TTS Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_loaded_voices: Dict[str, PiperVoice] = {}
_load_lock = threading.Lock()


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    voice: str = Field(default=DEFAULT_VOICE)


# --------------------------------------------------------------------------
# Voice download / load helpers
# --------------------------------------------------------------------------

def _voice_paths(voice: str) -> tuple[Path, Path]:
    model_path = MODEL_DIR / f"{voice}.onnx"
    config_path = MODEL_DIR / f"{voice}.onnx.json"
    return model_path, config_path


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading %s -> %s", url, dest)
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    tmp.rename(dest)


def ensure_voice_downloaded(voice: str) -> tuple[Path, Path]:
    if voice not in VOICES:
        raise HTTPException(status_code=404, detail=f"Unknown voice '{voice}'. See /voices.")

    model_path, config_path = _voice_paths(voice)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    hf_path = VOICES[voice]
    if not model_path.exists():
        _download(f"{HF_BASE}/{hf_path}.onnx", model_path)
    if not config_path.exists():
        _download(f"{HF_BASE}/{hf_path}.onnx.json", config_path)

    return model_path, config_path


def get_voice(voice: str) -> PiperVoice:
    if voice in _loaded_voices:
        return _loaded_voices[voice]

    with _load_lock:
        # Re-check inside the lock in case another request loaded it first.
        if voice in _loaded_voices:
            return _loaded_voices[voice]

        model_path, config_path = ensure_voice_downloaded(voice)
        logger.info("Loading voice '%s' into memory", voice)
        piper_voice = PiperVoice.load(str(model_path), config_path=str(config_path))
        _loaded_voices[voice] = piper_voice
        return piper_voice


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------

@app.on_event("startup")
def on_startup() -> None:
    try:
        ensure_voice_downloaded(DEFAULT_VOICE)
        logger.info("Default voice '%s' is ready on disk.", DEFAULT_VOICE)
    except Exception:
        # Don't crash the whole server if the download fails at boot (e.g.
        # transient network hiccup) - /tts will retry the download lazily.
        logger.exception("Failed to pre-download default voice '%s'", DEFAULT_VOICE)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/voices")
def list_voices():
    voices = []
    for name in VOICES:
        model_path, config_path = _voice_paths(name)
        voices.append(
            {
                "name": name,
                "downloaded": model_path.exists() and config_path.exists(),
                "loaded": name in _loaded_voices,
                "default": name == DEFAULT_VOICE,
            }
        )
    return {"voices": voices}


@app.post("/tts")
def tts(req: TTSRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="'text' must not be empty.")

    piper_voice = get_voice(req.voice)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        piper_voice.synthesize(text, wav_file)

    audio_bytes = buffer.getvalue()
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="speech.wav"'},
    )
