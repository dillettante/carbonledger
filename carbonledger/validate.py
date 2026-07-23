"""검증 관문 — AI가 뽑은 값을 그냥 믿지 않는다.

싼 관문 → 강한 관문 순으로 걸러 통과 못한 것만 사람이 본다(human-in-the-loop).
통과=빈 리스트, 문제=사유 리스트. 사유가 있으면 호출부가 review 큐로 보낸다.

관문:
  ① 형식·스키마 — 날짜꼴·금액 양수·필수 필드
  ② 마스터데이터 대조 — 추출 역명이 실제 역 목록에 있나(오독 적발)
  ③ 폴더-유형 일치 — 폴더가 선언한 scope와 추출된 문서유형이 어긋나나(오분류 적발)
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_STATIONS = Path(__file__).parent / "data" / "stations.json"


@lru_cache(maxsize=1)
def _stations() -> set[str]:
    # stations는 {역명: [위도,경도] 또는 null} — 키(역명)만 마스터 대조에 쓴다.
    return set(json.loads(_STATIONS.read_text(encoding="utf-8"))["stations"])


def validate_transport(rec: dict) -> list[str]:
    """교통 영수증 레코드 검증(관문 ①②)."""
    issues = []
    for f in ("transport", "origin", "destination"):
        if not rec.get(f):
            issues.append(f"필수 누락: {f}")

    amt = _num(rec.get("amount"))  # LLM이 47900.0·"47,900"으로 줘도 관대 파싱
    if rec.get("amount") is not None and (amt is None or amt <= 0):
        issues.append(f"금액 비정상: {rec.get('amount')!r}")

    d = rec.get("date")
    if d is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)):
        issues.append(f"날짜 형식 오류: {d!r}")

    # ② 역명 대조 (철도만) — 오독은 대개 목록에 없는 값을 만든다
    if rec.get("transport") == "철도":
        for f in ("origin", "destination"):
            v = rec.get(f)
            if v and v not in _stations():
                issues.append(f"역명 확인 필요({f}): {v!r} — 마스터 목록에 없음")
    return issues


def validate_hotel(rec: dict) -> list[str]:
    """숙박 영수증 레코드 검증(관문 ①)."""
    issues = []
    n = rec.get("nights")
    if not isinstance(n, int) or n <= 0:
        issues.append(f"박수 비정상: {n!r}")
    elif n > 60:
        issues.append(f"박수 과다(확인 필요): {n}")
    d = rec.get("checkin")
    if d is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)):
        issues.append(f"날짜 형식 오류: {d!r}")
    return issues


def _num(v):
    """숫자로 강제(문자열 '1,234' 허용). 실패 시 None."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def validate_fuel(rec: dict) -> list[str]:
    """주유 영수증 검증(관문 ①+ 교차산술). 고지서엔 역명 마스터가 없어 산술로 대체.

    교차산술: 주유량 × 단가 ≈ 금액 (±5%). AI 오독을 문서 내 자기일관성으로 적발.
    """
    issues = []
    if rec.get("fuel_type") not in ("휘발유", "경유", "LPG", "기타", None):
        issues.append(f"유종 이상: {rec.get('fuel_type')!r}")
    if rec.get("fuel_type") in ("LPG", "기타", None):
        issues.append(f"산정 불가 유종(계수 없음): {rec.get('fuel_type')!r} — 수기 확인")
    liters = _num(rec.get("liters"))
    if liters is None or liters <= 0:
        issues.append(f"주유량 비정상: {rec.get('liters')!r}")
    elif liters > 500:
        issues.append(f"주유량 과다(확인 필요): {liters}L")
    _cross_check(issues, liters, _num(rec.get("unit_price")), _num(rec.get("amount")),
                 "주유량×단가")
    return issues


def validate_gas(rec: dict) -> list[str]:
    """도시가스 고지서 검증(관문 ①)."""
    issues = []
    usage = _num(rec.get("usage"))
    unit = rec.get("unit", "").replace("㎥", "m3").strip()
    if usage is None or usage <= 0:
        issues.append(f"사용량 비정상: {rec.get('usage')!r}")
    if unit not in ("m3", "Nm3", "MJ"):
        issues.append(f"단위 확인 필요: {rec.get('unit')!r} (m3 또는 MJ)")
    # 사용량 sanity: m³면 수천 이하, MJ면 수십만 이하(정규화된 unit으로 판정)
    if usage:
        if unit in ("m3", "Nm3") and usage > 5000:
            issues.append(f"m³ 사용량 과다(확인 필요): {usage}")
        elif unit == "MJ" and usage > 300000:
            issues.append(f"MJ 사용량 과다(확인 필요): {usage}")
    return issues


# 한국 전기요금 상업·산업용 대략 단가 범위(원/kWh) — 금액÷kWh sanity용.
# 오독(자릿수 추가) 시 단가가 이 범위를 벗어난다. 지침이 없어도 작동하는 교차검증.
_ELEC_KRW_PER_KWH = (30, 2000)


def validate_electricity(rec: dict) -> list[str]:
    """전기 고지서 검증(관문 ①+ 교차산술).

    교차검증 2중(지침 결측·고압 배율에도 최소 하나는 작동):
      (a) 금액÷kWh 단가가 상식 범위(30~2000원/kWh) — 지침 없어도 자릿수 오독 적발
      (b) 지침이 둘 다 있으면 지침차 ≤ kWh (배율 CT/PT로 kWh≥지침차 가능, 역전만 이상)
    """
    issues = []
    kwh = _num(rec.get("kwh"))
    amount = _num(rec.get("amount"))
    if kwh is None or kwh <= 0:
        issues.append(f"kWh 비정상: {rec.get('kwh')!r}")
        return issues
    if kwh > 5_000_000:
        issues.append(f"kWh 과다(확인 필요): {kwh}")

    # (a) 금액 기반 단가 sanity — 지침 유무와 무관
    if amount and amount > 0:
        won_per_kwh = amount / kwh
        lo, hi = _ELEC_KRW_PER_KWH
        if not (lo <= won_per_kwh <= hi):
            issues.append(f"단가 이상: 금액÷kWh={won_per_kwh:.0f}원/kWh "
                          f"(상식 {lo}~{hi}) — kWh 또는 금액 오독 의심")

    # (b) 지침 교차검증 — 고압 배율 허용(kWh ≥ 지침차). 역전·지침차>kWh만 적발
    prev, curr = _num(rec.get("prev_reading")), _num(rec.get("curr_reading"))
    if prev is not None and curr is not None:
        diff = curr - prev
        if diff <= 0:
            issues.append(f"지침 역전: 당월{curr} ≤ 전월{prev}")
        elif diff > kwh * 1.05:
            issues.append(f"지침차({diff})가 사용량({kwh})보다 큼 — 오독 의심")
    return issues


def validate_corrected_record(rec: dict) -> list[str]:
    """수기 교정 레코드 검증 관문 — `review` 병합 전에 태운다.

    추출 경로(validate_transport 등)는 문서유형별 원시 필드를 보지만, 교정본은
    이미 산정이 끝난 '레코드'라 검사 대상이 다르다. 사람이 손으로 만든 JSON이
    검증 없이 헤드라인 합계에 직행하는 우회로를 막는 것이 목적이다.

    검사: 필수 필드 · 배출량 부호 · 계수×활동량=배출량 산술 일치 · 교정 이력(누가·언제·왜).
    """
    issues = []
    if not (rec.get("source_file") or "").strip():
        issues.append("source_file 누락 — 어느 건의 교정인지 특정 불가")
    if rec.get("scope") not in (1, 2, 3):
        issues.append(f"scope 이상: {rec.get('scope')!r} (1·2·3 중 하나)")

    kg = _num(rec.get("kgco2e"))
    if kg is None or kg < 0:
        issues.append(f"배출량(kgco2e) 비정상: {rec.get('kgco2e')!r}")

    # 계수·활동량이 있으면 산술 재현 확인 — 감사추적의 핵심 불변식
    fv, av = _num(rec.get("factor_value")), _num(rec.get("activity_value"))
    if kg is not None and fv is not None and av is not None:
        expect = fv * av
        if abs(expect - kg) > max(0.01, 0.01 * max(abs(kg), 1)):
            issues.append(f"산술 불일치: 계수{fv}×활동량{av}={expect:.3f} vs 배출량 {kg}")

    # 교정 이력 강제(통제) — 누가·언제·무엇을 근거로 고쳤는지 없으면 병합 거부
    rv = rec.get("review") or {}
    for k, label in (("reviewer", "교정자"), ("reviewed_at", "교정일시"), ("basis", "교정근거")):
        if not str(rv.get(k, "")).strip():
            issues.append(f"교정 이력 누락: review.{k}({label}) — 감사추적 필수")
    return issues


def _cross_check(issues, qty, price, amount, label):
    """수량 × 단가 ≈ 금액(±5%). 세 값이 다 있을 때만 검사."""
    if qty and price and amount:
        expect = qty * price
        if abs(expect - amount) > max(100.0, 0.05 * amount):
            issues.append(f"{label} 불일치: {qty}×{price}={expect:.0f} vs 금액 {amount:.0f}")


# 폴더가 선언한 scope/category ↔ 허용되는 추출 문서유형
# 폴더별 허용 문서유형(화이트리스트). 미등록 조합은 기본 거부(fail-closed) — 관문 ③.
_FOLDER_ALLOW = {
    "scope1-fuel": {"fuel", "gas"},        # 연료 연소·도시가스 = Scope 1
    "scope2-energy": {"electricity"},      # 전기 = Scope 2
    "travel": {"transport", "hotel"},      # 출장
}


def validate_folder_type(folder_kind: str, doc_type: str) -> list[str]:
    """관문 ③ — 폴더 선언과 추출 유형 일치. 화이트리스트 밖이면 사유 반환(fail-closed).

    input/travel/ 에 전기 고지서, scope2-energy/ 에 주유 영수증 등 오분류를 잡는다.
    Scope 귀속은 폴더가 선언하므로(boundary.md), 예상 밖 유형은 조용히 통과시키지 않는다.
    """
    allow = _FOLDER_ALLOW.get(folder_kind)
    if allow is not None and doc_type not in allow:
        return [f"폴더-유형 불일치: '{folder_kind}' 폴더에 '{doc_type}' 문서 "
                f"(허용: {', '.join(sorted(allow))})"]
    return []


def selftest():
    ok = {"transport": "철도", "origin": "서울", "destination": "부산",
          "date": "2026-07-12", "amount": 59800}
    assert validate_transport(ok) == [], "정상 교통레코드는 통과해야"
    assert any("금액" in i for i in validate_transport({**ok, "amount": -100})), "음수금액 미적발"
    assert any("역명" in i for i in validate_transport({**ok, "origin": "서을"})), "오독역명 미적발"
    assert any("필수" in i for i in validate_transport({**ok, "origin": None})), "필수누락 미적발"
    assert any("날짜" in i for i in validate_transport({**ok, "date": "2026/07/12"})), "날짜 미적발"

    assert validate_hotel({"nights": 2, "checkin": "2026-07-12"}) == [], "정상 숙박 통과해야"
    assert any("박수" in i for i in validate_hotel({"nights": 0})), "박수0 미적발"

    assert validate_folder_type("travel", "transport") == [], "travel-transport 정상"
    assert validate_folder_type("scope1-fuel", "transport"), "연료폴더 교통영수증 미적발"
    assert validate_folder_type("scope2-energy", "gas"), "전기폴더 가스고지서 미적발"
    assert validate_folder_type("scope2-energy", "fuel"), "전기폴더 주유영수증 미적발(화이트리스트)"
    assert validate_folder_type("scope1-fuel", "hotel"), "연료폴더 숙박 미적발(화이트리스트)"

    # 주유 교차산술: 50L × 1700 = 85,000 ≈ 금액이면 통과
    assert validate_fuel({"fuel_type": "경유", "liters": 50, "unit_price": 1700,
                          "amount": 85000}) == [], "정상 주유 통과해야"
    assert any("불일치" in i for i in validate_fuel(
        {"fuel_type": "경유", "liters": 50, "unit_price": 1700, "amount": 200000})), \
        "주유 교차산술 미적발"
    assert any("유종" in i for i in validate_fuel(
        {"fuel_type": "LPG", "liters": 30, "amount": 40000})), "LPG 계수없음 미적발"

    # 전기 (a)금액단가 교차검증: 500kWh·106975원 = 214원/kWh 정상
    assert validate_electricity({"kwh": 500, "amount": 106975,
                                 "prev_reading": 12000, "curr_reading": 12500}) == [], \
        "정상 전기 통과해야"
    # 지침 없어도 자릿수 오독 적발: 5000kWh·106975원 = 21원/kWh
    assert any("단가" in i for i in validate_electricity({"kwh": 5000, "amount": 106975})), \
        "금액단가 오독 미적발(지침 없음)"
    # 고압 배율 정상: 지침차 250 < kWh 500000 (배율 2000) — 통과해야
    assert validate_electricity({"kwh": 500000, "amount": 80_000_000,
                                 "prev_reading": 1000, "curr_reading": 1250}) == [], \
        "고압 배율을 오탐"
    # 지침 역전 적발
    assert any("역전" in i for i in validate_electricity(
        {"kwh": 300, "amount": 60000, "prev_reading": 1500, "curr_reading": 1000})), \
        "지침 역전 미적발"
    # kWh 상한
    assert any("과다" in i for i in validate_electricity({"kwh": 6_000_000, "amount": 1})), \
        "kWh 상한 미적발"

    # 도시가스 단위·상한
    assert validate_gas({"usage": 50, "unit": "m3"}) == [], "정상 가스 통과해야"
    assert validate_gas({"usage": 50, "unit": "㎥"}) == [], "㎥ 글리프 정상처리해야"
    assert any("단위" in i for i in validate_gas({"usage": 50, "unit": "L"})), "가스 단위 미적발"
    assert any("MJ" in i for i in validate_gas({"usage": 999999, "unit": "MJ"})), "MJ 상한 미적발"
    assert any("m³" in i for i in validate_gas({"usage": 6000, "unit": "㎥"})), \
        "m³ 상한(㎥ 글리프) 미적발"
    print("validate selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
