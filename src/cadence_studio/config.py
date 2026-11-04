"""Application paths, persisted configuration and first-run defaults."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .secrets import SecretStore, SecretStoreError

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1]
RESOURCE_DIR = APP_DIR / "resources"
WEB_DIR = APP_DIR / "web"
DATA_DIR_ENV = "CADENCE_DATA_DIR"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def resolve_data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV) or os.environ.get("CADENCE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CadenceStudio"
        return base.resolve()
    return (PROJECT_ROOT / "data").resolve()


DATA_DIR = resolve_data_dir()
AUDIO_DIR = DATA_DIR / "audio"
EXPORT_DIR = DATA_DIR / "exports"
LOG_DIR = DATA_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "cadence.db"
CONFIG_PATH = DATA_DIR / "config.json"
SECRETS_PATH = DATA_DIR / "secrets.bin"


def ensure_dirs() -> None:
    for directory in (DATA_DIR, AUDIO_DIR, EXPORT_DIR, LOG_DIR, TMP_DIR, BACKUP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def default_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workspace": {
            "name": "My Music Studio",
            "owner": "",
            "daily_goal": 500,
        },
        "inference": {
            "active_route_id": "moss",
            "routes": [
                {
                    "id": "moss",
                    "name": "MOSS Music 8B",
                    "provider": "huggingface",
                    "adapter": "cadence",
                    "model": "OpenMOSS-Team/MOSS-Music-8B-Instruct",
                    "base_url": "",
                    "hf_namespace": "",
                    "hf_endpoint_name": "",
                    "health_path": "/health",
                    "infer_path": "/v1/annotate",
                    "api_key_secret": "hf_token",
                    "hardware_profile": "a10g-24gb",
                    "max_concurrency": 1,
                    "timeout_seconds": 900,
                    "max_audio_seconds": 1200,
                    "max_new_tokens": 900,
                    "enabled": True,
                    "notes": "推荐先部署自定义推理容器。A10G 上建议并发 1，避免显存竞争。",
                },
                {
                    "id": "flamingo",
                    "name": "Music Flamingo 2601",
                    "provider": "huggingface",
                    "adapter": "cadence",
                    "model": "nvidia/music-flamingo-2601-hf",
                    "base_url": "",
                    "hf_namespace": "",
                    "hf_endpoint_name": "",
                    "health_path": "/health",
                    "infer_path": "/v1/annotate",
                    "api_key_secret": "hf_token",
                    "hardware_profile": "l40s-48gb",
                    "max_concurrency": 1,
                    "timeout_seconds": 900,
                    "max_audio_seconds": 1200,
                    "max_new_tokens": 1024,
                    "enabled": False,
                    "notes": "支持 30 秒窗口、最长 20 分钟；许可为非商业研究，商用前请核实。",
                },
            ],
            "lifecycle": {
                "auto_resume": True,
                "auto_pause": True,
                "pause_grace_seconds": 120,
                "resume_timeout_seconds": 900,
                "poll_seconds": 5,
            },
        },
        "llm": {
            "active_route_id": "deepseek",
            "routes": [
                {
                    "id": "deepseek",
                    "name": "DeepSeek Flash",
                    "provider": "openai_compatible",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-flash",
                    "api_key_secret": "deepseek_api_key",
                    "temperature": 0.1,
                    "max_tokens": 4096,
                    "timeout_seconds": 240,
                    "json_mode": True,
                    "thinking_mode": "disabled",
                    "enabled": True,
                }
            ],
            "normalization": {
                "strict_taxonomy": True,
                "allow_approximate_mapping": True,
                "include_confidence": True,
                "include_reasoning": False,
                "max_catalog_chars": 36000,
                "repair_attempts": 1,
            },
        },
        "processing": {
            "max_parallel_items": 2,
            "max_attempts": 3,
            "retry_backoff_seconds": 5,
            "transcode": True,
            "transcode_bitrate": "96k",
            "max_upload_mb": 512,
            "max_items_per_batch": 1000,
            "auto_start": True,
        },
        "ui": {
            "theme": "dark",
            "density": "comfortable",
            "locale": "zh-CN",
        },
        "exports": {
            "formats": ["xlsx", "json", "md"],
            "include_raw": True,
            "include_taxonomy": True,
            "include_mappings": True,
        },
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH, secrets_path: Path = SECRETS_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.secrets = SecretStore(secrets_path)
        self.load()

    def load(self) -> dict[str, Any]:
        with self._lock:
            ensure_dirs()
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"配置文件损坏：{self.path} — {exc}") from exc
                self._data = deep_merge(default_config(), raw)
                if self._migrate():
                    self._write()
            else:
                self._data = default_config()
                self._write()
            return self._data

    def _migrate(self) -> bool:
        """Update retired defaults without touching custom routes."""
        changed = False
        for route in self._data.get("inference", {}).get("routes", []):
            if not route.get("hardware_profile"):
                route["hardware_profile"] = (
                    "a10g-24gb" if route.get("id") == "moss" else "l40s-48gb" if route.get("id") == "flamingo" else "custom"
                )
                changed = True
            if not route.get("max_new_tokens"):
                route["max_new_tokens"] = 1024 if route.get("id") == "flamingo" else 900
                changed = True
        for route in self._data.get("llm", {}).get("routes", []):
            base = str(route.get("base_url") or "")
            if "deepseek.com" in base and route.get("model") in {"deepseek-chat", "deepseek-reasoner"}:
                route["model"] = "deepseek-flash"
                if route.get("name") in {"DeepSeek Chat", "DeepSeek Reasoner", "DeepSeek"}:
                    route["name"] = "DeepSeek Flash"
                route.setdefault("thinking_mode", "disabled")
                changed = True
            if "deepseek.com" in base and "thinking_mode" not in route:
                route["thinking_mode"] = "disabled"
                changed = True
        return changed

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def replace(self, incoming: dict[str, Any], secrets: dict[str, str | None] | None = None) -> dict[str, Any]:
        with self._lock:
            merged = deep_merge(default_config(), incoming)
            merged["created_at"] = self._data.get("created_at", utc_now())
            merged["updated_at"] = utc_now()
            self._data = merged
            if secrets:
                self.secrets.update(secrets)
            self._write()
            return self.get()

    def patch(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if section not in self._data:
                raise KeyError(section)
            if not isinstance(self._data[section], dict):
                self._data[section] = values
            else:
                self._data[section] = deep_merge(self._data[section], values)
            self._data["updated_at"] = utc_now()
            self._write()
            return self.get()

    def public(self) -> dict[str, Any]:
        data = self.get()
        for route in data.get("inference", {}).get("routes", []):
            secret_name = route.get("api_key_secret", "hf_token")
            route["secret_configured"] = self.secrets.has(secret_name)
            route["secret_hint"] = self.secrets.hint(secret_name)
            route["management_configured"] = bool(
                route.get("hf_namespace") and route.get("hf_endpoint_name") and self.secrets.has(secret_name)
            )
            route["resolved_url"] = (route.get("base_url") or "").strip()
        for route in data.get("llm", {}).get("routes", []):
            secret_name = route.get("api_key_secret", "deepseek_api_key")
            route["secret_configured"] = self.secrets.has(secret_name)
            route["secret_hint"] = self.secrets.hint(secret_name)
        data["secrets_meta"] = {
            "secure_storage": self.secrets.secure,
            "stored_names": self.secrets.names(),
            "data_dir": str(DATA_DIR),
        }
        return data

    def inference_route(self, route_id: str | None = None) -> dict[str, Any]:
        data = self.get()
        section = data["inference"]
        route_id = route_id or section["active_route_id"]
        for route in section["routes"]:
            if route["id"] == route_id:
                return route
        raise KeyError(f"未知推理路由：{route_id}")

    def llm_route(self, route_id: str | None = None) -> dict[str, Any]:
        data = self.get()
        section = data["llm"]
        route_id = route_id or section["active_route_id"]
        for route in section["routes"]:
            if route["id"] == route_id:
                return route
        raise KeyError(f"未知模型路由：{route_id}")

    def backup(self) -> Path | None:
        ensure_dirs()
        if not DB_PATH.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = BACKUP_DIR / f"cadence-{stamp}.db"
        shutil.copy2(DB_PATH, target)
        return target


CONFIG = ConfigStore()


def get_config() -> ConfigStore:
    return CONFIG


def secret_error_message(exc: Exception) -> str:
    if isinstance(exc, SecretStoreError):
        return str(exc)
    return f"凭据存储不可用：{exc}"
