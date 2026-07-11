# 291 — 파이썬 대정리: 객관 기준(PEP8) 수립 → 정리 → 구조 → 타입

## 배경

사용자 지시(2026-07-11): "파이썬 코드를 깔끔하게 정리 — 디자인 패턴·우아함으로 그 누구도 트집
못 잡게. **PEP8 등 스타일 가이드 준수.**" 범위 선택 = **C(전체)**: 기준 수립 + 진짜 잔여 수정 +
god-module 구조 분할 + 타입체커 도입.

정찰 실측(2026-07-11):
- **기본 규칙(pycodestyle E/W + F)으로는 이미 거의 깨끗**(위반 3건). 저수준 지저분함 없음.
- **린터·포매터·타입체커가 하나도 설정돼 있지 않음** — "트집 못 잡게"의 출발점인 *기계가 판정하는
  기준*이 부재. 이게 1순위.
- 확장 규칙셋 4093건이지만 **대부분 의도된 패턴**: `B008`(203, FastAPI `Depends()` 관용구)·
  `N815`(50, Pydantic API 계약 camelCase 필드 `sessionId` 류)·`E501`(3511, 긴 한글 주석). 진짜
  고칠 잔여는 200~300건(예: `B904` 예외 체이닝 18·`RUF100` 죽은 noqa 74·`I001` import 정렬 21·
  `ARG`·`TRY`·`SIM`·`UP`·`C4`).
- god-module 4개: `chat.py`(1891줄)·`eval_routes.py`(1393)·`broker.py`(1296)·`agents.py`(1237).
- 대상: `packages/api/src`(59파일 17805줄) + `packages/agent/src`(11파일 1937줄). 파이썬 3.12.

## 원칙

- **동작 불변**. 순수 정리·구조 이동·타입 주석만. 런타임 행위 변경·새 기능 금지. 안전망 =
  실모델 조합 스위트 51개(스펙 290, retries=2). **각 단계·각 분할마다 스위트 전판 초록**이 게이트.
- **PEP8는 도구가 강제한다**(자가선언 금지). ruff(E/W=pycodestyle·N=네이밍·I=import 그룹) +
  `ruff format`(Black 호환, PEP8 레이아웃)이 판정. "트집" = ruff/mypy 비-제로.
- **의도된 이탈은 삭제가 아니라 문서화된 예외로**. PEP8 위반처럼 보이지만 정당한 것(API 계약
  camelCase·한글 주석 유니코드·FastAPI Depends)은 설정에 *이유 주석과 함께* ignore — 침묵 억제가
  아니라 근거 박제([[complement-attack-can-be-honest-boundary]] 결: 고침도 기각도 아닌 정직화).

## 측정 지표 (베이스라인 → 목표) — 실측 2026-07-11

단순 정리가 아니라 **수치로 관리**한다([[numeric-verification-unlocks-autonomy]] — 완료조건을
측정 가능하게 설계하면 Ralph 반복도 가능). 아래가 진척·완료의 객관 잣대.

| 지표 | 도구 | 베이스라인 | 목표 | 기계 게이트 |
|---|---|---|---|---|
| 평균 순환복잡도(CC) | `radon cc -a` | **4.40 (A)** | ≤ 4.40(악화 금지) | — |
| CC 등급 D+ 블록(CC≥21) | `radon cc -n D` | **20** (15D·3E·2F) | **0**(전 블록 ≤ C) | `ruff` C901 max-complexity |
| 최악 블록 CC | `radon cc -s` | **73** (`_load_context`) | ≤ 20(코어 ≤ 10 지향) | 위와 동일 |
| MI 등급 A 미만 파일 | `radon mi -s` | **4** (chat·broker·eval=C·agents=B) | **0**(전 파일 A, MI≥20) | `xenon --max-modules A` |
| ruff 위반(문서화 ignore 제외) | `ruff check` | **191**(Phase 0 설정 실측, 자동수정 ~102) | **0** | `ruff check` exit 0 |
| 포맷 미준수 파일 | `ruff format --check` | **56/70** | **0** | exit 0 |
| mypy 오류(정의 범위) | `mypy` | **37**(느슨) | **0** | `mypy` exit 0 |
| 실모델 조합 스위트 | `tests/suite/run.py` | **51/51** | **51/51**(무회귀) | 각 단계 게이트 |

- **단일 게이트 스크립트**(`scripts/metrics.sh` 또는 `make metrics`): ruff check + format --check +
  xenon(radon 임계) + mypy + 스위트를 한 번에 돌려 하나라도 실패면 비-제로. 이게 Phase별 완료 판정
  이자, 향후 Ralph 루프의 종료 조건. Phase 0에서 이 스크립트부터 만들어 **베이스라인을 박제**한다
  (측정을 재현 가능하게 — 자가선언 금지, learning 149 결).
- worst offenders(Phase 3 표적): `_load_context` CC73·`chat` CC43·`resume_approval` CC38·
  `_agent_a2a_skills` CC40·`start_run` CC37 — 전부 god-module. 분할이 곧 CC·MI 개선의 본체.

## 리팩터링 방법 (적용 패턴) — 자가선언 아닌 실제 적용

복잡도를 낮추는 건 임의 분해가 아니라 **정해진 패턴의 적용**이다. 이 코드의 실제 최악 블록에
매핑:
- **Extract Method(관심사별 분리)** — `_load_context`(CC73)의 9개 관심사(에이전트·버전/페르소나·
  오버라이드·capabilities·모델·메모리·MCP·RAG·세션)를 이름 붙은 헬퍼로 분리 → 본체는 오케스트
  레이션, 각 헬퍼 CC<10. `chat`(CC43)·`resume_approval`(CC38)·`start_run`(CC37)도 동형.
- **Guard clause / early return** — 중첩 `if`를 조기 반환으로 평탄화(깊이=복잡도).
- **타입 있는 컨텍스트(dataclass/TypedDict)** — `ctx: dict`(키 20여 개를 흩뿌려 set)를 타입 구조로
  → **구조 정리 + mypy 관통이 한 번에**. Phase 3(구조)과 Phase 4(타입)의 교집합 기법.
- **분기 dispatch는 이미 전략 패턴** — flows `consumes` 튜플(스펙 206)은 유지(건드리지 않음).
- **Replace conditional with table** — if-elif 체인(있으면)은 dict dispatch로.

## 네이밍·주석 축 (리뷰 게이트 — 수치화 불가 정직 인정)

수치로 못 재는 두 축. **codex/deep-reasoner 리뷰로 게이트**(자가검증 지양 원칙 그대로).
- **네이밍**: 상수·변수·함수를 사람이 지은 듯 간결하게. 암호적 축약(`_P`·`vt_names`·`rc`·`cols`·
  `prow`·`mem_cfg`) → 읽히는 이름. 단 장황 금지(간결 > 서술). PEP8 네이밍(ruff N)이 형식 게이트,
  의미 적절성은 리뷰.
- **주석**: 딱 필요한 설명만. 규칙 —
  · 코드가 말하는 것(WHAT) 되풀이 주석 → **삭제**.
  · 코드에 없는 이유(WHY) → **유지**, 단 스펙/learning 있으면 서사 줄이고 **ID 링크로**
    (INDEX 층 원리를 주석에 적용 — 서사는 스펙, 주석은 포인터). 참고 문서 있으면 재설명 대신 링크.
  · 결정 기록(적대 검토 결과 등)은 손실이므로 **삭제 아닌 압축**.

## 단계 (측정 가능 완료 기준)

### Phase 0 — 기준 수립 (코드 무변경, 설정만)
- `pyproject.toml`에 `[tool.ruff]`: `target-version = py312`, `line-length`(정책 결정 아래),
  `select` = PEP8 코어(E,W,F) + I(import 정렬=PEP8 그룹) + N(PEP8 네이밍) + UP(3.12 현대화) +
  B,C4,SIM,RET,RUF(품질). `[tool.ruff.format]` 채택(Black 호환).
- **의도 예외 인코딩**(각 이유 주석): `B008`(FastAPI Depends 전역), `per-file-ignores`로
  `schemas.py`·모델 스키마의 `N815/N803`(API 계약 camelCase), `RUF001-003`(한글 문서 모호문자).
- `[tool.mypy]`: 점진 도입 설정(초기 코어 모듈 strict, 나머지 완화 → Phase 4에서 조임).
- **line-length 정책 결정**: PEP8 권장 79는 현 코드(한글 주석·긴 시그니처)와 불화 → **100**
  채택(E501은 코드에만 적용, 긴 주석은 formatter 미대상이라 자연 잔존 — 필요 시 개별 유지).
- 완료: 설정 커밋 후 `ruff check`·`mypy` 베이스라인 수치가 재현 측정된다(코드 diff 0).

### Phase 1 — 자동 안전 수정
- `ruff check --fix`(safe만) + `ruff format` 전판. import 정렬·죽은 noqa·UP·C4·SIM 안전분·
  포맷 레이아웃 일괄. 대량·기계적 → **fast-worker 위임 후보**(전후 ruff 카운트 측정으로 마감).
- 완료: 스위트 51/51 초록 + 그 규칙군 잔여 0. 커밋.

### Phase 2 — 진짜 잔여 수동 수정
- `B904` 예외 체이닝(`raise ... from e`) 18·real `ARG`·`TRY003/004/300/301`·`B008` 외 B계열·
  나머지 → **ruff check exit 0**(Phase 0에서 인코딩한 문서화 ignore 제외).
- 판단 필요분(어느 예외를 어디 체이닝, unused arg가 인터페이스 계약인지)은 메인·deep-reasoner.
- 완료: `ruff check packages/*/src` exit 0 + 스위트 51/51. 커밋.

### Phase 3 — 구조 정리 (god-module 분할)
- 역할별 분할(행위 보존 리팩터, import 재배선만): `chat.py` → 세션 해석/스트리밍/히스토리
  재구성/영속 등 관심사 분리; `eval_routes`·`broker`·`agents`도 역할별. 분할 경계는 각 파일
  착수 시 deep-reasoner로 관심사 지도 먼저(무리한 분할 금지 — 응집 유지).
- **각 파일 분할 = 독립 커밋**, 직후 스위트 전판 + `ruff`/`mypy` 무회귀. 비가역·대규모 이동이라
  분할마다 **codex 행위보존 적대 리뷰**([[move-breaks-references-both-directions]] 양방향 참조·
  [[whole-fix-over-minimal-patch]] 전체 정합).
- 완료: 4개 모듈 각 응집 단위로 분할·스위트 무회귀·순환 import 0.

### Phase 4 — 타입체커 도입
- `mypy` 도입. 전략: **코어 먼저**([[core-is-model-config-and-memory]]) — 모델/설정·메모리
  경로를 strict로 힌트 갭 닫고, 라우트·주변은 점진(`disallow_untyped_defs` 단계적 확대).
- 완료: 정의된 범위에서 `mypy` exit 0 + 스위트 51/51. 최종 strictness 문서화.

## 검증 (사다리 3런 — 비겹침)
- **객관 게이트(수치)**: `ruff check` exit 0 · `ruff format --check` 통과 · `mypy`(범위) exit 0 ·
  `xenon`(CC/MI 임계) 통과 · 스위트 51/51. `make metrics` 한 방.
- **동작 불변**: 실모델 조합 스위트 51개, 각 단계·각 분할마다.
- **적대 타자**: 구조 분할(Phase 3)은 codex 행위보존 리뷰(참조 양방향·순환·누락 export).
- **네이밍·주석(수치화 불가)**: deep-reasoner/codex 리뷰 게이트 — Phase 3(분할 중 자연히 개명·
  주석 압축)에서 수행하고 리뷰로 마감. 네이밍 형식은 ruff N이 선게이트.

## OUT (이번에 안 함)
- 런타임 동작 변경·새 기능·성능 최적화(순수 정리만).
- admin(TS/React) 정리 — 별도.
- 긴 한글 주석 리라이트(내용 보존이 우선, E501 주석은 정책상 허용).
- CI 파이프라인 신설(로컬 `make lint`/pre-commit 훅은 여유 시 선택).

## 커밋 전략
- Phase별 per-commit(상시 승인). Phase 3은 파일 분할마다 세분 커밋(스위트 그린 핀). 푸시는
  사용자 명시 시만.
