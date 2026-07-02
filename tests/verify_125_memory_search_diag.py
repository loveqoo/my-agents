"""verify_125 — 메모리 검색 진단 recall_diag (스펙 125).

recall_probe가 모든 미가용을 None으로 뭉개고 검색 예외를 던지던 걸, recall_diag가 4모드로 구분하고
예외를 삼켜 구조화한다(왜 0건/실패인지). 비밀(api_key)은 절대 error에 안 샌다.

검증(순수 + monkeypatch resolve_backend):
  - A mem_cfg=None → configured=False·error 미설정 안내·backend_ready=False.
  - B llm/embedder 누락 → configured=False.
  - C configured인데 resolve_backend None(초기화 실패) → backend_ready=False·error 초기화 실패.
  - D configured·backend_ready인데 search 예외(비밀 포함) → error 설정 + **비밀 마스킹**·results 빈.
  - E 정상 → results 반환·error None·embedder_model 노출(비밀 아님).
실행: uv run python tests/verify_125_memory_search_diag.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from api import memory  # noqa: E402

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


CFG = {"llm": {"model_id": "gpt-x", "api_key": "sk-SECRET123456", "base_url": "http://h/v1"},
       "embedder": {"model_id": "embed-3", "api_key": "sk-SECRET123456", "base_url": "http://h/v1"}}

SECRET = "sk-SECRET123456"


class _FakeBackend:
    def __init__(self, hits=None, raise_with=None):
        self._hits = hits or []
        self._raise = raise_with

    def search(self, scope, query, limit):
        if self._raise:
            raise RuntimeError(self._raise)
        return self._hits


def main() -> None:
    orig = memory.resolve_backend
    try:
        # A: mem_cfg None
        d = memory.recall_diag({"user_id": "u"}, "q", None, 4)
        check(d["configured"] is False and d["backend_ready"] is False and d["error"],
              f"A mem_cfg=None → 미구성+error(got {d['error']!r})")
        check("설정" in d["error"], "A error가 '미설정' 안내")

        # B: embedder 누락
        d = memory.recall_diag({"user_id": "u"}, "q", {"llm": {"model_id": "x"}}, 4)
        check(d["configured"] is False, "B embedder 누락 → configured=False")

        # C: configured인데 resolve_backend None(초기화 실패 흡수)
        memory.resolve_backend = lambda cfg: None
        d = memory.recall_diag({"user_id": "u"}, "q", CFG, 4)
        check(d["configured"] is True and d["backend_ready"] is False and d["error"],
              f"C configured+backend None → 초기화 실패 error(got {d['error']!r})")
        check(d["embedder_model"] == "embed-3", "C embedder_model 노출(비밀 아님)")

        # D: search 예외(비밀 포함 메시지) → error 마스킹, results 빈
        memory.resolve_backend = lambda cfg: _FakeBackend(raise_with=f"conn refused token={SECRET}")
        d = memory.recall_diag({"user_id": "u"}, "q", CFG, 4)
        check(d["backend_ready"] is True and d["error"] and d["results"] == [],
              f"D 검색 예외 → backend_ready·error·빈결과(got {d})")
        check(SECRET not in d["error"], f"D **비밀 마스킹**: error에 api_key 없음(got {d['error']!r})")
        check("검색 실행 실패" in d["error"], "D error가 '검색 실행 실패' 라벨")

        # E: 정상
        memory.resolve_backend = lambda cfg: _FakeBackend(
            hits=[{"type": "semantic", "text": "커피 좋아함", "score": 0.9, "scope": "user_id"}])
        d = memory.recall_diag({"user_id": "u"}, "q", CFG, 4)
        check(d["error"] is None and len(d["results"]) == 1 and d["backend_ready"] is True,
              f"E 정상 → results+error None(got {d})")

        # 마스킹 헬퍼 직접(다양한 비밀 형태)
        for s in [f"api_key={SECRET}", "Authorization: Bearer abc123def456", f"key {SECRET}"]:
            masked = memory._sanitize(s)
            check(SECRET not in masked and "abc123def456" not in masked, f"_sanitize 마스킹: {s[:20]!r}")

        # codex 125 H1 — 라벨 뒤 공백형/다른 라벨/hex 값(정규식 백스톱)
        HEX = "0123456789abcdef0123456789abcdef01234567"
        for s in [f"401 upstream, api_key: {HEX}", f"x-api-key: {HEX}", f"OPENAI_API_KEY = {HEX}",
                  f"token: {HEX}", f'{{"authorization": "{HEX}"}}']:
            masked = memory._sanitize(s)
            check(HEX not in masked, f"H1 백스톱 마스킹: {s[:24]!r} (got {masked[:40]!r})")

        # codex 125 H1 — mem_cfg 실제 api_key 정확 치환(형태 무관 1차 방어): 라벨 없이 노출돼도 제거
        raw_key = "anthropic-xyz_LONGKEY_9988776655"
        cfg2 = {"llm": {"model_id": "m", "api_key": raw_key}, "embedder": {"model_id": "e", "api_key": raw_key}}
        memory.resolve_backend = lambda cfg: _FakeBackend(raise_with=f"upstream said: {raw_key} bad")
        d = memory.recall_diag({"user_id": "u"}, "q", cfg2, 4)
        check(raw_key not in (d["error"] or ""), f"H1 정확치환: 실제 api_key 제거(got {d['error']!r})")
    finally:
        memory.resolve_backend = orig

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
