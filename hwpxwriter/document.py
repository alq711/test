"""HWPX 문서 빌더.

사용 예::

    from hwpxwriter import HwpxDocument, Run

    doc = HwpxDocument()
    doc.add_heading("보고서 제목", level=1)
    doc.add_paragraph(["일반 글자와 ", Run("굵은 글자", bold=True), "를 섞어 씁니다."])
    doc.add_paragraph(["넓이는 ", Run(r"\\pi r^2", equation=True), " 입니다."])
    with doc.box(label="정의", title="원의 넓이"):
        doc.add_equation(r"S = \\pi r^2")
    doc.add_table([["이름", "점수"], ["홍길동", "95"]])
    doc.set_footer("- {page} -")
    doc.save("report.hwpx")

문단은 기본적으로 본문에 쌓이지만, box() 같은 문맥 안에서는 표 칸 안에 쌓인다.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import re
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterator, Sequence, Union
from xml.sax.saxutils import escape

from . import units
from .images import ImageInfo, probe
from .latex import _letter_w, latex_to_hwp
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
    """같은 글자 모양을 가진 글자 묶음. text 안의 '\\n' 은 줄바꿈(Shift+Enter)이 된다.

    equation=True 이면 text 를 LaTeX 수식으로 보고 한글 수식 개체로 넣는다.
    """

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
    equation: bool = False
    border: str | None = None  # 글자 테두리 색 (예: '주의' 꼬리표)


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
    equation_font: str = "HancomEQN"  # 한글 수식 글꼴 (옛 모양: HYhwpEQ)
    equation_size: float | None = None  # 수식 글자 크기 pt (None = 주변 글자 크기)
    choice_symbols: tuple[str, ...] = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩")
    bullet_color: str | None = None  # 글머리표 색
    display_align: str = "center"  # $$수식$$ 정렬
    display_background: str | None = None  # $$수식$$ 줄 배경색
    display_indent: float = 0.0  # $$수식$$ 왼쪽 들여쓰기 (mm)
    table_style: str = "grid"  # grid: 모든 칸 테두리 / booktabs: 위·아래 굵은 선만
    table_rule_color: str = "#000000"  # booktabs 굵은 선 색
    table_row_line_color: str | None = None  # booktabs 행 사이 가는 선 색 (None = 없음)
    heading_styles: dict = field(default_factory=dict)  # {단계: HeadingStyle}


@dataclass
class HeadingStyle:
    """제목 한 단계의 모양. None 은 기본값(Theme 의 heading_sizes/heading_color)을 따른다."""

    size: float | None = None
    color: str | None = None
    font: str | None = None
    bold: bool = True
    align: str = "left"
    number_color: str | None = None  # '09 제목' 의 09 색 (None = 제목과 같음)
    number_size: float | None = None
    number_font: str | None = None
    sub_color: str = "#595959"  # '제목 | 보조' 의 보조 글 색
    sub_size: float | None = None
    sub_bold: bool = False
    rule_color: str | None = None  # 아래 선 색 (None = 선 없음)
    rule_width: str = "0.12 mm"
    rule_gap: float = 5.0  # 글자와 아래 선 사이 (pt)
    space_before: float | None = None  # pt
    space_after: float | None = None  # pt


@dataclass
class HeaderSpec:
    """머리말/꼬리말. right 가 있으면 왼쪽·오른쪽으로 나눈 한 줄."""

    left: object = ""
    right: object = None
    align: str = "CENTER"
    rule_color: str | None = None  # 아래(머리말)/위(꼬리말) 가는 선
    right_color: str | None = None
    right_bold: bool = True


@dataclass
class BoxStyle:
    """상자(정의·정리·예제 등) 모양.

    kind
      * "bar"    : 위쪽에 색 띠(제목 줄) + 아래 내용
      * "inline" : 내용 첫머리에 [꼬리표] + 제목
      * "line"   : 왼쪽 굵은 세로줄만
      * "plain"  : 테두리 상자만
      * "titled" : 제목을 상자 위 가운데에 (〈보 기〉)
      * "tag"    : 표 없이 테두리 글자 이름표 + 내어쓰기 (주의)
    """

    kind: str = "bar"
    border_color: str = "#2E74B5"
    border_width: str = "0.25 mm"
    border_type: str = "SOLID"
    background: str | None = None
    title_background: str | None = "#2E74B5"
    title_color: str = "#FFFFFF"
    label_color: str = "#2E74B5"
    padding: float = 3.0  # mm
    title_size: float | None = None  # pt (None = 본문 크기)


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
    column_break: bool = False
    ctrl: str = ""  # 문단 맨 앞에 넣을 조판 부호 (단 설정 등)
    pid: int = -1


@dataclass
class _BinItem:
    item_id: str
    href: str
    media_type: str
    data: bytes


@dataclass
class _Prefix:
    xml: str
    plain: str
    hang: int
    suffix_xml: str = ""
    suffix_plain: str = ""


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"\{(page|total|쪽|전체쪽)\}")
_BOX_PAGE_BREAK = "TABLE"  # 상자는 쪽 경계에서 칸 안쪽까지 나눔


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


def _box_fill(color: str, width: str, kind: str, fill: str | None) -> BorderFill:
    line = Line(kind, width, color)
    return BorderFill(line, line, line, line, fill)


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
        self.warnings: list[str] = []
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
        self._sink: list[_Paragraph] = self._paragraphs
        self._width_stack: list[int] = []
        self._left = 0  # 현재 문맥의 추가 왼쪽 여백 (HWPUNIT)
        self._prefix: _Prefix | None = None
        self._bins: list[_BinItem] = []
        self._bin_by_hash: dict[str, str] = {}
        self._header: HeaderSpec | None = None
        self._footer: HeaderSpec | None = None
        self.hide_first_page = False  # 첫 쪽(표지)에서 머리말·꼬리말·쪽 번호 감추기
        self._pending_page_break = False
        self._pending_column_break = False
        self._pending_ctrls: dict[str, str] = {}  # 다음 문단 앞에 넣을 조판 부호 (단 설정, 머리말 교체 등)
        self._columns = (1, units.mm(8), None)  # (단 수, 간격, 구분선 Line|None)
        self._initial_columns = self._columns
        self._para_id = 0
        self._obj_id = 0
        self._zorder = 0
        self._style_ids = self._register_named_styles()

    # ------------------------------------------------------------------
    # 너비·문맥
    # ------------------------------------------------------------------
    @property
    def column_width(self) -> int:
        count, gap, _ = self._columns
        return (self.page.text_width - gap * (count - 1)) // count

    @property
    def available_width(self) -> int:
        """지금 문단이 쓸 수 있는 너비 (HWPUNIT): 단 너비 또는 상자 안쪽 너비에서 들여쓰기를 뺀 값."""
        base = self._width_stack[-1] if self._width_stack else self.column_width
        return max(base - self._left, units.mm(10))

    @property
    def at_top_level(self) -> bool:
        return self._sink is self._paragraphs

    @contextmanager
    def indented(self, amount: int) -> Iterator[None]:
        """안쪽 문단 전체를 amount(HWPUNIT)만큼 들여쓴다."""
        self._left += amount
        try:
            yield
        finally:
            self._left -= amount

    @contextmanager
    def _capture(self, width: int) -> Iterator[list[_Paragraph]]:
        """안쪽에서 추가한 문단을 본문 대신 목록에 모은다 (표 칸 내용 만들기용)."""
        saved = (self._sink, self._left)
        target: list[_Paragraph] = []
        self._sink, self._left = target, 0
        self._width_stack.append(width)
        try:
            yield target
        finally:
            self._width_stack.pop()
            self._sink, self._left = saved

    def set_paragraph_prefix(
        self,
        prefix: Content,
        *,
        hang: int = 0,
        suffix: Content | None = None,
    ) -> None:
        """다음 글 문단 앞(과 뒤)에 붙일 글자. hang>0 이면 내어쓰기(첫 줄만 왼쪽으로)."""
        xml, plain = self._runs_xml(prefix, self._body_char)
        sxml, splain = self._runs_xml(suffix, self._body_char) if suffix else ("", "")
        self._prefix = _Prefix(xml, plain, hang, sxml, splain)

    def flush_prefix(self) -> None:
        """남아 있는 문단 앞 글자를 혼자 한 문단으로 내보낸다."""
        if self._prefix is not None:
            self._append(self._body_para, self._style_ids["body"], "", "")

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------
    def _heading_style(self, level: int) -> HeadingStyle:
        hs = self.theme.heading_styles.get(level) or self.theme.heading_styles.get(str(level))
        return hs or HeadingStyle()

    def _heading_styles(self, level: int) -> tuple[CharStyle, ParaStyle]:
        t = self.theme
        hs = self._heading_style(level)
        sizes = t.heading_sizes
        size = hs.size or sizes[min(level, len(sizes)) - 1]
        char = CharStyle(font=hs.font or t.heading_font, size=size, bold=hs.bold,
                         color=normalize_color(hs.color or t.heading_color) or "#000000")
        before = hs.space_before if hs.space_before is not None else size * (0.9 if level <= 2 else 0.6)
        after = hs.space_after if hs.space_after is not None else size * 0.4
        para = ParaStyle(
            align=normalize_align(hs.align, "LEFT"),
            line_spacing=min(t.line_spacing, 150),
            space_before=units.pt(before),
            space_after=units.pt(after),
            keep_with_next=True,
        )
        if hs.rule_color:
            bf = self.styles.border(BorderFill(bottom=Line("SOLID", hs.rule_width, normalize_color(hs.rule_color))))
            para = replace(para, border_fill=bf, border_offset_bottom=units.pt(hs.rule_gap),
                           space_after=para.space_after + units.pt(hs.rule_gap))
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

    def _tiny_char(self) -> CharStyle:
        return replace(self._body_char, size=2)

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
        if run.border:
            line = Line("SOLID", "0.12 mm", normalize_color(run.border) or "#000000")
            updates["border_fill"] = self.styles.border(BorderFill(line, line, line, line))
        return replace(cs, **updates) if updates else cs

    def _equation_xml(self, latex: str, char: CharStyle) -> str:
        eq = latex_to_hwp(latex)
        for w in eq.warnings:
            self.warnings.append(f"수식 ${latex}$: {w}")
        if not eq.script:
            return ""
        base_unit = round((self.theme.equation_size or char.size) * 100)
        width, height, base_line = eq.size(base_unit)
        eq_id = self._next_obj_id()
        self._zorder += 1
        return (
            f'<hp:equation id="{eq_id}" zOrder="{self._zorder}" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM" '
            'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" version="Equation Version 60" '
            f'baseLine="{base_line}" textColor="{char.color}" baseUnit="{base_unit}" lineMode="CHAR" '
            f'font="{escape(self.theme.equation_font)}">'
            f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="56" right="56" top="0" bottom="0"/>'
            "<hp:shapeComment>수식입니다.</hp:shapeComment>"
            f"<hp:script>{escape(eq.script)}</hp:script>"
            "</hp:equation>"
        )

    def _runs_xml(self, content: Content | None, base: CharStyle) -> tuple[str, str]:
        """(XML, 평문) — 같은 글자 모양이 이어지면 하나의 hp:run 으로 합친다."""
        segs: list[list] = []  # ["t", cid, text] | ["eq", cid, xml, latex]
        for run in _as_runs(content):
            if not run.text:
                continue
            cid = self.styles.char(self._char_for(run, base))
            if run.equation:
                xml = self._equation_xml(run.text, self._char_for(run, base))
                if xml:
                    segs.append(["eq", cid, xml, run.text])
                continue
            if segs and segs[-1][0] == "t" and segs[-1][1] == cid:
                segs[-1][2] += run.text
            else:
                segs.append(["t", cid, run.text])
        if not segs:
            return f'<hp:run charPrIDRef="{self.styles.char(base)}"><hp:t/></hp:run>', ""
        out, plain = [], []
        for seg in segs:
            if seg[0] == "t":
                out.append(f'<hp:run charPrIDRef="{seg[1]}"><hp:t>{_xml_text(seg[2])}</hp:t></hp:run>')
                plain.append(seg[2])
            else:
                out.append(f'<hp:run charPrIDRef="{seg[1]}">{seg[2]}</hp:run>')
                plain.append(f"${seg[3]}$")
        return "".join(out), "".join(plain)

    def estimate_width(self, content: Content, size: float | None = None) -> int:
        """글자들이 차지할 대략의 너비 (HWPUNIT)."""
        em = units.pt(size or self.theme.font_size)
        total = 0.0
        for run in _as_runs(content):
            if run.equation:
                eq = latex_to_hwp(run.text)
                total += eq.width * 1.08 + 0.3
            else:
                total += sum(_letter_w(c, upright=True) for c in run.text)
        return int(total * em)

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

    def _append(self, para_pr: ParaStyle, style: int, runs_xml: str, plain: str, *, kind: str = "text") -> None:
        if self._prefix is not None:
            pre = self._prefix
            if kind == "text" and para_pr.align == "CENTER" and not pre.hang:
                # 가운데 정렬 문단(수식 한 줄 등) 앞에 이름표를 붙이면 어색하므로 따로 한 줄
                self._prefix = None
                self._append(replace(self._body_para, keep_with_next=True), self._style_ids["body"],
                             pre.xml + pre.suffix_xml, pre.plain + pre.suffix_plain)
            elif kind == "text":
                self._prefix = None
                runs_xml = pre.xml + runs_xml + pre.suffix_xml
                plain = pre.plain + plain + pre.suffix_plain
                if pre.hang:
                    para_pr = replace(para_pr, indent=-pre.hang, align="JUSTIFY" if para_pr.align == "CENTER"
                                      else para_pr.align)
            else:
                self.flush_prefix()
        if self._left:
            para_pr = replace(para_pr, left=para_pr.left + self._left)
        top = self.at_top_level
        para = _Paragraph(
            self.styles.para(para_pr),
            style,
            runs_xml or f'<hp:run charPrIDRef="{self.styles.char(self._body_char)}"><hp:t/></hp:run>',
            plain,
            page_break=top and self._pending_page_break,
            column_break=top and self._pending_column_break,
            ctrl="".join(self._pending_ctrls.values()) if top else "",
            pid=self._next_para_id(),
        )
        if top:
            self._pending_page_break = self._pending_column_break = False
            self._pending_ctrls = {}
        self._sink.append(para)

    def _para_xml(self, p: _Paragraph, first_run: str = "") -> str:
        ctrl = f'<hp:run charPrIDRef="0">{p.ctrl}</hp:run>' if p.ctrl and not first_run else ""
        return (
            f'<hp:p id="{p.pid}" paraPrIDRef="{p.para_pr}" styleIDRef="{p.style}" '
            f'pageBreak="{int(p.page_break)}" columnBreak="{int(p.column_break)}" merged="0">'
            f"{first_run}{ctrl}{p.runs}</hp:p>"
        )

    # ------------------------------------------------------------------
    # 표 (내부 공통)
    # ------------------------------------------------------------------
    def _cell_xml(
        self,
        row: int,
        col: int,
        width: int,
        paragraphs: list[_Paragraph],
        border_fill: int,
        *,
        header: bool = False,
        margin: tuple[int, int, int, int] | None = None,
        vert_align: str = "CENTER",
        height: int = 282,
    ) -> str:
        if not paragraphs:
            paragraphs = [_Paragraph(0, 0, '<hp:run charPrIDRef="0"><hp:t/></hp:run>', pid=self._next_para_id())]
        left, right, top, bottom = margin or (510, 510, 141, 141)
        return (
            f'<hp:tc name="" header="{int(header)}" hasMargin="{int(margin is not None)}" protect="0" editable="0" '
            f'dirty="0" borderFillIDRef="{border_fill}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{vert_align}" '
            'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f"{''.join(self._para_xml(p) for p in paragraphs)}"
            "</hp:subList>"
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{width}" height="{height}"/>'
            f'<hp:cellMargin left="{left}" right="{right}" top="{top}" bottom="{bottom}"/>'
            "</hp:tc>"
        )

    def _place_table(
        self,
        rows_xml: list[str],
        n_cols: int,
        total_width: int,
        total_height: int,
        border_fill: int,
        *,
        page_break: str = "CELL",
        repeat_header: bool = False,
        in_margin: tuple[int, int, int, int] = (510, 510, 141, 141),
        space_after: float = 0,
        align: str = "LEFT",
        inline: bool | None = None,
        plain: str = "",
        keep_with_next: bool = False,
    ) -> None:
        """표 XML 을 만들어 한 문단에 넣는다.

        본문 바로 아래의 표는 '글자처럼 취급'을 끄고 문단에 붙여(자리차지) 쪽 경계에서 나뉠 수 있게 하고,
        상자·표 안에 들어가는 표는 글자처럼 취급한다.
        """
        if inline is None:
            inline = not self.at_top_level
        gap = units.pt(space_after)
        tbl = self._table_xml(rows_xml, n_cols, total_width, total_height, border_fill, page_break=page_break,
                              repeat_header=repeat_header, in_margin=in_margin, gap=gap, align=align, inline=inline)
        if inline:
            para = replace(self._body_para, align=align, line_spacing=100, space_after=gap, keep_with_next=keep_with_next)
            cid = 0
        else:
            para = replace(self._body_para, align="LEFT", line_spacing=100, space_after=0, keep_with_next=keep_with_next)
            cid = self.styles.char(self._tiny_char())
        self._append(para, 0, f'<hp:run charPrIDRef="{cid}">{tbl}<hp:t/></hp:run>', plain, kind="object")

    def _table_xml(
        self,
        rows_xml: list[str],
        n_cols: int,
        total_width: int,
        total_height: int,
        border_fill: int,
        *,
        page_break: str = "CELL",
        repeat_header: bool = False,
        in_margin: tuple[int, int, int, int] = (510, 510, 141, 141),
        gap: int = 0,
        align: str = "LEFT",
        inline: bool = True,
        paper: bool = False,
    ) -> str:
        tbl_id = self._next_obj_id()
        self._zorder += 1
        text_wrap = "TOP_AND_BOTTOM"
        if paper:  # 종이 기준 위치 (표지 띠 등)
            text_wrap = "IN_FRONT_OF_TEXT"
            pos = (
                '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="1" holdAnchorAndSO="0" '
                'vertRelTo="PAPER" horzRelTo="PAPER" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            )
            out_margin = '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        elif inline:
            pos = (
                '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
                'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            )
            out_margin = '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        else:
            pos = (
                '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
                f'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="{align}" vertOffset="0" horzOffset="0"/>'
            )
            out_margin = f'<hp:outMargin left="0" right="0" top="{units.pt(2)}" bottom="{gap}"/>'
        l, r, t, b = in_margin
        return (
            f'<hp:tbl id="{tbl_id}" zOrder="{self._zorder}" numberingType="TABLE" textWrap="{text_wrap}" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="{page_break}" '
            f'repeatHeader="{int(repeat_header)}" rowCnt="{len(rows_xml)}" colCnt="{n_cols}" cellSpacing="0" '
            f'borderFillIDRef="{border_fill}" noAdjust="0">'
            f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="{total_height}" '
            'heightRelTo="ABSOLUTE" protect="0"/>'
            f"{pos}{out_margin}"
            f'<hp:inMargin left="{l}" right="{r}" top="{t}" bottom="{b}"/>'
            f"{''.join(rows_xml)}"
            "</hp:tbl>"
        )

    # ------------------------------------------------------------------
    # 공개 API: 본문
    # ------------------------------------------------------------------
    def add_heading(
        self,
        content: Content,
        level: int = 1,
        *,
        align: str | None = None,
        number: str | None = None,
        sub: Content | None = None,
    ) -> None:
        """제목 (level 1~6). number='09' 는 제목 앞 번호, sub 는 제목 뒤 보조 글 (양식의 색·크기)."""
        level = max(1, min(6, int(level)))
        char, para = self._heading_styles(level)
        hs = self._heading_style(level)
        if align:
            para = replace(para, align=normalize_align(align))
        xml, plain = "", ""
        if number:
            num_char = replace(char, color=normalize_color(hs.number_color) or char.color,
                               size=hs.number_size or char.size, font=hs.number_font or char.font)
            nx, np_ = self._runs_xml(Run(number), num_char)
            sx, _ = self._runs_xml(Run("  "), char)
            xml, plain = nx + sx, np_ + "  "
        cx, cp = self._runs_xml(content, char)
        xml, plain = xml + cx, plain + cp
        if sub:
            sub_char = replace(char, bold=hs.sub_bold, color=normalize_color(hs.sub_color) or char.color,
                               size=hs.sub_size or char.size)
            sx, sp = self._runs_xml([Run("  ")] + _as_runs(sub), sub_char)
            xml, plain = xml + sx, plain + sp
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
        font: str | None = None,
        indent: float = 0,
        left: float = 0,
        space_before: float | None = None,
        space_after: float | None = None,
        line_spacing: int | None = None,
        keep_with_next: bool = False,
    ) -> None:
        """본문 문단. indent/left/space_* 단위는 pt."""
        char = self._body_char
        if size or bold or italic or color or font:
            char = replace(
                char,
                size=float(size) if size else char.size,
                bold=bold or char.bold,
                italic=italic or char.italic,
                color=normalize_color(color) if color else char.color,
                font=font or char.font,
            )
        para = self._body_para
        changes: dict[str, object] = {}
        if align:
            changes["align"] = normalize_align(align)
        if indent:
            changes["indent"] = units.pt(indent)
        if left:
            changes["left"] = units.pt(left)
        if space_before is not None:
            changes["space_before"] = units.pt(space_before)
        if space_after is not None:
            changes["space_after"] = units.pt(space_after)
        if line_spacing:
            changes["line_spacing"] = int(line_spacing)
        if keep_with_next:
            changes["keep_with_next"] = True
        if changes:
            para = replace(para, **changes)
        xml, plain = self._runs_xml(content, char)
        self._append(para, self._style_ids["body"], xml, plain)

    def add_equation(self, latex: str, *, align: str | None = None, size: float | None = None,
                     background: str | None = None, indent: float | None = None) -> None:
        """수식 한 줄. 정렬·배경·들여쓰기를 안 주면 Theme(display_*)·display_scope 설정을 따른다."""
        t = self.theme
        align = normalize_align(align or t.display_align, "CENTER")
        background = background if background is not None else t.display_background
        indent = t.display_indent if indent is None else indent
        para = replace(self._body_para, align=align, left=units.mm(indent))
        if background:
            bf = self.styles.border(BorderFill(fill=normalize_color(background)))
            gap = units.pt(5)
            para = replace(para, border_fill=bf, border_offset_top=gap, border_offset_bottom=gap,
                           space_before=para.space_before + gap, space_after=para.space_after + gap + units.pt(2),
                           line_spacing=120)
        xml, plain = self._runs_xml([Run(latex, equation=True, size=size)], self._body_char)
        self._append(para, self._style_ids["body"], xml, plain)

    @contextmanager
    def display_scope(self, *, align: str | None = None, background: str | None = "",
                      indent: float | None = None) -> Iterator[None]:
        """안쪽의 $$수식$$ 모양을 잠시 바꾼다 (background=None 이면 배경 없음, "" 이면 그대로)."""
        saved = self.theme
        changes: dict[str, object] = {}
        if align is not None:
            changes["display_align"] = align
        if background != "":
            changes["display_background"] = background
        if indent is not None:
            changes["display_indent"] = indent
        self.theme = replace(saved, **changes)
        try:
            yield
        finally:
            self.theme = saved

    @contextmanager
    def style_scope(self, *, font: str | None = None, size: float | None = None, line_spacing: int | None = None,
                    color: str | None = None, paragraph_spacing: float | None = None) -> Iterator[None]:
        """안쪽 본문 글자·문단 모양을 잠시 바꾼다 (예: 문제는 명조, 해설은 작게)."""
        saved = (self._body_char, self._body_para)
        char_changes: dict[str, object] = {}
        if font:
            char_changes["font"] = font
        if size:
            char_changes["size"] = float(size)
        if color:
            char_changes["color"] = normalize_color(color)
        para_changes: dict[str, object] = {}
        if line_spacing:
            para_changes["line_spacing"] = int(line_spacing)
        if paragraph_spacing is not None:
            para_changes["space_after"] = units.pt(paragraph_spacing)
        self._body_char = replace(self._body_char, **char_changes)
        self._body_para = replace(self._body_para, **para_changes)
        try:
            yield
        finally:
            self._body_char, self._body_para = saved

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
        is_bullet = ordered_number is None and marker in t.bullets
        mark = Run(marker, color=t.bullet_color if is_bullet else None,
                   size=self._body_char.size * 0.8 if is_bullet and t.bullet_color else None)
        runs = [mark, Run(" ")] + _as_runs(content)
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

    def add_horizontal_rule(self, *, color: str = "#999999", width: str = "0.25 mm", space_after: float = 8) -> None:
        """가로 구분선."""
        bf = self.styles.border(BorderFill(bottom=Line("SOLID", width, normalize_color(color) or "#999999")))
        para = replace(self._body_para, border_fill=bf, line_spacing=100, space_after=units.pt(space_after),
                       space_before=0)
        xml, plain = self._runs_xml("", replace(self._body_char, size=4))
        self._append(para, 0, xml, plain, kind="object")

    def add_split_line(
        self,
        left: Content,
        right: Content,
        *,
        left_size: float | None = None,
        right_size: float | None = None,
        right_color: str | None = None,
        rule: str | None = None,
        ratio: tuple[float, float] = (1, 1),
        space_after: float = 3,
        keep_with_next: bool = True,
    ) -> None:
        """한 줄을 왼쪽·오른쪽으로 나눠 쓴다 (예: 문제 번호 ↔ 출처, 해설 번호 ↔ 정답). rule: 아래 가는 선 색."""
        self.flush_prefix()
        width = self.available_width
        widths = _distribute(width, list(ratio))
        line = Line("SOLID", "0.12 mm", normalize_color(rule)) if rule else Line()
        bf = self.styles.border(BorderFill(bottom=line))
        lchar = replace(self._body_char, size=float(left_size)) if left_size else self._body_char
        rchar = replace(self._body_char, size=float(right_size) if right_size else self._body_char.size,
                        color=normalize_color(right_color) if right_color else self._body_char.color)
        cells = []
        for c, (content, align, ch) in enumerate(((left, "LEFT", lchar), (right, "RIGHT", rchar))):
            with self._capture(widths[c]) as cps:
                xml, plain = self._runs_xml(content, ch)
                self._append(ParaStyle(align=align, line_spacing=120), 0, xml, plain)
            cells.append(self._cell_xml(0, c, widths[c], cps, bf, margin=(0, 0, 0, units.pt(3) if rule else 0),
                                        vert_align="BOTTOM", height=units.pt(lchar.size * 1.5)))
        plain = "".join(x.text for x in _as_runs(left)) + "\t" + "".join(x.text for x in _as_runs(right))
        self._place_table([f"<hp:tr>{''.join(cells)}</hp:tr>"], 2, width, units.pt(lchar.size * 1.5), bf,
                          in_margin=(0, 0, 0, 0), space_after=space_after, inline=True, plain=plain,
                          keep_with_next=keep_with_next)

    def add_page_band(self, color: str, height: float = 6.0) -> None:
        """종이 맨 위에 꽉 찬 색 띠 (표지용). height: mm."""
        bf = self.styles.border(BorderFill(fill=normalize_color(color)))
        w, h = self.page.width, units.mm(height)
        with self._capture(w) as cps:
            self._append(ParaStyle(line_spacing=100), 0, "", "")
        row = "<hp:tr>" + self._cell_xml(0, 0, w, cps, bf, margin=(0, 0, 0, 0), height=h) + "</hp:tr>"
        tbl = self._table_xml([row], 1, w, h, bf, in_margin=(0, 0, 0, 0), inline=False, paper=True)
        para = replace(self._body_para, line_spacing=100, space_after=0, space_before=0)
        cid = self.styles.char(self._tiny_char())
        self._append(para, 0, f'<hp:run charPrIDRef="{cid}">{tbl}<hp:t/></hp:run>', "", kind="object")

    def add_spacer(self, height_mm: float) -> None:
        """빈 공간 (풀이 공간 등)."""
        para = replace(self._body_para, line_spacing=100, space_after=units.mm(height_mm))
        xml, plain = self._runs_xml("", self._tiny_char())
        self._append(para, 0, xml, plain, kind="object")

    def add_page_break(self) -> None:
        """다음 문단을 새 쪽에서 시작한다."""
        if self.at_top_level:
            self._pending_page_break = True

    def add_column_break(self) -> None:
        """다음 문단을 다음 단에서 시작한다."""
        if self.at_top_level:
            self._pending_column_break = True

    def set_columns(self, count: int, *, gap: float = 8.0, line: bool | str = False, line_color: str = "#999999") -> None:
        """다단 설정. 이후 문단부터 count 단으로 나눈다 (gap: 단 사이 mm, line: 구분선)."""
        if not self.at_top_level:
            raise ValueError("다단 설정은 본문에서만 바꿀 수 있습니다")
        count = max(1, min(int(count), 4))
        sep = None
        if line:
            sep = Line(line if isinstance(line, str) else "SOLID", "0.12 mm", normalize_color(line_color) or "#999999")
        cols = (count, units.mm(gap), sep)
        if not self._paragraphs:
            self._initial_columns = cols
        else:
            self._pending_ctrls["cols"] = f"<hp:ctrl>{self._col_pr_xml(cols)}</hp:ctrl>"
        self._columns = cols

    @staticmethod
    def _col_pr_xml(cols: tuple[int, int, Line | None]) -> str:
        count, gap, sep = cols
        head = (
            f'<hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{count}" sameSz="1" '
            f'sameGap="{gap if count > 1 else 0}"'
        )
        if sep is None or count == 1:
            return head + "/>"
        return head + f'><hp:colLine type="{sep.type}" width="{sep.width}" color="{sep.color}"/></hp:colPr>'

    # ------------------------------------------------------------------
    # 상자
    # ------------------------------------------------------------------
    @contextmanager
    def box(
        self,
        *,
        label: Content | None = None,
        title: Content | None = None,
        style: BoxStyle | None = None,
    ) -> Iterator[None]:
        """정의·정리·예제 같은 상자. with 문 안에서 추가한 내용이 상자 안에 들어간다."""
        st = style or BoxStyle()
        self.flush_prefix()
        if st.kind == "tag":
            # 표 없이: [이름표] 를 테두리 글자로 앞에 두고 내용은 내어쓰기
            color = normalize_color(st.label_color or st.border_color) or "#000000"
            size = st.title_size or max(self._body_char.size - 2, 6)
            tag = [replace(r, border=st.border_color, size=size, color=r.color or color, bold=True)
                   for r in _as_runs(label or "")]
            prefix = tag + [Run("  ")]
            if title:
                prefix += [replace(r, bold=True) for r in _as_runs(title)] + [Run("  ")]
            hang = max(self.estimate_width(tag, size) + units.mm(st.padding) + units.pt(6), units.mm(8))
            with self.indented(hang):
                self.set_paragraph_prefix(prefix, hang=hang)
                yield
                self.flush_prefix()
            return
        width = self.available_width
        pad = units.mm(st.padding)
        inner = width - 2 * pad
        border_color = normalize_color(st.border_color) or "#000000"
        title_char = replace(self._body_char, bold=True, font=self.theme.heading_font,
                             size=st.title_size or self._body_char.size)
        head_runs: list[Run] = []
        if label:
            head_runs += [replace(r, bold=True) for r in _as_runs(label)]
        if title:
            if head_runs:
                head_runs.append(Run("  "))
            head_runs += _as_runs(title)

        if st.kind == "line":
            side = Line(st.border_type, "1.0 mm" if st.border_width in ("0.1 mm", "0.12 mm") else st.border_width,
                        border_color)
            content_bf = BorderFill(left=side, fill=normalize_color(st.background) if st.background else None)
        else:
            content_bf = _box_fill(border_color, st.border_width, st.border_type,
                                   normalize_color(st.background) if st.background else None)
        content_bf_id = self.styles.border(content_bf)

        with self._capture(inner) as paras:
            if head_runs and st.kind in ("inline", "line", "plain"):
                color = normalize_color(st.label_color) or border_color
                colored = [replace(r, color=r.color or color) for r in head_runs]
                if st.kind == "inline":
                    self.set_paragraph_prefix(colored + [Run("  ")])
                else:
                    xml, plain = self._runs_xml(colored, title_char)
                    self._append(replace(self._body_para, keep_with_next=True), self._style_ids["body"], xml, plain)
            yield
            self.flush_prefix()
        # 마지막 문단의 문단 뒤 간격은 상자 안쪽 여백과 겹치므로 그대로 둔다
        rows_xml = []
        row = 0
        if head_runs and st.kind == "titled":
            # 제목을 상자 위 가운데에 (〈보 기〉 모양)
            none_bf = self.styles.border(BorderFill())
            with self._capture(inner) as tparas:
                tchar = replace(self._body_char, color=normalize_color(st.title_color) or self._body_char.color)
                xml, plain = self._runs_xml([replace(r, bold=False) for r in head_runs], tchar)
                self._append(ParaStyle(align="CENTER", line_spacing=120, keep_with_next=True), 0, xml, plain)
            rows_xml.append(
                "<hp:tr>" + self._cell_xml(row, 0, width, tparas, none_bf, margin=(0, 0, 0, units.pt(1))) + "</hp:tr>"
            )
            row += 1
        elif head_runs and st.kind == "bar":
            title_fill = normalize_color(st.title_background) if st.title_background else border_color
            title_bf = self.styles.border(_box_fill(border_color, st.border_width, st.border_type, title_fill))
            with self._capture(inner) as tparas:
                tchar = replace(title_char, color=normalize_color(st.title_color) or "#FFFFFF")
                xml, plain = self._runs_xml(head_runs, tchar)
                self._append(ParaStyle(align="LEFT", line_spacing=130), 0, xml, plain)
            rows_xml.append(
                "<hp:tr>"
                + self._cell_xml(row, 0, width, tparas, title_bf, margin=(pad, pad, units.mm(1.2), units.mm(1.2)))
                + "</hp:tr>"
            )
            row += 1
        rows_xml.append(
            "<hp:tr>"
            + self._cell_xml(row, 0, width, paras, content_bf_id, margin=(pad, pad, pad, max(pad - units.pt(4), 0)),
                             vert_align="TOP")
            + "</hp:tr>"
        )
        plain = "\n".join(p.plain for p in paras)
        self._place_table(
            rows_xml,
            1,
            width,
            282 * len(rows_xml),
            content_bf_id,
            page_break=_BOX_PAGE_BREAK,
            in_margin=(pad, pad, pad, pad),
            space_after=self.theme.paragraph_spacing + 4,
            plain=plain,
        )

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
        width: 표 전체 너비 (mm). 없으면 쓸 수 있는 너비 전체.
        """
        if not rows:
            return
        self.flush_prefix()
        n_cols = max(len(r) for r in rows)
        grid = [list(r) + [""] * (n_cols - len(r)) for r in rows]
        t = self.theme
        total_width = min(units.mm(width), self.available_width) if width else self.available_width
        if col_widths and len(col_widths) == n_cols:
            weights = [max(float(w), 0.01) for w in col_widths]
        else:
            weights = []
            for c in range(n_cols):
                longest = max(self.estimate_width(row[c]) for row in grid) / max(units.pt(t.font_size) / 2, 1)
                weights.append(min(max(longest, 4), 40))
        widths = _distribute(total_width, weights)
        col_align = [normalize_align(a, "LEFT") if a else "LEFT" for a in (align or [])]
        col_align += ["LEFT"] * (n_cols - len(col_align))

        border_color = normalize_color(t.table_border_color) or "#000000"
        body_bf = self.styles.border(BorderFill.box("0.12 mm", border_color))
        head_bf = self.styles.border(
            BorderFill.box("0.12 mm", border_color, normalize_color(t.table_header_background))
        )
        booktabs = t.table_style == "booktabs"
        if booktabs:
            rule = normalize_color(t.table_rule_color) or "#000000"
            thick, thin = Line("SOLID", "0.4 mm", rule), Line("SOLID", "0.12 mm", rule)
            row_line = Line("SOLID", "0.12 mm", normalize_color(t.table_row_line_color)) if t.table_row_line_color \
                else Line()
            n = len(grid)

            def booktabs_bf(r: int) -> int:
                top = thick if r == 0 else Line()
                if header and r == 0:
                    bottom = thin
                elif r == n - 1:
                    bottom = thick
                else:
                    bottom = row_line
                return self.styles.border(BorderFill(top=top, bottom=bottom))

            body_bf = self.styles.border(BorderFill())
        cell_char = replace(self._body_char, size=float(font_size)) if font_size else self._body_char
        head_char = replace(cell_char, bold=True)
        row_height = units.pt(cell_char.size * 1.6) + 282

        rows_xml = []
        for r, row in enumerate(grid):
            is_head = header and r == 0
            cell_bf = booktabs_bf(r) if booktabs else (head_bf if is_head else body_bf)
            cells = []
            for c, cell in enumerate(row):
                para = ParaStyle(align="CENTER" if is_head else col_align[c], line_spacing=130)
                with self._capture(widths[c] - 1020) as cps:
                    xml, plain = self._runs_xml(cell, head_char if is_head else cell_char)
                    self._append(para, 0, xml, plain)
                cells.append(self._cell_xml(r, c, widths[c], cps, cell_bf, header=is_head, height=row_height))
            rows_xml.append(f"<hp:tr>{''.join(cells)}</hp:tr>")

        if caption is not None:
            self._add_caption(caption, space_after=2)
        plain = "\n".join("\t".join("".join(x.text for x in _as_runs(c)) for c in row) for row in grid)
        self._place_table(rows_xml, n_cols, sum(widths), row_height * len(grid), body_bf, repeat_header=header,
                          space_after=t.paragraph_spacing + 4, align="CENTER", plain=plain)

    def add_answer_grid(
        self,
        items: Sequence[tuple[Content, Content]],
        *,
        columns: int = 10,
        rule_color: str = "#000000",
        line_color: str = "#BFBFBF",
        number_color: str | None = None,
    ) -> None:
        """빠른 정답표: 칸마다 위에 번호(굵게), 아래에 정답. 위는 굵은 선, 줄 사이는 가는 선."""
        if not items:
            return
        self.flush_prefix()
        columns = max(1, columns)
        width = self.available_width
        widths = _distribute(width, [1] * columns)
        thick = Line("SOLID", "0.4 mm", normalize_color(rule_color) or "#000000")
        thin = Line("SOLID", "0.12 mm", normalize_color(line_color) or "#BFBFBF")
        n_rows = -(-len(items) // columns)
        row_h = units.pt(self._body_char.size * 3.2)
        num_char = replace(self._body_char, bold=True, color=normalize_color(number_color) or self._body_char.color)
        rows_xml = []
        for r in range(n_rows):
            bf = self.styles.border(BorderFill(top=thick if r == 0 else thin, bottom=thin))
            cells = []
            for c in range(columns):
                k = r * columns + c
                with self._capture(widths[c]) as cps:
                    if k < len(items):
                        num, ans = items[k]
                        para = ParaStyle(align="CENTER", line_spacing=150)
                        xml1, p1 = self._runs_xml(num, num_char)
                        xml2, p2 = self._runs_xml(ans, self._body_char)
                        self._append(para, 0, xml1, p1)
                        self._append(para, 0, xml2, p2)
                cells.append(self._cell_xml(r, c, widths[c], cps, bf, margin=(0, 0, units.pt(3), units.pt(3)),
                                            height=row_h))
            rows_xml.append(f"<hp:tr>{''.join(cells)}</hp:tr>")
        none_bf = self.styles.border(BorderFill())
        plain = "  ".join("".join(x.text for x in _as_runs(n)) + " " + "".join(x.text for x in _as_runs(a))
                          for n, a in items)
        self._place_table(rows_xml, columns, width, row_h * n_rows, none_bf, in_margin=(0, 0, 0, 0),
                          space_after=self.theme.paragraph_spacing + 8, plain=plain)

    def add_choices(self, choices: Sequence[Content], *, columns: int | None = None,
                    symbols: Sequence[str] | None = None) -> None:
        """객관식 보기 ①②③④⑤. 보기 길이에 맞춰 한 줄에 5개 / 3개 / 2개 / 1개씩 자동 배치."""
        if not choices:
            return
        self.flush_prefix()
        symbols = list(symbols or self.theme.choice_symbols)
        items = []
        for i, choice in enumerate(choices):
            mark = symbols[i] if i < len(symbols) else f"({i + 1})"
            items.append([Run(mark + " ")] + _as_runs(choice))
        width = self.available_width
        if columns is None:
            longest = max(self.estimate_width(it) for it in items) + units.pt(self.theme.font_size)
            columns = 1
            for cand in (5, 3, 2):
                if cand <= len(items) and longest * cand <= width:
                    columns = cand
                    break
            if columns == 3 and len(items) == 4:
                columns = 2
        columns = max(1, min(columns, len(items)))
        n_rows = -(-len(items) // columns)
        widths = _distribute(width, [1] * columns)
        none_bf = self.styles.border(BorderFill())
        row_h = units.pt(self.theme.font_size * 1.8)
        rows_xml = []
        for r in range(n_rows):
            cells = []
            for c in range(columns):
                k = r * columns + c
                with self._capture(widths[c]) as cps:
                    if k < len(items):
                        xml, plain = self._runs_xml(items[k], self._body_char)
                        self._append(ParaStyle(align="LEFT", line_spacing=self.theme.line_spacing), 0, xml, plain)
                cells.append(self._cell_xml(r, c, widths[c], cps, none_bf, margin=(0, units.pt(4), 0, units.pt(2)),
                                            height=row_h))
            rows_xml.append(f"<hp:tr>{''.join(cells)}</hp:tr>")
        plain = "  ".join("".join(x.text for x in it) for it in items)
        self._place_table(rows_xml, columns, width, row_h * n_rows, none_bf, in_margin=(0, 0, 0, 0),
                          space_after=self.theme.paragraph_spacing, inline=True, plain=plain)

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

        width: 너비 (mm). width_ratio: 쓸 수 있는 너비 대비 비율 (0~1).
        둘 다 없으면 원본 크기(96 DPI 기준)로 넣되 영역을 넘지 않게 줄인다.
        """
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        info = probe(data)
        dpi = info.dpi_x or units.DEFAULT_DPI
        w = units.px(info.width, dpi)
        h = units.px(info.height, info.dpi_y or dpi)
        if w <= 0 or h <= 0:
            raise ValueError("그림 크기가 0 입니다")
        max_w = self.available_width
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
        self._append(para, 0, f'<hp:run charPrIDRef="0">{pic}<hp:t/></hp:run>', "", kind="object")
        if caption is not None:
            self._add_caption(caption, space_after=self.theme.paragraph_spacing + 6)

    def _add_caption(self, caption: Content, *, space_after: float) -> None:
        para = replace(self._caption_para(), space_after=units.pt(space_after))
        xml, plain = self._runs_xml(caption, self._caption_char())
        self._append(para, self._style_ids["caption"], xml, plain)

    # ------------------------------------------------------------------
    # 머리말 / 꼬리말
    # ------------------------------------------------------------------
    def _spec(self, content: Content | None, align: str, right: Content | None, rule: str | None,
              right_color: str | None, right_bold: bool) -> HeaderSpec | None:
        if not content and not right:
            return None
        return HeaderSpec(content or "", right, normalize_align(align), normalize_color(rule) if rule else None,
                          normalize_color(right_color) if right_color else None, right_bold)

    def set_header(self, content: Content | None, *, align: str = "center", right: Content | None = None,
                   rule: str | None = None, right_color: str | None = None, right_bold: bool = True) -> None:
        """머리말. 글자 안의 {page} 는 쪽 번호, {total} 은 전체 쪽 수로 바뀐다.

        right 를 주면 한 줄을 왼쪽(content)·오른쪽(right)으로 나눈다. rule 은 아래 가는 선 색.
        """
        self._header = self._spec(content, align, right, rule, right_color, right_bold)

    def set_footer(self, content: Content | None, *, align: str = "center", right: Content | None = None,
                   rule: str | None = None, right_color: str | None = None, right_bold: bool = True) -> None:
        """꼬리말. 예: set_footer('- {page} -') 또는 set_footer('{page} / {total}', align='right')."""
        self._footer = self._spec(content, align, right, rule, right_color, right_bold)

    def change_header(self, content: Content | None, **kw) -> None:
        """이 다음 문단이 있는 쪽부터 머리말을 바꾼다 (set_header 와 같은 인자)."""
        spec = self._spec(content, kw.get("align", "center"), kw.get("right"), kw.get("rule"),
                          kw.get("right_color"), kw.get("right_bold", True))
        if not self._paragraphs:
            self._header = spec
        elif spec is not None:
            self._pending_ctrls["header"] = self._header_footer_ctrl("header", spec)

    def change_footer(self, content: Content | None, **kw) -> None:
        """이 다음 문단이 있는 쪽부터 꼬리말을 바꾼다."""
        spec = self._spec(content, kw.get("align", "center"), kw.get("right"), kw.get("rule"),
                          kw.get("right_color"), kw.get("right_bold", True))
        if not self._paragraphs:
            self._footer = spec
        elif spec is not None:
            self._pending_ctrls["footer"] = self._header_footer_ctrl("footer", spec)

    def hide_on_this_page(self, *, header: bool = True, footer: bool = True, page_num: bool = False) -> None:
        """다음 문단이 있는 쪽에서만 머리말/꼬리말을 감춘다 (한글의 '현재 쪽만 감추기')."""
        self._pending_ctrls["hide"] = (
            f'<hp:ctrl><hp:pageHiding hideHeader="{int(header)}" hideFooter="{int(footer)}" hideMasterPage="0" '
            f'hideBorder="0" hideFill="0" hidePageNum="{int(page_num)}"/></hp:ctrl>'
        )

    def _hf_runs(self, content: Content, char: CharStyle) -> str:
        cid = self.styles.char(char)
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
        return "".join(pieces) or f'<hp:run charPrIDRef="{cid}"><hp:t/></hp:run>'

    def _header_footer_ctrl(self, kind: str, spec: HeaderSpec) -> str:
        char = self._header_footer_char()
        p = self.page
        is_header = kind == "header"
        style = self._style_ids["header" if is_header else "footer"]
        width = p.text_width
        if spec.right is None and not spec.rule_color:
            para = ParaStyle(align=spec.align, line_spacing=150)
            body = (
                f'<hp:p id="{self._next_para_id()}" paraPrIDRef="{self.styles.para(para)}" styleIDRef="{style}" '
                f'pageBreak="0" columnBreak="0" merged="0">{self._hf_runs(spec.left, char)}</hp:p>'
            )
        else:
            # 한 줄을 표 칸으로: 왼쪽 글 / 오른쪽 글 + 아래(머리말) 또는 위(꼬리말) 가는 선
            line = Line("SOLID", "0.12 mm", spec.rule_color) if spec.rule_color else Line()
            bf = self.styles.border(BorderFill(bottom=line) if is_header else BorderFill(top=line))
            right_char = replace(char, bold=spec.right_bold, color=spec.right_color or char.color)
            parts = [(spec.left, "LEFT" if spec.right is not None else spec.align, char)]
            if spec.right is not None:
                parts.append((spec.right, "RIGHT", right_char))
            widths = _distribute(width, [3, 2] if len(parts) == 2 else [1])
            cells = []
            for c, (content, align, ch) in enumerate(parts):
                para = ParaStyle(align=align, line_spacing=130)
                cp = _Paragraph(self.styles.para(para), style, self._hf_runs(content, ch), pid=self._next_para_id())
                cells.append(self._cell_xml(0, c, widths[c], [cp], bf, margin=(0, 0, 0, units.pt(2)),
                                            vert_align="BOTTOM"))
            tbl = self._table_xml([f"<hp:tr>{''.join(cells)}</hp:tr>"], len(parts), width, units.pt(12), bf,
                                  inline=True, in_margin=(0, 0, 0, 0))
            para = ParaStyle(align="LEFT", line_spacing=100)
            body = (
                f'<hp:p id="{self._next_para_id()}" paraPrIDRef="{self.styles.para(para)}" styleIDRef="{style}" '
                f'pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run></hp:p>'
            )
        text_height = units.mm(p.margin_header if is_header else p.margin_footer)
        return (
            f'<hp:ctrl><hp:{kind} id="{self._next_obj_id()}" applyPageType="BOTH">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
            f'vertAlign="{"TOP" if is_header else "BOTTOM"}" linkListIDRef="0" linkListNextIDRef="0" '
            f'textWidth="{width}" textHeight="{text_height}" hasTextRef="0" hasNumRef="0">'
            f"{body}</hp:subList></hp:{kind}></hp:ctrl>"
        )

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------
    def add_markdown(self, text: str, *, base_dir: str | Path | None = None, handler=None) -> None:
        """Markdown 문자열을 해석해서 문서 끝에 덧붙인다."""
        from .markdown import render_markdown

        render_markdown(self, text, base_dir=Path(base_dir) if base_dir else Path.cwd(), handler=handler)

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
            f'<hp:visibility hideFirstHeader="{int(self.hide_first_page)}" '
            f'hideFirstFooter="{int(self.hide_first_page)}" hideFirstMasterPage="0" border="SHOW_ALL" '
            f'fill="SHOW_ALL" hideFirstPageNum="{int(self.hide_first_page)}" hideFirstEmptyLine="0" showLineNumber="0"/>'
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
        if self._pending_page_break or self._pending_column_break or self._pending_ctrls or not paragraphs:
            paragraphs.append(
                _Paragraph(0, 0, '<hp:run charPrIDRef="0"><hp:t/></hp:run>', "", page_break=self._pending_page_break,
                           column_break=self._pending_column_break, ctrl="".join(self._pending_ctrls.values()),
                           pid=self._next_para_id())
            )
        controls = self._sec_pr_xml() + f"<hp:ctrl>{self._col_pr_xml(self._initial_columns)}</hp:ctrl>"
        if self._header:
            controls += self._header_footer_ctrl("header", self._header)
        if self._footer:
            controls += self._header_footer_ctrl("footer", self._footer)
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', f"<hs:sec {NS_DECL}>"]
        for i, para in enumerate(paragraphs):
            first = f'<hp:run charPrIDRef="0">{controls}{para.ctrl}</hp:run>' if i == 0 else ""
            out.append(self._para_xml(para, first))
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
        now = _dt.datetime.now().timetuple()[:6]
        with zipfile.ZipFile(buf, "w") as zf:
            # mimetype 은 반드시 첫 항목, 압축 없이
            zf.writestr(zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0)), "application/hwp+zip",
                        compress_type=zipfile.ZIP_STORED)
            for name, content in files:
                data = content.encode("utf-8") if isinstance(content, str) else content
                stored = name.startswith("BinData/") and name.endswith((".png", ".jpg", ".gif"))
                zf.writestr(zipfile.ZipInfo(name, date_time=now), data,
                            compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
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
