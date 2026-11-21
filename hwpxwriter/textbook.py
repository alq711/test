"""수학 교재 만들기: 양식(TOML) + 확장 Markdown → HWPX.

Markdown 확장 문법 (자세한 설명은 README)::

    # 1. 다항식                     ← 대단원: 새 쪽에서 시작, 문제 번호 다시 1부터
    ::: 정의 다항식의 덧셈            ← 양식의 [box."정의"] 모양 상자
    내용 $A+B$
    :::
    ::: 예제
    문제 ...
    [풀이]
    풀이 ...                         ← 예제 상자 안에 바로 보임
    :::
    \\columns{2}                     ← 여기부터 2단
    ::: 문제 [3점]
    문제 내용
    ① $1$ ② $2$ ③ $3$ ④ $4$ ⑤ $5$
    [정답] ②
    [해설]
    해설 내용                        ← 책 뒤 '정답과 해설'로 옮겨짐
    :::
    \\정답                           ← 지금까지 모인 정답과 해설을 여기에 (없으면 문서 끝)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Callable

from . import units
from .document import BoxStyle, HwpxDocument, PageSetup, Run, Theme
from .markdown import MarkdownHandler, render_markdown

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _toml = None  # type: ignore[assignment]

BUILTIN_TEMPLATE = Path(__file__).with_name("templates") / "수학교재.toml"

_PROBLEM_NAMES = {"문제", "problem", "연습문제", "연습", "exercise"}
_ANSWER_DIRECTIVES = {"정답", "해설", "정답과해설", "answers", "solutions"}
_ANSWER_MARK = re.compile(r"^\s*\[(정답|답|answer)\]\s*(.*)$", re.I)
_SOLUTION_MARK = re.compile(r"^\s*\[(해설|풀이|solution)\]\s*(.*)$", re.I)


# ---------------------------------------------------------------------------
# 양식
# ---------------------------------------------------------------------------


@dataclass
class ProblemStyle:
    number_format: str = "{n:02d}"  # {n}=번호, {chapter}=대단원 번호
    number_color: str = "#2E74B5"
    number_size: float = 12.0
    number_font: str | None = None  # None = 제목 글꼴
    number_bold: bool = True
    indent: float = 9.0  # mm: 번호 뒤 본문이 시작하는 위치
    reset: str = "chapter"  # chapter: 대단원마다 1부터 / never: 계속 이어서
    space_after: float = 6.0  # mm: 문제 뒤 빈 공간(풀이 공간)
    title_bold: bool = True  # ::: 문제 [3점] 의 [3점] 을 굵게
    names: tuple[str, ...] = tuple(sorted(_PROBLEM_NAMES))


@dataclass
class AnswerStyle:
    title: str = "정답과 해설"
    new_page: bool = True
    columns: int = 2
    column_line: bool = True
    quick_table: bool = True  # 빠른 정답표
    quick_columns: int = 5
    answer_label: str = "정답"
    show_chapters: bool = True  # 대단원 이름으로 묶기


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
    header: tuple[str, str] | None = None
    footer: tuple[str, str] | None = ("- {page} -", "center")
    columns: int = 1
    column_gap: float = 8.0
    column_line: bool = False
    chapter_new_page: bool = True
    problem: ProblemStyle = field(default_factory=ProblemStyle)
    answers: AnswerStyle = field(default_factory=AnswerStyle)
    boxes: dict[str, BoxDef] = field(default_factory=dict)
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


def load_template(path: str | Path | None = None) -> Template:
    """TOML 양식 파일을 읽는다. path 가 없으면 내장 수학 교재 양식."""
    if _toml is None:
        raise RuntimeError("양식 파일을 읽으려면 Python 3.11 이상이 필요합니다 (또는 pip install tomli)")
    path = Path(path) if path else BUILTIN_TEMPLATE
    with open(path, "rb") as fh:
        try:
            data = _toml.load(fh)
        except Exception as exc:  # tomllib.TOMLDecodeError
            raise ValueError(f"양식 파일 형식 오류 ({path.name}): {exc}") from exc
    return template_from_dict(data)


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
    theme_changes = _apply(
        Theme(), font, "font", w,
        rename={"body": "body_font", "heading": "heading_font", "code": "code_font", "size": "font_size",
                "color": "text_color"},
    )
    heading = dict(data.pop("heading", {}))
    theme_changes = _apply(theme_changes, heading, "heading", w,
                           rename={"sizes": "heading_sizes", "color": "heading_color"},
                           convert={"heading_sizes": lambda v: tuple(float(x) for x in v)})
    eq = dict(data.pop("equation", {}))
    theme_changes = _apply(theme_changes, eq, "equation", w,
                           rename={"font": "equation_font", "size": "equation_size"},
                           convert={"equation_size": lambda v: float(v) or None})
    table = dict(data.pop("table", {}))
    theme_changes = _apply(theme_changes, table, "table", w,
                           rename={"border_color": "table_border_color", "header_background": "table_header_background"})
    t.theme = theme_changes

    for key in ("header", "footer"):
        section = data.pop(key, None)
        if section is None:
            continue
        if isinstance(section, str):
            section = {"text": section}
        text = section.get("text", "")
        setattr(t, key, (text, section.get("align", "center")) if text else None)

    chapter = dict(data.pop("chapter", {}))
    t.chapter_new_page = bool(chapter.pop("new_page", True))
    for k in chapter:
        w.append(f"양식 [chapter] 의 '{k}' 는 알 수 없는 항목이라 무시했습니다")

    t.problem = _apply(t.problem, dict(data.pop("problem", {})), "problem", w,
                       convert={"names": lambda v: tuple(v)})
    t.answers = _apply(t.answers, dict(data.pop("answers", {})), "answers", w)

    boxes = data.pop("box", {})
    for name, spec in boxes.items():
        spec = dict(spec)
        box_keys = {f.name for f in fields(BoxDef)} - {"style"}
        own = {k: spec.pop(k) for k in list(spec) if k in box_keys}
        style = _apply(BoxStyle(), spec, f'box."{name}"', w)
        if style.kind not in ("bar", "inline", "line", "plain"):
            w.append(f'양식 [box."{name}"] kind 는 bar/inline/line/plain 중 하나여야 합니다')
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
        self._seen_content = False
        self._problem_names = {n.lower() for n in self.t.problem.names}

    # -- 진입점 ------------------------------------------------------------
    def build(self, markdown: str, *, base_dir: str | Path | None = None, title: str = "") -> HwpxDocument:
        t = self.t
        doc = HwpxDocument(t.page, t.theme, title=title or t.title)
        doc.warnings.extend(t.warnings)
        if t.header:
            doc.set_header(t.header[0], align=t.header[1])
        if t.footer:
            doc.set_footer(t.footer[0], align=t.footer[1])
        if t.columns > 1:
            doc.set_columns(t.columns, gap=t.column_gap, line=t.column_line)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        render_markdown(doc, markdown, base_dir=self.base_dir, handler=self)
        if self.answers:
            self.render_answers(doc, restore_columns=False)
        return doc

    # -- 처리기 ------------------------------------------------------------
    def heading(self, doc: HwpxDocument, level: int, raw: str, inline) -> bool:
        if level == 1 and doc.at_top_level:
            if self.t.chapter_new_page and doc._paragraphs:
                doc.add_page_break()
            self.chapter += 1
            self.chapter_title = re.sub(r"[*_`$]", "", raw)
            if self.t.problem.reset == "chapter":
                self.problem_no = 0
                self.box_no.clear()
        return False

    def directive(self, doc: HwpxDocument, name: str, arg: str) -> bool:
        if name.lower() in _ANSWER_DIRECTIVES:
            self.render_answers(doc)
            return True
        return False

    def container(self, doc: HwpxDocument, kind: str, title: str, lines: list[str], base_dir: Path, inline) -> bool:
        if kind.lower() in self._problem_names:
            self.render_problem(doc, title, lines, inline)
            return True
        if kind in self.t.boxes:
            self.render_box(doc, kind, title, lines, inline)
            return True
        return False

    # -- 문제 ------------------------------------------------------------
    def _number_run(self, text: str) -> Run:
        p = self.t.problem
        return Run(text, bold=p.number_bold, color=p.number_color, size=p.number_size,
                   font=p.number_font or self.t.theme.heading_font)

    def render_problem(self, doc: HwpxDocument, title: str, lines: list[str], inline) -> None:
        p = self.t.problem
        self.problem_no += 1
        number = p.number_format.format(n=self.problem_no, chapter=self.chapter)
        stem, answer, solution = _split_problem(lines)
        hang = units.mm(p.indent)
        suffix = None
        if title:
            suffix = [Run(" ")] + [replace(r, bold=r.bold or p.title_bold) for r in inline(title)]
        with doc.indented(hang):
            doc.set_paragraph_prefix([self._number_run(number), Run(" ")], hang=hang, suffix=suffix)
            render_markdown(doc, "\n".join(stem), base_dir=self.base_dir, handler=self)
            doc.flush_prefix()
        if p.space_after > 0:
            doc.add_spacer(p.space_after)
        if answer or any(s.strip() for s in solution):
            self.answers.append(_AnswerEntry(self.chapter, self.chapter_title, number, answer, solution))

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
            render_markdown(doc, "\n".join(stem), base_dir=self.base_dir, handler=self)
            if target is solution:
                color = bd.solution_color or bd.style.label_color or bd.style.border_color
                doc.add_paragraph([Run(bd.solution_label, bold=True, color=color)], space_before=4,
                                  keep_with_next=True)
                render_markdown(doc, "\n".join(solution), base_dir=self.base_dir, handler=self)

    # -- 정답과 해설 -------------------------------------------------------
    def render_answers(self, doc: HwpxDocument, *, restore_columns: bool = True) -> None:
        entries, self.answers = self.answers, []
        if not entries:
            return
        a = self.t.answers
        inline = lambda s: render_inline(doc, s)  # noqa: E731
        if a.new_page:
            doc.add_page_break()
        doc.set_columns(1)
        doc.add_heading(a.title, level=1)

        groups: list[list[_AnswerEntry]] = []
        for e in entries:
            if not groups or groups[-1][0].chapter != e.chapter:
                groups.append([])
            groups[-1].append(e)
        show_chapters = a.show_chapters and (len(groups) > 1 or groups[0][0].chapter_title)

        if a.quick_table:
            for group in groups:
                if show_chapters and group[0].chapter_title:
                    doc.add_paragraph(group[0].chapter_title, bold=True, keep_with_next=True, space_after=2)
                cells = [[self._number_run(e.number), Run("  ")] + (inline(e.answer) if e.answer else [Run("-")])
                         for e in group]
                cols = max(1, a.quick_columns)
                rows = [cells[i : i + cols] for i in range(0, len(cells), cols)]
                rows[-1] += [""] * (cols - len(rows[-1]))
                doc.add_table(rows, header=False, align=["center"] * cols, col_widths=[1] * cols)

        if any(e.solution for e in entries):
            if a.columns > 1:
                doc.set_columns(a.columns, gap=self.t.column_gap, line=a.column_line)
            hang = units.mm(self.t.problem.indent)
            for group in groups:
                if show_chapters and group[0].chapter_title:
                    doc.add_heading(group[0].chapter_title, level=3)
                for e in group:
                    with doc.indented(hang):
                        doc.set_paragraph_prefix([self._number_run(e.number), Run(" ")], hang=hang)
                        if e.answer:
                            doc.add_paragraph([Run(a.answer_label + " ", bold=True)] + inline(e.answer))
                        render_markdown(doc, "\n".join(e.solution), base_dir=self.base_dir, handler=self)
                        doc.flush_prefix()
                    doc.add_spacer(2)
        if restore_columns:  # 본문이 이어지면 원래 단 설정으로
            doc.set_columns(self.t.columns, gap=self.t.column_gap, line=self.t.column_line)


def render_inline(doc: HwpxDocument, text: str) -> list[Run]:
    from .markdown import parse_inline

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


def write_default_template(path: str | Path) -> Path:
    """내장 양식 파일을 복사해 고쳐 쓸 수 있게 한다."""
    path = Path(path)
    if path.suffix.lower() != ".toml":
        path = path.with_suffix(".toml")
    path.write_text(BUILTIN_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover
    print(load_template(sys.argv[1] if len(sys.argv) > 1 else None))
