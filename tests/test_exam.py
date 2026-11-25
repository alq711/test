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
    assert "제 2 교시" in sec and "홀수형" not in sec  # 2028 예시문항엔 홀수형 상자 없음
    # 한글 = 신명 중명조, 영문·기호 = 한양신명조
    fonts = dict(re.findall(r'<hh:font id="(\d+)" face="([^"]+)" type="HFT"', head))
    body = [k for k, v in fonts.items() if v == "신명 중명조"][0]
    latin = [k for k, v in fonts.items() if v == "한양신명조"][0]
    assert f'<hh:fontRef hangul="{body}" latin="{latin}"' in head
    assert '<hh:slash type="CENTER"' in head  # 꼬리말 쪽/전체 칸
    assert 'numType="TOTAL_PAGE"' in sec
    assert "5 지 선 다 형" in sec
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


def test_free_layout_big_problem_takes_column():
    t = load_template("모의고사")
    t.exam["layout"] = "free"
    tb = make_renderer(t)
    tb.build(_exam(3, big={1}))
    assert (tb.page, tb.col, tb.unit) == (1, 1, 2)


OLD_2027 = {"form": "홀수형", "label_1": "5지선다형", "label_2": "단답형", "common_short_from": 16,
            "common_slots": [1, 1, 1, 1, 1, 1, 2, 1, 1, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 2, 2, 2]}


def _where(n_common, subject=None, n_sub=0, exam=None):
    """번호마다 (쪽, 단, 칸) 기록."""
    t = load_template("모의고사")
    t.exam.update(exam or {})
    tb = make_renderer(t)
    seen = []
    orig = tb._push

    def push(doc, slot):
        orig(doc, slot)
        seen.append((tb.subject_name, tb.page, tb.col, tb.unit_before))

    tb._push = push
    tb.build(_exam(n_common, big={1, 2, 3}, subject=subject, n_sub=n_sub))
    return seen


def test_fixed_layout_2028():
    seen = {i + 1: s[1:] for i, s in enumerate(_where(30))}
    expect = {1: (1, 0, 0), 2: (1, 0, 1), 3: (1, 1, 0), 4: (1, 1, 1), 5: (2, 0, 0), 6: (2, 0, 1), 7: (2, 1, 0),
              8: (3, 0, 0), 9: (3, 0, 1), 10: (3, 1, 0), 11: (4, 0, 0), 20: (8, 1, 0), 21: (9, 0, 0),
              22: (9, 1, 0), 23: (9, 1, 1), 24: (10, 0, 0), 25: (10, 0, 1), 26: (10, 1, 0), 27: (11, 0, 0),
              28: (11, 1, 0), 29: (12, 0, 0), 30: (12, 1, 0)}
    for n, where in expect.items():
        assert seen[n] == where, n


def test_fixed_layout_2028_labels():
    doc = build_textbook(_exam(30), template="모의고사")
    sec, _ = _section(doc)
    assert sec.count(">5 지 선 다 형<") == 1 and sec.count(">단 답 형<") == 1


def test_fixed_layout_2027_with_subject():
    seen = _where(22, subject="미적분", n_sub=8, exam=OLD_2027)
    common = {i + 1: s[1:] for i, s in enumerate(seen[:22])}
    # '크게' 표시는 무시되고 평가원 원본 자리대로
    assert common[1] == (1, 0, 0) and common[2] == (1, 0, 1) and common[3] == (1, 1, 0) and common[4] == (1, 1, 1)
    assert common[7] == (2, 1, 0) and common[10] == (3, 1, 0)
    assert common[15] == (6, 0, 0) and common[16] == (6, 1, 0) and common[17] == (6, 1, 1)
    assert common[20] == (7, 1, 0) and common[21] == (8, 0, 0) and common[22] == (8, 1, 0)
    sub = [s[1:] for s in seen[22:]]
    assert sub == [(p, c, 0) for p in (1, 2, 3, 4) for c in (0, 1)]
