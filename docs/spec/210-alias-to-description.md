# 스펙 210 — 별명 폐지: 이름 단독 표시 + alias→description 개명

## 배경 (사용자 요청 2026-07-07, 항목 1·7)

스펙 148이 이름(식별)/별명(표시)을 분리하고 표시는 별명 우선으로 했는데, 실사용 결과 화면마다
표시가 제각각(에이전트 리스트=별명, 세션=이름, 블록=탭마다 다름)이라 혼란. 사용자 결정:
**모든 렌더링은 이름(name)만** 노출하고, 별명은 **설명(description)으로 개명**해 옵셔널 부가정보로
격하 — 리스트에서는 마우스 오버 툴팁으로만 노출.

사용자 선택(AskUserQuestion): **DB까지 개명**(표시만 변경 아님).

## 변경

### A. DB 마이그레이션 (한 번에 완성 — reload 재실행 함정 유의)
- `personas.alias` → `description` (rename)
- `mcp_servers.alias` → `description` (rename)
- `agents.alias` → `description` (rename)
- `collections`: 이미 `description` 보유 → **병합** `description = COALESCE(NULLIF(description,''), alias, description)`
  후 `alias` drop. (별명 값 소실 0 — 설명이 비어 있으면 별명으로 채움, 둘 다 있으면 설명 우선 유지)
- 리비전은 파일 저장 1회로 완성한다(--reload가 저장마다 migration 재실행 — memory `reload-reruns-migrations-mid-edit`).

### B. 백엔드
- models/schemas/serializers: `alias` → `description` (4종). EvalDataset·Provider·Role은 이미 description — 무변경.
- seed.py: 시드 데이터의 alias 값 → description.
- A2A external 유래(148: slugify+원문 별명): 원문 이름이 description에 저장되도록 임포트 경로 갱신.
- config/casbin 참조는 name 기반(148) — alias 미참조 확인(참조 무결성 무영향).

### C. 프론트
- `naming.ts` `displayName()` → **name만 반환**(단일 출처 — 소비처 전체가 이름 표시로 전환).
- 에이전트 리스트·블록 리스트(MCP/RAG/페르소나)·컬렉션 리스트: 이름만 + **Tooltip으로 description**.
- 세션 리스트: 이미 name(agent_name 박제) — 무변경 확인만.
- 폼: "별명(선택)" 입력 → "설명(선택)". 컬렉션 EditModal(176)은 별명+설명 2필드 → 설명 1필드.
- api.ts 타입 `alias` → `description`.

## 완료 기준 (측정 가능)
1. 마이그레이션 후 `alias` 컬럼 0개(4 테이블), 컬렉션 별명 값 소실 0(병합 전후 카운트).
2. `grep -rn "alias" admin/src packages/api/src` 잔존 0 (의도적 예외는 스펙에 기록).
3. 브라우저 e2e: 에이전트/블록/컬렉션/세션 리스트가 이름만 표시 + 마우스오버 툴팁에 설명.
4. tsc 0 에러, 기존 verify 무회귀.

## 실행 중 발견 (2026-07-07)
- **세션 agent_name 박제값**: 세션 리스트가 별명을 보이던 진짜 출처는 시드 세션 4행이 박제한
  "Research Assistant"류 문자열(런타임 박제는 원래 name). 시드 튜플을 식별 이름으로 수정 +
  기존 행 one-off `UPDATE sessions SET agent_name=a.name`(4행). 마이그레이션엔 미포함(이미 head
  적용 후 발견 — reload 함정 회피, 새 DB는 시드가 올바름).
- **구 계약 검증 스크립트 stale**: 표시 계약이 148(별명 우선)→210(이름 단독)으로 바뀌어 alias를
  단언하던 스크립트들이 구계약 검증이 됨. 파이썬 3개(verify_148/149/157)는 새 계약으로 갱신,
  브라우저 샷 7개(shot-naming-148·shot-custom-a2a-154·shot-eval-tool-honesty-170·verify-artifact-188
  ×2·verify-chunk-immutable-198·verify-grant-ux-200)는 당시 스펙의 시점 검증이라 **stale로 기록만**
  (재실행 시 alias 참조 부분은 실패 가능 — 재사용하려면 그때 갱신).
- **컬렉션 리스트 상시 설명 줄 제거**: 스펙 036 유래의 이름 아래 상시 설명 텍스트를 툴팁 단일화
  원칙에 맞춰 제거(워커 판단 보류 → 메인 결정).

## OUT
- 이름 규칙 자체(148 `^[가-힣a-z0-9.\-]+$`)는 불변.
- RBAC 비트리거(표시·컬럼 개명 — 소유권/게이트 무변경).
