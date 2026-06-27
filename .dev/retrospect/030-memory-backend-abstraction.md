# 030 — 메모리 백엔드 추상화 회고 (스펙 040, P4)

> 지배 스펙: `docs/spec/040-memory-backend-abstraction.md`. 관련 learning: [[039-second-implementation-measures-drop-in]],
> [[038-adversarial-review-finds-what-invariants-miss]], 020-pgvector-shared-backend, 021-mem0-value-is-scope-not-type.

## 무엇을 했나

- `memory.py`(단일 모듈) → **`memory/` 패키지**: `__init__.py`(facade, 공개 표면 보존) + `backend.py`(Protocol
  `MemoryBackend` + `resolve_backend` 선택/캐시) + `mem0_backend.py`(mem0 로직 전량 이전, `import mem0`는 여기 1곳만) +
  `inmemory_backend.py`(mem0 한 줄도 안 쓰는 dict 레퍼런스 백엔드).
- mem0의 축별 검색·병합·응답 정규화·dedup·top-k를 **byte-identical로 `Mem0Backend`에 이식**. facade 5함수는
  `resolve_backend(mem_cfg)` 위임 + 백엔드 None이면 안전 기본값(메모리 없어도 동작, 스펙 019).
- 백엔드 선택은 `MEMORY_BACKEND` env(기본 `"mem0"`) + `_BACKENDS` 레지스트리(lazy import) → grep0 격리.

## drop-in을 *주장*이 아니라 *측정*으로 만든 것 (이번의 핵심)

로드맵 #7의 완료 조건은 "그래프DB 백엔드 **drop-in 가능**"이다. 백엔드 추상화는 짜기 쉽지만, 그게
**진짜 백엔드-중립인지**는 mem0 구현 안에서는 보이지 않는다 — 내가 추상화 뒤로 숨겼다고 믿는 mem0 가정이
Protocol 시그니처에 새고 있어도, mem0 한 종류만 돌리면 영원히 안 드러난다.

→ 그래서 **두 번째 독립 구현(InMemoryBackend)을 함께 출하**하고, **동일 계약 단언 묶음**(`verify_040`의
`run_contract`)을 양쪽에 돌렸다. InMemoryBackend는 mem0 코드를 한 줄도 안 쓰는 dict 구현이라, 둘 다 같은
합집합 회상·격리·dedup·scope태깅·top-k·빈가드·update/delete 왕복을 통과 = **추상화가 실제로 mem0에
의존하지 않음을 측정**. 한 구현만 있었으면 "drop-in 가능"은 영영 주장이었다. **자세히 → [[039-second-implementation-measures-drop-in]]**.

- mem0 쪽은 `Mem0Sim`(mem0 2.0.7 관측 표면 모사: results/id/memory/score, 단축 필터)을 주입해 **어댑터의
  병합·정규화 경로를 실제로 태웠다** — `Mem0Backend.__new__` + `_mem` 주입으로 mem0 init 없이.

## 적대 리뷰의 임무가 "버그"가 아니라 "드리프트"였다

파괴적 작업이 아닌 **충실한 리팩터**라 적대 리뷰 프롬프트를 "공개 facade 동작이 리팩터 전후로 *달라지는
입력*을 찾아라"로 조준(병합 엣지·graceful 경로·캐시 키·top_k 우회). VERDICT = 기본 설정서 드리프트 0,
faithful. 발견된 "드리프트" 2건은 모두 **의도된 신규 표면**(설정-게이팅): 미등록 `MEMORY_BACKEND` →
graceful None+warning(기존 fail-safe와 동형), 캐시 키에 kind 포함. → §7에 "의도된 신동작"으로 명문화.

- 교훈: 리뷰 프롬프트의 조준이 리뷰 산출물을 정한다. 리팩터엔 "버그 찾아라"가 아니라 "전후 차이 나는
  입력 찾아라"라고 시켜야 한다. 38의 "내 불변식의 여집합"과 같은 원리 — 공격 각도를 작업 성격에 맞춰라.

## 테스트 seam 이전 (스테일 수선 포함)

- 옛 테스트는 `_get_memory`를 패치했는데 리팩터로 사라짐. 새 seam = `M.resolve_backend`를
  `Mem0Backend.__new__`+`_mem` 주입 백엔드로 패치 → **실제 병합 코드 경로**를 mem0 init 없이 탄다.
- verify_020 `test_add`가 2건 FAIL — 진단하니 **내 리팩터가 깬 게 아니라 스펙 029부터 stale**(029가 add에
  `infer` 파라미터 추가, 옛 코드도 `infer=infer`를 넘겼는데 020 테스트가 exact dict로 단언). Context 원칙대로
  그 자리서 수선(infer 빼고 비교). **단정 전 한 겹 더 파니** 내 탓이 아니라 기존 누적 부채였다.

## 검증

- `verify_040`(양 백엔드 계약) ✅ + 회귀 `verify_020/029/039` ✅ + 적대 리뷰 drift0 + 브라우저 라이브 CRUD
  (Research Assistant add 201 → 행 렌더 → delete 204 → 0행, 스샷). C1–C6 전부 충족.
