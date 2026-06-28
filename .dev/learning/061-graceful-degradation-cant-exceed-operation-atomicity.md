# 061 — graceful degradation은 그것을 구현하는 연산의 원자성을 넘지 못한다

## 언제 적용
"X가 없으면 그 부분만 비활성, 나머지는 동작"식 **부분 열화(graceful degradation)**를 설계할 때 —
특히 그 열화를 *하나의 원자적 연산*(DDL `create_all`, 단일 트랜잭션, 일괄 배포, all-or-nothing API)
위에 얹을 때. 선행조건(확장/권한/리소스) 에러를 try로 잡으면 "우아하게 넘어간다"고 착각하기 쉽다.

## 명제
선행조건 에러를 잡는 것과, 그에 *의존하는* 연산이 부분 성공하는 것은 별개다. 의존 연산이 원자적이면
(create_all은 한 테이블이 막히면 통째 실패) "일부만 비활성"은 **구현 불가능한 주장**이다 — catch는
선행 단계에서 멈추지만, 다음 단계가 같은 결함으로 *다시* 터져 전체가 무너진다. 부분 열화가 실재하려면:
(1) 구현 연산을 실제로 부분 실행할 수 있어야 하고, (2) 그 부분 실행이 *더 나쁜 하류 함정*을 만들지
않아야 한다. 둘 중 하나라도 깨지면 부분 열화는 환상이고, **정직한 fail-closed + 또렷한 조치 메시지**가
옳다.

## 표본 (스펙 058 G1, codex P1)
`init_db` 폴백이 `CREATE EXTENSION IF NOT EXISTS vector`를 try로 감싸고 "실패해도 RAG만 비활성"이라
적었다. 하지만 바로 뒤 `Base.metadata.create_all`이 `rag_chunks`의 `Vector` 컬럼을 만들다 *다시* 터지고
바깥 except가 `RuntimeError`로 부팅을 막는다 — `create_all`은 all-or-nothing이라 "부분 비활성"이 처음부터
불가. happy-path(pgvector 있는 docker)는 초록이라 **자가검증이 구조적으로 못 봄**, codex(타자)가 잡음.

"Vector 테이블만 빼고 create_all" 우회는 조건 (2)를 깬다: 빼고 만들면 `stamp head`와 엮여 *나중에
pgvector를 고쳐 재기동해도* alembic이 head로 스탬프돼 `rag_chunks`를 영영 안 만드는 **더 큰 함정**.
그래서 부분 부팅을 버리고, pgvector를 하드 요구로 두고 fail-closed(번들 이미지/수퍼유저 안내)로 정직화.
이미 설치된 환경은 `IF NOT EXISTS`가 비-수퍼유저에서도 no-op이라 그대로 통과 — 진짜 못 만드는 경우만 막음.

## 처방
- 부분 열화를 적기 전에 **그 열화를 실행하는 연산의 원자성**을 먼저 본다. 원자적이면 "일부만"은 거짓말.
- catch 위치와 *실패가 실제로 터지는 위치*를 분리해서 본다. 선행 단계 catch가 의존 단계 실패를 막지 못함
  ([[installed-guard-isnt-covering-guard]]의 "검사지점≠부수효과 발생지점"과 같은 골격).
- 부분 실행이 가능해 보여도 **하류 상태(스탬프/버전/인덱스)와의 정합**을 점검 — 부분 스키마가 복구
  경로를 막으면 침묵하는 손상이다. 또렷한 실패 > 침묵하는 부분 성공.
- 이 불일치는 happy-path 초록이라 **타자 적대 필수**([[adversarial-review-before-destructive-ship]]):
  "보장 목록의 여집합"(= 내가 상상 못 한 실패경로)을 시켜라.
- 회고/스펙의 *주장*을 코드 동작과 대조해 둘을 정직하게 맞춘다(주장 vs 구현 원자성 = drift의 한 종류,
  [[move-breaks-references-both-directions]]·[[consolidation-doesnt-inherit-retired-path-behaviors]]의
  "위상 바뀌면 보장 자동 안 따라옴" 가족).
