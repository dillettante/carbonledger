"""증빙 이미지/PDF → 구조화 JSON 추출 (갈래 B: 비전 LLM).

비전 LLM에 증빙을 통째로 던져 필드를 뽑는다. YOLO·라벨링 불필요.
문서유형별 차이는 DOC_SPECS(프롬프트·필드) 데이터로만 갈린다 — 엔진 코드는 하나.
PDF는 render_to_image()가 이미지로 렌더한다(폴백 사다리 + 백지 방어).

백엔드 4종 (CARBONLEDGER_BACKEND 환경변수, 기본 lmstudio):
  · lmstudio  — 로컬 LM Studio(OpenAI 호환, localhost:1234). **증빙이 외부로 안 나감**(기밀에 권장).
  · ollama    — 로컬 Ollama(OpenAI 호환, localhost:11434). **증빙이 외부로 안 나감**. `ollama pull qwen3-vl:4b`.
  · openai    — OpenAI API(OPENAI_API_KEY). ⚠️ 증빙 이미지가 OpenAI로 전송됨.
  · anthropic — Anthropic Claude(ANTHROPIC_API_KEY). ⚠️ 증빙 이미지가 Anthropic으로 전송됨.
상용 백엔드는 로컬 모델보다 정확도가 높지만, **기밀 증빙이 외부 제공자로 나간다**(개인정보·영업비밀 주의).
"""
import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# 백엔드별 엔드포인트·기본 모델
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODELS = {
    "lmstudio": "qwen/qwen3-vl-4b",
    "ollama": "qwen3-vl:4b",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-5",
}

# ── 문서유형 스펙: 프롬프트 + 기대 필드 ────────────────────────────
# scope/category는 폴더가 선언(cli), 여기선 '무엇을 뽑나'만 정의.
_FIELDS_TRANSPORT = ('{"transport":"철도|항공|버스|기타","origin":"출발지",'
                     '"destination":"도착지","date":"YYYY-MM-DD",'
                     '"amount":정수(원),"passenger":"이름 또는 null"}')
_FIELDS_HOTEL = ('{"doc":"숙박","name":"숙소명","checkin":"YYYY-MM-DD",'
                 '"nights":정수,"amount":정수(원),"guest":"이름 또는 null"}')
_FIELDS_FUEL = ('{"doc":"주유","fuel_type":"휘발유|경유|LPG|기타","liters":실수(리터),'
                '"unit_price":정수(원/L 또는 null),"amount":정수(원),"date":"YYYY-MM-DD"}')
_FIELDS_GAS = ('{"doc":"도시가스","usage":실수,"unit":"m3|MJ","amount":정수(원),'
               '"billing_month":"YYYY-MM"}')
_FIELDS_ELEC = ('{"doc":"전기","kwh":실수(사용량 kWh),"prev_reading":실수 또는 null,'
                '"curr_reading":실수 또는 null,"amount":정수(원),"billing_month":"YYYY-MM"}')

DOC_SPECS = {
    "transport": {
        "prompt": ("너는 한국 교통 영수증·승차권에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 이미지에 없는 값은 null.\n" + _FIELDS_TRANSPORT),
        "fields": ["transport", "origin", "destination", "date", "amount", "passenger"],
    },
    "hotel": {
        "prompt": ("너는 한국 숙박 영수증에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 없는 값은 null. nights=숙박 일수(박).\n"
                   + _FIELDS_HOTEL),
        "fields": ["doc", "name", "checkin", "nights", "amount", "guest"],
    },
    "fuel": {
        "prompt": ("너는 한국 주유 영수증에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 없는 값은 null. liters=주유량(리터), "
                   "fuel_type은 휘발유/경유/LPG 중 하나로 정규화.\n" + _FIELDS_FUEL),
        "fields": ["doc", "fuel_type", "liters", "unit_price", "amount", "date"],
    },
    "gas": {
        "prompt": ("너는 한국 도시가스 요금 고지서에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 없는 값은 null. usage=이번 달 사용량 숫자, "
                   "unit은 사용량 단위(m3 또는 MJ)를 고지서 표기 그대로. "
                   "billing_month=사용월/청구년월이며 납기일이 아니다.\n" + _FIELDS_GAS),
        "fields": ["doc", "usage", "unit", "amount", "billing_month"],
    },
    "electricity": {
        "prompt": ("너는 한국전력 전기요금 고지서에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 없는 값은 null. kwh=당월 사용전력량(kWh), "
                   "prev_reading·curr_reading=전월/당월 지침(계기 표시값)이 있으면 숫자로. "
                   "billing_month=사용월/청구년월이며 납기일이 아니다(예: '2026년 05월'→2026-05). "
                   "amount=청구금액 합계(개별 항목이 아니라 최종 합계).\n"
                   + _FIELDS_ELEC),
        "fields": ["doc", "kwh", "prev_reading", "curr_reading", "amount", "billing_month"],
    },
}


def _media_type(img: bytes) -> str:
    """바이트 매직으로 이미지 MIME 판정(확장자 신뢰 안 함)."""
    if img[:8].startswith(b"\x89PNG"):
        return "image/png"
    if img[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if img[:4] == b"RIFF" and img[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _data_url(img: bytes) -> str:
    return f"data:{_media_type(img)};base64," + base64.b64encode(img).decode()


def _looks_blank(png: bytes) -> bool:
    """렌더 결과가 백지인지 잉크 비율로 판정(깨진 PDF의 조용한 실패 방어).

    깨진 PDF는 fitz가 exit 0으로 백지 이미지를 내놓는다(지난 세션 법원실무제요 사례).
    백지를 비전 LLM에 넘기면 환각 추출로 이어지므로 렌더 단계에서 걸러 폴백으로 보낸다.
    PNG를 통째 디코드하지 않고 파일 크기 휴리스틱으로 싸게 1차 판정한다.
    """
    # ponytail: 크기 휴리스틱. 백지 PNG는 극단적으로 작다(단색 압축).
    #           정밀 판정이 필요해지면 Pillow로 픽셀 분산 검사로 승격.
    return len(png) < 3000


_MAX_PDF_PAGES = 3  # ponytail: 고지서는 통상 1~2쪽. 3쪽 초과는 비용·토큰 낭비라 절단(로그로 고지)


def render_pages(path: str) -> list[bytes]:
    """증빙 파일 → 이미지 바이트 리스트. 이미지는 [원본], PDF는 페이지별 렌더(최대 3쪽).

    PDF 폴백 사다리(전부 로컬): pymupdf(다중페이지) → macOS sips(첫 쪽만). 백지 쪽은 제외.
    렌더 가능한 쪽이 하나도 없으면 RenderError — 호출부가 review 큐로 보낸다.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return [p.read_bytes()]
    if ext != ".pdf":
        raise RenderError(f"지원 안 하는 형식: {ext}")

    # 1) pymupdf(fitz) — 다중페이지·해상도 제어
    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        if doc.page_count > _MAX_PDF_PAGES:
            print(f"[알림] {p.name}: {doc.page_count}쪽 중 앞 {_MAX_PDF_PAGES}쪽만 읽음")
        pages = []
        for i in range(min(doc.page_count, _MAX_PDF_PAGES)):
            png = doc[i].get_pixmap(dpi=200).tobytes("png")
            if not _looks_blank(png):
                pages.append(png)
        if pages:
            return pages
    except ImportError:
        pass
    except Exception:  # 깨진 PDF 등 — 다음 폴백으로
        pass

    # 2) macOS sips — 첫 페이지만 변환(한계). 다중페이지 PDF는 pymupdf 설치 권장
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            out = tf.name
        subprocess.run(["sips", "-s", "format", "png", "--resampleWidth", "1600",
                        path, "--out", out],
                       check=True, capture_output=True, timeout=60)
        png = Path(out).read_bytes()
        Path(out).unlink(missing_ok=True)
        if not _looks_blank(png):
            return [png]
    except Exception:
        pass

    raise RenderError(
        f"PDF 렌더 실패(백지/손상): {p.name} — 원본 재확보 또는 이미지 변환 후 재시도")


def render_to_image(path: str) -> bytes:
    """단일 이미지 하위호환 래퍼(첫 쪽)."""
    return render_pages(path)[0]


class RenderError(RuntimeError):
    """PDF를 읽을 수 있는 이미지로 렌더하지 못함(손상·백지·형식 미지원)."""


def _parse_json(text: str) -> dict:
    """```json``` 이나 설명이 섞여도 첫 {..} 덩어리를 건져 파싱."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"JSON을 못 찾음: {text[:200]}")
    return json.loads(m.group(0))


def backend() -> str:
    """현재 LLM 백엔드(CARBONLEDGER_BACKEND, 기본 lmstudio)."""
    return os.environ.get("CARBONLEDGER_BACKEND", "lmstudio").lower()


def resolve_model(model: str | None) -> str:
    """--model 미지정 시 백엔드별 기본 모델. 지정 시 그대로."""
    return model or DEFAULT_MODELS.get(backend(), DEFAULT_MODELS["lmstudio"])


def extract(path: str, doc_type: str, model: str | None = None) -> dict:
    """증빙 → DOC_SPECS[doc_type] 프롬프트로 비전 LLM 추출. 결과 dict 반환.

    백엔드(lmstudio/openai/anthropic)는 CARBONLEDGER_BACKEND로 선택. 상용은 이미지가 외부 전송됨.
    PDF는 페이지별로 렌더돼(최대 3쪽) 한 번의 호출에 모두 들어간다.
    """
    spec = DOC_SPECS[doc_type]
    pages = render_pages(path)
    model = resolve_model(model)
    b = backend()
    if b == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 미설정 (CARBONLEDGER_BACKEND=anthropic)")
        text = _call_anthropic(key, spec["prompt"], pages, model)
    elif b == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:  # 키 없이 호출하면 건별 401이 흩어진다 — 선검사로 한 번에 알림
            raise RuntimeError("OPENAI_API_KEY 미설정 (CARBONLEDGER_BACKEND=openai)")
        text = _call_openai_compat(OPENAI_URL, key, spec["prompt"], pages, model)
    elif b == "ollama":  # 로컬, 키 불필요
        text = _call_openai_compat(OLLAMA_URL, None, spec["prompt"], pages, model)
    else:  # lmstudio (로컬, 키 불필요)
        text = _call_openai_compat(LM_STUDIO_URL, None, spec["prompt"], pages, model)
    return _parse_json(text)


def _call_openai_compat(url: str, key: str | None, prompt: str,
                        pages: list[bytes], model: str) -> str:
    """OpenAI 호환 chat/completions(비전, 다중 이미지). LM Studio·OpenAI 공용."""
    import requests
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": _data_url(p)}} for p in pages]
    payload = {"model": model, "temperature": 0,
               "messages": [{"role": "user", "content": content}]}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_anthropic(key: str, prompt: str, pages: list[bytes], model: str) -> str:
    """Anthropic Messages API(비전, 다중 이미지)."""
    import requests
    content = [{"type": "image", "source": {"type": "base64",
                "media_type": _media_type(p), "data": base64.b64encode(p).decode()}}
               for p in pages]
    content.append({"type": "text", "text": prompt})
    payload = {"model": model, "max_tokens": 1024, "temperature": 0,
               "messages": [{"role": "user", "content": content}]}
    r = requests.post(ANTHROPIC_URL, json=payload, timeout=120, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def selftest():
    # JSON 관대 파싱
    assert _parse_json('설명\n```json\n{"a":1}\n```') == {"a": 1}, "관대 파싱 실패"

    # 백지 판정
    assert _looks_blank(b"x" * 100), "작은 바이트=백지여야"
    assert not _looks_blank(b"x" * 5000), "큰 바이트=비백지여야"

    # 이미지 바이트 passthrough (임시 PNG)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"\x89PNG\r\n" + b"x" * 100)
        tmp = tf.name
    assert render_to_image(tmp).startswith(b"\x89PNG"), "이미지 passthrough 실패"
    Path(tmp).unlink(missing_ok=True)

    # 미지원 형식
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        bad = tf.name
    try:
        render_to_image(bad)
        assert False, "미지원 형식을 통과시킴"
    except RenderError:
        pass
    Path(bad).unlink(missing_ok=True)

    assert set(DOC_SPECS) == {"transport", "hotel", "fuel", "gas", "electricity"}, \
        "DOC_SPECS 구성 변경됨"

    # 매직바이트 MIME 판정
    assert _media_type(b"\x89PNG\r\n\x1a\n") == "image/png", "PNG 판정 실패"
    assert _media_type(b"\xff\xd8\xff\xe0") == "image/jpeg", "JPEG 판정 실패"

    # 백엔드 기본 모델 해석
    assert resolve_model(None) in DEFAULT_MODELS.values(), "기본 모델 해석 실패"
    assert resolve_model("custom-x") == "custom-x", "지정 모델 무시됨"
    assert backend() in ("lmstudio", "ollama", "openai", "anthropic"), "백엔드 값 이상"
    assert set(DEFAULT_MODELS) == {"lmstudio", "ollama", "openai", "anthropic"}, "기본모델표 불일치"
    print("extract selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
