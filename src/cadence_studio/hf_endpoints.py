"""Hugging Face Inference Endpoints lifecycle management.

Uses the documented v2 REST API directly:
  GET  /v2/endpoint/{namespace}/{name}
  POST /v2/endpoint/{namespace}/{name}/resume
  POST /v2/endpoint/{namespace}/{name}/pause
  POST /v2/endpoint/{namespace}/{name}/scale-to-zero
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import ConfigStore

HF_ENDPOINTS_API = "https://api.endpoints.huggingface.cloud"
HF_API = "https://huggingface.co/api"
STATE_LABELS = {
    "running": "运行中",
    "paused": "已暂停",
    "scaledToZero": "已缩容到零",
    "stopped": "已停止",
    "initializing": "启动中",
    "pending": "等待调度",
    "updating": "更新中",
    "updateFailed": "更新失败",
    "failed": "运行失败",
    "deleting": "删除中",
    "unknown": "未知",
    "unconfigured": "未配置",
    "reachable": "可访问",
    "unreachable": "不可达",
}
ACTIVE_STATES = {"running"}
TRANSITIONAL_STATES = {"initializing", "pending", "updating"}
PAUSABLE_STATES = {"running", "updating", "initializing", "pending"}
RESUMABLE_STATES = {"paused", "scaledToZero", "stopped", "failed", "updateFailed"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class EndpointError(RuntimeError):
    def __init__(self, message: str, *, code: str = "endpoint_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class HFEndpointManager:
    def __init__(self, config: ConfigStore):
        self.config = config
        self._cache: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.RLock()

    def _lock(self, route_id: str) -> threading.RLock:
        with self._global_lock:
            # Reentrant: ensure_ready() holds the route lock and calls
            # action("resume"), which takes the same lock again.
            return self._locks.setdefault(route_id, threading.RLock())

    def _token(self, route: dict[str, Any]) -> str:
        return self.config.secrets.get(route.get("api_key_secret", "hf_token"))

    def _management(self, route: dict[str, Any]) -> bool:
        return bool(route.get("hf_namespace") and route.get("hf_endpoint_name") and self._token(route))

    def _headers(self, route: dict[str, Any]) -> dict[str, str]:
        token = self._token(route)
        return {"Authorization": f"Bearer {token}", "User-Agent": "CadenceStudio/0.1"} if token else {
            "User-Agent": "CadenceStudio/0.1"
        }

    def _request(self, method: str, url: str, route: dict[str, Any], **kwargs: Any) -> httpx.Response:
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=15.0)) as client:
                return client.request(method, url, headers=self._headers(route), **kwargs)
        except httpx.HTTPError as exc:
            raise EndpointError(f"无法连接 Hugging Face：{exc}", code="network_error", retryable=True) from exc

    def _endpoint_url(self, route: dict[str, Any]) -> str:
        return (
            f"{HF_ENDPOINTS_API}/v2/endpoint/"
            f"{route['hf_namespace']}/{route['hf_endpoint_name']}"
        )

    def raw_status(self, route: dict[str, Any], *, use_cache: bool = True) -> dict[str, Any]:
        route_id = route["id"]
        if use_cache:
            cached = self._cache.get(route_id)
            if cached and time.time() - cached["_ts"] < 8:
                return cached
        if self._management(route):
            response = self._request("GET", self._endpoint_url(route), route)
            if response.status_code == 401:
                result = self._status_payload(route, "unknown", error="Hugging Face 令牌无效或无权限（401）")
            elif response.status_code == 404:
                result = self._status_payload(route, "unconfigured", error="找不到端点：请核对 namespace 与名称")
            elif response.status_code >= 400:
                result = self._status_payload(
                    route, "unknown", error=f"HF API {response.status_code}：{response.text[:300]}"
                )
            else:
                try:
                    raw = response.json()
                except ValueError:
                    result = self._status_payload(route, "unknown", error="HF API 返回了非 JSON 响应")
                else:
                    status = raw.get("status") or {}
                    state = status.get("state") or raw.get("state") or "unknown"
                    result = self._status_payload(
                        route,
                        state,
                        url=status.get("url") or raw.get("url") or route.get("base_url") or "",
                        raw=raw,
                    )
                    result["replicas"] = raw.get("status", {}).get("replicas")
                    result["model_repository"] = (raw.get("model") or {}).get("repository")
                    result["model_revision"] = (raw.get("model") or {}).get("revision")
                    result["instance"] = raw.get("provider", {}).get("instance") or raw.get("instance")
        else:
            base = (route.get("base_url") or "").rstrip("/")
            if not base:
                result = self._status_payload(route, "unconfigured", error="尚未填写端点 URL")
            else:
                health_path = route.get("health_path") or "/health"
                url = f"{base}{health_path if health_path.startswith('/') else '/' + health_path}"
                try:
                    with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True) as client:
                        response = client.get(url, headers=self._headers(route))
                    state = "running" if response.status_code < 400 else "unreachable"
                    error = "" if response.status_code < 400 else f"健康检查 HTTP {response.status_code}"
                    result = self._status_payload(route, state, url=base, error=error)
                except httpx.HTTPError as exc:
                    result = self._status_payload(route, "unreachable", url=base, error=str(exc))
        self._cache[route_id] = {**result, "_ts": time.time()}
        return result

    def _status_payload(
        self, route: dict[str, Any], state: str, *, url: str = "", error: str = "", raw: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "route_id": route["id"],
            "route_name": route.get("name", route["id"]),
            "state": state,
            "state_label": STATE_LABELS.get(state, state),
            "url": url or route.get("base_url", ""),
            "error": error,
            "managed": self._management(route),
            "checked_at": utc_now(),
            "raw": raw or {},
        }

    def status(self, route_id: str | None = None) -> dict[str, Any]:
        route = self.config.inference_route(route_id)
        return self.raw_status(route)

    def cached_status(self, route_id: str | None = None) -> dict[str, Any] | None:
        route = self.config.inference_route(route_id)
        cached = self._cache.get(route["id"])
        if not cached:
            return None
        return {key: value for key, value in cached.items() if key != "_ts"}

    def invalidate(self, route_id: str | None = None) -> None:
        if route_id:
            self._cache.pop(route_id, None)
        else:
            self._cache.clear()

    def action(self, route_id: str, action: str) -> dict[str, Any]:
        route = self.config.inference_route(route_id)
        if not self._management(route):
            raise EndpointError(
                "该路由没有配置 Hugging Face 端点管理信息（namespace、端点名、HF 令牌），无法执行生命周期操作。",
                code="management_not_configured",
            )
        if action not in {"resume", "pause", "scale-to-zero"}:
            raise EndpointError(f"不支持的操作：{action}", code="bad_action")
        with self._lock(route_id):
            response = self._request("POST", f"{self._endpoint_url(route)}/{action}", route)
            self.invalidate(route_id)
            if response.status_code == 400 and action == "resume":
                text = response.text.lower()
                if "already" in text or "running" in text:
                    return self.raw_status(route)
                raise EndpointError(f"无法恢复端点：{response.text[:400]}", code="resume_failed")
            if response.status_code == 400 and action == "scale-to-zero":
                raise EndpointError(
                    "端点未开启 scale-to-zero。可在 Hugging Face 端点设置中开启，或直接使用“暂停”。",
                    code="scale_to_zero_not_enabled",
                )
            if response.status_code >= 400:
                raise EndpointError(
                    f"端点操作失败（HTTP {response.status_code}）：{response.text[:400]}",
                    code=action + "_failed",
                )
            return self.raw_status(route, use_cache=False)

    def resume(self, route_id: str) -> dict[str, Any]:
        return self.action(route_id, "resume")

    def pause(self, route_id: str) -> dict[str, Any]:
        return self.action(route_id, "pause")

    def wait_ready(self, route_id: str, timeout_seconds: int | None = None) -> dict[str, Any]:
        route = self.config.inference_route(route_id)
        lifecycle = self.config.get()["inference"]["lifecycle"]
        timeout_seconds = timeout_seconds or int(lifecycle.get("resume_timeout_seconds", 900))
        poll = max(2, int(lifecycle.get("poll_seconds", 5)))
        deadline = time.time() + timeout_seconds
        last: dict[str, Any] | None = None
        while time.time() < deadline:
            last = self.raw_status(route, use_cache=False)
            if last["state"] == "running":
                return last
            if last["state"] in {"failed", "updateFailed"}:
                raise EndpointError(
                    f"端点状态为 {last['state_label']}，请到 Hugging Face 控制台查看日志。{last.get('error', '')}",
                    code="endpoint_failed",
                )
            time.sleep(poll)
        raise EndpointError(
            f"等待端点启动超时（{timeout_seconds}s）。最后状态：{last['state_label'] if last else '未知'}",
            code="resume_timeout",
            retryable=True,
        )

    def ensure_ready(self, route_id: str, *, auto_resume: bool = True) -> dict[str, Any]:
        route = self.config.inference_route(route_id)
        with self._lock(route_id):
            status = self.raw_status(route, use_cache=False)
            if status["state"] == "running":
                return status
            if status["state"] in TRANSITIONAL_STATES:
                return self.wait_ready(route_id)
            if status["state"] in RESUMABLE_STATES:
                if not auto_resume:
                    raise EndpointError(
                        f"端点当前为 {status['state_label']}，已关闭自动恢复。",
                        code="endpoint_not_running",
                    )
                try:
                    self.action(route_id, "resume")
                except EndpointError as exc:
                    if exc.code != "resume_failed":
                        raise
                return self.wait_ready(route_id)
            if status["state"] == "unconfigured" and route.get("base_url"):
                # Direct endpoints have no lifecycle API; a successful health check is enough.
                if status.get("error"):
                    raise EndpointError(status["error"], code="endpoint_unreachable", retryable=True)
                return status
            raise EndpointError(
                status.get("error") or f"端点不可用：{status['state_label']}",
                code="endpoint_unavailable",
                retryable=True,
            )

    def auto_pause_if_idle(self, route_id: str, active_jobs: int) -> dict[str, Any] | None:
        lifecycle = self.config.get()["inference"]["lifecycle"]
        if not lifecycle.get("auto_pause", True) or active_jobs > 0:
            return None
        route = self.config.inference_route(route_id)
        if not self._management(route):
            return None
        status = self.raw_status(route)
        if status["state"] != "running":
            return status
        return self.pause(route_id)

    def list_hf_endpoints(self, namespace: str) -> list[dict[str, Any]]:
        token = self.config.secrets.get("hf_token")
        if not token:
            raise EndpointError("请先在设置中保存 Hugging Face 令牌。", code="missing_token")
        if not namespace:
            raise EndpointError("请先填写 Hugging Face namespace。", code="missing_namespace")
        url = f"{HF_ENDPOINTS_API}/v2/endpoint/{namespace}"
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}", "User-Agent": "CadenceStudio/0.1"},
                    params={"limit": 100},
                )
        except httpx.HTTPError as exc:
            raise EndpointError(f"无法连接 Hugging Face：{exc}", code="network_error", retryable=True) from exc
        if response.status_code >= 400:
            raise EndpointError(
                f"读取端点列表失败（HTTP {response.status_code}）：{response.text[:300]}",
                code="list_failed",
            )
        payload = response.json()
        items = payload.get("items", payload if isinstance(payload, list) else [])
        result = []
        for item in items:
            model = item.get("model") or {}
            status = item.get("status") or {}
            result.append(
                {
                    "name": item.get("name", ""),
                    "namespace": item.get("namespace", namespace),
                    "repository": model.get("repository", ""),
                    "task": model.get("task", ""),
                    "state": status.get("state", "unknown"),
                    "state_label": STATE_LABELS.get(status.get("state", "unknown"), status.get("state", "")),
                    "url": status.get("url", ""),
                    "type": item.get("type", ""),
                    "instance": item.get("provider", {}).get("instance"),
                    "created_at": status.get("createdAt"),
                }
            )
        return result

    def whoami(self) -> dict[str, Any]:
        token = self.config.secrets.get("hf_token")
        if not token:
            raise EndpointError("尚未保存 Hugging Face 令牌。", code="missing_token")
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    f"{HF_API}/whoami-v2", headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as exc:
            raise EndpointError(f"无法连接 Hugging Face：{exc}", code="network_error") from exc
        if response.status_code == 401:
            raise EndpointError("Hugging Face 令牌无效（401）。", code="invalid_token")
        if response.status_code >= 400:
            raise EndpointError(f"whoami 失败：HTTP {response.status_code}", code="whoami_failed")
        data = response.json()
        return {"name": data.get("name"), "fullname": data.get("fullname"), "type": data.get("type")}
