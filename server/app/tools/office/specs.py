"""مخططات مواصفات مستندات Office والوقاية من حقن الصيغ (Section 11.8)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


def sanitize_excel_cell(val: Any) -> Any:
    """منع حقن صيغ Excel (Formula Injection Defense).

    أي نص يبدأ بـ = أو + أو - أو @ يُسبق بـ ' ما لم يُدرج صراحة كصيغة معتمدة.
    """
    if isinstance(val, str):
        trimmed = val.strip()
        if trimmed and trimmed[0] in ("=", "+", "-", "@"):
            return f"'{val}"
    return val


class DocSection(BaseModel):
    heading: str | None = Field(default=None, description="عنوان فرعي للقسم")
    paragraphs: list[str] = Field(default_factory=list, description="فقرات نصية")
    bullets: list[str] = Field(default_factory=list, description="نقاط فرعية")
    table: list[list[str]] | None = Field(default=None, description="جدول بيانات")


class DocSpec(BaseModel):
    title: str = Field(..., description="عنوان المستند الرئيسي")
    language: str = Field(default="ar", description="لغة المستند (ar / en)")
    rtl: bool = Field(default=True, description="اتجاه الكتابة من اليمين إلى اليسار")
    sections: list[DocSection] = Field(default_factory=list, description="أقسام المستند")


class SheetSpec(BaseModel):
    name: str = Field(..., description="اسم ورقة العمل")
    rtl: bool = Field(default=True, description="اتجاه الورقة RTL")
    columns: list[str] = Field(default_factory=list, description="عناوين الأعمدة")
    rows: list[list[Any]] = Field(default_factory=list, description="صفوف البيانات")
    formulas: list[dict[str, str]] = Field(
        default_factory=list,
        description="الصيغ الصريحة المصرح بها: [{'cell': 'C10', 'formula': '=SUM(C2:C9)'}]",
    )


class WorkbookSpec(BaseModel):
    title: str = Field(..., description="عنوان جدول البيانات")
    sheets: list[SheetSpec] = Field(default_factory=list, description="أوراق العمل")


class SlideContent(BaseModel):
    title: str = Field(..., description="عنوان الشريحة")
    layout: Literal["title_and_content", "title_only", "two_content"] = Field(
        default="title_and_content", description="تخطيط الشريحة"
    )
    bullets: list[str] = Field(default_factory=list, description="نقاط الشريحة")
    notes: str | None = Field(default=None, description="ملاحظات المتحدث")


class PresentationSpec(BaseModel):
    title: str = Field(..., description="عنوان العرض التقديمي")
    slides: list[SlideContent] = Field(default_factory=list, description="الشرائح")
