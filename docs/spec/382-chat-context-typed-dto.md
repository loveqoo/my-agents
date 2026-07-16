# 382 — chat_context typed DTO: ctx dict → `ChatContext` dataclass (캠페인 374 Tier 2 ②)

## 왜

codex 리뷰 A: `_load_context`가 반환하는 **ctx dict**(36키)가 채팅 핫 경로 7파일·~20개 내부 헬퍼를
관통하는데 타입 안전이 0이다(`dict[str, Any]` — mypy가 키·타입 미검사). `ctx["promt"]` 오타가
조용히 None을 반환. 계약이 암묵이라 어떤 키가 있는지 코드로 드러나지 않음.

구남님 결정(2026-07-16): **전면 DTO 객체**(TypedDict 아님) — dict를 dataclass로 완전 교체.
whole-fix-over-minimal-patch.

## 무엇

`ChatContext` **mutable dataclass**(36필드)를 `chat_context.py`에 정의, `_load_context` 반환 타입으로.
접근이 `ctx["x"]` → `ctx.x`로 바뀌고 mypy가 전 접근 사이트의 필드·타입을 정적 검사.

### blast radius (측정)

- **소비처 7파일 191 사이트**: chat.py(91)·chat_approval(39)·eval_runner(24)·chat_stream(23)·
  chat_persist(9)·eval_suggest(3)·chat_history(2).
- chat_context.py 내부 20 사이트 + **ctx를 받는 헬퍼 시그니처 11개**(`ctx: dict` → `ctx: ChatContext`).
- ctx는 `resolve_agent_runtime`·`_rag_tools_for`·`_memory_inputs`·`_graph_fingerprint`·
  `_build_turn_runtime`·`_resolve_session_for_persist` 등에 **통째 전달** → 이 헬퍼들도 DTO 소비.

### 설계 결정

- **mutable dataclass** — ctx는 `_load_context`에서 **증분 빌드**(dict 리터럴 22필드 → 이후 14필드
  단계 할당)되고 **수령 후 변형**(chat_approval이 session_pk/session_pending 재설정)된다. frozen이면
  둘 다 깨짐 → mutable + 필드 기본값으로 증분 빌드 허용.
- **필드 기본값** — 증분 할당 필드(model_cfg·pins·session_* 등)는 `None`/`field(default_factory=...)`
  기본값. `_load_context`가 전 필드를 채우므로 런타임 결과는 dict 시절과 동일.
- **toolPolicy → tool_policy** — 유일한 camelCase 키(6 read 사이트)를 snake_case로 정리(dataclass
  N815 회피·일관). ctx는 wholesale JSON 직렬화 안 됨(값만 개별 소비)이라 rename 안전.
- **`.get("x", default)` 감사** — 명시 기본값은 chat_persist `ctx.get("prompt", "")` 하나뿐. prompt는
  항상 str이라 `.x`로 무손실 변환(default "" 죽은 코드였음).

### 완전성 그물 = mypy

변환 후 `make typecheck`가 **베이스라인(block_versions.py 무관 2건) 외 0 에러**여야 완료. 남은 `ctx[`는
"ChatContext is not indexable", 오타 attr은 "has no attribute"로 mypy가 전수 포착 → 누락 = 측정으로 확인.

## 완료 조건 (동작 불변)

- mypy 에러 = 베이스라인 2건(block_versions.py)만 · ruff 통과.
- app import(순환 0) · make test SUITE_OK · e2e 39/39 · 실제 채팅 왕복(스트리밍·승인 재개) 무회귀.
- 필드 36개 = dict 시절 키 집합과 1:1(런타임 값 동일).

## 검증 결과 (2026-07-16 — done)

전부 초록: mypy 베이스라인(block_versions.py 무관 2건) 외 0 · ruff clean · app import(순환 0) ·
SUITE_OK · e2e 39/39(실 스트리밍 채팅 #23·A2A #24·승인 #22) · verify_117(승인 resume — chat_approval
수령 후 변형) · verify_049(세션 정리 실경로) ALL PASS. 36필드 DTO, ~211 접근 사이트 mypy 정적 검증.

**덤(격리 축소)**: verify_049가 스펙 291의 `_create_approval(user_id)` 미갱신으로 격리돼 있었는데, ctx
dict→DTO 봉합과 함께 그 옛 호출도 고쳐 **격리 해제**(KNOWN_DRIFT −1, 그물이 049를 포함해도 green).

**사전 결함 확인(내 회귀 아님, stash 대조)**: verify_122(오버라이드 모델 드리프트)·057(asyncpg
이벤트루프 플레이크)·029:177(agents.py→패키지 이동)은 원본 코드에서도 동일 실패 → 격리 유지. 단
그 안의 옛 `ctx["x"]` 소스검사·subscript는 landmine 제거차 함께 갱신(029:162·058:140·122 capabilities).

## OUT

- ChatContext를 별 모듈(`chat_types.py`)로 분리 — 지금은 chat_context.py 내 정의(빌더와 동거)로 충분.
- 필드 그룹핑(session/rag/model 서브객체) — 계약 표면을 더 줄이는 후속(YAGNI, 이번은 dict→flat DTO).
