"""hwpxwriter 테스트.

한글 프로그램 없이 확인할 수 있는 것들을 검사한다:
  * ZIP 구조 (mimetype 이 첫 항목·무압축, 필수 파일 존재)
  * 모든 XML 이 올바른 형식인지
  * 본문의 모든 참조(charPrIDRef, paraPrIDRef, borderFillIDRef, styleIDRef, binaryItemIDRef)가
    header.xml / content.hpf 에 실제로 정의되어 있는지
  * itemCnt 속성이 실제 항목 수와 맞는지
  * Markdown 해석 결과
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hwpxwriter import HwpxDocument, PageSetup, Run, markdown_to_hwpx, text_to_hwpx
from hwpxwriter.cli import main as cli_main
from hwpxwriter.images import probe
from hwpxwriter.markdown import parse_inline
from hwpxwriter.xmlns import NAMESPACES

HP = "{%s}" % NAMESPACES["hp"]
HH = "{%s}" % NAMESPACES["hh"]
HC = "{%s}" % NAMESPACES["hc"]
OPF = "{%s}" % NAMESPACES["opf"]

REQUIRED = [
    "mimetype",
    "version.xml",
    "META-INF/container.xml",
    "META-INF/manifest.xml",
    "Contents/content.hpf",
    "Contents/header.xml",
    "Contents/section0.xml",
    "settings.xml",
]


def tiny_png(w: int = 40, h: int = 20) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def validate(data: bytes) -> dict[str, ET.Element]:
    """HWPX 패키지를 구조적으로 검사하고 파싱된 XML 들을 돌려준다."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    infos = zf.infolist()
    assert infos[0].filename == "mimetype"
    assert infos[0].compress_type == zipfile.ZIP_STORED
    assert zf.read("mimetype") == b"application/hwp+zip"
    names = zf.namelist()
    for req in REQUIRED:
        assert req in names, req
    assert len(names) == len(set(names)), "중복 항목"

    trees = {n: ET.fromstring(zf.read(n)) for n in names if n.endswith((".xml", ".hpf", ".rdf"))}
    head = trees["Contents/header.xml"]
    sec = trees["Contents/section0.xml"]
    hpf = trees["Contents/content.hpf"]

    def ids(tag: str) -> set[str]:
        return {e.get("id") for e in head.iter(HH + tag)}

    char_ids, para_ids, bf_ids, style_ids = ids("charPr"), ids("paraPr"), ids("borderFill"), ids("style")
    assert "0" in char_ids and "0" in para_ids and "0" in style_ids
    # id 는 0(또는 borderFill 은 1)부터 빈틈없이
    assert sorted(map(int, char_ids)) == list(range(len(char_ids)))
    assert sorted(map(int, para_ids)) == list(range(len(para_ids)))
    assert sorted(map(int, bf_ids)) == list(range(1, len(bf_ids) + 1))

    # itemCnt 검사
    for container, child in [
        ("charProperties", "charPr"),
        ("paraProperties", "paraPr"),
        ("borderFills", "borderFill"),
        ("styles", "style"),
        ("fontfaces", "fontface"),
    ]:
        el = head.find(f".//{HH}{container}")
        assert int(el.get("itemCnt")) == len(el.findall(HH + child)), container
    font_count = {fc.get("lang"): int(fc.get("fontCnt")) for fc in head.iter(HH + "fontface")}
    for fc in head.iter(HH + "fontface"):
        assert len(fc.findall(HH + "font")) == int(fc.get("fontCnt"))

    # 헤더 내부 참조
    for cp in head.iter(HH + "charPr"):
        assert cp.get("borderFillIDRef") in bf_ids
        ref = cp.find(HH + "fontRef")
        for lang, attr in zip(font_count, ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")):
            assert int(ref.get(attr)) < font_count[lang]
    for pp in head.iter(HH + "paraPr"):
        assert pp.find(HH + "border").get("borderFillIDRef") in bf_ids
    for st in head.iter(HH + "style"):
        assert st.get("paraPrIDRef") in para_ids and st.get("charPrIDRef") in char_ids

    # 본문 참조
    for el in sec.iter():
        if "charPrIDRef" in el.attrib:
            assert el.get("charPrIDRef") in char_ids, el.tag
        if "paraPrIDRef" in el.attrib:
            assert el.get("paraPrIDRef") in para_ids, el.tag
        if "styleIDRef" in el.attrib:
            assert el.get("styleIDRef") in style_ids, el.tag
        if el.tag in (HP + "tbl", HP + "tc"):
            assert el.get("borderFillIDRef") in bf_ids

    # 문단 id 중복 없음
    pids = [p.get("id") for p in sec.iter(HP + "p")]
    assert len(pids) == len(set(pids)), "문단 id 중복"

    # 첫 문단 첫 run 에 구역 정의
    first_run = sec.find(HP + "p").find(HP + "run")
    assert first_run.find(HP + "secPr") is not None

    # 그림 ↔ manifest ↔ BinData
    manifest = {i.get("id"): i.get("href") for i in hpf.iter(OPF + "item")}
    for img in sec.iter(HC + "img"):
        ref = img.get("binaryItemIDRef")
        assert ref in manifest and manifest[ref] in names

    # 표 구조
    for tbl in sec.iter(HP + "tbl"):
        rows = tbl.findall(HP + "tr")
        assert int(tbl.get("rowCnt")) == len(rows)
        for r, tr in enumerate(rows):
            cells = tr.findall(HP + "tc")
            assert len(cells) == int(tbl.get("colCnt"))
            for c, tc in enumerate(cells):
                addr = tc.find(HP + "cellAddr")
                assert (addr.get("rowAddr"), addr.get("colAddr")) == (str(r), str(c))
                assert tc.find(HP + "subList").find(HP + "p") is not None
    return trees


def section_text(trees: dict[str, ET.Element]) -> str:
    return "".join(t.text or "" for t in trees["Contents/section0.xml"].iter(HP + "t"))


# ---------------------------------------------------------------------------


def test_empty_document_is_valid():
    trees = validate(HwpxDocument().to_bytes())
    assert len(list(trees["Contents/section0.xml"].iter(HP + "p"))) == 1


def test_all_features_document_is_valid(tmp_path: Path):
    doc = HwpxDocument(PageSetup(paper="A4", landscape=True), title="테스트")
    doc.add_title("제목", subtitle="부제")
    doc.add_heading("1. 첫 장", level=1)
    doc.add_paragraph(["보통 ", Run("굵게", bold=True), " ", Run("빨강", color="#FF0000"), " <&> 특수문자"])
    doc.add_paragraph("가운데", align="center", size=14)
    doc.add_list_item("항목", level=0)
    doc.add_list_item("하위", level=1)
    doc.add_list_item("번호", ordered_number=3)
    doc.add_code_block("def f():\n    return 1\n")
    doc.add_quote("인용")
    doc.add_horizontal_rule()
    doc.add_table([["가", "나"], ["1", Run("2", bold=True)], ["짧은 행"]], align=["left", "right"], caption="표 1")
    doc.add_image(tiny_png(), width=50, caption="그림 1")
    doc.add_image(tiny_png(), width_ratio=0.3)  # 같은 그림 → BinData 하나
    doc.add_page_break()
    doc.add_paragraph("새 쪽")
    doc.add_page_break()  # 마지막 쪽 나눔
    doc.set_header("머리말 {page}/{total}", align="right")
    doc.set_footer("- {page} -")
    saved = doc.save(tmp_path / "all.hwpx")
    data = saved.read_bytes()
    trees = validate(data)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert [n for n in names if n.startswith("BinData/")] == ["BinData/image1.png"]
    sec = trees["Contents/section0.xml"]
    assert sec.find(f".//{HP}header") is not None and sec.find(f".//{HP}footer") is not None
    assert {a.get("numType") for a in sec.iter(HP + "autoNum")} == {"PAGE", "TOTAL_PAGE"}
    assert sum(p.get("pageBreak") == "1" for p in sec.iter(HP + "p")) == 2
    page_pr = sec.find(f".//{HP}pagePr")
    assert page_pr.get("landscape") == "NARROWLY" and int(page_pr.get("width")) > int(page_pr.get("height"))
    text = section_text(trees)
    assert "<&>" in text and "특수문자" in text
    # 저장을 두 번 해도 유효
    validate(doc.to_bytes())


def test_markdown_sample_converts(tmp_path: Path):
    sample = Path(__file__).resolve().parent.parent / "examples" / "sample.md"
    doc = markdown_to_hwpx(sample.read_text(encoding="utf-8"), tmp_path / "s.hwpx", base_dir=sample.parent,
                           page_number=True, header="머리말")
    trees = validate((tmp_path / "s.hwpx").read_bytes())
    sec = trees["Contents/section0.xml"]
    assert len(list(sec.iter(HP + "tbl"))) == 1
    assert len(list(sec.iter(HP + "pic"))) == 1
    assert "그림을 넣지 못함" not in doc.plain_text()
    assert sec.find(f".//{HP}lineBreak") is not None  # 줄 끝 공백 2칸


def test_heading_and_inline_styles_resolve_to_bold():
    doc = markdown_to_hwpx("# 큰 제목\n\n**굵게** 와 *기울임*")
    trees = validate(doc.to_bytes())
    head, sec = trees["Contents/header.xml"], trees["Contents/section0.xml"]
    bold_ids = {c.get("id") for c in head.iter(HH + "charPr") if c.find(HH + "bold") is not None}
    italic_ids = {c.get("id") for c in head.iter(HH + "charPr") if c.find(HH + "italic") is not None}
    runs = {(r.findtext(HP + "t") or ""): r.get("charPrIDRef") for r in sec.iter(HP + "run")}
    assert runs["큰 제목"] in bold_ids
    assert runs["굵게"] in bold_ids
    assert runs["기울임"] in italic_ids
    heights = {c.get("id"): int(c.get("height")) for c in head.iter(HH + "charPr")}
    assert heights[runs["큰 제목"]] == 2000


def test_parse_inline():
    runs = parse_inline("a **b** *c* ***d*** ~~e~~ `f*g*` [h](http://x) \\*i\\* snake_case_name")
    simple = [(r.text, r.bold, r.italic, r.strike, r.code, r.underline) for r in runs]
    assert ("b", True, False, False, False, False) in simple
    assert ("c", False, True, False, False, False) in simple
    assert ("d", True, True, False, False, False) in simple
    assert ("e", False, False, True, False, False) in simple
    assert ("f*g*", False, False, False, True, False) in simple
    assert ("h", False, False, False, False, True) in simple
    assert "".join(r.text for r in runs).endswith(" *i* snake_case_name")


def test_parse_inline_unclosed_markers_are_literal():
    assert "".join(r.text for r in parse_inline("2 * 3 = 6, **열림")) == "2 * 3 = 6, **열림"


def test_markdown_lists_nesting_and_numbering():
    md = "1. 하나\n2. 둘\n   - 하위\n   - 하위2\n3. 셋\n\n- [x] 완료\n- [ ] 미완료\n"
    doc = markdown_to_hwpx(md)
    lines = doc.plain_text().split("\n")
    # 2단계 글머리표는 ◦, 번호는 하위 목록 뒤에도 이어진다
    assert lines[:5] == ["1. 하나", "2. 둘", "◦ 하위", "◦ 하위2", "3. 셋"]
    assert lines[5:7] == ["☑ 완료", "☐ 미완료"]


def test_markdown_table_alignment():
    md = "| 왼 | 가운데 | 오른 |\n|:--|:--:|--:|\n| a | b | c |\n| 파이프 \\| 포함 | | |\n"
    trees = validate(markdown_to_hwpx(md).to_bytes())
    head, sec = trees["Contents/header.xml"], trees["Contents/section0.xml"]
    align = {p.get("id"): p.find(HH + "align").get("horizontal") for p in head.iter(HH + "paraPr")}
    body_row = sec.find(f".//{HP}tbl").findall(HP + "tr")[1]
    got = [align[tc.find(f".//{HP}p").get("paraPrIDRef")] for tc in body_row.findall(HP + "tc")]
    assert got == ["LEFT", "CENTER", "RIGHT"]
    assert "파이프 | 포함" in section_text(trees)


def test_missing_image_becomes_warning_paragraph(tmp_path: Path):
    doc = markdown_to_hwpx("![없음](nope.png)", base_dir=tmp_path)
    assert "그림을 넣지 못함" in doc.plain_text()
    validate(doc.to_bytes())


def test_big_image_is_scaled_to_text_width():
    doc = HwpxDocument()
    doc.add_image(tiny_png(4000, 100))
    sec = validate(doc.to_bytes())["Contents/section0.xml"]
    assert int(sec.find(f".//{HP}pic/{HP}sz").get("width")) == doc.page.text_width


def test_text_mode_one_paragraph_per_line():
    doc = text_to_hwpx("첫 줄\n**그대로**\n\n넷째")
    assert doc.plain_text() == "첫 줄\n**그대로**\n\n넷째"


def test_probe_formats():
    assert probe(tiny_png(7, 3)).width == 7
    gif = b"GIF89a" + struct.pack("<HH", 5, 9) + b"\x00" * 10
    assert (probe(gif).width, probe(gif).height) == (5, 9)
    jpeg = b"\xff\xd8" + b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 30, 40) + b"\x03\x01\x22\x00"
    assert (probe(jpeg).width, probe(jpeg).height) == (40, 30)
    with pytest.raises(ValueError):
        probe(b"not an image")


def test_cli(tmp_path: Path, capsys):
    src = tmp_path / "문서.md"
    src.write_text("# 제목\n\n본문", encoding="utf-8")
    assert cli_main([str(src), "--page-number", "--paper", "B5", "--margin", "10,15,10,15"]) == 0
    out = tmp_path / "문서.hwpx"
    validate(out.read_bytes())
    txt = tmp_path / "a.txt"
    txt.write_text("한 줄", encoding="utf-8")
    assert cli_main([str(txt), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out.hwpx").exists()
    assert cli_main([str(src), "--paper", "Z9"]) == 2
