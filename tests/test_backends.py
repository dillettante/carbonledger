"""백엔드 계약 테스트 — 우리가 만드는 HTTP 요청과 우리가 읽는 응답이 규격에 맞는가.

## 왜 골든 테스트로는 부족한가

골든 테스트(test_golden.py)는 LLM 호출 **자체를 목킹으로 갈아끼우고** 그 뒤 파이프라인을
검증한다. 즉 `_call_openai_compat`·`_call_anthropic` 두 함수는 한 줄도 실행되지 않는다.
백엔드 4종 중 로컬 2종만 실호출로 검증됐고 상용 2종은 미검증인 채였는데, 그 상태에서
Anthropic 경로에 `temperature: 0`이 들어 있었다 — 현행 모델은 이걸 400으로 거절한다.
README를 따라 `CARBONLEDGER_BACKEND=anthropic`을 쓴 사용자는 첫 호출에서 죽었을 것이다.

## 여기서 검증하는 것 / 못 하는 것

requests.post를 가로채 **요청 본문을 붙잡고**, 제공자 공식 문서에 실린 **응답 형태를 돌려준다.**
- ✅ 우리 요청이 규격을 어기지 않는가 (금지 파라미터·필수 헤더)
- ✅ 우리 파서가 실제 응답 형태를 읽어내는가 (thinking 블록이 앞에 오는 경우 포함)
- ❌ 제공자가 실제로 200을 주는가 — 이건 실호출로만 확인된다

마지막 한 줄이 이 파일의 한계이자, 실호출 스모크가 남아 있는 이유다.

실행: python3 -m pytest tests/  또는  python3 tests/test_backends.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carbonledger import extract  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"fake" * 40


class _Resp:
    """requests.Response 대역 — 우리 코드가 실제로 쓰는 것만 흉내낸다."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _capture(monkeypatch, response_payload):
    """requests.post를 가로채 요청을 기록하고 고정 응답을 돌려준다."""
    import requests
    seen = {}

    def fake_post(url, **kw):
        seen["url"] = url
        seen["json"] = kw.get("json")
        seen["headers"] = kw.get("headers") or {}
        return _Resp(response_payload)

    monkeypatch.setattr(requests, "post", fake_post)
    return seen


# ─────────────────────────────────────────────────────────────
# OpenAI 호환 경로 (lmstudio · ollama · openai 공용)
# ─────────────────────────────────────────────────────────────

def test_openai_compat_request_and_parse(tmp_path, monkeypatch):
    """요청 형태 + choices[0].message.content 파싱.

    응답 형태는 OpenAI Chat Completions 레퍼런스의 문서 예시 구조.
    """
    seen = _capture(monkeypatch, {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"kwh": 500}'},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    })

    out = extract._call_openai_compat("https://api.openai.com/v1/chat/completions",
                                      "test-key", "프롬프트", [PNG], "gpt-4o")
    assert out == '{"kwh": 500}', "choices[0].message.content 파싱 실패"

    body = seen["json"]
    assert body["model"] == "gpt-4o"
    assert seen["headers"]["Authorization"] == "Bearer test-key", "Bearer 인증 누락"

    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "프롬프트"}
    img = parts[1]
    assert img["type"] == "image_url", "이미지 파트 타입이 규격과 다름"
    # 문서 명시: url 필드는 이미지 URL 또는 base64 인코딩 데이터 둘 다 허용
    assert img["image_url"]["url"].startswith("data:image/png;base64,"), "data URL 형식 아님"


def test_openai_compat_local_needs_no_auth(tmp_path, monkeypatch):
    """로컬 백엔드(LM Studio·Ollama)엔 Authorization 헤더를 붙이지 않는다."""
    seen = _capture(monkeypatch, {"choices": [{"message": {"content": "{}"}}]})
    extract._call_openai_compat(extract.LM_STUDIO_URL, None, "p", [PNG], "qwen/qwen3-vl-4b")
    assert "Authorization" not in seen["headers"], "로컬 호출에 불필요한 인증 헤더"


def test_openai_compat_multipage(tmp_path, monkeypatch):
    """다중 페이지 PDF → 이미지 파트가 페이지 수만큼 붙는다."""
    seen = _capture(monkeypatch, {"choices": [{"message": {"content": "{}"}}]})
    extract._call_openai_compat(extract.OLLAMA_URL, None, "p", [PNG, PNG, PNG], "m")
    parts = seen["json"]["messages"][0]["content"]
    assert sum(1 for p in parts if p["type"] == "image_url") == 3, "페이지 누락"


# ─────────────────────────────────────────────────────────────
# Anthropic 경로 — 요청 형태·인증·파싱이 전부 다른 별도 코드
# ─────────────────────────────────────────────────────────────

def test_anthropic_rejects_sampling_params(tmp_path, monkeypatch):
    """[회귀 방지] temperature·top_p·top_k를 보내면 안 된다.

    Sonnet 5·Opus 4.7 이후 모델은 이 셋을 기본값 아닌 값으로 주면 400을 반환한다
    (temperature 기본값이 1.0이므로 0도 위반). 실제로 이 버그가 있었다.
    """
    seen = _capture(monkeypatch, {"content": [{"type": "text", "text": "{}"}]})
    extract._call_anthropic("k", "p", [PNG], "claude-sonnet-5")

    body = seen["json"]
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in body, \
            f"payload에 {banned} 포함 — 현행 모델이 400으로 거절한다"


def test_anthropic_request_shape(tmp_path, monkeypatch):
    """요청 형태·헤더가 Messages API 규격과 맞는가."""
    seen = _capture(monkeypatch, {"content": [{"type": "text", "text": "{}"}]})
    extract._call_anthropic("test-key", "프롬프트", [PNG], "claude-sonnet-5")

    h = seen["headers"]
    assert h["x-api-key"] == "test-key", "x-api-key 인증(Bearer 아님)"
    assert h["anthropic-version"] == "2023-06-01", "버전 헤더 누락"

    body = seen["json"]
    # max_tokens는 thinking + 본문 합산 상한이라 JSON이 잘리지 않을 만큼 필요하다
    assert body["max_tokens"] >= 4096, "max_tokens가 작아 JSON 절단 위험"

    content = body["messages"][0]["content"]
    img = content[0]
    assert img["type"] == "image" and img["source"]["type"] == "base64", "이미지 블록 형태 오류"
    assert img["source"]["media_type"] == "image/png", "media_type 오판정"
    assert content[-1] == {"type": "text", "text": "프롬프트"}
    # 마지막이 assistant 역할이면(프리필) 현행 모델은 400 — user 하나만 보낸다
    assert [m["role"] for m in body["messages"]] == ["user"]


def test_anthropic_parses_text_after_thinking_block(tmp_path, monkeypatch):
    """[회귀 방지] thinking이 켜진 모델은 content[0]이 text가 아니다.

    Sonnet 5·Opus 5는 thinking 필드를 생략해도 adaptive thinking이 기본 ON이라
    content 배열 앞에 thinking 블록이 온다. 위치로 꺼내면 KeyError가 난다.
    """
    seen = _capture(monkeypatch, {"content": [
        {"type": "thinking", "thinking": "", "signature": "abc"},
        {"type": "text", "text": '{"kwh": 500}'},
    ]})
    out = extract._call_anthropic("k", "p", [PNG], "claude-sonnet-5")
    assert out == '{"kwh": 500}', "thinking 블록 뒤의 text를 못 읽음"
    assert seen["url"] == extract.ANTHROPIC_URL


def test_anthropic_text_block_missing_is_loud(tmp_path):
    """text 블록이 없으면 조용히 넘어가지 말고 실패해야 한다."""
    try:
        extract._anthropic_text([{"type": "thinking", "thinking": ""}])
    except RuntimeError as e:
        assert "text 블록 없음" in str(e)
    else:
        assert False, "text 블록 없는 응답을 통과시킴"


def test_anthropic_parse_plain_response(tmp_path):
    """thinking 없는 응답(구 모델·Haiku)도 그대로 읽힌다."""
    assert extract._anthropic_text([{"type": "text", "text": "hello"}]) == "hello"


# ─────────────────────────────────────────────────────────────
# 백엔드 선택 → 실제로 어느 URL로 나가는가
# ─────────────────────────────────────────────────────────────

def test_backend_routing(tmp_path, monkeypatch):
    """CARBONLEDGER_BACKEND 값이 실제 호출 URL·인증으로 이어지는가."""
    import os
    png = tmp_path / "x.png"
    png.write_bytes(PNG)

    cases = [
        ("lmstudio", {}, extract.LM_STUDIO_URL),
        ("ollama", {}, extract.OLLAMA_URL),
        ("openai", {"OPENAI_API_KEY": "k"}, extract.OPENAI_URL),
        ("anthropic", {"ANTHROPIC_API_KEY": "k"}, extract.ANTHROPIC_URL),
    ]
    for name, env, expect_url in cases:
        monkeypatch.setattr(os, "environ", {**os.environ, "CARBONLEDGER_BACKEND": name, **env})
        payload = ({"content": [{"type": "text", "text": '{"kwh": 1}'}]} if name == "anthropic"
                   else {"choices": [{"message": {"content": '{"kwh": 1}'}}]})
        seen = _capture(monkeypatch, payload)
        assert extract.extract(str(png), "electricity") == {"kwh": 1}, f"{name} 추출 실패"
        assert seen["url"] == expect_url, f"{name} → 잘못된 URL {seen['url']}"


def test_commercial_backend_requires_key(tmp_path, monkeypatch):
    """키 없이 상용 백엔드를 고르면 건별 401이 흩어지기 전에 한 번에 실패."""
    import os
    png = tmp_path / "x.png"
    png.write_bytes(PNG)
    for name, key in (("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")):
        env = {k: v for k, v in os.environ.items() if k != key}
        monkeypatch.setattr(os, "environ", {**env, "CARBONLEDGER_BACKEND": name})
        try:
            extract.extract(str(png), "electricity")
        except RuntimeError as e:
            assert key in str(e), f"{name}: 오류 메시지에 키 이름 없음"
        else:
            assert False, f"{name}: 키 없이 통과함"


if __name__ == "__main__":
    import tempfile

    class _P:  # monkeypatch 대역(순수 실행용) — 원복까지 흉내낸다
        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)

        def undo(self):
            for obj, name, old in reversed(self._undo):
                setattr(obj, name, old)
            self._undo = []

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        mp = _P()
        with tempfile.TemporaryDirectory() as d:
            try:
                n = fn.__code__.co_argcount
                fn(Path(d), mp) if n == 2 else fn(Path(d))
            finally:
                mp.undo()
    print(f"백엔드 계약 테스트 {len(tests)}종 통과 ✅")
