
from fastapi.testclient import TestClient

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
        config["workspace"]["name"] = "Test Studio"
        response = client.put("/api/settings", json={"config": config, "secrets": {"hf_token": "hf_test"}})
        assert response.status_code == 200
        updated = client.get("/api/settings").json()
        assert updated["workspace"]["name"] == "Test Studio"
        assert updated["inference"]["routes"][0]["secret_configured"] is True
        assert "hf_test" not in response.text


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
