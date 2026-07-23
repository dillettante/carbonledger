# 조직 온실가스 배출량 리포트

- 보고기간: **2026**  · 생성일: 2026-07-23
- 자동 산정 건수: 30  · 검토 대기(미포함): 0

## 1. 총괄 — 조직 탄소발자국

| 구분 | 배출량 |
|---|---|
| Scope 1 (직접) | 0.129 tCO2eq (128.8 kg) |
| Scope 2 (전력, location-based) | 0.209 tCO2eq (208.7 kg) |
| Scope 3 (기타 간접) | 465.702 tCO2eq (465,701.8 kg) |
| **합계** | **466.039 tCO2eq (466,039.3 kg)** |

> Scope 2는 location-based 단일 산정이다. market-based(녹색프리미엄·REC·PPA) 미반영.
> Scope 1 연료는 **CO2 단독** 산정(CH4·N2O 미가산, 통상 <3%) — 합계는 계수별 GWP 기준이 혼재된 추정치다(부록 §5 참조).

## 2. Scope 3 카테고리별 (GHG Protocol 15개 프레임)

| # | 카테고리 | 상태 | 배출량 |
|---|---|---|---|
| 1 | 구매한 재화 및 서비스 | 측정 | 9.800 tCO2eq (9,800.0 kg) |
| 2 | 자본재 | 측정 | 5.850 tCO2eq (5,850.0 kg) |
| 3 | 연료 및 에너지 관련 활동 (Scope 1·2 미포함분) | 측정 | 0.063 tCO2eq (62.7 kg) |
| 4 | 업스트림 운송 및 유통 | 측정 | 1.685 tCO2eq (1,685.1 kg) |
| 5 | 사업장 발생 폐기물 | 측정 | 1.050 tCO2eq (1,050.3 kg) |
| 6 | 출장 | 측정 | 0.011 tCO2eq (10.6 kg) |
| 7 | 직원 통근 | 측정 | 3.972 tCO2eq (3,972.0 kg) |
| 8 | 업스트림 임차 자산 | 측정 | 4.590 tCO2eq (4,590.3 kg) |
| 9 | 다운스트림 운송 및 유통 | 측정 | 1.391 tCO2eq (1,391.1 kg) |
| 10 | 판매 제품의 가공 | 측정 | 104.325 tCO2eq (104,325.0 kg) |
| 11 | 판매 제품의 사용 | 측정 | 125.190 tCO2eq (125,190.0 kg) |
| 12 | 판매 제품의 폐기 | 측정 | 0.027 tCO2eq (26.7 kg) |
| 13 | 다운스트림 임대 자산 | 측정 | 8.346 tCO2eq (8,346.0 kg) |
| 14 | 프랜차이즈 | 측정 | 29.402 tCO2eq (29,402.0 kg) |
| 15 | 투자 | 측정 | 170.000 tCO2eq (170,000.0 kg) |

## 3. Scope 1·2 미측정 배출원 (부분집계 고지)

아래는 본 툴이 자동 산정하지 않는다. 헤드라인 합계는 이 항목을 **제외**한 부분집계다.

| Scope | 배출원 | 측정법 |
|---|---|---|
| Scope 1 | 냉매 누출(공조·냉동 HFC, fugitive) | 냉매 충전량·누출률 기반 별도 산정 |
| Scope 1 | 비상발전기·소각 등 기타 고정연소 | 연료 사용량 확보 시 fuel_* 계수로 산정 가능 |
| Scope 2 | 지역난방 열·스팀 | 지사별 열 배출계수(factors.json _reference_only) × 열사용량 수기 산정 |

## 4. 건별 명세 (감사추적)

| 파일 | Scope | 활동 | 활동량 | 계수 | 배출량(kg) |
|---|---|---|---|---|---|
| ktx_seoul_busan_synthetic.png | S3 | 철도 서울→부산 | 394.3 passenger-km | `travel_rail_ktx` | 10.607 |
| 주유_경유_202605.png | S1 | 경유 주유 | 50.0 L | `fuel_diesel` | 128.85 |
| 전기_한전_202605.png | S2 | 전력 사용 | 500.0 kWh | `electricity_kr` | 208.65 |
| commute.csv#1 | S3 | 통근 지하철 | 7920.0 passenger-km | `commute_subway` | 220.176 |
| commute.csv#2 | S3 | 통근 시내버스 | 3960.0 passenger-km | `commute_bus_local` | 429.502 |
| commute.csv#3 | S3 | 통근 승용차(휘발유) | 11000.0 km | `commute_car_petrol` | 1809.5 |
| commute.csv#4 | S3 | 통근 승용차(하이브리드) | 12000.0 km | `commute_car_hybrid` | 1512.84 |
| spend.csv#1 | S3 | 구매 사무용품 구매 | 12000000.0 KRW | `spend_category1_USER` | 4800.0 |
| spend.csv#2 | S3 | 구매 법률자문 용역 | 50000000.0 KRW | `spend_category1_USER` | 5000.0 |
| cat10_processing.csv#1 | S3 | 판매제품 가공: 중간재 A 고객가공(판매 500t) | 250000.0 kWh | `user_factor` | 104325.0 |
| cat11_use.csv#1 | S3 | 판매제품 사용: 판매가전 수명사용전력(1000대×수명300kWh) | 300000.0 kWh | `electricity_kr` | 125190.0 |
| cat12_eol.csv#1 | S3 | 판매제품 폐기: 판매제품 포장재 폐기(플라스틱 3t) | 3.0 tonne | `waste_plastic_landfill` | 26.652 |
| cat13_leased.csv#1 | S3 | 다운스트림 임대자산 에너지: 임대건물 전기(임차인 사용) | 20000.0 kWh | `electricity_kr` | 8346.0 |
| cat14_franchise.csv#1 | S3 | 프랜차이즈 에너지: 가맹점 5개 전기 합계 | 60000.0 kWh | `electricity_kr` | 25038.0 |
| cat14_franchise.csv#2 | S3 | 프랜차이즈 에너지: 가맹점 도시가스 합계 | 2000.0 Nm3 | `fuel_citygas_lng` | 4364.0 |
| cat15_investments.csv#1 | S3 | 투자 A제조 지분투자 (상장주식) | 500000.0 kgCO2eq(피투자) | `pcaf_financed` | 50000.0 |
| cat15_investments.csv#2 | S3 | 투자 B물류 대출 (기업대출) | 1200000.0 kgCO2eq(피투자) | `pcaf_financed` | 120000.0 |
| cat2_capital_goods.csv#1 | S3 | 자본재(취득): 사무용 복합기 3대 | 4500000.0 KRW | `user_factor` | 1350.0 |
| cat2_capital_goods.csv#2 | S3 | 자본재(취득): 업무용 노트북 10대 | 15000000.0 KRW | `user_factor` | 4500.0 |
| cat4_upstream_transport.csv#1 | S3 | 업스트림 운송·유통: 원자재 트럭 운송(50t×300km) | 15000.0 tonne-km | `freight_hgv` | 1462.8 |
| cat4_upstream_transport.csv#2 | S3 | 업스트림 운송·유통: 부품 철도 운송(20t×400km) | 8000.0 tonne-km | `freight_rail` | 222.32 |
| cat5_waste.csv#1 | S3 | 사업장 폐기물: 사무실 혼합폐기물 매립 2t | 2.0 tonne | `waste_mixed_landfill` | 1040.668 |
| cat5_waste.csv#2 | S3 | 사업장 폐기물: 폐지 재활용 1.5t | 1.5 tonne | `waste_recycling` | 9.616 |
| cat8_leased_assets.csv#1 | S3 | 업스트림 임차자산 에너지: 임차 사무실 전기 | 8000.0 kWh | `electricity_kr` | 3338.4 |
| cat8_leased_assets.csv#2 | S3 | 업스트림 임차자산 에너지: 임차 창고 전기(추정) | 3000.0 kWh | `user_factor` | 1251.9 |
| cat9_downstream_transport.csv#1 | S3 | 다운스트림 운송·유통: 제품 배송 트럭(30t×200km) | 6000.0 tonne-km | `freight_hgv` | 585.12 |
| cat9_downstream_transport.csv#2 | S3 | 다운스트림 운송·유통: 수출 해상운송(100t×500km) | 50000.0 tonne-km | `freight_ship_container` | 806.0 |
| 주유_경유_202605.png→cat3 | S3 | 연료·에너지 상류(WTT/T&D): 경유 주유 | 50.0 L | `wtt_diesel` | 30.551 |
| 전기_한전_202605.png→cat3 | S3 | 연료·에너지 상류(WTT/T&D): 전력 사용 | 500.0 kWh | `wtt_electricity_kr` | 22.95 |
| 전기_한전_202605.png→cat3 | S3 | 연료·에너지 상류(WTT/T&D): 전력 사용 | 500.0 kWh | `td_electricity_kr` | 9.15 |

## 5. 사용된 배출계수 · 출처 (부록)

| factor_id | 값 | 단위 | 신뢰수준 | 연도 | GWP | 출처 | 비고(한계·누락) |
|---|---|---|---|---|---|---|---|
| `travel_rail_ktx` | 0.0269 | kgCO2eq/passenger-km | 학술 | 2021 | 확인 필요 | 배준형·김진준·어성욱, 「고속철도 온실가스 감축량 산정을 위한 교통수단별 비교 연구」, 한 | KTX 26.9 gCO2eq/인·km. KTX 한정 — 무궁화·ITX·SRT 별도 공표값 없음(잠정 동일 적용). 26.9의  |
| `fuel_diesel` | 2.577 | kgCO2/L | 국가공식 | 2017 | SAR(3차 계획기간) | 온실가스 배출권거래제 지침 [별표 12] (Tier2) | CO2만 반영. CH4·N2O는 연소형태별 가산 필요. |
| `electricity_kr` | 0.4173 | kgCO2eq/kWh | 국가공식 | 2023 | AR5('06 IPCC 지침 기준 — 공표문 각주 명시) | 「2025년 승인 국가 온실가스 배출·흡수계수」 전력배출계수, '23년 소비단 CO2-eq | location-based 단일. market-based(녹색프리미엄·REC·PPA) 미반영. 소비단=소내소비·양수전력·송배전 |
| `commute_subway` | 0.0278 | kgCO2eq/passenger-km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, London Underground (한국 지하철 공식 인· | 한국 전력믹스가 영국보다 탄소집약적이라 과소 가능성. 서울교통공사 지속가능경영보고서 실측 확보 시 교체 예정. |
| `commute_bus_local` | 0.10846 | kgCO2eq/passenger-km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Average local bus |  |
| `commute_car_petrol` | 0.1645 | kgCO2eq/km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Average car/Petrol | 차량당(vehicle·km). 1인 탑승 가정이면 그대로, 카풀 시 탑승인원으로 나눔. |
| `commute_car_hybrid` | 0.12607 | kgCO2eq/km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Average car/Hybrid | 차량당. |
| `spend_category1_USER` | None | kgCO2eq/KRW | 사용자입력 | None | None | 사용자 입력 필수 — 현행·공개·무료의 한국 지출기반 산업계수표 부재(Phase 0 조사  | spend.csv의 factor·factor_source 열에 사용자가 직접 계수와 출처를 입력해야 산정된다. 실무 관행 소스 |
| `user_factor` | 행별 |  | 사용자입력 |  |  | 행별 factor_source 참조(건별 명세) |  |
| `waste_plastic_landfill` | 8.88386 | kgCO2eq/tonne | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Waste disposal (Plastics: averag | 카테고리 5·12 공용. |
| `fuel_citygas_lng` | 2.182 | kgCO2/Nm3 | 국가공식 | 2017 | SAR(3차 계획기간) | 온실가스 배출권거래제 지침 [별표 12] (Tier2) | 단위=Nm³(부피). 고지서가 열량단가제로 총발열량 MJ를 청구하면 순/총 보정(≈0.903) 후 적용하거나, 계량 m³를 순 |
| `pcaf_financed` | 행별 |  | 사용자입력 |  |  | 행별 factor_source 참조(건별 명세) |  |
| `freight_hgv` | 0.09752 | kgCO2eq/tonne-km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Freighting goods (All HGVs, aver | 카테고리 4(업스트림)·9(다운스트림) 공용. 활동량=톤×km. 한국 완제 tonne-km 계수 부재로 DEFRA 대체. |
| `freight_rail` | 0.02779 | kgCO2eq/tonne-km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Freighting goods (Rail, freight  | 활동량=톤×km(사용자가 선곱해 입력). 카테고리 4·9 공용. |
| `waste_mixed_landfill` | 520.3342 | kgCO2eq/tonne | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Waste disposal (Commercial and i | 카테고리 5(사업장 폐기물)·12(제품 폐기) 공용. 한국 환경부 완제 tonne당 계수 부재로 DEFRA 대체. |
| `waste_recycling` | 6.41061 | kgCO2eq/tonne | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Waste disposal (recycling, close | ⚠️ 처리공정만 반영(재질 무관 동일값). 재활용의 회피배출(avoided) 크레딧은 미포함 — 별도 방법론. 카테고리 5·1 |
| `freight_ship_container` | 0.01612 | kgCO2eq/tonne-km | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Freighting goods (Cargo ship, co | 활동량=톤×km(사용자가 선곱해 입력). 카테고리 4·9 공용. |
| `wtt_diesel` | 0.61101 | kgCO2eq/L | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, WTT- fuels (diesel average) | Scope 1 경유 연소(fuel_diesel)에서 자동 파생. |
| `wtt_electricity_kr` | 0.0459 | kgCO2eq/kWh | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, WTT- UK electricity (generation) | ⚠️ UK 전력 상류 프록시 — 한국 발전믹스와 다르다. 규제용 부적합, 자사 값 확보 시 교체. Scope 2 전력에서 자동 |
| `td_electricity_kr` | 0.0183 | kgCO2eq/kWh | 해외정부공식 | 2024 | AR5(DEFRA) | DEFRA/DESNZ 2024, Transmission and distribution —  | ⚠️ UK 송배전 손실 프록시 — 한국 손실률(~3.5%)·발전계수와 다르다. 규제용 부적합. Scope 2 전력에서 자동 파 |

> 비고의 '한계·누락'을 확인할 것. 예: 연료계수는 **CO2만 반영**(CH4·N2O 별도 가산 필요), 전력 WTT/T&D는 UK 프록시 등 — 헤드라인 수치에 영향. (전력계수 0.4173은 gir 원문 검증 완료 — GWP=AR5.)

---

> ⚠️ **면책** — 본 리포트는 조직 탄소발자국 **추정**이다. 배출권거래제·목표관리제 명세서 등 규제 신고용이 아니다. 거리기반·지출기반 산정은 명세서 방법론과 다르며, 계수 일부는 해외정부공식·학술·사용자입력 등급이다. 신고 전 소관기관(gir.go.kr·한국환경공단)의 확정계수·최신 고시로 재검증할 것.
