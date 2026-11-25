r"""수능 시험지 모양으로 조판하기 ([exam] 이 있는 양식, 예: 내장 양식 '모의고사').

평가원 수학 영역 문제지(A3)를 실측한 값을 기본으로 쓴다:

* 첫 쪽: '2027학년도 대학수학능력시험 문제지' · 쪽 번호 · (제 2 교시) · 수학 영역 · [홀수형] · 굵은 선
* 둘째 쪽부터: 바깥쪽 쪽 번호 · 가운데 '수학 영역' · 안쪽 [홀수형] · 굵은 선 (머리말)
* 2단, 가운데 세로선. 한 단을 위·아래 두 칸으로 나눠 문제를 칸 맨 위에 둔다
* 꼬리말: 가운데 '쪽/전체' 대각선 칸
* 선택과목은 새 쪽에서 '수학 영역(미적분)' 제목, 쪽 번호는 과목마다 1부터, 문제 번호는 23번부터
* 공통·선택과목이 끝나는 단 아래에 '※ 확인 사항' 상자

Markdown::

    ::: 시험지
    위: 2027학년도 대학수학능력시험 9월 모의평가 문제지
    교시: 제 2 교시
    영역: 수학 영역
    유형: 홀수형
    :::
    \5지선다형
    ::: 문제
    $\sqrt[3]{8}$의 값은? [2점]
    ① 1 ② 2 ③ 3 ④ 4 ⑤ 5
    [정답] ②
    :::
    ::: 문제 크게             ← 단 하나를 통째로 쓰는 문제 (기본은 반 단)
    ...
    :::
    \단답형
    \선택과목 미적분          ← 새 쪽, '수학 영역(미적분)', 23번부터
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

from . import units
from .document import HwpxDocument, Run, _Paragraph
from .styles import BorderFill, CharStyle, Line, ParaStyle, normalize_color
from .textbook import Template, Textbook, _COVER_NAMES, _split_problem

_EXAM_NAMES = {"시험지", "시험", "exam"} | _COVER_NAMES
_EXAM_KEY = re.compile(r"^\s*(위|교시|영역|유형|안내|저작권|top|period|subject|form|notice)\s*[:：]\s*(.*)$", re.I)
_EXAM_KEYS = {"위": "top_text", "top": "top_text", "교시": "period", "period": "period", "영역": "subject",
              "subject": "subject", "유형": "form", "form": "form", "안내": "notice", "저작권": "notice",
              "notice": "notice"}
_LABEL_DIRECTIVES = {"5지선다형": "5지선다형", "오지선다형": "5지선다형", "선다형": "5지선다형", "단답형": "단답형"}
_SUBJECT_DIRECTIVES = {"선택과목", "과목", "subject"}
_BIG_WORDS = {"크게", "큰", "1단", "전체", "full", "big"}


@dataclass
class ExamStyle:
    """시험지 모양 (길이 mm, 글자 pt, 장평 %). 기본값 = 평가원 수학 문제지 A3 실측."""

    top_text: str = "2027학년도 대학수학능력시험 문제지"
    period: str = "제 2 교시"
    subject: str = "수학 영역"
    form: str = "홀수형"  # "" 이면 홀수형 상자 없음
    notice: str = ""  # 꼬리말 오른쪽 아래 작은 글 (원본: '이 문제지에 관한 저작권은 …에 있습니다.')
    label_1: str = "5지선다형"  # \5지선다형 상자 글
    label_2: str = "단답형"
    check_title: str = "확인 사항"
    check_items: tuple[str, ...] = ("답안지의 해당란에 필요한 내용을 정확히 기입(표기)했는지 확인하시오.",)
    check_next: str = "이어서, 「선택과목({subject})」 문제가 제시되오니, 자신이 선택한 과목인지 확인하시오."
    check_box: bool = True  # 공통·선택과목 끝에 확인 사항 상자

    # 글꼴 (원본 PDF 에 들어 있는 한글 내장 글꼴)
    top_font: str = "신명 디나루"
    top_size: float = 21
    top_ratio: int = 85
    page_font: str = "신명 견명조"  # 머리말 큰 쪽 번호
    page_size: float = 33
    page_ratio: int = 90
    title_font: str = "한양견고딕"  # '수학 영역'
    title_size: float = 40  # 첫 쪽
    header_title_size: float = 28  # 둘째 쪽부터 머리말
    title_ratio: int = 95
    elective_font: str = "신명 신그래픽"  # '(미적분)'
    elective_size: float = 33
    header_elective_size: float = 28
    elective_ratio: int = 90
    period_font: str = "한양견명조"  # '제 2 교시'
    period_size: float = 22
    period_ratio: int = 80
    form_font: str = "한양견고딕"  # '홀수형'
    form_size: float = 28
    header_form_size: float = 20.5
    form_ratio: int = 85
    label_font: str = "#태고딕"  # '5지선다형' 상자
    label_size: float = 15
    label_ratio: int = 95
    check_font: str = "신명 중고딕"  # 확인 사항
    check_strong_font: str = "신명 태고딕"  # 「선택과목(…)」
    check_bullet_font: str = "명조"  # ◦
    check_size: float = 11
    check_ratio: int = 95
    footer_font: str = "신명 견명조"  # 꼬리말 '1/20'
    footer_size: float = 12
    footer_ratio: int = 95
    notice_font: str = "굴림"
    notice_size: float = 10

    # 자리 (mm)
    side_width: float = 50  # 머리말 왼쪽·오른쪽 칸 너비
    title_top: float = 38  # 첫 쪽 제목 덩어리 윗선 (종이 위에서)
    title_rule: float = 77  # 첫 쪽 굵은 선 (종이 위에서)
    title_row: float = 14  # 첫 쪽 제목 덩어리 윗줄 높이 ('…문제지' 줄)
    rule_width: str = "0.4 mm"  # 머리말·제목 아래 굵은 선
    period_box: tuple[float, float] = (32, 11)  # '제 2 교시' 둥근 상자
    period_round: int = 50
    form_box: tuple[float, float] = (28.5, 15.5)  # 첫 쪽 '홀수형' 상자
    header_form_box: tuple[float, float] = (21, 10.4)
    form_round: int = 15
    box_line: str = "0.2 mm"  # 둥근 상자 선
    column_line_width: str = "0.3 mm"
    slots: int = 2  # 한 단을 몇 칸으로 나눌지 (문제는 칸 맨 위에서 시작)
    slot_top: float = 6.5  # 칸 위 여백 (머리말 선 ~ 문제 번호)
    first_slot_top: float = 4.5  # 첫 쪽(제목 아래) 칸 위 여백
    label_box: tuple[float, float] = (39, 8.3)  # '5지선다형' 상자
    label_gap: float = 9  # 상자 아래 ~ 문제
    check_height: float = 36.2  # 확인 사항 상자 높이
    page_box: tuple[float, float] = (18, 7.8)  # 꼬리말 '1/20' 칸
    page_box_gap: float = 5.2  # 본문 아래 ~ 쪽 번호 칸

    @classmethod
    def from_dict(cls, data: dict | None, warnings: list[str] | None = None) -> "ExamStyle":
        names = {f.name: f for f in fields(cls)}
        changes = {}
        for key, value in (data or {}).items():
            if key not in names:
                if warnings is not None:
                    warnings.append(f"양식 [exam] 의 '{key}' 는 알 수 없는 항목이라 무시했습니다")
                continue
            if isinstance(value, list):
                value = tuple(value)
            changes[key] = value
        return replace(cls(), **changes)


@dataclass
class _Slot:
    paras: list[_Paragraph]
    units: int
    plain: str
    height: int = 0  # HWPUNIT (자리를 정할 때 계산)
    top: int = 0  # 칸 위 여백


class ExamPaper(Textbook):
    """확장 Markdown → 수능 시험지 모양 HWPX."""

    def __init__(self, template: Template | None = None) -> None:
        super().__init__(template)
        self.x = ExamStyle.from_dict(self.t.exam or {})
        self.started = False
        self.subject_name = ""  # 선택과목 이름 ("" = 공통)
        self.page = 0  # 과목 안 쪽 번호
        self.col = 0
        self.unit = 0  # 지금 단에서 쓴 칸 수
        self.first_page = True  # 지금 쪽이 제목 덩어리가 있는 쪽인지
        self.pending: _Slot | None = None  # 아직 놓지 않은 마지막 칸 (확인 사항을 붙일 수 있게)
        self.pending_label = ""
        self.force_break = False
        self.common_last: int | None = None
        self.unit_before = 0

    # -- 진입점 ------------------------------------------------------------
    def build(self, markdown: str, *, base_dir: str | Path | None = None, title: str = "") -> HwpxDocument:
        from .markdown import render_markdown

        t = self.t
        doc = HwpxDocument(t.page, t.theme, title=title or t.title)
        doc.warnings.extend(t.warnings)
        self.book_title = title or t.title
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        doc.set_columns(1)
        doc.add_ctrl("footer", self._footer_ctrl(doc))
        render_markdown(doc, markdown, base_dir=self.base_dir, handler=self)
        if not self.started:
            self._start(doc)
        self._finish_section(doc, None)
        if self.answers:
            doc.add_ctrl("header", self._header_ctrl(doc, number="", answers=True))
            self.render_answers(doc, restore_columns=False)
        return doc

    # -- 글자 모양 ---------------------------------------------------------
    def _char(self, doc: HwpxDocument, font: str, size: float, ratio: int | None = None, **kw) -> CharStyle:
        base = doc._body_char
        return replace(base, font=font, size=float(size), ratio=ratio, spacing=0 if ratio is not None else None,
                       bold=False, color=normalize_color(kw.pop("color", None)) or "#000000", **kw)

    def _runs(self, doc: HwpxDocument, char: CharStyle, content) -> str:
        xml, _ = doc._runs_xml(content, char)
        return xml

    def _cell_para(self, doc: HwpxDocument, xml: str, align: str = "CENTER", line_spacing: int = 100,
                   space_before: float = 0) -> _Paragraph:
        para = ParaStyle(align=align, line_spacing=line_spacing, space_before=units.mm(space_before))
        return _Paragraph(doc.styles.para(para), 0, xml, pid=doc._next_para_id())

    def _box_run(self, doc: HwpxDocument, text: str, char: CharStyle, size: tuple[float, float], ratio: int) -> str:
        rect = doc.rounded_box_xml(text, char, width=size[0], height=size[1], line_width=self.x.box_line, ratio=ratio)
        return f'<hp:run charPrIDRef="{doc.styles.char(char)}">{rect}<hp:t/></hp:run>'

    def _title_runs(self, doc: HwpxDocument, size: float, elective_size: float) -> str:
        x = self.x
        xml = self._runs(doc, self._char(doc, x.title_font, size, x.title_ratio), x.subject)
        if self.subject_name:
            xml += self._runs(doc, self._char(doc, x.elective_font, elective_size, x.elective_ratio),
                              f"({self.subject_name})")
        return xml

    # -- 머리말·꼬리말 -----------------------------------------------------
    def _header_ctrl(self, doc: HwpxDocument, number: str, answers: bool = False) -> str:
        """둘째 쪽부터의 머리말: 바깥쪽 쪽 번호, 가운데 과목, 안쪽 홀수형, 아래 굵은 선."""
        x = self.x
        width = doc.page.text_width
        side = units.mm(x.side_width)
        mid = width - 2 * side
        rule = Line("SOLID", x.rule_width, "#000000")
        bf = doc.styles.border(BorderFill(bottom=rule))
        num_xml = self._runs(doc, self._char(doc, x.page_font, x.page_size, x.page_ratio), number) if number else ""
        form_xml = ""
        if x.form and not answers:
            form_xml = self._box_run(doc, x.form, self._char(doc, x.form_font, x.header_form_size, x.form_ratio),
                                     x.header_form_box, x.form_round)
        if answers:
            title_xml = self._runs(doc, self._char(doc, x.title_font, x.header_title_size, x.title_ratio),
                                   self.t.answers.title)
        else:
            title_xml = self._title_runs(doc, x.header_title_size, x.header_elective_size)
        odd = (int(number) % 2 == 1) if number.isdigit() else True
        left, right = (form_xml, num_xml) if odd else (num_xml, form_xml)
        h = units.mm(doc.page.margin_header) - 200
        zero = (0, 0, 0, units.mm(0.6))
        cells = [
            doc._cell_xml(0, 0, side, [self._cell_para(doc, left, "LEFT")], bf, margin=zero, height=h),
            doc._cell_xml(0, 1, mid, [self._cell_para(doc, title_xml, "CENTER")], bf, margin=zero, height=h),
            doc._cell_xml(0, 2, side, [self._cell_para(doc, right, "RIGHT")], bf, margin=zero, height=h),
        ]
        tbl = doc._table_xml([f"<hp:tr>{''.join(cells)}</hp:tr>"], 3, width, h, bf, in_margin=(0, 0, 0, 0))
        para = _Paragraph(doc.styles.para(ParaStyle(align="LEFT", line_spacing=100)), 0,
                          f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run>', pid=doc._next_para_id())
        return doc.raw_header_footer("header", [para], vert_align="BOTTOM")

    def _footer_ctrl(self, doc: HwpxDocument) -> str:
        """꼬리말: 가운데 '쪽/전체' 대각선 칸 + (있으면) 오른쪽 아래 안내 글."""
        x = self.x
        char = self._char(doc, x.footer_font, x.footer_size, x.footer_ratio)
        w, h = units.mm(x.page_box[0]), units.mm(x.page_box[1])
        line = Line("SOLID", "0.12 mm", "#000000")
        bf = doc.styles.border(BorderFill(line, line, line, line, slash=True,
                                          diagonal=Line("SOLID", "0.12 mm", "#000000")))
        top = self._cell_para(doc, doc.page_number_runs("{page}", char), "LEFT", 90)
        bottom = self._cell_para(doc, doc.page_number_runs("{total}", char), "RIGHT", 90)
        cell = doc._cell_xml(0, 0, w, [top, bottom], bf, margin=(units.mm(0.8), units.mm(0.8), 0, 0), height=h)
        tbl = doc._table_xml([f"<hp:tr>{cell}</hp:tr>"], 1, w, h, bf, in_margin=(0, 0, 0, 0))
        paras = [_Paragraph(doc.styles.para(ParaStyle(align="CENTER", line_spacing=100,
                                                      space_before=units.mm(x.page_box_gap))), 0,
                            f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run>', pid=doc._next_para_id())]
        if x.notice:
            nchar = self._char(doc, x.notice_font, x.notice_size, 100)
            paras.append(self._cell_para(doc, self._runs(doc, nchar, x.notice), "RIGHT", 110,
                                         space_before=0.8))
        return doc.raw_header_footer("footer", paras, vert_align="TOP")

    # -- 쪽 시작 -----------------------------------------------------------
    def _title_block(self, doc: HwpxDocument) -> str:
        """첫 쪽 제목 덩어리 (종이 기준 고정 위치 표)."""
        x = self.x
        width = doc.page.text_width
        side = units.mm(x.side_width)
        mid = width - 2 * side
        h0 = units.mm(x.title_row)
        h1 = units.mm(x.title_rule - x.title_top - x.title_row)
        none_bf = doc.styles.border(BorderFill())
        rule_bf = doc.styles.border(BorderFill(bottom=Line("SOLID", x.rule_width, "#000000")))
        zero = (0, 0, 0, 0)
        top = self._runs(doc, self._char(doc, x.top_font, x.top_size, x.top_ratio), x.top_text)
        num = self._runs(doc, self._char(doc, x.page_font, x.page_size, x.page_ratio), "1")
        period = ""
        if x.period:
            period = self._box_run(doc, x.period, self._char(doc, x.period_font, x.period_size, x.period_ratio),
                                   x.period_box, x.period_round)
        form = ""
        if x.form:
            form = self._box_run(doc, x.form, self._char(doc, x.form_font, x.form_size, x.form_ratio), x.form_box,
                                 x.form_round)
        title = self._title_runs(doc, x.title_size, x.elective_size)
        low = (0, 0, 0, units.mm(2.5))
        rows = [
            "<hp:tr>"
            + doc._cell_xml(0, 0, side, [], none_bf, margin=zero, height=h0)
            + doc._cell_xml(0, 1, mid, [self._cell_para(doc, top)], none_bf, margin=zero, height=h0)
            + doc._cell_xml(0, 2, side, [self._cell_para(doc, num, "RIGHT")], none_bf, margin=zero, height=h0)
            + "</hp:tr>",
            "<hp:tr>"
            + doc._cell_xml(1, 0, side, [self._cell_para(doc, period, "LEFT")], rule_bf, margin=low, height=h1)
            + doc._cell_xml(1, 1, mid, [self._cell_para(doc, title)], rule_bf, margin=low, height=h1)
            + doc._cell_xml(1, 2, side, [self._cell_para(doc, form, "RIGHT")], rule_bf, margin=(0, 0, 0, units.mm(1)),
                            height=h1)
            + "</hp:tr>",
        ]
        return doc._table_xml(rows, 3, width, h0 + h1, none_bf, in_margin=(0, 0, 0, 0), inline=False, paper=True,
                              paper_offset=(units.mm(doc.page.margin_left), units.mm(x.title_top)))

    def _body_top(self, doc: HwpxDocument) -> float:
        p = doc.page
        return p.margin_top + p.margin_header

    def _column_height(self, doc: HwpxDocument, first: bool) -> float:
        p = doc.page
        h = p.size_mm()[1] - p.margin_top - p.margin_header - p.margin_bottom - p.margin_footer
        if first:
            h -= max(self.x.title_rule - self._body_top(doc), 0)
        return h

    def _title_page(self, doc: HwpxDocument) -> None:
        """새 과목의 첫 쪽: 제목 덩어리 + 빈 공간(1단) → 2단."""
        x = self.x
        doc.set_columns(1)
        doc.hide_on_this_page(header=True, footer=False)
        space = units.mm(max(x.title_rule - self._body_top(doc), 0))
        tbl = self._title_block(doc)
        cid = doc.styles.char(doc._tiny_char())
        para = ParaStyle(align="LEFT", line_spacing=100, space_after=max(space - units.pt(2), 0))
        doc._append(para, 0, f'<hp:run charPrIDRef="{cid}">{tbl}<hp:t/></hp:run>', "", kind="object")
        doc.set_columns(2, gap=self.t.column_gap, line=True, line_color="#000000", line_width=x.column_line_width)
        self.page, self.col, self.unit, self.first_page = 1, 0, 0, True

    def _start(self, doc: HwpxDocument) -> None:
        if not self.started:
            self.started = True
            self._title_page(doc)

    # -- 칸 -----------------------------------------------------------------
    def _slot_height(self, doc: HwpxDocument, n: int) -> int:
        h = self._column_height(doc, self.first_page)
        return units.mm(h * n / self.x.slots - 0.8)

    def _place(self, doc: HwpxDocument, slot: _Slot, check: list[_Paragraph] | None = None) -> None:
        """칸 하나를 고정 높이 표(테두리 없음)로 놓는다. check: 칸 아래쪽에 붙일 확인 사항 상자 문단."""
        x = self.x
        width = doc.column_width
        height, top = slot.height, slot.top
        none_bf = doc.styles.border(BorderFill())
        rows = []
        if check:
            box_h = units.mm(x.check_height)
            body_h = max(height - box_h, units.mm(5))
            rows.append("<hp:tr>" + doc._cell_xml(0, 0, width, slot.paras, none_bf, margin=(0, 0, top, 0),
                                                  vert_align="TOP", height=body_h) + "</hp:tr>")
            rows.append("<hp:tr>" + self._check_cell(doc, 1, width, box_h, check) + "</hp:tr>")
        else:
            rows.append("<hp:tr>" + doc._cell_xml(0, 0, width, slot.paras, none_bf, margin=(0, 0, top, 0),
                                                  vert_align="TOP", height=height) + "</hp:tr>")
        doc._place_table(rows, 1, width, height, none_bf, page_break="NONE", in_margin=(0, 0, 0, 0), inline=True,
                         plain=slot.plain)

    def _advance(self, doc: HwpxDocument, n: int) -> None:
        """n 칸을 쓸 자리로 옮긴다 (모자라면 다음 단·다음 쪽)."""
        n = max(1, min(n, self.x.slots))
        if self.force_break or self.unit + n > self.x.slots:
            self.force_break = False
            if self.col == 0:
                self.col = 1
                doc.add_column_break()
            else:
                self.col = 0
                self.page += 1
                self.first_page = False
                doc.add_page_break()
                doc.add_ctrl("header", self._header_ctrl(doc, str(self.page)))
            self.unit = 0
        self.unit_before = self.unit
        self.unit += n

    def _measure(self, doc: HwpxDocument, slot: _Slot) -> None:
        """방금 _advance 로 정한 자리의 칸 높이·위 여백을 적어 둔다 (칸은 나중에 놓으므로)."""
        x = self.x
        slot.height = self._slot_height(doc, slot.units)
        slot.top = units.mm(x.first_slot_top if (self.first_page and self.unit_before == 0) else x.slot_top)

    def _flush(self, doc: HwpxDocument, check: list[_Paragraph] | None = None) -> None:
        slot, self.pending = self.pending, None
        if slot is not None:
            self._place(doc, slot, check)

    def _push(self, doc: HwpxDocument, slot: _Slot) -> None:
        self._start(doc)
        self._flush(doc)
        self._advance(doc, slot.units)
        self._measure(doc, slot)
        self.pending = slot

    # -- 확인 사항 ---------------------------------------------------------
    def _check_paras(self, doc: HwpxDocument, next_subject: str | None) -> list[_Paragraph]:
        x = self.x
        width = doc.column_width - units.mm(8)
        char = self._char(doc, x.check_font, x.check_size, x.check_ratio)
        strong = self._char(doc, x.check_strong_font, x.check_size, x.check_ratio)
        bullet = self._char(doc, x.check_bullet_font, x.check_size, x.check_ratio)
        hang = units.mm(4)
        items = list(x.check_items)
        if next_subject:
            items.append(x.check_next.replace("{subject}", next_subject))
        paras = []
        with doc._capture(width) as cps:
            xml = self._runs(doc, char, "※ " + x.check_title)
            doc._append(ParaStyle(align="LEFT", line_spacing=150), 0, xml, "")
            for item in items:
                m = re.match(r"^(.*?)「(.*?)」(.*)$", item)
                xml = self._runs(doc, bullet, "◦ ")
                if m:
                    xml += self._runs(doc, char, m.group(1)) + self._runs(doc, strong, "「" + m.group(2) + "」")
                    xml += self._runs(doc, char, m.group(3))
                else:
                    xml += self._runs(doc, char, item)
                doc._append(ParaStyle(align="JUSTIFY", line_spacing=150, left=hang, indent=-hang,
                                      space_before=units.mm(1.5)), 0, xml, item)
        paras.extend(cps)
        return paras

    def _check_cell(self, doc: HwpxDocument, row: int, width: int, height: int, paras: list[_Paragraph]) -> str:
        """확인 사항 상자: 칸 아래쪽에 테두리 상자 (안에 표 하나)."""
        line = Line("SOLID", "0.12 mm", "#000000")
        box_bf = doc.styles.border(BorderFill(line, line, line, line))
        none_bf = doc.styles.border(BorderFill())
        pad = units.mm(4)
        inner = doc._cell_xml(0, 0, width, paras, box_bf, margin=(pad, pad, units.mm(2), units.mm(2)),
                              vert_align="TOP", height=height)
        tbl = doc._table_xml([f"<hp:tr>{inner}</hp:tr>"], 1, width, height, box_bf, in_margin=(0, 0, 0, 0))
        holder = _Paragraph(doc.styles.para(ParaStyle(align="LEFT", line_spacing=100)), 0,
                            f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run>', pid=doc._next_para_id())
        return doc._cell_xml(row, 0, width, [holder], none_bf, margin=(0, 0, 0, 0), vert_align="BOTTOM",
                             height=height)

    def _finish_section(self, doc: HwpxDocument, next_subject: str | None) -> None:
        """과목 하나가 끝날 때: 지금 단 아래에 확인 사항 상자."""
        if not self.started:
            return
        if not self.x.check_box:
            self._flush(doc)
            return
        check = self._check_paras(doc, next_subject)
        if self.pending is not None and self.unit >= self.x.slots:
            self._flush(doc, check)  # 단이 꽉 찼으면 마지막 칸 아래쪽에
            return
        self._flush(doc)
        rest = self.x.slots - self.unit
        if rest <= 0:
            rest = self.x.slots
            self._advance(doc, rest)
        else:
            self.unit_before = self.unit
            self.unit += rest
        filler = _Slot([], rest, "")
        self._measure(doc, filler)
        self._place(doc, filler, check)

    # -- 처리기 ------------------------------------------------------------
    def heading(self, doc: HwpxDocument, level: int, raw: str, inline) -> bool:
        return False

    def directive(self, doc: HwpxDocument, name: str, arg: str) -> bool:
        key = name.lower()
        if name in _LABEL_DIRECTIVES:
            label = _LABEL_DIRECTIVES[name]
            self.pending_label = self.x.label_1 if label == "5지선다형" else self.x.label_2
            return True
        if key in _SUBJECT_DIRECTIVES:
            subject = arg.strip()
            self._start(doc)
            self._finish_section(doc, subject)
            if self.common_last is None:
                self.common_last = self.problem_no
            self.problem_no = self.common_last
            self.subject_name = subject
            doc.add_page_break()
            self._title_page(doc)
            return True
        if key in ("columnbreak", "다음단"):
            self._flush(doc)
            self.force_break = True
            return True
        if key in ("newpage", "pagebreak", "clearpage", "다음쪽"):
            self._flush(doc)
            self.force_break = True
            if self.col == 0:
                self.col = 1  # 다음 _advance 가 새 쪽으로
            return True
        return super().directive(doc, name, arg)

    def container(self, doc: HwpxDocument, kind: str, title: str, lines: list[str], base_dir: Path, inline) -> bool:
        if kind.lower() in _EXAM_NAMES:
            self._exam_info(lines, title)
            return True
        if kind.lower() in self._problem_names:
            self.render_problem(doc, title, lines, inline)
            return True
        return super().container(doc, kind, title, lines, base_dir, inline)

    def _exam_info(self, lines: list[str], title: str) -> None:
        changes = {}
        for line in lines:
            m = _EXAM_KEY.match(line)
            if m:
                changes[_EXAM_KEYS[m.group(1).lower()]] = m.group(2).strip()
        if title and "top_text" not in changes:
            changes["top_text"] = title
        self.x = replace(self.x, **changes)

    # -- 문제 ---------------------------------------------------------------
    def render_problem(self, doc: HwpxDocument, title: str, lines: list[str], inline) -> None:
        p, x = self.t.problem, self.x
        words = set(title.lower().split())
        n = x.slots if words & _BIG_WORDS else 1
        m = re.search(r"(\d+)\s*칸", title)
        if m:
            n = int(m.group(1))
        self.problem_no += 1
        number = p.number_format.format(n=self.problem_no, chapter=self.chapter)
        stem, answer, solution = _split_problem(lines)
        width = doc.column_width
        with doc._capture(width) as paras:
            if self.pending_label:
                self._label(doc, self.pending_label)
                self.pending_label = ""
            with doc.style_scope(font=p.font, size=p.size, line_spacing=p.line_spacing), \
                    doc.display_scope(align=p.display_align, background=None, indent=p.display_indent):
                hang = units.mm(p.indent)
                with doc.indented(hang):
                    doc.set_paragraph_prefix([self._number_run(number), Run(" ")], hang=hang)
                    self._render(doc, stem)
                    doc.flush_prefix()
        self._push(doc, _Slot(list(paras), n, "\n".join(q.plain for q in paras)))
        if answer or any(s.strip() for s in solution):
            from .textbook import _AnswerEntry

            self.answers.append(_AnswerEntry(self.chapter, self.subject_name, number, answer, solution, ""))

    def _number_run(self, text: str, color: str | None = None) -> Run:
        p = self.t.problem
        return Run(text, bold=p.number_bold, color=color or p.number_color, size=p.number_size,
                   font=p.number_font or self.t.theme.heading_font)

    def _label(self, doc: HwpxDocument, text: str) -> None:
        """'5지선다형' / '단답형' 테두리 상자 (단 맨 위)."""
        x = self.x
        w, h = units.mm(x.label_box[0]), units.mm(x.label_box[1])
        line = Line("SOLID", "0.12 mm", "#000000")
        bf = doc.styles.border(BorderFill(line, line, line, line))
        char = self._char(doc, x.label_font, x.label_size, x.label_ratio)
        cell = doc._cell_xml(0, 0, w, [self._cell_para(doc, self._runs(doc, char, text))], bf,
                             margin=(0, 0, 0, 0), height=h)
        doc._place_table([f"<hp:tr>{cell}</hp:tr>"], 1, w, h, bf, in_margin=(0, 0, 0, 0), inline=True,
                         space_after=x.label_gap / 0.3528, plain=text)
