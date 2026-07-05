# 181 — 승인 내역(감사) 화면

## 배경·문제
승인 화면은 **대기(pending)만** 보여준다. 이미 승인/거부한 건을 볼 곳이 없어, 사용자가 "내가 뭘
승인했는지" 되짚을 수 없다(실사용 불편 제보). 게다가 resolve는 **status만 갱신**하고 *언제·누가*
처리했는지는 저장하지 않아, 지금 데이터로는 감사 이력을 만들 수 없다.

## 목표
승인 화면에 **대기 중 / 처리됨** 두 탭. 처리됨은 승인·거부된 건을 **결과·처리 시각·처리자(본인/관리자)**
와 함께 최근순으로. 소유 스코프는 기존대로(일반 유저=자기 것, 관리자=전체 — listApprovals 이미 반영).

## RBAC 경계(체크리스트 — 유저별 데이터 O)
- **입구**: 이력은 **읽기 전용**(list만). resolve(쓰기)는 기존 입구 그대로. 새 쓰기 입구 없음.
- **읽기 소유 스코프**: `list_approvals`가 이미 `_own_scope`로 `user_id==own`을 WHERE에 밀어 남의 것을
  로드조차 안 함(무변경). 이력 탭도 같은 엔드포인트라 자동 상속.
- **존재 비노출**: 볼 수 없는 행은 애초 SELECT에서 제외(404 불필요 — 목록이라 미노출).
- **처리자 표기**: 원 요청자(user_id)와 처리자(resolved_by) 비교로 self/other 파생 — 서버에서 계산해
  `resolvedBySelf`(bool)만 노출(원 UUID 미노출).

## 설계
**백엔드**
1. `Approval` 모델: `resolved_at`(DateTime tz, nullable) + `resolved_by`(String80, nullable=처리자 user_id) 추가.
2. 마이그레이션(head `a177b3c4d5e6` 뒤): 두 컬럼 nullable 추가(기존 행 NULL=레거시, 하위호환).
3. `resolve_approval`: 원자적 UPDATE의 `.values`에 `resolved_at=func.now()`, `resolved_by=str(principal.id)`
   함께 박음(status와 같은 트랜잭션 — 별도 write 입구 안 늘림).
4. `ApprovalOut`+serializer: `resolvedAt`(iso), `resolvedBySelf`(bool|None; resolved_by==user_id면 True,
   다르면 False, 미처리 None) 노출.

**프론트**
5. `ApprovalsView`: 상단 Segmented [대기 중 N] / [처리됨]. 대기 중=기존 resolve 카드. 처리됨=
   `listApprovals()`(전체) 중 status!=pending을 최근(resolvedAt) 순으로, **읽기 전용 카드**(결과 배지
   승인/거부·처리 시각·본인/관리자 태그·무엇을 요청했는지). 사이드바 배지는 pending만(무변경).
6. `mockData.Approval`: `resolvedAt?`, `resolvedBySelf?` 타입 추가.

## 검증(완료 조건)
- **단위/통합**: resolve 후 그 Approval에 resolved_at·resolved_by가 박히고, 재조회 시 ApprovalOut에
  resolvedAt·resolvedBySelf 정확(self 승인→True, admin이 남의 것 승인→False).
- **마이그레이션 안전(비가역)**: 적용 후 단일 head·중복 리비전 0·기존 행 NULL 하위호환. 헤더-only
  그래프 검증(스펙 177 교훈).
- **e2e(타자)**: 인라인/메뉴로 승인→승인 화면 **처리됨 탭**에 그 건이 결과 배지+처리 시각+본인 태그로
  뜸. 대기 중 탭엔 없음(이동됨).

## 단계
- **P1**: 백엔드(모델+마이그레이션+resolve 기록+ApprovalOut).
- **P2**: 프론트(처리됨 탭).
- **P3**: 검증(단위+마이그레이션 그래프+e2e).
