import json
from pathlib import Path

import httpx

base = "http://127.0.0.1:8780"
print(httpx.get(f"{base}/health", timeout=10).json())
audio = next(Path("data/audio/demo-seed").glob("*.mp3"))
with audio.open("rb") as handle:
    response = httpx.post(
        f"{base}/v1/annotate",
        data={"prompt": "Describe genre, mood, BPM, instrumentation and structure.", "max_new_tokens": "900"},
        files={"audio": (audio.name, handle, "audio/mpeg")},
        timeout=60,
    )
print(response.status_code)
print(json.dumps(response.json(), ensure_ascii=False, indent=2)[:800])
