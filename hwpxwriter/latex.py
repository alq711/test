"""LaTeX 수식 → 한글 수식(EqEdit 스크립트) 변환과 수식 상자 크기 추정.

한글 수식 편집기는 ``{a} over {b}``, ``sqrt {x}``, ``sum _{k=1} ^{n}`` 같은 자체 문법(스크립트)을
<hp:script> 에 저장한다. 이 모듈은 LaTeX 를 그 문법으로 옮기고, 동시에 결과의 대략적인 크기
(너비·높이·기준선)를 계산한다. Windows 판 한글은 파일에 저장된 상자 크기로 줄을 배치하므로
크기를 너무 작게 잡으면 뒤 글자와 겹치고, 너무 크게 잡으면 빈틈이 생긴다. 그래서 조금 넉넉하게 잡는다.

LaTeX 명령 → 한글 수식 키워드 대응은 한글에서 실제로 그려 확인된 철자를 따른다
(예: ``\\to`` → ``->``, ``\\forall`` → ``FORALL``, ``\\perp`` → ``BOT``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 대응표
# ---------------------------------------------------------------------------

_GREEK_LOWER = (
    "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi "
    "pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega"
).split()
_GREEK_UPPER = "Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega".split()

# (한글 수식 철자, 종류)  종류: ord(보통 글자) bin(이항 연산) rel(관계) op(큰 연산자) fn(함수) punct
_SYMBOLS: dict[str, tuple[str, str]] = {
    # 이항 연산
    "pm": ("+-", "bin"), "mp": ("-+", "bin"), "times": ("times", "bin"), "div": ("div", "bin"),
    "cdot": ("cdot", "bin"), "ast": ("ast", "bin"), "star": ("star", "bin"), "circ": ("circ", "bin"),
    "bullet": ("bullet", "bin"), "oplus": ("oplus", "bin"), "otimes": ("otimes", "bin"),
    "cup": ("cup", "bin"), "cap": ("cap", "bin"), "setminus": ("-", "bin"), "land": ("land", "bin"),
    "lor": ("lor", "bin"), "wedge": ("land", "bin"), "vee": ("lor", "bin"),
    # 관계
    "leq": ("leq", "rel"), "le": ("leq", "rel"), "leqq": ("leq", "rel"), "leqslant": ("leq", "rel"),
    "geq": ("geq", "rel"), "ge": ("geq", "rel"), "geqq": ("geq", "rel"), "geqslant": ("geq", "rel"),
    "neq": ("neq", "rel"), "ne": ("neq", "rel"), "equiv": ("equiv", "rel"), "approx": ("approx", "rel"),
    "sim": ("sim", "rel"), "simeq": ("simeq", "rel"), "cong": ("cong", "rel"), "propto": ("propto", "rel"),
    "ll": ("ll", "rel"), "gg": ("gg", "rel"), "in": ("in", "rel"), "notin": ("notin", "rel"),
    "subset": ("subset", "rel"), "subseteq": ("subseteq", "rel"), "supset": ("supset", "rel"),
    "supseteq": ("supseteq", "rel"), "mid": ("~|~", "rel"), "parallel": ("parallel", "rel"),
    "perp": ("BOT", "rel"),
    "to": ("->", "rel"), "rightarrow": ("->", "rel"), "longrightarrow": ("->", "rel"),
    "leftarrow": ("<-", "rel"), "gets": ("<-", "rel"), "longleftarrow": ("<-", "rel"),
    "leftrightarrow": ("<->", "rel"), "longleftrightarrow": ("<->", "rel"),
    "Rightarrow": ("Rightarrow", "rel"), "Longrightarrow": ("Rightarrow", "rel"), "implies": ("Rightarrow", "rel"),
    "Leftarrow": ("Leftarrow", "rel"), "Longleftarrow": ("Leftarrow", "rel"), "impliedby": ("Leftarrow", "rel"),
    "Leftrightarrow": ("LRARROW", "rel"), "Longleftrightarrow": ("LRARROW", "rel"), "iff": ("LRARROW", "rel"),
    "mapsto": ("mapsto", "rel"), "uparrow": ("uparrow", "rel"), "downarrow": ("downarrow", "rel"),
    "Uparrow": ("UPARROW", "rel"), "nearrow": ("NEARROW", "rel"), "searrow": ("SEARROW", "rel"),
    "rightleftharpoons": ("EXARROW", "rel"), "colon": (":", "punct"),
    # 보통 기호
    "infty": ("inf", "ord"), "partial": ("partial", "ord"), "nabla": ("nabla", "ord"),
    "angle": ("angle", "ord"), "triangle": ("TRIANGLE", "ord"), "therefore": ("therefore", "ord"),
    "because": ("because", "ord"), "emptyset": ("emptyset", "ord"), "varnothing": ("emptyset", "ord"),
    "forall": ("FORALL", "ord"), "exists": ("exists", "ord"), "neg": ("neg", "ord"), "lnot": ("neg", "ord"),
    "prime": ("prime", "ord"), "cdots": ("cdots", "ord"), "ldots": ("ldots", "ord"), "dots": ("cdots", "ord"),
    "vdots": ("vdots", "ord"), "ddots": ("ddots", "ord"), "hbar": ("hbar", "ord"), "ell": ("ell", "ord"),
    "vert": ("|", "ord"), "lvert": ("|", "ord"), "rvert": ("|", "ord"), "Vert": ("VERT", "ord"),
    "|": ("VERT", "ord"), "lVert": ("VERT", "ord"), "rVert": ("VERT", "ord"),
    "{": ("LBRACE", "ord"), "}": ("RBRACE", "ord"), "lbrace": ("LBRACE", "ord"), "rbrace": ("RBRACE", "ord"),
    "langle": ("LANGLE", "ord"), "rangle": ("RANGLE", "ord"),
    "lfloor": ("lfloor", "ord"), "rfloor": ("rfloor", "ord"), "lceil": ("lceil", "ord"), "rceil": ("rceil", "ord"),
    "%": ("%", "ord"), "$": ('"$"', "ord"), "#": ('"#"', "ord"), "&": ('"&"', "ord"), "_": ('"_"', "ord"),
    "backslash": ('"\\"', "ord"), "square": ("box {~}", "ord"), "Box": ("box {~}", "ord"),
    "degree": ("circ", "ord"),
    # 큰 연산자
    "sum": ("sum", "op"), "prod": ("prod", "op"), "coprod": ("coprod", "op"), "int": ("int", "op"),
    "iint": ("dint", "op"), "iiint": ("tint", "op"), "oint": ("oint", "op"), "bigcup": ("bigcup", "op"),
    "bigcap": ("bigcap", "op"), "lim": ("lim", "op"),
}
for _g in _GREEK_LOWER:
    _SYMBOLS[_g] = (_g, "ord")
for _g in _GREEK_UPPER:
    _SYMBOLS[_g] = (_g.upper(), "ord")
_SYMBOLS["varGamma"] = ("GAMMA", "ord")

_FUNCTIONS = set(
    "sin cos tan cot sec csc sinh cosh tanh arcsin arccos arctan log ln lg exp det dim gcd max min mod bmod".split()
)
_ACCENTS = {
    "vec": "vec", "overrightarrow": "vec", "bar": "bar", "overline": "overline", "underline": "underline",
    "hat": "hat", "widehat": "hat", "tilde": "tilde", "widetilde": "tilde", "dot": "dot", "ddot": "ddot",
    "acute": "acute", "grave": "grave", "check": "check", "breve": "breve", "overleftrightarrow": "dyad",
    "overarc": "arch", "wideparen": "arch", "boxed": "box",
}
_SPACES = {",": "`", ":": "~", ";": "~", " ": "~", "quad": "~~", "qquad": "~~~~", "!": "", "enspace": "~",
           "thinspace": "`", "medspace": "~", "thickspace": "~"}
_IGNORED = set(
    "displaystyle textstyle scriptstyle scriptscriptstyle limits nolimits big Big bigg Bigg bigl bigr Bigl Bigr "
    "biggl biggr Biggl Biggr bigm Bigm left right nonumber notag".split()
)
_TEXT_CMDS = {"text", "textrm", "mbox", "textnormal", "hbox", "textit", "textbf"}
_FONT_CMDS = {"mathrm": "rm", "operatorname": "rm", "mathbb": "rm", "mathcal": "rm", "mathsf": "rm",
              "mathbf": "bold", "boldsymbol": "bold", "bm": "bold", "mathit": "it", "mathscr": "rm"}
_MATRIX_ENVS = {"matrix": "matrix", "pmatrix": "pmatrix", "bmatrix": "bmatrix", "Bmatrix": "matrix",
                "vmatrix": "dmatrix", "Vmatrix": "dmatrix", "smallmatrix": "matrix", "array": "matrix",
                "cases": "cases", "aligned": "eqalign", "align": "eqalign", "align*": "eqalign",
                "gathered": "eqalign", "gather": "eqalign", "gather*": "eqalign", "split": "eqalign",
                "eqnarray": "eqalign", "eqnarray*": "eqalign", "alignat": "eqalign", "alignedat": "eqalign"}
_DELIMS = {"(": "(", ")": ")", "[": "[", "]": "]", "|": "|", ".": ".", "/": "/", "\\{": "{", "\\}": "}",
           "\\lbrace": "{", "\\rbrace": "}", "\\langle": "<", "\\rangle": ">", "\\lfloor": "lfloor",
           "\\rfloor": "rfloor", "\\lceil": "lceil", "\\rceil": "rceil", "\\|": "||", "\\vert": "|",
           "\\lvert": "|", "\\rvert": "|", "\\Vert": "||", "<": "<", ">": ">"}
_UNICODE = {"×": "\\times", "÷": "\\div", "±": "\\pm", "∓": "\\mp", "≤": "\\leq", "≥": "\\geq", "≠": "\\neq",
            "→": "\\to", "←": "\\leftarrow", "↔": "\\leftrightarrow", "⇒": "\\Rightarrow", "⇔": "\\iff",
            "∞": "\\infty", "−": "-", "·": "\\cdot", "⋯": "\\cdots", "…": "\\ldots", "△": "\\triangle",
            "∠": "\\angle", "⊥": "\\perp", "∥": "\\parallel", "∈": "\\in", "∉": "\\notin", "⊂": "\\subset",
            "⊃": "\\supset", "⊆": "\\subseteq", "⊇": "\\supseteq", "∪": "\\cup", "∩": "\\cap", "∅": "\\emptyset",
            "∴": "\\therefore", "∵": "\\because", "≈": "\\approx", "≡": "\\equiv", "∼": "\\sim", "∝": "\\propto",
            "∀": "\\forall", "∃": "\\exists", "∂": "\\partial", "∑": "\\sum", "∫": "\\int", "π": "\\pi",
            "θ": "\\theta", "α": "\\alpha", "β": "\\beta", "°": "\\degree", "′": "'"}

# ---------------------------------------------------------------------------
# 크기 (em, 글자 크기 1 = 1em)
# ---------------------------------------------------------------------------


@dataclass
class Box:
    w: float = 0.0
    a: float = 0.72  # 기준선 위
    d: float = 0.2  # 기준선 아래

    @property
    def h(self) -> float:
        return self.a + self.d


def _hbox(boxes: list[Box]) -> Box:
    if not boxes:
        return Box(0, 0.72, 0.2)
    return Box(sum(b.w for b in boxes), max(b.a for b in boxes), max(b.d for b in boxes))


_NARROW = set("fijlrt")
_WIDE = set("mw")


def _letter_w(ch: str, upright: bool = False) -> float:
    if ch.isdigit():
        return 0.5
    if ch.isascii() and ch.isalpha():
        if ch.isupper():
            return 0.95 if ch in "MW" else 0.48 if ch in "IJ" else 0.74
        return 0.85 if ch in _WIDE else 0.36 if ch in _NARROW else (0.52 if upright else 0.56)
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    if ch == " ":
        return 0.3
    return 0.5


_KIND_W = {"bin": 0.62 + 0.36, "rel": 0.7 + 0.5, "punct": 0.3 + 0.2}
_GLYPH_W = {"->": 1.1, "<-": 1.1, "<->": 1.3, "Rightarrow": 1.1, "Leftarrow": 1.1, "LRARROW": 1.3,
            "mapsto": 1.1, "EXARROW": 1.2, "~|~": 0.6, "cdots": 1.0, "ldots": 1.0, "inf": 0.75,
            "VERT": 0.35, "LBRACE": 0.45, "RBRACE": 0.45, "LANGLE": 0.4, "RANGLE": 0.4,
            "lfloor": 0.35, "rfloor": 0.35, "lceil": 0.35, "rceil": 0.35, "%": 0.8, "TRIANGLE": 0.8,
            "angle": 0.8, "therefore": 0.7, "because": 0.7, "emptyset": 0.6, "box {~}": 0.8}


# ---------------------------------------------------------------------------
# 결과
# ---------------------------------------------------------------------------


@dataclass
class Atom:
    script: str
    box: Box
    kind: str = "ord"  # ord / bin / rel / op / fn / punct / open / close / compound


@dataclass
class Equation:
    """변환 결과."""

    script: str
    width: float  # em
    ascent: float
    descent: float
    warnings: list[str] = field(default_factory=list)

    def size(self, base_unit: int) -> tuple[int, int, int]:
        """(너비, 높이, baseLine%) — base_unit 은 1/100 pt (10pt = 1000)."""
        a = max(self.ascent, 0.78)
        d = max(self.descent, 0.22)
        width = round((self.width * 1.08 + 0.15) * base_unit)
        height = round((a + d) * base_unit)
        return max(width, 100), max(height, 100), round(a / (a + d) * 100)


class LatexError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 토큰
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"\\([A-Za-z]+\*?|.)|(\s+)|(.)", re.S)


def _tokenize(src: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.finditer(src):
        if m.group(1) is not None:
            out.append("\\" + m.group(1))
        elif m.group(2) is not None:
            out.append(" ")
        else:
            ch = m.group(3)
            if ch in _UNICODE:
                rep = _UNICODE[ch]
                out.append(rep)
                if rep == "\\degree":
                    out[-1:] = ["^", "\\circ"]
            else:
                out.append(ch)
    return out


class _Parser:
    def __init__(self, src: str) -> None:
        self.t = _tokenize(src)
        self.i = 0
        self.warnings: list[str] = []

    # -- 도우미 -----------------------------------------------------------
    def peek(self, skip_space: bool = True) -> str | None:
        j = self.i
        while skip_space and j < len(self.t) and self.t[j] == " ":
            j += 1
        return self.t[j] if j < len(self.t) else None

    def next(self, skip_space: bool = True) -> str | None:
        while skip_space and self.i < len(self.t) and self.t[self.i] == " ":
            self.i += 1
        if self.i >= len(self.t):
            return None
        tok = self.t[self.i]
        self.i += 1
        return tok

    def raw_group(self) -> str:
        """{...} 안의 원문 (\\text 용)."""
        if self.peek() != "{":
            tok = self.next()
            return "" if tok is None else tok.lstrip("\\")
        self.next()
        depth, buf = 1, []
        while self.i < len(self.t):
            tok = self.t[self.i]
            self.i += 1
            if tok == "{":
                depth += 1
            elif tok == "}":
                depth -= 1
                if depth == 0:
                    break
            buf.append(tok[1:] if tok.startswith("\\") and len(tok) == 2 and not tok[1].isalpha() else tok)
        return "".join(buf)

    def optional_arg(self) -> list[Atom] | None:
        if self.peek() != "[":
            return None
        self.next()
        return self.parse_list({"]"})

    def argument(self) -> list[Atom]:
        """명령의 인자: {묶음} 또는 토큰 하나."""
        tok = self.peek()
        if tok is None:
            return []
        if tok == "{":
            self.next()
            return self.parse_list({"}"})
        if tok.isdigit():  # x^23 은 x² 다음 3
            self.next()
            return [Atom(tok, Box(0.5))]
        return self.parse_list(set(), single=True)

    # -- 구문 ------------------------------------------------------------
    def parse_list(self, stop: set[str], single: bool = False) -> list[Atom]:
        atoms: list[Atom] = []
        while True:
            tok = self.peek()
            if tok is None:
                if stop - {"$end"}:
                    if "}" in stop:
                        self.warnings.append("닫는 중괄호 } 가 없습니다")
                return atoms
            if tok in stop:
                self.next()
                return atoms
            if tok in ("^", "_"):
                self.next()
                self._script(atoms, tok)
                if single:
                    return atoms
                continue
            if tok == "\\right" or tok == "\\end" or tok in ("&", "\\\\"):
                return atoms  # 바깥에서 처리
            atom = self.parse_atom()
            if atom is not None:
                if isinstance(atom, list):
                    atoms.extend(atom)
                else:
                    atoms.append(atom)
            if single and atoms:
                # 단일 인자 뒤에 첨자가 붙는 경우는 바깥 목록이 처리
                return atoms

    def _script(self, atoms: list[Atom], kind: str) -> None:
        arg = self.argument()
        script, box = _join(arg)
        base = atoms.pop() if atoms else Atom("{}", Box(0, 0.72, 0.2))
        s = 0.7
        b = base.box
        if base.kind == "op" and base.script in ("sum", "prod", "coprod", "bigcup", "bigcap", "lim"):
            # 위아래 첨자
            w = max(b.w, box.w * s)
            if kind == "^":
                nb = Box(w, b.a + box.h * s + 0.05, b.d)
            else:
                nb = Box(w, b.a, b.d + box.h * s + 0.05)
        elif kind == "^":
            nb = Box(b.w + box.w * s + 0.06, max(b.a, 0.42 + box.h * s), b.d)
        else:
            nb = Box(b.w + box.w * s + 0.06, b.a, max(b.d, box.h * s - 0.2))
        base_script = base.script
        if base.kind == "compound":
            base_script = "{" + base_script + "}"
        # 같은 원자에 ^ 와 _ 가 모두 붙는 경우: x_{1}^{2} → 너비는 큰 쪽만
        if "^{" in base_script or "_{" in base_script:
            if (kind == "^" and "_{" in base_script and "^{" not in base_script) or (
                kind == "_" and "^{" in base_script and "_{" not in base_script
            ):
                nb.w = b.w + max(0.0, box.w * s - _last_script_w(base))
        new_kind = "op" if base.kind == "op" else ("compound" if base.kind == "compound" else "ord")
        atoms.append(Atom(f"{base_script} {kind}{{{script}}}", nb, new_kind))
        atoms[-1]._script_w = box.w * s  # type: ignore[attr-defined]

    def parse_atom(self) -> Atom | list[Atom] | None:
        tok = self.next()
        if tok is None:
            return None
        if tok == " ":
            return None
        if tok == "{":
            inner = self.parse_list({"}"})
            script, box = _join(inner)
            return Atom("{" + script + "}" if script else "{}", box, "ord")
        if tok == "}":
            self.warnings.append("짝이 없는 } 를 무시했습니다")
            return None
        if tok.startswith("\\") and len(tok) > 1:
            return self.command(tok[1:])
        return self.char(tok)

    def char(self, ch: str) -> Atom | None:
        if ch.isdigit() or ch == ".":
            buf = ch
            while self.i < len(self.t) and (self.t[self.i].isdigit() or (self.t[self.i] == "." and buf[-1].isdigit())):
                buf += self.t[self.i]
                self.i += 1
            return Atom(buf, Box(sum(0.5 if c.isdigit() else 0.25 for c in buf)))
        if ch.isascii() and ch.isalpha():
            return Atom(ch, Box(_letter_w(ch)))
        if ch in "+-*":
            sym = "ast" if ch == "*" else ch
            return Atom(sym, Box(_KIND_W["bin"]), "bin")
        if ch in "=<>":
            # <= 처럼 이어 붙여 쓰는 경우
            nxt = self.t[self.i] if self.i < len(self.t) else ""
            if ch in "<>" and nxt == "=":
                self.i += 1
                return Atom("leq" if ch == "<" else "geq", Box(_KIND_W["rel"]), "rel")
            return Atom(ch, Box(_KIND_W["rel"]), "rel")
        if ch in ",;":
            return Atom(ch, Box(_KIND_W["punct"]), "punct")
        if ch == ":":
            return Atom(":", Box(0.55), "rel")
        if ch in "()[]":
            return Atom(ch, Box(0.4, 0.78, 0.25), "open" if ch in "([" else "close")
        if ch == "|":
            return Atom("|", Box(0.3, 0.78, 0.25))
        if ch == "/":
            return Atom("/", Box(0.5))
        if ch in "!?":
            return Atom(ch, Box(0.35))
        if ch == "'":
            return Atom("'", Box(0.25))
        if ch == "~":
            return Atom("~", Box(0.33))
        if ch == "&":
            return Atom("&", Box(0))
        if ch == "#":
            return Atom('"#"', Box(0.6))
        if ch == '"':
            return Atom("\"''\"", Box(0.3))
        if ch == "`":
            return Atom("`", Box(0.17))
        # 그 밖의 글자 (한글 등) — 따옴표로 감싸 글자 그대로
        return Atom(f'"{ch}"', Box(_letter_w(ch)))

    def command(self, name: str) -> Atom | list[Atom] | None:
        if name in _IGNORED and name not in ("left", "right"):
            return None
        if name in _SPACES:
            sp = _SPACES[name]
            return Atom(sp, Box(0.17 if sp == "`" else 0.33 * len(sp))) if sp else None
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            num, nbox = _join(self.argument())
            den, dbox = _join(self.argument())
            w = max(nbox.w, dbox.w) + 0.3
            return Atom(f"{{{num}}} over {{{den}}}", Box(w, 0.3 + 0.12 + nbox.h, max(0.0, dbox.h + 0.12 - 0.3)),
                        "compound")
        if name in ("binom", "dbinom", "tbinom"):
            num, nbox = _join(self.argument())
            den, dbox = _join(self.argument())
            w = max(nbox.w, dbox.w) + 0.9
            return Atom(f"left ( {{{num}}} atop {{{den}}} right )",
                        Box(w, 0.3 + 0.1 + nbox.h, max(0.0, dbox.h + 0.1 - 0.3)), "compound")
        if name == "sqrt":
            index = self.optional_arg()
            inner, ibox = _join(self.argument())
            if index:
                idx, xbox = _join(index)
                return Atom(f"root {{{idx}}} of {{{inner}}}", Box(ibox.w + 0.8 + xbox.w * 0.6, ibox.a + 0.2, ibox.d + 0.05),
                            "compound")
            return Atom(f"sqrt {{{inner}}}", Box(ibox.w + 0.8, ibox.a + 0.2, ibox.d + 0.05), "compound")
        if name in _ACCENTS:
            inner, ibox = _join(self.argument())
            return Atom(f"{_ACCENTS[name]} {{{inner}}}", Box(max(ibox.w, 0.5) + 0.05, ibox.a + 0.3, ibox.d), "compound")
        if name in _TEXT_CMDS:
            text = self.raw_group().replace('"', "''")
            if not text.strip():
                return Atom("~", Box(0.33))
            # 한글 수식은 따옴표 안 공백도 무시하므로 낱말 사이는 ~ (공백)
            words = text.split(" ")
            script = "~".join(f'"{w}"' if w else "" for w in words)
            return Atom(script, Box(sum(_letter_w(c, True) for c in text)), "ord")
        if name in _FONT_CMDS:
            style = _FONT_CMDS[name]
            arg = self.argument()
            if name == "operatorname":
                text = "".join(a.script for a in arg if a.script not in ("{", "}")).replace(" ", "")
                return Atom(f'"{text}"', Box(sum(_letter_w(c, True) for c in text) + 0.15), "fn")
            plain = all(re.fullmatch(r"[A-Za-z0-9]+", a.script) for a in arg)
            if plain and style == "rm":
                text = "".join(a.script for a in arg)
                return Atom(f"{{rm {text}}}" if text not in _SYMBOLS and text not in _FUNCTIONS else f'"{text}"',
                            Box(sum(_letter_w(c, True) for c in text)))
            inner, ibox = _join(arg)
            return Atom(f"{{{style} {inner}}}" if style != "it" else f"{{{inner}}}", ibox)
        if name == "left":
            return self.left_right()
        if name == "begin":
            return self.environment()
        if name in ("over", "atop", "choose"):
            self.warnings.append(f"\\{name} 대신 \\frac 을 쓰세요")
            return Atom(name, Box(1.0))
        if name in _FUNCTIONS:
            fn = "mod" if name == "bmod" else name
            return Atom(fn, Box(sum(_letter_w(c, True) for c in fn) + 0.2), "fn")
        if name in _SYMBOLS:
            sym, kind = _SYMBOLS[name]
            if kind in _KIND_W:
                w = _KIND_W[kind] + max(0.0, _GLYPH_W.get(sym, 0.7) - 0.7)
            elif kind == "op":
                if sym == "lim":
                    return Atom("lim", Box(1.3), "op")
                big = sym in ("sum", "prod", "coprod", "bigcup", "bigcap")
                return Atom(sym, Box(1.15 if big else 0.7, 1.05, 0.45), "op")
            else:
                w = _GLYPH_W.get(sym, 0.62)
            return Atom(sym, Box(w), kind)
        if name == "\\":
            return Atom("#", Box(0), "newline")
        if name in ("degree", "circ"):
            return Atom("circ", Box(0.5))
        self.warnings.append(f"모르는 명령 \\{name} 을(를) 글자로 넣었습니다")
        return Atom(f'"{name}"', Box(sum(_letter_w(c, True) for c in name)))

    def _delim(self) -> str:
        tok = self.next()
        if tok is None:
            return "."
        if tok in _DELIMS:
            return _DELIMS[tok]
        self.warnings.append(f"괄호로 쓸 수 없는 {tok} 를 무시했습니다")
        return "."

    def left_right(self) -> Atom:
        open_d = self._delim()
        inner = self.parse_list(set())
        close_d = "."
        if self.peek() == "\\right":
            self.next()
            close_d = self._delim()
        else:
            self.warnings.append("\\left 에 짝이 되는 \\right 가 없습니다")
        script, box = _join(inner)
        h = box.h
        dw = 0.3 + 0.1 * max(0.0, h - 1.0)
        w = box.w + (dw if open_d != "." else 0) + (dw if close_d != "." else 0)
        return Atom(f"left {open_d} {script} right {close_d}", Box(w, box.a + 0.08, box.d + 0.08), "compound")

    def environment(self) -> Atom:
        env = self.raw_group().strip()
        if env == "array" and self.peek() == "{":
            self.raw_group()  # 열 정렬 지정은 버림
        if env in ("alignat", "alignedat"):
            self.raw_group()
        kind = _MATRIX_ENVS.get(env)
        if kind is None:
            self.warnings.append(f"지원하지 않는 환경 {env} — 행렬로 처리했습니다")
            kind = "matrix"
        rows: list[list[tuple[str, Box]]] = [[]]
        while True:
            cell = self.parse_list(set())
            rows[-1].append(_join(cell))
            tok = self.next()
            if tok is None:
                self.warnings.append(f"\\end{{{env}}} 가 없습니다")
                break
            if tok == "&":
                continue
            if tok == "\\\\":
                if self.peek() == "[":  # \\[2pt]
                    self.raw_until("]")
                rows.append([])
                continue
            if tok == "\\end":
                self.raw_group()
                break
            if tok == "\\right":
                self.warnings.append("환경 안에서 \\right 를 만났습니다")
                break
        if rows and not any(s for s, _ in rows[-1]) and len(rows) > 1:
            rows.pop()
        ncols = max(len(r) for r in rows)
        col_w = [max((r[c][1].w if c < len(r) else 0) for r in rows) for c in range(ncols)]
        row_h = [max(b.h for _, b in r) + 0.3 for r in rows]
        total_h = sum(row_h)
        gap = 1.0 if kind in ("cases", "eqalign") else 0.8
        width = sum(col_w) + gap * (ncols - 1)
        if kind in ("pmatrix", "bmatrix", "dmatrix"):
            width += 0.9
        elif kind == "cases":
            width += 0.6
        body = " # ".join(" & ".join(s for s, _ in r) for r in rows)
        return Atom(f"{kind}{{{body}}}", Box(width, total_h / 2 + 0.3, max(0.2, total_h / 2 - 0.3)), "compound")

    def raw_until(self, end: str) -> None:
        while self.i < len(self.t) and self.t[self.i] != end:
            self.i += 1
        self.i += 1


def _last_script_w(atom: Atom) -> float:
    return getattr(atom, "_script_w", 0.0)


def _join(atoms: list[Atom]) -> tuple[str, Box]:
    parts: list[str] = []
    boxes: list[Box] = []
    prev: Atom | None = None
    for atom in atoms:
        if atom.kind == "newline":
            parts.append("#")
            continue
        script = atom.script
        # 글자 낱낱이 띄어 써서 'in', 'pi' 같은 예약어로 읽히지 않게 한다
        if prev is not None and atom.kind == "bin" and prev.kind in ("bin", "rel", "open", "punct", "op"):
            # 단항 부호(-x)는 간격이 좁다
            boxes.append(Box(0.6))
        else:
            boxes.append(atom.box)
        parts.append(script)
        prev = atom
    if atoms and atoms[0].kind == "bin" and boxes:
        boxes[0] = Box(0.6)
    box = _hbox(boxes)
    return " ".join(p for p in parts if p != ""), box


def latex_to_hwp(latex: str) -> Equation:
    """LaTeX 수식(달러 기호 없이)을 한글 수식으로 바꾼다."""
    src = latex.strip()
    if not src:
        return Equation("", 0, 0.72, 0.2)
    p = _Parser(src)
    atoms: list[Atom] = []
    while p.i < len(p.t):
        atoms.extend(p.parse_list(set()))
        tok = p.next()
        if tok is None:
            break
        if tok == "\\\\":
            atoms.append(Atom("#", Box(0), "newline"))
        elif tok == "&":
            atoms.append(Atom("&", Box(0)))
        elif tok == "\\right":
            p.warnings.append("짝이 없는 \\right 를 무시했습니다")
            p._delim()
        elif tok == "\\end":
            p.raw_group()
            p.warnings.append("짝이 없는 \\end 를 무시했습니다")
    script, box = _join(atoms)
    # 여러 줄(\\)이면 줄 수만큼 높이
    lines = script.count(" # ") + 1 if "#" in [a.script for a in atoms] else 1
    if lines > 1:
        box = Box(box.w, box.a + (lines - 1) * 1.3 / 2, box.d + (lines - 1) * 1.3 / 2)
    return Equation(script, box.w, box.a, box.d, p.warnings)
