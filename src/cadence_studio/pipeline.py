"""Persistent annotation queue and item processing pipeline."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ConfigStore
from .db import Database
from .hf_endpoints import EndpointError, HFEndpointManager
from .inference import AudioInferenceClient, InferenceError
from .llm import LLMClient, LLMError
from .media import MediaError, prepare_inference_audio, probe_audio
from .modules import BatchSpec
from .normalizer import MODULE_OUTPUT_KEYS, NormalizationError, Normalizer, result_summary
from .prompts import build_audio_prompt, build_normalizer_messages
from .taxonomy import get_taxonomy


class BatchStateError(RuntimeError):
    pass


class CanceledError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def retry_at(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _route_configured(route: dict[str, Any], config: ConfigStore) -> tuple[bool, str]:
    token = config.secrets.get(route.get("api_key_secret", "hf_token"))
    if route.get("provider") == "huggingface":
        if route.get("hf_namespace") and route.get("hf_endpoint_name") and token:
            return True, ""
        if route.get("base_url") and token:
            return True, ""
        return False, "请填写 Hugging Face namespace、端点名称和令牌，或直接填写 Inference URL。"
    if route.get("base_url"):
        return True, ""
    return False, "请填写端点 URL。"


class WorkManager:
    def __init__(
        self,
        config: ConfigStore,
        db: Database,
        endpoints: HFEndpointManager,
        inference: AudioInferenceClient,
        llm: LLMClient,
    ):
        self.config = config
        self.db = db
        self.endpoints = endpoints
        self.inference = inference
        self.llm = llm
        self.taxonomy = get_taxonomy()
        self.normalizer = Normalizer(self.taxonomy)
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cadence-worker")
        self._futures: dict[str, Future] = {}
        self._active_routes: dict[str, int] = {}
        self._last_activity: dict[str, float] = {}
        self._auto_paused: set[str] = set()
        self._warm_locks: dict[str, float] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_pause_check = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        interrupted = self.db.reset_interrupted()
        if interrupted:
            self.db.add_event("system", f"检测到上次未完成任务，已重新入队 {interrupted} 个", level="warn")
        self._thread = threading.Thread(target=self._loop, name="cadence-scheduler", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def wake(self) -> None:
        """Nudge the scheduler after a batch is created or retried."""
        route_id = self._active_route_id()
        if route_id:
            self._last_activity[route_id] = time.time()
            self._auto_paused.discard(route_id)

    def _active_route_id(self) -> str | None:
        try:
            return self.config.inference_route()["id"]
        except Exception:  # noqa: BLE001
            return None

    # -------------------------------------------------------------------- actions
    def route_for_batch(self, batch: dict[str, Any]) -> tuple[str, str]:
        snapshot = batch.get("route_snapshot") or {}
        route_id = snapshot.get("inference_route_id") or self.config.get()["inference"]["active_route_id"]
        llm_id = snapshot.get("llm_route_id") or self.config.get()["llm"]["active_route_id"]
        return route_id, llm_id

    def validate_batch_config(self, batch: dict[str, Any]) -> tuple[str, str]:
        route_id, llm_id = self.route_for_batch(batch)
        try:
            route = self.config.inference_route(route_id)
        except KeyError as exc:
            raise BatchStateError(f"批次使用的推理路由已被删除：{route_id}") from exc
        ok, reason = _route_configured(route, self.config)
        if not ok:
            raise BatchStateError(f"推理端点未配置：{reason}")
        try:
            llm_route = self.config.llm_route(llm_id)
        except KeyError as exc:
            raise BatchStateError(f"批次使用的文字模型路由已被删除：{llm_id}") from exc
        if not llm_route.get("base_url") or not llm_route.get("model"):
            raise BatchStateError("文字模型未配置：请填写 API 地址与模型名。")
        return route_id, llm_id

    def start_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.db.get_batch(batch_id)
        if not batch:
            raise BatchStateError("批次不存在")
        if batch["status"] in {"completed", "completed_with_errors", "canceled"}:
            raise BatchStateError("该批次已经结束，请使用“重试失败项”或新建批次。")
        if batch["counts"]["total"] == 0:
            raise BatchStateError("批次中没有音频。")
        route_id, _ = self.validate_batch_config(batch)
        self.db.update_batch(
            batch_id,
            status="queued",
            started_at=batch.get("started_at") or utc_now(),
            finished_at=None,
        )
        self.db.add_event("batch_started", "批次已加入处理队列", batch_id=batch_id)
        self.warm_route(route_id)
        return self.db.get_batch(batch_id) or batch

    def pause_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.db.get_batch(batch_id)
        if not batch:
            raise BatchStateError("批次不存在")
        if batch["status"] not in {"queued", "running"}:
            raise BatchStateError("只有排队中或运行中的批次可以暂停。")
        self.db.update_batch(batch_id, status="paused")
        self.db.add_event("batch_paused", "批次已暂停；正在处理的音频会完成", batch_id=batch_id, level="warn")
        return self.db.get_batch(batch_id) or batch

    def resume_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.db.get_batch(batch_id)
        if not batch:
            raise BatchStateError("批次不存在")
        if batch["status"] != "paused":
            raise BatchStateError("只有已暂停的批次可以继续。")
        self.validate_batch_config(batch)
        self.db.update_batch(batch_id, status="queued")
        self.db.add_event("batch_resumed", "批次已继续", batch_id=batch_id)
        route_id, _ = self.route_for_batch(batch)
        self.warm_route(route_id)
        return self.db.get_batch(batch_id) or batch

    def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.db.get_batch(batch_id)
        if not batch:
            raise BatchStateError("批次不存在")
        if batch["status"] in {"completed", "completed_with_errors"}:
            raise BatchStateError("批次已经完成，不能取消。")
        self.db.set_batch_items_status(batch_id, ("queued",), "canceled")
        self.db.update_batch(batch_id, status="canceled", finished_at=utc_now())
        self.db.add_event("batch_canceled", "批次已取消；正在处理的单项可能仍会完成", batch_id=batch_id, level="warn")
        return self.db.get_batch(batch_id) or batch

    def retry_failed(self, batch_id: str) -> dict[str, Any]:
        batch = self.db.get_batch(batch_id)
        if not batch:
            raise BatchStateError("批次不存在")
        route_id, _ = self.validate_batch_config(batch)
        items = self.db.list_items(batch_id, status="failed", limit=10000, full=True)["items"]
        for item in items:
            self.db.retry_item(item["id"], normalize_only=bool(item.get("raw_text")))
        self.db.update_batch(batch_id, status="queued", finished_at=None)
        self.db.add_event("batch_retry", f"已重新排队 {len(items)} 个失败项", batch_id=batch_id)
        self.warm_route(route_id)
        return self.db.get_batch(batch_id) or batch

    def warm_route(self, route_id: str) -> None:
        now = time.time()
        with self._lock:
            if now - self._warm_locks.get(route_id, 0) < 30:
                return
            self._warm_locks[route_id] = now
        threading.Thread(
            target=self._warm_route_worker, args=(route_id,), name=f"warm-{route_id}", daemon=True
        ).start()

    def _warm_route_worker(self, route_id: str) -> None:
        try:
            status = self.endpoints.ensure_ready(
                route_id,
                auto_resume=bool(self.config.get()["inference"]["lifecycle"].get("auto_resume", True)),
            )
            self.endpoints.invalidate(route_id)
            self.db.add_event(
                "endpoint_ready",
                f"端点 {status['route_name']} 已就绪",
                data={"state": status["state"], "url": status["url"]},
            )
        except Exception as exc:  # noqa: BLE001
            self.db.add_event(
                "endpoint_warm_failed",
                f"端点预热未完成：{exc}",
                level="warn",
                data={"route_id": route_id},
            )

    # -------------------------------------------------------------------- scheduler
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._prune()
                self._schedule()
                self._maybe_auto_pause()
            except Exception as exc:  # noqa: BLE001
                self.db.add_event("scheduler_error", f"调度器异常：{exc}", level="error")
            self._stop.wait(1.2)

    def _prune(self) -> None:
        with self._lock:
            done = [item_id for item_id, future in self._futures.items() if future.done()]
            for item_id in done:
                self._futures.pop(item_id, None)

    def _schedule(self) -> None:
        settings = self.config.get()["processing"]
        max_parallel = max(1, int(settings.get("max_parallel_items", 4)))
        with self._lock:
            active_total = len(self._futures)
        if active_total >= max_parallel:
            return
        candidates = self.db.queued_items(limit=40)
        if not candidates:
            return
        for item in candidates:
            if len(self._futures) >= max_parallel:
                break
            batch = self.db.get_batch(item["batch_id"])
            if not batch:
                continue
            try:
                route_id, _ = self.route_for_batch(batch)
                route = self.config.inference_route(route_id)
            except KeyError:
                continue
            per_route_limit = max(1, int(route.get("max_concurrency", 1)))
            if self._active_routes.get(route_id, 0) >= per_route_limit:
                continue
            claimed = self.db.claim_item(item["id"], "preprocessing")
            if not claimed:
                continue
            self.db.update_batch(item["batch_id"], status="running", started_at=batch.get("started_at") or utc_now())
            with self._lock:
                self._futures[item["id"]] = self._executor.submit(self._process_wrapper, item["id"], route_id)
                self._active_routes[route_id] = self._active_routes.get(route_id, 0) + 1
                self._last_activity[route_id] = time.time()
                self._auto_paused.discard(route_id)
            self.db.add_event(
                "item_started",
                f"开始处理 {item['file_name']}",
                batch_id=item["batch_id"],
                item_id=item["id"],
            )

    def _process_wrapper(self, item_id: str, route_id: str) -> None:
        try:
            self._process_item(item_id, route_id)
        except CanceledError:
            self.db.set_item_state(item_id, "canceled", "canceled", 0, "canceled", "批次已取消")
        except Exception as exc:  # noqa: BLE001
            # A last-resort guard: never leave an item hanging in a running state.
            self.db.set_item_state(item_id, "failed", "failed", 0, "worker_crash", f"处理线程异常：{exc}")
            item = self.db.get_item(item_id)
            if item:
                self.db.add_event(
                    "item_failed",
                    f"{item['file_name']} 处理异常：{exc}",
                    batch_id=item["batch_id"],
                    item_id=item_id,
                    level="error",
                )
                self.db.refresh_batch_status(item["batch_id"])
        finally:
            with self._lock:
                self._active_routes[route_id] = max(0, self._active_routes.get(route_id, 0) - 1)
                self._last_activity[route_id] = time.time()
            item = self.db.get_item(item_id)
            if item:
                self.db.refresh_batch_status(item["batch_id"])

    def _update_stage(self, item, stage: str, message: str, progress: int, status: str = "inferencing") -> None:
        self.db.update_item(item["id"], status=status, stage=stage, progress=progress)
        self.db.add_event(
            stage,
            f"{item['file_name']}：{message}",
            batch_id=item["batch_id"],
            item_id=item["id"],
        )

    def _is_canceled(self, item_id: str) -> bool:
        current = self.db.get_item(item_id)
        return bool(current and current["status"] == "canceled")

    def _process_item(self, item_id: str, route_id: str) -> None:
        started = time.perf_counter()
        item = self.db.get_item(item_id)
        if not item:
            return
        batch = self.db.get_batch(item["batch_id"])
        if not batch:
            raise BatchStateError("批次不存在")
        spec = BatchSpec.model_validate(batch["spec"])
        raw_text = item.get("raw_text") or ""
        timings: dict[str, Any] = {}
        route = self.config.inference_route(route_id)
        llm_id = batch.get("route_snapshot", {}).get("llm_route_id") or self.config.get()["llm"]["active_route_id"]
        llm_route = self.config.llm_route(llm_id)

        try:
            # 1. Media preparation
            if not raw_text:
                if self._is_canceled(item_id):
                    raise CanceledError()
                self.db.update_item(
                    item_id,
                    status="preprocessing",
                    stage="preprocessing",
                    progress=8,
                    inference_route_id=route_id,
                    inference_model=route.get("model", ""),
                )
                media_started = time.perf_counter()
                source = Path(item["stored_path"])
                if not source.exists():
                    raise MediaError(f"音频文件不存在：{source.name}")
                probe = probe_audio(source)
                if not probe.get("duration_sec"):
                    raise MediaError("无法读取音频时长，请确认文件没有损坏。")
                max_seconds = int(route.get("max_audio_seconds", 1200))
                if probe["duration_sec"] > max_seconds + 1:
                    raise MediaError(
                        f"音频时长 {probe['duration_sec'] / 60:.1f} 分钟，超过当前端点上限 {max_seconds / 60:.0f} 分钟。"
                    )
                inference_path = source
                if self.config.get()["processing"].get("transcode", True):
                    inference_path = source.parent / "inference" / f"{item_id}.mp3"
                    if not inference_path.exists():
                        self._update_stage(item, "transcoding", "转码压缩", 12, status="preprocessing")
                        prepare_inference_audio(
                            source,
                            inference_path,
                            bitrate=self.config.get()["processing"].get("transcode_bitrate", "96k"),
                            max_seconds=max_seconds,
                        )
                    probe = probe_audio(inference_path) or probe
                self.db.update_item(
                    item_id,
                    duration_sec=probe.get("duration_sec"),
                    sample_rate=probe.get("sample_rate"),
                    channels=probe.get("channels"),
                    bitrate=probe.get("bitrate"),
                    inference_path=str(inference_path),
                    progress=18,
                )
                timings["preprocess_ms"] = int((time.perf_counter() - media_started) * 1000)

                # 2. Audio understanding
                if self._is_canceled(item_id):
                    raise CanceledError()
                metadata = {
                    "file_name": item["file_name"],
                    "duration_sec": probe.get("duration_sec"),
                    "sample_rate": probe.get("sample_rate"),
                    "channels": probe.get("channels"),
                }
                prompt = build_audio_prompt(spec, metadata, self.taxonomy)
                timings["audio_prompt_chars"] = len(prompt)
                self.db.update_item(
                    item_id,
                    status="inferencing",
                    stage="endpoint_wait",
                    progress=22,
                    timings_json=timings,
                )
                self.db.add_event(
                    "inference_started",
                    f"{item['file_name']}：发送到 {route.get('name', route_id)}",
                    batch_id=item["batch_id"],
                    item_id=item_id,
                )

                def progress_cb(stage: str, label: str) -> None:
                    progress = {"checking_endpoint": 24, "inferencing": 35}.get(stage, 35)
                    self.db.update_item(item_id, status="inferencing", stage=stage, progress=progress)

                response = self.inference.annotate(
                    route_id,
                    inference_path,
                    prompt,
                    spec.model_dump(),
                    progress_cb=progress_cb,
                )
                raw_text = response["text"]
                timings["inference_ms"] = response["latency_ms"]
                timings["inference_usage"] = response.get("usage", {})
                timings["inference_model"] = response.get("model")
                timings["inference_revision"] = response.get("revision")
                self.db.update_item(
                    item_id,
                    status="normalizing",
                    stage="raw_received",
                    progress=60,
                    raw_text=raw_text,
                    timings_json=timings,
                )
                self.db.add_usage(
                    stage="inference",
                    provider="huggingface",
                    model=response.get("model") or route.get("model", ""),
                    latency_ms=response["latency_ms"],
                    batch_id=item["batch_id"],
                    item_id=item_id,
                    meta={"usage": response.get("usage", {})},
                )
                item = self.db.get_item(item_id) or item
            else:
                timings["resumed_from_raw"] = True

            # 3. LLM normalization (with one repair attempt)
            if self._is_canceled(item_id):
                raise CanceledError()
            self._update_stage(item, "normalizing", "规范化与标签校验", 70, status="normalizing")
            normalization_started = time.perf_counter()
            max_chars = int(self.config.get()["llm"]["normalization"].get("max_catalog_chars", 36000))
            repair_attempts = int(self.config.get()["llm"]["normalization"].get("repair_attempts", 1))
            metadata = {
                "file_name": item["file_name"],
                "duration_sec": item.get("duration_sec"),
                "sample_rate": item.get("sample_rate"),
                "channels": item.get("channels"),
            }
            last_error: Exception | None = None
            normalized: dict[str, Any] | None = None
            llm_content = ""
            for attempt in range(repair_attempts + 1):
                repair_note = str(last_error) if last_error else ""
                messages = build_normalizer_messages(
                    spec,
                    raw_text,
                    metadata,
                    taxonomy=self.taxonomy,
                    max_catalog_chars=max_chars,
                    repair_note=repair_note,
                )
                llm_response = self.llm.complete(llm_id, messages, json_mode=True)
                llm_content = llm_response["content"]
                self.db.update_item(item_id, llm_raw_text=llm_content, progress=82)
                self.db.add_usage(
                    stage="normalization",
                    provider=llm_route.get("provider", ""),
                    model=llm_response.get("model") or llm_route.get("model", ""),
                    latency_ms=llm_response["latency_ms"],
                    batch_id=item["batch_id"],
                    item_id=item_id,
                    meta={"usage": llm_response.get("usage", {}), "attempt": attempt + 1},
                )
                try:
                    normalized = self.normalizer.parse_and_validate(llm_content, spec, metadata)
                    missing = [
                        MODULE_OUTPUT_KEYS[module]
                        for module in spec.modules
                        if MODULE_OUTPUT_KEYS[module] not in normalized
                    ]
                    if missing and attempt < repair_attempts:
                        raise NormalizationError(f"缺少模块：{', '.join(missing)}")
                    if missing:
                        normalized.setdefault("_meta", {}).setdefault("warnings", []).extend(
                            [f"模型未返回模块：{', '.join(missing)}"]
                        )
                    break
                except NormalizationError as exc:
                    last_error = exc
                    if attempt >= repair_attempts:
                        raise
            if normalized is None:
                raise NormalizationError(str(last_error or "规范化失败"), raw=llm_content)
            timings["normalization_ms"] = int((time.perf_counter() - normalization_started) * 1000)
            timings["llm_attempts"] = repair_attempts + 1
            timings["total_ms"] = int((time.perf_counter() - started) * 1000)
            summary = result_summary(normalized)
            self.db.update_item(
                item_id,
                status="saving",
                stage="saving",
                progress=94,
                llm_route_id=llm_id,
                llm_model=llm_route.get("model", ""),
                normalized_json=normalized,
                summary_json=summary,
                timings_json=timings,
                error_code="",
                error_message="",
                finished_at=utc_now(),
            )
            self.db.update_item(item_id, status="completed", stage="completed", progress=100, finished_at=utc_now())
            self.db.add_event(
                "item_completed",
                f"{item['file_name']} 标注完成",
                batch_id=item["batch_id"],
                item_id=item_id,
                data={"summary": summary},
            )
            self.endpoints.invalidate(route_id)
        except CanceledError:
            self.db.set_item_state(item_id, "canceled", "canceled", 0, "canceled", "批次已取消")
            raise
        except (InferenceError, EndpointError, LLMError, MediaError, NormalizationError, BatchStateError) as exc:
            self._handle_failure(item, batch, exc, raw_text, timings, route_id)
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(item, batch, exc, raw_text, timings, route_id)

    def _handle_failure(
        self,
        item: dict[str, Any],
        batch: dict[str, Any],
        exc: Exception,
        raw_text: str,
        timings: dict[str, Any],
        route_id: str,
    ) -> None:
        attempts = int(item.get("attempts") or 0) + 1
        max_attempts = int(self.config.get()["processing"].get("max_attempts", 3))
        retryable = bool(getattr(exc, "retryable", False))
        code = getattr(exc, "code", "processing_error")
        if isinstance(exc, NormalizationError):
            code = "normalization_failed"
            retryable = True
        if isinstance(exc, MediaError):
            retryable = False
        if isinstance(exc, BatchStateError):
            retryable = False
        can_retry = retryable and attempts < max_attempts
        message = self._friendly_error(exc)
        timings["total_ms"] = timings.get("total_ms", 0)
        timings["failed_at"] = utc_now()
        fields: dict[str, Any] = {
            "attempts": attempts,
            "error_code": code,
            "error_message": message,
            "timings_json": timings,
        }
        if raw_text:
            fields["raw_text"] = raw_text
        if can_retry:
            delay = max(2, int(self.config.get()["processing"].get("retry_backoff_seconds", 5))) * attempts
            self.db.update_item(
                item["id"],
                status="queued",
                stage="resume_normalize" if raw_text else "retry_wait",
                progress=0,
                next_retry_at=retry_at(delay),
                **fields,
            )
            self.db.add_event(
                "item_retry",
                f"{item['file_name']} 第 {attempts} 次失败，{delay}s 后重试：{message}",
                batch_id=item["batch_id"],
                item_id=item["id"],
                level="warn",
                data={"code": code},
            )
        else:
            self.db.update_item(
                item["id"],
                status="failed",
                stage="failed",
                progress=0,
                finished_at=utc_now(),
                **fields,
            )
            self.db.add_event(
                "item_failed",
                f"{item['file_name']} 处理失败：{message}",
                batch_id=item["batch_id"],
                item_id=item["id"],
                level="error",
                data={"code": code, "attempts": attempts},
            )
        try:
            self.db.refresh_batch_status(item["batch_id"])
        except Exception:  # noqa: BLE001
            pass
        self.endpoints.invalidate(route_id)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc).strip()
        if isinstance(exc, InferenceError):
            hints = {
                "timeout": "可尝试缩短音频、降低并发，或检查端点日志。",
                "server_error": "端点可能显存不足或正在冷启动；请查看 Hugging Face Logs。",
                "unauthorized": "请检查 Hugging Face 令牌权限。",
                "empty_response": "端点响应格式与 Cadence 适配器不匹配。",
            }
            hint = hints.get(exc.code, "")
            return f"{text}{(' ' + hint) if hint and hint not in text else ''}"
        if isinstance(exc, LLMError):
            return text
        if isinstance(exc, NormalizationError):
            return f"大模型输出未通过结构校验：{text}"
        return text or exc.__class__.__name__

    # ------------------------------------------------------------------ auto pause
    def _maybe_auto_pause(self) -> None:
        now = time.time()
        if now - self._last_pause_check < 10:
            return
        self._last_pause_check = now
        lifecycle = self.config.get()["inference"]["lifecycle"]
        if not lifecycle.get("auto_pause", True):
            return
        grace = int(lifecycle.get("pause_grace_seconds", 120))
        for route in self.config.get()["inference"]["routes"]:
            route_id = route["id"]
            if self._active_routes.get(route_id, 0) > 0:
                continue
            if route_id in self._auto_paused:
                continue
            last = self._last_activity.get(route_id, 0)
            if not last or now - last < grace:
                continue
            try:
                status = self.endpoints.status(route_id)
            except Exception:  # noqa: BLE001
                continue
            if status.get("state") != "running" or not status.get("managed"):
                self._auto_paused.add(route_id)
                continue
            self._auto_paused.add(route_id)

            def pause(rid=route_id):
                try:
                    self.endpoints.pause(rid)
                    self.db.add_event(
                        "endpoint_auto_paused",
                        "队列空闲，已自动暂停端点以节省费用",
                        data={"route_id": rid},
                    )
                except Exception as exc:  # noqa: BLE001
                    self.db.add_event(
                        "endpoint_pause_failed",
                        f"自动暂停端点失败：{exc}",
                        level="warn",
                        data={"route_id": rid},
                    )
                finally:
                    self.endpoints.invalidate(rid)

            threading.Thread(target=pause, daemon=True).start()
