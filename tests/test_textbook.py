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
        (r"\text{위치의 변화량} = 1", '"위치의"~"변화량" = 1'),
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


# ---------------------------------------------------------------------------
# '수능 파이널' 모양 (표지, 바뀌는 머리말, 출처 줄, 〈보기〉, 정답 격자)
# ---------------------------------------------------------------------------

SUNEUNG = Path(__file__).resolve().parent.parent / "examples" / "수능파이널_예시.md"


def test_suneung_template_loads_without_warnings():
    t = load_template("문제집")
    assert not t.warnings
    assert t.problem.layout == "header" and t.problem.columns == 2
    assert t.boxes["보기"].style.kind == "titled" and t.boxes["주의"].style.kind == "tag"
    assert 1 in t.theme.heading_styles and t.theme.heading_styles[1].number_color


def test_suneung_example_structure(tmp_path: Path):
    from test_hwpx import HC, HH

    doc = build_textbook(SUNEUNG.read_text(encoding="utf-8"), tmp_path / "s.hwpx", template="문제집",
                         base_dir=SUNEUNG.parent)
    assert doc.warnings == []
    trees = validate((tmp_path / "s.hwpx").read_bytes())
    sec, head = trees["Contents/section0.xml"], trees["Contents/header.xml"]
    # 표지: 첫 쪽 머리말 감춤 + 종이 기준 띠
    vis = sec.find(f".//{HP}visibility")
    assert vis.get("hideFirstHeader") == "1" and vis.get("hideFirstFooter") == "1"
    assert any(t.find(HP + "pos").get("vertRelTo") == "PAPER" for t in sec.iter(HP + "tbl"))
    # 번호 단원 첫 쪽만 머리말 감춤 (09, 10)
    assert len(list(sec.iter(HP + "pageHiding"))) == 2
    # 머리말 오른쪽 글이 단원마다 바뀜
    header_texts = ["".join(t.text or "" for t in h.iter(HP + "t")) for h in sec.iter(HP + "header")]
    assert any("공통 9번" in x for x in header_texts) and any("정답과 해설" in x for x in header_texts)
    # 개념 1단 ↔ 문제 2단
    assert [c.get("colCount") for c in sec.iter(HP + "colPr")] == ["1", "2", "1", "2", "1", "2"]
    # 번호는 책 전체 이어서 01~07, 정답 격자 10칸
    text = doc.plain_text()
    assert "07" in text and text.count("정답과 해설") == 1
    assert any(t.get("colCnt") == "10" for t in sec.iter(HP + "tbl"))
    # 수식 줄 회색 배경(개념), 문제 안 수식은 배경 없음
    fills = {bf.get("id") for bf in head.iter(HH + "borderFill")
             if (wb := bf.find(f".//{HC}winBrush")) is not None and wb.get("faceColor") == "#F2F2F2"}
    para_bg = {pp.get("id") for pp in head.iter(HH + "paraPr") if pp.find(HH + "border").get("borderFillIDRef") in fills}
    eq_paras = [p for p in sec.iter(HP + "p") if p.find(f"{HP}run/{HP}equation") is not None
                and all(r.find(HP + "t") is None or not (r.find(HP + "t").text or "").strip() for r in p.findall(HP + "run"))]
    assert any(p.get("paraPrIDRef") in para_bg for p in eq_paras)
    assert any(p.get("paraPrIDRef") not in para_bg for p in eq_paras)
    # 〈보기〉 상자와 ㄱ. ㄴ. ㄷ.
    sec_text = "".join(t.text or "" for t in sec.iter(HP + "t"))
    assert sec_text.count("〈보 기〉") == 3 and "ㄱ. " in text


def test_split_heading():
    from hwpxwriter.markdown import split_heading

    assert split_heading("09 수직선 위의 운동", True) == ("09", "수직선 위의 운동", None)
    assert split_heading("최근 기출 | 공통 9번", True) == (None, "최근 기출", "공통 9번")
    assert split_heading("Ⅱ. 방정식", True) == ("Ⅱ", "방정식", None)
    assert split_heading("09 그대로", False) == (None, "09 그대로", None)


def test_span_color_and_jamo_items():
    runs = parse_inline('<span style="color:#1F3864">**높음**</span> 보통')
    assert runs[0].text == "높음" and runs[0].bold and runs[0].color == "#1F3864"
    doc = HwpxDocument()
    doc.add_markdown("ㄱ. 첫째 줄\n이어지는 줄\nㄴ. 둘째\n")
    assert doc.plain_text().split("\n") == ["ㄱ. 첫째 줄 이어지는 줄", "ㄴ. 둘째"]


def test_header_split_and_change_mid_document():
    doc = HwpxDocument()
    doc.set_header("책 이름", right="1단원", rule="#999999")
    doc.add_paragraph("a")
    doc.hide_on_this_page()
    doc.change_header("책 이름", right="2단원", rule="#999999")
    doc.add_paragraph("b")
    sec = validate(doc.to_bytes())["Contents/section0.xml"]
    headers = list(sec.iter(HP + "header"))
    assert len(headers) == 2
    assert all(h.find(f".//{HP}tbl") is not None for h in headers)
    p_b = [p for p in sec.findall(HP + "p") if "".join(t.text or "" for t in p.iter(HP + "t")).endswith("b")][0]
    assert p_b.find(f".//{HP}pageHiding") is not None and p_b.find(f".//{HP}header") is not None


def test_cli_init_from_builtin(tmp_path: Path):
    out = tmp_path / "내양식.toml"
    assert cli_main(["--init-template", str(out), "-t", "문제집"]) == 0
    assert 'layout = "header"' in out.read_text(encoding="utf-8")
    assert not load_template(out).warnings


def test_ruled_and_shaded_paragraphs_do_not_bleed():
    """한글은 문단 테두리·배경을 위/아래 간격까지 포함해 그린다.

    그래서 선·배경이 있는 문단은 테두리 오프셋(바깥으로 넘치는 부분)이 없어야 하고,
    바깥 간격은 뒤따르는 빈 문단이 맡아야 한다.
    """
    from test_hwpx import HH

    doc = build_textbook(SUNEUNG.read_text(encoding="utf-8"), template="문제집", base_dir=SUNEUNG.parent)
    trees = validate(doc.to_bytes())
    head, sec = trees["Contents/header.xml"], trees["Contents/section0.xml"]
    plain_bf = {bf.get("id") for bf in head.iter(HH + "borderFill")
                if all(bf.find(HH + side).get("type") == "NONE"
                       for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"))
                and bf.find(f".//{{http://www.hancom.co.kr/hwpml/2011/core}}winBrush") is None}
    plain_bf |= {"1", "2"}
    for pp in head.iter(HH + "paraPr"):
        border = pp.find(HH + "border")
        if border.get("borderFillIDRef") in plain_bf:
            continue
        if border.get("offsetLeft") != "0":  # 인용문 왼쪽 막대만 옆으로 띄움
            continue
        assert border.get("offsetTop") == "0" and border.get("offsetBottom") == "0", pp.get("id")
    # 제목 '09' 문단 다음에는 선 아래 간격용 빈 문단
    paras = sec.findall(HP + "p")
    own = lambda p: "".join(t.text or "" for r in p.findall(HP + "run") for t in r.findall(HP + "t"))  # noqa: E731
    idx = next(i for i, p in enumerate(paras) if own(p).endswith("수직선 위의 운동"))
    assert "".join(t.text or "" for t in paras[idx + 1].iter(HP + "t")) == ""


def test_span_font_family_size_and_style():
    r = parse_inline("<span style=\"font-family: '나눔스퀘어', sans-serif; font-size: 12pt; color:#C00000; "
                     "font-weight:700\">글자</span>")[0]
    assert (r.text, r.font, r.size, r.color, r.bold) == ("글자", "나눔스퀘어", 12.0, "#C00000", True)
    r = parse_inline('<font face="맑은 고딕" size="16px">작게</font>')[0]
    assert (r.font, r.size) == ("맑은 고딕", 12.0)
    runs = parse_inline('<span style="font-family:바탕">겉 <span style="color:#00F">속</span> 끝</span>')
    assert [(x.text, x.font, x.color) for x in runs if x.text.strip()] == [
        ("겉 ", "바탕", None), ("속", "바탕", "#00F"), (" 끝", "바탕", None)]
    r = parse_inline('<span style="font-family: serif">기본</span>')[0]
    assert r.font is None  # 일반 계열 이름은 무시
    doc = HwpxDocument()
    doc.add_markdown('본문 <span style="font-family:나눔스퀘어">강조</span>')
    head = validate(doc.to_bytes())["Contents/header.xml"]
    from test_hwpx import HH
    assert "나눔스퀘어" in {f.get("face") for f in head.iter(HH + "font")}


# ---------------------------------------------------------------------------
# 시중 교재 모양 맞춤: 장평·자간, 문제 묶음, 내어쓰기, 〈보 기〉
# ---------------------------------------------------------------------------


def _header_and_section(data: bytes):
    trees = validate(data)
    return trees["Contents/header.xml"], trees["Contents/section0.xml"]


def test_font_ratio_and_spacing_from_template(tmp_path):
    t = template_from_dict({"font": {"body": "함초롬돋움", "ratio": {"함초롬바탕": 95}, "spacing": -3}})
    assert t.warnings == []
    assert t.theme.font_ratio == {"함초롬바탕": 95}
    assert t.theme.font_spacing == {"함초롬돋움": -3}
    out = tmp_path / "r.hwpx"
    build_textbook("::: 문제\n본문\n:::\n", out, template="문제집")
    head, _ = _header_and_section(out.read_bytes())
    HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
    fonts = [f.get("face") for f in head.find(f".//{HH}fontface").findall(HH + "font")]
    batang = str(fonts.index("신명 중명조"))
    ratios = {cp.find(HH + "fontRef").get("hangul"): cp.find(HH + "ratio").get("hangul") for cp in head.iter(HH + "charPr")}
    assert ratios[batang] == "95"


def test_problem_keep_together_releases_last_paragraph():
    doc = HwpxDocument()
    with doc.keep_together():
        doc.add_paragraph("하나")
        doc.add_paragraph("둘")
    doc.add_paragraph("다음 문제")
    head, sec = _header_and_section(doc.to_bytes())
    HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
    keep = {pp.get("id"): pp.find(HH + "breakSetting").get("keepWithNext") for pp in head.iter(HH + "paraPr")}
    paras = {"".join(t.text or "" for t in p.iter(HP + "t")): p.get("paraPrIDRef") for p in sec.iter(HP + "p")}
    assert keep[paras["하나"]] == "1"
    assert keep[paras["둘"]] == "0"  # 묶음 끝은 다음 문단과 묶지 않아야 한글이 묶음을 지킨다


def test_hanging_indent_uses_hangul_semantics():
    doc = HwpxDocument()
    doc.add_list_item("항목")
    head, sec = _header_and_section(doc.to_bytes())
    HH, HC = "{http://www.hancom.co.kr/hwpml/2011/head}", "{http://www.hancom.co.kr/hwpml/2011/core}"
    pid = next(p.get("paraPrIDRef") for p in sec.iter(HP + "p") if "항목" in "".join(t.text or "" for t in p.iter(HP + "t")))
    pp = next(pp for pp in head.iter(HH + "paraPr") if pp.get("id") == pid)
    case = pp.find(".//" + HH + "margin")
    assert int(case.find(HC + "intent").get("value")) < 0
    assert case.find(HC + "left").get("value") == "0"  # 글머리표는 본문 왼쪽 끝, 둘째 줄부터 들여씀


def test_bogi_label_sits_on_box_border():
    doc = HwpxDocument()
    from hwpxwriter.document import BoxStyle
    with doc.box(label="〈보 기〉", style=BoxStyle(kind="titled")):
        doc.add_paragraph("ㄱ. 내용")
    _, sec = _header_and_section(doc.to_bytes())
    tbl = next(sec.iter(HP + "tbl"))
    assert tbl.get("colCnt") == "3" and tbl.get("rowCnt") == "3"
    spans = [(s.get("colSpan"), s.get("rowSpan")) for s in tbl.iter(HP + "cellSpan")]
    assert ("1", "2") in spans and ("3", "1") in spans


def test_cover_author_fixed_position(tmp_path):
    out = tmp_path / "c.hwpx"
    build_textbook("::: 표지\n제목: 책\n설명:\n" + "긴 설명\n" * 40 + "저자: 이름\n:::\n", out, template="문제집")
    _, sec = _header_and_section(out.read_bytes())
    pos = [t.find(HP + "pos") for t in sec.iter(HP + "tbl")]
    assert any(p.get("vertRelTo") == "PAPER" and int(p.get("vertOffset")) > 0 for p in pos)


def test_workbook_template_old_name_and_title_header(tmp_path):
    assert load_template("수능파이널").header.left == load_template("문제집").header.left == "{title}"
    out = tmp_path / "t.hwpx"
    build_textbook("::: 표지\n제목: 내 문제집\n부제: 미적분 | 4점\n:::\n\n# 01 극한\n\n본문\n", out, template="문제집")
    _, sec = _header_and_section(out.read_bytes())
    texts = ["".join(t.text or "" for t in h.iter(HP + "t")) for h in sec.iter(HP + "header")]
    assert any("내 문제집 | 미적분" in t for t in texts)
    assert not any("{title}" in t for t in texts)


def test_concept_book_template_builds_example(tmp_path):
    t = load_template("개념서")
    assert t.warnings == []
    assert {"정의", "정리", "공식", "예제", "증명", "주의", "보기", "조건"} <= set(t.boxes)
    example = Path(__file__).resolve().parent.parent / "examples" / "개념서_예시.md"
    doc = build_textbook(example.read_text(encoding="utf-8"), tmp_path / "c.hwpx", template="개념서")
    assert doc.warnings == []
    validate((tmp_path / "c.hwpx").read_bytes())
