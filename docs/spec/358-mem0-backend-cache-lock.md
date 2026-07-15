# 358 — mem0 백엔드 캐시 동시 콜드스타트 중복 생성 봉합 (풀 누수)

## 왜 (전수조사 확증 — deep-reasoner)

`memory/backend.py`의 `resolve_backend`는 캐시 미스 시 **락 없이** `_construct` 후 `_cache[key]=`
한다(127-134). 이 함수는 **동기**이고 챗·배치가 `asyncio.to_thread`로 각자 워커 스레드에서 부른다.
같은 새 `mem_cfg`로 여러 스레드가 동시 진입하면 둘 다 캐시 미스 → 각자 `Mem0Backend`를 생성한다
(각 pgvector `ConnectionPool` min1/max5 + sqlite 오픈). last-write-wins로 한쪽 풀이 **고아**가 되어
명시적 close 없이 GC 의존으로 남는다 — psycopg 풀은 백그라운드 워커를 물어 GC 정리가 깔끔하지 않다.

빈도는 낮다(설정별 첫 사용 1회, 그 뒤론 캐시 히트). 그러나 데이터 초기화·재시작 직후 챗+배치가
겹치는 콜드스타트에서 실재한다.

## 설계 — double-checked locking

`threading.Lock`(동기 함수이므로 asyncio 아님)으로 미스 경로를 직렬화한다:

```
hit = _cache.get(key)
if hit is not None or key in _cache: return _cache[key]   # graceful None도 캐시됨(재시도 억제 유지)
with _cache_lock:
    if key in _cache: return _cache[key]                  # 재확인(다른 스레드가 채웠으면 재사용)
    ... _construct ... _cache[key] = backend; return backend
```

- **주의**: 기존 계약상 실패도 `None`으로 캐시된다(재시도 억제). 그래서 `key in _cache`로 판정해야
  `None` 캐시 히트와 미스를 구분한다(`get() is not None`만 보면 None 캐시를 매번 재구성).
- 락은 미스 경로에만 진입 — 히트는 락 없이 반환(첫 재확인 전 fast-path). construct가 풀을 여는 동안
  락을 쥐지만, 설정별 1회뿐이라 비용 무시 가능.

## 완료 조건 (수치)

- **B1** 같은 새 `mem_cfg`로 N개 스레드 동시 진입 → `_construct` 호출 **정확히 1회**(중복 0).
- **B2** None 캐시 무회귀: 실패 설정은 여전히 1회만 construct 시도하고 이후 None 히트(재시도 억제).
- **B3** 정상 경로 무회귀: 캐시 히트는 락 없이 같은 인스턴스 반환.
- **B4** 전체 기능점검: `make test` 씨앗 그물 초록.

## OUT

- 고아 풀의 명시적 close(생성했다가 버리는 인스턴스) — 애초에 하나만 만들면 불필요.
- `_construct` 자체의 리트라이/백오프 — 별개.
