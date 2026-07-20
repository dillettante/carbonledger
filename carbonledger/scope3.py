"""Scope 3 카테고리 2~15 자동 산정 (카테고리 1·6·7은 각각 spend/travel/commute에서 처리).

핵심 통찰: 12개 '나머지' 카테고리는 데이터 소스가 제각각이지만 계산은 모두 같다 —
    활동량 × 배출계수 = 배출량.
따라서 카테고리마다 특수 코드를 짜지 않고, **통일된 CSV 행 스키마** 하나로 전부 처리한다:

    각 행 = 활동량(activity) + 단위(unit) + 계수
      · 계수가 레지스트리에 있으면      → factor_id 열로 지정(단위 검증됨)
      · 권위 계수가 없으면(예: 지출기반) → factor + factor_source 열로 사용자 입력(출처 강제)

이로써 카테고리 2·4·5·8·9·10·11·12·13·14가 코드 한 벌로 자동화된다.
예외 둘은 계산 형태가 달라 전용 함수를 둔다:
  · 카테고리 3(연료·에너지 관련) = 신규 입력 0, 이미 산정된 Scope 1·2에서 파생(WTT/T&D)
  · 카테고리 15(투자)          = PCAF 귀속공식(포트폴리오 × 귀속계수 × 피투자 배출)

입력: input/scope3/cat{N}_*.csv  (예: cat4_upstream_transport.csv)
"""
import csv
from pathlib import Path

from . import calc, factors, validate

# CSV로 자동 산정하는 카테고리(2~14 중 3 제외). 값은 표시용 활동 설명.
CSV_CATEGORIES = {
    2: "자본재(취득)",
    4: "업스트림 운송·유통",
    5: "사업장 폐기물",
    8: "업스트림 임차자산 에너지",
    9: "다운스트림 운송·유통",
    10: "판매제품 가공",
    11: "판매제품 사용",
    12: "판매제품 폐기",
    13: "다운스트림 임대자산 에너지",
    14: "프랜차이즈 에너지",
}


def _resolve_factor(row: dict) -> tuple[float, str, str, str]:
    """행에서 계수를 해석. 반환: (계수값, 계수단위, factor_id, 출처).

    우선순위: factor_id(레지스트리) > factor+factor_source(사용자 입력).
    둘 다 없거나 사용자 계수에 출처가 없으면 ValueError(→ review 큐).
    """
    fid = (row.get("factor_id") or "").strip()
    if fid:
        rec = factors.get(fid)  # 미등록·미확정이면 FactorError
        return rec["value"], rec["unit"], fid, rec.get("source", "")
    f = validate._num(row.get("factor"))
    src = (row.get("factor_source") or "").strip()
    if f is not None and f > 0:
        if not src:
            raise ValueError("factor_source(계수 출처) 필수 — 감사추적")
        return f, "", "user_factor", src
    raise ValueError("계수 없음 — factor_id(레지스트리) 또는 factor+factor_source(사용자) 필요")


def process_csv(csv_path: Path, category: int, records: list, queue: list):
    """통일 스키마 CSV → 카테고리 N 배출 레코드. 카테고리 2·4·5·8~14 공통.

    필수 열: activity(활동량), unit(활동단위), 그리고 계수(factor_id 또는 factor+factor_source).
    선택 열: item/desc(설명).
    """
    label = CSV_CATEGORIES.get(category, f"카테고리{category}")
    with csv_path.open(encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), 1):
            src_id = f"{csv_path.name}#{i}"
            try:
                activity = validate._num(row.get("activity"))
                unit = (row.get("unit") or "").strip()
                if activity is None or activity <= 0:
                    raise ValueError(f"활동량 비정상: {row.get('activity')!r}")
                if not unit:
                    raise ValueError("단위(unit) 누락")
                fval, funit, fid, fsrc = _resolve_factor(row)
                # 레지스트리 계수면 단위 일치 강제(사용자 계수는 단위 자유)
                if funit and funit.split("/")[-1] != unit:
                    raise ValueError(f"활동단위 {unit!r}가 계수분모 {funit.split('/')[-1]!r}와 불일치")
                rec = {
                    "source_file": src_id, "scope": 3, "category": category,
                    "activity": f"{label}: {row.get('item') or row.get('desc') or ''}".strip(),
                    "factor_id": fid, "factor_value": fval,
                    "factor_unit": funit or f"kgCO2eq/{unit}",
                    "activity_value": activity, "activity_unit": unit,
                    "kgco2e": round(fval * activity, 3), "extracted": row,
                }
                if fid == "user_factor":
                    rec["factor_source"] = fsrc
                records.append(rec)
            except Exception as ex:
                queue.append({"source_file": src_id, "issues": [f"{label} 처리 실패: {ex}"]})


def derive_category3(records: list, queue: list):
    """카테고리 3(연료·에너지 관련) — 신규 입력 없이 기존 Scope 1·2에서 파생.

    구매 연료·전력의 상류배출: 연료 WTT(채굴·정제·수송) + 전력 WTT(발전연료) + T&D(송배전손실).
    이미 산정된 Scope 1 연료·Scope 2 전력 활동량에 WTT/T&D 계수를 곱한다.
    WTT/T&D 계수가 factors.json에 없으면(레지스트리 미비) 조용히 건너뛴다 — 억지 산정 안 함.
    """
    # 활동량을 계수 조회 가능한 factor_id에 매핑(연료 L/Nm3, 전력 kWh)
    wtt_map = {
        "fuel_gasoline": "wtt_gasoline", "fuel_diesel": "wtt_diesel",
        "fuel_citygas_lng": "wtt_citygas_lng",
    }
    for r in list(records):
        if r.get("scope") == 1 and r.get("factor_id") in wtt_map:
            _emit_derived(r, wtt_map[r["factor_id"]], records, queue)
        elif r.get("scope") == 2 and r.get("factor_id") == "electricity_kr":
            # 전력은 WTT(발전연료 상류) + T&D(송배전손실) 둘 다
            for wid in ("wtt_electricity_kr", "td_electricity_kr"):
                _emit_derived(r, wid, records, queue)


def _emit_derived(base: dict, factor_id: str, records: list, queue: list):
    """base 활동량 × WTT/T&D 계수 → 카테고리 3 파생 레코드. 계수 없으면 건너뜀."""
    try:
        rec = factors.get(factor_id)
    except factors.FactorError:
        return  # 계수 미등록 → 파생 생략(리포트 미측정에 남음)
    if rec["unit"].split("/")[-1] != base["activity_unit"]:
        return
    records.append({
        "source_file": base["source_file"] + "→cat3", "scope": 3, "category": 3,
        "activity": f"연료·에너지 상류(WTT/T&D): {base.get('activity','')}",
        "factor_id": factor_id, "factor_value": rec["value"], "factor_unit": rec["unit"],
        "activity_value": base["activity_value"], "activity_unit": base["activity_unit"],
        "kgco2e": round(rec["value"] * base["activity_value"], 3),
        "derived_from": base["source_file"],
    })


def process_pcaf(csv_path: Path, records: list, queue: list):
    """카테고리 15(투자) — PCAF 귀속공식. 금융배출량 = 귀속계수 × 피투자 배출.

    행 스키마: asset(자산명), asset_class, outstanding(투자·대출 잔액),
               denominator(EVIC 또는 총자본+부채), investee_emissions(피투자 tCO2e).
    귀속계수 = outstanding / denominator. financed = 귀속계수 × investee_emissions.
    """
    with csv_path.open(encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), 1):
            src_id = f"{csv_path.name}#{i}"
            try:
                out = validate._num(row.get("outstanding"))
                denom = validate._num(row.get("denominator"))
                inv = validate._num(row.get("investee_emissions"))  # tCO2e
                if not (out and denom and inv is not None):
                    raise ValueError("outstanding·denominator·investee_emissions 필수")
                if denom <= 0 or out <= 0:
                    raise ValueError("잔액·분모는 양수")
                attribution = out / denom
                inv_kg = inv * 1000  # 피투자 배출 tCO2e → kg (감사 불변식: 계수×활동량=배출량)
                records.append({
                    "source_file": src_id, "scope": 3, "category": 15,
                    "activity": f"투자 {row.get('asset','')} ({row.get('asset_class','')})",
                    "factor_id": "pcaf_financed", "factor_value": round(attribution, 6),
                    "factor_unit": "귀속계수(잔액/기업가치)",
                    "activity_value": round(inv_kg, 3), "activity_unit": "kgCO2eq(피투자)",
                    "kgco2e": round(attribution * inv_kg, 3),  # 귀속계수 × 피투자배출(kg)
                    "extracted": row,
                })
            except Exception as ex:
                queue.append({"source_file": src_id, "issues": [f"투자(PCAF) 처리 실패: {ex}"]})


def selftest():
    import tempfile
    # 통일 스키마 CSV: 레지스트리 계수(전력 재사용) + 사용자 계수 혼합
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cat8_leased.csv"
        p.write_text("item,activity,unit,factor_id,factor,factor_source\n"
                     "임차사무실 전기,1000,kWh,electricity_kr,,\n"
                     "임차창고 추정,500,kWh,,0.5,사내 추정\n", encoding="utf-8")
        recs, q = [], []
        process_csv(p, 8, recs, q)
        assert q == [], f"cat8 예외: {q}"
        assert recs[0]["kgco2e"] == round(0.4173 * 1000, 3), "레지스트리 계수 산정 오류"
        assert recs[1]["kgco2e"] == 250.0 and recs[1]["factor_source"] == "사내 추정", "사용자 계수 오류"

        # 출처 없는 사용자 계수 → 큐
        p2 = Path(d) / "cat2_capital.csv"
        p2.write_text("item,activity,unit,factor,factor_source\n설비,1000000,KRW,0.0004,\n",
                      encoding="utf-8")
        recs2, q2 = [], []
        process_csv(p2, 2, recs2, q2)
        assert recs2 == [] and len(q2) == 1 and "factor_source" in q2[0]["issues"][0], "출처강제 실패"

        # PCAF: 잔액 1억 / 기업가치 10억 = 귀속 0.1, 피투자 500 tCO2e → 50 tCO2e = 50000 kg
        p3 = Path(d) / "cat15_investments.csv"
        p3.write_text("asset,asset_class,outstanding,denominator,investee_emissions\n"
                      "A사 지분,상장주식,100000000,1000000000,500\n", encoding="utf-8")
        recs3, q3 = [], []
        process_pcaf(p3, recs3, q3)
        assert q3 == [] and recs3[0]["kgco2e"] == 50000.0, f"PCAF 산정 오류: {recs3}"

    # 카테고리 3 파생: 경유 100L × WTT 0.61101 = 61.101 kg (WTT 계수 등록됨)
    s1 = [{"scope": 1, "factor_id": "fuel_diesel", "activity_value": 100,
           "activity_unit": "L", "source_file": "x", "activity": "경유"}]
    derive_category3(s1, [])
    cat3 = [r for r in s1 if r.get("category") == 3]
    assert len(cat3) == 1 and cat3[0]["kgco2e"] == round(0.61101 * 100, 3), \
        f"WTT 파생 오류: {cat3}"

    # 미등록 factor_id(WTT 없는 연료)는 파생 건너뜀 — 억지 산정 안 함
    s2 = [{"scope": 1, "factor_id": "fuel_unknown", "activity_value": 100,
           "activity_unit": "L", "source_file": "y", "activity": "x"}]
    derive_category3(s2, [])
    assert not [r for r in s2 if r.get("category") == 3], "미등록 연료에 파생 생성됨"
    print("scope3 selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
