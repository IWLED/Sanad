"""مولد ملفات Office (Word, Excel, PowerPoint) بالعربية وRTL (Section 11.8)."""

import hashlib
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

import openpyxl  # type: ignore[import-untyped]
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pptx import Presentation
from pptx.util import Pt

from app.config import settings
from app.tools.office.specs import (
    DocSpec,
    PresentationSpec,
    WorkbookSpec,
    sanitize_excel_cell,
)


def _set_paragraph_rtl(paragraph: Any) -> None:
    """تعيين اتجاه الفقرة إلى RTL في Word."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_pr = paragraph._element.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    p_pr.append(bidi)


def generate_docx(spec: DocSpec, output_path: str) -> None:
    """توليد ملف Word (.docx) مهيأ بالكامل للغة العربية واتجاه RTL."""
    doc = Document()

    # عنوان المستند الرئيسي
    title_p = doc.add_paragraph()
    _set_paragraph_rtl(title_p)
    run = title_p.add_run(spec.title)
    run.bold = True
    run.font.size = Pt(20)

    for section in spec.sections:
        if section.heading:
            h_p = doc.add_paragraph()
            _set_paragraph_rtl(h_p)
            h_run = h_p.add_run(section.heading)
            h_run.bold = True
            h_run.font.size = Pt(14)

        for p_text in section.paragraphs:
            p = doc.add_paragraph()
            _set_paragraph_rtl(p)
            p.add_run(p_text)

        for bullet_text in section.bullets:
            b_p = doc.add_paragraph(style="List Bullet")
            _set_paragraph_rtl(b_p)
            b_p.add_run(bullet_text)

        if section.table and len(section.table) > 0:
            rows = len(section.table)
            cols = len(section.table[0])
            tbl = doc.add_table(rows=rows, cols=cols)
            tbl.style = "Table Grid"
            for r_idx, row_data in enumerate(section.table):
                for c_idx, cell_data in enumerate(row_data):
                    cell = tbl.cell(r_idx, c_idx)
                    cell.text = cell_data
                    for p in cell.paragraphs:
                        _set_paragraph_rtl(p)

    doc.save(output_path)


def generate_xlsx(spec: WorkbookSpec, output_path: str) -> None:
    """توليد ملف Excel (.xlsx) مع حماية ضد حقن الصيغ وتفعيل RTL."""
    wb = openpyxl.Workbook()
    # إزالة الورقة الافتراضية إذا كان لدينا أوراق محددة
    if spec.sheets:
        wb.remove(wb.active)

    for sheet_spec in spec.sheets:
        ws = wb.create_sheet(title=sheet_spec.name)
        if sheet_spec.rtl:
            ws.views.sheetView[0].rightToLeft = True

        # عناوين الأعمدة
        if sheet_spec.columns:
            ws.append(sheet_spec.columns)

        # الصفوف مع تطهير حقن الصيغ
        for row in sheet_spec.rows:
            sanitized_row = [sanitize_excel_cell(cell) for cell in row]
            ws.append(sanitized_row)

        # تطبيق الصيغ الصريحة المصرح بها
        for formula_def in sheet_spec.formulas:
            cell_ref = formula_def.get("cell")
            formula_val = formula_def.get("formula")
            if cell_ref and formula_val:
                ws[cell_ref] = formula_val

    wb.save(output_path)


def generate_pptx(spec: PresentationSpec, output_path: str) -> None:
    """توليد ملف PowerPoint (.pptx) مع دعم RTL للشرائح."""
    prs = Presentation()

    for slide_data in spec.slides:
        slide_layout = prs.slide_layouts[1]  # Title and Content
        slide = prs.slides.add_slide(slide_layout)

        # العنوان
        title = slide.shapes.title
        if title:
            title.text = slide_data.title

        # المحتوى والنقاط
        if slide.shapes.placeholders and len(slide.shapes.placeholders) > 1:
            body_shape = slide.shapes.placeholders[1]
            tf = body_shape.text_frame
            tf.word_wrap = True

            for idx, bullet in enumerate(slide_data.bullets):
                if idx == 0:
                    p = tf.paragraphs[0]
                    p.text = bullet
                else:
                    p = tf.add_paragraph()
                    p.text = bullet
                p.level = 0

        # ملاحظات المحاضر
        if slide_data.notes:
            notes_slide = slide.notes_slide
            text_frame = notes_slide.notes_text_frame
            text_frame.text = slide_data.notes

    prs.save(output_path)


def create_office_document(
    kind: str,
    spec_data: dict[str, Any],
    exports_dir: str | None = None,
) -> dict[str, Any]:
    """المعالج المركزي لإنشاء مستند Office وحفظه وتوليد بياناته الوصفية."""
    out_dir = Path(exports_dir or settings.exports_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        out_dir = Path(tempfile.gettempdir()) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)

    file_id = f"fil_{secrets.token_hex(8)}"

    if kind in ["docx", "word", "document"]:
        spec_doc = DocSpec.model_validate(spec_data)
        filename = f"{file_id}.docx"
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        full_path = os.path.join(out_dir, filename)
        generate_docx(spec_doc, full_path)
    elif kind in ["xlsx", "excel", "sheet"]:
        spec_wb = WorkbookSpec.model_validate(spec_data)
        filename = f"{file_id}.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        full_path = os.path.join(out_dir, filename)
        generate_xlsx(spec_wb, full_path)
    elif kind in ["pptx", "powerpoint", "slides"]:
        spec_pres = PresentationSpec.model_validate(spec_data)
        filename = f"{file_id}.pptx"
        mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        full_path = os.path.join(out_dir, filename)
        generate_pptx(spec_pres, full_path)
    else:
        raise ValueError(f"نوع المستند غير مدعوم: {kind}")

    size_bytes = os.path.getsize(full_path)
    with open(full_path, "rb") as f:
        file_sha256 = hashlib.sha256(f.read()).hexdigest()

    return {
        "file_id": file_id,
        "filename": filename,
        "path": full_path,
        "mime": mime,
        "size_bytes": size_bytes,
        "sha256": file_sha256,
    }
