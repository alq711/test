r"""Obsidian 볼트에서 교재 원고 만들기.

책 노트(설계도) 하나를 받아 교재용 확장 Markdown 으로 펼친다::

    ---
    template: 문제집
    ---
    # 09 수직선 위의 운동
    ## 최근 기출 | 공통 9번
    ![[2025 9월모평 수학 30번 (기하)]]        ← 문제 노트 → ::: 문제 … :::
    ![[개념 정리 노트#위치와 속도]]            ← 일반 노트(의 한 부분)는 내용을 그대로
    \문제모음 subject=기하/평면벡터 year>=2024   ← 속성으로 골라 모으기 (연도·시험·번호순)

문제 노트 (속성 + 본문 + 정답 콜아웃)::

    ---
    year: 2025
    exam: "9월모평"
    number: 30
    answer: "54"
    ---
    # 제목 (버림)
    문제 본문 … $수식$ …
    ![[그림.png]]
    > [!check]- 정답과 풀이           ← 정답은 책 뒤 정답표로, 나머지는 해설로
    > **정답: 54**
    > 풀이 …
    ---
    시험지 목차: [[MOC]]               ← 끝의 링크 모음은 버림
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

_FRONTMATTER = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_EMBED_LINE = re.compile(r"^\s*!\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]*))?\]\]\s*$")
_EMBED_ANY = re.compile(r"!\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]*))?\]\]")
_WIKILINK = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")
_COMMENT = re.compile(r"%%.*?%%", re.S)
_BLOCK_ID = re.compile(r"\s\^[A-Za-z0-9-]+\s*$")
_CALLOUT = re.compile(r"^\s*>\s*\[!([^\]]+)\]([+-]?)\s*(.*)$")
_QUOTE_LINE = re.compile(r"^\s*>\s?(.*)$")
_ANSWER_LINE = re.compile(r"^\s*\**\s*(?:정답|답|answer)\s*\**\s*[:：]\s*(.+?)\s*\**\s*$", re.I)
_QUERY_LINE = re.compile(r"^\s*\\(문제모음|problems)\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}

# 콜아웃 종류 → 양식 상자 이름 (상자가 양식에 있을 때만)
DEFAULT_CALLOUT_BOXES = {
    "note": "참고", "info": "참고", "tip": "참고", "hint": "참고", "important": "참고",
    "warning": "주의", "caution": "주의", "attention": "주의", "danger": "주의", "error": "주의",
    "example": "예제", "abstract": "정의", "summary": "정의", "tldr": "정의", "definition": "정의",
    "theorem": "정리", "proof": "증명", "formula": "공식",
}
DEFAULT_ANSWER_CALLOUTS = {"check", "success", "done", "answer", "solution", "정답", "풀이", "해설"}
DEFAULT_PROBLEM_TYPES = {"problem-bank", "problem", "문제", "문제은행", "기출"}
DEFAULT_SOURCE_FORMAT = "{year}학년도 {exam} {number}번"


# ---------------------------------------------------------------------------
# 속성(YAML) — 노트 앞머리에 흔히 쓰는 범위만 (외부 라이브러리 없이)
# ---------------------------------------------------------------------------


def _scalar(text: str):
    text = text.strip()
    if not text:
        return ""
    if (text[0] == text[-1]) and text[0] in "\"'" and len(text) >= 2:
        inner = text[1:-1]
        return inner.replace('\\"', '"') if text[0] == '"' else inner.replace("''", "'")
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d*", text):
        return float(text)
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(x) for x in _split_flow(text[1:-1])]
    return text


def _split_flow(text: str) -> list[str]:
    out, cur, quote = [], [], None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """(속성, 본문). 속성이 없으면 ({}, 원문)."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text.lstrip("﻿")
    meta: dict = {}
    key = None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s*(.*)$", raw) or re.match(r"^-\s+(.*)$", raw)
        if item and key is not None:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_scalar(item.group(1)))
            continue
        kv = re.match(r"^([^:#\s][^:]*?)\s*:\s*(.*)$", raw)
        if kv and not raw.startswith((" ", "\t")):
            key = kv.group(1).strip()
            value = kv.group(2)
            meta[key] = _scalar(value) if value.strip() else None
    return meta, text[m.end():]


# ---------------------------------------------------------------------------
# 볼트
# ---------------------------------------------------------------------------


@dataclass
class Note:
    path: Path
    meta: dict
    body: str

    @property
    def name(self) -> str:
        return self.path.stem


def find_vault_root(start: str | Path) -> Path | None:
    """start 에서 위로 올라가며 .obsidian 폴더가 있는 곳을 찾는다."""
    p = Path(start).resolve()
    for d in ([p, *p.parents] if p.is_dir() else [p.parent, *p.parent.parents]):
        if (d / ".obsidian").is_dir():
            return d
    return None


class Vault:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._notes: dict[str, list[Path]] = {}
        self._files: dict[str, list[Path]] = {}
        self._cache: dict[Path, Note] = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                path = Path(dirpath) / fn
                if fn.lower().endswith(".md"):
                    self._notes.setdefault(path.stem.lower(), []).append(path)
                self._files.setdefault(fn.lower(), []).append(path)

    @staticmethod
    def _closest(candidates: list[Path], near: Path | None) -> Path:
        if near is not None:
            for c in candidates:
                if c.parent == near.parent:
                    return c
        return sorted(candidates, key=lambda c: (len(c.parts), str(c)))[0]

    def find_note(self, name: str, near: Path | None = None) -> Path | None:
        name = name.strip()
        rel = self.root / (name if name.lower().endswith(".md") else name + ".md")
        if rel.is_file():
            return rel
        key = Path(name).name.lower()
        key = key[:-3] if key.endswith(".md") else key
        found = self._notes.get(key)
        return self._closest(found, near) if found else None

    def find_file(self, name: str, near: Path | None = None) -> Path | None:
        name = name.strip()
        for base in ([near.parent] if near else []) + [self.root]:
            cand = base / name
            if cand.is_file():
                return cand
        found = self._files.get(Path(name).name.lower())
        return self._closest(found, near) if found else None

    def read(self, path: Path) -> Note:
        path = path.resolve()
        if path not in self._cache:
            text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            meta, body = parse_frontmatter(text)
            self._cache[path] = Note(path, meta, body)
        return self._cache[path]

    def notes(self) -> list[Note]:
        return [self.read(p) for paths in self._notes.values() for p in paths]


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


@dataclass
class ObsidianSettings:
    source_format: str = DEFAULT_SOURCE_FORMAT
    exam_names: dict = field(default_factory=dict)  # {"9월모평": "9월 모의평가"} (기본 규칙 위에 덧씀)
    callout_boxes: dict = field(default_factory=dict)  # {"note": "참고"}
    answer_callouts: set = field(default_factory=lambda: set(DEFAULT_ANSWER_CALLOUTS))
    problem_types: set = field(default_factory=lambda: set(DEFAULT_PROBLEM_TYPES))
    drop_title: bool = True  # 끼워 넣는 노트의 맨 앞 '# 제목' 버리기

    @classmethod
    def from_dict(cls, data: dict | None, warnings: list[str] | None = None) -> "ObsidianSettings":
        s = cls()
        for key, value in (data or {}).items():
            if key in ("answer_callouts", "problem_types"):
                setattr(s, key, {str(v).lower() for v in value})
            elif key in ("exam_names", "callout_boxes"):
                setattr(s, key, dict(value))
            elif hasattr(s, key):
                setattr(s, key, value)
            elif warnings is not None:
                warnings.append(f"양식 [obsidian] 의 '{key}' 는 알 수 없는 항목이라 무시했습니다")
        return s


def exam_display(exam: str, settings: ObsidianSettings) -> str:
    """'9월모평' → '9월 모의평가', '3월학평' → '3월 학력평가'."""
    if exam in settings.exam_names:
        return settings.exam_names[exam]
    text = re.sub(r"(\d+)\s*월\s*모평", r"\1월 모의평가", exam)
    text = re.sub(r"(\d+)\s*월\s*학평", r"\1월 학력평가", text)
    return text


def _exam_order(exam: str) -> float:
    if "수능" in exam:
        return 11.5
    m = re.search(r"(\d+)\s*월", exam)
    return float(m.group(1)) if m else 99.0


# ---------------------------------------------------------------------------
# 변환기
# ---------------------------------------------------------------------------


class BookBuilder:
    """책 노트를 교재용 확장 Markdown 으로 펼친다."""

    def __init__(self, vault: Vault, *, box_names: set[str] | None = None,
                 settings: ObsidianSettings | None = None) -> None:
        self.vault = vault
        self.box_names = set(box_names or ())
        self.s = settings or ObsidianSettings()
        self.warnings: list[str] = []
        self._stack: list[Path] = []

    # -- 판별 ------------------------------------------------------------
    def is_problem(self, note: Note) -> bool:
        kind = str(note.meta.get("type", "")).lower()
        if kind in self.s.problem_types:
            return True
        if "answer" in note.meta and ("number" in note.meta or "exam" in note.meta):
            return True
        return any(self._is_answer_callout(m.group(1), m.group(3))
                   for m in map(_CALLOUT.match, note.body.splitlines()) if m)

    def _is_answer_callout(self, kind: str, title: str) -> bool:
        return kind.strip().lower() in self.s.answer_callouts or bool(re.search(r"정답|풀이|해설", title or ""))

    # -- 글 줄 다듬기 ----------------------------------------------------------
    def _image(self, name: str, opt: str | None, near: Path) -> str:
        path = self.vault.find_file(name, near)
        if path is None:
            self.warnings.append(f"그림을 찾지 못함: {name} ({near.name})")
            return f"[그림 없음: {name}]"
        attrs = ""
        alt = ""
        if opt:
            m = re.fullmatch(r"\s*(\d+)(?:\s*x\s*\d+)?\s*", opt)
            if m:
                attrs = "{width=%.0fmm}" % (int(m.group(1)) * 25.4 / 96)
            else:
                alt = opt.strip()
        return f"![{alt}](<{path.as_posix()}>){attrs}"

    def _inline(self, line: str, near: Path) -> str:
        def embed(m: re.Match) -> str:
            target = m.group(1).strip()
            if Path(target).suffix.lower() in IMAGE_EXTS:
                return self._image(target, m.group(3), near)
            return m.group(3) or target  # 글 중간의 노트 삽입은 이름만

        line = _EMBED_ANY.sub(embed, line)
        line = _WIKILINK.sub(lambda m: (m.group(3) or m.group(1)).strip(), line)
        return _BLOCK_ID.sub("", line)

    @staticmethod
    def _drop_nav_tail(lines: list[str]) -> list[str]:
        """끝의 '---' 다음이 링크 모음뿐이면 버림 (시험지 목차: [[…]] 등)."""
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "---":
                tail = [x for x in lines[i + 1:] if x.strip()]
                if all("[[" in x or x.strip().startswith("#") for x in tail):
                    return lines[:i]
                break
        return lines

    @staticmethod
    def _section(lines: list[str], heading: str) -> list[str] | None:
        target = heading.strip().lower()
        for i, line in enumerate(lines):
            m = _HEADING.match(line)
            if m and m.group(2).strip().lower() == target:
                level = len(m.group(1))
                out = []
                for nxt in lines[i + 1:]:
                    hm = _HEADING.match(nxt)
                    if hm and len(hm.group(1)) <= level:
                        break
                    out.append(nxt)
                return out
        return None

    # -- 본문 줄들 처리 (삽입, 콜아웃, 문제모음) ---------------------------------
    def expand_lines(self, lines: list[str], near: Path) -> list[str]:
        out: list[str] = []
        i = 0
        in_fence = False
        while i < len(lines):
            line = lines[i]
            if re.match(r"^\s*(```|~~~)", line):
                in_fence = not in_fence
                out.append(line)
                i += 1
                continue
            if in_fence:
                out.append(line)
                i += 1
                continue
            m = _EMBED_LINE.match(line)
            if m and Path(m.group(1)).suffix.lower() not in IMAGE_EXTS:
                out.extend(self.embed_note(m.group(1), m.group(2), near))
                i += 1
                continue
            m = _QUERY_LINE.match(line)
            if m:
                out.extend(self.query(m.group(2), near))
                i += 1
                continue
            m = _CALLOUT.match(line)
            if m:
                block = [line]
                i += 1
                while i < len(lines) and _QUOTE_LINE.match(lines[i]):
                    block.append(lines[i])
                    i += 1
                out.extend(self.callout(m.group(1), m.group(3), block[1:], near))
                continue
            out.append(self._inline(line, near))
            i += 1
        return out

    def callout(self, kind: str, title: str, inner_quoted: list[str], near: Path) -> list[str]:
        inner = [_QUOTE_LINE.match(x).group(1) for x in inner_quoted]
        key = kind.strip().lower()
        box = None
        if kind.strip() in self.box_names:
            box = kind.strip()
        else:
            mapped = {**DEFAULT_CALLOUT_BOXES, **self.s.callout_boxes}.get(key)
            if mapped in self.box_names:
                box = mapped
        body = self.expand_lines(inner, near)
        if box:
            shown = self._inline(title, near).strip()
            if shown in (box, kind.strip()):  # '> [!warning] 주의' → 이름표와 겹치는 제목은 생략
                shown = ""
            return ["", f"::: {box} {shown}".rstrip(), *body, ":::", ""]
        head = [f"> **{self._inline(title, near)}**"] if title.strip() else []
        return head + [("> " + x) if x.strip() else ">" for x in body] + [""]

    # -- 노트 삽입 ------------------------------------------------------------
    def embed_note(self, name: str, section: str | None, near: Path) -> list[str]:
        path = self.vault.find_note(name, near)
        if path is None:
            self.warnings.append(f"노트를 찾지 못함: [[{name}]] ({near.name})")
            return [f"**[노트를 찾지 못함: {name}]**", ""]
        if path.resolve() in self._stack or len(self._stack) > 8:
            self.warnings.append(f"노트가 자기 자신을 끼워 넣어 멈춤: [[{name}]]")
            return []
        note = self.vault.read(path)
        self._stack.append(path.resolve())
        try:
            if self.is_problem(note) and not section:
                return self.problem_block(note)
            lines = _COMMENT.sub("", note.body).split("\n")
            if section:
                part = self._section(lines, section)
                if part is None:
                    self.warnings.append(f"노트에 그 제목이 없음: [[{name}#{section}]]")
                    return []
                lines = part
            else:
                lines = self._drop_nav_tail(self._drop_title(lines))
            return ["", *self.expand_lines(lines, note.path), ""]
        finally:
            self._stack.pop()

    def _drop_title(self, lines: list[str]) -> list[str]:
        if not self.s.drop_title:
            return lines
        for k, line in enumerate(lines):
            if line.strip():
                return lines[k + 1:] if re.match(r"^#\s", line) else lines
        return lines

    # -- 문제 노트 ------------------------------------------------------------
    def source_line(self, note: Note) -> str:
        """출처 줄: 속성으로 source_format 을 채우고, 속성이 모자라면 '# 제목' 또는 노트 이름."""
        meta = dict(note.meta)
        if meta.get("exam"):
            meta["exam"] = exam_display(str(meta["exam"]), self.s)
        needed = re.findall(r"\{(\w+)", self.s.source_format)
        if all(meta.get(k) not in (None, "") for k in needed):
            try:
                return re.sub(r"\s+", " ", self.s.source_format.format(**meta)).strip()
            except (KeyError, IndexError, ValueError):
                pass
        for line in note.body.splitlines():
            m = re.match(r"^#\s+(.*)$", line)
            if m:
                return m.group(1).strip()
        return note.name

    def problem_block(self, note: Note) -> list[str]:
        lines = _COMMENT.sub("", note.body).split("\n")
        lines = self._drop_nav_tail(self._drop_title(lines))
        stem: list[str] = []
        answer_text = ""
        solution: list[str] = []
        i = 0
        while i < len(lines):
            m = _CALLOUT.match(lines[i])
            if m and self._is_answer_callout(m.group(1), m.group(3)):
                i += 1
                inner = []
                while i < len(lines) and _QUOTE_LINE.match(lines[i]):
                    inner.append(_QUOTE_LINE.match(lines[i]).group(1))
                    i += 1
                for x in inner:
                    am = _ANSWER_LINE.match(x)
                    if am and not answer_text:
                        answer_text = am.group(1).strip()
                        continue
                    solution.append(x)
                continue
            stem.append(lines[i])
            i += 1
        meta_answer = note.meta.get("answer")
        answer = str(meta_answer).strip() if meta_answer not in (None, "") else answer_text
        has_choices = any(c in "\n".join(stem) for c in _CIRCLED[:5])
        if has_choices and re.fullmatch(r"[1-9]", answer or ""):
            answer = _CIRCLED[int(answer) - 1]
        while stem and not stem[-1].strip():
            stem.pop()
        while solution and not solution[0].strip():
            solution.pop(0)
        out = ["", f"::: 문제 {self.source_line(note)}", *self.expand_lines(stem, note.path)]
        if answer:
            out.append(f"[정답] {answer}")
        body = self.expand_lines(solution, note.path)
        if any(x.strip() for x in body):
            out += ["[해설]", *body]
        out += [":::", ""]
        return out

    # -- 속성으로 모으기 ---------------------------------------------------------
    def query(self, spec: str, near: Path) -> list[str]:
        try:
            tokens = shlex.split(spec)
        except ValueError as exc:
            self.warnings.append(f"\\문제모음 조건을 읽지 못함: {spec} ({exc})")
            return []
        conds, sort_keys, limit = [], ["year", "exam", "number"], None
        for tok in tokens:
            m = re.match(r"^([\w.-]+)\s*(>=|<=|!=|=|>|<|~)\s*(.*)$", tok)
            if not m:
                self.warnings.append(f"\\문제모음 조건 형식이 이상함: {tok} (예: subject=기하 year>=2024)")
                continue
            key, op, value = m.groups()
            if key == "sort":
                sort_keys = [k.strip() for k in value.split(",") if k.strip()]
            elif key == "limit":
                limit = int(value) if value.isdigit() else None
            else:
                conds.append((key, op, value))
        notes = [n for n in self.vault.notes() if n.path.resolve() not in self._stack and self.is_problem(n)
                 and all(_match(n.meta, k, op, v) for k, op, v in conds)]

        def sort_value(n: Note, key: str):
            v = n.meta.get(key.lstrip("-"))
            if key.lstrip("-") == "exam":
                v = _exam_order(str(v or ""))
            if isinstance(v, (int, float)):
                return (0, v, "")
            return (1, 0, str(v or ""))

        for key in reversed(sort_keys):
            notes.sort(key=lambda n: sort_value(n, key), reverse=key.startswith("-"))
        if limit:
            notes = notes[:limit]
        if not notes:
            self.warnings.append(f"\\문제모음 {spec}: 맞는 문제 노트가 없습니다")
        out: list[str] = []
        for n in notes:
            self._stack.append(n.path.resolve())
            try:
                out.extend(self.problem_block(n))
            finally:
                self._stack.pop()
        return out

    # -- 책 ------------------------------------------------------------------
    def build(self, path: Path) -> tuple[str, dict]:
        """책 노트(또는 문제 노트 하나)를 펼친 원고와 책 노트 속성."""
        note = self.vault.read(path)
        self._stack.append(path.resolve())
        try:
            if self.is_problem(note):
                lines = self.problem_block(note)
            else:
                lines = self.expand_lines(_COMMENT.sub("", note.body).split("\n"), note.path)
        finally:
            self._stack.pop()
        return "\n".join(lines), note.meta


def _match(meta: dict, key: str, op: str, value: str) -> bool:
    actual = meta.get(key)
    if actual is None:
        return op == "!="
    values = actual if isinstance(actual, list) else [actual]

    def one(a) -> bool:
        a_text = str(a)
        if op == "~":
            return value in a_text
        try:
            a_num, v_num = float(a), float(value)
            numeric = True
        except (TypeError, ValueError):
            numeric = False
        if op in ("=", "!="):
            eq = (a_num == v_num) if numeric else (a_text == value or a_text.startswith(value + "/"))
            return eq if op == "=" else not eq
        if not numeric:
            return False
        return {">": a_num > v_num, "<": a_num < v_num, ">=": a_num >= v_num, "<=": a_num <= v_num}[op]

    if op == "!=":
        return all(one(a) for a in values)
    return any(one(a) for a in values)


def expand_note(path: str | Path, *, vault: str | Path | None = None, box_names: set[str] | None = None,
                settings: ObsidianSettings | None = None) -> tuple[str, dict, list[str]]:
    """책 노트 경로 → (펼친 원고, 책 노트 속성, 경고)."""
    path = Path(path).resolve()
    root = Path(vault) if vault else (find_vault_root(path) or path.parent)
    builder = BookBuilder(Vault(root), box_names=box_names, settings=settings)
    text, meta = builder.build(path)
    return text, meta, builder.warnings
