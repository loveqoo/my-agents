# 369 — 블록 버전화 (스펙 367-B: append-only 단조 불변 버전)

## 왜

스펙 367 확정 모델의 B 단계. 블록(prompt·memory-type·mcp-server·model·provider)이 지금은 가변 행이라
에이전트가 블록 버전을 못박을(C) 대상이 없다. 블록에 **무상태 append-only 단조 버전**을 깐다 —
draft/activate 없음(상태는 에이전트만), 편집=새 버전 append, 어떤 버전도 사후 불변.

## 설계

### 1. 저장 구조 — 공유 메커니즘 하나 (head + 폴리모픽 이력)

- **기존 블록 테이블 = head(최신 스냅샷)** 유지 — 목록/해석(resolve_prompt 등) 기존 코드 무접촉.
  각 블록 테이블에 `version: int default 1` 컬럼 추가.
- **이력 = 단일 폴리모픽 테이블 `block_versions`** (5종 공유 — 367 "공유 버전 메커니즘 하나"):
  ```
  id uuid PK · kind str(prompt|memory-type|mcp-server|model|provider)
  block_pk uuid(index) · version int · payload JSONB(그 버전의 저작 내용)
  + AuditMixin(created_at/by)   UNIQUE(kind, block_pk, version)
  ```
  kind별 테이블이 달라 FK 불가 — 블록 삭제 시 이력은 **앱 레벨 같은 트랜잭션에서 삭제**(삭제는 기존
  참조 가드가 미참조일 때만 허용, 스펙 093; 오픈된 에이전트 버전이 못박은 블록의 삭제 차단은 **C에서**).

### 2. 버전화 경계 — 저작 내용만, 운영 상태·비밀 제외

**payload = 동작을 결정하는 저작 내용**. 운영 상태·비밀은 head 전용(버전 무증가):

| kind | payload(버전화) | head 전용(비버전) |
|---|---|---|
| prompt | name·description·tone·body | — |
| memory-type | key·name·scope·body | — |
| mcp-server | name·description·source·transport·url·endpoint·tools·enabled_tools·tools_meta | status(라이브 헬스)·published(서빙 토글)·auth(비밀)·owner_id |
| model | name·provider_id·model_id·kind·params | is_default(포인터)·meta(카탈로그 캐시) |
| provider | name·protocol·base_url·kind·description | api_key(비밀 — 이력에 비밀 잔존 금지) |

- 비밀(provider.api_key·mcp auth)은 **이력에 절대 안 싣는다** — 로테이션이 과거 버전에 잔존하면 유출면.
  결과: 키 로테이션은 버전 무증가(운영 행위) — 수용된 경계.
- publish·is_default·status 변경 = 버전 무증가(C4로 검증).

### 3. 관문(chokepoint) — 버전 append는 헬퍼 한 곳

`record_block_version(session, kind, row, payload)` 단일 헬퍼: head.version+1 스탬프 + 이력 append를
같은 트랜잭션에. **모든 콘텐츠 변경 경로가 경유** — PUT 7곳(blocks.py prompts/memory-types/mcp-servers,
model_registry, providers) + **MCP 재탐색 동기화**(tools/tools_meta 갱신 — merge-preserve 경로도 콘텐츠
변경이므로 bump). 잡별 삽입 금지([[policy-at-the-chokepoint]]) — 미경유 mutate가 남으면 그 경로만
버전 없이 동작이 바뀐다(C6 자로 전수 확인).

- **동시 편집 레이스**: 같은 트랜잭션의 UNIQUE(kind,block_pk,version)가 이중 append를 막는다 —
  충돌 시 409("다른 편집과 겹침 — 다시 시도").

### 4. API·UI (최소)

- `GET /block-versions/{kind}/{block_pk}` → 이력 목록(version·created_at/by·payload 요약),
  `GET /block-versions/{kind}/{block_pk}/{version}` → 그 버전 payload. 제네릭 한 쌍(5종 공유).
- 기존 PUT 계약 불변(응답에 `version` 필드 추가만). 새 쓰기 엔드포인트 없음.
- UI: BlocksView 상세에 `v{n}` 태그 + 이력 목록(시각·작성자·보기). "채택" 배지·비교는 **C에서**
  (못박은 버전이 있어야 비교 대상이 생김 — 367 로드맵의 promptStale 은퇴도 C로 이동).

### 5. 이관·시드

- 마이그레이션(프로그램적 생성, learning 364): 5개 블록 테이블에 version 컬럼 + block_versions 테이블.
  백필: 기존 전 블록의 현재 내용 → v1 이력 행.
- 시드/신규 생성: 생성 경로도 관문 헬퍼 경유(v1 이력 자동). 공용 `ensure_v1_rows(session)`를 시드
  말미에 호출(백필과 같은 함수 재사용 — 처녀 빌드·기존 DB 동일 불변식).

## 완료 조건 (수치)

- **C1** 5종 각각 PUT → head.version 증가 + 이력 append + **이전 버전 payload 바이트 불변**(수정 후 재조회).
- **C2** 이관 불변식: 블록 행 수 == v1 이력 행 수(기존 DB 백필·처녀 빌드 시드 둘 다), clean boot.
- **C3** 동시 PUT 8발 레이스: 성공분 버전 연속·중복 0(UNIQUE 실측), 나머지 409.
- **C4** 운영 상태 변경(publish·is_default)은 version 불변.
- **C5** `make test` SUITE_OK + `make e2e` green(블록 CRUD 계약 무회귀).
- **C6** 완전성 자: 블록 콘텐츠 mutate 경로 전수 대장(grep) — 관문 헬퍼 미경유 **0**.

## 검증 결과 (2026-07-15 — done, verify_369 ALL PASS)

- **C1** 5종 전부: 생성=v1·편집→v2(prompt는 v3까지)·**v1 payload 바이트 불변**(편집 2회 후 재조회 동일)·
  무변경 저장 무증가. 직렬화 함정 하나 잡음 — 명시적 생성자(mcp_to_out·provider_to_out·model_to_out)는
  스키마에 필드를 추가해도 안 실어 기본값 1로 표시(ORM 모드와 달리 **명시 전달 필요**).
- **C2** 부트 백필 41건 → 이력 없는 블록 **0**(5종 전수 DB 실측).
- **C3** 동시 PUT 8발: 전부 200·버전 [1..11] **중복 0·연속**(단일 이벤트 루프+커밋 직렬화, UNIQUE는 백스톱).
- **C4** provider 키 로테이션만·model is_default만 → **버전 무증가**(경계 실측).
- **C5** make test SUITE_OK · make e2e 39/39.
- **C6** 관문 외 콘텐츠 mutate **0** — 대장: PUT 7곳 + MCP 재탐색 + **seed reconcile**(스윕이 잡은 미경유
  1건 — 코드 배포로 served MCP 도구 정의 변경 시 버전 없이 mutate하던 경로, 배선 완료) + 생성 4곳 +
  삭제 5곳(이력 동일 tx 정리).
- **UI**: 상세 드로어 "버전: vN" 태그 + "버전 이력 (N)" Collapse(시각·작성자·payload 보기) — 브라우저
  실측(v3 프롬프트로 확인, tsc 0).

## OUT

- 에이전트의 버전 못박기·"채택" 배지·promptStale 은퇴 — **C(스펙 367)**.
- RAG 컬렉션 버전화 — 제외 확정(367).
- 버전 diff/비교 UI·롤백 UI — 블록엔 롤백 없음(못박기는 에이전트가 함). 이력 열람까지만.
- NodeTemplate·AppSetting 등 비-빌딩블록 — 범위 밖(에이전트 config가 참조하는 5종만).
