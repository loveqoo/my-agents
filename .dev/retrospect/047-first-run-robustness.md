# 047 — 첫 실행(first-run) 견고성 회고 (스펙 058)

> 동기: 사용자가 외부(테스트 어려운 환경)에서 "프로젝트를 처음 받아 실행했을 때"의 다양한 상황(DB
> 미설정·테이블 없음·유저 0·임베딩/파운데이션 모델 없음 등)을 점검·보강 요청. 라이브 인프라 없이
> 정적/단위 + 타자(codex) 적대 검증만으로 진행.

## 무엇을 했나
정적 분석으로 먼저 **이미 견고한 것**과 **진짜 갭**을 갈랐다. 스키마(alembic→create_all 폴백)·시드
(`seed_if_empty`)·모델 부재(friendly 400)·임베딩 부재(메모리 graceful 비활성)·미로그인(LoginScreen)은
이미 견고. 갭은 *부팅 전제*(DB 연결)·*사람 진입*(첫 관리자)·*셋업 문서*에 몰려 있었다.

- **G1 DB 프리플라이트**: `init_db` 진입에 `SELECT 1` 프리플라이트 추가 → DB 미도달 시 raw asyncpg
  트레이스 대신 마스킹된 DSN + `docker compose up -d postgres` 조치를 보여주고 부팅 중단. 부수효과로
  폴백 `engine.begin()`의 *이중 throw*가 구조적으로 사라짐(여기 왔으면 DB는 도달 가능).
- **G2 첫 관리자 부트스트랩**: tests/에 숨어있던 복구 로직을 1급 `python -m api.bootstrap_admin`로 승격.
  **신규 생성만**·기존 계정 승격 거부(learning 050 escalation 가드). `seed_admin`은 유저 0일 때만
  시끄러운 복구 안내(노이즈 억제).
- **G3 루트 README 런북**: 처음 받아 실행하는 5단계 + 락아웃 복구 + 모델 전환 안내(초안, 인간 검토).
- **G4 모델 연결 힌트**: chat 스트림 except가 연결-지문 감지 시 'Mock LLM' 전환 힌트 첨부(제어흐름 불변).

## 타자(codex) 적대 검증이 잡은 것 — P1
스펙은 G1 폴백에서 "CREATE EXTENSION 실패해도 RAG만 비활성, 나머지는 동작"이라 적었고 코드도 확장 SQL을
try로 감쌌다. codex가 **스펙 주장 vs 코드 동작 불일치**를 적발: 확장 실패는 잡아도 바로 뒤 `create_all`이
`rag_chunks`의 Vector 컬럼을 만들다 *다시* 터지고, 바깥 except가 `RuntimeError`로 부팅을 막는다. DDL인
`create_all`은 **all-or-nothing**이라 "부분 비활성"이 애초에 불가능했다.

"Vector 테이블만 빼고 만들면 되지 않나?" — 더 큰 함정이었다. 빼고 만들면 `stamp head`와 엮여 *나중에
pgvector를 고치고 재기동해도* alembic이 이미 head로 스탬프돼 `rag_chunks`를 영영 안 만든다. 침묵하는
부분 스키마가 또렷한 실패보다 나쁘다. pgvector는 이 플랫폼의 **하드 요구**(코어 모델이 Vector 컬럼 선언,
docker가 번들)이므로, 만들 수 없으면 가리지 말고 **명확한 메시지로 fail-closed** 하도록 코드+스펙을
정직하게 맞췄다(이미 설치된 pgvector면 `IF NOT EXISTS`가 비-수퍼유저에서도 no-op이라 관리형 PG도 통과).

P2 2건(프리플라이트가 연결 외 범주도 포괄=원본오류 로깅으로 완화 / `_model_error_hint`의 timeout 마커
오탐 가능=힌트 첨부만, 제어흐름 불변)은 advisory로 근거를 코드에 남기고 보류. (b)(c)는 No finding —
escalation 가드·유저0 게이팅 견고 확인.

## 핵심 교훈 (→ learning 061)
**graceful degradation 주장은 그것을 구현하는 연산의 원자성을 넘지 못한다.** 선행조건 에러(CREATE
EXTENSION)를 잡아도, 그에 의존하는 *원자적* 연산(create_all 같은 DDL)은 통째로 실패한다. "일부만
비활성"이 실재하려면 구현 연산을 실제로 부분 실행할 수 있어야 하고, 그게 더 나쁜 하류 함정(head 스탬프
드리프트)을 안 만들어야 한다. 둘 다 아니면 **정직한 fail-closed + 또렷한 조치 메시지**가 답이다. 그리고
이 "주장 vs 구현 원자성" 불일치는 happy-path가 초록이라 자가검증이 구조적으로 못 본다 — 타자 적대 필수.

## 검증
- 정적/단위: `tests/verify_058_first_run_robustness.py` (G1 마스킹·프리플라이트 RuntimeError·폴백
  fail-closed / G2 입력검증·escalation 소스단언·유저0 게이팅 / G4 연결지문 감지·오탐 배제·except 사용).
  라이브 DB/MLX 불필요(engine 가짜 주입·DB 이전 분기만 실행·헬퍼 직접 호출). ALL PASS.
- 타자 적대: codex review — P1 1건 적발·해소, P2 2건 advisory 보류, escalation/게이팅 No finding.
- 통합 rung(실 DB 부팅·기존 seed/auth verify_*)은 사용자 복귀 후 1회 권장(현재 정적/단위 우선).
