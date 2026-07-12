# 304 — 테스트 잔해 스윕(프리픽스 화이트리스트) + 기존 정리

## 배경
스펙 303(시드 트림)에서 갈라낸 두 번째 층. dev `agents` DB에 **58 에이전트 중 53이 테스트 산물**
(브라우저/verify 테스트가 라이브 DB에 POST하고 teardown이 없어 누적). 딸린 잔해: 세션 1247·메시지
5772·에이전트버전 53·승인 77(감사행). 재발원은 **teardown 부재**(브라우저 `_fixture.mjs`는 임시
*유저*만 지우고 그 유저가 만든 에이전트는 안 지움; `suite/fixtures.py`만 멱등으로 9행 안정; `smoke_303`만
격리 DB). 조사: 서브에이전트 2건(§검증 참고).

사용자 결정(AskUser 2026-07-12): (1) 식별=**테스트 프리픽스 화이트리스트**(앞으로 UI로 만든 실 에이전트
보호), (2) 재발 방지=**스윕 스크립트 + make 타깃**(지금 정리 + 브라우저 배치 후 재사용), (3) 기존
잔해=**지금 삭제**.

## 잔해 인벤토리(실측 53, 프리픽스별)
`pipeline-`(12)·`rt-`(11: rt-271/272)·`suite-`(9, 안정)·`pnode-`(7: pnode-268)·`hist-`(5: hist-270,
`-copy` 포함)·`node-insp-`(3)·`pipe-exec-`(2)·`rag-insp-`(1)·`rag-node-`(1)·`detail-shot-`(1)·
`approval-demo`(1 고정명). **seed 5명**(research-assistant·personal-secretary·plan-execute-demo·
doc-translator·acme-translate-a2a)은 어떤 프리픽스와도 안 겹침(충돌 0 실측).

## 설계

### 프리픽스 화이트리스트(닫힌 집합, 53 전량 커버 검증)
```
approval-demo  detail-shot-  hist-  node-insp-  pipe-exec-  pipeline-
pnode-  rag-insp-  rag-node-  rt-  suite-
```
버전 꼬리(271/272·270·268)는 프리픽스 축약(`rt-`·`hist-`·`pnode-`)으로 흡수 — 같은 계열 재실행이
새 꼬리를 붙여도 잡힌다. seed 명은 이 집합의 어느 것으로도 시작하지 않음.

### 이중 가드(안전)
삭제 대상 = `name이 화이트리스트 프리픽스로 시작` **AND** `agent_id NOT IN (seed 5)`. 프리픽스가
seed와 겹칠 일은 없지만(실측), seed-keeplist를 겸해 **어떤 경우에도 seed·실 에이전트는 불가침**.
화이트리스트에 없는 이름(=사용자가 UI로 만든 실 에이전트)은 **건드리지 않음**.

### 스윕 스크립트 `tests/sweep_debris.py`
- **dry-run 기본**: 인자 없이 실행하면 *지울 것만 보고*(에이전트/세션/메시지/버전 카운트 + 이름 목록),
  **실삭제 안 함**. `--apply`를 줘야 실제 삭제(비가역 파괴는 명시 옵션 뒤로 — 적대 리뷰 습관).
- `DATABASE_URL` 존중(기본 dev DB). 삭제는 ORM/SQL `DELETE FROM agents WHERE ...` — Agent 자식
  FK가 DB단 `ondelete=CASCADE`(agent_versions·sessions→messages→message_feedback)라 **cascade
  자동 정리**, approvals는 `SET NULL`(감사행 보존). 실측 전후 카운트 출력(자가선언 금지·측정 마감).
- 안전핀: 화이트리스트가 비면 즉시 중단(전삭제 방지). seed-keeplist 상수는 seed.py의 AGENTS/
  커스텀/코드/외부 5 id와 단일 출처(드리프트 시 주석 링크).

### make 타깃
- `make sweep-debris` — dry-run(무해, 언제나 안전).
- `make sweep-debris-apply` — 실삭제(브라우저 배치 후 재사용 teardown / 지금 1회 정리 vehicle).

### 재발 방지 배선
브라우저 러너가 없어(각 `.mjs` 개별 실행) 중앙 teardown 지점이 없다. **make 타깃을 재사용 teardown**
으로 삼는다 — 브라우저 샷 배치 후 `make sweep-debris-apply` 1회로 그 세션의 산물을 정리. (`_fixture.mjs`
exit마다 전-DB 스윕은 과중·중복이라 배제 — 유저는 이미 exit에서 지워짐.)

## 실행 순서
1. `sweep_debris.py` 작성(dry-run 기본·--apply·이중 가드·카운트 측정).
2. Makefile 타깃 2개 추가.
3. **dry-run으로 53 에이전트 + 딸린 잔해가 정확히 잡히는지 확인**(seed 5·실 데이터 불가침 단언).
4. `--apply`로 **지금 삭제**(사용자 승인) → 삭제 후 카운트 재측정(에이전트 5·seed만 잔존).

## OUT(스코프 밖)
- 일회용 DB per run(옵션 a)·테스트별 finally DELETE(옵션 b) — 사용자가 스윕 방식 선택. 필요 시 후속.
- mem0_memories·personas 자체 테스트 잔재 — 에이전트 FK 없음, 별개(이번은 에이전트 서브트리만).
- mockData.ts 死배열 = 스펙 305(별도).

## 검증
- **dry-run 시맨틱**: 화이트리스트 프리픽스 매칭이 53 전량 잡고 seed 5는 0 매칭(실측 카운트로 단언).
  스크립트가 실제로 아무것도 안 지움을 DB 카운트 불변으로 확인.
- **실인프라(--apply)**: 실 dev DB에 적용 후 `agents`=5(seed만)·debris 세션/메시지/버전 0·approvals
  감사행 보존 실측. seed 5 에이전트·시드 세션/컬렉션/페르소나 불변 확인.
- **적대(codex)**: 파괴·비가역 경로라 적대 리뷰 필수(learning: adversarial-review-before-destructive-ship).
  "화이트리스트 여집합"·"seed 오삭제"·"cascade가 시드/실데이터를 넘어 지우나"를 codex에 refute 요청.
