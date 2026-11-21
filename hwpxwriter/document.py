"""HWPX 문서 빌더.

사용 예::

    from hwpxwriter import HwpxDocument, Run

    doc = HwpxDocument()
    doc.add_heading("보고서 제목", level=1)
    doc.add_paragraph(["일반 글자와 ", Run("굵은 글자", bold=True), "를 섞어 씁니다."])
    doc.add_table([["이름", "점수"], ["홍길동", "95"]])
    doc.set_footer("- {page} -")
    doc.save("report.hwpx")
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Sequence, Union
from xml.sax.saxutils import escape, quoteattr

from . import units
from .images import ImageInfo, probe
from .styles import (
    BorderFill,
    CharStyle,
    Line,
    ParaStyle,
    StyleRegistry,
    normalize_align,
    normalize_color,
)
from .xmlns import NS_DECL

# ---------------------------------------------------------------------------
# 공개 데이터 타입
# ---------------------------------------------------------------------------


@dataclass
class Run:
    """같은 글자 모양을 가진 글자 묶음. text 안의 '\\n' 은 줄바꿈(Shift+Enter)이 된다."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    code: bool = False  # 고정폭 글꼴 + 음영
    color: str | None = None
    size: float | None = None  # pt
    font: str | None = None
    highlight: str | None = None  # 글자 배경색
    superscript: bool = False
    subscript: bool = False


Content = Union[str, Run, Sequence[Union[str, Run]]]


@dataclass
class PageSetup:
    """용지와 여백 (단위: mm)."""

    paper: str | tuple[float, float] = "A4"
    landscape: bool = False
    margin_left: float = 30
    margin_right: float = 30
    margin_top: float = 20
    margin_bottom: float = 15
    margin_header: float = 15
    margin_footer: float = 15
    gutter: float = 0

    def size_mm(self) -> tuple[float, float]:
        if isinstance(self.paper, str):
            key = self.paper.upper()
            if key not in units.PAPER_SIZES:
                raise ValueError(f"알 수 없는 용지 크기: {self.paper!r} ({', '.join(units.PAPER_SIZES)})")
            w, h = units.PAPER_SIZES[key]
        else:
            w, h = self.paper
        return (h, w) if self.landscape else (w, h)

    @property
    def width(self) -> int:
        return units.mm(self.size_mm()[0])

    @property
    def height(self) -> int:
        return units.mm(self.size_mm()[1])

    @property
    def text_width(self) -> int:
        """본문 영역 너비 (HWPUNIT)."""
        return self.width - units.mm(self.margin_left) - units.mm(self.margin_right) - units.mm(self.gutter)

    @property
    def text_height(self) -> int:
        """본문 영역 높이 (HWPUNIT). 한글은 머리말/꼬리말 영역을 위/아래 여백과 따로 잡는다."""
        return self.height - units.mm(
            self.margin_top + self.margin_bottom + self.margin_header + self.margin_footer
        )


@dataclass
class Theme:
    """문서 전체의 기본 서식."""

    body_font: str = "함초롬바탕"
    heading_font: str = "함초롬돋움"
    code_font: str = "굴림체"
    font_size: float = 10.0
    line_spacing: int = 160  # %
    paragraph_spacing: float = 4.0  # 문단 뒤 간격 (pt)
    heading_sizes: tuple[float, ...] = (20, 16, 14, 12, 11, 10)
    heading_color: str = "#000000"
    text_color: str = "#000000"
    link_color: str = "#0563C1"
    code_background: str = "#F2F2F2"
    quote_color: str = "#555555"
    quote_bar_color: str = "#BBBBBB"
    table_border_color: str = "#000000"
    table_header_background: str = "#E7E6E6"
    header_footer_size: float = 9.0
    header_footer_color: str = "#444444"
    bullets: tuple[str, ...] = ("•", "◦", "▪")
    list_indent: float = 18.0  # 목록 한 단계 들여쓰기 (pt)


# ---------------------------------------------------------------------------
# 내부 표현
# ---------------------------------------------------------------------------


@dataclass
class _Paragraph:
    para_pr: int
    style: int
    runs: str  # 직렬화된 <hp:run> 들
    plain: str = ""
    page_break: bool = False
    pid: int = -1


@dataclass
class _BinItem:
    item_id: str
    href: str
    media_type: str
    data: bytes


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"\{(page|total|쪽|전체쪽)\}")


def _xml_text(text: str) -> str:
    """hp:t 안에 들어갈 글자. 줄바꿈은 <hp:lineBreak/>, 탭은 공백 4칸."""
    text = _CONTROL_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    "))
    return "<hp:lineBreak/>".join(escape(part) for part in text.split("\n"))


def _as_runs(content: Content | None) -> list[Run]:
    if content is None:
        return []
    if isinstance(content, (str, Run)):
        content = [content]
    return [Run(item) if isinstance(item, str) else item for item in content]


def _distribute(total: int, weights: Sequence[float]) -> list[int]:
    s = sum(weights) or 1
    sizes = [int(total * w / s) for w in weights]
    sizes[-1] += total - sum(sizes)
    return sizes


def _display_len(text: str) -> int:
    """폭 추정: 한글·한자 등 전각 문자는 2칸."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


# ---------------------------------------------------------------------------
# 문서
# ---------------------------------------------------------------------------


class HwpxDocument:
    """처음부터 새 HWPX 문서를 만든다."""

    def __init__(
        self,
        page: PageSetup | None = None,
        theme: Theme | None = None,
        *,
        title: str = "",
        author: str = "",
    ) -> None:
        self.page = page or PageSetup()
        self.theme = theme or Theme()
        self.title = title
        self.author = author
        t = self.theme
        self._body_char = CharStyle(font=t.body_font, size=t.font_size, color=normalize_color(t.text_color) or "#000000")
        self._body_para = ParaStyle(
            align="JUSTIFY",
            line_spacing=t.line_spacing,
            space_after=units.pt(t.paragraph_spacing),
        )
        # 서식 id 0 = '바탕글' (간격 없는 기본 문단)
        self.styles = StyleRegistry(
            default_char=self._body_char,
            default_para=ParaStyle(align="JUSTIFY", line_spacing=t.line_spacing),
        )
        self._paragraphs: list[_Paragraph] = []
        self._bins: list[_BinItem] = []
        self._bin_by_hash: dict[str, str] = {}
        self._header: tuple[Content, str] | None = None
        self._footer: tuple[Content, str] | None = None
        self._pending_page_break = False
        self._para_id = 0
        self._obj_id = 0
        self._zorder = 0
        self._style_ids = self._register_named_styles()

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------
    def _heading_styles(self, level: int) -> tuple[CharStyle, ParaStyle]:
        t = self.theme
        sizes = t.heading_sizes
        size = sizes[min(level, len(sizes)) - 1]
        char = CharStyle(font=t.heading_font, size=size, bold=True, color=normalize_color(t.heading_color) or "#000000")
        para = ParaStyle(
            align="LEFT",
            line_spacing=t.line_spacing,
            space_before=units.pt(size * (0.9 if level <= 2 else 0.6)),
            space_after=units.pt(size * 0.4),
            keep_with_next=True,
        )
        return char, para

    def _register_named_styles(self) -> dict[str, int]:
        reg = self.styles
        ids = {"normal": 0}
        ids["body"] = reg.add_style("본문", "Body", para=self._body_para, char=self._body_char)
        for level in range(1, 7):
            char, para = self._heading_styles(level)
            ids[f"h{level}"] = reg.add_style(f"제목 {level}", f"Heading {level}", para=para, char=char)
        hf_char = self._header_footer_char()
        hf_para = ParaStyle(align="CENTER", line_spacing=150)
        ids["header"] = reg.add_style("머리말", "Header", para=hf_para, char=hf_char)
        ids["footer"] = reg.add_style("꼬리말", "Footer", para=hf_para, char=hf_char)
        ids["caption"] = reg.add_style("캡션", "Caption", para=self._caption_para(), char=self._caption_char())
        ids["code"] = reg.add_style("코드", "Code", para=self._code_para(False), char=self._code_char())
        ids["quote"] = reg.add_style("인용", "Quote", para=self._quote_para(0), char=self._quote_char())
        return ids

    def _header_footer_char(self) -> CharStyle:
        t = self.theme
        return replace(self._body_char, size=t.header_footer_size, color=normalize_color(t.header_footer_color) or "#000000")

    def _caption_char(self) -> CharStyle:
        return replace(self._body_char, size=max(self.theme.font_size - 1, 6))

    def _caption_para(self) -> ParaStyle:
        return replace(self._body_para, align="CENTER")

    def _code_char(self) -> CharStyle:
        return replace(self._body_char, font=self.theme.code_font, size=max(self.theme.font_size - 1, 6))

    def _code_para(self, last: bool) -> ParaStyle:
        bf = self.styles.border(BorderFill(fill=normalize_color(self.theme.code_background)))
        pad = units.pt(6)
        return ParaStyle(
            align="LEFT",
            line_spacing=130,
            left=pad,
            right=pad,
            border_fill=bf,
            border_offset_left=pad,
            border_offset_right=pad,
            border_offset_top=units.pt(4),
            border_offset_bottom=units.pt(4),
            border_connect=True,
            space_after=units.pt(self.theme.paragraph_spacing + 6) if last else 0,
            break_latin_word="BREAK_WORD",
        )

    def _quote_char(self) -> CharStyle:
        return replace(self._body_char, color=normalize_color(self.theme.quote_color) or "#555555")

    def _quote_para(self, level: int) -> ParaStyle:
        bar = Line("SOLID", "0.7 mm", normalize_color(self.theme.quote_bar_color) or "#BBBBBB")
        bf = self.styles.border(BorderFill(left=bar))
        return replace(
            self._body_para,
            left=units.pt(12) * (level + 1),
            border_fill=bf,
            border_offset_left=units.pt(8),
            border_connect=True,
        )

    # ------------------------------------------------------------------
    # 글자 묶음 직렬화
    # ------------------------------------------------------------------
    def _char_for(self, run: Run, base: CharStyle) -> CharStyle:
        t = self.theme
        cs = base
        if run.code:
            cs = replace(cs, font=t.code_font, shade=normalize_color(t.code_background) or "none")
        updates: dict[str, object] = {}
        if run.bold:
            updates["bold"] = True
        if run.italic:
            updates["italic"] = True
        if run.underline:
            updates["underline"] = True
        if run.strike:
            updates["strike"] = True
        if run.superscript:
            updates["superscript"] = True
        if run.subscript:
            updates["subscript"] = True
        if run.color:
            updates["color"] = normalize_color(run.color)
        if run.size:
            updates["size"] = float(run.size)
        if run.font:
            updates["font"] = run.font
        if run.highlight:
            updates["shade"] = normalize_color(run.highlight)
        return replace(cs, **updates) if updates else cs

    def _runs_xml(self, content: Content | None, base: CharStyle) -> tuple[str, str]:
        """(XML, 평문) — 같은 글자 모양이 이어지면 하나의 hp:run 으로 합친다."""
        merged: list[list] = []  # [charPr id, text]
        for run in _as_runs(content):
            if not run.text:
                continue
            cid = self.styles.char(self._char_for(run, base))
            if merged and merged[-1][0] == cid:
                merged[-1][1] += run.text
            else:
                merged.append([cid, run.text])
        if not merged:
            return f'<hp:run charPrIDRef="{self.styles.char(base)}"><hp:t/></hp:run>', ""
        xml = "".join(f'<hp:run charPrIDRef="{cid}"><hp:t>{_xml_text(text)}</hp:t></hp:run>' for cid, text in merged)
        return xml, "".join(text for _, text in merged)

    # ------------------------------------------------------------------
    # 문단 추가 (내부)
    # ------------------------------------------------------------------
    def _next_para_id(self) -> int:
        pid = self._para_id
        self._para_id += 1
        return pid

    def _next_obj_id(self) -> int:
        self._obj_id += 1
        return self._obj_id

    def _append(self, para_pr: ParaStyle, style: int, runs_xml: str, plain: str) -> None:
        self._paragraphs.append(
            _Paragraph(self.styles.para(para_pr), style, runs_xml, plain, page_break=self._pending_page_break,
                       pid=self._next_para_id())
        )
        self._pending_page_break = False

    # ------------------------------------------------------------------
    # 공개 API: 본문
    # ------------------------------------------------------------------
    def add_heading(self, content: Content, level: int = 1, *, align: str | None = None) -> None:
        """제목 (level 1~6)."""
        level = max(1, min(6, int(level)))
        char, para = self._heading_styles(level)
        if align:
            para = replace(para, align=normalize_align(align))
        xml, plain = self._runs_xml(content, char)
        self._append(para, self._style_ids[f"h{level}"], xml, plain)

    def add_title(self, content: Content, *, size: float | None = None, subtitle: Content | None = None) -> None:
        """문서 맨 위의 큰 가운데 정렬 제목."""
        t = self.theme
        char = CharStyle(font=t.heading_font, size=size or t.heading_sizes[0] + 4, bold=True,
                         color=normalize_color(t.heading_color) or "#000000")
        para = ParaStyle(align="CENTER", line_spacing=t.line_spacing, space_after=units.pt(6 if subtitle else 18))
        xml, plain = self._runs_xml(content, char)
        self._append(para, self._style_ids["h1"], xml, plain)
        if subtitle is not None:
            sub_char = replace(self._body_char, size=t.font_size + 2, color="#555555")
            sub_para = replace(para, space_after=units.pt(18))
            xml, plain = self._runs_xml(subtitle, sub_char)
            self._append(sub_para, self._style_ids["body"], xml, plain)

    def add_paragraph(
        self,
        content: Content = "",
        *,
        align: str | None = None,
        size: float | None = None,
        bold: bool = False,
        italic: bool = False,
        color: str | None = None,
        indent: float = 0,
        left: float = 0,
        space_after: float | None = None,
        line_spacing: int | None = None,
    ) -> None:
        """본문 문단. indent/left/space_after 단위는 pt."""
        char = self._body_char
        if size or bold or italic or color:
            char = replace(
                char,
                size=float(size) if size else char.size,
                bold=bold or char.bold,
                italic=italic or char.italic,
                color=normalize_color(color) if color else char.color,
            )
        para = self._body_para
        changes: dict[str, object] = {}
        if align:
            changes["align"] = normalize_align(align)
        if indent:
            changes["indent"] = units.pt(indent)
        if left:
            changes["left"] = units.pt(left)
        if space_after is not None:
            changes["space_after"] = units.pt(space_after)
        if line_spacing:
            changes["line_spacing"] = int(line_spacing)
        if changes:
            para = replace(para, **changes)
        xml, plain = self._runs_xml(content, char)
        self._append(para, self._style_ids["body"], xml, plain)

    def add_list_item(
        self,
        content: Content,
        *,
        level: int = 0,
        marker: str | None = None,
        ordered_number: int | None = None,
        tight: bool = True,
    ) -> None:
        """목록 항목 하나. marker 가 없으면 단계별 글머리표(•, ◦, ▪)를 쓴다."""
        t = self.theme
        if marker is None:
            marker = f"{ordered_number}." if ordered_number is not None else t.bullets[level % len(t.bullets)]
        step = units.pt(t.list_indent)
        para = replace(
            self._body_para,
            align="LEFT",
            left=step * (level + 1),
            indent=-step,
            space_after=units.pt(2) if tight else self._body_para.space_after,
        )
        runs = [Run(marker + " ")] + _as_runs(content)
        xml, plain = self._runs_xml(runs, self._body_char)
        self._append(para, self._style_ids["body"], xml, plain)

    def add_code_block(self, code: str, *, language: str | None = None) -> None:
        """고정폭 글꼴 + 회색 배경 상자. 줄마다 한 문단."""
        lines = code.replace("\r\n", "\n").rstrip("\n").split("\n") or [""]
        char = self._code_char()
        for i, line in enumerate(lines):
            para = self._code_para(last=(i == len(lines) - 1))
            xml, plain = self._runs_xml(line, char)
            self._append(para, self._style_ids["code"], xml, plain)

    def add_quote(self, content: Content, *, level: int = 0) -> None:
        """인용문 (왼쪽 세로줄)."""
        xml, plain = self._runs_xml(content, self._quote_char())
        self._append(self._quote_para(level), self._style_ids["quote"], xml, plain)

    def add_horizontal_rule(self) -> None:
        """가로 구분선."""
        bf = self.styles.border(BorderFill(bottom=Line("SOLID", "0.25 mm", "#999999")))
        para = replace(self._body_para, border_fill=bf, line_spacing=100, space_after=units.pt(8))
        char = replace(self._body_char, size=4)
        xml, plain = self._runs_xml("", char)
        self._append(para, 0, xml, plain)

    def add_page_break(self) -> None:
        """다음 문단을 새 쪽에서 시작한다."""
        self._pending_page_break = True

    # ------------------------------------------------------------------
    # 표
    # ------------------------------------------------------------------
    def add_table(
        self,
        rows: Sequence[Sequence[Content]],
        *,
        header: bool = True,
        align: Sequence[str | None] | None = None,
        col_widths: Sequence[float] | None = None,
        width: float | None = None,
        font_size: float | None = None,
        caption: Content | None = None,
    ) -> None:
        """표를 추가한다.

        rows: 2차원 목록. 각 칸은 문자열, Run, 또는 Run 목록.
        header: 첫 줄을 제목 줄(굵게, 배경색, 쪽마다 반복)로 쓸지.
        align: 열별 정렬 ('left' / 'center' / 'right').
        col_widths: 열 너비 비율 (예: [1, 3, 1]). 없으면 내용 길이로 추정.
        width: 표 전체 너비 (mm). 없으면 본문 너비.
        """
        if not rows:
            return
        n_cols = max(len(r) for r in rows)
        grid = [list(r) + [""] * (n_cols - len(r)) for r in rows]
        n_rows = len(grid)
        t = self.theme
        total_width = units.mm(width) if width else self.page.text_width
        if col_widths and len(col_widths) == n_cols:
            weights = [max(float(w), 0.01) for w in col_widths]
        else:
            weights = []
            for c in range(n_cols):
                longest = max(_display_len("".join(r.text for r in _as_runs(row[c]))) for row in grid)
                weights.append(min(max(longest, 4), 40))
        widths = _distribute(total_width, weights)
        col_align = [normalize_align(a, "LEFT") if a else "LEFT" for a in (align or [])]
        col_align += ["LEFT"] * (n_cols - len(col_align))

        border_color = normalize_color(t.table_border_color) or "#000000"
        body_bf = self.styles.border(BorderFill.box("0.12 mm", border_color))
        head_bf = self.styles.border(
            BorderFill.box("0.12 mm", border_color, normalize_color(t.table_header_background))
        )
        cell_char = replace(self._body_char, size=float(font_size)) if font_size else self._body_char
        head_char = replace(cell_char, bold=True)
        row_height = units.pt(cell_char.size * 1.6) + 282

        rows_xml = []
        for r, row in enumerate(grid):
            is_head = header and r == 0
            cells = []
            for c, cell in enumerate(row):
                para = ParaStyle(align="CENTER" if is_head else col_align[c], line_spacing=130)
                xml, _ = self._runs_xml(cell, head_char if is_head else cell_char)
                cells.append(
                    f'<hp:tc name="" header="{int(is_head)}" hasMargin="0" protect="0" editable="0" dirty="0" '
                    f'borderFillIDRef="{head_bf if is_head else body_bf}">'
                    '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
                    'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                    f'<hp:p id="{self._next_para_id()}" paraPrIDRef="{self.styles.para(para)}" styleIDRef="0" '
                    f'pageBreak="0" columnBreak="0" merged="0">{xml}</hp:p>'
                    "</hp:subList>"
                    f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
                    '<hp:cellSpan colSpan="1" rowSpan="1"/>'
                    f'<hp:cellSz width="{widths[c]}" height="{row_height}"/>'
                    '<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
                    "</hp:tc>"
                )
            rows_xml.append(f"<hp:tr>{''.join(cells)}</hp:tr>")

        tbl_id = self._next_obj_id()
        tbl = (
            f'<hp:tbl id="{tbl_id}" zOrder="{self._zorder}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
            'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" '
            f'repeatHeader="{int(header)}" rowCnt="{n_rows}" colCnt="{n_cols}" cellSpacing="0" '
            f'borderFillIDRef="{body_bf}" noAdjust="0">'
            f'<hp:sz width="{sum(widths)}" widthRelTo="ABSOLUTE" height="{row_height * n_rows}" '
            'heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
            f"{''.join(rows_xml)}"
            "</hp:tbl>"
        )
        self._zorder += 1
        if caption is not None:
            self._add_caption(caption, space_after=2)
        para = replace(self._body_para, align="CENTER", line_spacing=100, space_after=units.pt(t.paragraph_spacing + 4))
        plain = "\n".join("\t".join("".join(x.text for x in _as_runs(c)) for c in row) for row in grid)
        self._append(para, 0, f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run>', plain)

    # ------------------------------------------------------------------
    # 그림
    # ------------------------------------------------------------------
    def _register_binary(self, data: bytes, info: ImageInfo) -> str:
        digest = hashlib.sha1(data).hexdigest()
        if digest in self._bin_by_hash:
            return self._bin_by_hash[digest]
        n = len(self._bins) + 1
        item_id = f"image{n}"
        self._bins.append(_BinItem(item_id, f"BinData/{item_id}.{info.ext}", info.media_type, data))
        self._bin_by_hash[digest] = item_id
        return item_id

    def add_image(
        self,
        source: str | Path | bytes,
        *,
        width: float | None = None,
        width_ratio: float | None = None,
        align: str = "center",
        caption: Content | None = None,
    ) -> None:
        """그림을 한 문단으로 추가한다.

        width: 너비 (mm). width_ratio: 본문 너비 대비 비율 (0~1).
        둘 다 없으면 원본 크기(96 DPI 기준)로 넣되 본문 영역을 넘지 않게 줄인다.
        """
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        info = probe(data)
        dpi = info.dpi_x or units.DEFAULT_DPI
        w = units.px(info.width, dpi)
        h = units.px(info.height, info.dpi_y or dpi)
        if w <= 0 or h <= 0:
            raise ValueError("그림 크기가 0 입니다")
        max_w = self.page.text_width
        max_h = int(self.page.text_height * 0.9)
        if width:
            target = units.mm(width)
        elif width_ratio:
            target = int(max_w * max(0.01, min(float(width_ratio), 1.0)))
        else:
            target = w
        target = min(target, max_w)
        scale = target / w
        if h * scale > max_h:
            scale = max_h / h
        dw, dh = max(1, round(w * scale)), max(1, round(h * scale))

        item_id = self._register_binary(data, info)
        pic_id = self._next_obj_id()
        ident = 'e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"'
        pic = (
            f'<hp:pic id="{pic_id}" zOrder="{self._zorder}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{pic_id}" reverse="0">'
            '<hp:offset x="0" y="0"/>'
            f'<hp:orgSz width="{dw}" height="{dh}"/>'
            f'<hp:curSz width="{dw}" height="{dh}"/>'
            '<hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{dw // 2}" centerY="{dh // 2}" rotateimage="1"/>'
            f"<hp:renderingInfo><hc:transMatrix {ident}/><hc:scaMatrix {ident}/><hc:rotMatrix {ident}/></hp:renderingInfo>"
            "<hp:imgRect>"
            f'<hc:pt0 x="0" y="0"/><hc:pt1 x="{dw}" y="0"/><hc:pt2 x="{dw}" y="{dh}"/><hc:pt3 x="0" y="{dh}"/>'
            "</hp:imgRect>"
            f'<hp:imgClip left="0" right="{dw}" top="0" bottom="{dh}"/>'
            '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:imgDim dimwidth="{dw}" dimheight="{dh}"/>'
            f'<hc:img binaryItemIDRef="{item_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            "<hp:effects/>"
            f'<hp:sz width="{dw}" widthRelTo="ABSOLUTE" height="{dh}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            "<hp:shapeComment/>"
            "</hp:pic>"
        )
        self._zorder += 1
        para = replace(
            self._body_para,
            align=normalize_align(align, "CENTER"),
            line_spacing=100,
            space_after=units.pt(2 if caption is not None else self.theme.paragraph_spacing + 4),
        )
        self._append(para, 0, f'<hp:run charPrIDRef="0">{pic}<hp:t/></hp:run>', "")
        if caption is not None:
            self._add_caption(caption, space_after=self.theme.paragraph_spacing + 6)

    def _add_caption(self, caption: Content, *, space_after: float) -> None:
        para = replace(self._caption_para(), space_after=units.pt(space_after))
        xml, plain = self._runs_xml(caption, self._caption_char())
        self._append(para, self._style_ids["caption"], xml, plain)

    # ------------------------------------------------------------------
    # 머리말 / 꼬리말
    # ------------------------------------------------------------------
    def set_header(self, content: Content | None, *, align: str = "center") -> None:
        """머리말. 글자 안의 {page} 는 쪽 번호, {total} 은 전체 쪽 수로 바뀐다."""
        self._header = (content, normalize_align(align)) if content else None

    def set_footer(self, content: Content | None, *, align: str = "center") -> None:
        """꼬리말. 예: set_footer('- {page} -') 또는 set_footer('{page} / {total}', align='right')."""
        self._footer = (content, normalize_align(align)) if content else None

    def _header_footer_ctrl(self, kind: str, content: Content, align: str) -> str:
        char = self._header_footer_char()
        cid = self.styles.char(char)
        para = ParaStyle(align=align, line_spacing=150)
        pieces: list[str] = []
        pending: list[Run] = []

        def flush() -> None:
            if pending:
                xml, _ = self._runs_xml(list(pending), char)
                pieces.append(xml)
                pending.clear()

        for run in _as_runs(content):
            pos = 0
            for m in _PLACEHOLDER.finditer(run.text):
                if m.start() > pos:
                    pending.append(replace(run, text=run.text[pos : m.start()]))
                flush()
                num_type = "PAGE" if m.group(1) in ("page", "쪽") else "TOTAL_PAGE"
                pieces.append(
                    f'<hp:run charPrIDRef="{cid}"><hp:ctrl><hp:autoNum num="1" numType="{num_type}">'
                    '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar="" supscript="0"/>'
                    "</hp:autoNum></hp:ctrl></hp:run>"
                )
                pos = m.end()
            if pos < len(run.text):
                pending.append(replace(run, text=run.text[pos:]))
        flush()
        if not pieces:
            pieces.append(f'<hp:run charPrIDRef="{cid}"><hp:t/></hp:run>')
        p = self.page
        is_header = kind == "header"
        text_height = units.mm(p.margin_header if is_header else p.margin_footer)
        style = self._style_ids["header" if is_header else "footer"]
        return (
            f'<hp:ctrl><hp:{kind} id="{self._next_obj_id()}" applyPageType="BOTH">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
            f'vertAlign="{"TOP" if is_header else "BOTTOM"}" linkListIDRef="0" linkListNextIDRef="0" '
            f'textWidth="{p.text_width}" textHeight="{text_height}" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="{self._next_para_id()}" paraPrIDRef="{self.styles.para(para)}" styleIDRef="{style}" '
            f'pageBreak="0" columnBreak="0" merged="0">{"".join(pieces)}</hp:p>'
            f"</hp:subList></hp:{kind}></hp:ctrl>"
        )

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------
    def add_markdown(self, text: str, *, base_dir: str | Path | None = None) -> None:
        """Markdown 문자열을 해석해서 문서 끝에 덧붙인다."""
        from .markdown import render_markdown

        render_markdown(self, text, base_dir=Path(base_dir) if base_dir else Path.cwd())

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------
    def _sec_pr_xml(self) -> str:
        p = self.page
        return (
            '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" '
            'tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
            '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
            '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
            '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" '
            'fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
            '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
            f'<hp:pagePr landscape="{"NARROWLY" if p.landscape else "WIDELY"}" width="{p.width}" height="{p.height}" '
            'gutterType="LEFT_ONLY">'
            f'<hp:margin header="{units.mm(p.margin_header)}" footer="{units.mm(p.margin_footer)}" '
            f'gutter="{units.mm(p.gutter)}" left="{units.mm(p.margin_left)}" right="{units.mm(p.margin_right)}" '
            f'top="{units.mm(p.margin_top)}" bottom="{units.mm(p.margin_bottom)}"/>'
            "</hp:pagePr>"
            "<hp:footNotePr>"
            '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
            '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
            '<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>'
            '<hp:numbering type="CONTINUOUS" newNum="1"/>'
            '<hp:placement place="EACH_COLUMN" beneathText="0"/>'
            "</hp:footNotePr>"
            "<hp:endNotePr>"
            '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
            '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>'
            '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
            '<hp:numbering type="CONTINUOUS" newNum="1"/>'
            '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/>'
            "</hp:endNotePr>"
            + "".join(
                f'<hp:pageBorderFill type="{kind}" borderFillIDRef="1" textBorder="PAPER" headerInside="0" '
                'footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
                "</hp:pageBorderFill>"
                for kind in ("BOTH", "EVEN", "ODD")
            )
            + "</hp:secPr>"
        )

    def _section_xml(self) -> str:
        paragraphs = list(self._paragraphs)
        if self._pending_page_break or not paragraphs:
            paragraphs.append(
                _Paragraph(0, 0, '<hp:run charPrIDRef="0"><hp:t/></hp:run>', "", page_break=self._pending_page_break,
                           pid=self._next_para_id())
            )
        controls = self._sec_pr_xml() + (
            '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        )
        if self._header:
            controls += self._header_footer_ctrl("header", *self._header)
        if self._footer:
            controls += self._header_footer_ctrl("footer", *self._footer)
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', f"<hs:sec {NS_DECL}>"]
        for i, para in enumerate(paragraphs):
            first_run = f'<hp:run charPrIDRef="0">{controls}</hp:run>' if i == 0 else ""
            out.append(
                f'<hp:p id="{para.pid}" paraPrIDRef="{para.para_pr}" styleIDRef="{para.style}" '
                f'pageBreak="{int(para.page_break)}" columnBreak="0" merged="0">{first_run}{para.runs}</hp:p>'
            )
        out.append("</hs:sec>")
        return "".join(out)

    def _content_hpf(self) -> str:
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = f"<opf:title>{escape(self.title)}</opf:title>" if self.title else "<opf:title/>"
        author = escape(self.author)
        items = [
            '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>',
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>',
            '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>',
        ]
        items += [
            f'<opf:item id="{b.item_id}" href="{b.href}" media-type="{b.media_type}" isEmbeded="1"/>' for b in self._bins
        ]
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<opf:package {NS_DECL} version="" unique-identifier="" id="">'
            "<opf:metadata>"
            f"{title}<opf:language>ko</opf:language>"
            f'<opf:meta name="creator" content="text">{author}</opf:meta>'
            '<opf:meta name="subject" content="text"/>'
            '<opf:meta name="description" content="text"/>'
            f'<opf:meta name="lastsaveby" content="text">{author}</opf:meta>'
            f'<opf:meta name="CreatedDate" content="text">{now}</opf:meta>'
            f'<opf:meta name="ModifiedDate" content="text">{now}</opf:meta>'
            '<opf:meta name="keyword" content="text"/>'
            "</opf:metadata>"
            f"<opf:manifest>{''.join(items)}</opf:manifest>"
            '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine>'
            "</opf:package>"
        )

    def plain_text(self) -> str:
        """본문을 평문으로 (미리보기·검사용)."""
        return "\n".join(p.plain for p in self._paragraphs)

    def to_bytes(self) -> bytes:
        """완성된 .hwpx 파일 내용을 bytes 로 돌려준다."""
        section = self._section_xml()  # 머리말/꼬리말 서식도 여기서 등록되므로 header.xml 보다 먼저
        header = self.styles.header_xml()
        files: list[tuple[str, bytes | str]] = [
            (
                "version.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" '
                'major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" '
                'application="Hancom Office Hangul" appVersion="13, 0, 0, 1408 WIN32LEWindows_10"/>',
            ),
            ("Contents/header.xml", header),
            ("Contents/section0.xml", section),
            ("Contents/content.hpf", self._content_hpf()),
            (
                "settings.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                '<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
                'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
                '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>',
            ),
            ("Preview/PrvText.txt", self.plain_text()[:1024]),
            (
                "META-INF/container.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
                'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles>'
                '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
                '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
                '<ocf:rootfile full-path="META-INF/container.rdf" media-type="application/rdf+xml"/>'
                "</ocf:rootfiles></ocf:container>",
            ),
            (
                "META-INF/manifest.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>',
            ),
            ("META-INF/container.rdf", _CONTAINER_RDF),
        ]
        files += [(b.href, b.data) for b in self._bins]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # mimetype 은 반드시 첫 항목, 압축 없이
            zf.writestr(zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0)), "application/hwp+zip",
                        compress_type=zipfile.ZIP_STORED)
            for name, content in files:
                data = content.encode("utf-8") if isinstance(content, str) else content
                compress = zipfile.ZIP_STORED if name.startswith("BinData/") and name.endswith((".png", ".jpg", ".gif")) \
                    else zipfile.ZIP_DEFLATED
                zf.writestr(zipfile.ZipInfo(name, date_time=_dt.datetime.now().timetuple()[:6]), data,
                            compress_type=compress)
        return buf.getvalue()

    def save(self, path: str | Path) -> Path:
        """파일로 저장하고 경로를 돌려준다."""
        path = Path(path)
        if path.suffix.lower() != ".hwpx":
            path = path.with_suffix(".hwpx")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.to_bytes())
        return path


_CONTAINER_RDF = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
    'rdf:resource="Contents/header.xml"/></rdf:Description>'
    '<rdf:Description rdf:about="Contents/header.xml"><rdf:type '
    'rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#HeaderFile"/></rdf:Description>'
    '<rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
    'rdf:resource="Contents/section0.xml"/></rdf:Description>'
    '<rdf:Description rdf:about="Contents/section0.xml"><rdf:type '
    'rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description>'
    '<rdf:Description rdf:about=""><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/>'
    "</rdf:Description></rdf:RDF>"
)
