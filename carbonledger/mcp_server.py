"""carbonledger MCP 서버 — CLI를 감싸 AI 에이전트(Claude 등)가 직접 호출하게 한다.

## 왜 이 파일이 있나

PLAYBOOK이 권하는 사용법("에이전트에게 CLI를 대신 시키기")을 에이전트가 터미널
문자열을 조립하지 않고 수행하게 만든다. 원래 설계는 MCP를 의도적으로 만들지
않았으나(최소 구성), 그 전제는 "CLI를 감싸는 형태면 추가될 수 있다"였다 — 이 파일이
정확히 그 형태다. 산정 로직·검증 관문·감사추적은 한 줄도 여기 없다.

## 설계 제약 — 에이전트가 검증 관문을 우회할 수 없어야 한다

PLAYBOOK §"AI 에이전트로 굴리기"의 경고: **배출량 계산은 에이전트가 아니라 툴이
해야 한다.** 에이전트가 직접 곱셈을 하면 단위검사·산술 불변식·계수 출처·수기교정
이력이 전부 사라진다. 그래서 이 서버는:

  · `활동량 × 계수` 같은 **계산 원시함수를 노출하지 않는다**. 파이프라인 전체
    (run/review/diff)만 도구로 낸다 — 관문을 통과한 숫자만 나온다.
  · run·review는 CLI와 **같은 함수**(cli.run_pipeline·cli.review_merge)를 호출한다.
    복제하면 한쪽만 관문이 바뀌어 두 표면의 결과가 갈린다.
  · 교정본은 여기서도 반려된다 — 에이전트가 만든 JSON도 사람이 만든 것과 동일 관문.

## 전송·의존성

stdio 전용이다(로컬 증빙을 다루므로 원격 HTTP는 부적절 — 기밀 처리 원칙과 충돌).
MCP SDK는 선택 의존성(`pip install ".[mcp]"`)이고, 이 파일의 구현 함수들은
SDK 없이도 임포트·테스트된다(도구 등록만 SDK를 요구).
"""
import json
from pathlib import Path
from typing import Any

from . import __version__, factors, inventory

# 리포트 원문을 통째로 반환하면 에이전트 컨텍스트를 낭비한다. 요약·경로를 주고
# 상세는 get_records(페이지네이션)로 가져가게 한다.
_MAX_QUEUE_PREVIEW = 20
_MAX_RECORDS_PAGE = 50


def _err(msg: str, hint: str = "") -> dict[str, Any]:
    """실패도 구조를 유지한다 — 에이전트가 다음 행동을 정할 수 있게 hint를 함께."""
    return {"ok": False, "error": msg, "hint": hint} if hint else {"ok": False, "error": msg}


def _load_ledger(out_dir: str) -> dict[str, Any]:
    p = Path(out_dir) / "records.json"
    if not p.exists():
        raise FileNotFoundError(
            f"records.json 없음: {out_dir} — carbonledger_run을 먼저 실행해야 한다")
    return json.loads(p.read_text(encoding="utf-8"))


# ── 도구 구현 (SDK 없이 임포트·테스트 가능) ──────────────────────────


def run_impl(input_dir: str, period: str | None = None,
             model: str | None = None, out_dir: str | None = None) -> dict[str, Any]:
    """증빙 폴더 일괄 처리 → 리포트 3종 생성."""
    from . import cli
    try:
        s = cli.run_pipeline(input_dir, period=period, model=model, out_dir=out_dir)
    except FileNotFoundError as e:
        return _err(str(e), "입력 폴더에 travel/·scope1-fuel/·scope2-energy/·"
                            "commute.csv·spend.csv·scope3/ 중 있는 것만 두면 된다")
    except Exception as e:  # 백엔드 미가동·키 누락 등
        return _err(f"{type(e).__name__}: {e}",
                    "로컬 백엔드면 LM Studio/Ollama 구동 확인, 상용이면 API 키 환경변수 확인")

    q = s["review_queue"]
    return {
        "ok": True, "out": s["out"], "period": period,
        "emissions_kgco2e": {"scope1": s["scope1"], "scope2": s["scope2"],
                             "scope3": s["scope3"],
                             "subtotal_s1_s2": round(s["scope1"] + s["scope2"], 3),
                             "total": s["total_kgco2e"]},
        "counts": {"records": s["records"], "review_queue": s["review"]},
        "declaration_warnings": s["declaration_warnings"],
        "review_queue_preview": [
            {"source_file": x.get("source_file"), "issues": x.get("issues", [])}
            for x in q[:_MAX_QUEUE_PREVIEW]],
        "review_queue_truncated": max(0, len(q) - _MAX_QUEUE_PREVIEW),
        "files": {"report_md": f"{s['out']}/report.md",
                  "report_xlsx": f"{s['out']}/report.xlsx",
                  "records_json": f"{s['out']}/records.json"},
        "notes": [
            "검토 대기 건은 합계에 포함되지 않았다(fail-closed).",
            "이 수치는 추정치이며 규제 신고 자료가 아니다 — 리포트 면책 고지 참조.",
        ],
    }


def review_status_impl(out_dir: str) -> dict[str, Any]:
    """검토 대기 목록 조회(읽기 전용 — 원장을 바꾸지 않는다)."""
    try:
        data = _load_ledger(out_dir)
    except FileNotFoundError as e:
        return _err(str(e))
    q = data.get("review_queue", [])
    return {
        "ok": True, "out": out_dir, "count": len(q),
        "review_queue": [{"source_file": x.get("source_file"), "issues": x.get("issues", [])}
                         for x in q],
        "correction_schema": {
            "필수": ["source_file(기존 records·검토대기에 실재하는 값)", "scope(1|2|3)",
                   "factor_id", "factor_value", "activity_value", "activity_unit",
                   "kgco2e(= factor_value × activity_value, ±1%)",
                   "review{reviewer, reviewed_at, basis}"],
            "추가필수": {"scope 3": "category(1~15)",
                     "scope 1·2": "factor_id·activity_unit(카테고리 3 자동 재파생에 사용)"},
            "저장위치": f"{out_dir}/reviewed/*.json (파일 하나에 레코드 하나)",
            "주의": "자동 파생 건(source_file에 '→cat3')은 직접 교정 불가 — "
                  "원본 Scope 1·2 건을 교정하면 파생은 자동 재계산된다",
        },
    }


def review_merge_impl(out_dir: str) -> dict[str, Any]:
    """reviewed/*.json을 검증 관문에 태워 병합·재집계."""
    from . import cli
    try:
        r = cli.review_merge(out_dir)
    except FileNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")

    out = {"ok": True, "out": r["out"], "merged": r["merged"],
           "corrected_count": len(r["corrected"]),
           "rejected": r["rejected"],
           "remaining_queue_count": len(r["queue"])}
    if r["merged"]:
        s = r["summary"]
        out["emissions_kgco2e"] = {
            "scope1": s["scope1"], "scope2": s["scope2"], "scope3": s["scope3"],
            "subtotal_s1_s2": round(s["scope1"] + s["scope2"], 3),
            "total": s["total_kgco2e"]}
        out["note"] = ("교정 건은 리포트 §수기 교정 이력에 교정자·근거와 함께 표시된다. "
                       "Scope 1·2를 교정했으면 카테고리 3 파생은 자동 재계산됐다.")
    else:
        out["note"] = ("반영할 교정본이 없어 원장을 바꾸지 않았다. "
                       f"{r['out']}/reviewed/*.json에 교정본을 저장한 뒤 다시 호출할 것.")
    return out


def get_records_impl(out_dir: str, scope: int | None = None,
                     category: int | None = None, limit: int = 20,
                     offset: int = 0) -> dict[str, Any]:
    """산정 결과 건별 조회(페이지네이션·필터)."""
    try:
        data = _load_ledger(out_dir)
    except FileNotFoundError as e:
        return _err(str(e))

    rows = data.get("records", [])
    if scope is not None:
        rows = [r for r in rows if r.get("scope") == scope]
    if category is not None:
        rows = [r for r in rows if r.get("category") == category]
    total = len(rows)
    limit = max(1, min(int(limit), _MAX_RECORDS_PAGE))
    offset = max(0, int(offset))
    page = rows[offset:offset + limit]

    # extracted(원본 추출 JSON)는 부피가 크고 개인정보가 섞일 수 있어 기본 제외한다
    slim = [{k: v for k, v in r.items() if k != "extracted"} for r in page]
    return {
        "ok": True, "total": total, "count": len(slim), "offset": offset,
        "has_more": offset + len(slim) < total,
        "next_offset": offset + len(slim) if offset + len(slim) < total else None,
        "period": data.get("period"), "factors_version": data.get("factors_version"),
        "records": slim,
    }


def list_factors_impl(query: str | None = None) -> dict[str, Any]:
    """배출계수 레지스트리 조회 — CSV의 factor_id를 고를 때 쓴다."""
    reg = json.loads(
        (Path(__file__).parent / "data" / "factors.json").read_text(encoding="utf-8"))
    meta = reg.get("_meta", {})
    out = []
    for fid, rec in reg.items():
        if fid.startswith("_"):
            continue
        if query:
            hay = f"{fid} {rec.get('activity','')} {rec.get('source','')}".lower()
            if query.lower() not in hay:
                continue
        out.append({"factor_id": fid, "value": rec.get("value"), "unit": rec.get("unit"),
                    "scope": rec.get("scope"), "category": rec.get("category"),
                    "activity": rec.get("activity"), "confidence": rec.get("confidence"),
                    "year": rec.get("year"), "gwp_basis": rec.get("gwp_basis"),
                    "source": rec.get("source"), "note": rec.get("note", "")})
    return {
        "ok": True, "factors_version": meta.get("version"), "count": len(out),
        "factors": out,
        "usage": {
            "CSV 열": "factor_id를 채우면 레지스트리 계수(단위 검증됨). 없으면 "
                    "factor+factor_source로 사용자 계수(출처 필수).",
            "단위 규칙": "활동 단위가 계수 분모와 일치해야 한다(운송=tonne-km, "
                     "폐기물=tonne, 전기=kWh, 통근=km 또는 passenger-km).",
            "통근 제한": "commute.csv의 factor_id는 commute_* 계수만 허용된다.",
        },
    }


def inventory_template_impl() -> dict[str, Any]:
    """조직 선언(inventory.json) 템플릿 — 리포트 §0에 전재될 항목."""
    return {
        "ok": True,
        "filename": "input/inventory.json",
        "template": inventory.TEMPLATE,
        "fields": [{"key": k, "label": lab, "desc": d} for k, lab, d in inventory.FIELDS],
        "note": ("툴은 이 내용을 전재만 하고 연결기준의 적정성·제외의 정당성을 "
                 "판정하지 않는다. verification은 조직 인벤토리에 관한 선언이며 "
                 "본 툴 산정치의 검증이 아니다."),
    }


def diff_impl(prev_records_json: str, curr_records_json: str,
              out_path: str | None = None) -> dict[str, Any]:
    """두 실행 대조 — 배출량보다 산정 기준의 변화를 먼저 낸다."""
    from . import diff as diff_mod
    for p in (prev_records_json, curr_records_json):
        if not Path(p).exists():
            return _err(f"파일 없음: {p}", "각 실행의 out/records.json 경로를 준다")
    try:
        r = diff_mod.run(prev_records_json, curr_records_json, out_path)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")

    d = r["result"]
    basis_changed = bool(d["basis"] or d["categories_added"] or d["categories_removed"]
                         or d["factors_added"] or d["factors_removed"]
                         or d["factors_changed"])
    return {
        "ok": True,
        "basis_changed": basis_changed,
        "basis": d["basis"],
        "categories_added": d["categories_added"],
        "categories_removed": d["categories_removed"],
        "factors_changed": d["factors_changed"],
        "totals": d["totals"], "scopes": d["scopes"],
        "decomposition": d["decomposition"],
        "markdown_path": out_path,
        "note": ("기준이 바뀌었으면 두 수치는 비교 대상이 아니다. 요인분해의 "
                 "'계수효과'가 크면 감축이 아니라 산정 기준 변경이다."
                 if basis_changed else
                 "기준 변화 없음 — 두 수치는 같은 기준 위에 있어 직접 비교 가능하다."),
    }


def selftest_impl() -> dict[str, Any]:
    """네트워크·LLM 없이 전 모듈 자체 검증."""
    import contextlib
    import io

    from . import calc, extract, report, scope3, validate
    from . import diff as diff_mod
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            for m in (factors, validate, calc, extract, scope3, report, diff_mod, inventory):
                m.selftest()
    except AssertionError as e:
        return _err(f"selftest 실패: {e}", "설치본이 손상됐거나 계수판이 코드와 어긋난다")
    return {"ok": True, "tool_version": __version__,
            "factors_version": factors.meta().get("version"),
            "detail": buf.getvalue().strip().splitlines()}


# ── MCP 도구 등록 (SDK 필요) ─────────────────────────────────────────

SERVER_INSTRUCTIONS = """\
carbonledger — 영수증·고지서·CSV로 조직 온실가스 배출량(Scope 1·2·3)을 산정하는 도구.

중요: 배출량 계산을 직접 하지 말고 이 도구가 하게 할 것. 직접 곱하면 단위 검증·
산술 불변식·계수 출처·감사추적이 사라진다(이 도구를 쓰는 이유가 사라진다).

통상 순서:
 1) carbonledger_list_factors 로 CSV에 쓸 factor_id 확인
 2) 증빙을 input/ 폴더 구조로 정리 — Scope 귀속은 폴더가 선언한다
    (법인차 주유=scope1-fuel/ · 개인차 출장=travel/ · 통근=commute.csv)
    영수증만 봐선 귀속을 알 수 없으므로 사용자에게 확인할 것. 추측 금지.
 3) carbonledger_run 실행
 4) carbonledger_review_status 로 검토 대기 사유 확인 → 사용자와 함께 교정본 작성
    → reviewed/*.json 저장 → carbonledger_review_merge
 5) 전년 대비는 carbonledger_diff

산출물은 추정치이며 규제 신고 자료가 아니다.
"""


def build_server():
    """FastMCP 서버 구성. SDK가 없으면 ImportError(main이 안내 메시지로 변환)."""
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    mcp = FastMCP("carbonledger_mcp", instructions=SERVER_INSTRUCTIONS)

    def _ann(title, *, read_only, open_world=False, idempotent=False):
        return ToolAnnotations(title=title, readOnlyHint=read_only,
                               destructiveHint=False, idempotentHint=idempotent,
                               openWorldHint=open_world)

    @mcp.tool(name="carbonledger_run",
              annotations=_ann("증빙 폴더 산정 실행", read_only=False, open_world=True))
    def carbonledger_run(input_dir: str, period: str | None = None,
                         model: str | None = None, out_dir: str | None = None) -> dict[str, Any]:
        """증빙 폴더를 일괄 처리해 조직 온실가스 배출량 리포트를 생성한다.

        이미지 증빙(영수증·고지서)은 비전 LLM으로 읽고, CSV는 그대로 읽어
        검증 관문을 통과한 건만 집계한다. 통과 못한 건은 합계에서 빠지고
        검토 대기로 남는다(fail-closed — 조용한 누락이 아니다).

        ⚠️ 비용·시간: 이미지 1장당 LLM 호출 1회다. 상용 백엔드(CARBONLEDGER_BACKEND=
        openai|anthropic)면 장당 과금되고 증빙 이미지가 외부로 전송된다. 수백 장
        일괄 실행 전에 몇 장으로 시험할 것. 로컬(lmstudio·ollama)은 무료·외부전송 없음.

        Args:
            input_dir: 증빙 폴더 경로. 하위에 travel/·scope1-fuel/·scope2-energy/·
                commute.csv·spend.csv·scope3/cat{N}_*.csv·inventory.json 중 있는 것만.
                **폴더가 Scope 귀속을 선언한다** — 같은 주유 영수증도 법인차면
                scope1-fuel/, 개인차 출장이면 travel/이다. 추측하지 말 것.
            period: 보고연도(예: "2026"). 기간 밖 증빙은 집계에서 제외되고 목록으로 남는다.
            model: 추출 모델 override(예: "qwen/qwen3-vl-8b"). 미지정 시 백엔드 기본값.
                저화질·밀집 표 고지서가 전부 실패하면 상위 모델로 재시도.
            out_dir: 산출 폴더. 미지정 시 input_dir/out.

        Returns:
            dict: {ok, out, emissions_kgco2e{scope1,scope2,scope3,subtotal_s1_s2,total},
                   counts{records,review_queue}, declaration_warnings[],
                   review_queue_preview[{source_file,issues}], review_queue_truncated,
                   files{report_md,report_xlsx,records_json}, notes[]}
            실패 시 {ok: false, error, hint}.

        보고 시 주의: subtotal_s1_s2(Scope 1+2)가 규제·감축목표의 통상 기준이고
        total은 밸류체인 전체다. 용도에 맞는 쪽을 인용할 것.
        """
        return run_impl(input_dir, period, model, out_dir)

    @mcp.tool(name="carbonledger_review_status",
              annotations=_ann("검토 대기 조회", read_only=True, idempotent=True))
    def carbonledger_review_status(out_dir: str) -> dict[str, Any]:
        """검토 대기(집계에서 빠진 건)와 그 사유, 교정본 작성 규격을 조회한다.

        Args:
            out_dir: run이 만든 산출 폴더(records.json이 있는 곳).

        Returns:
            dict: {ok, out, count, review_queue[{source_file, issues[]}],
                   correction_schema{필수, 추가필수, 저장위치, 주의}}
            실패 시 {ok: false, error}.

        교정값은 **원증빙을 확인한 사람**이 정해야 한다. 에이전트가 값을 지어내
        관문을 통과시키면 감사추적이 거짓이 된다 — 사유를 사용자에게 보이고
        실제 값을 받을 것.
        """
        return review_status_impl(out_dir)

    @mcp.tool(name="carbonledger_review_merge",
              annotations=_ann("교정본 병합 재집계", read_only=False, idempotent=True))
    def carbonledger_review_merge(out_dir: str) -> dict[str, Any]:
        """reviewed/*.json 교정본을 검증 관문에 태워 병합하고 리포트를 재생성한다.

        교정본도 자동 추출과 같은 관문을 통과해야 한다: 계수×활동량=배출량 산술
        (±1%), 교정자·교정일시·근거 3개, 교정 대상 실재, Scope 3의 category 등.
        반려된 건은 합계에 들어가지 않고 사유와 함께 반환·기록된다.
        재실행해도 이중 계상되지 않는다(멱등).

        Args:
            out_dir: run이 만든 산출 폴더. 교정본은 그 아래 reviewed/*.json.

        Returns:
            dict: {ok, out, merged, corrected_count, rejected[{source_file,issues}],
                   remaining_queue_count, emissions_kgco2e?, note}
            실패 시 {ok: false, error}.
        """
        return review_merge_impl(out_dir)

    @mcp.tool(name="carbonledger_get_records",
              annotations=_ann("건별 명세 조회", read_only=True, idempotent=True))
    def carbonledger_get_records(out_dir: str, scope: int | None = None,
                                 category: int | None = None, limit: int = 20,
                                 offset: int = 0) -> dict[str, Any]:
        """산정된 건별 명세를 조회한다(감사추적용, 필터·페이지네이션).

        run은 요약만 돌려준다 — 개별 건의 계수·활동량·배출량이 필요할 때 이것을 쓴다.

        Args:
            out_dir: run이 만든 산출 폴더.
            scope: 1|2|3 필터(생략 시 전체).
            category: Scope 3 카테고리 1~15 필터(생략 시 전체).
            limit: 최대 반환 건수(1~50, 기본 20).
            offset: 건너뛸 건수(페이지네이션).

        Returns:
            dict: {ok, total, count, offset, has_more, next_offset, period,
                   factors_version, records[{source_file, scope, category, activity,
                   activity_value, activity_unit, factor_id, factor_value,
                   factor_unit, kgco2e, ...}]}
            원본 추출 JSON(extracted)은 부피·개인정보 때문에 제외된다.
        """
        return get_records_impl(out_dir, scope, category, limit, offset)

    @mcp.tool(name="carbonledger_list_factors",
              annotations=_ann("배출계수 조회", read_only=True, idempotent=True))
    def carbonledger_list_factors(query: str | None = None) -> dict[str, Any]:
        """배출계수 레지스트리를 조회한다 — CSV에 넣을 factor_id를 고를 때 쓴다.

        Args:
            query: 부분 문자열 필터(factor_id·활동·출처 대상). 예: "freight", "폐기물", "commute".

        Returns:
            dict: {ok, factors_version, count,
                   factors[{factor_id, value, unit, scope, category, activity,
                            confidence, year, gwp_basis, source, note}],
                   usage{CSV 열, 단위 규칙, 통근 제한}}

        note의 한계 경고(예: UK 프록시, 소각계수의 직접 CO2 제외)를 사용자에게
        함께 전달할 것 — 헤드라인 수치에 영향을 준다.
        """
        return list_factors_impl(query)

    @mcp.tool(name="carbonledger_inventory_template",
              annotations=_ann("조직 선언 템플릿", read_only=True, idempotent=True))
    def carbonledger_inventory_template() -> dict[str, Any]:
        """조직 선언(input/inventory.json) 템플릿과 각 항목의 의미를 반환한다.

        배출량이 '무엇에 대한 숫자인지'(조직명·보고기간·연결기준·조직경계·제외 사유·
        검증 상태)는 툴이 알 수 없다. 이 파일에 적으면 리포트 §0에 그대로 전재된다.

        Returns:
            dict: {ok, filename, template{...}, fields[{key,label,desc}], note}

        내용은 **사용자에게 물어서** 채울 것. 조직경계·제외 사유를 에이전트가
        지어내면 리포트가 거짓 선언을 싣게 된다.
        """
        return inventory_template_impl()

    @mcp.tool(name="carbonledger_diff",
              annotations=_ann("두 실행 대조", read_only=True, idempotent=True))
    def carbonledger_diff(prev_records_json: str, curr_records_json: str,
                          out_path: str | None = None) -> dict[str, Any]:
        """두 실행(예: 전년·금년)을 대조해 무엇이 왜 달라졌는지 낸다.

        배출량 증감보다 **산정 기준의 변화**(보고기간·계수판 버전·카테고리 집합·
        계수값)를 먼저 본다. 기준이 바뀌면 두 수치는 비교 대상이 아니다.
        요인분해로 증감이 활동량 때문인지 계수 때문인지 가른다.

        Args:
            prev_records_json: 이전 실행의 records.json 경로.
            curr_records_json: 이번 실행의 records.json 경로.
            out_path: 대조 리포트(.md) 저장 경로(선택).

        Returns:
            dict: {ok, basis_changed, basis[], categories_added[], categories_removed[],
                   factors_changed[], totals{}, scopes[], decomposition[], markdown_path, note}
        """
        return diff_impl(prev_records_json, curr_records_json, out_path)

    @mcp.tool(name="carbonledger_selftest",
              annotations=_ann("설치 자체검증", read_only=True, idempotent=True))
    def carbonledger_selftest() -> dict[str, Any]:
        """네트워크·LLM 없이 전 모듈 자체 검증을 돌린다(설치·계수판 정합 확인).

        Returns:
            dict: {ok, tool_version, factors_version, detail[]} 또는 {ok:false, error, hint}
        """
        return selftest_impl()

    return mcp


def main():
    """stdio MCP 서버 실행(엔트리포인트: carbonledger-mcp)."""
    try:
        server = build_server()
    except ImportError:
        raise SystemExit(
            "MCP SDK가 없습니다. 설치: pip install \"carbonledger[mcp]\"\n"
            "(CLI만 쓰려면 이 서버 없이 `carbonledger run ...`을 그대로 사용하세요)")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
