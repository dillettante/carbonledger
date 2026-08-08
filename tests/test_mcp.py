"""MCP 서버 테스트 — 도구 구현의 계약과 '관문 우회 불가' 불변식을 고정한다.

MCP SDK는 선택 의존성이라 CI(기본 설치)에는 없다. 그래서 두 층으로 나눈다:
  · 구현 함수(*_impl) — SDK 없이 항상 검증. 실제 파이프라인을 돌린다.
  · 서버 등록(build_server) — SDK가 있을 때만 검증(없으면 건너뜀).

핵심 불변식: MCP 표면이 CLI와 **같은 검증 관문**을 통과해야 한다. 관문을 우회하는
계산 도구가 생기면(활동량×계수 직접 노출) 이 파일의 test_no_raw_calculation_tool이 깨진다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carbonledger import mcp_server  # noqa: E402

try:  # SDK 유무 판정(선택 의존성)
    import mcp  # noqa: F401
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


def _attr(obj, snake: str):
    """SDK 버전 차이를 흡수해 필드를 읽는다 — 1.x는 camelCase, 2.x는 snake_case.

    서버 코드(mcp_server.py)는 한 벌로 족하다: 생성 시 camelCase kwargs를 2.x도
    alias로 받아 주기 때문이다(실측 확인). 읽는 쪽만 여기서 흡수한다.
    """
    if hasattr(obj, snake):
        return getattr(obj, snake)
    head, *rest = snake.split("_")
    return getattr(obj, head + "".join(w.title() for w in rest))


def _mini_input(tmp_path: Path) -> Path:
    """LLM 없이 도는 최소 입력(CSV만) — 정상 2건 + 관문 위반 1건."""
    inp = tmp_path / "input"
    (inp / "scope3").mkdir(parents=True)
    (inp / "commute.csv").write_text(
        "employee_id,mode,factor_id,oneway_km,workdays\n"
        "E001,지하철,commute_subway,18,220\n", encoding="utf-8")
    (inp / "scope3" / "cat5_waste.csv").write_text(
        "item,activity,unit,factor_id,factor,factor_source\n"
        "사업장폐기물,2,tonne,waste_mixed_landfill,,\n", encoding="utf-8")
    # 출처 없는 사용자 계수 — 관문에 걸려 검토 대기로 가야 한다
    (inp / "spend.csv").write_text(
        "item,krw,factor,factor_source\n사무용품,1000000,0.0004,\n", encoding="utf-8")
    return inp


def test_run_impl_enforces_gates(tmp_path):
    """MCP run이 CLI와 같은 fail-closed 관문을 통과한다 — 우회로가 아니다."""
    inp = _mini_input(tmp_path)
    r = mcp_server.run_impl(str(inp), period="2026")

    assert r["ok"] is True
    assert r["counts"]["records"] == 2, "정상 2건이 산정되지 않음"
    assert r["counts"]["review_queue"] == 1, "출처 없는 지출이 관문을 통과함(우회로 발생)"
    assert any("factor_source" in i for q in r["review_queue_preview"]
               for i in q["issues"]), "큐 사유가 전달되지 않음"

    # 헤드라인 오도 방지: S1+2 소계가 총계와 별도로 제공돼야
    e = r["emissions_kgco2e"]
    assert e["subtotal_s1_s2"] == round(e["scope1"] + e["scope2"], 3)
    assert e["total"] == round(e["scope1"] + e["scope2"] + e["scope3"], 3)
    assert any("규제 신고 자료가 아니" in n for n in r["notes"]), "면책 고지 누락"

    # 실제 산출물이 만들어졌는지(요약만 그럴듯한 게 아니라)
    for k in ("report_md", "report_xlsx", "records_json"):
        assert Path(r["files"][k]).exists(), f"{k} 미생성"


def test_run_impl_missing_dir_returns_hint(tmp_path):
    """오류도 구조를 유지하고 다음 행동을 안내해야(예외로 세션을 죽이지 않음)."""
    r = mcp_server.run_impl(str(tmp_path / "없음"))
    assert r["ok"] is False and r["hint"], "오류에 hint 없음"


def test_review_status_and_merge_gates(tmp_path):
    """교정본도 MCP 경로에서 동일 관문 — 산술 조작·이력 누락은 반려."""
    inp = _mini_input(tmp_path)
    run = mcp_server.run_impl(str(inp), period="2026")
    out = run["out"]

    st = mcp_server.review_status_impl(out)
    assert st["ok"] and st["count"] == 1
    assert "저장위치" in st["correction_schema"], "교정 규격 안내 누락"

    # 교정본 없음 → 원장 불변
    r0 = mcp_server.review_merge_impl(out)
    assert r0["ok"] and r0["merged"] is False

    # 산술이 틀린 교정본 → 반려(합계 미반영)
    rev = Path(out) / "reviewed"
    rev.mkdir(exist_ok=True)
    bad = {"source_file": "spend.csv#1", "scope": 3, "category": 1,
           "factor_id": "spend_category1_USER", "factor_value": 0.0004,
           "activity_value": 1000000, "activity_unit": "KRW",
           "kgco2e": 99999.0,  # 0.0004×1,000,000 = 400 이어야 함
           "review": {"reviewer": "홍길동", "reviewed_at": "2026-08-09", "basis": "확인"}}
    (rev / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    r1 = mcp_server.review_merge_impl(out)
    assert r1["ok"] and r1["corrected_count"] == 0, "산술 조작 교정본이 반영됨"
    assert any("산술 불일치" in i for rj in r1["rejected"] for i in rj["issues"])

    # 올바른 교정본 → 반영 + 이력 표시
    good = {**bad, "kgco2e": 400.0}
    (rev / "bad.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    r2 = mcp_server.review_merge_impl(out)
    assert r2["merged"] is True and r2["corrected_count"] == 1
    md = (Path(out) / "report.md").read_text(encoding="utf-8")
    assert "수기 교정 이력" in md and "홍길동" in md, "교정 이력이 리포트에 안 남음"


def test_get_records_pagination_and_privacy(tmp_path):
    inp = _mini_input(tmp_path)
    out = mcp_server.run_impl(str(inp), period="2026")["out"]

    p = mcp_server.get_records_impl(out, limit=1)
    assert p["total"] == 2 and p["count"] == 1
    assert p["has_more"] is True and p["next_offset"] == 1
    # 원본 추출 JSON은 부피·개인정보 때문에 나가지 않아야
    assert all("extracted" not in r for r in p["records"]), "extracted 유출"

    # 필터
    assert mcp_server.get_records_impl(out, scope=3)["total"] == 2
    assert mcp_server.get_records_impl(out, scope=1)["total"] == 0
    assert mcp_server.get_records_impl(out, category=5)["total"] == 1
    # 상한 강제(에이전트가 limit=9999를 줘도 컨텍스트가 터지지 않게)
    assert mcp_server.get_records_impl(out, limit=9999)["count"] <= mcp_server._MAX_RECORDS_PAGE


def test_list_factors_and_inventory_template(tmp_path):
    f = mcp_server.list_factors_impl()
    assert f["ok"] and f["count"] >= 25
    assert f["factors_version"], "계수판 버전 미노출"
    assert "통근 제한" in f["usage"], "commute_* 제한 안내 누락"

    q = mcp_server.list_factors_impl(query="freight")
    assert q["count"] == 5 and all("freight" in x["factor_id"] for x in q["factors"])
    # 한계 경고(UK 프록시 등)가 note로 함께 전달돼야
    assert any(x["note"] for x in q["factors"]), "계수 한계 note 누락"

    t = mcp_server.inventory_template_impl()
    assert t["ok"] and "organization" in t["template"]
    assert "판정하지 않는" in t["note"], "툴이 판정하지 않는다는 고지 누락"


def test_diff_impl_surfaces_basis_change(tmp_path):
    """diff는 배출량보다 '기준 변화'를 먼저 알려야 한다."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"period": "2025", "factors_version": "0.1.0", "records": [
        {"scope": 1, "factor_id": "fuel_diesel", "factor_value": 2.577,
         "activity_value": 100, "kgco2e": 257.7}]}), encoding="utf-8")
    b.write_text(json.dumps({"period": "2026", "factors_version": "0.2.0", "records": [
        {"scope": 1, "factor_id": "fuel_diesel", "factor_value": 2.7,
         "activity_value": 80, "kgco2e": 216.0}]}), encoding="utf-8")

    r = mcp_server.diff_impl(str(a), str(b))
    assert r["ok"] and r["basis_changed"] is True
    assert any(x["항목"] == "계수판 버전" for x in r["basis"])
    fd = next(x for x in r["decomposition"] if x["factor_id"] == "fuel_diesel")
    assert abs(fd["활동량효과"] + fd["계수효과"] - fd["배출증감"]) < 0.01

    assert mcp_server.diff_impl(str(a), str(tmp_path / "없음.json"))["ok"] is False


def test_no_raw_calculation_tool(tmp_path):
    """설계 불변식: 관문을 우회하는 '계산 원시함수'를 노출하지 않는다.

    PLAYBOOK 경고("배출량 계산은 에이전트가 아니라 툴이") — MCP에 곱셈 도구가
    생기면 단위검사·산술 불변식·계수 출처·감사추적이 전부 무의미해진다.
    """
    exposed = {n for n in dir(mcp_server) if n.endswith("_impl")}
    assert exposed == {"run_impl", "review_status_impl", "review_merge_impl",
                       "get_records_impl", "list_factors_impl",
                       "inventory_template_impl", "diff_impl", "selftest_impl"}, \
        f"도구 구성이 바뀜 — 관문 우회 여부를 재검토할 것: {exposed}"
    src = Path(mcp_server.__file__).read_text(encoding="utf-8")
    for banned in ("calc.scope1_fuel", "calc.scope2_electricity", "calc.scope3_travel",
                   "calc._emit", "factors.get("):
        assert banned not in src, f"MCP가 계산 원시함수를 직접 호출함: {banned}"


def test_selftest_impl(tmp_path):
    r = mcp_server.selftest_impl()
    assert r["ok"] and r["factors_version"]
    assert len(r["detail"]) >= 8, "전 모듈 selftest가 돌지 않음"


def test_server_registration(tmp_path):
    """SDK가 있으면 실제로 서버가 구성되고 도구 메타가 올바른지 확인."""
    if not HAS_SDK:
        print("  (MCP SDK 없음 — 서버 등록 검증 건너뜀)")
        return
    import asyncio

    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"carbonledger_run", "carbonledger_review_status",
                     "carbonledger_review_merge", "carbonledger_get_records",
                     "carbonledger_list_factors", "carbonledger_inventory_template",
                     "carbonledger_diff", "carbonledger_selftest"}, names

    def hint(tool, name):
        """주석 값 읽기(SDK 버전 차이 흡수)."""
        return _attr(tool.annotations, name)

    by = {t.name: t for t in tools}
    # 쓰기 도구가 readOnly로 표시되면 클라이언트가 승인 없이 돌릴 수 있다
    assert hint(by["carbonledger_run"], "read_only_hint") is False
    assert hint(by["carbonledger_review_merge"], "read_only_hint") is False
    # run은 증빙을 외부 제공자로 보낼 수 있다(상용 백엔드) → openWorld
    assert hint(by["carbonledger_run"], "open_world_hint") is True
    assert hint(by["carbonledger_review_status"], "read_only_hint") is True

    for t in tools:
        assert t.description and len(t.description) > 80, f"{t.name}: 설명 부실"
        assert _attr(t, "output_schema"), f"{t.name}: outputSchema 없음(구조화 출력 불가)"
        assert hint(t, "destructive_hint") is False


if __name__ == "__main__":
    import tempfile

    for fn in (test_run_impl_enforces_gates, test_run_impl_missing_dir_returns_hint,
               test_review_status_and_merge_gates, test_get_records_pagination_and_privacy,
               test_list_factors_and_inventory_template, test_diff_impl_surfaces_basis_change,
               test_no_raw_calculation_tool, test_selftest_impl, test_server_registration):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print(f"MCP 테스트 9종 통과 ✅ (SDK {'있음' if HAS_SDK else '없음 — 등록 검증 생략'})")
