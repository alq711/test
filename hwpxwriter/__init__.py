"""hwpxwriter — Markdown/텍스트를 한글(HWPX) 문서로 만드는 라이브러리."""

from __future__ import annotations

from pathlib import Path

from .document import HwpxDocument, PageSetup, Run, Theme
from .styles import BorderFill, CharStyle, Line, ParaStyle

__all__ = [
    "HwpxDocument",
    "PageSetup",
    "Run",
    "Theme",
    "CharStyle",
    "ParaStyle",
    "BorderFill",
    "Line",
    "markdown_to_hwpx",
    "text_to_hwpx",
]

__version__ = "0.1.0"


def markdown_to_hwpx(
    markdown: str,
    output: str | Path | None = None,
    *,
    base_dir: str | Path | None = None,
    page: PageSetup | None = None,
    theme: Theme | None = None,
    title: str = "",
    header: str | None = None,
    footer: str | None = None,
    page_number: bool = False,
) -> HwpxDocument:
    """Markdown 문자열로 문서를 만들고, output 이 있으면 저장까지 한다."""
    doc = HwpxDocument(page, theme, title=title)
    if header:
        doc.set_header(header)
    if footer:
        doc.set_footer(footer)
    elif page_number:
        doc.set_footer("- {page} -")
    doc.add_markdown(markdown, base_dir=base_dir)
    if output is not None:
        doc.save(output)
    return doc


def text_to_hwpx(
    text: str,
    output: str | Path | None = None,
    *,
    page: PageSetup | None = None,
    theme: Theme | None = None,
    title: str = "",
    header: str | None = None,
    footer: str | None = None,
    page_number: bool = False,
) -> HwpxDocument:
    """일반 텍스트: 한 줄이 한 문단이 된다 (서식 해석 없음)."""
    doc = HwpxDocument(page, theme, title=title)
    if header:
        doc.set_header(header)
    if footer:
        doc.set_footer(footer)
    elif page_number:
        doc.set_footer("- {page} -")
    for line in text.replace("\r\n", "\n").split("\n"):
        doc.add_paragraph(line.rstrip(), space_after=0)
    if output is not None:
        doc.save(output)
    return doc
