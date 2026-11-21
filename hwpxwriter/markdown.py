"""Markdown → HwpxDocument 변환 (외부 라이브러리 없음).

지원 문법
  블록:  # 제목(1~6), 문단, - * + 글머리표 / 1. 번호 목록(중첩, [ ] 체크박스),
         > 인용, ``` 코드 블록, | 표 |, ![그림](경로){width=50%}, ---(구분선),
         \\newpage · \\pagebreak · <!-- pagebreak -->(쪽 나눔), 줄 끝 공백 2칸/\\ (줄바꿈)
  글자:  **굵게**, *기울임*, ***굵게+기울임***, ~~취소선~~, `코드`, [링크](주소),
         <u>밑줄</u>, <sup>위첨자</sup>, <sub>아래첨자</sub>, ==형광펜==, <br>
"""

from __future__ import annotations

import html
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .document import Run

if TYPE_CHECKING:
    from .document import HwpxDocument

# ---------------------------------------------------------------------------
# 인라인
# ---------------------------------------------------------------------------

_ESCAPABLE = set("\\`*_{}[]()#+-.!|~<>=\"'")
_HTML_TAGS = {
    "b": "bold",
    "strong": "bold",
    "i": "italic",
    "em": "italic",
    "u": "underline",
    "ins": "underline",
    "s": "strike",
    "del": "strike",
    "strike": "strike",
    "sup": "superscript",
    "sub": "subscript",
    "mark": "highlight",
}
_HIGHLIGHT = "#FFF59D"


def parse_inline(text: str, base: Run | None = None, link_color: str = "#0563C1") -> list[Run]:
    """한 문단의 Markdown 글자 서식을 Run 목록으로 바꾼다."""
    base = base or Run("")
    out: list[Run] = []
    buf: list[str] = []

    def emit_text() -> None:
        if buf:
            out.append(replace(base, text=html.unescape("".join(buf))))
            buf.clear()

    def wrap(inner: str, **changes: object) -> None:
        emit_text()
        out.extend(parse_inline(inner, replace(base, **changes), link_color))

    i, n = 0, len(text)
    while i < n:
        ch = text[i]

        # 줄바꿈: 줄 끝 공백 2칸 이상 또는 역슬래시 → 강제 줄바꿈, 그 외는 공백
        if ch == "\n":
            hard = (i >= 2 and text[i - 2 : i] == "  ") or (buf and buf[-1] == "\\")
            if buf and buf[-1] == "\\":
                buf.pop()
            while buf and buf[-1] == " ":
                buf.pop()
            buf.append("\n" if hard else " ")
            i += 1
            continue

        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            buf.append(text[i + 1])
            i += 2
            continue

        # `코드`
        if ch == "`":
            m = re.match(r"(`+)", text[i:])
            ticks = m.group(1)
            end = text.find(ticks, i + len(ticks))
            if end != -1:
                emit_text()
                code = text[i + len(ticks) : end].replace("\n", " ")
                if code.startswith(" ") and code.endswith(" ") and code.strip():
                    code = code[1:-1]
                out.append(replace(base, text=code, code=True))
                i = end + len(ticks)
                continue
            buf.append(ticks)
            i += len(ticks)
            continue

        # ![그림](주소) — 문단 중간의 그림은 대체 글자로
        if ch == "!" and text.startswith("![", i):
            m = re.match(r"!\[([^\]]*)\]\(([^)]*)\)(\{[^}]*\})?", text[i:])
            if m:
                emit_text()
                alt = m.group(1) or "그림"
                out.append(replace(base, text=f"[{alt}]", italic=True))
                i += m.end()
                continue

        # [링크](주소)
        if ch == "[":
            m = re.match(r"\[((?:[^\[\]\\]|\\.|\[[^\]]*\])*)\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)", text[i:])
            if m:
                wrap(m.group(1), color=link_color, underline=True)
                i += m.end()
                continue

        # <http://...> 자동 링크, <br>, 간단한 HTML 태그
        if ch == "<":
            m = re.match(r"<((?:https?|ftp)://[^>\s]+|[\w.+-]+@[\w-]+\.[\w.-]+)>", text[i:])
            if m:
                emit_text()
                out.append(replace(base, text=m.group(1), color=link_color, underline=True))
                i += m.end()
                continue
            m = re.match(r"<br\s*/?>", text[i:], re.I)
            if m:
                buf.append("\n")
                i += m.end()
                continue
            m = re.match(r"<(\w+)(?:\s[^>]*)?>", text[i:])
            if m and m.group(1).lower() in _HTML_TAGS:
                tag = m.group(1).lower()
                close = re.search(rf"</{tag}\s*>", text[i + m.end() :], re.I)
                if close:
                    inner = text[i + m.end() : i + m.end() + close.start()]
                    attr = _HTML_TAGS[tag]
                    wrap(inner, **({"highlight": _HIGHLIGHT} if attr == "highlight" else {attr: True}))
                    i += m.end() + close.end()
                    continue
            m = re.match(r"<!--.*?-->|</?\w+(?:\s[^>]*)?/?>", text[i:], re.S)
            if m:  # 그 밖의 HTML 태그는 지움
                i += m.end()
                continue

        # 강조: *** ** * ___ __ _ ~~ ==
        if ch in "*_~=":
            run_len = len(re.match(rf"\{ch}+", text[i:]).group(0))
            if ch in "~=" and run_len < 2:
                buf.append(ch)
                i += 1
                continue
            delim = ch * (min(run_len, 3) if ch in "*_" else 2)
            prev = text[i - 1] if i > 0 else " "
            nxt = text[i + len(delim)] if i + len(delim) < n else " "
            opens = not nxt.isspace() and not (ch == "_" and prev.isalnum())
            if opens:
                end = _find_closing(text, i + len(delim), delim)
                if end != -1:
                    inner = text[i + len(delim) : end]
                    if ch == "~":
                        wrap(inner, strike=True)
                    elif ch == "=":
                        wrap(inner, highlight=_HIGHLIGHT)
                    elif len(delim) == 3:
                        wrap(inner, bold=True, italic=True)
                    elif len(delim) == 2:
                        wrap(inner, bold=True)
                    else:
                        wrap(inner, italic=True)
                    i = end + len(delim)
                    continue
            buf.append(text[i : i + run_len])
            i += run_len
            continue

        buf.append(ch)
        i += 1

    emit_text()
    return out


def _find_closing(text: str, start: int, delim: str) -> int:
    """start 이후에서 delim 으로 닫히는 위치. 코드 구간과 이스케이프는 건너뛴다."""
    i, n, ch = start, len(text), delim[0]
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            ticks = re.match(r"`+", text[i:]).group(0)
            end = text.find(ticks, i + len(ticks))
            i = (end + len(ticks)) if end != -1 else i + len(ticks)
            continue
        if text.startswith(delim, i) and i > start and not text[i - 1].isspace():
            run_len = len(re.match(rf"\{ch}+", text[i:]).group(0))
            after = text[i + run_len] if i + run_len < n else " "
            if ch == "_" and after.isalnum():
                i += run_len
                continue
            # '**굵게*기울임***' 처럼 더 긴 구분자 묶음이면 끝쪽을 닫는 짝으로 쓴다
            return i + run_len - len(delim) if run_len > len(delim) else i
        i += 1
    return -1


# ---------------------------------------------------------------------------
# 블록
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})\s*([\w+#.-]*)")
_LIST = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_TASK = re.compile(r"^\[([ xX])\][ \t]+")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_IMAGE_BLOCK = re.compile(r"^\s*!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"([^\"]*)\")?\s*\)(\{[^}]*\})?\s*$")
_PAGEBREAK = re.compile(r"^\s*(\\newpage|\\pagebreak|<!--\s*(page\s*-?break|newpage)\s*-->)\s*$", re.I)
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_QUOTE = re.compile(r"^ {0,3}>\s?")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, cur, i = [], [], 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if line[i] == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(line[i])
        i += 1
    cells.append("".join(cur).strip())
    return cells


def _table_align(sep: str) -> list[str | None]:
    out: list[str | None] = []
    for cell in _split_row(sep):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else "right" if right else "left" if left else None)
    return out


def _image_attrs(spec: str | None) -> dict[str, float]:
    """{width=50%} / {width=80mm} / {width=0.5}"""
    if not spec:
        return {}
    m = re.search(r"width\s*=\s*\"?([\d.]+)\s*(%|mm|cm)?", spec)
    if not m:
        return {}
    value, unit = float(m.group(1)), m.group(2)
    if unit == "%":
        return {"width_ratio": value / 100}
    if unit == "mm":
        return {"width": value}
    if unit == "cm":
        return {"width": value * 10}
    return {"width_ratio": value} if value <= 1 else {"width": value}


def _starts_block(line: str, next_line: str | None) -> bool:
    return bool(
        _HEADING.match(line)
        or _HR.match(line)
        or _FENCE.match(line)
        or _LIST.match(line)
        or _QUOTE.match(line)
        or _PAGEBREAK.match(line)
        or _IMAGE_BLOCK.match(line)
        or ("|" in line and next_line is not None and _TABLE_SEP.match(next_line) and "-" in next_line)
    )


def _strip_front_matter(lines: list[str]) -> list[str]:
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                return lines[j + 1 :]
    return lines


def render_markdown(doc: "HwpxDocument", text: str, *, base_dir: Path) -> None:
    lines = _strip_front_matter(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    link_color = doc.theme.link_color

    def inline(s: str, **base: object) -> list[Run]:
        return parse_inline(s, Run("", **base), link_color)

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < n else None

        if not line.strip():
            i += 1
            continue

        if _PAGEBREAK.match(line):
            doc.add_page_break()
            i += 1
            continue

        # 코드 블록
        m = _FENCE.match(line)
        if m:
            indent, fence, lang = len(m.group(1)), m.group(2), m.group(3)
            body: list[str] = []
            i += 1
            while i < n and not re.match(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$", lines[i]):
                body.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i])
                i += 1
            i += 1  # 닫는 펜스
            doc.add_code_block("\n".join(body), language=lang or None)
            continue

        m = _HEADING.match(line)
        if m:
            doc.add_heading(inline((m.group(2) or "").strip()), level=len(m.group(1)))
            i += 1
            continue

        if _HR.match(line):
            doc.add_horizontal_rule()
            i += 1
            continue

        # 표
        if "|" in line and nxt is not None and _TABLE_SEP.match(nxt) and "-" in nxt:
            header = _split_row(line)
            aligns = _table_align(nxt)
            rows = [header]
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(_split_row(lines[i]))
                i += 1
            width = len(header)
            cells = [[inline(c) for c in (r + [""] * width)[:width]] for r in rows]
            doc.add_table(cells, header=True, align=aligns[:width])
            continue

        # 그림 (한 줄 전체가 그림일 때)
        m = _IMAGE_BLOCK.match(line)
        if m:
            alt, src, title, attrs = m.groups()
            _add_image(doc, base_dir, src, alt, title, _image_attrs(attrs), inline)
            i += 1
            continue

        # 인용
        if _QUOTE.match(line):
            quote: list[str] = []
            while i < n and lines[i].strip() and (_QUOTE.match(lines[i]) or not _starts_block(lines[i], None)):
                quote.append(_QUOTE.sub("", lines[i], count=1))
                i += 1
            _render_quote(doc, quote, inline)
            continue

        # 목록
        if _LIST.match(line):
            i = _render_list(doc, lines, i, inline)
            continue

        # 문단 (+ setext 제목)
        para = [line]
        i += 1
        while i < n and lines[i].strip():
            if _SETEXT.match(lines[i]) and len(para) >= 1:
                level = 1 if lines[i].strip().startswith("=") else 2
                doc.add_heading(inline("\n".join(para).strip()), level=level)
                para = []
                i += 1
                break
            if _starts_block(lines[i], lines[i + 1] if i + 1 < n else None) and not _SETEXT.match(lines[i]):
                break
            para.append(lines[i])
            i += 1
        if para:
            # 줄 끝 공백 2칸(강제 줄바꿈 표시)은 남겨야 하므로 왼쪽만 다듬는다
            doc.add_paragraph(inline("\n".join(s.lstrip() for s in para).rstrip()))


def _add_image(doc, base_dir: Path, src: str, alt: str, title: str | None, attrs: dict, inline) -> None:
    path = Path(src)
    if not path.is_absolute():
        path = base_dir / path
    caption = title or alt or None
    try:
        doc.add_image(path, caption=inline(caption) if caption else None, **attrs)
    except (OSError, ValueError) as exc:
        doc.add_paragraph(inline(f"[그림을 넣지 못함: {src} — {exc}]"), color="#C00000", align="center")


def _render_quote(doc, lines: list[str], inline) -> None:
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            doc.add_quote(inline("\n".join(paragraph).strip()))
            paragraph.clear()

    for raw in lines:
        level = 0
        while _QUOTE.match(raw):  # 중첩 인용 > > 는 한 단계 더 들여씀
            raw = _QUOTE.sub("", raw, count=1)
            level += 1
        if not raw.strip():
            flush()
            continue
        m = _HEADING.match(raw)
        if m:
            flush()
            doc.add_quote(inline((m.group(2) or "").strip(), bold=True), level=level)
            continue
        if level:
            flush()
            doc.add_quote(inline(raw.strip()), level=level)
            continue
        lm = _LIST.match(raw)
        if lm:
            flush()
            marker = lm.group(2)
            bullet = marker if marker[0].isdigit() else doc.theme.bullets[0]
            doc.add_quote([Run(bullet + " ")] + inline(lm.group(3)))
            continue
        paragraph.append(raw)
    flush()


def _render_list(doc, lines: list[str], i: int, inline) -> int:
    """연속된 목록을 처리하고 다음 줄 번호를 돌려준다."""
    n = len(lines)
    indent_stack: list[int] = []  # 단계별 들여쓰기 열
    counters: dict[int, int] = {}
    items: list[tuple[int, str | None, int | None, list[str]]] = []  # (level, marker, number, text lines)
    loose = False

    while i < n:
        line = lines[i]
        m = _LIST.match(line)
        if m:
            col = len(m.group(1).replace("\t", "    "))
            # 2칸 이상 더 들여쓰면 한 단계 아래, 덜 들여쓰면 맞는 단계로 돌아감 (1칸 차이는 같은 단계)
            if indent_stack and col >= indent_stack[-1] + 2:
                indent_stack.append(col)
            else:
                while indent_stack and col <= indent_stack[-1] - 2:
                    indent_stack.pop()
                if not indent_stack:
                    indent_stack.append(col)
            level = len(indent_stack) - 1
            for deeper in [k for k in counters if k > level]:
                del counters[deeper]
            marker_raw, body = m.group(2), m.group(3)
            number = None
            marker = None
            if marker_raw[0].isdigit():
                start = int(marker_raw[:-1])
                number = counters[level] + 1 if level in counters else start
                counters[level] = number
            else:
                counters.pop(level, None)
            t = _TASK.match(body)
            if t:
                marker = "☑" if t.group(1).lower() == "x" else "☐"
                body = body[t.end() :]
                number = None
            items.append((level, marker, number, [body]))
            i += 1
            continue
        if not line.strip():
            # 빈 줄 뒤에 목록/들여쓴 내용이 이어지면 같은 목록
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (_LIST.match(lines[j]) or (lines[j].startswith(("  ", "\t")) and items)):
                loose = True
                i = j
                continue
            break
        if items and (line.startswith(("  ", "\t")) or not _starts_block(line, lines[i + 1] if i + 1 < n else None)):
            items[-1][3].append(line.strip())  # 이어지는 줄
            i += 1
            continue
        break

    for level, marker, number, text_lines in items:
        doc.add_list_item(
            inline("\n".join(text_lines).strip()),
            level=level,
            marker=marker,
            ordered_number=number,
            tight=not loose,
        )
    return i
