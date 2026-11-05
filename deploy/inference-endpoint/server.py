"""Cadence inference endpoint.

One container serves ONE model family (MOSS-Music or Music Flamingo) because
their Transformers versions conflict and an A10G can only hold one 8B model.

Contract:
  GET  /health          -> 200 only when the model is ready
  POST /v1/annotate     -> multipart audio + prompt -> {text, model, usage, timings}
  GET  /v1/models       -> minimal metadata

The workbench's "cadence" adapter speaks this contract. Set:
  MODEL_FAMILY=moss | moss-thinking | flamingo
  MODEL_PATH=/repository
  MODEL_ID=...
  MAX_AUDIO_SECONDS=1200
  DRY_RUN=0
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    import torch
except ImportError:  # DRY_RUN mode can run without the GPU stack.
    torch = None  # type: ignore[assignment]
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cadence.endpoint")

MODEL_FAMILY = os.environ.get("MODEL_FAMILY", "moss").strip().lower()
MODEL_PATH = os.environ.get("MODEL_PATH", "/repository")
MODEL_ID = os.environ.get("MODEL_ID", MODEL_PATH)
MODEL_REVISION = os.environ.get("MODEL_REVISION", "")
MAX_AUDIO_SECONDS = int(os.environ.get("MAX_AUDIO_SECONDS", "1200"))
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "1024"))
DRY_RUN = os.environ.get("DRY_RUN", "0") in {"1", "true", "yes"}
DEVICE = os.environ.get(
    "DEVICE", "cuda:0" if torch is not None and torch.cuda.is_available() else "cpu"
)
if torch is not None and torch.cuda.is_available():
    DTYPE = torch.bfloat16 if os.environ.get("TORCH_DTYPE", "bfloat16") == "bfloat16" else torch.float16
else:
    DTYPE = None
LOAD_IN_4BIT = os.environ.get("LOAD_IN_4BIT", "0") in {"1", "true", "yes"}
SERVER_PORT = int(os.environ.get("PORT", "8000"))

_engine: dict[str, Any] = {}
_generate_lock = threading.Lock()


class AnnotateResponse(BaseModel):
    text: str
    model: str
    model_family: str
    revision: str
    usage: dict[str, Any]
    timings: dict[str, Any]
    audio_seconds: float


def _ffprobe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else 0.0
    except (ValueError, OSError):
        return 0.0


def _moss_imports(model_path: str):
    """Import the model repository's relative-import modules as a package.

    The Hub repo ships modeling_*.py / processing_*.py at its root with
    relative imports. A tiny symlink package lets us import them without
    copying the 18 GB weights.
    """
    root = Path(model_path)
    package_parent = Path(tempfile.mkdtemp(prefix="cadence-moss-pkg-"))
    package = package_parent / "mossmusic"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    for item in root.glob("*.py"):
        (package / item.name).symlink_to(item)
    sys.path.insert(0, str(package_parent))
    from mossmusic.configuration_moss_music import MossMusicConfig  # type: ignore
    from mossmusic.modeling_moss_music import MossMusicModel  # type: ignore
    from mossmusic.processing_moss_music import MossMusicProcessor  # type: ignore

    return MossMusicConfig, MossMusicModel, MossMusicProcessor


_MOSS_AUDIO_DEFAULTS = {
    "d_model": 1280,
    "output_dim": 1280,
    "num_mel_bins": 128,
    "encoder_layers": 32,
    "encoder_attention_heads": 20,
    "encoder_ffn_dim": 5120,
    "downsample_rate": 8,
    "downsample_hidden_size": 480,
    "encoder_attention_window_size": 100,
    "max_source_positions": 1500,
    "dropout": 0.1,
    "attention_dropout": 0.1,
    "activation_dropout": 0.0,
    "activation_function": "gelu",
    "layer_norm_eps": 1e-5,
    "_attn_implementation": "eager",
    "pretrained_path": "",
    "n_window": 200,
    "conv_chunksize": 64,
    "deepstack_encoder_layer_indexes": [8, 16, 24],
}


def _load_moss() -> dict[str, Any]:
    MossMusicConfig, MossMusicModel, MossMusicProcessor = _moss_imports(MODEL_PATH)
    # The Hub checkpoint ships a minimal configuration class that leaves
    # audio_config as a plain dict. The modeling class expects attribute
    # access (config.audio_config.downsample_hidden_size). Convert it before
    # constructing the model; the values are exactly the checkpoint's values.
    config = MossMusicConfig.from_pretrained(MODEL_PATH, trust_remote_code=True)
    audio_config = getattr(config, "audio_config", None)
    if isinstance(audio_config, dict):
        config.audio_config = SimpleNamespace(**{**_MOSS_AUDIO_DEFAULTS, **audio_config})
        logger.info("Converted MOSS audio_config dict to attribute config")
    elif audio_config is not None:
        for key, value in _MOSS_AUDIO_DEFAULTS.items():
            if not hasattr(audio_config, key):
                setattr(audio_config, key, value)
    else:
        config.audio_config = SimpleNamespace(**_MOSS_AUDIO_DEFAULTS)

    kwargs: dict[str, Any] = {
        "config": config,
        "trust_remote_code": True,
        "torch_dtype": DTYPE,
        "device_map": DEVICE,
        "low_cpu_mem_usage": True,
    }
    if LOAD_IN_4BIT:
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=DTYPE,
            bnb_4bit_quant_type="nf4",
        )
        kwargs.pop("torch_dtype", None)
    logger.info("Loading MOSS-Music from %s with %s", MODEL_PATH, kwargs)
    model = MossMusicModel.from_pretrained(MODEL_PATH, **kwargs)
    model.eval()
    processor = MossMusicProcessor.from_pretrained(
        MODEL_PATH, trust_remote_code=True, enable_time_marker=True
    )
    return {"kind": "moss", "model": model, "processor": processor}


def _load_flamingo() -> dict[str, Any]:
    from transformers import AutoProcessor, MusicFlamingoForConditionalGeneration

    kwargs: dict[str, Any] = {
        "torch_dtype": DTYPE,
        "device_map": DEVICE,
        "low_cpu_mem_usage": True,
    }
    logger.info("Loading Music Flamingo from %s with %s", MODEL_PATH, kwargs)
    model = MusicFlamingoForConditionalGeneration.from_pretrained(MODEL_PATH, **kwargs)
    model.eval()
    processor = AutoProcessor.from_pretrained(MODEL_PATH)
    return {"kind": "flamingo", "model": model, "processor": processor}


def _load() -> None:
    if DRY_RUN:
        _engine.update({"kind": "dry", "model": None, "processor": None})
        logger.warning("DRY_RUN=1: no model weights loaded; returning a synthetic report")
        return
    started = time.perf_counter()
    if MODEL_FAMILY.startswith("moss"):
        _engine.update(_load_moss())
    elif MODEL_FAMILY.startswith("flamingo"):
        _engine.update(_load_flamingo())
    else:
        raise RuntimeError(f"Unsupported MODEL_FAMILY={MODEL_FAMILY!r}")
    _engine["load_seconds"] = round(time.perf_counter() - started, 2)
    logger.info("Model ready in %.1fs on %s", _engine["load_seconds"], DEVICE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load()
    yield
    _engine.clear()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(title="Cadence Inference Endpoint", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    ready = bool(_engine)
    if not ready:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {
        "status": "ok",
        "model_family": _engine["kind"],
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "device": DEVICE,
        "max_audio_seconds": MAX_AUDIO_SECONDS,
        "load_seconds": _engine.get("load_seconds"),
        "gpu": torch.cuda.get_device_name(0) if torch is not None and torch.cuda.is_available() else None,
        "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
        if torch is not None and torch.cuda.is_available()
        else None,
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "cadence"}],
    }


def _dry_run_text(prompt: str, duration: float) -> str:
    return (
        f"[DRY RUN] This is a synthetic endpoint response for {duration:.1f}s of audio.\n"
        "Genre: electronic / ambient\nMood: calm, hopeful\nTempo: 96 BPM\nKey: G major\n"
        "Instrumentation: synth pads, soft kick, arpeggiated synth\n"
        "Vocal: instrumental\n"
        "Structure: 0-8s intro, 8-16s build, 16-24s main section, 24-end outro\n"
        "Caption: A warm, slowly brightening electronic bed with soft transients and an airy top end.\n"
        f"Requested tasks: {prompt[:300]}"
    )


def _generate_moss(audio_path: Path, prompt: str, max_new_tokens: int) -> tuple[str, dict[str, Any]]:
    import torchaudio

    engine = _engine
    model = engine["model"]
    processor = engine["processor"]
    waveform, original_rate = torchaudio.load(str(audio_path))
    if waveform.size(0) > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if original_rate != processor.config.mel_sr:
        waveform = torchaudio.functional.resample(
            waveform, orig_freq=original_rate, new_freq=processor.config.mel_sr
        )
    raw = waveform.squeeze(0).cpu().numpy()
    inputs = processor(text=prompt, audios=[raw], return_tensors="pt")
    inputs = inputs.to(model.device)
    if inputs.get("audio_data") is not None:
        inputs["audio_data"] = inputs["audio_data"].to(model.dtype)
    inputs["audio_input_mask"] = inputs["input_ids"] == processor.audio_token_id
    input_tokens = int(inputs["input_ids"].numel())
    started = time.perf_counter()
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            use_cache=True,
            repetition_penalty=1.08,
            no_repeat_ngram_size=6,
        )
    input_len = inputs["input_ids"].shape[1]
    output_ids = generated[0, input_len:]
    text = processor.decode(output_ids, skip_special_tokens=True).strip()
    if MODEL_FAMILY == "moss-thinking" and "</think>" in text:
        text = text.split("</think>")[-1].strip()
    return text, {
        "input_tokens": input_tokens,
        "output_tokens": int(output_ids.numel()),
        "generate_ms": int((time.perf_counter() - started) * 1000),
    }


def _generate_flamingo(audio_path: Path, prompt: str, max_new_tokens: int) -> tuple[str, dict[str, Any]]:
    engine = _engine
    model = engine["model"]
    processor = engine["processor"]
    conversation = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "audio", "path": str(audio_path)},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        conversation,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
    )
    inputs = inputs.to(model.device)
    if inputs.get("input_features") is not None:
        inputs["input_features"] = inputs["input_features"].to(model.dtype)
    input_tokens = int(inputs["input_ids"].numel())
    started = time.perf_counter()
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            use_cache=True,
            repetition_penalty=1.05,
            no_repeat_ngram_size=6,
        )
    input_len = inputs["input_ids"].shape[1]
    output_ids = generated[0, input_len:]
    text = processor.batch_decode(output_ids.unsqueeze(0), skip_special_tokens=True)[0].strip()
    return text, {
        "input_tokens": input_tokens,
        "output_tokens": int(output_ids.numel()),
        "generate_ms": int((time.perf_counter() - started) * 1000),
    }


@app.post("/v1/annotate", response_model=AnnotateResponse)
def annotate(
    audio: UploadFile = File(...),
    prompt: str = Form(...),
    max_new_tokens: int = Form(1024),
    temperature: float = Form(0.0),
) -> AnnotateResponse:
    if not _engine:
        raise HTTPException(status_code=503, detail="model not loaded")
    suffix = Path(audio.filename or "audio.mp3").suffix or ".mp3"
    tmp_dir = Path(tempfile.mkdtemp(prefix="cadence-audio-"))
    target = tmp_dir / f"input{suffix}"
    started = time.perf_counter()
    try:
        with target.open("wb") as handle:
            shutil.copyfileobj(audio.file, handle)
        if target.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="empty audio")
        duration = _ffprobe_duration(target)
        if duration <= 0:
            raise HTTPException(status_code=422, detail="could not read audio duration")
        if duration > MAX_AUDIO_SECONDS:
            raise HTTPException(
                status_code=413,
                detail=f"audio {duration:.1f}s exceeds endpoint limit {MAX_AUDIO_SECONDS}s",
            )
        tokens = max(64, min(int(max_new_tokens), MAX_NEW_TOKENS))
        if DRY_RUN:
            time.sleep(0.8)
            text = _dry_run_text(prompt, duration)
            usage = {"input_tokens": 0, "output_tokens": 0, "generate_ms": 800}
        else:
            with _generate_lock:
                if _engine["kind"] == "moss":
                    text, usage = _generate_moss(target, prompt, tokens)
                else:
                    text, usage = _generate_flamingo(target, prompt, tokens)
        return AnnotateResponse(
            text=text,
            model=MODEL_ID,
            model_family=MODEL_FAMILY,
            revision=MODEL_REVISION,
            usage=usage,
            timings={"preprocess_ms": int((time.perf_counter() - started) * 1000)},
            audio_seconds=round(duration, 2),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="info")
