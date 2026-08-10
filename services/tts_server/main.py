"""
TTS Server — Fun-CosyVoice3-0.5B-2512
Exposes an OpenAI-compatible /v1/audio/speech endpoint so that
Dograh (and any other OpenAI-compatible client) can use it as a drop-in
Text-to-Speech provider.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8002

Prerequisites:
    The CosyVoice library must be installed first (see README.md / setup_cosyvoice.ps1).
    This server assumes CosyVoice is importable from the Python environment.
"""

import io
import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional, Literal

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tts_server")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # AIVoiceCallAgent/
MODEL_PATH = BASE_DIR / "models" / "Fun-CosyVoice3-0.5B-2512"

# CosyVoice repo may be cloned into services/tts_server/CosyVoice
COSYVOICE_REPO = Path(__file__).parent / "CosyVoice"
if COSYVOICE_REPO.exists():
    sys.path.insert(0, str(COSYVOICE_REPO))

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="CosyVoice3 TTS Server",
    description="OpenAI-compatible Text-to-Speech using Fun-CosyVoice3 running locally.",
    version="1.0.0",
)

# ── Global model state ────────────────────────────────────────────────────────
cosyvoice = None
SAMPLE_RATE = 24_000  # CosyVoice3 always outputs 24 kHz

# Voice-to-speaker mapping (SFT built-in voices from CosyVoice3)
# Dograh sends standard OpenAI voice names; we map them to CosyVoice roles.
VOICE_MAP: dict[str, str] = {
    "alloy":   "中文女",
    "echo":    "中文男",
    "fable":   "英文女",
    "onyx":    "英文男",
    "nova":    "粤语女",
    "shimmer": "韩语女",
}


@app.on_event("startup")
async def load_model():
    """Load CosyVoice3 model at startup."""
    global cosyvoice

    log.info("Loading Fun-CosyVoice3-0.5B-2512 from %s …", MODEL_PATH)
    t0 = time.time()

    try:
        from cosyvoice.cli.cosyvoice import CosyVoice3
        cosyvoice = CosyVoice3(str(MODEL_PATH), load_trt=False, fp16=False)
        log.info("Model loaded in %.1f s", time.time() - t0)
        spks = cosyvoice.list_available_spks()
        log.info("Available built-in speakers: %s", spks)
    except ImportError as exc:
        log.error(
            "CosyVoice library not found: %s\n"
            "Run setup_cosyvoice.ps1 to install it, then restart this server.",
            exc,
        )
    except Exception as exc:
        log.exception("Failed to load CosyVoice3 model: %s", exc)


# ── Request / Response models ─────────────────────────────────────────────────

class SpeechRequest(BaseModel):
    model: str = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    input: str
    voice: str = "alloy"
    response_format: Literal["mp3", "wav", "pcm", "opus", "aac", "flac"] = "wav"
    speed: float = 1.0


# ── Helper ────────────────────────────────────────────────────────────────────

def _tensor_to_wav_bytes(audio_tensor: torch.Tensor, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convert a 1-D or 2-D float tensor to WAV bytes."""
    if audio_tensor.dim() == 1:
        audio_tensor = audio_tensor.unsqueeze(0)
    buf = io.BytesIO()
    torchaudio.save(buf, audio_tensor.cpu(), sample_rate, format="wav")
    buf.seek(0)
    return buf.read()


def _speaker_from_voice(voice: str) -> str:
    """Map an OpenAI voice name to a CosyVoice3 SFT role."""
    return VOICE_MAP.get(voice, VOICE_MAP["alloy"])


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": cosyvoice is not None}


@app.get("/v1/voices")
async def list_voices():
    """List available built-in voices (non-standard but helpful for debugging)."""
    if cosyvoice is None:
        raise HTTPException(status_code=503, detail="Model not loaded.")
    return {"voices": cosyvoice.list_available_spks(), "voice_map": VOICE_MAP}


@app.post("/v1/audio/speech")
async def synthesize(req: SpeechRequest):
    """
    OpenAI-compatible TTS endpoint.
    Uses SFT mode (built-in speaker) by default.
    Returns: audio bytes (WAV format).
    """
    if cosyvoice is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet. Retry in a few seconds.")

    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="'input' text is required.")

    speaker = _speaker_from_voice(req.voice)
    t0 = time.time()

    log.info("TTS request: %d chars, voice=%s → speaker=%s", len(req.input), req.voice, speaker)

    try:
        # Use streaming inference for lower latency
        audio_chunks: list[torch.Tensor] = []
        for result in cosyvoice.inference_sft(
            tts_text=req.input,
            spk_id=speaker,
            stream=False,
        ):
            audio_chunks.append(result["tts_speech"])

        if not audio_chunks:
            raise RuntimeError("No audio generated.")

        # Concatenate all chunks
        full_audio = torch.cat(audio_chunks, dim=-1)

        elapsed = time.time() - t0
        duration = full_audio.shape[-1] / SAMPLE_RATE
        log.info("Synthesized %.1fs audio in %.2fs (RTF=%.2f)", duration, elapsed, elapsed / max(duration, 1e-6))

        wav_bytes = _tensor_to_wav_bytes(full_audio, SAMPLE_RATE)

        return StreamingResponse(
            io.BytesIO(wav_bytes),
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=speech.wav",
                "X-Synthesis-Duration": f"{duration:.3f}",
                "X-Inference-Time": f"{elapsed:.3f}",
            },
        )

    except Exception as exc:
        log.exception("TTS inference failed")
        raise HTTPException(status_code=500, detail=f"TTS inference error: {exc}") from exc


# ── Dev server ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002, log_level="info", reload=False)
