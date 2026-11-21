# hwpxwriter

Markdown이나 일반 텍스트를 **한글 문서(.hwpx)** 로 만들어 주는 Python 라이브러리이자 명령줄 도구입니다.
외부 라이브러리 없이 Python 표준 라이브러리만 사용합니다 (Python 3.9 이상).

## 설치

```bash
pip install .            # 이 폴더에서
# 또는 설치 없이: python -m hwpxwriter 입력.md
```

## 명령줄 사용법

```bash
md2hwpx 보고서.md                                   # → 보고서.hwpx
md2hwpx 보고서.md -o 결과/최종.hwpx --page-number
md2hwpx 보고서.md --header "2026년 업무 보고" --footer "{page} / {total}"
md2hwpx 메모.txt                                     # .txt 는 한 줄 = 한 문단
md2hwpx *.md -o 변환결과/                            # 여러 파일 한꺼번에
md2hwpx 보고서.md --paper A4 --landscape --margin 20,20,15,20 --font 맑은\ 고딕 --font-size 11
```

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `-o, --output` | 출력 파일 또는 폴더 | 입력과 같은 이름 |
| `--header`, `--footer` | 머리말/꼬리말. `{page}` 쪽 번호, `{total}` 전체 쪽 수 | 없음 |
| `--page-number` | 꼬리말 가운데에 `- 1 -` 형식 쪽 번호 | 끔 |
| `--paper` | `A4`, `A3`, `A5`, `B4`, `B5`, `LETTER`, `LEGAL` 또는 `가로x세로`(mm) | A4 |
| `--landscape` | 가로 방향 | 세로 |
| `--margin` | 여백 mm, `위,오른쪽,아래,왼쪽` | 20,30,15,30 |
| `--font`, `--heading-font`, `--code-font` | 본문/제목/코드 글꼴 | 함초롬바탕 / 함초롬돋움 / 굴림체 |
| `--font-size` | 본문 글자 크기(pt) | 10 |
| `--line-spacing` | 줄 간격(%) | 160 |
| `--paragraph-spacing` | 문단 뒤 간격(pt) | 4 |
| `--text` | Markdown 해석 없이 일반 텍스트로 | 끔 |

## 지원하는 Markdown

| 문법 | 한글 문서에서 |
|---|---|
| `#` ~ `######` 제목 | 제목 1~6 스타일 (크기·굵기 차등, 다음 문단과 같은 쪽에 유지) |
| `**굵게**`, `*기울임*`, `~~취소선~~`, `<u>밑줄</u>`, `==형광펜==` | 글자 모양 |
| `` `코드` `` | 고정폭 글꼴 + 회색 음영 |
| `[링크](주소)` | 파란색 밑줄 글자 |
| `H<sub>2</sub>O`, `x<sup>2</sup>` | 아래/위 첨자 |
| `-` `*` `+` 목록, `1.` 번호 목록, `- [x]` 체크 목록 | 내어쓰기 목록 (중첩 단계별 • ◦ ▪) |
| `> 인용` | 왼쪽 세로줄 + 회색 글자 |
| ```` ``` ```` 코드 블록 | 회색 배경 상자, 고정폭 글꼴 |
| `\| 표 \|` (GFM) | 테두리 표, 제목 줄 굵게·배경색·쪽마다 반복, `:--:` 정렬 반영 |
| `![설명](그림.png)` | 그림 + 아래에 캡션. `{width=50%}` 또는 `{width=80mm}` 로 크기 지정 |
| `---` | 가로 구분선 |
| `\newpage`, `\pagebreak`, `<!-- pagebreak -->` | 쪽 나눔 |
| 줄 끝 공백 2칸 / `\` / `<br>` | 문단 안 줄바꿈 |

그림은 PNG, JPEG, GIF, BMP를 지원하며, 본문 너비보다 크면 자동으로 줄입니다.

## Python에서 직접 만들기

```python
from hwpxwriter import HwpxDocument, PageSetup, Theme, Run

doc = HwpxDocument(
    PageSetup(paper="A4", margin_left=20, margin_right=20),
    Theme(body_font="맑은 고딕", font_size=11),
    title="실적 보고",
)
doc.set_header("기획팀", align="right")
doc.set_footer("- {page} -")

doc.add_title("2026년 실적 보고", subtitle="기획팀")
doc.add_heading("1. 개요", level=1)
doc.add_paragraph(["올해 매출은 ", Run("12% 증가", bold=True, color="#C00000"), "했습니다."])
doc.add_list_item("신규 고객 120곳")
doc.add_list_item("세부 항목", level=1)
doc.add_table(
    [["구분", "목표", "실적"], ["매출", "1,000", "1,120"]],
    align=["left", "right", "right"],
    col_widths=[2, 1, 1],
)
doc.add_image("chart.png", width_ratio=0.7, caption="그림 1. 분기별 실적")
doc.add_page_break()
doc.add_markdown("## 2. 계획\n\n- Markdown 도 **섞어서** 쓸 수 있습니다.")
doc.save("실적보고.hwpx")
```

한 번에 변환만 하려면:

```python
from hwpxwriter import markdown_to_hwpx
markdown_to_hwpx(open("보고서.md", encoding="utf-8").read(), "보고서.hwpx", page_number=True)
```

## 구조

```
hwpxwriter/
  document.py   문서 빌더 (문단·표·그림·머리말/꼬리말, .hwpx 패키징)
  styles.py     글자/문단 모양·테두리 관리, header.xml 생성
  markdown.py   Markdown 해석기
  images.py     그림 형식·크기 읽기
  cli.py        md2hwpx 명령
tests/          구조 검사 테스트 (pytest)
examples/       sample.md 와 그림
```

HWPX는 ZIP 안에 XML(OWPML, KS X 6101)을 담은 형식입니다. 본문(`Contents/section0.xml`)의 문단·글자는
서식을 직접 갖지 않고 `Contents/header.xml`에 모아 둔 글자 모양/문단 모양의 번호만 참조합니다.
`styles.py`가 쓰인 서식 조합을 모아 번호를 매기고, `document.py`가 본문과 패키지를 씁니다.

## 테스트

```bash
pip install pytest
python -m pytest tests
```

테스트는 ZIP 구조, XML 형식, 모든 서식 참조가 실제로 정의되어 있는지 등을 검사합니다.
한글 프로그램 자체에서 여는 확인은 자동화되어 있지 않으니, `examples/sample.md`를 변환해서
한글(또는 무료 한컴오피스 뷰어)로 열어 확인해 보세요.

## 아직 지원하지 않는 것

- 표 칸 병합, 각주/미주, 하이퍼링크 필드(링크는 모양만 적용), 수식, 목차 자동 생성
- 문단 중간의 그림 (한 줄 전체가 그림일 때만 그림으로 넣음)
- 기존 hwpx 양식 파일 읽어서 채우기
