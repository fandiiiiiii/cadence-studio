import json
from pathlib import Path

from cadence_studio.config import ConfigStore, deep_merge, default_config


def test_legacy_deepseek_and_route_defaults_migrate(tmp_path: Path):
    data = deep_merge(default_config(), {})
    data["llm"]["routes"][0].update(
        name="DeepSeek Chat",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
    )
    data["llm"]["routes"][0].pop("thinking_mode", None)
    data["inference"]["routes"][0].pop("hardware_profile", None)
    data["inference"]["routes"][0].pop("max_new_tokens", None)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    store = ConfigStore(config_path, tmp_path / "secrets.bin")
    loaded = store.get()
    route = loaded["llm"]["routes"][0]
    assert route["model"] == "deepseek-flash"
    assert route["name"] == "DeepSeek Flash"
    assert route["thinking_mode"] == "disabled"
    assert loaded["inference"]["routes"][0]["hardware_profile"] == "a10g-24gb"
    assert loaded["inference"]["routes"][0]["max_new_tokens"] == 900
