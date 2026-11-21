"""단위 변환 도우미.

한글(HWPX)의 기본 길이 단위는 HWPUNIT 이다.
  * 1 pt   = 100 HWPUNIT
  * 1 inch = 7200 HWPUNIT
  * 1 mm   = 7200 / 25.4 ≈ 283.46 HWPUNIT
글자 크기(charPr height)도 pt × 100 으로 저장된다 (10pt → 1000).
"""

from __future__ import annotations

HWPUNIT_PER_INCH = 7200
HWPUNIT_PER_PT = 100

#: 그림의 픽셀 크기를 HWPUNIT 으로 바꿀 때 가정하는 해상도.
DEFAULT_DPI = 96


def mm(value: float) -> int:
    """밀리미터 → HWPUNIT."""
    return round(value * HWPUNIT_PER_INCH / 25.4)


def pt(value: float) -> int:
    """포인트 → HWPUNIT."""
    return round(value * HWPUNIT_PER_PT)


def px(value: float, dpi: float = DEFAULT_DPI) -> int:
    """픽셀 → HWPUNIT (기본 96 DPI)."""
    return round(value * HWPUNIT_PER_INCH / dpi)


#: 용지 크기 (가로 mm, 세로 mm)
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "B4": (257, 364),
    "B5": (182, 257),
    "LETTER": (215.9, 279.4),
    "LEGAL": (215.9, 355.6),
}
