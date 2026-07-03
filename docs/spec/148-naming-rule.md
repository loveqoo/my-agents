# 148 — 네이밍 규칙 + 식별 이름/별명 분리 (사용자 지정, v2)

## 규칙 (식별 이름에만 적용)
`_` 금지(대신 `-`) · 공백 금지 · 영어 대문자 금지. 허용: 한글·영소문자·숫자·대시(`-`)·마침표.
정규식: `^[가-힣a-z0-9.\-]+$` (선행/후행 대시 및 연속 대시는 v1 허용 — 과규제 회피).

## 이름 2원화 (2026-07-03 사용자 설계 — 5종 전부)
- **식별 이름** = 기존 `name` 컬럼: 규칙 적용, 참조·검색 키(에이전트 설정이 RAG/MCP/페르소나/권한을
  *이름으로* 참조 — 참조 키를 규칙으로 잠그면 자유 개명이 참조를 깨는 기존 취약이 해소된다).
- **별명** = 새 `alias` 컬럼(nullable): 자유 표기("옵시디언 매니저"), 화면 표시 = `alias ?? name`.
- 대상 5종: 에이전트·RAG 컬렉션·페르소나·권한·MCP 서버. (메모리 타입은 대상 외.)

## 적용 방식
- **UI 생성/이름 변경**: 서버 400(진실원), 프론트는 힌트+즉시 검사.
- **원격 유래**(external A2A 카드명·code SDK 등록명): 거부하지 않고 **자동 변환**(slugify) +
  원문을 별명으로 보존 — 우리가 짓는 이름이 아니므로 등록을 막지 않는다.
- 복제: 식별 이름 `{원본}-복사본`(+중복 시 `-2`…), 별명 `{원본 별명} (복사본)`.
- 에이전트 식별 이름 **유니크**(컬렉션·MCP는 기존에 이미 유니크). 페르소나·권한 유니크는 OUT
  (레거시 중복 가능성·참조 모호성은 기존과 동일 — 후속).

## 기존 데이터 (자동 변환 — 사용자 승인 2026-07-03)
마이그레이션에서 5종 전량: 위반 이름 → `alias=원문`, `name=slugify(원문)`(+중복 `-2`…), 그리고
**에이전트/버전 config 안의 이름 참조(persona·vectorTables·mcps·permissions·capabilities
"rag:/mcp:")를 old→new 매핑으로 함께 재작성**(move-breaks-references — 단방향 변환은 참조를 깬다).
seed.py도 규칙 준수 이름+별명으로 갱신(신규 설치가 위반 데이터로 시작하지 않게).

## 구현
- `api/naming.py`: `validate_resource_name(name)`(오류 메시지 or None)·`slugify_name(name)`(소문자화·
  공백/`_`→`-`·불허 문자 제거·대시 압축) — 순수 함수.
- alembic 1건: alias 5컬럼 + 데이터 변환(**규칙 준수 행 우선 처리** — codex High: 반대 순서면
  "docs_kb"가 "docs-kb"를 선점해 기존 참조가 엉뚱한 행을 가리킴) + 참조 재작성 + agents.name 유니크.
- 라우트: agents(create/update/clone/code등록/external빌더)·rag(create)·blocks(persona/permission/
  mcp create·update). 스키마 In/Out에 alias + max_length(DB 컬럼 정합, codex Medium).
- **참조 가드 확장(codex High/Medium)**: references.py 닫힌 집합에 permissions·persona(스칼라) 추가,
  mcps/vectorTables는 조율형 capabilities(`kind:name[/tool]`)도 검사. 페르소나·권한 rename/삭제에
  MCP(093)와 동일한 409 가드 — 이름 규칙 스펙은 사실 참조 무결성 스펙이다(개명이 교정 수단이 되므로).
- 프론트: 5종 폼에 식별 이름(규칙 힌트+즉시 검사)+별명 입력, 목록/드로어 표시=별명 우선(식별 이름
  보조 표기), 검색은 둘 다 매칭.

## 검증 (2026-07-03 완료)
- verify_148 45/45: 순수 함수 표본·라우트별 400·중복 409·복제 자동 이름·원격 자동 변환·grandfather
  편집 허용·참조 가드 409(V7, 자가-잠금 아님 핀 포함)·5테이블 전량 준수·config 참조 무결.
- e2e 6/6(fast-worker, shot-naming-148.mjs): 별명+식별 이름 2중 표기·폼 거부(버튼 disabled)·생성·
  검색(둘 다 매칭)·컬렉션 폼 거부·삭제. e2e 함정: 147 private 정책이 fixture 계정에도 적용(K1 첫
  FAIL — 타인 필터 opt-in으로 보정).
- codex 적대 리뷰: High 3(마이그레이션 dedupe 순서·페르소나/권한 참조 무가드)·Medium 3·Low 2 → 6건
  수정, 2건 OUT(아래).
- 마이그레이션 실 DB 적용 실측: "옵시디언 매니저"→"옵시디언-매니저"+별명 등 전량 변환·참조 재작성
  무결(dangling 0 — 기존 잔재 2건은 이전에 삭제된 컬렉션 참조로 무관).

## OUT (정직 경계)
- 동시 connect/복제의 자동 dedupe 레이스 — 한쪽 409(단일 관리자 환경, 재시도 루프 없음).
- 미참조 MCP rename 시 casbin per-cap 부여(`capability:mcp:{구이름}`)가 stale로 남을 수 있음
  (참조 중이면 rename 자체가 409라 실경로 좁음) — 후속: rename 시 정책 동반 갱신.
- 페르소나·권한 유니크 강제(DB에 이미 있음)·참조 자동 갱신(rename 시 config 일괄 재작성)은 후속.
- 2026-07-03 데이터 초기화(사용자 요청): 스키마 드롭→재시드(전량 규칙 준수 이름+별명)→docs-kb 샘플
  재적재(ingest 스크립트의 스펙 128 페이지 응답 미반영 잔재 수리)→qwen provider/기본 모델 재등록.
