import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["CADENCE_DATA_DIR"] = tempfile.mkdtemp(prefix="cadence-e2e-")
sys.path.insert(0, "src")

from fastapi.testclient import TestClient  # noqa: E402
from cadence_studio.app import app  # noqa: E402

with TestClient(app) as client:
    config = client.get("/api/settings").json()
    config["inference"]["routes"][0]["base_url"] = "http://127.0.0.1:8780"
    config["inference"]["routes"][0]["hf_namespace"] = ""
    config["inference"]["routes"][0]["hf_endpoint_name"] = ""
    config["inference"]["routes"][0]["provider"] = "custom"
    config["inference"]["routes"][0]["max_concurrency"] = 1
    config["inference"]["lifecycle"]["auto_pause"] = False
    config["llm"]["routes"][0]["base_url"] = "http://127.0.0.1:8790/v1"
    config["llm"]["routes"][0]["model"] = "mock"
    config["llm"]["routes"][0]["api_key_secret"] = "mock_key"
    response = client.put("/api/settings", json={"config": config, "secrets": {"mock_key": "x"}})
    print("settings", response.status_code, response.text[:300])
    spec = {
        "modules": ["caption", "genre", "mood", "bpm_key", "instruments", "structure"],
        "language": "zh",
        "caption_length": "medium",
        "structure_detail": "sections",
        "lyrics_timestamps": False,
        "include_confidence": True,
        "taxonomy_mode": "strict",
        "custom_instruction": "",
        "custom_fields": [],
        "audio_model_prompt": "",
        "output_language_note": "",
    }
    files = []
    paths = sorted(Path("data/audio/demo-seed").glob("*.mp3"))[:2]
    for path in paths:
        files.append(("files", (path.name, path.open("rb"), "audio/mpeg")))
    response = client.post(
        "/api/batches",
        data={"name": "E2E 管线测试", "note": "mock endpoint + mock LLM", "spec": json.dumps(spec, ensure_ascii=False), "auto_start": "true"},
        files=files,
    )
    print("create", response.status_code, response.text[:300])
    batch = response.json()["batch"]
    batch_id = batch["id"]
    for _ in range(40):
        time.sleep(1)
        status = client.get(f"/api/batches/{batch_id}").json()
        if status["status"] in {"completed", "completed_with_errors", "failed", "canceled"}:
            break
    print("final", status["status"], status["counts"])
    items = client.get(f"/api/batches/{batch_id}/items").json()["items"]
    for item in items:
        detail = client.get(f"/api/items/{item['id']}").json()
        print(item["file_name"], item["status"], detail.get("error_code"), detail.get("error_message")[:200])
        if detail.get("normalized"):
            print(json.dumps(detail["normalized"], ensure_ascii=False)[:800])
