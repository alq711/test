"""글자 모양(charPr), 문단 모양(paraPr), 테두리/배경(borderFill) 관리와 header.xml 생성.

HWPX 문서에서 본문(section0.xml)의 문단과 글자는 서식을 직접 들고 있지 않고,
header.xml 에 정의된 서식 목록의 번호(IDRef)만 참조한다. 이 모듈은 문서를 만드는 동안
필요한 서식 조합을 모아 번호를 매기고(같은 조합은 같은 번호 재사용), 마지막에 header.xml
한 벌을 만들어 낸다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from .xmlns import NS_DECL

_LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
_LANG_ATTRS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")

ALIGNMENTS = {"JUSTIFY", "LEFT", "RIGHT", "CENTER", "DISTRIBUTE"}


def _all_langs(value: object) -> str:
    return " ".join(f'{name}="{value}"' for name in _LANG_ATTRS)


def _clamp(value: object, low: int, high: int) -> int:
    return max(low, min(high, round(float(value))))  # type: ignore[arg-type]


_HFT_PREFIXES = ("한양", "신명 ", "#")
_HFT_NAMES = {"명조", "고딕", "샘물", "필기", "시스템", "옛한글", "중고딕", "태고딕", "견명조", "견고딕"}


def font_type(name: str) -> str:
    """한글에 들어 있는 HFT 글꼴(한양신명조, 신명 중명조, #태고딕 …)은 HFT, 나머지는 TTF."""
    return "HFT" if name.startswith(_HFT_PREFIXES) or name in _HFT_NAMES else "TTF"


def normalize_align(value: str | None, default: str = "JUSTIFY") -> str:
    if not value:
        return default
    upper = value.strip().upper()
    aliases = {"BOTH": "JUSTIFY", "MIDDLE": "CENTER", "CENTRE": "CENTER"}
    upper = aliases.get(upper, upper)
    if upper not in ALIGNMENTS:
        raise ValueError(f"지원하지 않는 정렬입니다: {value!r} (left/center/right/justify)")
    return upper


def normalize_color(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text.lower() == "none":
        return "none"
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:  # #abc → #aabbcc
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if len(text) != 7 or any(c not in "0123456789abcdefABCDEF" for c in text[1:]):
        raise ValueError(f"색상은 #RRGGBB 형식이어야 합니다: {value!r}")
    return text.upper()


# ---------------------------------------------------------------------------
# 서식 정의 (불변 값 객체 → dict 키로 써서 중복 제거)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharStyle:
    """글자 모양."""

    font: str = "함초롬바탕"
    size: float = 10.0  # pt
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    color: str = "#000000"
    shade: str = "none"  # 글자 배경(음영) 색
    superscript: bool = False
    subscript: bool = False
    border_fill: int = 2  # 글자 테두리 (2 = 없음)
    ratio: int | None = None  # 장평(%) — None 이면 글꼴별 설정(font_ratio)
    spacing: int | None = None  # 자간(%) — None 이면 글꼴별 설정(font_spacing)


@dataclass(frozen=True)
class Line:
    """테두리 선 하나. type: NONE, SOLID, DASH, DOT, DOUBLE_SLIM ..."""

    type: str = "NONE"
    width: str = "0.1 mm"
    color: str = "#000000"


NO_LINE = Line()


@dataclass(frozen=True)
class BorderFill:
    """테두리 + 배경 채우기."""

    left: Line = NO_LINE
    right: Line = NO_LINE
    top: Line = NO_LINE
    bottom: Line = NO_LINE
    fill: str | None = None  # 배경색 (#RRGGBB), None 이면 채우기 없음
    slash: bool = False  # 칸 대각선 '/' (왼쪽 아래 → 오른쪽 위). 수능 시험지 쪽 번호 칸 '1/20'
    diagonal: Line = Line("SOLID", "0.1 mm", "#000000")  # 대각선 모양

    @classmethod
    def box(cls, width: str = "0.12 mm", color: str = "#000000", fill: str | None = None) -> "BorderFill":
        line = Line("SOLID", width, color)
        return cls(line, line, line, line, fill)


@dataclass(frozen=True)
class ParaStyle:
    """문단 모양. 길이 값은 모두 HWPUNIT."""

    align: str = "JUSTIFY"
    indent: int = 0  # 첫 줄 들여쓰기(+) / 내어쓰기(-)
    left: int = 0
    right: int = 0
    space_before: int = 0
    space_after: int = 0
    line_spacing: int = 160  # %
    border_fill: int = 2  # borderFill id (2 = 테두리 없음)
    border_offset_left: int = 0
    border_offset_right: int = 0
    border_offset_top: int = 0
    border_offset_bottom: int = 0
    border_connect: bool = False  # 연속된 같은 테두리 문단을 하나로 이어 그림
    keep_with_next: bool = False
    keep_lines: bool = False
    break_latin_word: str = "KEEP_WORD"
    break_non_latin_word: str = "KEEP_WORD"  # 한글: KEEP_WORD = 글자 단위로 나눔 (BREAK_WORD 는 어절 단위라 양쪽 정렬 때 빈칸이 벌어짐)


@dataclass
class _StyleEntry:
    name: str
    eng_name: str
    kind: str  # PARA | CHAR
    para_pr: int
    char_pr: int


# ---------------------------------------------------------------------------
# 레지스트리
# ---------------------------------------------------------------------------


@dataclass
class StyleRegistry:
    """문서가 쓰는 모든 서식을 모아 번호를 매긴다."""

    default_char: CharStyle = field(default_factory=CharStyle)
    default_para: ParaStyle = field(default_factory=ParaStyle)
    font_ratio: dict = field(default_factory=dict)  # 글꼴 이름 → 장평(%), 예: {"함초롬바탕": 95}
    font_spacing: dict = field(default_factory=dict)  # 글꼴 이름 → 자간(%), 예: {"함초롬바탕": -3}
    # 글꼴 이름 → 언어별 글꼴. 예: {"신명 중명조": {"LATIN": "한양신명조", "SYMBOL": "한양신명조"}}
    # (한글 문서는 글자 한 벌 안에서도 한글·영문·기호마다 다른 글꼴을 쓸 수 있다. 수능 시험지:
    #  한글 = 신명 중명조, 숫자·영문·기호(? [ ] ①) = 한양신명조)
    font_lang: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._fonts: list[str] = []
        self._char: dict[CharStyle, int] = {}
        self._para: dict[ParaStyle, int] = {}
        self._border: dict[BorderFill, int] = {}
        self._styles: list[_StyleEntry] = []
        self._style_index: dict[str, int] = {}
        # id 1: 쪽 테두리용(선 없음), id 2: 글자/문단 기본(선 없음, 채우기 없음)
        self._border[BorderFill()] = 1
        self._border_page_fill_marker = BorderFill(fill="none")
        self._border[self._border_page_fill_marker] = 2
        # id 0 은 반드시 기본 서식
        self.char(self.default_char)
        self.para(self.default_para)
        self.add_style("바탕글", "Normal", para=self.default_para, char=self.default_char)

    # --- 등록 ------------------------------------------------------------
    def font(self, name: str) -> int:
        if name not in self._fonts:
            self._fonts.append(name)
        return self._fonts.index(name)

    def _lang_fonts(self, name: str) -> list[str]:
        """_LANGS 순서대로 언어별 글꼴 이름."""
        table = {str(k).upper(): v for k, v in (self.font_lang.get(name) or {}).items()}
        return [table.get(lang, name) for lang in _LANGS]

    def char(self, style: CharStyle) -> int:
        if style not in self._char:
            self.font(style.font)
            for name in self._lang_fonts(style.font):
                self.font(name)
            self._char[style] = len(self._char)
        return self._char[style]

    def para(self, style: ParaStyle) -> int:
        if style not in self._para:
            self._para[style] = len(self._para)
        return self._para[style]

    def border(self, border: BorderFill) -> int:
        if border not in self._border:
            self._border[border] = len(self._border) + 1  # borderFill id 는 1부터
        return self._border[border]

    def add_style(
        self,
        name: str,
        eng_name: str,
        *,
        para: ParaStyle | None = None,
        char: CharStyle | None = None,
        kind: str = "PARA",
    ) -> int:
        """한글의 '스타일' 목록(F6)에 나타날 스타일을 등록하고 번호를 돌려준다."""
        if name in self._style_index:
            return self._style_index[name]
        entry = _StyleEntry(
            name,
            eng_name,
            kind,
            self.para(para or self.default_para),
            self.char(char or self.default_char),
        )
        self._styles.append(entry)
        self._style_index[name] = len(self._styles) - 1
        return self._style_index[name]

    def style_id(self, name: str) -> int:
        return self._style_index.get(name, 0)

    # --- XML 생성 -----------------------------------------------------------
    def _fontfaces_xml(self) -> str:
        fonts = "".join(
            f'<hh:font id="{i}" face={quoteattr(name)} type="{font_type(name)}" isEmbedded="0">'
            '<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" '
            'strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/>'
            "</hh:font>"
            for i, name in enumerate(self._fonts)
        )
        faces = "".join(
            f'<hh:fontface lang="{lang}" fontCnt="{len(self._fonts)}">{fonts}</hh:fontface>' for lang in _LANGS
        )
        return f'<hh:fontfaces itemCnt="{len(_LANGS)}">{faces}</hh:fontfaces>'

    def _border_fills_xml(self) -> str:
        items = []
        for bf, bf_id in sorted(self._border.items(), key=lambda kv: kv[1]):
            parts = [
                f'<hh:borderFill id="{bf_id}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">',
                f'<hh:slash type="{"CENTER" if bf.slash else "NONE"}" Crooked="0" isCounter="0"/>',
                '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>',
            ]
            for tag, line in (
                ("leftBorder", bf.left),
                ("rightBorder", bf.right),
                ("topBorder", bf.top),
                ("bottomBorder", bf.bottom),
            ):
                parts.append(f'<hh:{tag} type="{line.type}" width="{line.width}" color="{line.color}"/>')
            d = bf.diagonal
            parts.append(f'<hh:diagonal type="{d.type}" width="{d.width}" color="{d.color}"/>')
            if bf.fill is not None:
                parts.append(
                    f'<hc:fillBrush><hc:winBrush faceColor="{bf.fill}" hatchColor="#999999" alpha="0"/></hc:fillBrush>'
                )
            parts.append("</hh:borderFill>")
            items.append("".join(parts))
        return f'<hh:borderFills itemCnt="{len(items)}">{"".join(items)}</hh:borderFills>'

    def _char_props_xml(self) -> str:
        items = []
        for cs, cs_id in sorted(self._char.items(), key=lambda kv: kv[1]):
            names = self._lang_fonts(cs.font)
            refs = " ".join(f'{a}="{self.font(n)}"' for a, n in zip(_LANG_ATTRS, names))

            def per_lang(table: dict, default: object, low: int, high: int) -> str:
                return " ".join(f'{a}="{_clamp(table.get(n, table.get(cs.font, default)), low, high)}"'
                                for a, n in zip(_LANG_ATTRS, names))

            height = round(cs.size * 100)
            parts = [
                f'<hh:charPr id="{cs_id}" height="{height}" textColor="{cs.color}" shadeColor="{cs.shade}" '
                f'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="{cs.border_fill}">',
                f"<hh:fontRef {refs}/>",
                f"<hh:ratio {_all_langs(_clamp(cs.ratio, 50, 200)) if cs.ratio is not None else per_lang(self.font_ratio, 100, 50, 200)}/>",
                f"<hh:spacing {_all_langs(_clamp(cs.spacing, -50, 50)) if cs.spacing is not None else per_lang(self.font_spacing, 0, -50, 50)}/>",
                f"<hh:relSz {_all_langs(100)}/>",
                f"<hh:offset {_all_langs(0)}/>",
            ]
            if cs.italic:
                parts.append("<hh:italic/>")
            if cs.bold:
                parts.append("<hh:bold/>")
            parts.append(
                f'<hh:underline type="{"BOTTOM" if cs.underline else "NONE"}" shape="SOLID" color="{cs.color}"/>'
            )
            parts.append(f'<hh:strikeout shape="{"SOLID" if cs.strike else "NONE"}" color="{cs.color}"/>')
            parts.append('<hh:outline type="NONE"/>')
            parts.append('<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/>')
            if cs.superscript:
                parts.append("<hh:supscript/>")
            elif cs.subscript:
                parts.append("<hh:subscript/>")
            parts.append("</hh:charPr>")
            items.append("".join(parts))
        return f'<hh:charProperties itemCnt="{len(items)}">{"".join(items)}</hh:charProperties>'

    @staticmethod
    def _margin_xml(ps: ParaStyle, scale: int) -> str:
        unit = ' unit="HWPUNIT"'
        # ParaStyle 은 CSS 처럼 left = 둘째 줄부터의 왼쪽 여백, indent < 0 = 첫 줄을 그만큼 왼쪽으로.
        # 한글의 '내어쓰기'는 반대로 첫 줄을 왼쪽 여백에 두고 둘째 줄부터 밀어 넣으므로 여기서 바꿔 적는다.
        left = ps.left + min(ps.indent, 0)
        return (
            "<hh:margin>"
            f'<hc:intent value="{ps.indent * scale}"{unit}/>'
            f'<hc:left value="{left * scale}"{unit}/>'
            f'<hc:right value="{ps.right * scale}"{unit}/>'
            f'<hc:prev value="{ps.space_before * scale}"{unit}/>'
            f'<hc:next value="{ps.space_after * scale}"{unit}/>'
            "</hh:margin>"
            f'<hh:lineSpacing type="PERCENT" value="{ps.line_spacing}" unit="HWPUNIT"/>'
        )

    def _para_props_xml(self) -> str:
        items = []
        for ps, ps_id in sorted(self._para.items(), key=lambda kv: kv[1]):
            # 한글은 같은 값을 두 번 적는다: HwpUnitChar 를 아는 판(case)과 옛 판(default, 값 × 2).
            items.append(
                f'<hh:paraPr id="{ps_id}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" '
                'suppressLineNumbers="0" checked="0" textDir="LTR">'
                f'<hh:align horizontal="{ps.align}" vertical="BASELINE"/>'
                '<hh:heading type="NONE" idRef="0" level="0"/>'
                f'<hh:breakSetting breakLatinWord="{ps.break_latin_word}" '
                f'breakNonLatinWord="{ps.break_non_latin_word}" widowOrphan="0" '
                f'keepWithNext="{int(ps.keep_with_next)}" keepLines="{int(ps.keep_lines)}" '
                'pageBreakBefore="0" lineWrap="BREAK"/>'
                '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
                "<hp:switch>"
                '<hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
                f"{self._margin_xml(ps, 1)}"
                "</hp:case>"
                f"<hp:default>{self._margin_xml(ps, 2)}</hp:default>"
                "</hp:switch>"
                f'<hh:border borderFillIDRef="{ps.border_fill}" offsetLeft="{ps.border_offset_left}" '
                f'offsetRight="{ps.border_offset_right}" offsetTop="{ps.border_offset_top}" '
                f'offsetBottom="{ps.border_offset_bottom}" connect="{int(ps.border_connect)}" ignoreMargin="0"/>'
                "</hh:paraPr>"
            )
        return f'<hh:paraProperties itemCnt="{len(items)}">{"".join(items)}</hh:paraProperties>'

    def _styles_xml(self) -> str:
        items = []
        for i, st in enumerate(self._styles):
            items.append(
                f'<hh:style id="{i}" type="{st.kind}" name={quoteattr(st.name)} engName={quoteattr(st.eng_name)} '
                f'paraPrIDRef="{st.para_pr}" charPrIDRef="{st.char_pr}" '
                f'nextStyleIDRef="{i if st.kind == "PARA" else 0}" langID="1042" lockForm="0"/>'
            )
        return f'<hh:styles itemCnt="{len(items)}">{"".join(items)}</hh:styles>'

    def header_xml(self, section_count: int = 1) -> str:
        """완성된 Contents/header.xml 문자열."""
        tab_props = (
            '<hh:tabProperties itemCnt="3">'
            '<hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/>'
            '<hh:tabPr id="1" autoTabLeft="1" autoTabRight="0"/>'
            '<hh:tabPr id="2" autoTabLeft="0" autoTabRight="1"/>'
            "</hh:tabProperties>"
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<hh:head {NS_DECL} version="1.5" secCnt="{section_count}">'
            '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
            "<hh:refList>"
            f"{self._fontfaces_xml()}"
            f"{self._border_fills_xml()}"
            f"{self._char_props_xml()}"
            f"{tab_props}"
            f"{_NUMBERINGS_XML}"
            f"{self._para_props_xml()}"
            f"{self._styles_xml()}"
            "</hh:refList>"
            '<hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
            '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
            '<hh:trackchageConfig flags="56"/>'
            "</hh:head>"
        )


def _numbering_xml() -> str:
    # 구역 정의(secPr)의 outlineShapeIDRef="1" 이 가리키는 기본 개요 번호 모양.
    heads = [
        (1, "DIGIT", "^1.", 0),
        (2, "HANGUL_SYLLABLE", "^2.", 0),
        (3, "DIGIT", "^3)", 0),
        (4, "HANGUL_SYLLABLE", "^4)", 0),
        (5, "DIGIT", "(^5)", 0),
        (6, "HANGUL_SYLLABLE", "(^6)", 0),
        (7, "CIRCLED_DIGIT", "^7", 1),
        (8, "CIRCLED_HANGUL_SYLLABLE", "^8", 1),
        (9, "HANGUL_JAMO", "", 0),
        (10, "ROMAN_SMALL", "", 1),
    ]
    parts = []
    for level, fmt, text, checkable in heads:
        attrs = (
            f'start="1" level="{level}" align="LEFT" useInstWidth="1" autoIndent="1" widthAdjust="0" '
            f'textOffsetType="PERCENT" textOffset="50" numFormat="{fmt}" charPrIDRef="4294967295" '
            f'checkable="{checkable}"'
        )
        parts.append(f"<hh:paraHead {attrs}>{escape(text)}</hh:paraHead>" if text else f"<hh:paraHead {attrs}/>")
    return f'<hh:numberings itemCnt="1"><hh:numbering id="1" start="0">{"".join(parts)}</hh:numbering></hh:numberings>'


_NUMBERINGS_XML = _numbering_xml()
