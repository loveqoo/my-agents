# 292 — 네이밍 컨벤션 정밀화: 룰 명문화 + 기계 게이트 승격

## 배경

사용자 지적(2026-07-11, broker/core.py 열람): "네이밍·컨벤션이 들쭉날쭉하다" — 정확했다.
스펙 291의 네이밍 정리는 "분해하는 블록 안에서만"이라 파일·코드베이스 수준의 일관성은 미완이고,
수치 게이트(CC·MI·ruff·mypy)는 스타일 일관성을 못 잰다. **이번엔 룰을 촘촘히 명문화하고,
잴 수 있는 것은 전부 `make metrics`에 편입**한다(문서만 남기면 291의 재판 — 게이트가 재발을 막는다).

## 실태 (AST 전수 측정, 2026-07-11 — 886 함수)

| 축 | 실태 | 판정 |
|---|---|---|
| bool 반환 함수 60개의 이름 | 질문형 접두(is/has/can…) 22 · 형용사/과거분사 8 · **기타(명사구 등) 29** | 절반이 규칙 밖 — 통일 필요 |
| 파라미터 타입 주석 | 1786 중 **294 미주석(16%)** | mypy 관대 설정의 사각 |
| 반환 타입 주석 | 886 중 **114 미주석** | 〃 |
| 블록 for문 한 글자 변수 | **69회**(m·c·r·t·n·v…) | 전체 단어화 |
| 모듈 상수 | `_UPPER` 77 · `UPPER` 48 | 규칙 자체는 있음(내부=_접두) — 명문화만 |
| 축약어 | cfg 41·obj 22·db 17·resp 16… | 관용어 화이트리스트 명문화, 밖은 금지 |

## 룰 (촘촘한 판별 기준 — 애매함 제거)

### R1. bool 반환 함수 = 두 부류로만
- **판정 술어**(상태를 묻기만): 질문형으로 — `is_`/`has_`/`can_`/`may_`/`should_`/`supports_`/
  `wants_`/`allows_`/`uses_` 접두, 또는 3인칭 동사 어미(`_applies`, `_matches`, `_exists`,
  `_overlaps`, `_survives`). 예: `_direct_grant` → `_has_direct_grant`, `_rbac_check` →
  `_rbac_allows`, `valid_machine_token` → `is_valid_machine_token`, `_empty` → `_is_empty`.
- **동작+성공 여부**(부수효과 있고 성공 bool 반환): 동사 원형 유지 — `add_policy`, `remove_policy`,
  `probe_endpoint`. **판별자: 부수효과(쓰기·IO·상태 변경) 유무.**
- 게이트: `scripts/naming_audit.py`(신설)가 AST로 "bool 반환 + 술어 패턴 불일치 + 감사 화이트리스트
  (동작형 등재) 밖" = 위반 카운트. 목표 0, `make metrics-fast` 편입.

### R2. 타입 주석 전수 — 기계 게이트로
- 모든 함수의 파라미터·반환에 타입 주석(핵심은 ruff **ANN 규칙 활성**: ANN001/ANN2xx —
  `*args/**kwargs`(ANN002/003)·self/cls는 제외 설정). Any 남발 금지(구체 타입 우선, 정말 이질
  dict만 `dict[str, Any]`).
- mypy `disallow_untyped_defs`는 ANN 소거 후 켠다(이중 게이트 — ruff가 빠르고 mypy가 정밀).

### R3. 루프·지역 변수
- 블록 `for`문 타깃은 전체 단어(`for cap in caps`). **한 글자 허용은 두 곳만**: ① 한 줄
  컴프리헨션/제너레이터 내부, ② 수학적 인덱스 `i`/`j`(enumerate 등). `_`(버림)는 항상 허용.
- 게이트: naming_audit가 블록 for문 한 글자 타깃 카운트(컴프리헨션 제외). 목표 0.

### R4. 축약어 화이트리스트 (이 밖의 축약 금지 — 새 이름은 전체 단어)
`cfg ctx db sess conn args kwargs exc err req resp msg impl env caps cap col cols doc mem uid pk
ms i j` + 도메인 고유(`mcp rag a2a hil rbac sse llm`). 예: `rc`·`vt`·`prow`·`inv` 같은 임시 축약은
금지(→ `rag_collection`, `vector_table`, `persona_row`, `frame`). 게이트: 리뷰(기계화는 오탐 과다
— 사전은 audit 스크립트 docstring에 동거).

### R5. 상수·비공개·배치
- 모듈 내부 전용 상수 `_UPPER`, 모듈 밖에서 import되면 `UPPER`(현행 규칙 명문화).
- 모듈 헬퍼는 **사용처 위**(정의→사용, top-down). 클래스 전용 헬퍼는 클래스 바로 위 또는 스태틱
  메서드. 파일 구조: docstring → import → 상수 → 헬퍼 → 클래스 → 공개 함수/라우트.
- 게이트: 리뷰(배치는 기계화 안 함 — 이동 자체가 위험 대비 이득 낮음, 신규 코드에 적용).

### R6. 도메인 동사 사전 (이미 코드에 있는 체계의 명문화)
`resolve_`=이름/ID→객체 해석 · `build_`=조립(순수) · `derive_`=계산 파생 · `ensure_`=멱등 생성 ·
`load_`=IO 로드 · `_out`=직렬화 변환 · `_gate`/`_enforce_`=거부 가능 검사 · `spawn`=백그라운드 기동.
새 함수는 이 사전에서 동사를 고른다(사전에 없으면 스펙/회고에 추가하고 사용).

## 실행 (범위 — 측정 기반)

1. **P0 게이트 구축**: `scripts/naming_audit.py`(R1·R3 카운터+R4 사전) 신설, Makefile
   `naming` 타깃 → `metrics-fast` 편입. ruff ANN 활성(+마이그레이션 per-file-ignores).
2. **P1 소거**: R1 위반 ~29건 개명(외부 참조·tests 전수 갱신 — grep 전수, learning 149),
   ANN 위반(파라미터 294·반환 114) 주석 부여, R3 69건 개명. 분석·판정=메인, 실행=서브에이전트.
3. **P2 검증·마감**: `make metrics` 전판(스위트 51 포함) + codex 스팟(개명 참조 완전성).
   naming_audit 0 도달이 완료 조건(랄프).

## OUT
- R5 배치의 소급 이동(신규 코드부터), admin(TS) 네이밍(별도), 파일명·모듈명 개편.
- 화이트리스트 밖 축약의 소급 전수 개명은 이번에 안 함 — audit가 신규만 잡게 하고, 눈에 띄는
  악성(rc·vt·prow 류)만 P1에서 처리.

## 검증
- naming_audit 위반 0 · ruff(ANN 포함) 0 · mypy 0 · 스위트 51/51 · codex 개명 파급 리뷰.
