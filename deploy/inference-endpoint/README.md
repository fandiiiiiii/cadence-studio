# Cadence Inference Endpoint Container

One container = **one model family**. MOSS-Music and Music Flamingo require
different Transformers versions and an A10G cannot hold both comfortably.

## Contract

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | 200 only after model load; includes model/revision/GPU |
| GET | `/v1/models` | minimal model metadata |
| POST | `/v1/annotate` | multipart: `audio`, `prompt`, `max_new_tokens`, `temperature` |

Response:

```json
{
  "text": "raw model observation",
  "model": "OpenMOSS-Team/MOSS-Music-8B-Instruct",
  "model_family": "moss",
  "revision": "optional-pinned-sha",
  "usage": {"input_tokens": 1234, "output_tokens": 567},
  "timings": {"preprocess_ms": 1200, "generate_ms": 43000},
  "audio_seconds": 210.0
}
```

The Cadence workbench uses the `cadence` adapter and `infer_path=/v1/annotate`.

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `MODEL_FAMILY` | `moss` | `moss`, `moss-thinking`, `flamingo` |
| `MODEL_PATH` | `/repository` | HF mounts the selected model repo here |
| `MODEL_ID` | `MODEL_PATH` | used in response/trace |
| `MODEL_REVISION` | empty | pin a commit SHA in production |
| `MAX_AUDIO_SECONDS` | `1200` | reject longer audio |
| `MAX_NEW_TOKENS` | `1024` | hard cap |
| `TORCH_DTYPE` | `bfloat16` | A10G supports bf16 |
| `LOAD_IN_4BIT` | `0` | experimental, unverified |
| `DRY_RUN` | `0` | returns synthetic text; no model load |
| `PORT` | `8000` | container port |

## Build

```bash
docker buildx build --platform linux/amd64 \
  -f Dockerfile \
  --build-arg MODEL_FAMILY=moss \
  -t your-user/cadence-moss:0.1 .

docker buildx build --platform linux/amd64 \
  -f Dockerfile \
  --build-arg MODEL_FAMILY=flamingo \
  -t your-user/cadence-flamingo:0.1 .
```

## Dry-run test

```bash
docker run --rm -p 8000:8000 -e DRY_RUN=1 -e MODEL_FAMILY=moss your-user/cadence-moss:0.1

curl -X POST http://127.0.0.1:8000/v1/annotate \
  -F "audio=@/path/song.mp3" \
  -F "prompt=Describe genre, mood, BPM and structure." \
  -F "max_new_tokens=900"
```

## Model-specific notes

### MOSS

- The container imports `modeling_moss_music.py` / `processing_moss_music.py`
  from `/repository` through a tiny symlink package; the 18GB weights are never
  copied.
- Requires `torchaudio`; Dockerfile installs `torchaudio==2.9.1`.
- MOSS recommends fork-SGLang for maximum quality/throughput. This container
  uses Transformers and is the simplest HF Endpoints path.
- Thinking variant strips `</think>` and returns the final text.

### Music Flamingo

- Requires `transformers>=5.6`; supports up to 20 minutes in 30s windows.
- Model card: NVIDIA OneWay Noncommercial License. Do not use commercially
  without checking the license.
- vLLM is not a supported serving path as of 2026-11.

## A10G reality check

- MOSS 9.05B / ~18.1GB bf16; Flamingo 8.27B / ~16.5GB bf16.
- A10G has 24GB. 4-minute audio + 1k output tokens + CUDA context may OOM.
- Keep batch=1; the server serializes generation with a lock.
- If OOM: use a 48GB+ GPU, shorten audio, or evaluate 4-bit experimentally.
- No real A10G validation is included in this repository. Record the first run
  in `docs/quality/benchmark.md`.
