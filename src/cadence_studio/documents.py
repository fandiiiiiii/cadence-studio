"""Extract text from user-provided project reference files.

The audio model never receives these files. Text is extracted once when the
batch is created, then passed only to the configured normalizer/planner LLM.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log"}
REFERENCE_EXTENSIONS = TEXT_EXTENSIONS | {".docx", ".pdf", ".xlsx"}

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_PER_FILE_CHARS = 12_000
MAX_TOTAL_CHARS = 30_000
MAX_FILES = 6


class DocumentError(ValueError):
    pass


def safe_reference_name(name: str) -> str:
    """Like media.safe_filename but does not force an audio extension."""
    clean = Path(name or "reference").name
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean).strip(" .")
    if not clean:
        clean = "reference.txt"
    stem, suffix = Path(clean).stem, Path(clean).suffix
    if not suffix:
        clean = f"{stem}.txt"
    return clean[:180]


def _clean(text: str, limit: int) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text[:limit].strip()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_docx(path: Path) -> str:
    from docx import Document

    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise DocumentError("PDF 已加密，无法读取") from exc
    parts = []
    for page in reader.pages[:80]:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        if text.strip():
            parts.append(text)
    if not parts:
        raise DocumentError("PDF 没有可提取文字，可能是扫描件；请先 OCR 或粘贴文字")
    return "\n".join(parts)


def _read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    parts = []
    try:
        for sheet in workbook.worksheets[:8]:
            parts.append(f"## Sheet: {sheet.title}")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= 300:
                    parts.append("…（已截断更多行）")
                    break
                cells = [str(value).strip() for value in row if value is not None and str(value).strip()]
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        workbook.close()
    return "\n".join(parts)


def extract_reference_file(path: Path, *, max_chars: int = MAX_PER_FILE_CHARS) -> str:
    suffix = path.suffix.lower()
    if suffix not in REFERENCE_EXTENSIONS:
        raise DocumentError(f"不支持的参考资料格式：{suffix or '无扩展名'}")
    if not path.is_file():
        raise DocumentError("参考资料不存在")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DocumentError("参考资料超过 15MB 限制")
    try:
        if suffix in TEXT_EXTENSIONS:
            text = _read_text(path)
        elif suffix == ".docx":
            text = _read_docx(path)
        elif suffix == ".pdf":
            text = _read_pdf(path)
        elif suffix == ".xlsx":
            text = _read_xlsx(path)
        else:
            raise DocumentError(f"不支持的参考资料格式：{suffix}")
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"解析失败：{exc}") from exc
    cleaned = _clean(text, max_chars)
    if not cleaned:
        raise DocumentError("没有提取到可用文字")
    return cleaned


def extract_references(paths: Iterable[tuple[str, Path]]) -> tuple[str, list[str], list[str]]:
    """Return (combined_text, accepted_names, warnings)."""
    chunks: list[str] = []
    accepted: list[str] = []
    warnings: list[str] = []
    total = 0
    for original_name, path in list(paths)[:MAX_FILES]:
        try:
            text = extract_reference_file(path)
        except DocumentError as exc:
            warnings.append(f"{original_name}：{exc}")
            continue
        remaining = MAX_TOTAL_CHARS - total
        if remaining <= 0:
            warnings.append(f"{original_name}：已超过参考资料总长度上限，后续内容被截断")
            break
        if len(text) > remaining:
            text = text[:remaining]
            warnings.append(f"{original_name}：内容超过总长度上限，已截断")
        chunks.append(f"### {original_name}\n{text}")
        accepted.append(original_name)
        total += len(text)
    return "\n\n".join(chunks), accepted, warnings
