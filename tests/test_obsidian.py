"""Obsidian 볼트 → 교재 테스트 (examples/obsidian_vault 사용)."""

from __future__ import annotations

import shutil
from pathlib import Path

from hwpxwriter.cli import main as cli_main
from hwpxwriter.obsidian import (
    BookBuilder,
    ObsidianSettings,
    Vault,
    exam_display,
    expand_note,
    find_vault_root,
    parse_frontmatter,
)
from hwpxwriter.textbook import build_from_obsidian, load_template

from test_hwpx import HP, validate

VAULT = Path(__file__).resolve().parent.parent / "examples" / "obsidian_vault"
BOOK = VAULT / "교재" / "수능 파이널 (예시).md"
NOTE30 = VAULT / "20_Teaching_Materials" / "마더텅 수능기출" / "2025 9월모평" / "2025 9월모평 수학 30번 (기하).md"
BOXES = set(load_template("문제집").boxes)


def builder() -> BookBuilder:
    return BookBuilder(Vault(VAULT), box_names=BOXES)


def test_frontmatter_parsing():
    meta, body = parse_frontmatter(
        '---\ntitle: "제목: 콜론"\nnumber: 30\nanswer: "54"\nok: true\ntags:\n  - a\n  - b/c\ninline: [x, "y z"]\n'
        "empty:\n---\n본문\n"
    )
    assert meta == {"title": "제목: 콜론", "number": 30, "answer": "54", "ok": True, "tags": ["a", "b/c"],
                    "inline": ["x", "y z"], "empty": None}
    assert body == "본문\n"
    assert parse_frontmatter("본문만") == ({}, "본문만")


def test_exam_display():
    s = ObsidianSettings()
    assert exam_display("9월모평", s) == "9월 모의평가"
    assert exam_display("3월학평", s) == "3월 학력평가"
    assert exam_display("수능", s) == "수능"
    assert exam_display("9월모평", ObsidianSettings(exam_names={"9월모평": "9월 평가원"})) == "9월 평가원"


def test_vault_root_detection():
    assert find_vault_root(NOTE30) == VAULT.resolve()


def test_user_problem_note_becomes_problem_block():
    b = builder()
    note = b.vault.read(NOTE30)
    assert b.is_problem(note)
    text = "\n".join(b.problem_block(note))
    assert "::: 문제 2025학년도 9월 모의평가 30번" in text
    assert "(4점)" not in text and "[4점]" in text  # 배점은 교재식 대괄호로
    assert "[정답] 54" in text
    assert "정답: 54" not in text  # 콜아웃 안 정답 줄은 정답표로만
    assert "[해설]" in text and "M+m=54" in text
    assert "# 2025학년도" not in text  # 제목 줄은 버림
    assert "MOC" not in text and "[[" not in text  # 끝의 목차 링크 버림
    assert "attachments/2025-9월모평_기하_30_1.png>)" in text
    assert text.index("[정답]") > text.index("구하시오")


def test_choice_answer_number_becomes_circled_and_callout_answer_is_used():
    b = builder()
    nine = b.vault.read(b.vault.find_note("2027 9월모평 수학 9번"))
    six = b.vault.read(b.vault.find_note("2027 6월모평 수학 9번"))  # 속성에 answer 없음
    assert "[정답] ①" in "\n".join(b.problem_block(nine))
    six_text = "\n".join(b.problem_block(six))
    assert "[정답] ③" in six_text and "정답: 3" not in six_text
    assert "%%" not in "\n".join(b.problem_block(nine))  # 주석 제거


def test_section_embed_and_callout_box():
    b = builder()
    lines = b.embed_note("수직선 위의 운동", "위치·속도·가속도", BOOK)
    text = "\n".join(lines)
    assert "### 1 위치·속도·가속도의 관계" in text
    assert "메모" not in text  # 다른 부분은 안 가져옴
    assert "::: 주의\n" in text + "\n" and "::: 주의 주의" not in text
    assert "^speed" not in text  # 블록 id 제거


def test_query_filters_sorts_and_limits():
    b = builder()
    nine = "\n".join(b.query("subject=수학Ⅱ year>=2027", BOOK))
    assert nine.index("6월 모의평가") < nine.index("9월 모의평가")  # 같은 해: 6월 → 9월
    assert "기하" not in nine
    last = "\n".join(builder().query("subject=수학Ⅱ sort=-exam limit=1", BOOK))
    assert last.count("::: 문제") == 1 and "9월 모의평가" in last
    assert "30번" in "\n".join(builder().query("tags=수능기출 number>20", BOOK))
    assert b.query("subject=없는과목", BOOK) == [] and b.warnings


def test_query_skips_problems_already_in_book():
    b = builder()
    first = "\n".join(b.query("subject=수학Ⅱ", BOOK))
    assert first.count("::: 문제") >= 2
    assert b.query("subject=수학Ⅱ", BOOK) == []  # 같은 문제를 두 번 넣지 않음
    b2 = builder()
    b2.embed_note("2027 9월모평 수학 9번", None, BOOK)
    again = "\n".join(b2.query("subject=수학Ⅱ", BOOK))
    assert again.count("::: 문제") == first.count("::: 문제") - 1


def test_query_only_book_outside_vault_uses_obsidian_mode(tmp_path: Path):
    book = tmp_path / "책.md"
    book.write_text("---\ntemplate: 문제집\n---\n# 01 벡터\n\\문제모음 subject=기하\n", encoding="utf-8")
    out = tmp_path / "책.hwpx"
    assert cli_main([str(book), "--vault", str(VAULT), "-o", str(out)]) == 0
    assert cli_main([str(book), "-o", str(tmp_path / "b.hwpx")]) == 0  # 볼트 밖이어도 문제모음은 펼쳐 봄


def test_missing_note_and_self_embed_warn(tmp_path: Path):
    vault = tmp_path / "v"
    shutil.copytree(VAULT, vault)
    (vault / "자기참조.md").write_text("앞\n![[자기참조]]\n![[없는 노트]]\n", encoding="utf-8")
    text, _, warnings = expand_note(vault / "자기참조.md")
    assert "노트를 찾지 못함: 없는 노트" in text
    assert any("자기 자신" in w for w in warnings) and any("없는 노트" in w for w in warnings)


def test_build_book_end_to_end(tmp_path: Path):
    doc = build_from_obsidian(BOOK, tmp_path / "책.hwpx")
    assert doc.warnings == []
    data = (tmp_path / "책.hwpx").read_bytes()
    trees = validate(data)
    sec = trees["Contents/section0.xml"]
    assert len(list(sec.iter(HP + "pic"))) == 1
    assert len(list(sec.iter(HP + "equation"))) > 30
    text = doc.plain_text()
    body, answers = text.split("정답과 해설", 1)
    assert "M+m=54" not in body and "M+m=54" in answers  # 해설은 책 뒤로
    assert "2025학년도 9월 모의평가 30번" in body
    # 양식은 책 노트 속성(template: 수능파이널)에서
    assert any(t.get("colCnt") == "10" for t in sec.iter(HP + "tbl"))


def test_single_problem_note_and_cli(tmp_path: Path):
    out = tmp_path / "30.hwpx"
    assert cli_main([str(NOTE30), "-t", "문제집", "-o", str(out)]) == 0
    validate(out.read_bytes())
    out2 = tmp_path / "book.hwpx"
    assert cli_main([str(BOOK), "--vault", str(VAULT), "-o", str(out2)]) == 0
    validate(out2.read_bytes())
