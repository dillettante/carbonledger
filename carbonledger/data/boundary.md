# 조직경계 설정 안내

본 툴은 조직경계를 **결정하지 않는다**. 어떤 배출원이 우리 조직의 Scope 1·2인지는 사용자가 아래 기준으로 먼저 정하고, 그 결정에 따라 증빙을 입력 폴더에 분류해야 한다. 그리고 그렇게 정한 내용을 `input/inventory.json`에 적으면 리포트 §0에 **그대로 전재된다**(아래 4).

## 1. 연결 기준 선택 (GHG Protocol Corporate Standard)

셋 중 하나를 선택해 일관 적용한다:

| 기준 | 내용 | 통상 선택 |
|---|---|---|
| **운영통제** (operational control) | 운영 방침을 도입·실행할 권한이 있는 사업장 100% 계상 | 한국 실무 대다수 (배출권거래제·목표관리제도 이 계열) |
| 재무통제 (financial control) | 재무·운영 방침 지배력 기준 | |
| 지분율 (equity share) | 지분 비율만큼 계상 | 투자회사 등 |

## 2. 자주 틀리는 귀속 판단

| 사례 | 귀속 | 입력 위치 |
|---|---|---|
| 법인 소유·리스 차량 주유 | **Scope 1** | `input/scope1-fuel/` |
| 임직원 개인차량 **출장** 주유 | Scope 3 카테고리 6 | `input/travel/` |
| 임직원 개인차량 **통근** | Scope 3 카테고리 7 | `commute.csv` |
| 자가 사무실 전기 | **Scope 2** | `input/scope2-energy/` |
| 임차 사무실 전기 (요금을 우리가 냄) | 운영통제 기준이면 통상 **Scope 2** | `input/scope2-energy/` |
| 임차 사무실 전기 (임대료 포함, 별도 고지 없음) | Scope 3 카테고리 8 (추정 배분 필요) | 미자동화 — 리포트 안내 참조 |
| 건물 중앙 지역난방 | Scope 2 (열·스팀) — **본 툴 미자동화** | 리포트에 미측정 표기됨 |
| 냉방기·냉장고 냉매 누출 | Scope 1 (fugitive) — **본 툴 미자동화** | 리포트에 미측정 표기됨 |

## 3. 보고기간

역년(1.1.~12.31.) 단위를 권장한다. `run --period 2026`으로 지정하면 기간 밖 증빙은 집계에서 제외되고 별도 목록으로 표시된다.

## 4. 정한 경계를 기록하기 — `input/inventory.json`

배출량은 툴이 계산하지만 **그 숫자가 무엇에 대한 숫자인지**는 조직만 안다. 위 1~3에서 정한 내용을 `input/inventory.json`에 적으면 리포트 맨 앞 §0에 전재된다. 파일이 없으면 리포트는 "조직 선언 없음"이라고만 적는다 — 조직명도 경계도 없는 배출량 표만 남는다.

| 항목 | 내용 |
|---|---|
| `organization` · `responsible` | 보고 주체·작성 책임 |
| `reporting_period` | 보고기간(`--period`와 별개로 문장으로 기재) |
| `consolidation_approach` | 위 1에서 고른 연결기준 — **어느 것을 택했는지 밝히는 것 자체가 요구사항**이다(ISO 14064-1 5.1) |
| `boundary_description` | 포함한 법인·사업장 범위 서술 |
| `significance_criteria` | 어느 간접배출을 '유의'로 보아 포함했는지의 기준(§2의 카테고리 취사선택 근거) |
| `base_year` | 기준연도와 재산정 방침 |
| `exclusions[]` | 제외한 대상과 **사유** — 위 2의 미자동화 항목(냉매·지역난방)도 여기 적는다 |
| `verification` | 조직 인벤토리의 검증 상태 |

양식은 [`examples/input/inventory.json`](../../examples/input/inventory.json)을 복사해 고쳐 쓴다.

**툴은 이 내용을 판정하지 않는다.** 연결기준이 적정한지, 제외가 정당한지 심사하지 않고, 재무연결 범위와 대조하지도 않는다. 조직의 말을 조직의 말로 옮길 뿐이다. `verification`을 "검증완료"로 적어도 그것은 조직 인벤토리에 관한 선언이며 **본 툴 산정치가 검증받았다는 뜻이 아니다** — 리포트가 그 점을 함께 적는다.

---
근거: GHG Protocol Corporate Accounting and Reporting Standard (Revised Edition), Chapter 3 "Setting Organizational Boundaries". https://ghgprotocol.org/corporate-standard
