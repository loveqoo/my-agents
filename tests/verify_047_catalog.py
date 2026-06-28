"""스펙 047 단위 검증 — models.dev 카탈로그 매칭(#7) + GET /models 수집기 보안 표면.

카탈로그 lookup의 매칭 우선순위(full→bare→None)와 _to_meta 정규화 형태,
그리고 _list_remote_models의 적대 가드(스킴·raw 바이트 상한·타입 검증)를 네트워크 없이
httpx 목으로 결정적 검증한다(learning 028·041 — 캡은 원천 바이트에서, 트러스트 경계는 관리자 입력).

검증:
  C1. lookup(full id 완전일치) → 그 메타(catalog_id 일치).
  C2. lookup(bare id, 마지막 세그먼트) → 매칭(없으면 정상적으로 None인 사설 id와 구분).
  C3. lookup(미수록 id) → None.  C4. lookup(None/빈) → None.
  C5. _to_meta — 정규화 키 셋·capabilities bool 강제·modalities 리스트 기본값.
  S1. _list_remote_models 빈 base_url → (False, _, []).
  S2. 비-http(s) 스킴(ftp://) → (False, "http(s) 스킴만 허용", []) — 네트워크 안 함.
  S3. HTTP 200 + 정상 data[*].id → (True, "연결됨", ids) — dict/누락 id 필터.
  S4. raw 바이트가 상한 초과로 흘러오면 → (True, "...상한 초과...", []) — 버퍼 폭주 차단.
  S5. 비-200 → (True, "HTTP {code}", []) — 본문(키 에코 가능) 미파싱.
  S6. slow-trickle(per-read 짧지만 전체 길게) → 벽시계 deadline이 차단(hold-open 방지, 적대 리뷰 047).

실행: uv run python tests/verify_047_catalog.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import catalog  # noqa: E402
from api import providers  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ── httpx.AsyncClient.stream 대역 ────────────────────────────────────────────
class _FakeStream:
    def __init__(self, status_code: int, chunks: list[bytes]):
        self.status_code = status_code
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


class _FakeClient:
    def __init__(self, status_code: int, chunks: list[bytes]):
        self._status = status_code
        self._chunks = chunks

    def __init_subclass__(cls):  # pragma: no cover
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        return _FakeStream(self._status, self._chunks)


def _patch_httpx(status_code: int, chunks: list[bytes]):
    orig = providers.httpx.AsyncClient
    providers.httpx.AsyncClient = lambda *a, **k: _FakeClient(status_code, chunks)
    return lambda: setattr(providers.httpx, "AsyncClient", orig)


# ── slow-trickle 대역: 청크 사이에 sleep을 끼워 per-read는 짧지만 전체는 길게 만든다 ──
class _SlowStream(_FakeStream):
    def __init__(self, status_code: int, chunks: list[bytes], gap: float):
        super().__init__(status_code, chunks)
        self._gap = gap

    async def aiter_bytes(self):
        for c in self._chunks:
            await asyncio.sleep(self._gap)  # 매 read는 빠르지만 누적은 deadline 초과
            yield c


class _SlowClient(_FakeClient):
    def __init__(self, status_code: int, chunks: list[bytes], gap: float):
        super().__init__(status_code, chunks)
        self._gap = gap

    def stream(self, method, url, headers=None):
        return _SlowStream(self._status, self._chunks, self._gap)


def _patch_httpx_slow(gap: float, n_chunks: int):
    orig = providers.httpx.AsyncClient
    chunks = [b"x"] * n_chunks
    providers.httpx.AsyncClient = lambda *a, **k: _SlowClient(200, chunks, gap)
    return lambda: setattr(providers.httpx, "AsyncClient", orig)


async def main() -> None:
    # ── 카탈로그 매칭 ────────────────────────────────────────────────────────
    # full id를 카탈로그에서 하나 골라 검증(스냅샷 의존이지만 by_full 키가 곧 full id).
    by_full, by_bare = catalog._index()
    check(len(by_full) > 1000, f"index 로드됨 (full_ids={len(by_full)})")
    sample_full = next(iter(by_full))  # e.g. "openai/gpt-4o"
    meta = catalog.lookup(sample_full)
    check(meta is not None and meta.get("catalog_id") == by_full[sample_full]["catalog_id"],
          f"C1 full id 완전일치 → 메타 ({sample_full})")

    bare = sample_full.split("/")[-1]
    meta_bare = catalog.lookup(bare)
    check(meta_bare is not None, f"C2 bare id(마지막 세그먼트) → 매칭 ({bare})")

    check(catalog.lookup("nonexistent/private-model-zzz-999") is None,
          "C3 미수록 id → None (MLX 사설 모델 정상 미매칭)")
    check(catalog.lookup(None) is None and catalog.lookup("") is None,
          "C4 None/빈 입력 → None (크래시 없음)")

    # _to_meta 정규화 — 일부 키 누락 엔트리도 안전한 기본값.
    norm = catalog._to_meta({"id": "x/y", "name": "Y", "reasoning": True})
    keys_ok = {"catalog_id", "name", "context", "output_limit", "modalities",
               "cost", "capabilities", "release_date"} <= set(norm)
    check(keys_ok, "C5 _to_meta 정규화 키 셋 완비")
    check(norm["capabilities"]["reasoning"] is True and norm["capabilities"]["tool_call"] is False,
          "C5 capabilities bool 강제(reasoning True / tool_call 기본 False)")
    check(norm["modalities"]["input"] == [] and norm["modalities"]["output"] == [],
          "C5 modalities 누락 시 빈 리스트 기본값")

    # ── _list_remote_models 보안 가드 ───────────────────────────────────────
    reachable, detail, ids = await providers._list_remote_models("", None)
    check(reachable is False and ids == [], "S1 빈 base_url → (False, _, [])")

    reachable, detail, ids = await providers._list_remote_models("ftp://x/v1", None)
    check(reachable is False and "스킴" in detail and ids == [],
          "S2 비-http(s) 스킴 → 거부 (네트워크 안 함)")

    body = b'{"data":[{"id":"a"},{"id":"b"},{"noid":1},"notdict",{"id":""}]}'
    restore = _patch_httpx(200, [body])
    try:
        reachable, detail, ids = await providers._list_remote_models("http://h/v1", None)
        check(reachable is True and ids == ["a", "b"] and detail == "연결됨",
              f"S3 200 정상 → id만 필터(dict+truthy id): {ids}")
    finally:
        restore()

    # S4 — raw 바이트 상한 초과(원천 누적). 큰 청크 2개로 _MAX_MODELS_BYTES 돌파.
    big = b"x" * (providers._MAX_MODELS_BYTES // 2 + 10)
    restore = _patch_httpx(200, [big, big])
    try:
        reachable, detail, ids = await providers._list_remote_models("http://h/v1", None)
        check(reachable is True and ids == [] and "상한" in detail,
              "S4 raw 바이트 상한 초과 → 차단 (버퍼 폭주 방지, learning 041)")
    finally:
        restore()

    restore = _patch_httpx(503, [b"secret-key-leak?"])
    try:
        reachable, detail, ids = await providers._list_remote_models("http://h/v1", None)
        check(reachable is True and ids == [] and detail == "HTTP 503",
              "S5 비-200 → 본문 미파싱(키 에코 차단), 상태코드만")
    finally:
        restore()

    # S6 — slow-trickle: per-read는 짧지만 스트림 전체가 deadline 초과 → asyncio.timeout이
    # 끊고 (False, "연결 실패", []). httpx per-read 타임아웃만으론 못 막던 hold-open(적대 리뷰 047).
    orig_deadline = providers._STREAM_DEADLINE
    providers._STREAM_DEADLINE = 0.3
    restore = _patch_httpx_slow(gap=0.2, n_chunks=10)  # 0.2*10=2.0s ≫ 0.3s deadline
    try:
        reachable, detail, ids = await providers._list_remote_models("http://h/v1", None)
        check(reachable is False and ids == [] and detail == "연결 실패",
              "S6 slow-trickle 응답 → 벽시계 deadline이 차단(hold-open 방지, 적대 리뷰 047)")
    finally:
        restore()
        providers._STREAM_DEADLINE = orig_deadline

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
