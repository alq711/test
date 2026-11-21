"""수식 변환과 교재(양식·문제·정답과 해설) 테스트."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hwpxwriter import HwpxDocument, Run
from hwpxwriter.cli import main as cli_main
from hwpxwriter.latex import latex_to_hwp
from hwpxwriter.markdown import parse_inline
from hwpxwriter.textbook import Textbook, build_textbook, load_template, template_from_dict

from test_hwpx import HP, validate

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "수학교재_예시.md"


# ---------------------------------------------------------------------------
# LaTeX → 한글 수식
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "latex, script",
    [
        (r"x^2+1", "x ^{2} + 1"),
        (r"x^23", "x ^{2} 3"),
        (r"a_{n+1}", "a _{n + 1}"),
        (r"\frac{a+b}{2}", "{a + b} over {2}"),
        (r"\dfrac{1}{x}", "{1} over {x}"),
        (r"\sqrt{x}", "sqrt {x}"),
        (r"\sqrt[3]{8}", "root {3} of {8}"),
        (r"\sum_{k=1}^{n} k", "sum _{k = 1} ^{n} k"),
        (r"\int_0^1 f(x)\,dx", "int _{0} ^{1} f ( x ) ` d x"),
        (r"\lim_{x \to 0} x", "lim _{x -> 0} x"),
        (r"\alpha\beta\Gamma", "alpha beta GAMMA"),
        (r"a \le b \ne c \geq d", "a leq b neq c geq d"),
        (r"\pm \times \div \cdot", "+- times div cdot"),
        (r"\left( x \right)", "left ( x right )"),
        (r"\{1, 2\}", "LBRACE 1 , 2 RBRACE"),
        (r"\overline{AB}", "overline {A B}"),
        (r"\vec{a}", "vec {a}"),
        (r"\text{넓이}", '"넓이"'),
        (r"\mathrm{cm}^2", "{rm cm} ^{2}"),
        (r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}", "pmatrix{1 & 2 # 3 & 4}"),
        (r"\begin{cases} x & x>0 \\ 0 & x \le 0 \end{cases}", "cases{x & x > 0 # 0 & x leq 0}"),
        (r"\binom{n}{r}", "left ( {n} atop {r} right )"),
        (r"\forall x \in A", "FORALL x in A"),
        (r"\infty", "inf"),
        (r"30^\circ", "30 ^{circ}"),
        (r"\perp", "BOT"),
        (r"\displaystyle \sum x", "sum x"),
    ],
)
def test_latex_to_hwp(latex, script):
    eq = latex_to_hwp(latex)
    assert eq.script == script
    assert not eq.warnings


def test_latex_unknown_command_warns_but_converts():
    eq = latex_to_hwp(r"\foo x")
    assert eq.script == '"foo" x'
    assert eq.warnings


def test_latex_unbalanced_braces_do_not_crash():
    for src in [r"\frac{1}{", r"x^", r"\left( x", r"}", r"\begin{pmatrix} 1 & 2"]:
        latex_to_hwp(src)  # 예외 없이


def test_equation_size_grows_with_content():
    small = latex_to_hwp("x").size(1000)
    wide = latex_to_hwp("x+y+z+w").size(1000)
    tall = latex_to_hwp(r"\frac{a}{b}").size(1000)
    assert wide[0] > small[0]
    assert tall[1] > small[1]
    assert 0 < tall[2] < small[2] <= 100  # 분수는 기준선이 더 아래


def test_inline_math_parsing():
    runs = parse_inline(r"가격은 \$5 이고 $x^2$ 와 $$y$$, 그리고 1$ 2$ 는 수식 아님")
    eqs = [r.text for r in runs if r.equation]
    assert eqs == ["x^2", "y"]
    assert "$5" in "".join(r.text for r in runs if not r.equation)


def test_math_inside_emphasis_is_not_broken():
    runs = parse_inline(r"**굵게 $a*b$ 끝**")
    assert any(r.equation and r.text == "a*b" and r.bold for r in runs)


# ---------------------------------------------------------------------------
# 문서 엔진: 수식·상자·다단·보기
# ---------------------------------------------------------------------------


def test_equation_xml_and_box_columns_choices_are_valid():
    doc = HwpxDocument()
    doc.add_paragraph(["넓이 ", Run(r"\pi r^2", equation=True)])
    doc.add_equation(r"\int_0^1 x\,dx = \frac{1}{2}")
    with doc.box(label="정의 1", title="원"):
        doc.add_paragraph("상자 안")
        doc.add_table([["a", "b"], ["1", "2"]])
        with doc.box(label="안쪽"):
            doc.add_paragraph("중첩 상자")
    doc.set_columns(2, line=True)
    doc.add_choices(["$1$", "$2$", "$3$", "$4$", "$5$"])
    doc.add_choices(["아주 긴 보기 문장입니다 " * 3] * 5)
    doc.add_column_break()
    doc.add_paragraph("둘째 단")
    trees = validate(doc.to_bytes())
    sec = trees["Contents/section0.xml"]
    eqs = list(sec.iter(HP + "equation"))
    assert len(eqs) == 2
    for eq in eqs:
        assert eq.find(HP + "script").text
        assert int(eq.find(HP + "sz").get("width")) > 0
    col_counts = [c.get("colCount") for c in sec.iter(HP + "colPr")]
    assert col_counts == ["1", "2"]
    assert sec.find(f".//{HP}colLine") is not None
    assert any(p.get("columnBreak") == "1" for p in sec.iter(HP + "p"))
    tables = list(sec.iter(HP + "tbl"))
    # 상자 2 + 안쪽 표 1 + 보기 2
    assert len(tables) == 5
    choice_tables = [t for t in tables if t.get("colCnt") in ("5", "1") and t.get("rowCnt") in ("1", "5")]
    assert {t.get("colCnt") for t in choice_tables} >= {"5", "1"}
    # 본문 바로 아래 상자는 쪽 경계에서 나뉠 수 있게(글자처럼 취급 안 함)
    top_box = tables[0]
    assert top_box.find(HP + "pos").get("treatAsChar") == "0"


def test_box_inside_box_and_table_widths_fit():
    doc = HwpxDocument()
    outer_w = doc.available_width
    with doc.box(label="밖"):
        inner_w = doc.available_width
        assert inner_w < outer_w
        with doc.indented(1000):
            assert doc.available_width == inner_w - 1000
    assert doc.available_width == outer_w


def test_columns_reduce_available_width():
    doc = HwpxDocument()
    full = doc.available_width
    doc.add_paragraph("x")
    doc.set_columns(2, gap=10)
    assert doc.available_width < full // 2 + 1


# ---------------------------------------------------------------------------
# 교재
# ---------------------------------------------------------------------------


def test_builtin_template_loads_without_warnings():
    t = load_template()
    assert not t.warnings
    assert {"정의", "정리", "예제", "공식", "주의", "참고", "증명"} <= set(t.boxes)
    assert t.answers.title == "정답과 해설"


def test_template_typos_are_reported():
    t = template_from_dict({"page": {"colums": 2}, "problem": {"numbr_color": "#000"}, "foo": {}})
    joined = " ".join(t.warnings)
    assert "colums" in joined and "numbr_color" in joined and "foo" in joined


def test_textbook_example_builds_and_is_valid(tmp_path: Path):
    doc = build_textbook(EXAMPLE.read_text(encoding="utf-8"), tmp_path / "교재.hwpx", base_dir=EXAMPLE.parent)
    assert doc.warnings == []
    trees = validate((tmp_path / "교재.hwpx").read_bytes())
    text = doc.plain_text()
    # 문제 번호: 대단원마다 다시 01 부터
    assert text.count("01 ") >= 2 and "04 " in text
    # 정답과 해설은 끝에, 해설 내용은 본문 문제 자리에 없음
    body, answers = text.split("정답과 해설", 1)
    assert "근과 계수의 관계" not in body
    assert "근과 계수의 관계" in answers
    # 예제의 풀이는 상자 안에 그대로
    assert "풀이" in body and "19" in body
    sec = trees["Contents/section0.xml"]
    assert len(list(sec.iter(HP + "equation"))) > 50


def test_problem_markers_and_numbering():
    md = (
        "::: 문제 [2점]\n1+1은?\n\n① $1$ ② $2$ ③ $3$\n\n[정답] ②\n[해설]\n더하면 2\n:::\n"
        "::: 문제\n답만 있는 문제\n[정답] 7\n:::\n"
        "::: 문제\n정답 없는 문제\n:::\n"
    )
    tb = Textbook(template_from_dict({"problem": {"number_format": "{n}."}, "answers": {"new_page": False}}))
    doc = tb.build(md)
    text = doc.plain_text()
    assert "1. 1+1은? [2점]" in text
    assert "2. 답만 있는 문제" in text and "3. 정답 없는 문제" in text
    after = text.split("정답과 해설", 1)[1]
    assert "1.  ②" in after.replace("\t", "  ") and "더하면 2" in after
    assert "3." not in after  # 정답 없는 문제는 빠짐
    validate(doc.to_bytes())


def test_answers_directive_places_answers_mid_document():
    md = "# 1단원\n::: 문제\nA\n[정답] 1\n:::\n\\정답\n\n# 2단원\n::: 문제\nB\n[정답] 2\n:::\n"
    doc = Textbook(load_template()).build(md)
    text = doc.plain_text()
    assert text.count("정답과 해설") == 2
    assert text.index("2단원") > text.index("정답과 해설")
    validate(doc.to_bytes())


def test_unknown_container_becomes_generic_box():
    doc = Textbook(load_template()).build("::: 메모 제목\n내용\n:::\n")
    sec = validate(doc.to_bytes())["Contents/section0.xml"]
    assert sec.find(f".//{HP}tbl") is not None
    assert "메모" in doc.plain_text() or "내용" in doc.plain_text()


def test_custom_box_from_template():
    t = template_from_dict({"box": {"보충": {"kind": "line", "border_color": "#00FF00", "numbered": True}}})
    doc = Textbook(t).build("::: 보충 더 알아보기\n내용\n:::\n::: 보충\n둘째\n:::\n")
    assert "보충 1" in doc.plain_text() and "보충 2" in doc.plain_text()
    validate(doc.to_bytes())


def test_cli_template_and_init(tmp_path: Path):
    tpl = tmp_path / "내양식.toml"
    assert cli_main(["--init-template", str(tpl)]) == 0
    text = tpl.read_text(encoding="utf-8").replace('number_format = "{n:02d}"', 'number_format = "[{n}]"')
    tpl.write_text(text, encoding="utf-8")
    src = tmp_path / "교재.md"
    src.write_text("::: 문제\n$x$\n[정답] 1\n:::\n", encoding="utf-8")
    assert cli_main([str(src), "--template", str(tpl)]) == 0
    validate((tmp_path / "교재.hwpx").read_bytes())
    assert cli_main([str(src), "-t", str(tmp_path / "없음.toml")]) == 2
