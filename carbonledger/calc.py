"""활동량 → 배출량 산정. Scope별 산정 함수 + 거리 계산.

거리: 출발·도착 지명을 Kakao Local로 좌표화 → haversine(대권거리).
Phase 0 조사 반영:
  · 철도 = 대권거리 × 우회계수 1.2 (간선 역쌍별 실거리 공개데이터 부재 → 근사)
  · 항공 = 대권거리 원값 (DEFRA 계수에 우회 uplift 8% 내장 → 추가 보정 시 이중계산)
"""
import json
import math
import os
from functools import lru_cache
from pathlib import Path

from . import factors

KAKAO_LOCAL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_GEOCODE = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
_STATIONS = Path(__file__).parent / "data" / "stations.json"


@lru_cache(maxsize=1)
def _station_coords() -> dict:
    """역명 → (위도,경도) 내장 좌표. 좌표 없는(null) 역은 제외."""
    raw = json.loads(_STATIONS.read_text(encoding="utf-8"))["stations"]
    return {k: tuple(v) for k, v in raw.items() if v}

# 수단 → (배출계수 factor_id, 거리 우회계수)
_TRANSPORT = {
    "철도": ("travel_rail_ktx", 1.2),
    "항공": ("travel_air_domestic", 1.0),
    "버스": ("travel_bus_intercity", 1.2),   # 시외·고속 기본. 시내는 travel_bus_local
}


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 (위도,경도) 사이 대권거리 km. 지구 반경 6371km."""
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = math.radians(b[0] - a[0])
    dlmb = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _kakao_geocode(place: str, key: str) -> tuple[float, float] | None:
    import requests
    r = requests.get(KAKAO_LOCAL, params={"query": place},
                     headers={"Authorization": f"KakaoAK {key}"}, timeout=15)
    r.raise_for_status()
    docs = r.json().get("documents", [])
    if not docs:
        return None
    d = docs[0]
    return (float(d["y"]), float(d["x"]))  # y=위도, x=경도


def _naver_geocode(place: str, cid: str, csec: str) -> tuple[float, float] | None:
    """네이버 클라우드 플랫폼 Geocoding(주소→좌표). Kakao 대안."""
    import requests
    r = requests.get(NAVER_GEOCODE, params={"query": place}, timeout=15,
                     headers={"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": csec})
    r.raise_for_status()
    docs = r.json().get("addresses", [])
    if not docs:
        return None
    d = docs[0]
    return (float(d["y"]), float(d["x"]))  # y=위도, x=경도


def _api_geocode(place: str) -> tuple[float, float] | None:
    """지도 API로 지명→좌표. Kakao 우선, 없으면 Naver. 둘 다 키 없으면 None."""
    kakao = os.environ.get("KAKAO_REST_API_KEY")
    if kakao:
        return _kakao_geocode(place, kakao)
    ncid = os.environ.get("NAVER_MAP_CLIENT_ID")
    ncsec = os.environ.get("NAVER_MAP_CLIENT_SECRET")
    if ncid and ncsec:
        return _naver_geocode(place, ncid, ncsec)
    return None


def _coords(place: str, transport: str) -> tuple[float, float] | None:
    """지명 → 좌표. 철도역은 내장 좌표 우선(오프라인·지명 외부전송 없음), 없으면 지도 API."""
    if transport == "철도":
        c = _station_coords().get(place)
        if c:
            return c
    suffix = "역" if transport == "철도" else ""
    return _api_geocode(place + suffix)


def distance_km(origin: str, destination: str, transport: str) -> float | None:
    """구간 거리(km). 철도역은 내장 좌표로 오프라인 산정, 그 외/미등재는 지도 API 폴백.

    지도 API = Kakao(KAKAO_REST_API_KEY) 우선, 없으면 Naver(NAVER_MAP_CLIENT_ID/SECRET).
    셋 다 없으면(내장좌표도, 키도) None → 호출부가 review 큐로.
    ⚠️ 대권거리 근사. 철도·버스는 ×1.2 우회계수로 실노선 근사(그래도 부정확 가능).
    """
    a = _coords(origin, transport)
    b = _coords(destination, transport)
    if not a or not b:
        return None
    _, detour = _TRANSPORT.get(transport, ("", 1.0))
    return round(haversine(a, b) * detour, 1)


# ── Scope별 배출량 산정 ────────────────────────────────────────────
def _emit(factor_id: str, activity_value: float, activity_unit: str) -> dict:
    """공통: 계수 조회 × 활동량 → 배출 레코드 조각. 활동단위와 계수분모 일치를 강제."""
    rec = factors.get(factor_id)
    factor_unit = rec["unit"]
    # factor 단위의 분모가 활동 단위와 맞는지 확인 (예: kgCO2/L ↔ 활동 L)
    denom = factor_unit.split("/")[-1]
    if denom != activity_unit:
        raise factors.FactorError(
            f"{factor_id}: 활동단위 {activity_unit!r}가 계수분모 {denom!r}와 불일치"
        )
    return {
        "factor_id": factor_id,
        "factor_value": rec["value"],
        "factor_unit": factor_unit,
        "activity_value": activity_value,
        "activity_unit": activity_unit,
        "kgco2e": round(rec["value"] * activity_value, 3),
    }


def scope1_fuel(fuel_type: str, liters_or_nm3: float) -> dict:
    """Scope 1 연료 연소. fuel_type: 휘발유|경유|도시가스."""
    fid = {"휘발유": "fuel_gasoline", "경유": "fuel_diesel",
           "도시가스": "fuel_citygas_lng"}[fuel_type]
    unit = "Nm3" if fuel_type == "도시가스" else "L"
    return _emit(fid, liters_or_nm3, unit)


# 도시가스(LNG) 총발열량(GCV, gross) MJ/Nm³ — 배출권거래제 지침 별표12 발열량표.
# 열량단가제 고지서의 MJ(총발열량 기준)를 Nm³ 부피로 되돌릴 때 쓴다.
# 배출계수(순발열량 NCV 38.9 기준)와 짝을 이뤄 순/총 보정이 자동 적용된다.
_GAS_GCV_PER_NM3 = 43.1


def scope1_citygas(usage: float, unit: str) -> dict:
    """Scope 1 도시가스. 계량 m³(≈Nm³ 근사) 또는 열량단가제 MJ(총발열량) 입력.

    Phase 0 함정: 고지서 MJ는 총발열량(GCV) 기준, 계수 56,100 kgCO2/TJ는 순발열량(NCV) 기준.
    MJ 입력 시 GCV 43.1 MJ/Nm³로 나눠 Nm³ 부피로 되돌린 뒤 순발열량 계수를 적용한다
    (MJ에 순발열량 계수를 직접 곱하면 GCV/NCV 비율만큼 ~10% 과대산정).
    """
    u = unit.replace("㎥", "m3").strip()
    if u in ("m3", "Nm3"):
        return _emit("fuel_citygas_lng", usage, "Nm3")
    if u == "MJ":
        nm3 = round(usage / _GAS_GCV_PER_NM3, 4)
        r = _emit("fuel_citygas_lng", nm3, "Nm3")
        r["activity_note"] = (f"고지서 {usage} MJ(총발열량)를 {_GAS_GCV_PER_NM3} "
                              f"MJ/Nm³로 나눠 {nm3} Nm³ 환산 후 순발열량 계수 적용")
        return r
    raise factors.FactorError(f"도시가스 단위 미지원: {unit!r} (m3 또는 MJ)")


def scope2_electricity(kwh: float) -> dict:
    """Scope 2 전력(location-based)."""
    return _emit("electricity_kr", kwh, "kWh")


def scope3_travel(transport: str, km: float, *, local_bus: bool = False) -> dict:
    """Scope 3 카테고리 6 출장(육상·항공). 거리 × 인·km 계수."""
    fid = "travel_bus_local" if (transport == "버스" and local_bus) \
        else _TRANSPORT[transport][0]
    return _emit(fid, km, "passenger-km")


def scope3_hotel(nights: int) -> dict:
    """Scope 3 카테고리 6 숙박. 박수 × 객실·박 계수."""
    return _emit("travel_hotel_kr", nights, "room-night")


def scope3_commute(mode_factor_id: str, annual_km: float) -> dict:
    """Scope 3 카테고리 7 통근. 연간거리 × 수단계수(commute_* factor_id)."""
    denom = factors.get(mode_factor_id)["unit"].split("/")[-1]
    return _emit(mode_factor_id, annual_km, denom)


def scope3_spend(krw: float, user_factor: float, source: str) -> dict:
    """Scope 3 카테고리 1 지출기반 — 사용자 제공 계수(kgCO2eq/KRW) × 지출액."""
    return {
        "factor_id": "spend_category1_USER",
        "factor_value": user_factor,
        "factor_unit": "kgCO2eq/KRW",
        "factor_source": source,  # 사용자 입력 출처 — 감사추적
        "activity_value": krw,
        "activity_unit": "KRW",
        "kgco2e": round(user_factor * krw, 3),
    }


def selftest():
    # haversine: 서울(37.5547,126.9707)↔부산(35.1151,129.0403) 대권 ≈ 325km
    d = haversine((37.5547, 126.9707), (35.1151, 129.0403))
    assert 315 < d < 335, f"haversine 이상: {d}"

    # 내장 좌표 오프라인 거리(Kakao 없이): 서울→부산 철도 = 대권×1.2 ≈ 390km
    dk = distance_km("서울", "부산", "철도")
    assert dk and 380 < dk < 400, f"내장좌표 철도거리 이상: {dk}"
    # 미등재 역은 키 없으면 None(호출부가 큐로)
    assert distance_km("서울", "없는역", "철도") is None, "미등재역이 좌표를 지어냄"

    # 연료: 경유 100L × 2.577
    r = scope1_fuel("경유", 100)
    assert r["kgco2e"] == round(2.577 * 100, 3), "경유 산정 오류"
    assert r["factor_unit"] == "kgCO2/L"

    # 전력: 1000kWh × 0.4173
    assert scope2_electricity(1000)["kgco2e"] == round(0.4173 * 1000, 3), "전력 산정 오류"

    # 도시가스 m³: 100 × 2.182
    assert scope1_citygas(100, "m3")["kgco2e"] == round(2.182 * 100, 3), "도시가스 m3 오류"
    # 도시가스 MJ: 4310 MJ / 43.1 = 100 Nm³ → × 2.182
    g = scope1_citygas(4310, "MJ")
    assert g["activity_value"] == 100.0 and g["kgco2e"] == round(2.182 * 100, 3), "도시가스 MJ 환산 오류"

    # 출장 항공 100km × 0.273
    assert scope3_travel("항공", 100)["kgco2e"] == round(0.273 * 100, 3), "항공 산정 오류"
    # 시내버스 분기
    assert scope3_travel("버스", 10, local_bus=True)["factor_id"] == "travel_bus_local"

    # 숙박 2박 × 55.8
    assert scope3_hotel(2)["kgco2e"] == round(55.8 * 2, 3), "숙박 산정 오류"

    # 지출: 사용자계수 0.0005 × 1,000,000원
    s = scope3_spend(1_000_000, 0.0005, "한국은행 환경산업연관표(2006)")
    assert s["kgco2e"] == 500.0 and s["factor_source"], "지출 산정 오류"

    # 활동단위 불일치는 예외
    try:
        _emit("fuel_gasoline", 100, "kWh")
        assert False, "활동단위 불일치를 못 잡음"
    except factors.FactorError:
        pass

    print("calc selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
