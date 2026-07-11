# 153 — 파라미터 개명은 "위치 호출 확인"만으론 불충분: keyword-only는 이름이 곧 계약

## 상황 (스펙 291, 2026-07-11)

ruff ARG(미사용 인자) 소거에서 미사용 파라미터를 `_` 접두로 개명했다. 지시서는 "호출부가 전부
위치 인자임을 확인했다"를 안전 근거로 걸었다. 그런데 batch 잡 3개의 시그니처가
`async def cleanup_sessions(*, dry_run: bool, run_id=None)` — **keyword-only**였고, runner는
`await job(dry_run=dry_run, run_id=run_id)`로 키워드 호출한다. `run_id → _run_id` 개명 순간
배치 실행 전체가 TypeError로 즉사하는 상태가 됐다.

## 왜 아무도 못 잡았나 (게이트 사다리의 구멍)

- **실모델 스위트 51개**: 채팅 경로만 지남 — 배치 경로 미커버.
- **ruff**: 개명 *후*가 규칙상 "올바른" 코드(ARG 소거 완료)라 초록.
- **codex 적대 리뷰**: 분할 diff 중심이라 Phase 2 개명까지 소급 안 함.
- **mypy(Phase 4 도입 첫 판)가 적발**: `Unexpected keyword argument "run_id"; did you mean
  "_run_id"?` — 호출-시그니처 정합은 타입체커만 본다.

부수 실수: 이 실패(verify_038)를 stash 차등으로 "기존 부채"라 오분류했다. stash는 미커밋만
걷어내고 **이미 커밋된 회귀는 양쪽에 남아 "전후 동일 실패"로 위장**된다. 재검증은 스펙 시작 전
커밋 worktree로 — 038=회귀, 036/056=진짜 부채로 갈렸다.

## 처방

1. **개명 전 3체크**: ① 위치 호출만인가? ② `*` 뒤(keyword-only)인가? ③ `**kwargs`로 릴레이되는가?
   — ②③은 이름이 API다: 개명 금지하거나 호출부를 같은 변경에서 동시 수정.
2. 미사용이지만 이름을 못 바꾸는 계약 인자는 `# noqa: ARG001 — <누가 키워드로 호출>` 사유 부착.
3. **타입체커를 검증 사다리에 상설** — 시그니처 정합 rung은 mypy가 유일하게 덮는다.
4. 차등 판정 기준점은 "스펙 시작 전 커밋"의 worktree(stash 아님).

관련: [[verification-ladder-three-rungs]](rung 비겹침), retrospect 266.
