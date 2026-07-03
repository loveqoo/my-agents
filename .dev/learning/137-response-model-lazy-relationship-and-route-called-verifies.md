# 137 — 응답 모델 필드명이 ORM lazy 관계와 겹치면 지뢰 + verify는 라우트를 직접 불러라

## 트리거
(a) pydantic 응답 모델(from_attributes)로 ORM 객체를 변환하는 엔드포인트 — 특히 모델 필드명이 ORM의
relationship 이름과 겹칠 때. (b) 신규 엔드포인트의 verify를 "DB 상태 확인"으로만 쓸 때.
(c) 백그라운드 잡(asyncio.create_task) 설계.

## 사례 (스펙 137)
- **500 버그**: `RunDetailOut.model_validate(run)` — results 필드가 ORM `EvalRun.results`(lazy 관계)와
  동명이라 from_attributes가 비동기 밖 lazy load 시도 → MissingGreenlet. **129(commit 후 onupdate
  만료)·026(rollback 후 만료)에 이은 세 번째 변종** — 공통 뿌리: "비동기 세션 밖에서 ORM 속성을
  동기 접근". 안전 패턴: **관계 필드가 없는 베이스 모델로 추출 후 명시 구성**.
- **왜 단위가 못 잡았나**: verify가 결과를 DB로 직접 조회했지 라우트 함수(get_run)를 안 불렀다 —
  직렬화 계층 크래시는 라우트를 불러야만 드러난다. e2e(브라우저)가 잡았고, 그 후 라우트 직접 호출
  핀(C4d)을 추가. **신규 엔드포인트마다 verify에서 라우트 함수를 최소 1회 직접 호출**이 규칙.
- **백그라운드 잡 3종 세트**(codex): asyncio.create_task는 재시작을 못 넘김 → ①startup 좀비 sweep
  (running 잔류→error 박제), ②중복 실행 게이트(같은 대상 running이면 409 — 더블클릭=실모델 N배 비용),
  ③입력 크기 상한(프롬프트로 들어가는 필드·JSONB 배열 개수·인자 길이).
- 곁다리: 관측 union — 같은 의미의 행위(도구 사용)가 시스템 안에서 형태가 다르면(그래프 노드 vs
  calls_sink vs 플래그) 채점/관측 계층에서 canonical 토큰으로 통일해야 소비자가 형태를 몰라도 된다.

## 다음에 할 일
- 응답 모델 설계 시 ORM 관계명과 필드명 충돌 점검(겹치면 베이스 추출+명시 구성).
- verify 작성 체크: 모든 신규 라우트 함수 직접 호출 1회 이상.
- create_task 기반 잡엔 sweep+게이트+상한 3종 세트.
