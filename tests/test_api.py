
import io
import json
import wave

from fastapi.testclient import TestClient

from cadence_studio.api import SERVICES
from cadence_studio.app import app


def test_health_and_modules():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        modules = client.get("/api/modules").json()
        assert len(modules["modules"]) == 15
        assert "caption" in modules["all_ids"]


def test_taxonomy_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/taxonomy/meta")
        assert response.status_code == 200
        assert response.json()["source"]["label_count"] == 641
        response = client.get("/api/taxonomy?category=Mood&limit=10")
        assert response.status_code == 200
        assert response.json()["total"] == 33
        assert len(response.json()["tags"]) == 10


def test_settings_round_trip():
    with TestClient(app) as client:
        config = client.get("/api/settings").json()
        assert config["llm"]["routes"][0]["model"] == "deepseek-flash"
        assert config["llm"]["routes"][0]["thinking_mode"] == "disabled"
        config["workspace"]["name"] = "Test Studio"
        response = client.put("/api/settings", json={"config": config, "secrets": {"hf_token": "hf_test"}})
        assert response.status_code == 200
        updated = client.get("/api/settings").json()
        assert updated["workspace"]["name"] == "Test Studio"
        assert updated["inference"]["routes"][0]["secret_configured"] is True
        assert "hf_test" not in response.text


def test_label_languages_patch():
    with TestClient(app) as client:
        response = client.patch("/api/label-languages", json={"mood": "en", "scene": "en"})
        assert response.status_code == 200
        configured = client.get("/api/settings").json()
        assert configured["ui"]["label_languages"]["mood"] == "en"
        assert configured["ui"]["label_languages"]["scene"] == "en"
        assert configured["ui"]["label_languages"]["genre"] == "zh"


def test_inference_test_route_is_not_shadowed(monkeypatch):
    monkeypatch.setattr(
        SERVICES.inference,
        "health",
        lambda route_id: {"state": "running", "state_label": "运行中", "route_id": route_id},
    )
    with TestClient(app) as client:
        response = client.post("/api/inference/moss/test")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_hardware_profiles_and_workspace_goal():
    with TestClient(app) as client:
        profiles = client.get("/api/hardware-profiles").json()
        assert any(profile["id"] == "a10g-24gb" for profile in profiles["profiles"])
        assert any(profile["id"] == "l40s-48gb" for profile in profiles["profiles"])
        response = client.patch("/api/workspace", json={"daily_goal": 137})
        assert response.status_code == 200
        assert response.json()["workspace"]["daily_goal"] == 137
        overview = client.get("/api/system/overview").json()
        assert overview["daily_goal"] == 137


def test_batch_with_project_reference_uses_planner(monkeypatch):
    def fake_complete(route_id, messages, **kwargs):
        assert "15 秒卡点" in messages[1]["content"]
        return {"content": "请优先判断 15 秒卡点，并保持品牌语气克制。"}

    monkeypatch.setattr(SERVICES.llm, "complete", fake_complete)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * 8000 * 3)
    wav = buffer.getvalue()
    spec = {"modules": ["caption"], "project_instruction": "优先判断 15 秒卡点。"}
    with TestClient(app) as client:
        response = client.post(
            "/api/batches",
            files=[
                ("files", ("test.wav", wav, "audio/wav")),
                ("project_files", ("brief.txt", "品牌语气克制。".encode(), "text/plain")),
            ],
            data={"spec": json.dumps(spec, ensure_ascii=False), "auto_start": "false"},
        )
    assert response.status_code == 200, response.text
    batch = response.json()["batch"]
    assert "品牌语气克制" in batch["spec"]["project_context"]
    assert batch["spec"]["project_files"] == ["brief.txt"]
    assert "15 秒卡点" in batch["spec"]["audio_model_prompt"]


def test_demo_and_exports():
    with TestClient(app) as client:
        demo = client.post("/api/demo/seed")
        assert demo.status_code == 200
        batch = demo.json()["batch"]
        assert batch["counts"]["completed"] == 4
        items = client.get(f"/api/batches/{batch['id']}/items").json()
        assert items["total"] == 4
        first = items["items"][0]
        detail = client.get(f"/api/items/{first['id']}").json()
        assert detail["normalized"]["caption"]["text"]
        assert detail["raw_text"].startswith("A warm") or detail["raw_text"].startswith("A lo-fi")
        audio = client.get(f"/api/items/{first['id']}/audio")
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/")
        for fmt in ("xlsx", "json", "md", "csv", "zip"):
            exported = client.get(f"/api/batches/{batch['id']}/export?format={fmt}")
            assert exported.status_code == 200, fmt
            assert len(exported.content) > 1000, fmt
