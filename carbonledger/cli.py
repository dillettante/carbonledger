"""carbonledger CLI — 증빙 폴더를 일괄 처리해 조직 탄소발자국 리포트를 낸다.

입력 폴더 구조가 Scope 귀속을 선언한다(AI가 추측하지 않음, boundary.md 참조):
    input/
    ├── scope1-fuel/      # 법인차·시설 연료 영수증·고지서 → Scope 1
    ├── scope2-energy/    # 전기 고지서 → Scope 2
    ├── travel/           # 출장 승차권·항공권·숙박 영수증 → Scope 3 cat.6
    ├── commute.csv       # 통근 설문 → Scope 3 cat.7
    ├── spend.csv         # 구매 지출(사용자 계수 포함) → Scope 3 cat.1
    └── scope3/           # 나머지 카테고리 cat{N}_*.csv (2·4·5·8~15)

명령:
    carbonledger run <입력폴더> [--period 2026] [--model 모델명] [--out OUT]
    carbonledger selftest        # 네트워크 없이 전 모듈 검증
    carbonledger review <OUT>    # 검토 큐 조회 + reviewed/*.json 병합 재집계

LLM 백엔드: CARBONLEDGER_BACKEND = lmstudio(기본·로컬) | ollama(로컬) | openai | anthropic (extract.py 참조).
"""
import argparse
import csv
import re
import sys
from pathlib import Path

from . import calc, extract, report, scope3, validate

_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def _in_period(date_str, period) -> bool:
    """레코드 날짜가 보고기간(연도) 안인가. period 없으면 항상 True."""
    if not period or not date_str:
        return True
    return str(date_str).startswith(str(period))


def _period_ok(fname, date_str, period, queue) -> bool:
    """보고기간 검사 + fail-closed. period 지정 시 날짜 결측이면 review 큐로.

    날짜가 없으면 그 건이 보고기간 안인지 확인할 수 없으므로 조용히 포함하지 않는다
    (fail-open이면 타 연도 배출이 총계에 섞인다 — 반증검토 지적).
    """
    if period and not date_str:
        queue.append({"source_file": fname,
                      "issues": ["보고기간 확인 불가: 날짜 미추출 — 수기 확인 후 재집계"]})
        return False
    if not _in_period(date_str, period):
        queue.append({"source_file": fname, "issues": [f"보고기간 밖: {date_str}"]})
        return False
    return True


def _process_travel(folder: Path, model: str, period, records, queue):
    """input/travel/ 이미지 → 출장(교통·숙박) 추출·검증·산정."""
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in _IMG_EXT:
            continue
        # 숙박 vs 교통: 파일명 힌트로 스펙 선택(둘 다 travel 폴더라 scope는 동일)
        doc_type = "hotel" if _looks_hotel(f) else "transport"
        try:
            rec = extract.extract(str(f), doc_type, model)
        except Exception as e:  # 렌더·추출 실패 → 큐(백지 PDF 등)
            queue.append({"source_file": f.name, "issues": [f"추출 실패: {e}"]})
            continue

        issues = (validate.validate_hotel(rec) if doc_type == "hotel"
                  else validate.validate_transport(rec))
        if issues:
            queue.append({"source_file": f.name, "extracted": rec, "issues": issues})
            continue

        _calc_travel(f.name, doc_type, rec, period, records, queue)


def _looks_hotel(path: Path) -> bool:
    """파일명 힌트로 숙박 여부 추정(1차 추출이 애매할 때만)."""
    n = path.name.lower()
    return any(k in n for k in ("hotel", "숙박", "호텔", "stay"))


def _calc_travel(fname, doc_type, rec, period, records, queue):
    if doc_type == "hotel":
        if not _period_ok(fname, rec.get("checkin"), period, queue):
            return
        e = calc.scope3_hotel(rec["nights"])
        records.append({"source_file": fname, "scope": 3, "category": 6,
                        "activity": f"숙박 {rec.get('name','')}",
                        **e, "extracted": rec})
        return

    if not _period_ok(fname, rec.get("date"), period, queue):
        return
    km = calc.distance_km(rec["origin"], rec["destination"], rec["transport"])
    if km is None:
        queue.append({"source_file": fname, "extracted": rec,
                      "issues": ["거리 산정 실패(지도 API 키(Kakao/Naver) 미설정 또는 지명 조회 실패)"]})
        return
    e = calc.scope3_travel(rec["transport"], km)
    records.append({"source_file": fname, "scope": 3, "category": 6,
                    "activity": f"{rec['transport']} {rec['origin']}→{rec['destination']}",
                    **e, "extracted": rec})


def _bill_period_key(rec):
    """고지서 날짜(billing_month 또는 date) — 보고기간 필터용."""
    return rec.get("billing_month") or rec.get("date")


def _process_bills(folder: Path, folder_kind: str, model: str, period, records, queue):
    """Scope 1·2 고지서 폴더 처리. folder_kind: scope1-fuel | scope2-energy.

    파일명 힌트로 doc_type(fuel/gas/electricity) 선택 → 추출 → 검증(교차산술) → 산정.
    폴더 선언과 문서유형이 어긋나면(전기 폴더에 가스) review 큐(관문 ③).
    """
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in _IMG_EXT:
            continue
        doc_type = _guess_bill_type(f, folder_kind)
        try:
            rec = extract.extract(str(f), doc_type, model)
        except Exception as e:
            queue.append({"source_file": f.name, "issues": [f"추출 실패: {e}"]})
            continue

        issues = {"fuel": validate.validate_fuel, "gas": validate.validate_gas,
                  "electricity": validate.validate_electricity}[doc_type](rec)
        issues += validate.validate_folder_type(folder_kind, doc_type)
        pkey = _bill_period_key(rec)
        if period and not pkey:
            issues.append("보고기간 확인 불가: 날짜 미추출 — 수기 확인 후 재집계")
        elif not _in_period(pkey, period):
            issues.append(f"보고기간 밖: {pkey}")
        if issues:
            queue.append({"source_file": f.name, "extracted": rec, "issues": issues})
            continue

        _calc_bill(f.name, doc_type, rec, records, queue)


def _guess_bill_type(path: Path, folder_kind: str) -> str:
    """파일명 힌트 → 고지서 유형. 힌트 없으면 폴더 기본값.

    주유(fuel)를 가스보다 먼저 검사한다 — 'gasoline'에 'gas'가 들어 있어
    가스 검사를 먼저 하면 주유 영수증이 도시가스로 오분류된다.
    """
    n = path.name.lower()
    if any(k in n for k in ("주유", "fuel", "gasoline", "diesel", "경유", "휘발유")):
        return "fuel"
    if any(k in n for k in ("도시가스", "가스", "citygas")):
        return "gas"
    if any(k in n for k in ("전기", "elec", "kepco", "한전", "power")):
        return "electricity"
    return "electricity" if folder_kind == "scope2-energy" else "fuel"


def _calc_bill(fname, doc_type, rec, records, queue):
    try:
        if doc_type == "fuel":
            e = calc.scope1_fuel(rec["fuel_type"], validate._num(rec["liters"]))
            scope, cat, act = 1, None, f"{rec['fuel_type']} 주유"
        elif doc_type == "gas":
            e = calc.scope1_citygas(validate._num(rec["usage"]), rec["unit"])
            scope, cat, act = 1, None, "도시가스 연소"
        else:  # electricity
            e = calc.scope2_electricity(validate._num(rec["kwh"]))
            scope, cat, act = 2, None, "전력 사용"
    except Exception as ex:
        queue.append({"source_file": fname, "extracted": rec,
                      "issues": [f"산정 실패: {ex}"]})
        return
    records.append({"source_file": fname, "scope": scope, "category": cat,
                    "activity": act, **e, "extracted": rec})


def _process_commute(csv_path: Path, records, queue):
    """commute.csv → Scope 3 cat.7. 열: mode,factor_id,oneway_km,workdays,employee_id."""
    with csv_path.open(encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), 1):
            try:
                oneway = float(row["oneway_km"]); days = int(row["workdays"])
                annual = oneway * 2 * days
                e = calc.scope3_commute(row["factor_id"], annual)
                records.append({"source_file": f"{csv_path.name}#{i}", "scope": 3,
                                "category": 7, "activity": f"통근 {row.get('mode','')}",
                                **e, "extracted": row})
            except Exception as ex:
                queue.append({"source_file": f"{csv_path.name}#{i}",
                              "issues": [f"통근행 처리 실패: {ex}"]})


def _process_spend(csv_path: Path, records, queue):
    """spend.csv → Scope 3 cat.1(지출기반). 열: item,krw,factor,factor_source.

    한국 공개 지출계수표 부재 → factor·factor_source를 사용자가 직접 입력해야 한다.
    """
    with csv_path.open(encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), 1):
            try:
                krw = float(row["krw"]); f = float(row["factor"])
                src = row.get("factor_source", "").strip()
                if not src:
                    raise ValueError("factor_source(계수 출처) 필수 — 감사추적")
                e = calc.scope3_spend(krw, f, src)
                records.append({"source_file": f"{csv_path.name}#{i}", "scope": 3,
                                "category": 1, "activity": f"구매 {row.get('item','')}",
                                **e, "extracted": row})
            except Exception as ex:
                queue.append({"source_file": f"{csv_path.name}#{i}",
                              "issues": [f"지출행 처리 실패: {ex}"]})


def cmd_run(a):
    root = Path(a.input)
    if not root.is_dir():
        sys.exit(f"입력 폴더 없음: {root}")
    records, queue = [], []

    travel = root / "travel"
    if travel.is_dir():
        _process_travel(travel, a.model, a.period, records, queue)
    for sub in ("scope1-fuel", "scope2-energy"):
        if (root / sub).is_dir():
            _process_bills(root / sub, sub, a.model, a.period, records, queue)

    if (root / "commute.csv").exists():
        _process_commute(root / "commute.csv", records, queue)
    if (root / "spend.csv").exists():
        _process_spend(root / "spend.csv", records, queue)

    # Scope 3 카테고리 2·4·5·8~15: input/scope3/cat{N}_*.csv (통일 스키마 어댑터)
    s3dir = root / "scope3"
    if s3dir.is_dir():
        for f in sorted(s3dir.glob("cat*.csv")):
            m = re.match(r"cat(\d+)", f.name)
            if not m:
                continue
            cat = int(m.group(1))
            if cat == 15:
                scope3.process_pcaf(f, records, queue)
            elif cat in scope3.CSV_CATEGORIES:
                scope3.process_csv(f, cat, records, queue)
            else:
                print(f"[알림] {f.name}: 카테고리 {cat}는 CSV 자동산정 대상 아님 — 건너뜀")

    # 카테고리 3(연료·에너지 관련) — Scope 1·2 산정 후 파생(WTT/T&D 계수 있을 때만)
    scope3.derive_category3(records, queue)

    out = a.out or str(root / "out")
    summary = report.build(records, queue, out, period=a.period)
    print(f"\n리포트 생성: {out}/report.md · report.xlsx · records.json")
    print(f"  Scope1 {summary['scope1']} / Scope2 {summary['scope2']} / "
          f"Scope3 {summary['scope3']} kg  → 합계 {summary['total_kgco2e']} kgCO2eq")
    print(f"  산정 {summary['records']}건 · 검토대기(미포함) {summary['review']}건")


def cmd_review(a):
    """검토 큐 조회 + reviewed/*.json 병합 재집계(human-in-the-loop 완결)."""
    import json
    out = Path(a.out)
    rec_file = out / "records.json"
    if not rec_file.exists():
        sys.exit(f"records.json 없음: {out}")
    data = json.loads(rec_file.read_text(encoding="utf-8"))
    queue = data.get("review_queue", [])
    reviewed_dir = out / "reviewed"

    corrected = []
    if reviewed_dir.is_dir():
        for jf in sorted(reviewed_dir.glob("*.json")):
            c = json.loads(jf.read_text(encoding="utf-8"))
            c["human_corrected"] = True   # 감사추적 표지
            corrected.append(c)

    if not corrected:
        print(f"검토 대기 {len(queue)}건. 교정하려면 각 건을 아래 형식으로 "
              f"{reviewed_dir}/*.json 에 저장 후 재실행:")
        for q in queue:
            print(f"  - {q.get('source_file')}: {'; '.join(q.get('issues', []))}")
        print("\n(교정 레코드 형식은 records.json의 records[] 항목과 동일 + kgco2e 계산값)")
        return

    merged = data["records"] + corrected
    report.build(merged, [q for q in queue], str(out), period=data.get("period"))
    print(f"교정 {len(corrected)}건 병합 재집계 완료 → {out}/report.md")


def cmd_selftest(a):
    from . import factors
    factors.selftest(); calc.selftest(); extract.selftest()
    validate.selftest(); scope3.selftest(); report.selftest()
    print("\n전 모듈 selftest 통과 ✅ (네트워크 없음)")


def main():
    ap = argparse.ArgumentParser(prog="carbonledger",
                                 description="영수증·고지서 등 기초자료를 LLM으로 읽어 조직 온실가스(Scope 1·2·3)·탄소발자국 산정")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="증빙 폴더 일괄 처리 → 리포트")
    r.add_argument("input", help="입력 폴더(scope1-fuel/·travel/·commute.csv 등)")
    r.add_argument("--period", help="보고기간 연도(예: 2026). 밖의 건은 미포함")
    r.add_argument("--model", default=None,
                   help="비전 모델(미지정 시 백엔드별 기본: lmstudio/ollama=qwen3-vl-4b·openai=gpt-4o·anthropic=claude-sonnet-5)")
    r.add_argument("--out", help="출력 폴더(기본: <입력>/out)")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("review", help="검토 큐 조회 + 교정본 병합 재집계")
    v.add_argument("out", help="리포트 출력 폴더(records.json 위치)")
    v.set_defaults(func=cmd_review)

    s = sub.add_parser("selftest", help="네트워크 없이 전 모듈 검증")
    s.set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
