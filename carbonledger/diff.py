"""두 실행 대조 — 배출량이 아니라 **산정 기준**이 무엇이 바뀌었는지 밝힌다.

## 왜 이 모듈이 있나 (실증 근거)

국내 3사(KCC·삼성전자·SK주식회사)의 지속가능경영보고서 3개년을 대조한 결과,
공시가 무너지는 지점은 값이 아니라 **기준의 조용한 변경**이었다. 파괴 지점만 달랐다:

  · KCC   — Scope 3 산정 카테고리가 11→10→12개로 바뀌었는데 고지 없음.
            세 값이 한 행에 나란히 제시돼 비교 가능성이 깨졌다("같은 값, 다른 기준").
  · 삼성전자 — NF₃를 새로 산정하며 과거 연도를 소급하지 않아, 공표 Scope 1은 +24.5%인데
            NF₃ 제외 환산하면 −16.8%로 부호가 뒤집힌다.
  · SK    — Scope 3 값은 소수점까지 일치하나 카테고리 15의 취합 경계와 조직경계가 각 3회 변경.

또 세 회사 모두 **배출량 증감의 요인**(활동량인가 계수인가)을 밝히지 않았다.
KCC는 원재료가 17.4% 줄었는데 카테고리 1 배출은 6.05%만 줄어, 역산하면 원재료 톤당
계수가 13.7% 오른 셈인데 그 사실이 보고서에 없다.

carbonledger는 자기 실행의 기준을 이미 전부 기록한다(factors_version·factor_id·
카테고리·활동량). 그래서 두 실행을 대조해 **무엇이 바뀌었고 배출량 변화가 어디서
왔는지**를 기계적으로 낼 수 있다 — 조직의 판단을 대신하지 않고, 툴 자신의 산출물만으로.

ISO 14064-1 대응: 9.3.1 n)(정량화 접근법 변경 설명)·l)(기준연도 재산정 설명),
6.4.2 b)(계산방법론 또는 **배출계수** 변경 시 재산정 트리거).
"""
import json
from pathlib import Path


def _load(p) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _by_cat(records, scope=3) -> dict:
    """카테고리별 합계."""
    out = {}
    for r in records:
        if r.get("scope") != scope:
            continue
        c = r.get("category")
        if c is None:
            continue
        out[c] = out.get(c, 0) + (r.get("kgco2e", 0) or 0)
    return out


def _by_scope(records) -> dict:
    out = {}
    for r in records:
        s = r.get("scope")
        out[s] = out.get(s, 0) + (r.get("kgco2e", 0) or 0)
    return out


def _factor_map(records) -> dict:
    """factor_id → 계수값(마지막 관측). 같은 id에 다른 값이 오면 그것 자체가 변경 신호."""
    out = {}
    for r in records:
        fid = r.get("factor_id")
        if fid:
            out.setdefault(fid, set()).add(r.get("factor_value"))
    return out


def _activity_by_factor(records) -> dict:
    """factor_id → (활동량 합, 배출량 합). 요인분해용."""
    out = {}
    for r in records:
        fid = r.get("factor_id")
        if not fid:
            continue
        a, e = out.get(fid, (0.0, 0.0))
        out[fid] = (a + (r.get("activity_value", 0) or 0),
                    e + (r.get("kgco2e", 0) or 0))
    return out


def _unit_ratio_flag(a: float, b: float) -> str:
    """1000배(또는 100·10배) 배수면 단위 변경 의심 — 실제 증감으로 오독하기 쉬운 유형.

    3사 대조에서 GJ→TJ 전환(정확히 1000배)이 '소급 수정'으로 잘못 잡힌 사례가 있었다.
    """
    if not a or not b:
        return ""
    r = b / a
    for mult, label in ((1000, "×1000"), (0.001, "÷1000"), (100, "×100"),
                        (0.01, "÷100"), (10, "×10"), (0.1, "÷10")):
        if abs(r - mult) < abs(mult) * 0.001:
            return f" ⚠️ 단위 변경 의심({label})"
    return ""


def compare(prev: dict, curr: dict) -> dict:
    """두 records.json → 기준 변화 + 배출량 변화 + 요인분해."""
    pr, cr = prev.get("records", []), curr.get("records", [])

    # ── 1. 기준(basis) 변화 — 값보다 먼저 본다
    basis = []
    for k, label in (("period", "보고기간"), ("factors_version", "계수판 버전"),
                     ("tool_version", "툴 버전")):
        a, b = prev.get(k), curr.get(k)
        if a != b:
            basis.append({"항목": label, "이전": a, "이번": b})

    p_cats, c_cats = set(_by_cat(pr)), set(_by_cat(cr))
    cat_added, cat_removed = sorted(c_cats - p_cats), sorted(p_cats - c_cats)

    p_f, c_f = _factor_map(pr), _factor_map(cr)
    f_added = sorted(set(c_f) - set(p_f))
    f_removed = sorted(set(p_f) - set(c_f))
    f_changed = []
    for fid in sorted(set(p_f) & set(c_f)):
        pv, cv = p_f[fid], c_f[fid]
        if pv != cv:
            f_changed.append({"factor_id": fid, "이전": sorted(pv), "이번": sorted(cv)})

    # ── 2. 배출량 변화
    p_s, c_s = _by_scope(pr), _by_scope(cr)
    scopes = []
    for s in (1, 2, 3):
        a, b = p_s.get(s, 0), c_s.get(s, 0)
        scopes.append({"scope": s, "이전": round(a, 3), "이번": round(b, 3),
                       "증감": round(b - a, 3),
                       "증감률": f"{(b-a)/a*100:+.2f}%" if a else "—"})
    pt, ct = sum(p_s.values()), sum(c_s.values())

    p_c3, c_c3 = _by_cat(pr), _by_cat(cr)
    cats = []
    for i in sorted(set(p_c3) | set(c_c3)):
        a, b = p_c3.get(i, 0), c_c3.get(i, 0)
        cats.append({"category": i, "이전": round(a, 3), "이번": round(b, 3),
                     "증감": round(b - a, 3),
                     "증감률": f"{(b-a)/a*100:+.2f}%" if a else ("신규" if b else "—"),
                     "비고": ("**신규 산정**" if i in cat_added else
                             "**산정 중단**" if i in cat_removed else "")})

    # ── 3. 요인분해 — 배출 변화가 활동량 때문인가 계수 때문인가
    # Δ배출 = Δ활동량 × 계수(이전) + 활동량(이번) × Δ계수  (계수가 단일값일 때만 유효)
    p_af, c_af = _activity_by_factor(pr), _activity_by_factor(cr)
    decomp = []
    for fid in sorted(set(p_af) & set(c_af)):
        pa, pe = p_af[fid]
        ca, ce = c_af[fid]
        if not pa or not ca:
            continue
        p_rate, c_rate = pe / pa, ce / ca          # 실효계수(배출/활동량)
        act_effect = (ca - pa) * p_rate            # 활동량 효과
        rate_effect = ca * (c_rate - p_rate)       # 계수 효과
        if abs(ce - pe) < 0.001:
            continue
        decomp.append({
            "factor_id": fid,
            "배출증감": round(ce - pe, 3),
            "활동량효과": round(act_effect, 3),
            "계수효과": round(rate_effect, 3),
            "활동량": f"{pa:,.1f} → {ca:,.1f}" + _unit_ratio_flag(pa, ca),
            "실효계수": f"{p_rate:.6g} → {c_rate:.6g}"
                        + (" **계수 변동**" if abs(c_rate - p_rate) > abs(p_rate) * 1e-6 else ""),
        })

    return {
        "basis": basis,
        "categories_added": cat_added, "categories_removed": cat_removed,
        "factors_added": f_added, "factors_removed": f_removed, "factors_changed": f_changed,
        "scopes": scopes, "categories": cats, "decomposition": decomp,
        "totals": {"이전": round(pt, 3), "이번": round(ct, 3), "증감": round(ct - pt, 3),
                   "증감률": f"{(ct-pt)/pt*100:+.2f}%" if pt else "—"},
        "meta": {"prev_period": prev.get("period"), "curr_period": curr.get("period"),
                 "prev_records": len(pr), "curr_records": len(cr)},
    }


def _t(kg) -> str:
    return f"{kg/1000:,.3f}"


def render_md(d: dict) -> str:
    """대조 결과 → 마크다운. 기준 변화를 배출량보다 **먼저** 낸다."""
    m = d["meta"]
    L = ["# 산정 대조 리포트 (두 실행 비교)", ""]
    L.append(f"- 이전: 보고기간 **{m['prev_period'] or '미지정'}** · {m['prev_records']}건")
    L.append(f"- 이번: 보고기간 **{m['curr_period'] or '미지정'}** · {m['curr_records']}건")
    L.append("")
    L.append("> 배출량 증감보다 **산정 기준의 변화**를 먼저 확인할 것 — 기준이 바뀌면 "
             "두 수치는 비교 대상이 아니다(실제 공시에서 카테고리 집합·가스 커버리지·"
             "취합 경계가 고지 없이 바뀐 사례가 다수 확인된다).")
    L.append("")

    # ── §1 기준 변화
    L.append("## 1. 산정 기준 변화 ⚠️ 먼저 볼 것\n")
    changed = bool(d["basis"] or d["categories_added"] or d["categories_removed"]
                   or d["factors_added"] or d["factors_removed"] or d["factors_changed"])
    if not changed:
        L.append("**기준 변화 없음** — 보고기간·계수판·카테고리 집합·사용 계수가 모두 동일하다. "
                 "두 수치는 같은 기준 위에 있으므로 직접 비교 가능하다.\n")
    else:
        if d["basis"]:
            L.append("| 항목 | 이전 | 이번 |")
            L.append("|---|---|---|")
            for b in d["basis"]:
                L.append(f"| {b['항목']} | {b['이전']} | {b['이번']} |")
            L.append("")
        if d["categories_added"] or d["categories_removed"]:
            L.append("**산정 카테고리 집합 변경** — 비교 가능성에 직접 영향:\n")
            if d["categories_added"]:
                L.append(f"- 신규 산정: 카테고리 {', '.join(map(str, d['categories_added']))}")
            if d["categories_removed"]:
                L.append(f"- 산정 중단: 카테고리 {', '.join(map(str, d['categories_removed']))}")
            L.append("\n> 카테고리가 늘거나 줄면 총계 증감의 일부는 **범위 변화**지 배출 변화가 아니다. "
                     "보고 시 그 사실과 사유를 기재할 것(ISO 14064-1 9.3.1 i·n).\n")
        if d["factors_changed"]:
            L.append("**동일 factor_id의 계수값 변경** — 같은 활동량이라도 배출량이 달라진다:\n")
            L.append("| factor_id | 이전 | 이번 |")
            L.append("|---|---|---|")
            for f in d["factors_changed"]:
                L.append(f"| `{f['factor_id']}` | {f['이전']} | {f['이번']} |")
            L.append("\n> 계수 변경은 ISO 14064-1 6.4.2 b)상 **기준연도 재산정 검토 사유**다.\n")
        if d["factors_added"] or d["factors_removed"]:
            if d["factors_added"]:
                L.append(f"- 신규 사용 계수: {', '.join('`'+x+'`' for x in d['factors_added'])}")
            if d["factors_removed"]:
                L.append(f"- 미사용 전환 계수: {', '.join('`'+x+'`' for x in d['factors_removed'])}")
            L.append("")

    # ── §2 배출량 변화
    L.append("## 2. 배출량 변화\n")
    L.append("| 구분 | 이전(tCO2eq) | 이번(tCO2eq) | 증감 | 증감률 |")
    L.append("|---|---:|---:|---:|---:|")
    for s in d["scopes"]:
        L.append(f"| Scope {s['scope']} | {_t(s['이전'])} | {_t(s['이번'])} | "
                 f"{_t(s['증감'])} | {s['증감률']} |")
    t = d["totals"]
    L.append(f"| **총계** | **{_t(t['이전'])}** | **{_t(t['이번'])}** | "
             f"**{_t(t['증감'])}** | **{t['증감률']}** |")
    L.append("")

    if d["categories"]:
        L.append("### Scope 3 카테고리별\n")
        L.append("| # | 이전(tCO2eq) | 이번(tCO2eq) | 증감 | 증감률 | 비고 |")
        L.append("|---|---:|---:|---:|---:|---|")
        for c in d["categories"]:
            L.append(f"| {c['category']} | {_t(c['이전'])} | {_t(c['이번'])} | "
                     f"{_t(c['증감'])} | {c['증감률']} | {c['비고']} |")
        L.append("")

    # ── §3 요인분해
    L.append("## 3. 요인분해 — 활동량인가 계수인가\n")
    if not d["decomposition"]:
        L.append("배출량이 변한 계수가 없다.\n")
    else:
        L.append("`Δ배출 ≈ Δ활동량 × 종전 실효계수 + 금번 활동량 × Δ실효계수`\n")
        L.append("| factor_id | 배출증감(kg) | 활동량 효과 | 계수 효과 | 활동량 | 실효계수 |")
        L.append("|---|---:|---:|---:|---|---|")
        for x in d["decomposition"]:
            L.append(f"| `{x['factor_id']}` | {x['배출증감']:,.1f} | {x['활동량효과']:,.1f} | "
                     f"{x['계수효과']:,.1f} | {x['활동량']} | {x['실효계수']} |")
        L.append("\n> **계수 효과가 크면 감축·증가가 아니라 산정 기준 변경**이다. "
                 "실제 공시에서 활동량이 17% 줄었는데 배출은 6%만 줄어 실효계수가 14% 오른 사례가 "
                 "설명 없이 보고된 바 있다 — 그 구분을 여기서 자동으로 드러낸다.")
        L.append("> 활동량에 '단위 변경 의심'이 붙으면 실제 증감이 아니라 단위 표기가 바뀐 것일 수 있다.\n")

    L.append("---\n")
    L.append("> 본 대조는 carbonledger 산출물(records.json) 간 기계적 비교다. "
             "조직경계·감축목표·검증 여부 등 조직이 판단·선언하는 사항은 다루지 않는다.")
    return "\n".join(L)


def run(prev_path, curr_path, out_path=None) -> dict:
    d = compare(_load(prev_path), _load(curr_path))
    md = render_md(d)
    if out_path:
        Path(out_path).write_text(md, encoding="utf-8")
    return {"result": d, "markdown": md}


def selftest():
    prev = {"period": "2025", "factors_version": "0.1.0", "tool_version": "0.1.0", "records": [
        {"scope": 1, "factor_id": "fuel_diesel", "factor_value": 2.577,
         "activity_value": 100, "kgco2e": 257.7},
        {"scope": 3, "category": 6, "factor_id": "travel_rail_ktx", "factor_value": 0.0269,
         "activity_value": 1000, "kgco2e": 26.9},
    ]}
    curr = {"period": "2026", "factors_version": "0.2.0", "tool_version": "0.1.0", "records": [
        # 활동량 감소 + 계수 상승(요인분해가 갈라내야 함)
        {"scope": 1, "factor_id": "fuel_diesel", "factor_value": 2.7,
         "activity_value": 80, "kgco2e": 216.0},
        {"scope": 3, "category": 6, "factor_id": "travel_rail_ktx", "factor_value": 0.0269,
         "activity_value": 1000, "kgco2e": 26.9},
        # 카테고리 신규 산정
        {"scope": 3, "category": 5, "factor_id": "waste_mixed_landfill", "factor_value": 520.3342,
         "activity_value": 2, "kgco2e": 1040.668},
    ]}
    d = compare(prev, curr)

    assert any(b["항목"] == "계수판 버전" for b in d["basis"]), "계수판 변경 미검출"
    assert any(b["항목"] == "보고기간" for b in d["basis"]), "보고기간 변경 미검출"
    assert d["categories_added"] == [5], f"신규 카테고리 미검출: {d['categories_added']}"
    assert "waste_mixed_landfill" in d["factors_added"], "신규 계수 미검출"
    assert any(f["factor_id"] == "fuel_diesel" for f in d["factors_changed"]), "계수값 변경 미검출"

    # 요인분해: 경유 100L×2.577=257.7 → 80L×2.7=216.0
    fd = next(x for x in d["decomposition"] if x["factor_id"] == "fuel_diesel")
    assert abs(fd["배출증감"] - (216.0 - 257.7)) < 0.01, "배출증감 오류"
    # 활동량 효과 = (80-100)×2.577 = -51.54 / 계수 효과 = 80×(2.7-2.577) = +9.84
    assert abs(fd["활동량효과"] - (-51.54)) < 0.01, f"활동량 효과 오류: {fd['활동량효과']}"
    assert abs(fd["계수효과"] - 9.84) < 0.01, f"계수 효과 오류: {fd['계수효과']}"
    assert abs(fd["활동량효과"] + fd["계수효과"] - fd["배출증감"]) < 0.01, "분해 합이 총증감과 불일치"

    # 단위 변경(1000배) 감지
    assert "×1000" in _unit_ratio_flag(100, 100000), "1000배 미감지"
    assert _unit_ratio_flag(100, 120) == "", "정상 증감을 단위변경으로 오탐"

    md = render_md(d)
    assert "산정 기준 변화" in md and "요인분해" in md and "신규 산정" in md, "렌더 누락"
    print("diff selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
