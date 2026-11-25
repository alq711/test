"""'모의고사' 양식 (수능 시험지 모양) 테스트."""

import re
import zipfile

from hwpxwriter.exam import ExamPaper
from hwpxwriter.textbook import build_textbook, load_template, make_renderer


def _section(doc):
    import io

    with zipfile.ZipFile(io.BytesIO(doc.to_bytes())) as z:
        return z.read("Contents/section0.xml").decode(), z.read("Contents/header.xml").decode()


def _exam(n_common=4, big=(), subject=None, n_sub=2):
    lines = ["::: 시험지", "위: 2027학년도 대학수학능력시험 9월 모의평가 문제지", ":::", "\\5지선다형"]
    for i in range(1, n_common + 1):
        lines += ["::: 문제" + (" 크게" if i in big else ""), f"문제 {i} 의 값은? [2점]", "① 1 ② 2 ③ 3 ④ 4 ⑤ 5",
                  "[정답] ①", ":::"]
    if subject:
        lines.append(f"\\선택과목 {subject}")
        for i in range(n_sub):
            lines += ["::: 문제 크게", "선택 문제 [3점]", ":::"]
    return "\n".join(lines)


def test_template_has_exam():
    t = load_template("모의고사")
    assert t.exam is not None
    assert isinstance(make_renderer(t), ExamPaper)
    assert t.page.size_mm() == (297, 420)
    assert not t.warnings


def test_aliases():
    assert load_template("수능").exam is not None


def test_first_page_title_and_fonts():
    doc = build_textbook(_exam(), template="모의고사")
    sec, head = _section(doc)
    assert "2027학년도 대학수학능력시험 9월 모의평가 문제지" in sec
    assert "<hp:rect " in sec and 'ratio="50"' in sec  # 제 2 교시 둥근 상자
    assert "제 2 교시" in sec and "홀수형" in sec
    # 한글 = 신명 중명조, 영문·기호 = 한양신명조
    fonts = dict(re.findall(r'<hh:font id="(\d+)" face="([^"]+)" type="HFT"', head))
    body = [k for k, v in fonts.items() if v == "신명 중명조"][0]
    latin = [k for k, v in fonts.items() if v == "한양신명조"][0]
    assert f'<hh:fontRef hangul="{body}" latin="{latin}"' in head
    assert '<hh:slash type="CENTER"' in head  # 꼬리말 쪽/전체 칸
    assert 'numType="TOTAL_PAGE"' in sec
    assert "5지선다형" in sec
    assert "확인 사항" in sec


def test_slots_paginate():
    # 반 칸 4개 = 첫 쪽, 다섯째 문제는 둘째 쪽 → 쪽 나눔 1번, 머리말(쪽 번호 2) 1개
    doc = build_textbook(_exam(5), template="모의고사")
    sec, _ = _section(doc)
    assert sec.count('pageBreak="1"') == 2  # 둘째 쪽 + 정답과 해설
    assert sec.count("<hp:header ") == 2  # 둘째 쪽 머리말 + 정답 머리말


def test_subject_restarts_numbers():
    doc = build_textbook(_exam(2, subject="미적분"), template="모의고사")
    sec, _ = _section(doc)
    assert "(미적분)" in sec
    assert "3." in sec and "4." in sec  # 공통 2문제 다음 선택과목은 3번부터
    assert "「선택과목(미적분)」" in sec


def test_big_problem_takes_column():
    tb = make_renderer(load_template("모의고사"))
    tb.build(_exam(3, big={1}))
    assert (tb.page, tb.col, tb.unit) == (1, 1, 2)
