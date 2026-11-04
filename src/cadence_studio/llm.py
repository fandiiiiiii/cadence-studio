"""OpenAI-compatible chat completion client used for normalization."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .config import ConfigStore


class LLMError(RuntimeError):
    def __init__(self, message: str, *, code: str = "llm_error", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class LLMClient:
    def __init__(self, config: ConfigStore):
        self.config = config

    @staticmethod
    def _url(base_url: str) -> str:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise LLMError("尚未配置大模型 API 地址", code="missing_base_url", retryable=False)
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _headers(self, route: dict[str, Any]) -> dict[str, str]:
        token = self.config.secrets.get(route.get("api_key_secret", "deepseek_api_key"))
        headers = {"Content-Type": "application/json", "User-Agent": "CadenceStudio/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def complete(
        self,
        route_id: str | None,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = True,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        route = self.config.llm_route(route_id)
        url = self._url(route.get("base_url", ""))
        body: dict[str, Any] = {
            "model": route.get("model"),
            "messages": messages,
            "temperature": route.get("temperature", 0.1) if temperature is None else temperature,
            "max_tokens": route.get("max_tokens", 4096) if max_tokens is None else max_tokens,
            "stream": False,
        }
        if json_mode and route.get("json_mode", True):
            body["response_format"] = {"type": "json_object"}
        # DeepSeek V4 enables thinking by default. Normalization wants a fast,
        # deterministic final JSON, so disable it unless the user explicitly
        # configured otherwise. Non-DeepSeek providers do not get this field.
        base_url = str(route.get("base_url") or "")
        thinking_mode = route.get("thinking_mode", "disabled")
        if "deepseek.com" in base_url and thinking_mode in {"enabled", "disabled"}:
            body["thinking"] = {"type": thinking_mode}
        started = time.perf_counter()
        attempts = 0
        tried_without_json = False
        while attempts < 3:
            attempts += 1
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(float(route.get("timeout_seconds", 240)), connect=20.0)
                ) as client:
                    response = client.post(url, headers=self._headers(route), json=body)
            except httpx.TimeoutException as exc:
                raise LLMError("大模型请求超时。", code="llm_timeout", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"连接大模型失败：{exc}", code="llm_network", retryable=True) from exc

            if response.status_code == 400 and "response_format" in body and not tried_without_json:
                tried_without_json = True
                body.pop("response_format", None)
                continue
            if response.status_code in {401, 403}:
                raise LLMError(
                    f"大模型鉴权失败（HTTP {response.status_code}），请检查 API Key。",
                    code="llm_unauthorized",
                    retryable=False,
                )
            if response.status_code == 429:
                if attempts >= 3:
                    raise LLMError("大模型触发限流（429），请稍后重试。", code="llm_rate_limited", retryable=True)
                time.sleep(3 * attempts)
                continue
            if response.status_code >= 500:
                if attempts >= 3:
                    raise LLMError(
                        f"大模型服务错误（HTTP {response.status_code}）：{response.text[:400]}",
                        code="llm_server_error",
                        retryable=True,
                    )
                time.sleep(2 * attempts)
                continue
            if response.status_code >= 400:
                raise LLMError(
                    f"大模型请求失败（HTTP {response.status_code}）：{response.text[:600]}",
                    code="llm_client_error",
                    retryable=False,
                )
            try:
                payload = response.json()
                choice = payload["choices"][0]
                message = choice.get("message", {})
                content = message.get("content") or ""
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError("大模型返回了无法解析的响应。", code="llm_bad_response", retryable=False) from exc
            if not str(content).strip():
                reasoning = message.get("reasoning_content") if isinstance(message, dict) else ""
                if reasoning:
                    raise LLMError(
                        "大模型只返回了推理内容，没有最终 JSON。请关闭思考模式，或换用 deepseek-flash。",
                        code="llm_no_content",
                        retryable=False,
                    )
                raise LLMError("大模型返回空内容。", code="llm_empty", retryable=True)
            usage = payload.get("usage") or {}
            return {
                "content": str(content),
                "model": payload.get("model") or route.get("model"),
                "usage": usage,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "attempts": attempts,
            }
        raise LLMError("大模型请求重试耗尽。", code="llm_retry_exhausted", retryable=True)

    def test(self, route_id: str | None = None) -> dict[str, Any]:
        response = self.complete(
            route_id,
            [
                {"role": "system", "content": '只输出 JSON：{"ok": true}'},
                {"role": "user", "content": "ping"},
            ],
            json_mode=True,
            max_tokens=32,
            temperature=0,
        )
        return {
            "ok": True,
            "model": response["model"],
            "latency_ms": response["latency_ms"],
            "preview": response["content"][:200],
        }
