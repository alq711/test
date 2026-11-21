"""명령줄 도구: md2hwpx 입력.md [-o 출력.hwpx] [옵션]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, markdown_to_hwpx, text_to_hwpx
from .document import PageSetup, Theme


def _margins(value: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in value.replace(" ", "").split(",")]
    if len(parts) == 1:
        parts *= 4
    elif len(parts) == 2:
        parts = [parts[0], parts[1], parts[0], parts[1]]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("여백은 '위,오른쪽,아래,왼쪽' (mm) 형식으로 적으세요")
    return tuple(parts)  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="md2hwpx",
        description="Markdown/텍스트 파일을 한글 문서(.hwpx)로 변환합니다.",
        epilog="예) md2hwpx 보고서.md --page-number --header '2026년 업무 보고'",
    )
    p.add_argument("inputs", nargs="*", help="입력 파일 (.md / .txt). '-' 는 표준입력")
    p.add_argument("-o", "--output", help="출력 파일 또는 폴더 (기본: 입력과 같은 이름 .hwpx)")
    p.add_argument("--text", action="store_true", help="Markdown 해석 없이 일반 텍스트로 처리 (.txt 는 자동)")
    p.add_argument("--title", default="", help="문서 정보의 제목")

    g = p.add_argument_group("교재 양식")
    g.add_argument("-t", "--template", metavar="양식.toml",
                   help="교재 양식 파일로 변환 (문제·상자·정답과 해설). 내장 양식: 기본(=수학교재), 수능파이널")
    g.add_argument("--vault", metavar="볼트 폴더",
                   help="Obsidian 볼트 폴더 (![[노트]] 와 그림을 찾을 곳). 노트가 볼트 안에 있으면 자동으로 찾음")
    g.add_argument("--init-template", metavar="경로.toml",
                   help="고쳐 쓸 수 있는 양식 파일을 만들고 끝냄 (--template 으로 바탕 양식 선택)")

    g = p.add_argument_group("머리말·꼬리말")
    g.add_argument("--header", help="머리말 글자 ({page}=쪽 번호, {total}=전체 쪽 수)")
    g.add_argument("--footer", help="꼬리말 글자 (예: '- {page} -', '{page} / {total}')")
    g.add_argument("--page-number", action="store_true", help="꼬리말 가운데에 '- 쪽번호 -' 넣기")

    g = p.add_argument_group("용지")
    g.add_argument("--paper", default="A4", help="A4, A3, A5, B4, B5, LETTER, LEGAL 또는 '가로x세로' mm (기본 A4)")
    g.add_argument("--landscape", action="store_true", help="가로 방향")
    g.add_argument("--margin", type=_margins, help="여백 mm: '위,오른쪽,아래,왼쪽' 또는 하나의 값 (기본 20,30,15,30)")

    g = p.add_argument_group("글꼴")
    g.add_argument("--font", default="함초롬바탕", help="본문 글꼴 (기본 함초롬바탕)")
    g.add_argument("--heading-font", default="함초롬돋움", help="제목 글꼴 (기본 함초롬돋움)")
    g.add_argument("--code-font", default="굴림체", help="코드 글꼴 (기본 굴림체)")
    g.add_argument("--font-size", type=float, default=10.0, help="본문 글자 크기 pt (기본 10)")
    g.add_argument("--line-spacing", type=int, default=160, help="줄 간격 %% (기본 160)")
    g.add_argument("--paragraph-spacing", type=float, default=4.0, help="문단 뒤 간격 pt (기본 4)")

    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _page_setup(args: argparse.Namespace) -> PageSetup:
    paper: str | tuple[float, float] = args.paper
    if "x" in args.paper.lower():
        w, h = args.paper.lower().split("x")
        paper = (float(w), float(h))
    page = PageSetup(paper=paper, landscape=args.landscape)
    if args.margin:
        page.margin_top, page.margin_right, page.margin_bottom, page.margin_left = args.margin
    return page


def _in_vault(path: Path) -> bool:
    from .obsidian import find_vault_root

    return find_vault_root(path) is not None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.init_template:
        from .textbook import write_default_template

        try:
            made = write_default_template(args.init_template, base=args.template)
        except OSError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 2
        print(f"양식 파일을 만들었습니다: {made}")
        return 0
    if not args.inputs:
        parser.error("입력 파일을 적어 주세요")
    template = None
    if args.template:
        from .textbook import load_template

        try:
            template = load_template(args.template)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"오류: 양식을 읽지 못했습니다 — {exc}", file=sys.stderr)
            return 2
    theme = Theme(
        body_font=args.font,
        heading_font=args.heading_font,
        code_font=args.code_font,
        font_size=args.font_size,
        line_spacing=args.line_spacing,
        paragraph_spacing=args.paragraph_spacing,
    )
    try:
        page = _page_setup(args)
        page.size_mm()
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    out_dir: Path | None = None
    if args.output and (len(args.inputs) > 1 or Path(args.output).is_dir()):
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)

    status = 0
    for name in args.inputs:
        try:
            if name == "-":
                source = sys.stdin.read()
                src_path = Path("stdin.md")
                base_dir = Path.cwd()
            else:
                src_path = Path(name)
                source = src_path.read_text(encoding="utf-8-sig")
                base_dir = src_path.resolve().parent
            if out_dir is not None:
                target = out_dir / (src_path.stem + ".hwpx")
            elif args.output:
                target = Path(args.output)
            else:
                target = src_path.with_suffix(".hwpx")

            common = dict(
                page=page,
                theme=theme,
                title=args.title or src_path.stem,
                header=args.header,
                footer=args.footer,
                page_number=args.page_number,
            )
            obsidian_mode = (
                name != "-" and not args.text and src_path.suffix.lower() == ".md"
                and (args.vault or "[[" in source or _in_vault(src_path))
            )
            if obsidian_mode:
                from .textbook import build_from_obsidian

                doc = build_from_obsidian(src_path, vault=args.vault, template=template or args.template,
                                          title=args.title)
            elif template is not None and not args.text:
                from .textbook import Textbook

                tpl = template
                if args.header or args.footer or args.page_number:
                    from dataclasses import replace as _replace

                    from .textbook import HeaderDef

                    tpl = _replace(
                        tpl,
                        header=HeaderDef(args.header, align="right") if args.header else tpl.header,
                        footer=HeaderDef(args.footer) if args.footer
                        else HeaderDef("- {page} -") if args.page_number else tpl.footer,
                    )
                doc = Textbook(tpl).build(source, base_dir=base_dir, title=args.title or src_path.stem)
            elif args.text or src_path.suffix.lower() == ".txt":
                doc = text_to_hwpx(source, **common)
            else:
                doc = markdown_to_hwpx(source, base_dir=base_dir, **common)
            saved = doc.save(target)
            for warning in dict.fromkeys(doc.warnings):
                print(f"  주의: {warning}", file=sys.stderr)
            print(f"저장: {saved}")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            print(f"오류 ({name}): {exc}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
