"""집계 리포트 — 배출 레코드 → 조직 탄소발자국(S1+S2+S3) md + xlsx + records.json.

정직성 장치(Phase 0·반증검토 반영):
  · 계수별 출처·신뢰수준을 리포트 표면에 노출(부록 자동생성)
  · Scope 3 미측정 12개 카테고리 + Scope 1·2 미측정 배출원을 명시(부분집계 은폐 금지)
  · 면책 고지를 README가 아니라 리포트 파일 자체에 삽입
  · review 큐(미검증 건)를 '본 수치 미포함'으로 요약
"""
import json
from datetime import date
from pathlib import Path

from . import factors

_CATS = Path(__file__).parent / "data" / "categories.json"

DISCLAIMER = (
    "본 리포트는 조직 탄소발자국 **추정**이다. 배출권거래제·목표관리제 명세서 등 규제 신고용이 아니다. "
    "거리기반·지출기반 산정은 명세서 방법론과 다르며, 계수 일부는 해외정부공식·학술·사용자입력 등급이다. "
    "신고 전 소관기관(gir.go.kr·한국환경공단)의 확정계수·최신 고시로 재검증할 것."
)

# Scope 1·2에서 본 툴이 자동 산정하지 않는 배출원(부분집계 명시용)
_S12_MISSING = [
    ("Scope 1", "냉매 누출(공조·냉동 HFC, fugitive)", "냉매 충전량·누출률 기반 별도 산정"),
    ("Scope 1", "비상발전기·소각 등 기타 고정연소", "연료 사용량 확보 시 fuel_* 계수로 산정 가능"),
    ("Scope 2", "지역난방 열·스팀", "지사별 열 배출계수(factors.json _reference_only) × 열사용량 수기 산정"),
]


def _load_cats() -> dict:
    return json.loads(_CATS.read_text(encoding="utf-8"))["categories"]


def _sum(records, scope=None, category=None) -> float:
    t = 0.0
    for r in records:
        if scope is not None and r.get("scope") != scope:
            continue
        if category is not None and r.get("category") != category:
            continue
        t += r.get("kgco2e", 0) or 0
    return round(t, 3)


def build(records: list[dict], review_queue: list[dict], out_dir: str,
          period: str | None = None) -> dict:
    """레코드 → 리포트 3종 생성. 반환: 요약 dict(총량 등)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    s1 = _sum(records, scope=1)
    s2 = _sum(records, scope=2)
    s3 = _sum(records, scope=3)
    total = round(s1 + s2 + s3, 3)

    # records.json — 감사추적 원장 (어느 툴·계수판으로 산정했는지 스탬프)
    from . import __version__
    (out / "records.json").write_text(
        json.dumps({"period": period, "generated": str(date.today()),
                    "tool_version": __version__,
                    "factors_version": factors.meta().get("version", ""),
                    "records": records, "review_queue": review_queue},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    _write_md(out / "report.md", records, review_queue, s1, s2, s3, total, period)
    _write_xlsx(out / "report.xlsx", records, review_queue, s1, s2, s3, total, period)

    return {"scope1": s1, "scope2": s2, "scope3": s3, "total_kgco2e": total,
            "records": len(records), "review": len(review_queue)}


def _t(kg: float) -> str:
    return f"{kg/1000:,.3f} tCO2eq ({kg:,.1f} kg)"


def _write_md(path, records, review_queue, s1, s2, s3, total, period):
    L = []
    L.append(f"# 조직 온실가스 배출량 리포트")
    L.append(f"\n- 보고기간: **{period or '전체(미지정)'}**  · 생성일: {date.today()}")
    L.append(f"- 자동 산정 건수: {len(records)}  · 검토 대기(미포함): {len(review_queue)}\n")

    L.append("## 1. 총괄 — 조직 탄소발자국\n")
    L.append("| 구분 | 배출량 |")
    L.append("|---|---|")
    L.append(f"| Scope 1 (직접) | {_t(s1)} |")
    L.append(f"| Scope 2 (전력, location-based) | {_t(s2)} |")
    L.append(f"| Scope 3 (기타 간접) | {_t(s3)} |")
    L.append(f"| **합계** | **{_t(total)}** |")
    L.append("\n> Scope 2는 location-based 단일 산정이다. market-based(녹색프리미엄·REC·PPA) 미반영.")
    L.append("> Scope 1 연료는 **CO2 단독** 산정(CH4·N2O 미가산, 통상 <3%) — 합계는 계수별 GWP 기준이 혼재된 추정치다(부록 §5 참조).\n")

    L.append("## 2. Scope 3 카테고리별 (GHG Protocol 15개 프레임)\n")
    L.append("| # | 카테고리 | 상태 | 배출량 |")
    L.append("|---|---|---|---|")
    cats = _load_cats()
    for i in range(1, 16):
        c = cats[str(i)]
        has = any(r.get("scope") == 3 and r.get("category") == i for r in records)
        if has:
            status, val = "측정", _t(_sum(records, scope=3, category=i))
        else:
            # 입력 없는 카테고리는 자동화 여부 무관하게 '미측정' + 측정법 안내(0을 측정으로 오독 방지)
            m = c.get("method", c.get("guidance", ""))[:45]
            who = c.get("applies_to", "")
            status = "미측정"
            val = f"측정법: {m}" + (f" · 해당: {who[:20]}" if who else "")
        L.append(f"| {i} | {c['name']} | {status} | {val} |")

    L.append("\n## 3. Scope 1·2 미측정 배출원 (부분집계 고지)\n")
    L.append("아래는 본 툴이 자동 산정하지 않는다. 헤드라인 합계는 이 항목을 **제외**한 부분집계다.\n")
    L.append("| Scope | 배출원 | 측정법 |")
    L.append("|---|---|---|")
    for sc, src, how in _S12_MISSING:
        L.append(f"| {sc} | {src} | {how} |")

    L.append("\n## 4. 건별 명세 (감사추적)\n")
    L.append("| 파일 | Scope | 활동 | 활동량 | 계수 | 배출량(kg) |")
    L.append("|---|---|---|---|---|---|")
    for r in records:
        L.append(f"| {r.get('source_file','')} | S{r.get('scope','')} | "
                 f"{r.get('activity','')} | {r.get('activity_value','')} {r.get('activity_unit','')} | "
                 f"`{r.get('factor_id','')}` | {r.get('kgco2e','')} |")

    L.append("\n## 5. 사용된 배출계수 · 출처 (부록)\n")
    used = factors.all_used(r.get("factor_id") for r in records)
    L.append("| factor_id | 값 | 단위 | 신뢰수준 | 연도 | GWP | 출처 | 비고(한계·누락) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for f in used:
        L.append(f"| `{f['id']}` | {f.get('value')} | {f.get('unit')} | "
                 f"{f.get('confidence')} | {f.get('year','')} | {f.get('gwp_basis','')} | "
                 f"{f.get('source','')[:50]} | {f.get('note','')[:70]} |")
    L.append("\n> 비고의 '한계·누락'을 확인할 것. 예: 연료계수는 **CO2만 반영**(CH4·N2O 별도 가산 필요), "
             "전력 WTT/T&D는 UK 프록시 등 — 헤드라인 수치에 영향. "
             "(전력계수 0.4173은 gir 원문 검증 완료 — GWP=AR5.)")

    # 수기 교정 이력 — 자동 추출 건과 구별되지 않으면 통제 흔적이 사라진다
    corrected = [r for r in records if r.get("human_corrected")]
    if corrected:
        L.append("\n## 6. 수기 교정 이력 (사람이 값을 확인·수정해 합계에 반영한 건)\n")
        L.append(f"아래 {len(corrected)}건은 자동 추출이 아니라 **사람이 교정**해 집계에 포함됐다. "
                 "교정본도 검증 관문(필수필드·산술 일치·교정 이력)을 통과한 것만 반영된다.\n")
        L.append("| 파일 | 활동 | 배출량(kg) | 교정자 | 교정일시 | 근거 |")
        L.append("|---|---|---|---|---|---|")
        for r in corrected:
            rv = r.get("review") or {}
            L.append(f"| {r.get('source_file','')} | {r.get('activity','')} | {r.get('kgco2e','')} | "
                     f"{rv.get('reviewer','')} | {rv.get('reviewed_at','')} | {rv.get('basis','')} |")
        L.append(f"\n> 수기 교정분 합계: {_t(sum(r.get('kgco2e', 0) or 0 for r in corrected))} "
                 f"(전체의 {(sum(r.get('kgco2e',0) or 0 for r in corrected) / total * 100 if total else 0):.1f}%)\n")

    if review_queue:
        L.append("\n## 7. 검토 대기 (본 수치 미포함)\n")
        L.append("검증 관문을 통과 못해 집계에서 제외됐다. 교정 후 `carbonledger review`로 재집계.\n")
        L.append("| 파일 | 사유 |")
        L.append("|---|---|")
        for q in review_queue:
            L.append(f"| {q.get('source_file','')} | {'; '.join(q.get('issues',[]))} |")

    L.append(f"\n---\n\n> ⚠️ **면책** — {DISCLAIMER}\n")
    Path(path).write_text("\n".join(L), encoding="utf-8")


def _write_xlsx(path, records, review_queue, s1, s2, s3, total, period):
    from openpyxl import Workbook
    wb = Workbook()

    ws = wb.active
    ws.title = "총괄"
    ws.append(["보고기간", period or "전체(미지정)"])
    ws.append(["생성일", str(date.today())])
    ws.append([])
    ws.append(["구분", "배출량(kgCO2eq)", "tCO2eq"])
    for name, v in [("Scope 1", s1), ("Scope 2", s2), ("Scope 3", s3), ("합계", total)]:
        ws.append([name, v, round(v / 1000, 3)])
    ws.append([])
    ws.append(["면책", DISCLAIMER])

    wr = wb.create_sheet("건별_감사추적")
    wr.append(["파일", "Scope", "카테고리", "활동", "활동량", "활동단위",
               "factor_id", "계수값", "계수단위", "배출량(kg)",
               "수기교정", "교정자", "교정일시", "교정근거"])
    for r in records:
        rv = r.get("review") or {}
        wr.append([r.get("source_file"), r.get("scope"), r.get("category"),
                   r.get("activity"), r.get("activity_value"), r.get("activity_unit"),
                   r.get("factor_id"), r.get("factor_value"), r.get("factor_unit"),
                   r.get("kgco2e"),
                   "Y" if r.get("human_corrected") else "",
                   rv.get("reviewer", ""), rv.get("reviewed_at", ""), rv.get("basis", "")])

    wf = wb.create_sheet("계수목록")
    wf.append(["factor_id", "값", "단위", "신뢰수준", "연도", "GWP기준", "출처", "출처URL"])
    for f in factors.all_used(r.get("factor_id") for r in records):
        wf.append([f["id"], f.get("value"), f.get("unit"), f.get("confidence"),
                   f.get("year"), f.get("gwp_basis"), f.get("source"), f.get("source_url")])

    if review_queue:
        wq = wb.create_sheet("검토대기")
        wq.append(["파일", "사유"])
        for q in review_queue:
            wq.append([q.get("source_file"), "; ".join(q.get("issues", []))])

    wb.save(path)


def selftest():
    import tempfile
    recs = [
        {"source_file": "a.jpg", "scope": 1, "activity": "경유 연소",
         "activity_value": 100, "activity_unit": "L", "factor_id": "fuel_diesel",
         "factor_value": 2.577, "factor_unit": "kgCO2/L", "kgco2e": 257.7},
        {"source_file": "b.jpg", "scope": 3, "category": 6, "activity": "KTX 출장",
         "activity_value": 400, "activity_unit": "passenger-km", "factor_id": "travel_rail_ktx",
         "factor_value": 0.0269, "factor_unit": "kgCO2eq/passenger-km", "kgco2e": 10.76},
    ]
    q = [{"source_file": "c.pdf", "issues": ["역명 확인 필요: '서을'"]}]
    with tempfile.TemporaryDirectory() as d:
        summary = build(recs, q, d, period="2026")
        assert summary["scope1"] == 257.7 and summary["scope3"] == 10.76, "집계 오류"
        assert summary["total_kgco2e"] == round(257.7 + 10.76, 3), "합계 오류"
        md = (Path(d) / "report.md").read_text(encoding="utf-8")
        assert "면책" in md and "미측정" in md and "travel_rail_ktx" in md, "리포트 정직성장치 누락"
        assert (Path(d) / "report.xlsx").exists(), "xlsx 미생성"
        assert (Path(d) / "records.json").exists(), "records.json 미생성"
    print("report selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
