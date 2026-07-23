# carbonledger 운영 플레이북

> **이게 뭔가요? — 터미널에서 실행하는 프로그램(CLI)입니다.**
> Claude 스킬도, MCP 서버도, 웹사이트도 아닙니다. `pip`으로 설치하고 `carbonledger`라는 명령어로 실행하는 **독립 실행형 파이썬 프로그램**입니다.
> 하는 일: **영수증·고지서 사진과 엑셀(CSV)을 폴더에 넣고 명령 한 줄을 실행하면 → AI가 읽어서 → 조직의 온실가스 배출량(탄소발자국) 리포트(마크다운 + 엑셀)를 만들어 줍니다.**

- 버전 0.1.0 · 최종 2026-07-20 · 지원 OS: **macOS/Linux** (Windows는 `export` 대신 `$env:` 사용, PDF 처리 시 `pip install ".[pdf]"` 필수 — sips 폴백이 macOS 전용)
- 빠른 시작은 `README.md`, 계수 근거는 `PHASE0_RESEARCH.md`. (설계 이력 PLAN.md는 비공개 내부 문서라 저장소에 없음)

---

## 한눈에 보는 흐름

```
 [당신이 넣는 것]                  [프로그램이 하는 일]              [나오는 것]
 ┌─────────────────┐              ┌──────────────────┐            ┌────────────────┐
 │ input/ 폴더      │              │ ① AI가 사진에서   │            │ out/           │
 │  ├ 전기 고지서.jpg │  ─ 실행 ─▶  │   숫자를 읽음      │  ─────▶   │  ├ report.md    │
 │  ├ 주유 영수증.jpg │  carbonledger│ ② 값이 말이 되는지 │            │  │ (읽는 리포트) │
 │  ├ KTX 승차권.png │   run input/ │   검증            │            │  ├ report.xlsx  │
 │  ├ commute.csv   │              │ ③ 활동량×배출계수  │            │  │ (엑셀)       │
 │  └ spend.csv     │              │ ④ 다 더해서 집계   │            │  └ records.json │
 └─────────────────┘              └──────────────────┘            └────────────────┘
```

- **넣는 것**: 증빙 이미지(영수증·고지서 사진/PDF)와 몇 개의 CSV 파일.
- **나오는 것**: 사람이 읽는 리포트(`report.md`), 엑셀(`report.xlsx`), 감사추적용 원장(`records.json`).
- **AI 부분**: 사진에서 글자·숫자를 읽는 데만 AI(비전 LLM)를 씁니다. 계산·검증·집계는 전부 일반 코드입니다.

---

## 시작하기 전 준비물 (순서대로)

### 준비물 1 — 프로그램 설치
파이썬 3.10 이상이 있는 컴퓨터에서:
```bash
git clone <저장소주소> carbonledger
cd carbonledger
pip install -e .              # 기본 (requests + openpyxl)
pip install -e ".[pdf]"       # 고지서가 PDF면 추가 (pymupdf)
```
설치가 됐는지 확인 (인터넷·AI 없이 동작):
```bash
carbonledger selftest        # "전 모듈 selftest 통과 ✅" 나오면 OK
```

### 준비물 2 — AI(비전 LLM) 연결 ⭐ 가장 중요
사진에서 숫자를 읽으려면 **비전 LLM**이 필요합니다. **세 가지 방법 중 하나**를 고르세요:

| 방법 | 설정 | 특징 |
|---|---|---|
| **A. Claude (Anthropic)** | `ANTHROPIC_API_KEY` 발급 | 정확도 높음. ⚠️ **사진이 Anthropic 서버로 전송됨** |
| **B. ChatGPT (OpenAI)** | `OPENAI_API_KEY` 발급 | 정확도 높음. ⚠️ **사진이 OpenAI 서버로 전송됨** |
| **C. 로컬 — LM Studio** | 앱 설치 후 모델 로드 | ⭐ **사진이 외부로 안 나감**(기밀·개인정보에 안전). 무료. GUI 앱 |
| **D. 로컬 — Ollama** | `ollama pull qwen3-vl:4b` | ⭐ 사진이 외부로 안 나감. 무료. 터미널 사용자에게 익숙 |

**어느 걸 고르나?**
- 영수증에 **개인정보·영업비밀**이 있다 → **C 또는 D(로컬)**. 증빙이 내 컴퓨터 밖으로 안 나갑니다. GUI가 편하면 C, 이미 Ollama를 쓰고 있으면 D.
- 그냥 편하고 정확한 게 좋다, 민감정보 없다 → **A(Claude)** 또는 **B(ChatGPT)**. 설치할 게 없습니다.

**방법 A — Claude 쓰기** (가장 간단):
```bash
export CARBONLEDGER_BACKEND=anthropic
export ANTHROPIC_API_KEY="sk-ant-...당신의 키..."
# 실행 시 자동으로 claude-sonnet-5 사용 (--model로 변경 가능)
```

**방법 B — ChatGPT 쓰기**:
```bash
export CARBONLEDGER_BACKEND=openai
export OPENAI_API_KEY="sk-...당신의 키..."
# 자동으로 gpt-4o 사용
```

**방법 C — 로컬 LM Studio 쓰기** (기밀 증빙, GUI):
1. [LM Studio](https://lmstudio.ai) 앱 설치
2. 앱에서 `qwen/qwen3-vl-4b` 모델 검색·다운로드·로드 (또는 `~/.lmstudio/bin/lms load qwen/qwen3-vl-4b`)
3. 별도 환경변수 불필요(기본값이 로컬 LM Studio). `curl localhost:1234/v1/models`로 모델이 뜨면 준비 완료.

**방법 D — 로컬 Ollama 쓰기** (기밀 증빙, 터미널):
```bash
# Ollama 설치(https://ollama.com) 후:
ollama pull qwen3-vl:4b
export CARBONLEDGER_BACKEND=ollama
# 실행 시 자동으로 qwen3-vl:4b 사용. curl localhost:11434/v1/models 로 확인
```

> ⚠️ **개인정보 주의**: A·B(상용)는 증빙 이미지가 외부 제공자 서버로 전송됩니다. 증빙에는 탑승자 성명·주소·고객번호 등 **직원·거래처의 개인정보**가 포함될 수 있습니다. 이런 증빙의 국외 전송은 **개인정보보호법상 국외이전·처리위탁 요건 검토가 필요할 수 있습니다** — 조직에서 사용할 때는 개인정보 보호책임자와 협의를 권장합니다. 법률·의료·영업비밀 증빙이라면 C(로컬)를 쓰세요. 이 선택이 이 툴의 핵심 프라이버시 결정입니다.
>
> 💰 **비용 주의**: A·B(상용)는 **이미지 1장당 API 호출 요금**이 부과됩니다(모델·해상도에 따라 장당 수 원~수십 원 수준, 제공자 요금표 확인). 증빙 수백 장 일괄 처리 전에 **몇 장으로 소액 테스트**를 먼저 해 보세요. C(로컬)는 무료입니다.

### 준비물 3 — 지도 API (출장 거리용, 선택)
KTX 등 주요 철도역은 **좌표가 내장돼 있어 이것 없이도** 거리가 나옵니다. 내장에 없는 역·버스·항공 지명만 지도 API가 필요합니다. **Kakao 권장**:
```bash
# Kakao (권장 — 지명·키워드 검색)
export KAKAO_REST_API_KEY="...키..."               # developers.kakao.com

# 또는 Naver (Kakao 키가 없을 때 폴백)
export NAVER_MAP_CLIENT_ID="...ID..."              # console.ncloud.com (Maps)
export NAVER_MAP_CLIENT_SECRET="...Secret..."
```
- ⚠️ Naver Geocoding은 **주소 지향 API**라 "서울역" 같은 지명 검색이 안 될 수 있습니다(지명 질의 미실측). 지명 위주 데이터면 Kakao를 쓰세요.
- 둘 다 없어도 프로그램은 돌아갑니다 — 좌표를 못 구한 출장 건만 "검토 대기"로 빠집니다(조용히 누락 아님).
- 지명(출발·도착)만 지도 API로 전송됩니다.

---

## 이제 실행해 봅시다 (실전 예제)

프로그램에 딸려 온 예제로 전체 흐름을 확인하세요(전부 합성 데이터):
```bash
# 로컬 LLM(준비물 2-C 완료 상태)이면 그대로:
carbonledger run examples/input --period 2026 --out examples/out

# Claude로 하려면:
export CARBONLEDGER_BACKEND=anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
carbonledger run examples/input --period 2026 --out examples/out
```
> ℹ️ 개발 검증은 로컬 백엔드(LM Studio)로 수행됐습니다. 상용 백엔드(Claude·ChatGPT)는 각 제공자의 표준 API 규격으로 구현됐으나 **실호출 검증은 사용자 환경의 첫 실행**이 됩니다 — 이미지 1~2장으로 소액 테스트 후 일괄 실행하세요.

나오는 결과:
```
리포트 생성: examples/out/report.md · report.xlsx · records.json
  Scope1 128.85 / Scope2 208.65 / Scope3 465701.75 kg  → 합계 466039.25 kgCO2eq
  산정 30건 · 검토대기(미포함) 0건
```
`examples/out/report.md`를 열면 조직 탄소발자국 리포트가, `examples/sample_output/`에는 미리 만들어 둔 샘플이 있습니다.

**내 데이터로 하려면**: `examples/input`을 흉내 내 내 폴더를 만들고(§"넣는 것 준비하기"), 그 경로로 `carbonledger run 내폴더/ --period 2026` 실행하면 됩니다.

---

## 터미널이 부담스러우면 — AI 에이전트로 굴리기

이 툴은 평범한 CLI라서 **Claude Code 같은 AI 코딩 에이전트에게 대신 시킬 수 있습니다.** 터미널 명령을 직접 칠 필요가 없습니다:

> "이 폴더(carbonledger)에서 `pip install -e .` 하고, 내 증빙이 있는 `~/Desktop/증빙2026` 폴더를 input 구조로 정리한 다음 `carbonledger run`으로 2026년 리포트를 만들어 줘"

에이전트로 굴릴 때 특히 좋은 점:
- **입력 준비를 맡길 수 있다** — 뒤섞인 증빙 파일을 scope1-fuel/·travel/ 폴더로 분류하고 파일명 힌트를 붙이는 일(§1)을 에이전트가 합니다. 단, **Scope 귀속(법인차 vs 개인차)은 사람이 알려줘야** 합니다 — 에이전트도 영수증만으론 모릅니다.
- **검토 대기 처리가 쉬워진다** — "review_queue 보고 교정 파일 만들어서 재집계해 줘"라고 하면 §3의 JSON 작성을 대신합니다.
- CSV(통근 설문·지출 내역) 정리도 원본 엑셀에서 스키마에 맞게 변환시킬 수 있습니다.

주의:
- 에이전트가 **증빙 폴더를 읽게 되므로**, 에이전트 자체가 상용 모델이면 파일 내용이 그 제공자에게 전송될 수 있습니다 — 기밀 증빙이면 추출 백엔드뿐 아니라 **에이전트 선택도** 같은 기준으로.
- 배출량 숫자는 에이전트가 아니라 **이 툴이 계산하게 하세요**(에이전트에게 "대신 계산해 줘"라고 하면 검증 관문·감사추적 없이 숫자가 나옵니다 — 이 툴을 쓰는 이유가 사라집니다).

웹 대시보드·MCP 서버 형태는 의도적으로 만들지 않았습니다(설계 원칙: 최소 구성). 필요해지면 CLI를 감싸는 형태로 추가될 수 있습니다.

---

## 목차 (상세 참조)

1. [넣는 것 준비하기 — 폴더·파일 스키마](#1-넣는-것-준비하기)
2. [나오는 것 읽기 — 리포트 구조](#2-나오는-것-읽기)
3. [검증과 "검토 대기" 처리](#3-검증과-검토-대기-처리)
4. [배출계수 전체 목록](#4-배출계수-전체-목록)
5. [유지관리·확장](#5-유지관리확장)
6. [문제해결 (함정 총람)](#6-문제해결)
7. [한계·규제 경계](#7-한계와-규제-경계)
8. [기여·문의](#8-기여문의)

---

## 1. 넣는 것 준비하기

`input/` 아래에 이렇게 둡니다(있는 것만 두면 됨 — 전부 필요 없음):

```
input/
├── scope1-fuel/          ← 법인차·시설 연료 영수증·고지서 사진   (직접배출 Scope 1)
├── scope2-energy/        ← 전기 고지서 사진                     (전력 Scope 2)
├── travel/               ← 출장 승차권·항공권·숙박 영수증 사진   (Scope 3-6)
├── commute.csv           ← 직원 통근 설문                       (Scope 3-7)
├── spend.csv             ← 구매 지출                            (Scope 3-1)
└── scope3/               ← Scope 3 나머지 카테고리 CSV
    └── cat4_운송.csv  cat5_폐기물.csv  cat15_투자.csv  …
```

> **왜 폴더로 나누나?** 같은 주유 영수증도 **법인차면 Scope 1, 개인차 출장이면 Scope 3-6, 통근이면 3-7**입니다. 영수증만 봐선 구분이 안 되니 AI가 추측하지 않고, **당신이 어느 폴더에 넣느냐로 정합니다.** 어디에 넣을지 헷갈리면 `carbonledger/data/boundary.md`(조직경계 안내)를 보세요.

### 1-A. 이미지 증빙 (사진·PDF)
지원: `.jpg .png .webp .pdf`. **파일명에 힌트**를 넣으면 AI가 무슨 문서인지 압니다:

| 폴더 | 파일명에 넣을 말 | 프로그램이 읽는 것 |
|---|---|---|
| scope1-fuel/ | `주유`·`휘발유`·`경유`·`fuel` | 유종·주유량(L)·단가·금액 |
| scope1-fuel/ | `도시가스`·`가스` | 사용량·단위(m³/MJ)·청구월 |
| scope2-energy/ | `전기`·`한전`·`kepco` | 사용량(kWh)·전월/당월 지침·청구월 |
| travel/ | (그 외 = 교통) | 수단·출발·도착·날짜·금액 |
| travel/ | `숙박`·`호텔`·`hotel` | 숙소명·체크인·박수·금액 |

예: `주유_경유_202605.jpg`, `전기_한전_202605.png`, `KTX_서울부산.png`, `호텔_부산_202605.jpg`
- 힌트는 AI가 아니라 **파일명 문자열 매칭**으로 판정됩니다. **힌트가 없으면 폴더 기본 유형**으로 처리됩니다(scope1-fuel→주유, scope2-energy→전기) — 가스 고지서를 힌트 없이 scope1-fuel에 넣으면 주유로 읽혀 검토 대기로 빠지니, 파일명에 힌트를 넣는 것이 안전합니다.
- **파일 1개 = 증빙 1건**입니다. 한 장에 청구서 여러 장을 합철한 스캔은 한 건만 읽히고 나머지가 조용히 누락됩니다 — 청구서별로 잘라 파일을 나누세요. 저화질 스캔은 상위 모델(`qwen3-vl-8b` 이상)을 권장합니다.

### 1-B. commute.csv (통근)
```csv
employee_id,mode,factor_id,oneway_km,workdays
E001,지하철,commute_subway,18,220
E002,시내버스,commute_bus_local,9,220
E003,승용차휘발유,commute_car_petrol,25,220
```
- `factor_id`: `commute_subway` / `commute_bus_local` / `commute_car_petrol` / `commute_car_diesel` / `commute_car_hybrid` 중 하나(§4 목록).
- 계산: `편도km × 2 × 근무일 × 계수`. 승용차 계수는 차량당이니 카풀이면 인원으로 나눠 입력.

### 1-C. spend.csv (구매 재화·서비스)
```csv
item,krw,factor,factor_source
사무용품,12000000,0.0004,한국은행 환경산업연관표(2006) 도소매
```
- 한국에 공개된 지출기반 계수표가 없어서(조사 결과) **계수를 직접 넣습니다**: `factor`(1원당 kgCO2eq), `factor_source`(출처).
- **출처(factor_source)를 비우면 그 줄은 "검토 대기"로 빠집니다** — 근거 없는 숫자를 막기 위해서입니다.

### 1-D. scope3/cat{N}_*.csv (나머지 카테고리 2·4·5·8~14)
전부 **같은 형식**입니다 — 활동량, 단위, 그리고 계수(레지스트리 아이디 또는 직접 입력):
```csv
item,activity,unit,factor_id,factor,factor_source
원자재 트럭운송,15000,tonne-km,freight_hgv,,
임차창고 전기,3000,kWh,electricity_kr,,
협력사 추정,500,kWh,,0.42,사내 추정치(출처설명)
```
- **아는 계수면** `factor_id`를 채웁니다(예: 운송 `freight_hgv`, 폐기물 `waste_mixed_landfill`, 전기 `electricity_kr` — §4 목록). 단위(`unit`)는 계수와 맞아야 합니다(운송=`tonne-km`, 폐기물=`tonne`, 전기=`kWh`).
- **모르는 계수면** `factor_id`를 비우고 `factor`+`factor_source`를 직접 넣습니다(spend.csv처럼).
- **운송은 톤×km를 미리 곱해** 넣습니다(50톤을 300km = 15000).
- 파일명 `cat4_...`, `cat5_...`의 숫자가 카테고리 번호입니다.

### 1-E. scope3/cat15_*.csv (투자 — 금융기관용)
투자는 계산이 달라서 전용 형식(PCAF 방법)입니다:
```csv
asset,asset_class,outstanding,denominator,investee_emissions
A제조 지분,상장주식,100000000,1000000000,500
```
- `outstanding`=투자·대출 잔액, `denominator`=기업가치(상장=EVIC, 대출=총자본+부채), `investee_emissions`=그 회사 배출량(**tCO2e**).
- 계산: (잔액÷기업가치) × 그 회사 배출량 = 우리에게 귀속되는 금융배출.

### 1-F. 카테고리 3은 넣을 것 없음
"연료·에너지 관련"(카테고리 3)은 Scope 1·2를 넣으면 **자동으로 파생 계산**됩니다(연료·전력의 상류배출). 별도 파일 불필요.

---

## 2. 나오는 것 읽기

`report.md`(마크다운)를 열면 위에서 아래로:

1. **총괄** — 조직 탄소발자국 = Scope 1+2+3 합계(tCO2eq).
2. **Scope 3 카테고리별** — 15개 전체 표. 데이터를 넣은 카테고리는 "측정"+수치, 안 넣은 건 "미측정"+측정법 안내.
3. **Scope 1·2 미측정 배출원** — 냉매·지역난방 등 이 툴이 자동으로 못 잡는 것(합계가 부분집계임을 알림).
4. **건별 명세** — 파일 → 활동량 → 계수 → 배출량. 감사 추적용.
5. **사용된 배출계수·출처** — 각 계수의 값·출처·신뢰수준·**한계**(예: "CO2만 반영", "UK 프록시").
6. **검토 대기** — 검증을 통과 못해 합계에서 빠진 건과 이유.

`report.xlsx`는 같은 내용을 4개 시트(총괄/건별/계수목록/검토대기)로. `records.json`은 재집계·프로그램 연동용 원장.

---

## 3. 검증과 "검토 대기" 처리

프로그램은 AI가 읽은 값을 **그냥 믿지 않습니다.** 이상하면 합계에 넣지 않고 "검토 대기"로 뺍니다:

| 검사 | 무엇을 잡나 |
|---|---|
| 형식 | 날짜꼴·금액 양수·필수 항목 빠짐 |
| 역명 대조 | 실제 없는 역명(AI 오독) |
| 폴더-유형 | 전기 폴더에 가스 고지서 같은 오분류 |
| 교차 산술 | 주유량×단가≈금액 / 전기요금÷kWh가 상식 범위(30~2000원) / 계량 지침 역전 |
| 보고기간 | 지정한 연도 밖이거나 날짜를 못 읽은 건 |

**검토 대기 건 되살리기**: `out/records.json`의 `review_queue`에서 어떤 게 왜 빠졌는지 봅니다. 사람이 값을 확인·교정해 `out/reviewed/` 폴더에 JSON 파일로 저장한 뒤 `carbonledger review out/`을 실행하면 합계에 다시 합쳐집니다(교정 건은 "human_corrected" 표시).

교정 파일 형식 — `records.json`의 records[] 항목 + **교정 이력**. 예(`out/reviewed/fix1.json`):
```json
{
  "source_file": "전기_공장_202603.pdf",
  "scope": 2, "activity": "전력 사용",
  "factor_id": "electricity_kr", "factor_value": 0.4173, "factor_unit": "kgCO2eq/kWh",
  "activity_value": 1200, "activity_unit": "kWh",
  "kgco2e": 500.76,
  "review": {
    "reviewer": "홍길동",
    "reviewed_at": "2026-07-23",
    "basis": "원증빙 재확인 — 고지서 2쪽 사용량 1,200kWh"
  }
}
```
`kgco2e`는 계수×활동량을 직접 계산해 넣습니다(0.4173×1200=500.76). 파일 하나에 레코드 하나.

**교정본도 검증 관문을 통과해야 합계에 들어갑니다**(자동 추출과 동일한 fail-closed 원칙):
- `review`의 **교정자·교정일시·근거 3개는 필수** — 하나라도 없으면 반려되고 검토 대기로 남습니다
- **계수 × 활동량 = 배출량** 산술이 맞아야 합니다(±1%) — 근거 없는 숫자를 총계에 넣을 수 없습니다
- 필수 필드(source_file·scope)·배출량 부호도 검사합니다
- 반려된 건은 화면에 사유가 표시되고 **집계에 반영되지 않습니다**

교정으로 반영된 건은 리포트 **§6 「수기 교정 이력」** 에 교정자·일시·근거와 함께 표시되고, 전체 대비 비중도 나옵니다(xlsx 감사추적 시트에도 '수기교정' 열로). 사람이 손댄 수치가 자동 추출 수치와 섞여 구별 불가능해지지 않게 하기 위함입니다.

---

## 4. 배출계수 전체 목록

`carbonledger/data/factors.json`. 신뢰수준: **국가공식**(한국 정부 고시) > **해외정부공식**(DEFRA·OGL v3) > **학술** > **사용자입력**.

**Scope 1 연료** (한국 gir 별표12, CO2만): `fuel_gasoline` 2.177 · `fuel_diesel` 2.577 kgCO2/L · `fuel_citygas_lng` 2.182 kgCO2/Nm³
**Scope 2 전력**: `electricity_kr` 0.4173 kgCO2eq/kWh (2023 소비단, location-based)
**출장(3-6)**: `travel_rail_ktx` 0.0269 · `travel_air_domestic` 0.273 · `travel_bus_intercity` 0.02717 · `travel_bus_local` 0.10846 (인·km) · `travel_hotel_kr` 55.8 (박당)
**통근(3-7)**: `commute_car_petrol` 0.1645 · `commute_car_diesel` 0.16984 · `commute_car_hybrid` 0.12607 (km, 차량당) · `commute_subway` 0.0278 · `commute_bus_local` 0.10846 (인·km)
**연료·에너지 상류(3-3, 자동파생)**: `wtt_gasoline` 0.58094 · `wtt_diesel` 0.61101 (L) · `wtt_citygas_lng` 0.3366 (Nm³) · `wtt_electricity_kr` 0.0459 · `td_electricity_kr` 0.0183 (kWh) ⚠️UK 프록시
**운송(3-4·9, tonne·km)**: `freight_hgv` 0.09752 · `freight_van` 0.61643 · `freight_rail` 0.02779 · `freight_ship_container` 0.01612 · `freight_air_longhaul` 1.09904
**폐기물(3-5·12, tonne당)**: `waste_mixed_landfill` 520.3342 · `waste_mixed_combustion` 6.41061 ⚠️직접 CO2 제외 · `waste_paper_landfill` 1164.39 · `waste_plastic_landfill` 8.88386 · `waste_recycling` 6.41061 ⚠️크레딧 미포함
**구매(3-1)**: `spend_category1_USER` (사용자 입력)

값의 출처·연도·경고는 factors.json의 각 항목 note와 리포트 §5 부록에 있습니다. 계수 근거 전량은 `PHASE0_RESEARCH.md`.

---

## 5. 유지관리·확장

**계수 갱신(연 1회 권장)**: DEFRA는 매년 여름 신판, 한국 전력계수는 gir 연 1회 공표. `factors.json`의 값·`year`를 바꾸고 `carbonledger selftest`로 회귀 확인(값을 못박은 테스트가 있어 같이 갱신).
**GWP 전환**: 4차 계획기간(2026~) AR5로 이행 시 각 계수 `gwp_basis` 갱신.
**역 마스터 확대**: 더 많은 역을 오프라인 처리하려면 `data/stations.json`에 `"역명":[위도,경도]` 추가(공공데이터포털 「한국철도공사 역 위치 정보」).
**새 문서유형/계수/카테고리 추가**: 이미지 유형은 `extract.py`의 `DOC_SPECS`에 항목 추가, 계수는 `factors.json`에 추가, Scope 3 새 카테고리는 `cat{N}_*.csv`로 넣으면 통일 어댑터가 처리.

---

## 6. 문제해결

| 증상 | 원인 | 해결 |
|---|---|---|
| "ANTHROPIC_API_KEY 미설정" / "OPENAI_API_KEY 미설정" 오류 | 상용 백엔드 선택했는데 키 없음 | 해당 키 `export` 또는 백엔드를 lmstudio로 |
| 이미지 추출이 전부 실패(로컬) | LM Studio 모델 미로드 / Ollama 미실행 | `curl localhost:1234/v1/models`(LM Studio) 또는 `curl localhost:11434/v1/models`(Ollama) 확인 |
| 고지서 숫자 오독·전부 null | 저화질 스캔·밀집 표(경량 모델 한계) | 상위 모델로 재시도 — 로컬이면 `--model qwen/qwen3-vl-8b`, 상용이면 `--model claude-opus-4-8` 등. 실물 스캔 검증: 4b 실패(→검토대기)·8b 성공 |
| 한 장에 청구서 여러 장(합철 스캔) | 스캔 파일 1장=문서 1건 가정 위반 — **한 장만 읽히고 나머지는 조용히 누락** | 이미지를 청구서별로 잘라 파일을 나눠 입력(사건기록·경리 스캔철에서 흔함) |
| PDF가 백지로 나옴 | 손상 PDF | 검토 대기로 빠짐. 이미지로 변환 후 재시도 |
| PDF 2쪽 이후를 못 읽음 | pymupdf 미설치(sips 폴백은 첫 쪽만) | `pip install ".[pdf]"` — 설치 시 앞 3쪽까지 읽음 |
| 출장이 전부 검토 대기 | 지도 키 없고 내장 좌표에도 없는 역 | Kakao/Naver 키 설정 또는 stations.json에 좌표 추가 |
| 폐기물 소각이 너무 작음 | DEFRA 소각계수는 처리공정만(직접 CO2 제외) | 직접 연소배출 별도 가산(계수 note 경고) |
| 단위 불일치 오류 | CSV의 unit이 계수와 안 맞음 | 운송=tonne-km, 폐기물=tonne, 전기=kWh |
| 다른 연도가 섞임 | `--period` 안 줌 | `--period 2026` 지정 |

---

## 7. 한계와 규제 경계

**이 툴이 내는 숫자는 추정치입니다. 규제 신고 자료가 아닙니다.**
- 배출권거래제·목표관리제 명세서는 지정된 산정방법·검증이 따로 요구됩니다. 이 툴의 거리기반·지출기반 산정은 그 방법론과 다릅니다.
- 신고 전에는 소관기관(온실가스종합정보센터 gir.go.kr / 한국환경공단)의 확정계수로 재검증하세요.

**숨기지 않는 한계**(전부 리포트·factors.json에 표기):
- 연료계수는 CO2만(CH4·N2O 별도), 전력은 location-based 단일(REC·PPA 미반영)
- 거리는 직선근사(철도·버스 ×1.2 보정), 항공 계수엔 우회 8% 내장
- 운송·폐기물·전력WTT/T&D는 DEFRA(영국) 대체·프록시 — 한국 완제계수 부재
- 폐기물 소각은 처리공정만(직접 CO2 제외), 재활용은 회피배출 크레딧 미포함
- 상용 LLM 사용 시 증빙 이미지가 외부 제공자로 전송됨

---

## 8. 기여·문의

- 버그·개선 제안은 저장소 **Issues**로. 재현 정보(백엔드·모델·증빙 유형·오류 메시지)를 함께 적어 주세요. **실제 증빙 이미지는 첨부하지 마세요**(개인정보) — 합성 재현 샘플 또는 텍스트 설명으로.
- 배출계수 갱신 제안은 출처(고시번호·문서명·URL) 필수 — 출처 없는 계수는 받지 않습니다.
- 라이선스 Apache 2.0, 계수 출처·OGL v3 고지는 `NOTICE`.

---
*carbonledger 운영 플레이북 v0.1.0 — 산출물은 규제 신고 자료가 아니며 소관기관 확정계수로 재검증해야 한다.*
