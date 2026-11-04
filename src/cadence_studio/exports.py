"""Batch export to XLSX, JSON, Markdown, CSV and ZIP."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import EXPORT_DIR
from .taxonomy import get_taxonomy

EXPORT_VERSION = "1.0.0"


def _safe_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", value).strip("-")
    return value[:80] or "batch"


def _item_row(item: dict[str, Any], index: int) -> dict[str, Any]:
    result = item.get("normalized") or {}
    summary = item.get("summary") or {}
    genre = result.get("genre") or {}
    bpm_key = result.get("bpm_key") or {}
    instruments = result.get("instruments") or {}
    vocal = result.get("vocal") or {}
    language = result.get("language") or {}
    structure = result.get("structure") or {}
    quality = result.get("quality") or {}
    lyrics = result.get("lyrics") or {}
    tags = (result.get("mood") or {}).get("tags") or []
    return {
        "序号": index,
        "文件名": item.get("file_name", ""),
        "状态": item.get("status", ""),
        "阶段": item.get("stage", ""),
        "时长(秒)": round(float(item.get("duration_sec") or 0), 2),
        "主曲风": summary.get("genre", ""),
        "次曲风": " / ".join(
            tag.get("name_zh") or tag.get("name_en") or "" for tag in (genre.get("secondary") or [])
        ),
        "主情绪": summary.get("mood", ""),
        "情绪标签": " / ".join(tag.get("name_zh") or tag.get("name_en") or "" for tag in tags),
        "BPM": bpm_key.get("bpm"),
        "调性": f"{bpm_key.get('key', '')} {bpm_key.get('mode', '')}".strip(),
        "拍号": bpm_key.get("time_signature", ""),
        "主奏乐器": " / ".join(
            tag.get("name_zh") or tag.get("name_en") or "" for tag in (instruments.get("primary") or [])
        ),
        "人声": "有" if vocal.get("present") else "无 / 未知",
        "语言": (language.get("primary") or {}).get("name_zh", ""),
        "歌词显式": "是" if lyrics.get("explicit") else "否",
        "Caption": (result.get("caption") or {}).get("text", ""),
        "结构段数": len(structure.get("sections") or []),
        "质量分": quality.get("score"),
        "复核": item.get("review_status", ""),
        "错误码": item.get("error_code", ""),
        "错误": item.get("error_message", ""),
        "音频模型": item.get("inference_model", ""),
        "文字模型": item.get("llm_model", ""),
        "创建时间": item.get("created_at", ""),
        "完成时间": item.get("finished_at", ""),
    }


def _style_header(ws, columns: int) -> None:
    fill = PatternFill("solid", fgColor="111315")
    font = Font(color="C8F464", bold=True, size=10)
    thin = Side(style="thin", color="E5E7E9")
    for column in range(1, columns + 1):
        cell = ws.cell(row=1, column=column)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=thin)
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 24


def _auto_width(ws, max_width: int = 60) -> None:
    for column_cells in ws.columns:
        max_len = 0
        letter = get_column_letter(column_cells[0].column)
        for cell in column_cells[:80]:
            value = str(cell.value or "")
            max_len = max(max_len, min(len(value), max_width))
        ws.column_dimensions[letter].width = max(10, min(max_width, max_len * 1.3))


def build_payload(batch: dict[str, Any], items: list[dict[str, Any]], taxonomy_version: str) -> dict[str, Any]:
    return {
        "export_version": EXPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "taxonomy_version": taxonomy_version,
        "batch": {
            "id": batch.get("id"),
            "name": batch.get("name"),
            "note": batch.get("note", ""),
            "status": batch.get("status"),
            "mode": batch.get("mode"),
            "created_at": batch.get("created_at"),
            "finished_at": batch.get("finished_at"),
            "spec": batch.get("spec"),
            "routes": batch.get("route_snapshot"),
        },
        "summary": batch.get("counts"),
        "items": [
            {
                "index": index,
                "file_name": item.get("file_name"),
                "status": item.get("status"),
                "duration_sec": item.get("duration_sec"),
                "sha256": item.get("sha256"),
                "review_status": item.get("review_status"),
                "raw_audio_model_output": item.get("raw_text", ""),
                "llm_raw_output": item.get("llm_raw_text", ""),
                "normalized": item.get("normalized"),
                "timings": item.get("timings"),
                "error": {
                    "code": item.get("error_code"),
                    "message": item.get("error_message"),
                }
                if item.get("error_code")
                else None,
                "models": {
                    "audio": item.get("inference_model"),
                    "text": item.get("llm_model"),
                },
            }
            for index, item in enumerate(items, 1)
        ],
    }


def export_json(batch, items, path: Path) -> Path:
    payload = build_payload(batch, items, get_taxonomy().version)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_csv(batch, items, path: Path) -> Path:
    rows = [_item_row(item, index) for index, item in enumerate(items, 1)]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["文件名"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def export_xlsx(batch, items, path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "标注总表"
    rows = [_item_row(item, index) for index, item in enumerate(items, 1)]
    headers = list(rows[0].keys()) if rows else ["文件名"]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(header, "") for header in headers])
    _style_header(ws, len(headers))
    _auto_width(ws)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    overview = wb.create_sheet("批次概览")
    overview.append(["字段", "值"])
    for key, value in [
        ("批次 ID", batch.get("id")),
        ("批次名称", batch.get("name")),
        ("状态", batch.get("status")),
        ("模式", batch.get("mode")),
        ("标签版本", get_taxonomy().version),
        ("音频总数", len(items)),
        ("完成", batch.get("counts", {}).get("completed")),
        ("失败", batch.get("counts", {}).get("failed")),
        ("创建时间", batch.get("created_at")),
        ("完成时间", batch.get("finished_at")),
    ]:
        overview.append([key, value])
    _style_header(overview, 2)
    _auto_width(overview, 90)

    raw_sheet = wb.create_sheet("原始与规范化")
    raw_sheet.append(["序号", "文件名", "音频模型原始输出", "大模型原始输出", "规范化 JSON"])
    for index, item in enumerate(items, 1):
        raw_sheet.append(
            [
                index,
                item.get("file_name", ""),
                (item.get("raw_text") or "")[:32000],
                (item.get("llm_raw_text") or "")[:32000],
                json.dumps(item.get("normalized"), ensure_ascii=False, indent=2)[:32000]
                if item.get("normalized")
                else "",
            ]
        )
    _style_header(raw_sheet, 5)
    raw_sheet.column_dimensions["A"].width = 8
    raw_sheet.column_dimensions["B"].width = 38
    for letter in ("C", "D", "E"):
        raw_sheet.column_dimensions[letter].width = 70
    for row in raw_sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    structure_sheet = wb.create_sheet("结构时间轴")
    structure_sheet.append(["文件名", "段落", "中文名", "开始(秒)", "结束(秒)", "能量", "置信度", "描述"])
    for item in items:
        sections = ((item.get("normalized") or {}).get("structure") or {}).get("sections") or []
        for section in sections:
            structure_sheet.append(
                [
                    item.get("file_name", ""),
                    section.get("label", ""),
                    section.get("label_zh", ""),
                    section.get("start_sec"),
                    section.get("end_sec"),
                    section.get("energy"),
                    section.get("confidence"),
                    section.get("description", ""),
                ]
            )
    _style_header(structure_sheet, 8)
    _auto_width(structure_sheet, 45)

    mappings = wb.create_sheet("标签映射")
    mappings.append(["文件名", "模块", "原词", "规范 ID", "中文名", "英文名", "置信度", "是否映射"])
    for item in items:
        normalized = item.get("normalized") or {}
        for module in ("genre", "mood", "scene", "instruments", "vocal", "language", "extra"):
            value = normalized.get(module) or {}
            tags = []
            if isinstance(value.get("primary"), dict):
                tags.append(value["primary"])
            for key in ("secondary", "tags"):
                if isinstance(value.get(key), list):
                    tags.extend(tag for tag in value[key] if isinstance(tag, dict))
            for tag in tags:
                mappings.append(
                    [
                        item.get("file_name", ""),
                        module,
                        tag.get("source_label", ""),
                        tag.get("id", ""),
                        tag.get("name_zh", ""),
                        tag.get("name_en", ""),
                        tag.get("confidence"),
                        tag.get("mapped"),
                    ]
                )
    _style_header(mappings, 8)
    _auto_width(mappings, 45)

    wb.save(path)
    return path


def export_markdown(batch, items, path: Path) -> Path:
    taxonomy = get_taxonomy()
    lines = [
        f"# {batch.get('name', '未命名批次')}",
        "",
        f"- 批次 ID：`{batch.get('id')}`",
        f"- 状态：`{batch.get('status')}`",
        f"- 标签体系：`{taxonomy.version}`",
        f"- 创建时间：{batch.get('created_at')}",
        f"- 完成时间：{batch.get('finished_at') or '—'}",
        f"- 音频数：{len(items)}",
        "",
        "## 批次说明",
        "",
        batch.get("note") or "（无）",
        "",
        "## 曲目",
        "",
    ]
    for index, item in enumerate(items, 1):
        result = item.get("normalized") or {}
        summary = item.get("summary") or {}
        lines.extend(
            [
                f"### {index:03d} · {item.get('file_name')}",
                "",
                f"- 状态：`{item.get('status')}` · 时长：{item.get('duration_sec') or 0:.1f}s",
                f"- 主曲风：{summary.get('genre') or '—'} · 主情绪：{summary.get('mood') or '—'}",
                f"- BPM / 调性：{summary.get('bpm') or '—'} / {summary.get('key') or '—'}",
                "",
            ]
        )
        caption = (result.get("caption") or {}).get("text")
        if caption:
            lines.extend([caption, ""])
        if item.get("error_code"):
            lines.extend([f"> **失败** `{item['error_code']}`：{item.get('error_message', '')}", ""])
        if result:
            lines.extend(
                [
                    "<details><summary>结构化结果</summary>",
                    "",
                    "```json",
                    json.dumps(result, ensure_ascii=False, indent=2)[:50000],
                    "```",
                    "",
                    "</details>",
                    "",
                ]
            )
        if item.get("raw_text"):
            lines.extend(
                [
                    "<details><summary>音频模型原始输出</summary>",
                    "",
                    "```text",
                    item["raw_text"][:20000],
                    "```",
                    "",
                    "</details>",
                    "",
                ]
            )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_batch(batch: dict[str, Any], items: list[dict[str, Any]], fmt: str) -> Path:
    target_dir = EXPORT_DIR / str(batch["id"])
    target_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(batch.get("name") or batch["id"])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fmt = fmt.lower()
    if fmt == "json":
        return export_json(batch, items, target_dir / f"{safe}-{stamp}.json")
    if fmt == "csv":
        return export_csv(batch, items, target_dir / f"{safe}-{stamp}.csv")
    if fmt == "md":
        return export_markdown(batch, items, target_dir / f"{safe}-{stamp}.md")
    if fmt == "xlsx":
        return export_xlsx(batch, items, target_dir / f"{safe}-{stamp}.xlsx")
    if fmt != "zip":
        raise ValueError(f"不支持的导出格式：{fmt}")

    bundle = target_dir / f"{safe}-{stamp}.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "export_version": EXPORT_VERSION,
                    "batch_id": batch.get("id"),
                    "batch_name": batch.get("name"),
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "taxonomy_version": get_taxonomy().version,
                    "files": ["annotations.json", "annotations.csv", "annotations.md", "annotations.xlsx", "taxonomy.json"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.write(export_json(batch, items, target_dir / "annotations.json"), "annotations.json")
        archive.write(export_csv(batch, items, target_dir / "annotations.csv"), "annotations.csv")
        archive.write(export_markdown(batch, items, target_dir / "annotations.md"), "annotations.md")
        archive.write(export_xlsx(batch, items, target_dir / "annotations.xlsx"), "annotations.xlsx")
        archive.write(get_taxonomy().path, "taxonomy.json")
    return bundle
