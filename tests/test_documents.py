from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter

from cadence_studio.documents import DocumentError, extract_reference_file, extract_references
from cadence_studio.modules import BatchSpec
from cadence_studio.prompts import build_normalizer_messages, build_prompt_planner_messages


def test_extract_text_docx_and_xlsx(tmp_path: Path):
    text = tmp_path / "notes.md"
    text.write_text("# 规则\n优先判断 15 秒卡点。", encoding="utf-8")

    docx = tmp_path / "brief.docx"
    document = Document()
    document.add_paragraph("品牌语气要克制")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "场景"
    table.rows[0].cells[1].text = "晨间通勤"
    document.save(docx)

    xlsx = tmp_path / "scores.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "标准"
    sheet.append(["维度", "权重"])
    sheet.append(["卡点", 0.4])
    workbook.save(xlsx)

    assert "15 秒卡点" in extract_reference_file(text)
    assert "品牌语气要克制" in extract_reference_file(docx)
    assert "晨间通勤" in extract_reference_file(docx)
    assert "卡点" in extract_reference_file(xlsx)

    combined, accepted, warnings = extract_references(
        [("notes.md", text), ("brief.docx", docx), ("scores.xlsx", xlsx)]
    )
    assert "15 秒卡点" in combined
    assert accepted == ["notes.md", "brief.docx", "scores.xlsx"]
    assert warnings == []


def test_scanned_pdf_without_text_is_rejected(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open("wb") as handle:
        writer.write(handle)
    try:
        extract_reference_file(pdf)
    except DocumentError as exc:
        assert "扫描件" in str(exc)
    else:
        raise AssertionError("blank PDF should have no extractable text")


def test_project_rules_reach_planner_and_normalizer():
    spec = BatchSpec(
        modules=["caption", "genre"],
        project_instruction="这是品牌广告曲库，优先判断 15 秒卡点。",
        project_context="参考资料：不要使用文学化描述。",
    )
    planner = build_prompt_planner_messages(spec)
    assert "15 秒卡点" in planner[1]["content"]
    assert "不要使用文学化描述" in planner[1]["content"]
    normalizer = build_normalizer_messages(spec, "raw observation")
    assert "品牌广告曲库" in normalizer[0]["content"]
    assert "不要使用文学化描述" in normalizer[0]["content"]
