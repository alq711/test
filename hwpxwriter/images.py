"""그림 파일의 형식과 픽셀 크기를 외부 라이브러리 없이 읽는다 (PNG/JPEG/GIF/BMP)."""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageInfo:
    ext: str  # png / jpg / gif / bmp
    media_type: str
    width: int  # px
    height: int  # px
    dpi_x: float | None = None
    dpi_y: float | None = None


class ImageError(ValueError):
    pass


def probe(data: bytes) -> ImageInfo:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return ImageInfo("gif", "image/gif", w, h)
    if data[:2] == b"BM":
        w, h = struct.unpack("<ii", data[18:26])
        return ImageInfo("bmp", "image/bmp", abs(w), abs(h))
    raise ImageError("지원하지 않는 그림 형식입니다 (PNG, JPEG, GIF, BMP 만 가능)")


def _png(data: bytes) -> ImageInfo:
    w, h = struct.unpack(">II", data[16:24])
    dpi_x = dpi_y = None
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        if ctype == b"pHYs" and length >= 9:
            ppu_x, ppu_y, unit = struct.unpack(">IIB", data[pos + 8 : pos + 17])
            if unit == 1 and ppu_x and ppu_y:  # 미터당 픽셀
                dpi_x, dpi_y = ppu_x * 0.0254, ppu_y * 0.0254
            break
        if ctype in (b"IDAT", b"IEND"):
            break
        pos += 12 + length
    return ImageInfo("png", "image/png", w, h, dpi_x, dpi_y)


def _jpeg(data: bytes) -> ImageInfo:
    pos = 2
    dpi_x = dpi_y = None
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        segment = data[pos + 4 : pos + 2 + length]
        if marker == 0xE0 and segment[:5] == b"JFIF\x00" and len(segment) >= 12:
            unit = segment[7]
            xd, yd = struct.unpack(">HH", segment[8:12])
            if unit == 1 and xd and yd:
                dpi_x, dpi_y = float(xd), float(yd)
            elif unit == 2 and xd and yd:
                dpi_x, dpi_y = xd * 2.54, yd * 2.54
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", segment[1:5])
            return ImageInfo("jpg", "image/jpeg", w, h, dpi_x, dpi_y)
        pos += 2 + length
    raise ImageError("JPEG 크기 정보를 찾지 못했습니다")
