"""배출계수 레지스트리 로더 (data/factors.json).

계수를 코드에 하드코딩하지 않는 이유: 공개 배포 툴의 신뢰성은 "이 숫자가 어느
출처·연도·신뢰수준인가"를 기계적으로 추적할 수 있느냐에 달렸다. 모든 배출량 레코드는
factor_id를 달고 다니고, 리포트는 이 레지스트리로 출처 부록을 자동 생성한다.

get(factor_id, expect_unit=...) 는 단위 문자열을 검사한다 — kWh 활동량에 연료계수(/L)를
곱하는 실수를 조회 시점에 예외로 잡는다(7단계 검증 깔때기의 '산술 검증'을 구조로 흡수).
"""
import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "factors.json"


class FactorError(ValueError):
    """계수 부재·단위 불일치·미확정(사용자입력 필요) 등 조회 실패."""


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def meta() -> dict:
    return _load()["_meta"]


def get(factor_id: str, expect_unit: str | None = None) -> dict:
    """factor_id로 계수 레코드를 조회. expect_unit을 주면 단위 일치를 강제한다.

    반환: {value, unit, source, confidence, ...} 전체 레코드(+ id 필드).
    value가 null(사용자입력 필수)이거나 단위가 어긋나면 FactorError.
    """
    reg = _load()
    if factor_id not in reg:
        raise FactorError(f"미등록 계수: {factor_id!r}")
    rec = dict(reg[factor_id])
    rec["id"] = factor_id

    if rec.get("value") is None:
        raise FactorError(
            f"{factor_id}: 계수값 미확정({rec.get('confidence')}) — {rec.get('note','')}"
        )
    if expect_unit is not None and rec.get("unit") != expect_unit:
        raise FactorError(
            f"{factor_id}: 단위 불일치 — 기대 {expect_unit!r}, 실제 {rec.get('unit')!r}"
        )
    return rec


def all_used(factor_ids) -> list[dict]:
    """리포트 출처 부록용 — 사용된 factor_id들의 레코드를 중복 없이 반환.

    레지스트리에 없는 id(user_factor·pcaf_financed 등 사용자 입력·공식 산정)는
    스텁으로 표기한다 — 실제 계수·출처는 각 배출 레코드의 factor_source에 있다.
    """
    reg = _load()
    seen, out = set(), []
    for fid in factor_ids:
        if fid and fid not in seen:
            seen.add(fid)
            if fid in reg:
                r = dict(reg[fid])
            else:
                r = {"value": "행별", "unit": "", "confidence": "사용자입력",
                     "source": "행별 factor_source 참조(건별 명세)"}
            r["id"] = fid
            out.append(r)
    return out


def selftest():
    reg = _load()
    assert "_meta" in reg and "electricity_kr" in reg, "레지스트리 구조 이상"

    e = get("electricity_kr", expect_unit="kgCO2eq/kWh")
    assert e["value"] == 0.4173 and e["confidence"] == "국가공식", "전력계수 조회 오류"

    # 단위 불일치는 예외
    try:
        get("fuel_gasoline", expect_unit="kgCO2eq/kWh")
        assert False, "단위 불일치를 못 잡음"
    except FactorError:
        pass

    # 사용자입력 필수 계수(value null)는 예외
    try:
        get("spend_category1_USER")
        assert False, "미확정 계수를 통과시킴"
    except FactorError:
        pass

    used = all_used(["fuel_diesel", "fuel_diesel", "electricity_kr"])
    assert len(used) == 2, "중복 제거 실패"
    print("factors selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
