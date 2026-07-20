# 조직경계 설정 안내

본 툴은 조직경계를 **결정하지 않는다**. 어떤 배출원이 우리 조직의 Scope 1·2인지는 사용자가 아래 기준으로 먼저 정하고, 그 결정에 따라 증빙을 입력 폴더에 분류해야 한다. 리포트에는 "사용자 선언 경계"로 표기된다.

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

---
근거: GHG Protocol Corporate Accounting and Reporting Standard (Revised Edition), Chapter 3 "Setting Organizational Boundaries". https://ghgprotocol.org/corporate-standard
