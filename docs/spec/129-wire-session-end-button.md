# 129 — 세션 상세 "세션 종료" 버튼 배선 (+ 백엔드 500 수정)

## 배경 / 왜
세션 상세 드로어의 "세션 종료" 버튼이 onClick 없는 목업(128 조사에서 확인, 백로그 후속 씨앗).
백엔드 `POST /sessions/{id}/end`는 소유권 스코프(`_own_scope`, 067/070) 안에서 status를
"completed"로 바꾸고 SessionOut을 돌려준다.

**전제 정정(검증이 잡음)**: 초안은 "백엔드 완성·무변경"을 전제했으나 **실측 반증** — 이 라우트는
한 번도 실사용(e2e)된 적이 없었고, 첫 호출에서 500이 났다. `last_activity`가 `onupdate=func.now()`
**서버 생성값**이라 commit 후 만료 상태로 남고, 응답 직렬화(session_to_out)의 동기 접근이 lazy-load를
시도해 MissingGreenlet(회고 026 재발 부류). **커밋은 성공하고 응답만 실패**라 "세션은 종료됐는데
화면엔 실패"라는 거짓 실패 UX. 처방: commit 후 `await session.refresh(s)` 1줄(백엔드 수정 포함).

## 설계
- api.ts: `endSession(id) → POST /sessions/{id}/end → Session`(목록 items와 동형 응답).
- SessionsView:
  - "세션 종료" 버튼에 **Popconfirm**(비가역 상태 전이 — 실수 클릭 방지) + loading.
  - 성공: `setDetail(응답)`(드로어에 완료 상태 즉시 반영 — status가 completed면 기존 footer 조건에
    의해 종료 버튼이 사라지고 닫기만 남음) + `refreshKey++`(PagedListShell 재조회 — 목록·counts 갱신)
    + 성공 토스트.
  - 실패: 오류 메시지 표시(서버 detail 그대로).
- 소유권은 서버가 강제(_own_scope) — 프론트 추가 게이트 불요.

## 검증
- tsc. 브라우저(시드 세션으로 — **실 세션을 종료하지 않는다**): sessions 테이블에 검증용 세션 1건
  시드(status=active) → 검색으로 찾아 행 클릭 → 종료 버튼 Popconfirm 확인 → 종료 → 드로어가 "완료"
  상태로 바뀌고 종료 버튼 사라짐 + 목록 status 갱신 확인 → 시드 삭제.
- 백엔드 무변경이라 기존 verify(067/070 own-scope) 무회귀 확인만.

## 비목표 (OUT)
- running 세션의 실제 실행 중단(그래프 인터럽트) — end는 status 전이만(백엔드 기존 시맨틱 유지).
- 목록 행 단위 종료 액션 — 상세 드로어에서만(기존 UI 위치 유지).
