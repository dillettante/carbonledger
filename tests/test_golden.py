"""Golden 대조 — LLM 추출을 목킹해 파이프라인(추출→검증→산정→집계)을 결정론 검증.

실제 비전 LLM·Kakao 없이 CI에서 돈다. 추출 결과를 고정 주입하고, 기대 배출량을
숫자로 못 박는다. 산정 로직이 바뀌면 여기서 실패한다.

실행: python3 -m pytest tests/  또는  python3 tests/test_golden.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carbonledger import calc, cli, extract  # noqa: E402


def test_commute_golden(tmp_path):
    """examples/commute.csv → 통근 배출량 골든값."""
    src = Path(__file__).resolve().parents[1] / "examples" / "input" / "commute.csv"
    records, queue = [], []
    cli._process_commute(src, records, queue)

    assert queue == [], f"통근 처리에 예외: {queue}"
    assert len(records) == 4

    # E001 지하철: 18km ×2 ×220일 = 7920km × 0.02780 = 220.176
    e1 = next(r for r in records if r["source_file"].endswith("#1"))
    assert e1["kgco2e"] == round(7920 * 0.02780, 3) == 220.176

    # E003 승용차 휘발유: 25 ×2 ×220 = 11000km × 0.16450 = 1809.5
    e3 = next(r for r in records if r["source_file"].endswith("#3"))
    assert e3["kgco2e"] == round(11000 * 0.16450, 3)


def test_spend_requires_source(tmp_path):
    """지출: factor_source 없으면 큐로(감사추적 강제)."""
    csv = tmp_path / "spend.csv"
    csv.write_text("item,krw,factor,factor_source\nX,1000000,0.0005,\n", encoding="utf-8")
    records, queue = [], []
    cli._process_spend(csv, records, queue)
    assert records == [] and len(queue) == 1, "출처 없는 지출을 통과시킴"
    assert "factor_source" in queue[0]["issues"][0]


def test_travel_pipeline_mocked(tmp_path, monkeypatch):
    """travel 폴더 → 추출·거리 목킹 → 리포트 골든값."""
    travel = tmp_path / "travel"
    travel.mkdir()
    (travel / "ktx.jpg").write_bytes(b"\x89PNG fake")

    # LLM 추출·Kakao 거리를 고정값으로 목킹
    monkeypatch.setattr(extract, "extract", lambda *a, **k: {
        "transport": "철도", "origin": "서울", "destination": "부산",
        "date": "2026-05-01", "amount": 59800})
    monkeypatch.setattr(calc, "distance_km", lambda o, d, t: 400.0)

    records, queue = [], []
    cli._process_travel(travel, "mock-model", "2026", records, queue)

    assert queue == [], f"목킹 파이프라인에 예외: {queue}"
    assert len(records) == 1
    # 400km × 0.0269 = 10.76
    assert records[0]["kgco2e"] == round(400 * 0.0269, 3) == 10.76
    assert records[0]["scope"] == 3 and records[0]["category"] == 6


def test_period_filter(tmp_path, monkeypatch):
    """보고기간 밖 레코드는 집계 제외."""
    travel = tmp_path / "travel"
    travel.mkdir()
    (travel / "old.jpg").write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(extract, "extract", lambda *a, **k: {
        "transport": "철도", "origin": "서울", "destination": "부산",
        "date": "2024-01-01", "amount": 50000})
    monkeypatch.setattr(calc, "distance_km", lambda o, d, t: 400.0)

    records, queue = [], []
    cli._process_travel(travel, "mock", "2026", records, queue)
    assert records == [] and len(queue) == 1
    assert "보고기간 밖" in queue[0]["issues"][0]


def test_bills_pipeline_mocked(tmp_path, monkeypatch):
    """scope1-fuel/ scope2-energy/ 고지서 → 추출 목킹 → Scope1·2 골든값."""
    from carbonledger import validate  # noqa

    fuel = tmp_path / "scope1-fuel"; fuel.mkdir()
    (fuel / "주유_202605.jpg").write_bytes(b"\x89PNG fake")
    energy = tmp_path / "scope2-energy"; energy.mkdir()
    (energy / "전기_202605.jpg").write_bytes(b"\x89PNG fake")

    def fake_extract(path, doc_type, model):
        if doc_type == "fuel":
            return {"doc": "주유", "fuel_type": "경유", "liters": 50,
                    "unit_price": 1700, "amount": 85000, "date": "2026-05-10"}
        return {"doc": "전기", "kwh": 500, "prev_reading": 12000,
                "curr_reading": 12500, "amount": 95000, "billing_month": "2026-05"}
    monkeypatch.setattr(extract, "extract", fake_extract)

    records, queue = [], []
    cli._process_bills(fuel, "scope1-fuel", "mock", "2026", records, queue)
    cli._process_bills(energy, "scope2-energy", "mock", "2026", records, queue)

    assert queue == [], f"고지서 파이프라인 예외: {queue}"
    s1 = next(r for r in records if r["scope"] == 1)
    s2 = next(r for r in records if r["scope"] == 2)
    assert s1["kgco2e"] == round(2.577 * 50, 3)   # 경유 50L
    assert s2["kgco2e"] == round(0.4173 * 500, 3)  # 전력 500kWh


def test_folder_type_mismatch_to_queue(tmp_path, monkeypatch):
    """전기 폴더에 가스 고지서(파일명 힌트) → 오분류로 review 큐(관문 ③)."""
    energy = tmp_path / "scope2-energy"; energy.mkdir()
    (energy / "가스_202605.jpg").write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(extract, "extract", lambda *a, **k: {
        "doc": "도시가스", "usage": 50, "unit": "m3", "amount": 40000,
        "billing_month": "2026-05"})
    records, queue = [], []
    cli._process_bills(energy, "scope2-energy", "mock", "2026", records, queue)
    assert records == [] and len(queue) == 1, "오분류를 통과시킴"
    assert any("불일치" in i for i in queue[0]["issues"]), "폴더-유형 관문 미작동"


def test_guess_bill_type_gasoline(tmp_path):
    """'gasoline' 파일명이 gas로 오매칭되지 않아야(fuel 우선)."""
    assert cli._guess_bill_type(Path("gasoline_202605.jpg"), "scope1-fuel") == "fuel"
    assert cli._guess_bill_type(Path("도시가스_202605.jpg"), "scope1-fuel") == "gas"
    assert cli._guess_bill_type(Path("전기_202605.jpg"), "scope2-energy") == "electricity"


def test_bill_date_null_fail_closed(tmp_path, monkeypatch):
    """고지서 날짜(billing_month) 결측 + period 지정 → review 큐(fail-closed)."""
    energy = tmp_path / "scope2-energy"; energy.mkdir()
    (energy / "전기_x.jpg").write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(extract, "extract", lambda *a, **k: {
        "doc": "전기", "kwh": 500, "amount": 106975,
        "prev_reading": 12000, "curr_reading": 12500, "billing_month": None})
    records, queue = [], []
    cli._process_bills(energy, "scope2-energy", "mock", "2026", records, queue)
    assert records == [] and len(queue) == 1, "날짜 결측을 조용히 포함(fail-open)"
    assert "보고기간 확인 불가" in queue[0]["issues"][0]


def test_scope3_freight_waste_golden(tmp_path):
    """카테고리 4·5 레지스트리 계수(DEFRA freight/waste) 골든값."""
    from carbonledger import scope3
    f = tmp_path / "cat4_transport.csv"
    f.write_text("item,activity,unit,factor_id,factor,factor_source\n"
                 "트럭,15000,tonne-km,freight_hgv,,\n", encoding="utf-8")
    recs, q = [], []
    scope3.process_csv(f, 4, recs, q)
    assert q == [] and recs[0]["kgco2e"] == round(0.09752 * 15000, 3), "freight 산정 오류"

    w = tmp_path / "cat5_waste.csv"
    w.write_text("item,activity,unit,factor_id,factor,factor_source\n"
                 "매립,2,tonne,waste_mixed_landfill,,\n", encoding="utf-8")
    recs2, q2 = [], []
    scope3.process_csv(w, 5, recs2, q2)
    assert q2 == [] and recs2[0]["kgco2e"] == round(520.3342 * 2, 3), "waste 산정 오류"


def test_scope3_cat3_derivation_golden(tmp_path):
    """카테고리 3 파생: Scope 1 경유 + Scope 2 전력에서 WTT/T&D 자동 산출."""
    from carbonledger import scope3
    recs = [
        {"scope": 1, "factor_id": "fuel_diesel", "activity_value": 50,
         "activity_unit": "L", "source_file": "fuel", "activity": "경유"},
        {"scope": 2, "factor_id": "electricity_kr", "activity_value": 500,
         "activity_unit": "kWh", "source_file": "elec", "activity": "전력"},
    ]
    scope3.derive_category3(recs, [])
    cat3 = [r for r in recs if r.get("category") == 3]
    # 경유 50×0.61101 + 전력 500×(0.0459 WTT + 0.0183 T&D)
    total = round(sum(r["kgco2e"] for r in cat3), 3)
    assert total == round(50 * 0.61101 + 500 * 0.0459 + 500 * 0.0183, 3), f"cat3 파생 오류: {total}"


def test_review_merge_idempotent(tmp_path):
    """review 재실행이 교정본을 이중 계상하지 않고, 교정된 건은 큐에서 빠져야."""
    records = [
        {"source_file": "a.jpg", "scope": 2, "kgco2e": 100.0},
        {"source_file": "b.jpg", "scope": 2, "kgco2e": 200.0},
    ]
    queue = [{"source_file": "c.jpg", "issues": ["보고기간 확인 불가"]}]
    corrected = [{"source_file": "c.jpg", "scope": 2, "kgco2e": 50.0, "human_corrected": True}]

    merged, remaining = cli._merge_reviewed(records, queue, corrected)
    assert sum(r["kgco2e"] for r in merged) == 350.0, "1차 병합 합계 오류"
    assert remaining == [], "교정된 건이 큐에 남음(미포함으로 오표시)"

    # 2차 실행: 이미 병합된 원장에 같은 교정본을 또 넣어도 합계 불변(멱등)
    merged2, _ = cli._merge_reviewed(merged, remaining, corrected)
    assert sum(r["kgco2e"] for r in merged2) == 350.0, "review 재실행에 이중 계상"
    assert len(merged2) == 3, "레코드 중복"

    # 원본 재추출 건을 교정본이 '대체'하는지
    merged3, _ = cli._merge_reviewed(records, [], [{"source_file": "a.jpg", "kgco2e": 999.0}])
    assert sum(r["kgco2e"] for r in merged3) == 1199.0, "교정본이 원본을 대체하지 않음"


if __name__ == "__main__":
    import tempfile

    class _P:  # monkeypatch 대체(순수 실행용)
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    for fn, needs_mp in [(test_commute_golden, False), (test_spend_requires_source, False),
                         (test_travel_pipeline_mocked, True), (test_period_filter, True),
                         (test_bills_pipeline_mocked, True),
                         (test_folder_type_mismatch_to_queue, True),
                         (test_guess_bill_type_gasoline, False),
                         (test_bill_date_null_fail_closed, True),
                         (test_scope3_freight_waste_golden, False),
                         (test_scope3_cat3_derivation_golden, False),
                         (test_review_merge_idempotent, False)]:
        with tempfile.TemporaryDirectory() as d:  # 테스트마다 새 tmp(충돌 방지)
            fn(Path(d), _P()) if needs_mp else fn(Path(d))
    print("golden 테스트 11종 통과 ✅")
