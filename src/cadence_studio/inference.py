"""Audio model adapters (custom Cadence endpoint and OpenAI-compatible audio chat)."""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx

from .config import ConfigStore
from .hf_endpoints import EndpointError, HFEndpointManager


class InferenceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "inference_error", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AudioInferenceClient:
    def __init__(self, config: ConfigStore, endpoints: HFEndpointManager):
        self.config = config
        self.endpoints = endpoints

    def _resolved_base(self, route: dict[str, Any], status: dict[str, Any] | None = None) -> str:
        if status and status.get("url"):
            base = str(status["url"]).rstrip("/")
            if not base.endswith("/health"):
                return base
        base = str(route.get("base_url") or "").rstrip("/")
        return base

    def _headers(self, route: dict[str, Any], *, scale_up: bool = True) -> dict[str, str]:
        token = self.config.secrets.get(route.get("api_key_secret", "hf_token"))
        headers = {"User-Agent": "CadenceStudio/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if scale_up and route.get("provider") == "huggingface":
            # Supported by HF dedicated endpoints; ignored by other servers.
            headers["X-Scale-Up-Timeout"] = str(min(900, int(route.get("timeout_seconds", 600))))
        return headers

    def _extract_text(self, payload: Any) -> tuple[str, dict[str, Any]]:
        if isinstance(payload, str):
            return payload, {}
        if not isinstance(payload, dict):
            raise InferenceError("端点返回了无法识别的响应格式", code="bad_response", retryable=False)
        for key in ("text", "raw", "output", "generated_text", "annotation", "result"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), payload
        outputs = payload.get("outputs")
        if isinstance(outputs, list) and outputs:
            first = outputs[0]
            if isinstance(first, str):
                return first, payload
            if isinstance(first, dict):
                for key in ("text", "generated_text", "output"):
                    if isinstance(first.get(key), str):
                        return first[key], payload
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content")
            if isinstance(content, str):
                return content, payload
            if isinstance(content, list):
                parts = [part.get("text", "") for part in content if isinstance(part, dict)]
                if "".join(parts).strip():
                    return "".join(parts).strip(), payload
        raise InferenceError("端点响应中没有文本结果", code="empty_response", retryable=False)

    def _cadence_request(
        self, base: str, route: dict[str, Any], audio: Path, prompt: str, spec: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        path = route.get("infer_path") or "/v1/annotate"
        url = f"{base}{path if path.startswith('/') else '/' + path}"
        data = {
            "prompt": prompt,
            "model": route.get("model", ""),
            "max_new_tokens": "900",
            "temperature": "0.1",
            "response_format": "text",
        }
        if spec.get("lyrics_timestamps"):
            data["timestamps"] = "true"
        try:
            with audio.open("rb") as handle:
                files = {
                    "audio": (
                        audio.name,
                        handle,
                        mimetypes.guess_type(audio.name)[0] or "application/octet-stream",
                    )
                }
                with httpx.Client(
                    timeout=httpx.Timeout(
                        float(route.get("timeout_seconds", 600)), connect=30.0, write=300.0
                    ),
                    follow_redirects=True,
                ) as client:
                    response = client.post(url, headers=self._headers(route), data=data, files=files)
        except httpx.TimeoutException as exc:
            raise InferenceError(
                f"音频模型超时（{route.get('timeout_seconds', 600)}s）。可尝试缩短音频或检查端点日志。",
                code="timeout",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise InferenceError(f"连接推理端点失败：{exc}", code="network_error", retryable=True) from exc
        if response.status_code == 401:
            raise InferenceError("推理端点鉴权失败（401），请检查 HF 令牌。", code="unauthorized", retryable=False)
        if response.status_code == 413:
            raise InferenceError("上传音频超过端点请求体限制（413）。", code="payload_too_large", retryable=False)
        if response.status_code >= 500:
            retryable = response.status_code in {502, 503, 504}
            raise InferenceError(
                f"推理端点错误 HTTP {response.status_code}：{response.text[:500]}",
                code="server_error",
                retryable=retryable,
            )
        if response.status_code >= 400:
            raise InferenceError(
                f"推理请求失败 HTTP {response.status_code}：{response.text[:500]}",
                code="client_error",
                retryable=False,
            )
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            if text:
                return text, {"content_type": response.headers.get("content-type", "")}
            raise InferenceError("推理端点返回空响应", code="empty_response", retryable=False) from None
        text, _ = self._extract_text(payload)
        usage = {
            "model": payload.get("model", route.get("model", "")),
            "revision": payload.get("revision") or payload.get("model_revision"),
            "usage": payload.get("usage") or {},
            "timings": payload.get("timings") or {},
            "audio_seconds": payload.get("audio_seconds"),
        }
        return text, usage

    def _openai_request(
        self, base: str, route: dict[str, Any], audio: Path, prompt: str, spec: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        url = base.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        mime = mimetypes.guess_type(audio.name)[0] or "audio/mpeg"
        suffix = audio.suffix.lower().lstrip(".") or "mp3"
        if suffix == "m4a":
            suffix = "mp4"
        encoded = base64.b64encode(audio.read_bytes()).decode("ascii")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        style = route.get("audio_payload_style", "input_audio")
        if style == "audio_url":
            content.append(
                {"type": "audio_url", "audio_url": {"url": f"data:{mime};base64,{encoded}"}}
            )
        else:
            content.append(
                {"type": "input_audio", "input_audio": {"data": encoded, "format": suffix}}
            )
        body = {
            "model": route.get("model"),
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": 1200,
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(float(route.get("timeout_seconds", 600)), connect=30.0),
                follow_redirects=True,
            ) as client:
                response = client.post(url, headers=self._headers(route), json=body)
        except httpx.TimeoutException as exc:
            raise InferenceError("音频模型请求超时。", code="timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise InferenceError(f"连接音频模型失败：{exc}", code="network_error", retryable=True) from exc
        if response.status_code == 401:
            raise InferenceError("音频模型鉴权失败（401）。", code="unauthorized", retryable=False)
        if response.status_code >= 500:
            raise InferenceError(
                f"音频模型错误 HTTP {response.status_code}：{response.text[:500]}",
                code="server_error",
                retryable=response.status_code in {502, 503, 504},
            )
        if response.status_code >= 400:
            raise InferenceError(
                f"音频模型请求失败 HTTP {response.status_code}：{response.text[:500]}",
                code="client_error",
                retryable=False,
            )
        payload = response.json()
        text, _ = self._extract_text(payload)
        return text, {
            "model": payload.get("model", route.get("model", "")),
            "usage": payload.get("usage") or {},
            "timings": payload.get("timings") or {},
        }

    def annotate(
        self,
        route_id: str,
        audio: Path,
        prompt: str,
        spec: dict[str, Any],
        *,
        progress_cb: Any | None = None,
    ) -> dict[str, Any]:
        route = self.config.inference_route(route_id)
        started = time.perf_counter()
        if progress_cb:
            progress_cb("checking_endpoint", "检查端点状态")
        status = self.endpoints.ensure_ready(
            route_id, auto_resume=bool(self.config.get()["inference"]["lifecycle"].get("auto_resume", True))
        )
        base = self._resolved_base(route, status)
        if not base:
            raise InferenceError("端点没有可用的 Inference URL。", code="missing_url", retryable=False)
        if progress_cb:
            progress_cb("inferencing", "音频模型分析中")
        adapter = route.get("adapter", "cadence")
        attempts = 0
        last_error: Exception | None = None
        while attempts < 3:
            attempts += 1
            try:
                if adapter == "openai_audio":
                    text, meta = self._openai_request(base, route, audio, prompt, spec)
                else:
                    text, meta = self._cadence_request(base, route, audio, prompt, spec)
                latency = int((time.perf_counter() - started) * 1000)
                return {
                    "text": text,
                    "model": meta.get("model") or route.get("model", ""),
                    "revision": meta.get("revision"),
                    "usage": meta.get("usage") or {},
                    "timings": {**meta.get("timings", {}), "wall_ms": latency, "attempts": attempts},
                    "latency_ms": latency,
                }
            except InferenceError as exc:
                last_error = exc
                if not exc.retryable or attempts >= 3:
                    raise
                time.sleep(2 * attempts)
            except EndpointError as exc:
                last_error = exc
                if not exc.retryable or attempts >= 3:
                    raise InferenceError(str(exc), code=exc.code, retryable=False) from exc
                time.sleep(2 * attempts)
        raise InferenceError(str(last_error or "未知推理错误"), code="retry_exhausted", retryable=False)

    def health(self, route_id: str) -> dict[str, Any]:
        status = self.endpoints.status(route_id)
        return {
            "ok": status["state"] == "running",
            "state": status["state"],
            "state_label": status["state_label"],
            "url": status["url"],
            "message": status.get("error", ""),
            "managed": status["managed"],
            "checked_at": status["checked_at"],
        }
