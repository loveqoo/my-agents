"""스펙 358 검증 — mem0 백엔드 캐시 동시 콜드스타트 중복 생성 봉합(풀 누수).

`resolve_backend`는 동기 함수이고 챗·배치가 to_thread 워커에서 동시 호출한다. 락 없으면 같은 새
mem_cfg로 두 스레드가 동시에 _construct → 풀 하나 고아 누수. double-checked locking으로 미스 경로를
직렬화해 construct를 정확히 1회로 만든다.

단언(순수 단위 — DB·실백엔드 불필요, _construct를 카운팅 stub으로 대체):
  B1. 같은 새 mem_cfg로 N개 스레드 동시 진입 → _construct 정확히 1회 + 전원 같은 인스턴스.
  B2. None 캐시 무회귀: _construct가 예외면 None 캐시 → 이후 호출은 재construct 안 함(1회만 시도).
  B3. 캐시 히트 무회귀: 두 번째 호출은 construct 없이 같은 인스턴스.

실행: .venv/bin/python tests/verify_358_backend_cache_lock.py
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api.memory import backend as be  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# llm/embedder 있어야 가드 통과. 축 변형으로 캐시 키를 시나리오마다 새로.
def _cfg(tag: str) -> dict:
    return {
        "llm": {"provider": "x", "config": {"model": f"m-{tag}"}},
        "embedder": {"provider": "x", "config": {"model": f"e-{tag}"}},
    }


class _Sentinel:  # MemoryBackend 대역(인스턴스 동일성만 본다)
    pass


def main() -> None:
    _orig_construct = be._construct

    # ── B1: 동시 진입 → construct 정확히 1회 ──────────────────────────────────
    be._reset_cache()
    calls = {"n": 0}
    call_lock = threading.Lock()

    def _slow_construct(kind, mem_cfg):
        with call_lock:
            calls["n"] += 1
        time.sleep(0.05)  # 경합 창 확대 — 락 없으면 여러 스레드가 이 안에서 겹친다
        return _Sentinel()

    be._construct = _slow_construct
    cfg = _cfg("b1")
    N = 12
    results: list = [None] * N
    barrier = threading.Barrier(N)

    def _worker(i):
        barrier.wait()  # 전원 동시 출발(최대 경합)
        results[i] = be.resolve_backend(cfg)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check(calls["n"] == 1, f"[B1] _construct 정확히 1회(실제 {calls['n']}) — 중복 생성 0")
    check(all(r is results[0] and r is not None for r in results), "[B1] 전 스레드 같은 인스턴스")

    # ── B2: _construct 예외 → None 캐시, 재시도 억제 ──────────────────────────
    be._reset_cache()
    fail_calls = {"n": 0}

    def _raising_construct(kind, mem_cfg):
        fail_calls["n"] += 1
        raise RuntimeError("boom")

    be._construct = _raising_construct
    cfg2 = _cfg("b2")
    r_a = be.resolve_backend(cfg2)
    r_b = be.resolve_backend(cfg2)
    check(r_a is None and r_b is None, "[B2] 실패 → None 반환(graceful)")
    check(fail_calls["n"] == 1, f"[B2] construct 1회만 시도(실제 {fail_calls['n']}) — None 캐시 재시도 억제")

    # ── B3: 캐시 히트 무회귀 ──────────────────────────────────────────────────
    be._reset_cache()
    hit_calls = {"n": 0}

    def _once_construct(kind, mem_cfg):
        hit_calls["n"] += 1
        return _Sentinel()

    be._construct = _once_construct
    cfg3 = _cfg("b3")
    first = be.resolve_backend(cfg3)
    second = be.resolve_backend(cfg3)
    check(hit_calls["n"] == 1, f"[B3] 두 번째는 construct 없이 히트(실제 {hit_calls['n']}회)")
    check(first is second and first is not None, "[B3] 같은 인스턴스 반환")

    be._construct = _orig_construct
    be._reset_cache()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_358)")


if __name__ == "__main__":
    main()
