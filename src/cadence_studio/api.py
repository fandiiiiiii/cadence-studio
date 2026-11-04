"""HTTP API for the local Cadence Studio workbench."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import AUDIO_DIR, DATA_DIR, TMP_DIR
from .demo import create_demo_batch, remove_demo
from .exports import export_batch
from .hardware import PROFILES
from .media import (
    ALLOWED_EXTENSIONS,
    MIME_BY_EXT,
    MediaError,
    delete_tree,
    probe_audio,
    safe_filename,
    save_stream_to_file,
    sha256_file,
)
from .modules import ALL_MODULE_IDS, BatchSpec, module_catalog
from .normalizer import Normalizer
from .pipeline import BatchStateError
from .prompts import prompt_metrics
from .services import SERVICES
from .taxonomy import get_taxonomy

router = APIRouter(prefix="/api")
taxonomy = get_taxonomy()
normalizer = Normalizer(taxonomy)


class SettingsPayload(BaseModel):
    config: dict[str, Any]
    secrets: dict[str, str | None] = Field(default_factory=dict)


class BatchPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=4000)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    owner: str | None = Field(default=None, max_length=120)
    daily_goal: int | None = Field(default=None, ge=1, le=10000)


class ItemPatch(BaseModel):
    review_status: Literal["unreviewed", "approved", "needs_changes"] | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    normalized: dict[str, Any] | None = None


class RetryPayload(BaseModel):
    normalize_only: bool = False


class TestEndpointPayload(BaseModel):
    route_id: str | None = None


def _now_label() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _raise(message: str, status: int = 400, code: str = "bad_request", extra: dict[str, Any] | None = None):
    detail: dict[str, Any] = {"message": message, "code": code}
    if extra:
        detail.update(extra)
    raise HTTPException(status_code=status, detail=detail)


def _validate_settings(config: dict[str, Any]) -> None:
    inference = config.get("inference") or {}
    routes = inference.get("routes") or []
    if not routes:
        _raise("至少保留一个推理端点路由。")
    ids = set()
    for route in routes:
        rid = str(route.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", rid):
            _raise("推理路由 ID 只能包含小写字母、数字、下划线和连字符（2–41 字符）。")
        if rid in ids:
            _raise(f"推理路由 ID 重复：{rid}")
        ids.add(rid)
        if route.get("adapter") not in {"cadence", "openai_audio"}:
            _raise("推理适配器必须是 cadence 或 openai_audio。")
        if route.get("base_url") and not str(route["base_url"]).startswith(("http://", "https://")):
            _raise("推理端点 URL 必须以 http:// 或 https:// 开头。")
        try:
            concurrency = int(route.get("max_concurrency", 1))
        except (TypeError, ValueError):
            concurrency = 1
        if not 1 <= concurrency <= 8:
            _raise("单路由并发必须在 1–8 之间。A10G 建议 1。")
        try:
            max_audio = int(route.get("max_audio_seconds", 1200))
            max_tokens = int(route.get("max_new_tokens", 900))
        except (TypeError, ValueError):
            _raise("音频上限与最大输出 tokens 必须是整数。")
        if not 10 <= max_audio <= 1200:
            _raise("音频上限必须在 10–1200 秒之间。")
        if not 128 <= max_tokens <= 4096:
            _raise("最大输出 tokens 必须在 128–4096 之间。")
        if route.get("hardware_profile") and not any(
            profile["id"] == route["hardware_profile"] for profile in PROFILES
        ):
            _raise(f"未知硬件预设：{route['hardware_profile']}")
    if inference.get("active_route_id") not in ids:
        _raise("当前推理路由不存在，请重新选择。")
    llm = config.get("llm") or {}
    llm_routes = llm.get("routes") or []
    if not llm_routes:
        _raise("至少保留一个文字模型路由。")
    llm_ids = set()
    for route in llm_routes:
        rid = str(route.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", rid):
            _raise("文字模型路由 ID 只能包含小写字母、数字、下划线和连字符。")
        if rid in llm_ids:
            _raise(f"文字模型路由 ID 重复：{rid}")
        llm_ids.add(rid)
        base = str(route.get("base_url") or "")
        if not base.startswith(("http://", "https://")):
            _raise("文字模型 API 地址必须以 http:// 或 https:// 开头。")
        if not route.get("model"):
            _raise("文字模型名称不能为空。")
    if llm.get("active_route_id") not in llm_ids:
        _raise("当前文字模型路由不存在，请重新选择。")
    workspace = config.get("workspace") or {}
    try:
        goal = int(workspace.get("daily_goal", 500))
    except (TypeError, ValueError):
        goal = 0
    if not 1 <= goal <= 10000:
        _raise("每日目标必须是 1–10000 首。")
    processing = config.get("processing") or {}
    for key, low, high in (("max_parallel_items", 1, 8), ("max_attempts", 1, 6)):
        try:
            value = int(processing.get(key))
        except (TypeError, ValueError):
            value = low
        if not low <= value <= high:
            _raise(f"{key} 必须在 {low}–{high} 之间。")
    if not config.get("workspace", {}).get("name", "").strip():
        _raise("工作区名称不能为空。")


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": __version__,
        "data_dir": str(DATA_DIR),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
    }


@router.get("/system/overview")
def system_overview() -> dict[str, Any]:
    overview = SERVICES.db.overview()
    config = SERVICES.config.get()
    routes = []
    for route in config["inference"]["routes"]:
        status = SERVICES.endpoints.cached_status(route["id"])
        if status is None:
            status = {
                "route_id": route["id"],
                "route_name": route.get("name", route["id"]),
                "state": "unknown",
                "state_label": "待检查",
                "error": "",
                "managed": bool(route.get("hf_namespace") and route.get("hf_endpoint_name")),
                "url": route.get("base_url", ""),
            }
        routes.append(
            {
                **status,
                "configured": bool(route.get("base_url") or route.get("hf_namespace")),
                "model": route.get("model", ""),
                "enabled": route.get("enabled", True),
                "max_concurrency": route.get("max_concurrency", 1),
            }
        )
    overview["endpoints"] = routes
    overview["active_inference_route_id"] = config["inference"]["active_route_id"]
    overview["daily_goal"] = config.get("workspace", {}).get("daily_goal", 500)
    overview["workspace"] = config.get("workspace", {})
    overview["recent_events"] = SERVICES.db.list_events(limit=8)
    overview["taxonomy_version"] = taxonomy.version
    overview["server"] = {
        "version": __version__,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "data_dir": str(DATA_DIR),
    }
    return overview


@router.get("/hardware-profiles")
def hardware_profiles() -> dict[str, Any]:
    return {
        "profiles": PROFILES,
        "checked_at": "2026-11-05",
        "source": "Hugging Face Inference Endpoints provider API (public list, prices vary)",
        "note": "These are recommendations. The custom Cadence server serializes generation; 1 concurrent request per replica is the safe default.",
    }


@router.get("/workspace")
def get_workspace() -> dict[str, Any]:
    return SERVICES.config.get().get("workspace", {})


@router.patch("/workspace")
def patch_workspace(payload: WorkspacePatch) -> dict[str, Any]:
    config = SERVICES.config.get()
    workspace = config.setdefault("workspace", {})
    if payload.name is not None:
        if not payload.name.strip():
            _raise("工作区名称不能为空。")
        workspace["name"] = payload.name.strip()
    if payload.owner is not None:
        workspace["owner"] = payload.owner.strip()
    if payload.daily_goal is not None:
        workspace["daily_goal"] = payload.daily_goal
    SERVICES.config.replace(config)
    SERVICES.db.add_event("workspace_updated", f"每日目标更新为 {workspace.get('daily_goal')} 首")
    return {"workspace": workspace, "overview": SERVICES.db.overview()}


@router.get("/modules")
def modules() -> dict[str, Any]:
    return {
        "modules": module_catalog(),
        "defaults": [m["id"] for m in module_catalog() if m["default"]],
        "taxonomy_modules": sorted(
            {"genre", "mood", "scene", "instruments", "vocal", "language", "extra"}
        ),
        "all_ids": ALL_MODULE_IDS,
    }


@router.get("/taxonomy")
def get_taxonomy_payload(category: str | None = None, q: str = "", limit: int = 700, offset: int = 0):
    if category or q:
        result = taxonomy.search(q, category, limit=limit, offset=offset)
        return {"summary": taxonomy.summary(), "tags": result["items"], "total": result["total"]}
    return {**taxonomy.canonical_payload(), "summary": taxonomy.summary()}


@router.get("/taxonomy/meta")
def taxonomy_meta() -> dict[str, Any]:
    return taxonomy.summary()


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return SERVICES.config.public()


@router.put("/settings")
def put_settings(payload: SettingsPayload) -> dict[str, Any]:
    try:
        _validate_settings(payload.config)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _raise(f"配置校验失败：{exc}")
    try:
        SERVICES.config.replace(payload.config, payload.secrets)
    except Exception as exc:  # noqa: BLE001
        _raise(f"保存配置失败：{exc}", status=500, code="config_save_failed")
    SERVICES.endpoints.invalidate()
    SERVICES.db.add_event("settings_saved", "设置已保存")
    return SERVICES.config.public()


@router.get("/settings/prompt-metrics")
def settings_prompt_metrics(modules: str = "") -> dict[str, Any]:
    selected = [m for m in modules.split(",") if m in ALL_MODULE_IDS] or list(
        module_catalog()[0]["id"] for _ in range(1)
    )
    try:
        spec = BatchSpec(modules=selected)
    except Exception as exc:  # noqa: BLE001
        _raise(f"模块无效：{exc}")
    return {"metrics": prompt_metrics(spec, taxonomy), "modules": selected}


@router.post("/settings/test/hf")
def test_hf() -> dict[str, Any]:
    try:
        return {"ok": True, **SERVICES.endpoints.whoami()}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": str(exc), "code": getattr(exc, "code", "hf_error")},
        )


@router.post("/settings/test/llm")
def test_llm(payload: TestEndpointPayload) -> dict[str, Any]:
    try:
        return {"ok": True, **SERVICES.llm.test(payload.route_id)}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": str(exc), "code": getattr(exc, "code", "llm_error")},
        )


@router.get("/inference/status")
def inference_status(route_id: str | None = None) -> dict[str, Any]:
    try:
        return SERVICES.endpoints.status(route_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=400,
            content={"state": "unknown", "state_label": "状态未知", "error": str(exc)},
        )


@router.post("/inference/{route_id}/{action}")
def inference_action(route_id: str, action: Literal["resume", "pause", "scale-to-zero"]) -> dict[str, Any]:
    try:
        return SERVICES.endpoints.action(route_id, action)
    except Exception as exc:  # noqa: BLE001
        _raise(str(exc), status=400, code=getattr(exc, "code", "endpoint_error"))


@router.post("/inference/{route_id}/test")
def inference_test(route_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, **SERVICES.inference.health(route_id)}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@router.get("/inference/hf/endpoints")
def hf_endpoint_list(namespace: str = Query(..., min_length=1)) -> dict[str, Any]:
    try:
        return {"items": SERVICES.endpoints.list_hf_endpoints(namespace)}
    except Exception as exc:  # noqa: BLE001
        _raise(str(exc), status=400, code=getattr(exc, "code", "endpoint_list_failed"))


@router.get("/batches")
def list_batches(
    query: str = "",
    status: str = "",
    mode: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return SERVICES.db.list_batches(query=query, status=status, mode=mode, limit=limit, offset=offset)


@router.post("/batches")
def create_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    name: str = Form(""),
    note: str = Form(""),
    spec: str = Form("{}"),
    auto_start: bool = Form(True),
) -> dict[str, Any]:
    if not files:
        _raise("请至少选择一个音频文件。")
    try:
        spec_payload = json.loads(spec or "{}")
        batch_spec = BatchSpec.model_validate(spec_payload)
    except Exception as exc:  # noqa: BLE001
        _raise(f"标注要求无效：{exc}")
    config = SERVICES.config.get()
    max_items = int(config["processing"].get("max_items_per_batch", 1000))
    if len(files) > max_items:
        _raise(f"单批最多 {max_items} 个文件。")
    max_bytes = int(config["processing"].get("max_upload_mb", 512)) * 1024 * 1024
    batch_name = name.strip() or f"批次 {_now_label()}"
    batch_id = f"bat_{int(time.time() * 1000)}_{uuid_short()}"
    batch_dir = AUDIO_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    try:
        for index, upload in enumerate(files, 1):
            original = safe_filename(upload.filename or f"audio-{index}.mp3")
            ext = Path(original).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                warnings.append(f"{upload.filename}：不支持的扩展名，已跳过")
                continue
            item_id = f"itm_{int(time.time() * 1000)}_{uuid_short()}"
            target = batch_dir / f"{item_id}{ext}"
            try:
                size = save_stream_to_file(upload.file, target, max_bytes)
                probe = probe_audio(target)
                if not probe.get("duration_sec"):
                    warnings.append(f"{upload.filename}：未检测到可读音频，已跳过")
                    target.unlink(missing_ok=True)
                    continue
                if probe["duration_sec"] < 2:
                    warnings.append(f"{upload.filename}：短于 2 秒，已跳过")
                    target.unlink(missing_ok=True)
                    continue
                digest = sha256_file(target)
                if digest in seen_hashes:
                    warnings.append(f"{upload.filename}：与本批其他文件重复，已跳过")
                    target.unlink(missing_ok=True)
                    continue
                seen_hashes.add(digest)
                items.append(
                    {
                        "id": item_id,
                        "position": len(items) + 1,
                        "file_name": original,
                        "stored_path": str(target),
                        "inference_path": "",
                        "mime": MIME_BY_EXT.get(ext, upload.content_type or "application/octet-stream"),
                        "size_bytes": size,
                        "sha256": digest,
                        "duration_sec": probe.get("duration_sec"),
                        "sample_rate": probe.get("sample_rate"),
                        "channels": probe.get("channels"),
                        "bitrate": probe.get("bitrate"),
                    }
                )
            except MediaError as exc:
                warnings.append(f"{upload.filename}：{exc}")
                target.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{upload.filename}：导入失败（{exc}）")
                target.unlink(missing_ok=True)
        if not items:
            delete_tree(batch_dir)
            _raise("没有可导入的音频。", extra={"warnings": warnings})
        inference_route = SERVICES.config.inference_route()
        llm_route = SERVICES.config.llm_route()
        route_snapshot = {
            "inference_route_id": inference_route["id"],
            "inference_route": {
                "id": inference_route["id"],
                "name": inference_route.get("name"),
                "model": inference_route.get("model"),
                "adapter": inference_route.get("adapter"),
                "hardware_profile": inference_route.get("hardware_profile", ""),
                "max_concurrency": inference_route.get("max_concurrency", 1),
                "max_audio_seconds": inference_route.get("max_audio_seconds", 1200),
                "max_new_tokens": inference_route.get("max_new_tokens", 900),
            },
            "llm_route_id": llm_route["id"],
            "llm_route": {
                "id": llm_route["id"],
                "name": llm_route.get("name"),
                "model": llm_route.get("model"),
                "thinking_mode": llm_route.get("thinking_mode", ""),
            },
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        batch = SERVICES.db.create_batch(
            batch_name,
            batch_spec.model_dump(),
            route_snapshot,
            note=note.strip(),
            mode="live",
            batch_id=batch_id,
        )
        SERVICES.db.add_items(batch_id, items)
        SERVICES.db.add_event(
            "batch_created",
            f"导入 {len(items)} 个音频",
            batch_id=batch_id,
            data={"warnings": warnings},
        )
        if auto_start:
            try:
                batch = SERVICES.manager.start_batch(batch_id) or batch
            except BatchStateError as exc:
                warnings.append(f"已保存为草稿：{exc}")
        else:
            batch = SERVICES.db.get_batch(batch_id) or batch
        return {"batch": batch, "warnings": warnings, "imported": len(items)}
    except HTTPException:
        if not SERVICES.db.get_batch(batch_id):
            delete_tree(batch_dir)
        raise
    except Exception as exc:  # noqa: BLE001
        if not SERVICES.db.get_batch(batch_id):
            delete_tree(batch_dir)
        _raise(f"创建批次失败：{exc}", status=500, code="batch_create_failed")


def uuid_short() -> str:
    import uuid

    return uuid.uuid4().hex[:6]


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str) -> dict[str, Any]:
    batch = SERVICES.db.get_batch(batch_id)
    if not batch:
        _raise("批次不存在", status=404, code="not_found")
    batch["events"] = SERVICES.db.list_events(batch_id=batch_id, limit=30)
    batch["prompt_metrics"] = prompt_metrics(BatchSpec.model_validate(batch["spec"]), taxonomy)
    return batch


@router.patch("/batches/{batch_id}")
def patch_batch(batch_id: str, payload: BatchPatch) -> dict[str, Any]:
    batch = SERVICES.db.get_batch(batch_id)
    if not batch:
        _raise("批次不存在", status=404, code="not_found")
    fields: dict[str, Any] = {}
    if payload.name is not None:
        if not payload.name.strip():
            _raise("批次名称不能为空。")
        fields["name"] = payload.name.strip()
    if payload.note is not None:
        fields["note"] = payload.note.strip()
    if fields:
        batch = SERVICES.db.update_batch(batch_id, **fields)
    return batch or {}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str) -> dict[str, Any]:
    batch = SERVICES.db.get_batch(batch_id)
    if not batch:
        _raise("批次不存在", status=404, code="not_found")
    if batch["counts"]["running"] > 0:
        _raise("批次仍在处理，请先暂停或等待完成。")
    if batch.get("mode") == "demo":
        remove_demo(SERVICES.db, batch_id)
        return {"ok": True}
    batch_dir = AUDIO_DIR / batch_id
    if batch_dir.exists() and AUDIO_DIR in batch_dir.parents:
        delete_tree(batch_dir)
    SERVICES.db.delete_batch(batch_id)
    return {"ok": True}


@router.get("/batches/{batch_id}/items")
def batch_items(
    batch_id: str,
    query: str = "",
    status: str = "",
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort: str = "position",
) -> dict[str, Any]:
    if not SERVICES.db.get_batch(batch_id):
        _raise("批次不存在", status=404, code="not_found")
    return SERVICES.db.list_items(batch_id, query=query, status=status, limit=limit, offset=offset, sort=sort)


@router.get("/batches/{batch_id}/events")
def batch_events(batch_id: str, since_id: int = 0, limit: int = 100) -> dict[str, Any]:
    return {"items": SERVICES.db.list_events(since_id=since_id, batch_id=batch_id, limit=limit)}


@router.post("/batches/{batch_id}/start")
def start_batch(batch_id: str) -> dict[str, Any]:
    try:
        return {"batch": SERVICES.manager.start_batch(batch_id)}
    except BatchStateError as exc:
        _raise(str(exc), status=409, code="batch_state")
    except Exception as exc:  # noqa: BLE001
        _raise(str(exc), status=500, code="start_failed")


@router.post("/batches/{batch_id}/pause")
def pause_batch(batch_id: str) -> dict[str, Any]:
    try:
        return {"batch": SERVICES.manager.pause_batch(batch_id)}
    except BatchStateError as exc:
        _raise(str(exc), status=409, code="batch_state")


@router.post("/batches/{batch_id}/resume")
def resume_batch(batch_id: str) -> dict[str, Any]:
    try:
        return {"batch": SERVICES.manager.resume_batch(batch_id)}
    except BatchStateError as exc:
        _raise(str(exc), status=409, code="batch_state")


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str) -> dict[str, Any]:
    try:
        return {"batch": SERVICES.manager.cancel_batch(batch_id)}
    except BatchStateError as exc:
        _raise(str(exc), status=409, code="batch_state")


@router.post("/batches/{batch_id}/retry-failed")
def retry_failed(batch_id: str) -> dict[str, Any]:
    try:
        return {"batch": SERVICES.manager.retry_failed(batch_id)}
    except BatchStateError as exc:
        _raise(str(exc), status=409, code="batch_state")


@router.get("/batches/{batch_id}/export")
def export(batch_id: str, format: str = Query("xlsx")):
    batch = SERVICES.db.get_batch(batch_id)
    if not batch:
        _raise("批次不存在", status=404, code="not_found")
    items = SERVICES.db.list_items(batch_id, limit=10000, full=True)["items"]
    if not items:
        _raise("批次没有可导出的音频。", status=400, code="empty")
    fmt = format.lower()
    if fmt not in {"xlsx", "json", "md", "csv", "zip"}:
        _raise("导出格式必须是 xlsx、json、md、csv 或 zip。")
    try:
        path = export_batch(batch, items, fmt)
    except Exception as exc:  # noqa: BLE001
        _raise(f"导出失败：{exc}", status=500, code="export_failed")
    return FileResponse(
        path,
        filename=path.name,
        media_type={
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "json": "application/json",
            "md": "text/markdown; charset=utf-8",
            "csv": "text/csv; charset=utf-8",
            "zip": "application/zip",
        }.get(fmt, "application/octet-stream"),
    )


@router.get("/items/{item_id}")
def item_detail(item_id: str) -> dict[str, Any]:
    item = SERVICES.db.get_item(item_id)
    if not item:
        _raise("音频不存在", status=404, code="not_found")
    batch = SERVICES.db.get_batch(item["batch_id"])
    item["batch"] = {"id": batch["id"], "name": batch["name"], "spec": batch["spec"]} if batch else None
    return item


@router.patch("/items/{item_id}")
def patch_item(item_id: str, payload: ItemPatch) -> dict[str, Any]:
    item = SERVICES.db.get_item(item_id)
    if not item:
        _raise("音频不存在", status=404, code="not_found")
    batch = SERVICES.db.get_batch(item["batch_id"])
    if not batch:
        _raise("批次不存在", status=404, code="not_found")
    fields: dict[str, Any] = {}
    if payload.review_status is not None:
        fields["review_status"] = payload.review_status
    if payload.review_note is not None:
        fields["review_note"] = payload.review_note.strip()
    if payload.normalized is not None:
        try:
            spec = BatchSpec.model_validate(batch["spec"])
            validated = normalizer.validate(payload.normalized, spec, item)
            validated.setdefault("_meta", {})["manual_edit"] = True
            validated["_meta"]["edited_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            from .normalizer import result_summary

            fields["normalized_json"] = validated
            fields["summary_json"] = result_summary(validated)
        except Exception as exc:  # noqa: BLE001
            _raise(f"手工编辑不符合规范：{exc}")
    if fields:
        if "normalized_json" in fields:
            SERVICES.db.update_item(
                item_id,
                review_status=fields.pop("review_status", item.get("review_status", "unreviewed")),
                normalized_json=fields.pop("normalized_json"),
                summary_json=fields.pop("summary_json"),
            )
        if fields:
            SERVICES.db.update_item(item_id, **fields)
        SERVICES.db.add_event("item_reviewed", "人工复核记录已更新", batch_id=item["batch_id"], item_id=item_id)
    return SERVICES.db.get_item(item_id) or {}


@router.post("/items/{item_id}/retry")
def retry_item(item_id: str, payload: RetryPayload) -> dict[str, Any]:
    item = SERVICES.db.get_item(item_id)
    if not item:
        _raise("音频不存在", status=404, code="not_found")
    batch = SERVICES.db.get_batch(item["batch_id"])
    if not batch:
        _raise("批次不存在", status=404, code="not_found")
    try:
        SERVICES.manager.validate_batch_config(batch)
    except BatchStateError as exc:
        _raise(str(exc), status=409, code="config")
    if payload.normalize_only and not item.get("raw_text"):
        _raise("该项目没有可复用的音频模型原始结果，请重新运行完整流程。")
    SERVICES.db.retry_item(item_id, normalize_only=payload.normalize_only)
    SERVICES.db.update_batch(item["batch_id"], status="queued", finished_at=None)
    route_id, _ = SERVICES.manager.route_for_batch(batch)
    SERVICES.manager.warm_route(route_id)
    return {"item": SERVICES.db.get_item(item_id), "batch": SERVICES.db.get_batch(item["batch_id"])}


def _range_response(path: Path, request: Request, media_type: str) -> FileResponse | StreamingResponse:
    size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    start_raw, end_raw = match.groups()
    if start_raw:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    else:
        suffix = int(end_raw or 0)
        start = max(0, size - suffix)
        end = size - 1
    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))
    length = end - start + 1

    def iter_file():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "private, max-age=3600",
    }
    return StreamingResponse(iter_file(), status_code=206, headers=headers, media_type=media_type)


@router.get("/items/{item_id}/audio")
def item_audio(item_id: str, request: Request):
    item = SERVICES.db.get_item(item_id)
    if not item:
        _raise("音频不存在", status=404, code="not_found")
    path = Path(item["stored_path"])
    if not path.exists() or AUDIO_DIR not in path.parents:
        _raise("音频文件不可用", status=404, code="audio_missing")
    media_type = item.get("mime") or MIME_BY_EXT.get(path.suffix.lower(), "audio/mpeg")
    return _range_response(path, request, media_type)


@router.get("/items/{item_id}/export")
def item_export(item_id: str, format: str = "json"):
    item = SERVICES.db.get_item(item_id)
    if not item:
        _raise("音频不存在", status=404, code="not_found")
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", Path(item["file_name"]).stem)[:80]
    target = TMP_DIR / f"{safe}-{item_id}.{format}"
    if format == "json":
        payload = {
            "file_name": item["file_name"],
            "batch_id": item["batch_id"],
            "raw_audio_model_output": item["raw_text"],
            "llm_raw_output": item["llm_raw_text"],
            "normalized": item["normalized"],
            "timings": item["timings"],
            "error": {"code": item["error_code"], "message": item["error_message"]} if item["error_code"] else None,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif format == "md":
        normalized = json.dumps(item["normalized"], ensure_ascii=False, indent=2) if item["normalized"] else "—"
        target.write_text(
            f"# {item['file_name']}\n\n## 音频模型原始输出\n\n```text\n{item['raw_text']}\n```\n\n"
            f"## 规范化结果\n\n```json\n{normalized}\n```\n",
            encoding="utf-8",
        )
    else:
        _raise("单曲导出只支持 json 或 md。")
    return FileResponse(target, filename=target.name)


@router.post("/demo/seed")
def seed_demo() -> dict[str, Any]:
    try:
        batch = create_demo_batch(SERVICES.db)
        return {"batch": batch}
    except Exception as exc:  # noqa: BLE001
        _raise(f"创建演示批次失败：{exc}", status=500, code="demo_failed")


@router.get("/activity")
def activity(limit: int = Query(100, ge=1, le=300), level: str = "") -> dict[str, Any]:
    return {"items": SERVICES.db.recent_events(limit=limit, level=level)}


@router.get("/events")
def events(since_id: int = 0, limit: int = 100, batch_id: str | None = None) -> dict[str, Any]:
    items = SERVICES.db.list_events(since_id=since_id, batch_id=batch_id, limit=limit)
    return {"items": items, "last_id": items[-1]["id"] if items else since_id}


@router.get("/events/stream")
async def event_stream(request: Request, since_id: int = 0):
    async def generator():
        last_id = since_id
        heartbeat = time.time()
        while True:
            if await request.is_disconnected():
                break
            items = SERVICES.db.list_events(since_id=last_id, limit=100)
            for item in items:
                last_id = item["id"]
                yield f"id: {last_id}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            if time.time() - heartbeat > 15:
                heartbeat = time.time()
                yield ": connected\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/system/backup")
def backup() -> dict[str, Any]:
    try:
        path = SERVICES.config.backup()
    except Exception as exc:  # noqa: BLE001
        _raise(f"备份失败：{exc}", status=500, code="backup_failed")
    return {"ok": True, "path": str(path) if path else ""}
