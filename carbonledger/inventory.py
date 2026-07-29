"""조직 선언(inventory.json) — 툴이 판정할 수 없는 것을 조직이 적고, 리포트에 전재한다.

## 왜 필요한가

배출량은 툴이 계산하지만, **그 숫자가 무엇에 대한 숫자인지**는 조직만 안다:
어느 법인·사업장을 포함했는지, 연결기준은 통제인지 지분인지, 무엇을 왜 제외했는지.
실제 지속가능경영보고서 3사(KCC·삼성전자·SK)를 대조해 보면 이 선언부가 공시의
비교 가능성을 좌우하는데, carbonledger 산출물에는 조직명조차 없었다.

## 설계 원칙 — 툴은 전재만 한다

- **판정하지 않는다**: 연결기준이 맞는지, 제외가 정당한지 툴이 심사하지 않는다.
- **자동 산출하지 않는다**: 재무연결 범위와의 차집합 같은 것을 툴이 계산하지 않는다
  (조직의 회계 자료를 툴이 알 수 없고, 틀린 계산이 근거처럼 보이면 더 위험하다).
- **없으면 없다고만 한다**: 미기재 항목에 "필수" 라벨을 붙이지 않는다.
  이 툴은 특정 표준 적합성을 주장하지 않으므로, 무엇이 필수인지 단정할 위치가 아니다.
- **검증 정보는 조직 인벤토리에 관한 것**임을 리포트에 명시한다 — 이 툴의 산정치가
  검증받았다는 뜻이 아니다(검증인이 본 적 없는 숫자에 보증 외관을 씌우지 않기 위해).

각 항목이 어느 표준 조항에 대응하는지는 PLAYBOOK과 템플릿 주석에 적어 두었다.
사용자가 왜 이 칸을 채우는지 알게 하되, 산출물에는 표준 라벨을 찍지 않는다.
"""
import json
from pathlib import Path

FILENAME = "inventory.json"

# 선언 항목 — (키, 표시명, 설명)
FIELDS = [
    ("organization", "조직", "보고 주체(법인명)"),
    ("responsible", "보고 책임", "보고서 작성·책임 주체"),
    ("reporting_period", "보고기간", "예: 2026-01-01 ~ 2026-12-31"),
    ("consolidation_approach", "연결기준", "운영통제 | 재무통제 | 지분율"),
    ("boundary_description", "조직경계", "포함한 법인·사업장 범위 서술"),
    ("significance_criteria", "유의성 기준", "어느 간접배출을 '유의'로 보아 포함했는지의 기준"),
]

_APPROACHES = ("운영통제", "재무통제", "지분율")


def load(input_dir) -> dict | None:
    """input/inventory.json 읽기. 없으면 None(선택 파일이므로 오류 아님)."""
    p = Path(input_dir) / FILENAME
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def check(d: dict) -> list[str]:
    """선언 내용 점검 — 경고만 반환한다(배출량에 영향이 없으므로 실행을 막지 않는다).

    산정 결과를 바꾸지 않는 선언이라 fail-closed 대상이 아니다. 다만 오탈자로
    연결기준이 엉뚱하게 들어가는 것은 알려 준다.
    """
    issues = []
    ca = (d.get("consolidation_approach") or "").strip()
    if ca and ca not in _APPROACHES:
        issues.append(f"연결기준 표기 확인: {ca!r} (통상 {' | '.join(_APPROACHES)})")
    for ex in d.get("exclusions") or []:
        if not str(ex.get("reason", "")).strip():
            issues.append(f"제외 항목에 사유 없음: {ex.get('item', '(항목명 없음)')}")
    v = d.get("verification") or {}
    if v.get("status") == "검증완료" and not str(v.get("body", "")).strip():
        issues.append("검증완료로 선언했으나 검증기관 미기재")
    return issues


def render_md(d: dict | None) -> list[str]:
    """리포트 §0 — 조직 선언 전재. 선언이 없으면 그 사실만 한 줄."""
    L = []
    if not d:
        L.append("## 0. 조직 선언\n")
        L.append("조직 선언(`input/inventory.json`)이 없다. 이 리포트는 **배출량 산정 결과만** 담으며, "
                 "조직명·조직경계·연결기준·제외 사유는 기재되지 않았다 — "
                 "인벤토리 보고서로 쓰려면 그 사항을 별도로 붙여야 한다.\n")
        return L

    L.append("## 0. 조직 선언 (조직이 기재한 내용을 그대로 전재)\n")
    L.append("| 항목 | 내용 |")
    L.append("|---|---|")
    for key, label, _ in FIELDS:
        v = str(d.get(key, "") or "").strip().replace("|", "\\|")
        L.append(f"| {label} | {v if v else '*미기재*'} |")

    by = d.get("base_year") or {}
    if isinstance(by, dict) and (by.get("year") or by.get("note")):
        note = str(by.get("note", "") or "").replace("|", "\\|")
        L.append(f"| 기준연도 | {by.get('year', '')} {('— ' + note) if note else ''} |")

    L.append("")

    ex = d.get("exclusions") or []
    if ex:
        L.append("**제외한 배출원·범위와 사유** (조직 기재):\n")
        L.append("| 제외 대상 | 사유 |")
        L.append("|---|---|")
        for e in ex:
            item = str(e.get("item", "") or "").replace("|", "\\|")
            reason = str(e.get("reason", "") or "*사유 미기재*").replace("|", "\\|")
            L.append(f"| {item} | {reason} |")
        L.append("")

    v = d.get("verification") or {}
    if v.get("status"):
        parts = [f"상태 **{v['status']}**"]
        for k, lab in (("body", "검증기관"), ("level", "보증수준"), ("date", "일자")):
            if str(v.get(k, "") or "").strip():
                parts.append(f"{lab} {v[k]}")
        L.append("**검증**: " + " · ".join(parts))
        L.append("\n> 위 검증 정보는 **조직이 선언한 인벤토리 전반**에 관한 것이며, "
                 "본 리포트의 산정치가 검증을 받았다는 의미가 아니다. "
                 "이 툴의 산출물은 별도 검증 대상이다.\n")

    if str(d.get("notes", "") or "").strip():
        L.append(f"**비고**: {d['notes']}\n")

    L.append("> 위 내용은 **조직이 기재한 선언**을 그대로 옮긴 것이다. "
             "툴은 연결기준의 적정성·제외의 정당성을 판정하지 않는다.\n")
    return L


TEMPLATE = {
    "_주석": "조직 선언 — 툴이 판정할 수 없는 것을 조직이 기재한다. input/inventory.json으로 저장.",
    "organization": "(주)예시상사",
    "responsible": "지속가능경영팀",
    "reporting_period": "2026-01-01 ~ 2026-12-31",
    "consolidation_approach": "운영통제",
    "_연결기준_설명": "운영통제 | 재무통제 | 지분율 중 하나. 어느 것을 택했는지 밝히는 것이 핵심(ISO 14064-1 5.1).",
    "boundary_description": "국내 사업장(본사·공장 2곳). 해외 법인·지분 50% 미만 관계사 제외.",
    "significance_criteria": "Scope 3는 총 Scope 3 배출량의 5% 이상인 카테고리를 유의한 것으로 보아 포함.",
    "base_year": {"year": "2023", "note": "최초 인벤토리 작성 연도"},
    "exclusions": [
        {"item": "해외 판매법인 3곳", "reason": "데이터 수집체계 미비 — 2027년 편입 예정"},
        {"item": "Scope 3 카테고리 10·11", "reason": "중간재 미판매·에너지 사용 제품 미생산으로 해당 없음"}
    ],
    "verification": {"status": "미검증", "body": "", "level": "", "date": ""},
    "_검증_설명": "미검증 | 검증예정 | 검증완료. 보증수준은 통상 합리적 보증 | 제한적 보증.",
    "notes": ""
}


def selftest():
    # 선언 있음 — 전 항목 전재
    d = dict(TEMPLATE)
    md = "\n".join(render_md(d))
    assert "(주)예시상사" in md and "운영통제" in md, "선언 전재 실패"
    assert "해외 판매법인 3곳" in md and "데이터 수집체계 미비" in md, "제외 사유 전재 실패"
    assert "판정하지 않는다" in md, "판정 안 한다는 고지 누락"
    assert "산정치가 검증을 받았다는 의미가 아니다" in md, "검증 오인 방지 문구 누락"

    # 선언 없음 — 그 사실만, '필수' 라벨 없이
    md0 = "\n".join(render_md(None))
    assert "조직 선언" in md0 and "없다" in md0, "미선언 고지 실패"
    assert "필수" not in md0, "미선언에 '필수' 라벨을 붙임(툴이 표준 적합성을 단정하면 안 됨)"

    # 점검 — 경고만
    assert check(d) == [], f"정상 선언에 경고: {check(d)}"
    assert any("연결기준" in i for i in check({**d, "consolidation_approach": "지분"})), "연결기준 오타 미검출"
    assert any("사유 없음" in i for i in
               check({**d, "exclusions": [{"item": "X"}]})), "제외 사유 누락 미검출"
    assert any("검증기관" in i for i in
               check({**d, "verification": {"status": "검증완료"}})), "검증기관 누락 미검출"

    # 미기재 항목은 '미기재'로 드러나야
    md2 = "\n".join(render_md({"organization": "A사"}))
    assert "*미기재*" in md2, "미기재 항목이 드러나지 않음"
    print("inventory selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
