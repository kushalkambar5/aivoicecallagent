"""
STT Server — Qwen3-ASR-1.7B
Exposes an OpenAI-compatible /v1/audio/transcriptions endpoint so that
Dograh (and any other OpenAI-compatible client) can use it as a drop-in
Speech-to-Text provider.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8001
"""

import io
import os
import time
import logging
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("stt_server")

# ── Model path (relative to this file so it works wherever the repo sits) ────
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # AIVoiceCallAgent/
MODEL_PATH = BASE_DIR / "models" / "Qwen3-ASR-1.7B"

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Qwen3-ASR-1.7B STT Server",
    description="OpenAI-compatible Speech-to-Text using Qwen3-ASR-1.7B running locally.",
    version="1.0.0",
)

# ── Global model state ────────────────────────────────────────────────────────
loaded_model = None
loaded_processor = None
loaded_device = None


@app.on_event("startup")
async def load_model():
    """Load Qwen3-ASR model at startup so inference is fast on first request."""
    global loaded_model, loaded_processor, loaded_device

    log.info("Loading Qwen3-ASR-1.7B from %s …", MODEL_PATH)
    t0 = time.time()

    # Lazy import — keeps startup error messages clean if torch not installed
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

    loaded_device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if loaded_device == "cuda" else torch.float32

    log.info("Using device: %s  |  dtype: %s", loaded_device, torch_dtype)

    loaded_processor = AutoProcessor.from_pretrained(str(MODEL_PATH), trust_remote_code=True)
    loaded_model = AutoModelForSpeechSeq2Seq.from_pretrained(
        str(MODEL_PATH),
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    ).to(loaded_device)

    loaded_model.eval()
    log.info("Model loaded in %.1f s", time.time() - t0)


# ── Helper ────────────────────────────────────────────────────────────────────

def _load_audio(data: bytes, filename: str) -> tuple[np.ndarray, int]:
    """Return (audio_array_float32, sample_rate) for any audio format."""
    try:
        buf = io.BytesIO(data)
        audio, sr = sf.read(buf, dtype="float32", always_2d=False)
        # Convert stereo → mono
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio, sr
    except Exception:
        # Fallback to librosa (handles more formats including MP3)
        import librosa
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".wav", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            audio, sr = librosa.load(tmp_path, sr=16_000, mono=True)
            return audio, sr
        finally:
            os.unlink(tmp_path)


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int = 16_000) -> np.ndarray:
    if orig_sr == target_sr:
        return audio
    import librosa
    return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": loaded_model is not None, "device": str(loaded_device)}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: Optional[str] = Form(default="Qwen/Qwen3-ASR-1.7B"),
    language: Optional[str] = Form(default=None),
    response_format: Optional[str] = Form(default="json"),
    temperature: Optional[float] = Form(default=0.0),
    prompt: Optional[str] = Form(default=None),
):
    """
    OpenAI-compatible transcription endpoint.
    Accepts: wav, mp3, mp4, m4a, webm, ogg, flac, opus
    Returns: {"text": "transcription here"}
    """
    # Reference module-level globals
    global loaded_model, loaded_processor, loaded_device

    if loaded_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet. Retry in a few seconds.")

    # Read audio bytes
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    t0 = time.time()

    try:
        audio_np, sr = _load_audio(audio_bytes, file.filename or "audio.wav")
        audio_np = _resample(audio_np, sr, 16_000)
    except Exception as exc:
        log.exception("Audio decode failed")
        raise HTTPException(status_code=422, detail=f"Audio decode error: {exc}") from exc

    # Build model inputs
    try:
        inputs = loaded_processor(
            audio_np,
            sampling_rate=16_000,
            return_tensors="pt",
        )
        inputs = {k: v.to(loaded_device) for k, v in inputs.items()}

        # Optionally provide language hint
        generate_kwargs: dict = {"max_new_tokens": 448}
        if language:
            # Qwen3-ASR supports language via forced_decoder_ids or language token
            try:
                forced_decoder_ids = loaded_processor.get_decoder_prompt_ids(language=language, task="transcribe")
                generate_kwargs["forced_decoder_ids"] = forced_decoder_ids
            except Exception:
                pass  # Ignore if language not supported

        with torch.no_grad():
            predicted_ids = loaded_model.generate(**inputs, **generate_kwargs)

        transcription = loaded_processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()
    except Exception as exc:
        log.exception("Inference failed")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc

    elapsed = time.time() - t0
    log.info("Transcribed %.1fs audio in %.2fs → %d chars", len(audio_np) / 16_000, elapsed, len(transcription))

    # OpenAI-compatible response
    if response_format == "text":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(transcription)

    return JSONResponse({
        "text": transcription,
        "model": "Qwen/Qwen3-ASR-1.7B",
        "duration": round(len(audio_np) / 16_000, 3),
    })


# ── Dev server ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, log_level="info", reload=False)
