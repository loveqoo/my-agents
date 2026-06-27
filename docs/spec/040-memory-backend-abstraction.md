# 040 — 메모리 백엔드 추상화 (P4, 로드맵 #7)

> 지배 스펙: docs/spec/033-feature-roadmap.md(#7), 020(다층 스코프), 019(pgvector 공유), 029/030/039(메모리 사용처).
> 관련 learning: 021(mem0 가치=스코프·추출), 020(pgvector·DSN 위임), 038(적대 리뷰), 033(신규 테이블 없음).

## 1. 무엇을 / 왜

`packages/api/src/api/memory.py`의 mem0 라이브러리 호출을 **백엔드 추상화(Protocol/ABC) 뒤로**
들어내, 향후 그래프DB 등 **다른 메모리 백엔드를 drop-in**할 수 있게 한다. 로드맵 #7의 정의는
"메모리 Protocol/ABC 추출(현 mem0 호출을 어댑터 뒤로) → 그래프DB 백엔드 drop-in **가능**" —
즉 **가능하게 만드는 인터페이스 추출**이지, 실물 그래프DB 구축이 아니다.

**왜 지금:** P2/P3로 메모리 사용처(RAG·스케줄러·통합)가 안정됐다. 5개 외부 소비자
(chat/runtime/agents/memory_routes/batch.jobs)는 **이미 공개 facade만** 호출하고, mem0 결합은
`memory.py` 한 모듈(import 1곳, `memory.py:126`)에 격리돼 있다 → seam이 깨끗해 지금이 추출 적기.

## 2. 현 상태 (census)

- **공개 facade(외부 소비자가 쓰는 5+1):** `memory_enabled`, `search(scope, query, mem_cfg, limit)`,
  `add(scope, messages, mem_cfg, infer)`, `list_memories(scope, mem_cfg)`,
  `update_memory(mem_id, text, mem_cfg)`, `delete_memory(mem_id, mem_cfg)`. 시그니처는 이미 backend-agnostic.
- **mem0 고유 부분(들어낼 대상):**
  - 인스턴스: `_get_memory`(mem_cfg-tuple 캐시) + `_cfg_key` + `Memory.from_config`.
  - 설정: `_build_config`(openai provider) + `_pg_vector_store` + `_sync_dsn` + `_EMBED_DIMS`(차원 결합).
  - 연산: `.search(query, filters={axis}, top_k)`·`.get_all(filters={axis})`·`.add(messages, infer, **scope)`·
    `.update(memory_id, data)`·`.delete(memory_id)`.
  - **정책(축별 루프 + 병합·dedup·score정렬·top-k·scope태깅):** 이건 mem0 **AND 필터 우회책**(learning 021)
    이므로 어댑터 내부로 들어간다 — 그래프DB는 union을 다르게 할 수 있다.
- **테스트 seam:** verify_020/029 → `_get_memory` 패치, verify_039 → `list_memories` 패치.

## 3. 설계 (권장안)

### 3.1 구조 — `memory.py` → `memory/` 패키지

```
packages/api/src/api/memory/
  __init__.py        공개 facade(6함수) — 기존 import 경로 `from api import memory` 보존. backend 해석·위임만.
  backend.py         MemoryBackend Protocol/ABC + 결과 타입 + 레지스트리/선택(resolve_backend)
  mem0_backend.py    Mem0Backend(MemoryBackend) — 현 mem0 로직 전부 이주(import mem0는 여기에만)
  inmemory_backend.py InMemoryBackend(MemoryBackend) — 레퍼런스 구현(계약 증명용, 인프라 0)
```

기존 `memory.py`는 패키지 `memory/`로 치환. `__init__.py`가 동일 이름을 re-export하므로
`from api import memory` / `memory.search(...)` 호출부는 **무변경**(소비자 5곳 그대로).

> 대안(저위험): 단일 모듈 `memory.py` 안에 클래스만 도입(파일 분리 없음). 패키지가 "drop-in 백엔드"
> 의도에 더 맞아 권장안으로 둔다. 승인 시 확정.

### 3.2 Protocol — 스코프 단위 op (축별 raw op 아님)

```python
Scope = dict   # {"user_id"?, "run_id"?, "agent_id"?}  (None 허용)
Hit    = dict  # {type, text, score, scope}
Record = dict  # {id, text}

class MemoryBackend(Protocol):       # (또는 ABC)
    def search(self, scope: Scope, query: str, limit: int) -> list[Hit]: ...
    def add(self, scope: Scope, messages: list[dict], infer: bool) -> None: ...
    def list_all(self, scope: Scope) -> list[Record]: ...
    def update(self, mem_id: str, text: str) -> bool: ...
    def delete(self, mem_id: str) -> bool: ...
```

- **mem_cfg는 Protocol 밖.** 백엔드는 `resolve_backend(mem_cfg)`에서 **설정을 박아 생성**한다
  (mem0 어댑터는 Memory 인스턴스를 보유). facade는 `b = resolve_backend(mem_cfg)`; `b`가 None이면
  안전 기본값 반환, 아니면 `b.method(...)` 위임. → 현 graceful 무력화·캐시 의미 보존(캐시 키에 백엔드 종류 추가).
- **축별 병합은 Protocol 계약**(관측 가능): `search`는 스코프 전 축의 **합집합 회상**(id dedup, 높은 score
  유지, score 내림차순, top-k 절단, hit에 scope축 태깅). mem0 어댑터는 축별 루프로, 인메모리 어댑터는
  자유 구현으로 — **같은 계약을 만족하면 통과**.

### 3.3 백엔드 선택 / drop-in 기전

`resolve_backend(mem_cfg) -> MemoryBackend | None`:
- 종류 결정: env `MEMORY_BACKEND`(기본 `"mem0"`). 레지스트리 `_BACKENDS = {"mem0": Mem0Backend, ...}`.
- 생성·캐시(키=(종류, cfg_key)), 설정 불완전/초기화 실패 → None(graceful).
- **drop-in = 클래스 1개 등록 + env 1개** — 이 단순성이 #7의 "가능"을 충족.

## 4. 작업 항목

1. `memory/backend.py` — `MemoryBackend` Protocol/ABC + `Scope/Hit/Record` 타입 + `resolve_backend`/`_BACKENDS` 레지스트리 + 백엔드 캐시(graceful None).
2. `memory/mem0_backend.py` — 현 mem0 로직 전부 이주(`_build_config`/`_pg_vector_store`/`_sync_dsn`/`_EMBED_DIMS`/
   축별 루프·병합). `import mem0`는 **여기에만**.
3. `memory/inmemory_backend.py` — `InMemoryBackend` 레퍼런스(dict 저장, 부분문자열 매칭으로 union 회상). 계약 충족이 목표.
4. `memory/__init__.py` — 공개 facade 6함수(기존 시그니처·docstring 보존), `resolve_backend` 위임. `memory_enabled`는 순수 함수라 그대로.
5. `mem_config.py` — 변경 없음(mem_cfg 해석기는 백엔드 무관). 확인만.
6. 테스트 seam 갱신: verify_020/029의 `_get_memory` 패치 → 백엔드/`resolve_backend` 패치로 이전. verify_039는 facade(`list_memories`) 패치라 무영향(확인).

## 5. 검증 (측정 가능 — 타자 검증 우선)

- **계약 테스트(앵커, 신규) `tests/verify_040_memory_backend_contract.py`:** 동일 단언 묶음을
  **Mem0Backend(실 mem0, 검증 유저 게이팅=verify_039 방식)** 와 **InMemoryBackend** **양쪽**에 돌린다.
  단언: 축 합집합 회상 / id dedup(높은 score) / top-k 절단 / scope태깅 / add 축태깅 / infer 전달 /
  update·delete 왕복 / graceful(None cfg→무력화). **둘 다 통과 = drop-in 실측 증명.**
- **회귀:** verify_020/029/039 전부 통과(seam 갱신 후).
- **격리(정적):** facade(`memory/__init__.py`·`backend.py`)에 `mem0` 참조 0 — grep. `import mem0`는 `mem0_backend.py`에만.
- **소비자 무변경(정적):** 5개 소비자 호출부 diff 0 — grep으로 공개 시그니처 보존 확인.
- **적대 리뷰(코어·필수, learning 038):** 서브에이전트에 "공개 facade 동작이 리팩터 전후로 **달라지는 입력**을
  찾아라"(병합 엣지·graceful 경로·캐시 키·top_k 우회) 명시. 드리프트는 floor 또는 §7 빚으로 정직히.
- **브라우저:** 메모리 콘솔(MemoryView) CRUD가 mem0 백엔드로 무회귀 동작 — 스크린샷.

## 6. 완료 조건

- [x] C1. `MemoryBackend` Protocol/ABC 정의, mem0 로직 100% `Mem0Backend`로, facade에 mem0 참조 grep=0.
      (`memory/{backend,mem0_backend,inmemory_backend}.py` + `__init__.py` facade. `import mem0`는 `mem0_backend.py` 1곳만.)
- [x] C2. `InMemoryBackend`가 Protocol 구현, 공유 계약 테스트가 **양 백엔드** 통과(drop-in 증명).
      (`verify_040` — 동일 단언이 inmemory/mem0(Sim 주입) 양쪽 ✅.)
- [x] C3. verify_020/029/039 전부 통과(seam 갱신 후). (seam = `M.resolve_backend` → `Mem0Backend.__new__`+`_mem` 주입.)
- [x] C4. 5개 외부 소비자 호출부 무변경(공개 시그니처 보존, grep 확인). (16개 호출부 diff 0, 전원 clean import.)
- [x] C5. 브라우저: 메모리 콘솔 CRUD가 mem0 백엔드로 무회귀. (라이브 add 201→list→행 렌더→delete 204→0행.)
- [x] C6. 적대 리뷰: 동작 드리프트 0(또는 빚 명문화). (기본 설정서 드리프트 0 — VERDICT faithful. 신규 `MEMORY_BACKEND` 기전은 §7에 의도된 신동작으로 명문화.)

## 7. 범위 밖 / 빚

- **실물 그래프DB 백엔드 구축**은 범위 밖(#7은 "가능"). InMemoryBackend는 계약 증명용 레퍼런스이지 프로덕션 백엔드가 아님.
- mem_cfg 구조 자체의 백엔드-중립화(현재 llm+embedder는 mem0 전제)는 후속 — 첫 비-mem0 백엔드 추가 시 재검토.
- `MEMORY_BACKEND` 외 백엔드별 추가 설정 채널(테이블/UI)은 후속.
- **의도된 신동작(적대 리뷰 C6 산물, drop-in 기전 자체):** 기본값(`MEMORY_BACKEND` 미설정=`"mem0"`)에선
  리팩터 전후 동작 100% 동일(응답 정규화·예외 흡수 입도·캐시 무재시도·scope 우선·infer 통과·빈가드 모두 byte-identical).
  추가된 표면은 둘뿐이며 모두 설정-게이팅: (1) 미등록 `MEMORY_BACKEND` 종류 → graceful `None` + `log.warning`(기존 "설정
  미비 → 무력화"와 동일 fail-safe), (2) 캐시 키에 backend kind 포함(종류 전환 시 재구성). 신규 백엔드가 없으면 트리거 안 됨.
