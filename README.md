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

## 수학 교재 만들기 (양식 + 수식)

```bash
md2hwpx --init-template 내양식.toml          # 기본 수학 교재 양식을 복사 → 값만 고치면 내 양식
md2hwpx 교재.md --template 내양식.toml       # 양식대로 변환
md2hwpx 교재.md -t 기본                      # 내장 양식 그대로
```

예시: `examples/수학교재_예시.md` → `md2hwpx examples/수학교재_예시.md -t 기본`

### 교재용 Markdown 문법

````markdown
# Ⅰ. 다항식                 ← 대단원: 새 쪽에서 시작, 문제 번호가 01부터 다시

본문 안의 수식은 $x^2 + 1$ 처럼, 가운데 한 줄 수식은
$$\frac{-b \pm \sqrt{b^2-4ac}}{2a}$$

::: 정의 동류항              ← 양식의 [box."정의"] 모양 상자 (번호 자동: 정의 1, 정의 2 …)
문자와 차수가 같은 항을 **동류항**이라 한다.
:::

::: 예제 곱셈 공식의 활용
$x+y=5$, $xy=3$일 때 $x^2+y^2$의 값은?
[풀이]                      ← 예제의 풀이는 상자 안에 바로 표시
$(x+y)^2 - 2xy = 19$
:::

\columns{2}                 ← 여기부터 2단 (\columns{1} 로 되돌림, \columnbreak 로 다음 단)

::: 문제 [3점]              ← 번호 자동 (01, 02 …), 뒤의 글은 문제 끝에 붙음
$(2x+1)^2$을 전개한 식은?

① $4x^2+1$ ② $4x^2+2x+1$ ③ $4x^2+4x+1$ ④ $2x^2+4x+1$ ⑤ $4x^2+4x+2$

\vspace{20mm}               ← 빈 공간 (서술형 풀이 칸)

[정답] ③
[해설]                       ← [정답]·[해설]은 책 뒤 '정답과 해설'로 이동
$(2x+1)^2 = 4x^2 + 4x + 1$
:::

\정답                        ← 여기까지의 정답과 해설을 이 자리에 (없으면 문서 맨 끝)
````

- **보기 ①~⑤**: 보기 길이를 보고 한 줄에 5개 / 3개 / 2개 / 1개씩 자동 정렬합니다.
- **상자 종류(기본 양식)**: 정의, 정리, 공식, 예제, 증명, 참고, 주의. 양식 파일에 `[box."새이름"]`을 추가하면 `::: 새이름`으로 바로 쓸 수 있습니다.
- **정답과 해설**: 빠른 정답표 + 문제별 해설(2단). 대단원 이름별로 묶입니다.

### 내장 양식 '수능파이널' (문제집 모양)

```bash
md2hwpx 원고.md -t 수능파이널
md2hwpx --init-template 내양식.toml -t 수능파이널    # 이 모양을 바탕으로 내 양식 만들기
```

예시: `examples/수능파이널_예시.md`. 이 양식은 아래처럼 조판합니다.

- **표지**: 종이 위쪽 남색 띠, 큰 제목, 남색 부제. 표지 쪽에는 머리말·쪽 번호가 없습니다.
- **머리말**: 왼쪽 "책 이름 | 부제", 오른쪽 남색 굵은 글(단원마다 바뀜), 아래 가는 선. `# 09 …`처럼 번호가 있는 단원의 첫 쪽에서는 감춥니다.
- **단원 제목**: 큰 남색 번호 + 제목 + 굵은 남색 선
- **글꼴**: 핵심 개념은 고딕이고 `$$수식$$` 줄에 회색 배경이 깔립니다. 문제·해설은 명조입니다.
- **문제**: 나오면 자동으로 2단(가운데 세로선)으로 바뀝니다. "01 …… 출처" 머리줄, 번호는 책 전체에서 이어집니다.
- **정답과 해설**: 10칸 정답 격자, 문항별 "01 출처 …… 정답 ①" 줄 + 해설(2단)

이 양식에서 쓰는 문법:

````markdown
::: 표지
위: 2027학년도 대학수학능력시험 대비
제목: 수능 파이널
부제: 번호별 출제 예측 | 공통 4점 + 미적분     ← '|' 뒤는 작은 글씨
설명:
공통 4점 9 – 15번 · 20 – 22번
저자: 저자 이름
:::

# 09 수직선 위의 운동          ← 숫자는 큰 남색 번호로
\머리말 공통 9번               ← 이 단원부터 머리말 오른쪽 글

## 핵심 개념
### 1 위치·속도·가속도의 관계
$$v(t) = x'(t)$$              ← 회색 배경 수식 줄
- **위치가 같아진다** → …      ← ▪ 남색 글머리표

::: 주의                       ← 테두리 꼬리표 + 내어쓰기
구간 안에서 $v$의 부호가 바뀌면 …
:::

## 최근 기출 | 공통 9번        ← '|' 뒤는 보조 글(진한 회색, 보통 굵기)

::: 문제 2026학년도 수능 11번    ← 제목 자리 = 출처 (오른쪽 작은 회색)
… 고른 것은? [4점]
::: 보기                       ← 〈보 기〉 상자
ㄱ. …                          ← ㄱ. ㄴ. ㄷ. 내어쓰기 항목
ㄴ. …
:::
① ㄱ ② ㄱ, ㄴ ③ ㄱ, ㄷ ④ ㄴ, ㄷ ⑤ ㄱ, ㄴ, ㄷ
[정답] ③
[해설]
…
:::
````

표 안의 강조 색은 `<span style="color:#1F3864">**높음**</span>`처럼 씁니다.

차례(목차)는 자동으로 만들지 않습니다. 쪽 번호는 한글이 배치한 뒤에야 정해지기 때문입니다. 한글의 **도구 → 차례/색인 → 차례 만들기**에서 "스타일로 모으기"로 `제목 1`, `제목 2`를 고르면 쪽 번호가 붙은 차례가 만들어집니다.

### Obsidian 볼트에서 교재 만들기

문제은행 노트는 그대로 두고, 책마다 **책 노트**(설계도)를 하나 만들어 문제 노트를 `![[ ]]`로 끼워 넣습니다.
Obsidian 미리보기에서도 문제가 펼쳐져 보이므로, 책 노트가 곧 교재 초안입니다.

```bash
md2hwpx "교재/수능 파이널.md"                       # 볼트(.obsidian 폴더)와 양식을 자동으로 찾음
md2hwpx "교재/수능 파이널.md" --vault "C:\Users\...\Obsidian Vault" -t 내양식.toml
md2hwpx "2025 9월모평 수학 30번 (기하).md" -t 수능파이널   # 문제 노트 하나만
```

책 노트 예시 (`examples/obsidian_vault/교재/수능 파이널 (예시).md`):

```markdown
---
template: 수능파이널            ← 양식 (내장 이름 또는 볼트 안 .toml 경로)
title: 수능 파이널
---
# 09 수직선 위의 운동
\머리말 공통 9번
## 핵심 개념
![[수직선 위의 운동#위치·속도·가속도]]   ← 개념 노트의 그 제목 아래 부분만
## 최근 기출 | 공통 9번
![[2027 9월모평 수학 9번]]              ← 문제 노트 → 문제
![[2027 6월모평 수학 9번]]
\문제모음 subject=기하 year>=2025        ← 속성으로 골라 모으기 (연도 → 시험 → 번호순)
```

**문제 노트로 보는 기준:** 속성 `type: problem-bank`이거나, `answer`와 `number`/`exam`이 있거나, 정답 콜아웃이 있는 노트

| 문제 노트의 부분 | 교재에서 |
|---|---|
| 속성 `year` `exam` `number` | 출처 줄 "2025학년도 9월 모의평가 30번" (`9월모평` → `9월 모의평가`) |
| 속성 `answer` (없으면 콜아웃 안 `**정답: …**`) | 정답표. 보기 ①~⑤가 있는 문제는 `3` → `③` |
| 맨 앞 `# 제목` | 버림 (출처 줄이 대신함) |
| `![[그림.png]]`, `![[그림.png\|300]]` | 볼트에서 같은 이름 파일을 찾아 넣음 (`\|300` = 300px 너비) |
| `> [!check]- 정답과 풀이` (제목에 정답·풀이·해설) | 책 뒤 '정답과 해설'로 |
| 다른 콜아웃 `> [!warning]`, `> [!note]` … | 양식의 상자(주의, 참고 …)로 |
| `[[링크\|별칭]]` | 별칭 글자만 |
| `%%주석%%`, `^블록id` | 지움 |
| 끝의 `---` + 목차 링크 | 버림 |

`\문제모음` 조건: `=` (목록 속성은 포함 여부, `기하`는 `기하/평면벡터`도 포함), `!=`, `>` `>=` `<` `<=`, `~`(글자 포함),
`sort=year,-number`, `limit=5`. 값에 공백이 있으면 `subject="수학 Ⅱ"`처럼 따옴표로 감쌉니다.

출처 줄 형식이나 시험 이름은 양식에서 바꿀 수 있습니다:

```toml
[obsidian]
source_format = "{year}학년도 {exam} {number}번"
exam_names = { "9월모평" = "9월 모의평가", "사관학교" = "사관학교 기출" }
callout_boxes = { note = "참고", warning = "주의", example = "예제" }
```

### 양식 파일 (TOML)

`--init-template`로 만든 파일에 모든 항목이 한글 설명과 함께 들어 있습니다. 주요 항목:

| 구역 | 정하는 것 |
|---|---|
| `[page]` | 용지, 여백, 기본 단 수·간격·구분선 |
| `[font]`, `[heading]` | 본문/제목 글꼴·크기·줄 간격·색 |
| `[equation]` | 수식 글꼴(`HancomEQN`/`HYhwpEQ`)과 크기 |
| `[header]`, `[footer]` | 머리말·꼬리말 (`{page}`, `{total}`) |
| `[chapter]` | 대단원마다 새 쪽 |
| `[problem]` | 번호 모양(`{n:02d}` → 01, `{chapter}-{n}` → 1-3), 색·크기, 들여쓰기, 풀이 공간 |
| `[answers]` | '정답과 해설' 제목, 새 쪽, 단 수, 빠른 정답표 |
| `[box."이름"]` | 상자 모양(`bar` 색 띠 / `inline` 이름표 / `line` 왼쪽 세로줄 / `plain` 테두리 / `titled` 〈보 기〉형 / `tag` 테두리 꼬리표), 테두리·배경·제목 띠 색, 번호 |
| `[heading.1]` ~ `[heading.6]` | 단계별 제목: 크기·색, 번호 색·크기, 보조 글 색, 아래 선 색·굵기 |
| `[list]` | 글머리표 기호·색 |
| `[table]` | `style = "booktabs"`(위·아래 굵은 선만) 또는 `"grid"`(모든 칸 테두리) |
| `[cover]` | 표지 띠 색·높이, 제목·부제 크기와 색, 여백 |

`[problem]`의 `layout = "header"`(번호 ↔ 출처 줄), `columns = 2`(문제는 자동 2단), `font`(문제 글꼴)와
`[answers]`의 `quick_style = "grid"`, `entry_layout = "line"` 같은 항목은 `수능파이널.toml`에 설명과 함께 들어 있습니다.

항목 이름을 잘못 쓰면 변환할 때 `주의:` 로 알려 줍니다.

### 지원하는 LaTeX

`\frac` `\dfrac` `\sqrt` `\sqrt[n]` `^` `_` `\sum` `\int` `\iint` `\oint` `\lim` `\prod`,
그리스 문자, `\le \ge \ne \pm \times \div \cdot \approx \equiv \to \Rightarrow \iff`,
집합 `\in \subset \cup \cap \emptyset`, `\left( \right)`, `\overline \vec \hat \bar \dot`,
`\text{한글}` `\mathrm`, `\therefore \because \angle \triangle \perp \parallel \infty`,
행렬 `pmatrix bmatrix vmatrix matrix`, `cases`, `aligned`, `\binom` 등.
모르는 명령은 글자로 넣고 `주의:` 메시지를 보여 줍니다.

> 수식 상자 크기는 계산으로 추정한 값입니다. 한글(특히 Windows)은 저장된 크기로 줄을 배치하므로
> 수식 앞뒤 간격이 어색하면 그 수식을 더블클릭했다가 닫으면 한글이 크기를 다시 맞춥니다.

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

교재 기능을 코드에서 쓰려면:

```python
from hwpxwriter.textbook import build_textbook, load_template
build_textbook(open("교재.md", encoding="utf-8").read(), "교재.hwpx", template="내양식.toml")

# 또는 직접: 수식·상자·다단·보기
doc.add_equation(r"\int_0^1 x^2\,dx = \frac{1}{3}")
with doc.box(label="정의 1", title="허수단위"):
    doc.add_paragraph(["제곱하여 ", Run("-1", equation=True), "이 되는 수"])
doc.set_columns(2, line=True)
doc.add_choices(["$1$", "$2$", "$3$", "$4$", "$5$"])
```

## 구조

```
hwpxwriter/
  document.py   문서 빌더 (문단·표·그림·수식·상자·다단·머리말/꼬리말, .hwpx 패키징)
  styles.py     글자/문단 모양·테두리 관리, header.xml 생성
  markdown.py   Markdown 해석기 (+ 수식, ::: 블록, 지시어)
  latex.py      LaTeX → 한글 수식 변환, 수식 크기 추정
  textbook.py   교재: 양식 읽기, 문제 번호, 상자, 정답과 해설
  templates/    내장 양식 (수학교재.toml)
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

- 표 칸 병합, 각주/미주, 하이퍼링크 필드(링크는 모양만 적용), 목차 자동 생성, 수식 번호
- 문단 중간의 그림 (한 줄 전체가 그림일 때만 그림으로 넣음)
- 기존 hwpx 양식 파일 읽어서 채우기
