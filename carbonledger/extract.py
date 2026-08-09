"""증빙 이미지/PDF → 구조화 JSON 추출 (갈래 B: 비전 LLM).

비전 LLM에 증빙을 통째로 던져 필드를 뽑는다. YOLO·라벨링 불필요.
문서유형별 차이는 DOC_SPECS(프롬프트·필드) 데이터로만 갈린다 — 엔진 코드는 하나.
PDF는 render_to_image()가 이미지로 렌더한다(폴백 사다리 + 백지 방어).

백엔드 (CARBONLEDGER_BACKEND 환경변수, 기본 lmstudio):
  · lmstudio  — 로컬 LM Studio(OpenAI 호환, localhost:1234). **증빙이 외부로 안 나감**(기밀에 권장).
  · ollama    — 로컬 Ollama(OpenAI 호환, localhost:11434). **증빙이 외부로 안 나감**. `ollama pull qwen3-vl:4b`.
  · openai    — OpenAI API(OPENAI_API_KEY). ⚠️ 증빙 이미지가 OpenAI로 전송됨.
  · anthropic — Anthropic Claude(ANTHROPIC_API_KEY). ⚠️ 증빙 이미지가 Anthropic으로 전송됨.
  · custom    — **임의의 OpenAI 호환 제공자**. CARBONLEDGER_BASE_URL로 주소를 지정한다.
                Gemini·xAI·OpenRouter·Together·사내 vLLM 등 어디든 코드 수정 없이 붙는다.
상용 백엔드는 로컬 모델보다 정확도가 높지만, **기밀 증빙이 외부 제공자로 나간다**(개인정보·영업비밀 주의).

## 왜 'custom'이 있나

이름 붙은 4종만 지원하면 새 제공자가 나올 때마다 코드를 고쳐야 하고, 사용자는
그때까지 못 쓴다. 그런데 OpenAI 호환 규격을 따르는 제공자는 **주소와 모델명만
다를 뿐 요청·응답 형태가 같다** — 이미 `_call_openai_compat` 한 함수가 로컬 2종과
OpenAI를 함께 처리하고 있었다. 그 주소를 사용자가 정할 수 있게 연 것이 custom이다.
새 코드 경로가 아니라 기존 경로의 매개변수화이므로 검증 표면이 늘지 않는다.
"""
import base64
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

# ── 상용 API 제약(공식 문서 기준) ─────────────────────────────────────
# Anthropic Messages API: 이미지 1장당 10MB(base64 인코딩 후), 요청 전체 32MB(초과 시 413),
# 이미지 최대 8000×8000px. 로컬 백엔드(LM Studio·Ollama)는 이런 상한이 없다.
# 사전 점검 없이 보내면 수백 장 배치가 413로 무더기 실패하고, 원인이 응답 본문에만 남는다.
_B64_OVERHEAD = 4 / 3          # base64는 원본의 약 4/3배
_ANTHROPIC_MAX_IMAGE_B64 = 10 * 1024 * 1024
_ANTHROPIC_MAX_REQUEST = 32 * 1024 * 1024

# 재시도: 공식 문서가 '지수 백오프로 재시도'를 지시하는 코드만 고른다.
# 400(잘못된 요청)·401(인증)·403(권한)·413(크기 초과)은 재시도해도 같은 결과라 즉시 실패시킨다.
_RETRY_STATUS = {429, 500, 502, 503, 504, 529}
_MAX_ATTEMPTS = 3              # 공식 SDK 기본값(재시도 2회)과 동일
_BACKOFF_BASE = 1.0            # 1s → 2s (지수)
_sleep = time.sleep            # 테스트에서 갈아끼울 수 있게 참조로 둔다

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
    # custom은 제공자를 모르므로 기본 모델을 정할 수 없다 — 사용자가 --model 또는
    # CARBONLEDGER_MODEL로 반드시 지정한다(추측하면 엉뚱한 모델로 과금된다).
    "custom": None,
}
BACKENDS = tuple(DEFAULT_MODELS)


def _custom_url() -> str:
    """custom 백엔드의 엔드포인트. 끝이 /chat/completions가 아니면 붙여 준다.

    사용자는 보통 제공자 문서의 'base URL'(…/v1)을 그대로 복사해 온다.
    그때마다 404를 내는 대신 관용적으로 받아 준다 — 단, 무엇으로 해석했는지는
    오류 시 메시지에 드러난다.
    """
    base = (os.environ.get("CARBONLEDGER_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "CARBONLEDGER_BASE_URL 미설정 (CARBONLEDGER_BACKEND=custom)\n"
            "  예) Gemini : https://generativelanguage.googleapis.com/v1beta/openai\n"
            "      xAI    : https://api.x.ai/v1\n"
            "      사내 vLLM: http://10.0.0.5:8000/v1")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"

# ── 문서유형 스펙: 프롬프트 + 기대 필드 ────────────────────────────
# scope/category는 폴더가 선언(cli), 여기선 '무엇을 뽑나'만 정의.
# 개인정보 최소수집: 탑승자·투숙객 성명은 배출량 산정에 쓰이지 않으므로 추출하지 않는다
_FIELDS_TRANSPORT = ('{"transport":"철도|항공|버스|기타","origin":"출발지",'
                     '"destination":"도착지","date":"YYYY-MM-DD","amount":정수(원)}')
_FIELDS_HOTEL = ('{"doc":"숙박","name":"숙소명","checkin":"YYYY-MM-DD",'
                 '"nights":정수,"amount":정수(원)}')
_FIELDS_FUEL = ('{"doc":"주유","fuel_type":"휘발유|경유|LPG|기타","liters":실수(리터),'
                '"unit_price":정수(원/L 또는 null),"amount":정수(원),"date":"YYYY-MM-DD"}')
_FIELDS_GAS = ('{"doc":"도시가스","usage":실수,"unit":"m3|MJ","amount":정수(원),'
               '"billing_month":"YYYY-MM"}')
_FIELDS_ELEC = ('{"doc":"전기","kwh":실수(사용량 kWh),"prev_reading":실수 또는 null,'
                '"curr_reading":실수 또는 null,"amount":정수(원),"billing_month":"YYYY-MM"}')

DOC_SPECS = {
    "transport": {
        "prompt": ("너는 한국 교통 영수증·승차권에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 이미지에 없는 값은 null. 승객 성명 등 개인정보는 추출하지 마라.\n" + _FIELDS_TRANSPORT),
        "fields": ["transport", "origin", "destination", "date", "amount"],
    },
    "hotel": {
        "prompt": ("너는 한국 숙박 영수증에서 정보를 뽑는 추출기다. JSON으로만 출력. "
                   "설명·코드블록 없이 순수 JSON. 없는 값은 null. nights=숙박 일수(박). 투숙객 성명 등 개인정보는 추출하지 마라.\n"
                   + _FIELDS_HOTEL),
        "fields": ["doc", "name", "checkin", "nights", "amount"],
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
_PDF_DPI = 200            # 고지서 밀집 표가 읽히는 실측 하한
_PDF_DPI_FALLBACK = 110   # 상한 초과 시 재렌더용(가독성 손실 < 전송 실패)


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
            png = doc[i].get_pixmap(dpi=_PDF_DPI).tobytes("png")
            # 큰 지면·고해상도는 상용 API 이미지 상한을 넘을 수 있다. 우리가 DPI를
            # 정하는 경로이므로 낮춰 다시 렌더하면 해결된다(이미지 라이브러리 불필요).
            if len(png) * _B64_OVERHEAD > _ANTHROPIC_MAX_IMAGE_B64:
                png = doc[i].get_pixmap(dpi=_PDF_DPI_FALLBACK).tobytes("png")
                print(f"[알림] {p.name} {i+1}쪽: 용량이 커 {_PDF_DPI_FALLBACK}dpi로 낮춰 렌더"
                      "(글자가 작으면 원본을 잘라 나눠 입력할 것)")
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

    # 원인은 둘 중 하나다: ①손상·백지 PDF ②렌더러 부재(pymupdf 미설치 + 비macOS라
    # sips도 없음). ②를 ①로 읽으면 사용자가 멀쩡한 PDF를 의심하게 되므로 둘 다 적는다.
    raise RenderError(
        f"PDF 렌더 실패: {p.name} — 손상·백지 PDF이거나 렌더러 부재. "
        "pymupdf 미설치면 `pip install '.[pdf]'`(macOS 외 필수), "
        "손상이면 원본 재확보 또는 이미지 변환 후 재시도")


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
    """모델 결정: --model > CARBONLEDGER_MODEL > 백엔드 기본값.

    custom 백엔드는 제공자를 모르므로 기본값이 없다 — 지정하지 않으면 실행 전에
    막는다(엉뚱한 모델명으로 건별 4xx가 흩어지는 것보다 낫다).
    """
    m = model or os.environ.get("CARBONLEDGER_MODEL") or DEFAULT_MODELS.get(backend())
    if not m:
        raise RuntimeError(
            f"모델 미지정 (CARBONLEDGER_BACKEND={backend()}) — "
            "--model 또는 CARBONLEDGER_MODEL로 지정할 것"
            "\n  예) --model gemini-2.5-flash / grok-4 / qwen2.5-vl-7b-instruct")
    return m


def extract(path: str, doc_type: str, model: str | None = None) -> dict:
    """증빙 → DOC_SPECS[doc_type] 프롬프트로 비전 LLM 추출. 결과 dict 반환.

    백엔드는 CARBONLEDGER_BACKEND로 선택(§모듈 독스트링). 상용·custom은 이미지가 외부 전송됨.
    PDF는 페이지별로 렌더돼(최대 3쪽) 한 번의 호출에 모두 들어간다.
    """
    spec = DOC_SPECS[doc_type]
    b = backend()
    # 백엔드 검증이 모델 해석보다 먼저다 — 오타 백엔드는 기본 모델이 없어서
    # 순서가 반대면 '모델 미지정'이라는 엉뚱한 사유가 나온다(진짜 원인은 오타).
    if b not in BACKENDS:
        raise RuntimeError(
            f"알 수 없는 백엔드: {b!r} — 사용 가능: {', '.join(BACKENDS)}"
            "\n  임의 제공자는 CARBONLEDGER_BACKEND=custom + CARBONLEDGER_BASE_URL")
    pages = render_pages(path)
    model = resolve_model(model)
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
    elif b == "custom":
        # 임의 OpenAI 호환 제공자. 키는 선택 — 사내 vLLM처럼 인증 없는 경우가 있다.
        key = os.environ.get("CARBONLEDGER_API_KEY") or None
        text = _call_openai_compat(_custom_url(), key, spec["prompt"], pages, model)
    elif b == "ollama":  # 로컬, 키 불필요
        text = _call_openai_compat(OLLAMA_URL, None, spec["prompt"], pages, model)
    else:  # lmstudio (로컬, 키 불필요)
        text = _call_openai_compat(LM_STUDIO_URL, None, spec["prompt"], pages, model)
    return _parse_json(text)


def _retry_after(resp) -> float | None:
    """429·503의 retry-after 헤더(초). 제공자가 준 대기시간이 우리 추측보다 정확하다."""
    v = (getattr(resp, "headers", None) or {}).get("retry-after")
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return None  # HTTP-date 형식이면 지수 백오프로 폴백


def _post_with_retry(url: str, **kw):
    """requests.post + 제한적 재시도. 두 백엔드 호출 경로가 공유한다.

    수백 장 배치에서 429(쿼터)·5xx(일시 장애)는 정상적으로 발생한다 — 한 번 맞고
    포기하면 멀쩡한 증빙이 검토 대기로 쌓인다. 반대로 400·401·403·413은 재시도해도
    결과가 같으므로 즉시 실패시킨다(무의미한 대기·과금 방지).

    실패 시 예외 메시지에 **응답 본문을 포함**한다 — raise_for_status의
    'HTTP 400 Client Error'만으로는 사용자가 원인을 알 수 없다.
    """
    import requests
    last = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = requests.post(url, **kw)
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            if attempt == _MAX_ATTEMPTS - 1:
                raise RuntimeError(
                    f"네트워크 오류로 {_MAX_ATTEMPTS}회 실패: {type(e).__name__}: {e}") from e
            _sleep(_BACKOFF_BASE * (2 ** attempt))
            continue

        code = getattr(r, "status_code", 200)
        if code < 400:
            return r
        body = ""
        try:
            body = json.dumps(r.json(), ensure_ascii=False)[:300]
        except Exception:
            body = (getattr(r, "text", "") or "")[:300]

        if code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS - 1:
            wait = _retry_after(r)
            _sleep(wait if wait is not None else _BACKOFF_BASE * (2 ** attempt))
            last = code
            continue

        hint = {
            401: " — API 키 확인(환경변수)",
            403: " — 키 권한·조직 설정 확인",
            413: " — 요청이 너무 큼: PDF 쪽수를 줄이거나 이미지를 축소",
            429: f" — 쿼터 소진({_MAX_ATTEMPTS}회 재시도 후 포기). 잠시 후 재실행",
        }.get(code, "")
        raise RuntimeError(f"API 오류 HTTP {code}{hint}: {body}")
    raise RuntimeError(f"재시도 소진: {last}")


def _call_openai_compat(url: str, key: str | None, prompt: str,
                        pages: list[bytes], model: str) -> str:
    """OpenAI 호환 chat/completions(비전, 다중 이미지). LM Studio·OpenAI 공용."""
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": _data_url(p)}} for p in pages]
    payload = {"model": model, "temperature": 0,
               "messages": [{"role": "user", "content": content}]}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = _post_with_retry(url, json=payload, headers=headers, timeout=120)
    return r.json()["choices"][0]["message"]["content"]


def _call_anthropic(key: str, prompt: str, pages: list[bytes], model: str) -> str:
    """Anthropic Messages API(비전, 다중 이미지).

    OpenAI 호환 경로와 달리 요청 형태·인증·응답 파싱이 전부 다르므로 별도 함수다.
    아래 세 가지는 현행 모델(Sonnet 5·Opus 4.7 이후)의 제약이라 어겨선 안 된다.
    """
    _check_anthropic_size(pages)
    content = [{"type": "image", "source": {"type": "base64",
                "media_type": _media_type(p), "data": base64.b64encode(p).decode()}}
               for p in pages]
    content.append({"type": "text", "text": prompt})
    # temperature를 보내지 않는다 — Sonnet 5·Opus 4.7 이후 모델은 temperature·top_p·top_k를
    # 기본값 아닌 값으로 주면 400이다(기본 1.0이므로 0도 위반). 결정성은 프롬프트로 확보한다.
    # max_tokens는 thinking + 본문의 '합산' 상한이고 이 모델들은 thinking이 기본 ON이라,
    # 1024로는 추론 토큰이 먹고 남은 자리에 JSON이 잘려 들어갈 수 있다.
    payload = {"model": model, "max_tokens": 4096,
               "messages": [{"role": "user", "content": content}]}
    r = _post_with_retry(ANTHROPIC_URL, json=payload, timeout=120, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    return _anthropic_text(r.json().get("content", []))


def _check_anthropic_size(pages: list[bytes]):
    """전송 전 크기 관문 — 413을 맞고 나서가 아니라 보내기 전에 알려 준다.

    고해상도 스캔·다중페이지 PDF는 상한을 쉽게 넘는다. 그냥 보내면 제공자가
    413으로 끊고(과금 없이도 시간은 버려진다) 원인이 응답 본문에만 남는다.
    """
    for i, p in enumerate(pages, 1):
        b64 = len(p) * _B64_OVERHEAD
        if b64 > _ANTHROPIC_MAX_IMAGE_B64:
            raise RuntimeError(
                f"이미지 {i}쪽이 Anthropic 상한 초과: 약 {b64/1024/1024:.1f}MB "
                f"(base64 기준 10MB 한도) — 스캔 해상도를 낮추거나 이미지를 축소할 것")
    total = sum(len(p) for p in pages) * _B64_OVERHEAD
    if total > _ANTHROPIC_MAX_REQUEST:
        raise RuntimeError(
            f"요청 전체가 상한 초과: 약 {total/1024/1024:.1f}MB (32MB 한도, {len(pages)}쪽) "
            "— PDF를 쪽별로 나누거나 해상도를 낮출 것")


def _anthropic_text(blocks: list) -> str:
    """content 배열에서 text 블록을 꺼낸다.

    thinking이 켜진 모델은 content[0]이 thinking 블록이라 [0]["text"]가 KeyError가 난다.
    위치가 아니라 type으로 찾는다.
    """
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            return b["text"]
    kinds = [b.get("type") for b in blocks if isinstance(b, dict)]
    raise RuntimeError(f"Anthropic 응답에 text 블록 없음 (블록 종류: {kinds})")


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
    assert resolve_model("custom-x") == "custom-x", "지정 모델 무시됨"
    assert set(DEFAULT_MODELS) == {"lmstudio", "ollama", "openai", "anthropic", "custom"}, \
        "기본모델표 불일치"

    # 백엔드 해석: 환경변수를 건드리므로 원복을 보장한다
    _env_backup = {k: os.environ.get(k) for k in
                   ("CARBONLEDGER_BACKEND", "CARBONLEDGER_BASE_URL", "CARBONLEDGER_MODEL")}
    try:
        for k in _env_backup:
            os.environ.pop(k, None)
        assert backend() == "lmstudio", "기본 백엔드는 lmstudio"
        assert resolve_model(None) == DEFAULT_MODELS["lmstudio"], "기본 모델 해석 실패"

        # custom: 기본 모델이 없으므로 미지정은 실행 전에 막아야
        os.environ["CARBONLEDGER_BACKEND"] = "custom"
        try:
            resolve_model(None)
            assert False, "custom인데 모델 미지정을 통과시킴"
        except RuntimeError as e:
            assert "모델 미지정" in str(e)
        os.environ["CARBONLEDGER_MODEL"] = "gemini-2.5-flash"
        assert resolve_model(None) == "gemini-2.5-flash", "CARBONLEDGER_MODEL 미반영"
        assert resolve_model("override") == "override", "--model이 환경변수를 못 이김"

        # custom: BASE_URL 미설정은 안내와 함께 실패, 설정 시 경로 보정
        os.environ.pop("CARBONLEDGER_BASE_URL", None)
        try:
            _custom_url()
            assert False, "BASE_URL 없이 통과함"
        except RuntimeError as e:
            assert "CARBONLEDGER_BASE_URL" in str(e)
        os.environ["CARBONLEDGER_BASE_URL"] = "https://x.example/v1"
        assert _custom_url() == "https://x.example/v1/chat/completions", "경로 보정 실패"
        os.environ["CARBONLEDGER_BASE_URL"] = "https://x.example/v1/chat/completions"
        assert _custom_url() == "https://x.example/v1/chat/completions", "완전경로를 중복 부착"
        os.environ["CARBONLEDGER_BASE_URL"] = "https://x.example/v1/"
        assert _custom_url() == "https://x.example/v1/chat/completions", "말미 슬래시 처리 실패"
    finally:
        for k, v in _env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("extract selftest 통과 ✅")


if __name__ == "__main__":
    selftest()
