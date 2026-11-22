r"""수학 교재 만들기: 양식(TOML) + 확장 Markdown → HWPX.

Markdown 확장 문법 (자세한 설명은 README)::

    ::: 표지                         ← 표지 (제목·부제·설명·저자)
    제목: 수능 파이널
    :::
    # 09 수직선 위의 운동             ← 대단원: 새 쪽, 큰 번호 + 제목 + 굵은 선
    \머리말 공통 9번                  ← 이 단원부터 머리말 오른쪽 글
    ## 핵심 개념
    ### 1 위치·속도·가속도의 관계
    $$v(t) = x'(t)$$                 ← 회색 배경 수식 줄 (양식 설정)
    ::: 주의
    ...                              ← 테두리 꼬리표 + 내어쓰기
    :::
    ## 최근 기출 | 공통 9번
    ::: 문제 2027학년도 9월 모의평가 9번   ← 번호(자동) ↔ 출처, 2단으로 자동 전환
    문제 내용 [4점]
    ::: 보기
    ㄱ. ...
    :::
    ① ㄱ ② ㄱ, ㄴ ...
    [정답] ②
    [해설]
    해설 내용                        ← 책 뒤 '정답과 해설'로 옮겨짐
    :::
    \정답                           ← 지금까지 모인 정답과 해설을 여기에 (없으면 문서 끝)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Callable

from . import units
from .document import BoxStyle, HeadingStyle, HwpxDocument, PageSetup, Run, Theme
from .markdown import MarkdownHandler, parse_inline, render_markdown, split_heading

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _toml = None  # type: ignore[assignment]

TEMPLATE_DIR = Path(__file__).with_name("templates")
BUILTIN_TEMPLATE = TEMPLATE_DIR / "수학교재.toml"
_BUILTIN_ALIASES = {"기본": "수학교재", "default": "수학교재", "math": "수학교재", "suneung": "문제집", "수능파이널": "문제집", "workbook": "문제집"}

_PROBLEM_NAMES = {"문제", "problem", "연습문제", "연습", "exercise"}
_COVER_NAMES = {"표지", "cover"}
_ANSWER_DIRECTIVES = {"정답", "해설", "정답과해설", "answers", "solutions"}
_HEADER_DIRECTIVES = {"머리말", "header", "running"}
_ANSWER_MARK = re.compile(r"^\s*\[(정답|답|answer)\]\s*(.*)$", re.I)
_SOLUTION_MARK = re.compile(r"^\s*\[(해설|풀이|solution)\]\s*(.*)$", re.I)
_COVER_KEY = re.compile(r"^\s*(위|제목|부제|설명|아래|저자|top|title|subtitle|author)\s*[:：]\s*(.*)$", re.I)
_COVER_KEYS = {"위": "top", "제목": "title", "부제": "subtitle", "설명": "desc", "아래": "author", "저자": "author"}


# ---------------------------------------------------------------------------
# 양식
# ---------------------------------------------------------------------------


@dataclass
class ProblemStyle:
    layout: str = "inline"  # inline: '01 문제…' 한 줄 / header: 번호 ↔ 출처 줄을 따로
    number_format: str = "{n:02d}"  # {n}=번호, {chapter}=대단원 번호
    number_color: str = "#2E74B5"
    number_size: float = 12.0
    number_font: str | None = None  # None = 제목 글꼴
    number_bold: bool = True
    source_color: str = "#7F7F7F"  # layout=header 일 때 출처 글
    source_size: float = 8.0
    indent: float = 9.0  # mm: (inline) 번호 뒤 본문이 시작하는 위치
    reset: str = "chapter"  # chapter: 대단원마다 1부터 / never: 계속 이어서
    space_after: float = 6.0  # mm: 문제 뒤 빈 공간(풀이 공간)
    title_bold: bool = True  # (inline) ::: 문제 [3점] 의 [3점] 을 굵게
    font: str | None = None  # 문제 본문 글꼴 (None = 본문 글꼴)
    size: float | None = None
    line_spacing: int | None = None
    display_align: str | None = None  # 문제 안 $$수식$$ 정렬 (None = 본문과 같게)
    display_indent: float = 0.0  # mm
    columns: int = 0  # 문제가 나오면 자동으로 바꿀 단 수 (0 = 그대로)
    column_line: bool = True
    names: tuple[str, ...] = tuple(sorted(_PROBLEM_NAMES))
    # 문제 구역: 이 제목으로 시작하는 '## ' 제목부터 다음 '## ' 제목까지
    section_titles: tuple[str, ...] = ("확인 문제", "연습 문제", "기출 문제", "최근 기출", "실전 문제", "유형 문제")
    new_page: bool = False  # 문제 구역을 새 쪽에서 시작 (개념 쪽과 문제 쪽을 나눔). 개념으로 돌아갈 때도 새 쪽
    section_header: str | None = None  # 문제 구역 머리말 오른쪽 글. {chapter}=단원, {section}=구역 제목


@dataclass
class AnswerStyle:
    title: str = "정답과 해설"
    new_page: bool = True
    columns: int = 2
    column_line: bool = True
    quick_table: bool = True  # 빠른 정답표
    quick_style: str = "table"  # table: '01 ③' 칸 / grid: 위 번호·아래 정답 격자
    quick_columns: int = 5
    answer_label: str = "정답"
    show_chapters: bool | None = None  # 대단원별로 묶기 (None = 번호가 대단원마다 다시 시작할 때만)
    entry_layout: str = "inline"  # inline: '01 정답 ③' / line: '01 출처 …… 정답 ③' + 가는 선
    rule_color: str = "#BFBFBF"
    font: str | None = None
    size: float | None = None
    line_spacing: int | None = None


@dataclass
class CoverStyle:
    band_color: str | None = None  # 종이 맨 위 띠 색
    band_height: float = 6.0  # mm
    top_space: float = 70.0  # mm: 위쪽 빈 공간
    top_color: str = "#595959"
    top_size: float = 11.0
    title_size: float = 40.0
    title_color: str = "#222222"
    subtitle_size: float = 18.0
    subtitle_color: str = "#1F3864"
    subtitle_sub_size: float = 12.0
    rule_color: str = "#000000"
    desc_color: str = "#595959"
    desc_size: float = 9.0
    author_space: float = 110.0  # mm: 설명과 저자 사이 (author_y 가 없을 때)
    author_size: float = 10.0
    author_y: float | None = None  # mm: 종이 위에서 저자 줄까지 (정하면 본문 흐름과 상관없이 그 자리에)
    author_color: str = "#222222"


@dataclass
class HeaderDef:
    left: str = ""
    right: str | None = None  # "{chapter}" 는 대단원 제목으로 바뀜
    align: str = "center"
    rule: str | None = None
    right_color: str | None = None
    right_bold: bool = True

    def kwargs(self, right: str | None) -> dict:
        return dict(align=self.align, right=right, rule=self.rule, right_color=self.right_color,
                    right_bold=self.right_bold)


@dataclass
class BoxDef:
    style: BoxStyle = field(default_factory=BoxStyle)
    label: str = ""
    numbered: bool = False
    label_format: str = "{label} {n}"  # {label} {n} {chapter}
    solution_label: str = "풀이"
    solution_color: str | None = None  # None = 상자 색


@dataclass
class Template:
    page: PageSetup = field(default_factory=PageSetup)
    theme: Theme = field(default_factory=Theme)
    title: str = ""
    header: HeaderDef | None = None
    footer: HeaderDef | None = field(default_factory=lambda: HeaderDef("- {page} -"))
    columns: int = 1
    column_gap: float = 8.0
    column_line: bool = False
    chapter_new_page: bool = True
    chapter_hide_header: str = "none"  # 대단원 첫 쪽 머리말·꼬리말 감추기: none / numbered / all
    problem: ProblemStyle = field(default_factory=ProblemStyle)
    answers: AnswerStyle = field(default_factory=AnswerStyle)
    cover: CoverStyle = field(default_factory=CoverStyle)
    boxes: dict[str, BoxDef] = field(default_factory=dict)
    obsidian: dict = field(default_factory=dict)  # [obsidian] 설정 (obsidian.ObsidianSettings)
    warnings: list[str] = field(default_factory=list)


def _apply(obj: Any, data: dict, where: str, warnings: list[str], rename: dict[str, str] | None = None,
           convert: dict[str, Callable[[Any], Any]] | None = None) -> Any:
    """data 의 값을 dataclass obj 의 같은 이름 필드에 넣는다. 모르는 키는 경고."""
    rename = rename or {}
    convert = convert or {}
    names = {f.name for f in fields(obj)}
    changes = {}
    for key, value in data.items():
        name = rename.get(key, key)
        if name not in names:
            warnings.append(f"양식 [{where}] 의 '{key}' 는 알 수 없는 항목이라 무시했습니다")
            continue
        changes[name] = convert[name](value) if name in convert else value
    return replace(obj, **changes)


def resolve_template_path(path: str | Path | None) -> Path:
    """양식 경로. 내장 양식 이름(기본, 수학교재, 문제집)도 받는다. 예전 이름 수능파이널 = 문제집."""
    if path is None:
        return BUILTIN_TEMPLATE
    p = Path(path)
    if p.exists():
        return p
    name = _BUILTIN_ALIASES.get(str(path), str(path))
    builtin = TEMPLATE_DIR / f"{Path(name).stem}.toml"
    return builtin if builtin.exists() else p


def builtin_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATE_DIR.glob("*.toml"))


def load_template(path: str | Path | None = None) -> Template:
    """TOML 양식 파일을 읽는다. path 가 없으면 내장 수학 교재 양식."""
    if _toml is None:
        raise RuntimeError("양식 파일을 읽으려면 Python 3.11 이상이 필요합니다 (또는 pip install tomli)")
    path = resolve_template_path(path)
    with open(path, "rb") as fh:
        try:
            data = _toml.load(fh)
        except Exception as exc:  # tomllib.TOMLDecodeError
            raise ValueError(f"양식 파일 형식 오류 ({path.name}): {exc}") from exc
    return template_from_dict(data)


def _header_def(section: Any, where: str, w: list[str]) -> HeaderDef | None:
    if isinstance(section, str):
        section = {"text": section}
    section = dict(section)
    if "text" in section:
        section["left"] = section.pop("text")
    hd = _apply(HeaderDef(), section, where, w)
    return hd if (hd.left or hd.right) else None


def template_from_dict(data: dict) -> Template:
    w: list[str] = []
    t = Template(warnings=w)
    data = dict(data)
    t.title = data.pop("title", "")

    page = dict(data.pop("page", {}))
    t.columns = int(page.pop("columns", 1))
    t.column_gap = float(page.pop("column_gap", 8.0))
    t.column_line = bool(page.pop("column_line", False))
    margin = page.pop("margin", None)
    if margin is not None:
        top, right, bottom, left = (list(margin) * 4)[:4] if len(margin) == 1 else margin
        page.update(margin_top=top, margin_right=right, margin_bottom=bottom, margin_left=left)
    t.page = _apply(t.page, page, "page", w, convert={"paper": lambda v: tuple(v) if isinstance(v, list) else v})

    font = dict(data.pop("font", {}))
    for key in ("ratio", "spacing"):  # 장평·자간: 숫자 하나면 본문 글꼴, 표면 글꼴별
        if key in font and not isinstance(font[key], dict):
            font[key] = {font.get("body", Theme.body_font): font[key]}
    theme = _apply(
        Theme(), font, "font", w,
        rename={"body": "body_font", "heading": "heading_font", "code": "code_font", "size": "font_size",
                "color": "text_color", "ratio": "font_ratio", "spacing": "font_spacing"},
    )
    heading = dict(data.pop("heading", {}))
    levels = {k: heading.pop(k) for k in list(heading) if isinstance(heading[k], dict)}
    theme = _apply(theme, heading, "heading", w, rename={"sizes": "heading_sizes", "color": "heading_color"},
                   convert={"heading_sizes": lambda v: tuple(float(x) for x in v)})
    styles = {}
    for key, spec in levels.items():
        if not str(key).isdigit() or not 1 <= int(key) <= 6:
            w.append(f"양식 [heading.{key}] 는 1~6 이어야 합니다")
            continue
        styles[int(key)] = _apply(HeadingStyle(), spec, f"heading.{key}", w)
    theme = replace(theme, heading_styles=styles)
    theme = _apply(theme, dict(data.pop("equation", {})), "equation", w,
                   rename={"font": "equation_font", "size": "equation_size"},
                   convert={"equation_size": lambda v: float(v) or None})
    theme = _apply(theme, dict(data.pop("table", {})), "table", w,
                   rename={"border_color": "table_border_color", "header_background": "table_header_background",
                           "style": "table_style", "rule_color": "table_rule_color",
                           "row_line_color": "table_row_line_color"})
    lst = dict(data.pop("list", {}))
    if "bullet" in lst:
        b = lst.pop("bullet")
        lst["bullets"] = tuple(b) if isinstance(b, list) else (b,)
    theme = _apply(theme, lst, "list", w, rename={"indent": "list_indent"})
    t.theme = theme

    for key in ("header", "footer"):
        if key in data:
            setattr(t, key, _header_def(data.pop(key), key, w))

    chapter = dict(data.pop("chapter", {}))
    t.chapter_new_page = bool(chapter.pop("new_page", True))
    hide = chapter.pop("hide_header", "none")
    t.chapter_hide_header = {True: "all", False: "none"}.get(hide, hide) if isinstance(hide, bool) else str(hide)
    for k in chapter:
        w.append(f"양식 [chapter] 의 '{k}' 는 알 수 없는 항목이라 무시했습니다")

    t.problem = _apply(t.problem, dict(data.pop("problem", {})), "problem", w,
                       convert={"names": lambda v: tuple(v), "section_titles": lambda v: tuple(v)})
    t.answers = _apply(t.answers, dict(data.pop("answers", {})), "answers", w)
    t.cover = _apply(t.cover, dict(data.pop("cover", {})), "cover", w)
    t.obsidian = dict(data.pop("obsidian", {}))
    if t.obsidian:
        from .obsidian import ObsidianSettings

        ObsidianSettings.from_dict(t.obsidian, w)  # 오타 경고만

    for name, spec in data.pop("box", {}).items():
        spec = dict(spec)
        box_keys = {f.name for f in fields(BoxDef)} - {"style"}
        own = {k: spec.pop(k) for k in list(spec) if k in box_keys}
        style = _apply(BoxStyle(), spec, f'box."{name}"', w)
        if style.kind not in ("bar", "inline", "line", "plain", "titled", "tag"):
            w.append(f'양식 [box."{name}"] kind 는 bar/inline/line/plain/titled/tag 중 하나여야 합니다')
            style = replace(style, kind="bar")
        t.boxes[name] = replace(BoxDef(style=style, label=name), **own)

    for key in data:
        w.append(f"양식의 [{key}] 는 알 수 없는 항목이라 무시했습니다")
    return t


# ---------------------------------------------------------------------------
# 교재 렌더러
# ---------------------------------------------------------------------------


@dataclass
class _AnswerEntry:
    chapter: int
    chapter_title: str
    number: str
    answer: str
    solution: list[str]
    source: str = ""


def _split_problem(lines: list[str]) -> tuple[list[str], str, list[str]]:
    """문제 본문 / 정답 / 해설 줄."""
    stem: list[str] = []
    answer = ""
    solution: list[str] = []
    mode = "stem"
    depth = 0
    for line in lines:
        if depth == 0:
            m = _ANSWER_MARK.match(line)
            if m:
                answer = m.group(2).strip()
                mode = "answer"
                continue
            m = _SOLUTION_MARK.match(line)
            if m:
                mode = "solution"
                if m.group(2).strip():
                    solution.append(m.group(2))
                continue
        s = line.strip()
        if s.startswith(":::"):  # 문제 안의 상자: 그 안의 [풀이] 는 상자 몫
            depth = max(0, depth - 1) if set(s) <= {":"} else depth + 1
        if mode == "stem":
            stem.append(line)
        elif mode == "solution":
            solution.append(line)
        elif line.strip():  # [정답] 다음 줄에 이어 쓴 것
            answer = (answer + " " + line.strip()).strip()
    return stem, answer, solution


class Textbook(MarkdownHandler):
    """확장 Markdown 을 양식에 맞춰 교재로 조판한다."""

    def __init__(self, template: Template | None = None) -> None:
        self.t = template or load_template()
        self.problem_no = 0
        self.box_no: dict[str, int] = {}
        self.chapter = 0
        self.chapter_title = ""
        self.answers: list[_AnswerEntry] = []
        self.base_dir = Path.cwd()
        self._problem_names = {n.lower() for n in self.t.problem.names}
        self._header_right: str | None = None

    # -- 진입점 ------------------------------------------------------------
    def build(self, markdown: str, *, base_dir: str | Path | None = None, title: str = "") -> HwpxDocument:
        t = self.t
        doc = HwpxDocument(t.page, t.theme, title=title or t.title)
        doc.warnings.extend(t.warnings)
        self.book_title = title or t.title
        if t.header:
            self._header_right = t.header.right
            doc.set_header(self._left_text(), **t.header.kwargs(self._right_text(t.header.right)))
        if t.footer:
            doc.set_footer(t.footer.left, **t.footer.kwargs(t.footer.right))
        if t.columns > 1:
            doc.set_columns(t.columns, gap=t.column_gap, line=t.column_line)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        render_markdown(doc, markdown, base_dir=self.base_dir, handler=self)
        if self.answers:
            self.render_answers(doc, restore_columns=False)
        return doc

    def _render(self, doc: HwpxDocument, lines: list[str] | str) -> None:
        text = lines if isinstance(lines, str) else "\n".join(lines)
        render_markdown(doc, text, base_dir=self.base_dir, handler=self)

    def _inline(self, doc: HwpxDocument, text: str, **base: object) -> list[Run]:
        return parse_inline(text, Run("", **base), doc.theme.link_color)

    def _left_text(self) -> str:
        """머리말 왼쪽 글. {title} 은 책 이름(표지 제목 | 부제, 또는 문서 제목)으로 바뀐다."""
        left = self.t.header.left if self.t.header else ""
        return left.replace("{title}", getattr(self, "book_title", "") or "").strip(" |")

    def _right_text(self, right: str | None) -> str | None:
        if right is None:
            return None
        return right.replace("{chapter}", self.chapter_title)

    def _change_header(self, doc: HwpxDocument, right: str | None) -> None:
        if self.t.header is None:
            return
        doc.change_header(self._left_text(), **self.t.header.kwargs(self._right_text(right)))

    def _restore_columns(self, doc: HwpxDocument) -> None:
        if doc.at_top_level and doc._columns[0] != max(self.t.columns, 1):
            doc.set_columns(self.t.columns, gap=self.t.column_gap, line=self.t.column_line)

    # -- 처리기 ------------------------------------------------------------
    def heading(self, doc: HwpxDocument, level: int, raw: str, inline) -> bool:
        if not doc.at_top_level:
            return False
        if level == 2:
            self._problem_section(doc, raw)
        if level <= 2:
            self._restore_columns(doc)
        if level == 1:
            self._in_problem_section = False
            self._fresh_chapter = True
            number, title, _ = split_heading(raw, True)
            if self.t.chapter_new_page and doc._paragraphs:
                doc.add_page_break()
            hide = self.t.chapter_hide_header
            if hide == "all" or (hide == "numbered" and number):
                doc.hide_on_this_page()
            self.chapter += 1
            self.chapter_title = re.sub(r"[*_`$]", "", title)
            if self.t.problem.reset == "chapter":
                self.problem_no = 0
                self.box_no.clear()
            if self.t.header and self.t.header.right and "{chapter}" in self.t.header.right:
                self._change_header(doc, self.t.header.right)
        return False

    def _problem_section(self, doc: HwpxDocument, raw: str) -> None:
        """'## 확인 문제' 같은 문제 구역의 시작·끝: 새 쪽, 머리말 바꾸기."""
        p = self.t.problem
        _, title, _ = split_heading(raw, False)
        title = re.sub(r"[*_`$]", "", title).strip()
        is_problem = any(title.startswith(name) for name in p.section_titles)
        fresh = getattr(self, "_fresh_chapter", False)
        self._fresh_chapter = False
        was = getattr(self, "_in_problem_section", False)
        if is_problem == was:
            return
        self._in_problem_section = is_problem
        if p.new_page and doc._paragraphs and not fresh:
            doc.add_page_break()
        if p.section_header and self.t.header and self.t.header.right is not None:
            if is_problem:
                section = title.partition(" | ")[0].strip()
                self._change_header(doc, p.section_header.replace("{section}", section))
            else:
                self._change_header(doc, self._header_right)

    def directive(self, doc: HwpxDocument, name: str, arg: str) -> bool:
        key = name.lower()
        if key in _ANSWER_DIRECTIVES:
            self.render_answers(doc)
            return True
        if key in _HEADER_DIRECTIVES:
            self._change_header(doc, arg.strip())
            return True
        return False

    def container(self, doc: HwpxDocument, kind: str, title: str, lines: list[str], base_dir: Path, inline) -> bool:
        if kind.lower() in self._problem_names:
            self.render_problem(doc, title, lines, inline)
            return True
        if kind.lower() in _COVER_NAMES:
            self.render_cover(doc, title, lines)
            return True
        if kind in self.t.boxes:
            self.render_box(doc, kind, title, lines, inline)
            return True
        return False

    # -- 표지 ------------------------------------------------------------
    def render_cover(self, doc: HwpxDocument, title: str, lines: list[str]) -> None:
        c = self.t.cover
        info: dict[str, list[str]] = {"top": [], "title": [title] if title else [], "subtitle": [], "desc": [],
                                      "author": []}
        key = "desc"
        for line in lines:
            m = _COVER_KEY.match(line)
            if m:
                key = _COVER_KEYS.get(m.group(1), m.group(1).lower())
                if m.group(2).strip():
                    info[key].append(m.group(2).strip())
            elif line.strip() and line.strip() not in ("---",):
                info[key if key == "desc" else "desc"].append(line.strip())
        if not doc._paragraphs:
            doc.hide_first_page = True
        if info["title"] and self.t.header and "{title}" in self.t.header.left:
            # 머리말 왼쪽 '{title}' = 표지 제목 | 부제(작은 글씨 부분 빼고)
            name = re.sub(r"[*_`$]", "", info["title"][0])
            if info["subtitle"]:
                name += " | " + re.sub(r"[*_`$]", "", info["subtitle"][0].partition(" | ")[0])
            self.book_title = name
            self._change_header(doc, self._header_right)
        if c.band_color:
            doc.add_page_band(c.band_color, c.band_height)
        doc.add_spacer(c.top_space)
        head = self.t.theme.heading_font
        for text in info["top"]:
            doc.add_paragraph(self._inline(doc, text), size=c.top_size, color=c.top_color, font=head, align="left",
                              space_after=6)
        for text in info["title"]:
            doc.add_paragraph(self._inline(doc, text), size=c.title_size, bold=True, color=c.title_color, font=head,
                              align="left", line_spacing=120, space_after=8)
        for text in info["subtitle"]:
            main, _, sub = text.partition(" | ")
            runs = self._inline(doc, main)
            if sub:
                runs += [Run("    ")] + [replace(r, size=c.subtitle_sub_size) for r in self._inline(doc, sub)]
            doc.add_paragraph(runs, size=c.subtitle_size, bold=True, color=c.subtitle_color, font=head, align="left",
                              line_spacing=130, space_after=10)
        if info["desc"]:
            doc.add_horizontal_rule(color=c.rule_color, width="0.12 mm", space_after=6)
            for text in info["desc"]:
                doc.add_paragraph(self._inline(doc, text), size=c.desc_size, color=c.desc_color, font=head,
                                  align="left", line_spacing=140, space_after=0)
        if info["author"] and c.author_y is not None:
            # 종이 기준 고정 위치: 설명이 길어도 저자가 다음 쪽으로 밀려나지 않는다
            x = doc.page.margin_left
            for i, text in enumerate(info["author"]):
                doc.add_paper_text(self._inline(doc, text), x=x, y=c.author_y + i * c.author_size * 0.6,
                                   size=c.author_size, color=c.author_color, font=head)
        elif info["author"]:
            doc.add_spacer(c.author_space)
            for text in info["author"]:
                doc.add_paragraph(self._inline(doc, text), size=c.author_size, font=head, align="left")
        doc.add_page_break()

    # -- 문제 ------------------------------------------------------------
    def _number_run(self, text: str, color: str | None = None) -> Run:
        p = self.t.problem
        return Run(text, bold=p.number_bold, color=color or p.number_color, size=p.number_size,
                   font=p.number_font or self.t.theme.heading_font)

    def render_problem(self, doc: HwpxDocument, title: str, lines: list[str], inline) -> None:
        p = self.t.problem
        self.problem_no += 1
        number = p.number_format.format(n=self.problem_no, chapter=self.chapter)
        stem, answer, solution = _split_problem(lines)
        if p.columns > 1 and doc.at_top_level and doc._columns[0] != p.columns:
            doc.set_columns(p.columns, gap=self.t.column_gap, line=p.column_line)
        with doc.style_scope(font=p.font, size=p.size, line_spacing=p.line_spacing), \
                doc.display_scope(align=p.display_align, background=None, indent=p.display_indent), \
                doc.keep_together():  # 문제 하나는 단·쪽 경계에서 나뉘지 않게
            if p.layout == "header":
                source = [Run(r.text, size=p.source_size, color=p.source_color, equation=r.equation)
                          for r in inline(title)] if title else [Run("")]
                doc.add_split_line([self._number_run(number)], source, ratio=(1, 3), space_after=2)
                self._render(doc, stem)
            else:
                hang = units.mm(p.indent)
                suffix = None
                if title:
                    suffix = [Run(" ")] + [replace(r, bold=r.bold or p.title_bold) for r in inline(title)]
                with doc.indented(hang):
                    doc.set_paragraph_prefix([self._number_run(number), Run(" ")], hang=hang, suffix=suffix)
                    self._render(doc, stem)
                    doc.flush_prefix()
        if p.space_after > 0:
            doc.add_spacer(p.space_after)
        if answer or any(s.strip() for s in solution):
            source = title if p.layout == "header" else ""
            self.answers.append(_AnswerEntry(self.chapter, self.chapter_title, number, answer, solution, source))

    # -- 상자 ------------------------------------------------------------
    def render_box(self, doc: HwpxDocument, kind: str, title: str, lines: list[str], inline) -> None:
        bd = self.t.boxes[kind]
        label = bd.label or kind
        if bd.numbered:
            self.box_no[kind] = self.box_no.get(kind, 0) + 1
            label = bd.label_format.format(label=label, n=self.box_no[kind], chapter=self.chapter)
        stem, solution = [], []
        target = stem
        for line in lines:
            m = _SOLUTION_MARK.match(line)
            if m and target is stem:
                target = solution
                if m.group(2).strip():
                    solution.append(m.group(2))
                continue
            target.append(line)
        with doc.box(label=label, title=inline(title) if title else None, style=bd.style):
            self._render(doc, stem)
            if target is solution:
                color = bd.solution_color or bd.style.label_color or bd.style.border_color
                doc.add_paragraph([Run(bd.solution_label, bold=True, color=color)], space_before=4,
                                  keep_with_next=True)
                self._render(doc, solution)

    # -- 정답과 해설 -------------------------------------------------------
    def render_answers(self, doc: HwpxDocument, *, restore_columns: bool = True) -> None:
        entries, self.answers = self.answers, []
        if not entries:
            return
        a, p = self.t.answers, self.t.problem
        if a.new_page:
            doc.add_page_break()
        doc.set_columns(1)
        saved_right = self._header_right
        if self.t.header and self.t.header.right is not None:
            self._change_header(doc, a.title)
        doc.add_heading(a.title, level=1)

        groups: list[list[_AnswerEntry]] = []
        for e in entries:
            if not groups or groups[-1][0].chapter != e.chapter:
                groups.append([])
            groups[-1].append(e)
        show = a.show_chapters if a.show_chapters is not None else p.reset == "chapter"
        show_chapters = bool(show) and any(g[0].chapter_title for g in groups)

        def answer_runs(e: _AnswerEntry) -> list[Run]:
            return self._inline(doc, e.answer) if e.answer else [Run("-")]

        if a.quick_table:
            if a.quick_style == "grid" and not show_chapters:
                doc.add_answer_grid([(e.number, answer_runs(e)) for e in entries], columns=a.quick_columns,
                                    line_color=a.rule_color)
            else:
                for group in groups:
                    if show_chapters and group[0].chapter_title:
                        doc.add_paragraph(group[0].chapter_title, bold=True, keep_with_next=True, space_after=2)
                    if a.quick_style == "grid":
                        doc.add_answer_grid([(e.number, answer_runs(e)) for e in group], columns=a.quick_columns,
                                            line_color=a.rule_color)
                        continue
                    cells = [[self._number_run(e.number), Run("  ")] + answer_runs(e) for e in group]
                    cols = max(1, a.quick_columns)
                    rows = [cells[i : i + cols] for i in range(0, len(cells), cols)]
                    rows[-1] += [""] * (cols - len(rows[-1]))
                    doc.add_table(rows, header=False, align=["center"] * cols, col_widths=[1] * cols)

        if any(e.solution for e in entries) or a.entry_layout == "line":
            if a.columns > 1:
                doc.set_columns(a.columns, gap=self.t.column_gap, line=a.column_line)
            with doc.style_scope(font=a.font or p.font, size=a.size, line_spacing=a.line_spacing), \
                    doc.display_scope(align=p.display_align or "left", background=None, indent=p.display_indent):
                for group in groups:
                    if show_chapters and group[0].chapter_title:
                        doc.add_heading(group[0].chapter_title, level=3)
                    for e in group:
                        self._render_answer_entry(doc, e, answer_runs(e))
        self._header_right = saved_right
        if restore_columns:  # 본문이 이어지면 원래 단 설정·머리말로
            doc.set_columns(self.t.columns, gap=self.t.column_gap, line=self.t.column_line)

    def _render_answer_entry(self, doc: HwpxDocument, e: _AnswerEntry, answer: list[Run]) -> None:
        a, p = self.t.answers, self.t.problem
        if a.entry_layout == "line":
            left = [self._number_run(e.number)]
            if e.source:
                left += [Run("  "), Run(e.source, size=p.source_size, color="#333333")]
            right = [Run(a.answer_label + " ", bold=True)] + [replace(r, bold=True) for r in answer]
            with doc.keep_together():
                doc.add_split_line(left, right, rule=a.rule_color, ratio=(3, 1), space_after=4)
                if e.solution:
                    self._render(doc, e.solution)
            doc.add_spacer(1.5)
            return
        hang = units.mm(p.indent)
        with doc.indented(hang):
            doc.set_paragraph_prefix([self._number_run(e.number), Run(" ")], hang=hang)
            if e.answer:
                doc.add_paragraph([Run(a.answer_label + " ", bold=True)] + answer)
            self._render(doc, e.solution)
            doc.flush_prefix()
        doc.add_spacer(2)


def render_inline(doc: HwpxDocument, text: str) -> list[Run]:
    return parse_inline(text, Run(""), doc.theme.link_color)


def build_textbook(
    markdown: str,
    output: str | Path | None = None,
    *,
    template: Template | str | Path | None = None,
    base_dir: str | Path | None = None,
    title: str = "",
) -> HwpxDocument:
    """확장 Markdown 으로 교재를 만들고, output 이 있으면 저장한다."""
    tpl = template if isinstance(template, Template) else load_template(template)
    doc = Textbook(tpl).build(markdown, base_dir=base_dir, title=title)
    if output is not None:
        doc.save(output)
    return doc


def build_from_obsidian(
    note: str | Path,
    output: str | Path | None = None,
    *,
    vault: str | Path | None = None,
    template: Template | str | Path | None = None,
    title: str = "",
) -> HwpxDocument:
    """Obsidian 책 노트(또는 문제 노트 하나)로 교재를 만든다.

    양식은 template 인자 → 책 노트 속성 'template' → 내장 '기본' 순서로 정한다.
    """
    from .obsidian import ObsidianSettings, expand_note, find_vault_root, parse_frontmatter

    note = Path(note).resolve()
    root = Path(vault).resolve() if vault else (find_vault_root(note) or note.parent)
    meta, _ = parse_frontmatter(note.read_text(encoding="utf-8-sig"))
    if not isinstance(template, Template):
        name = template or meta.get("template")
        if name and not isinstance(name, Path):
            for base in (note.parent, root):  # 볼트 안 양식 파일
                cand = base / str(name)
                if cand.is_file():
                    name = cand
                    break
        template = load_template(name)
    settings = ObsidianSettings.from_dict(template.obsidian)
    text, meta, warnings = expand_note(note, vault=root, box_names=set(template.boxes), settings=settings)
    doc = Textbook(template).build(text, base_dir=note.parent, title=title or str(meta.get("title") or note.stem))
    doc.warnings[:0] = warnings
    if output is not None:
        doc.save(output)
    return doc


def write_default_template(path: str | Path, base: str | None = None) -> Path:
    """내장 양식 파일을 복사해 고쳐 쓸 수 있게 한다. base: 내장 양식 이름 (기본: 수학교재)."""
    path = Path(path)
    if path.suffix.lower() != ".toml":
        path = path.with_suffix(".toml")
    source = resolve_template_path(base) if base else BUILTIN_TEMPLATE
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover
    print(load_template(sys.argv[1] if len(sys.argv) > 1 else None))
