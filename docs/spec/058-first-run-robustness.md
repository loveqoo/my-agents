# 058 — 첫 실행(first-run) 견고성: 부팅 전제와 사람 진입의 갭 메우기

> 상태: **초안 v1(AI 작성 · 인간 검토 대기)**. 동기: 사용자가 외부(테스트 어려운 환경)에서
> "프로젝트를 처음 받아 실행했을 때"의 다양한 상황(DB 미설정, 테이블 없음, 유저 0, 임베딩/파운데이션
> 모델 없음 등)을 점검·보강 요청. 정적 분석 결과 *스키마·모델·시드*는 이미 견고하고, 진짜 갭은
> **부팅 전제(DB 연결)·사람 진입(첫 관리자)·셋업 문서**였다. 본 스펙은 그 갭만 메운다.

## 배경 — 점검 결과 (정적 분석)
이미 견고(변경 없음):
- **테이블 없음** → `init_db`가 `alembic upgrade head`, 실패 시 `create_all`+`stamp head`. 자동.
- **빈 DB** → `seed_if_empty`가 카탈로그별 시드(Provider MLX+Mock, Model 4종[chat/embed × 실/목],
  Agent, Collection, Session…). 자동.
- **파운데이션 모델 없음** → chat이 이름→default(is_default)→없으면 **friendly 400**.
- **임베딩 모델 없음** → `mem_cfg=None`으로 메모리 **graceful 비활성**, RAG는 게이트(048).
- **미로그인** → `AuthGate`/`LoginScreen`.

갭(본 스펙 대상):
- **G1 DB 미설정/다운** → `alembic` throw→catch→폴백 `engine.begin()`이 *또* throw(미캐치)→lifespan
  크래시. 운영자는 raw asyncpg 트레이스만 본다(원인·조치 불명). 또한 `create_all` 폴백은
  `CREATE EXTENSION vector`를 안 해서, 확장 없는 postgres에선 Vector 컬럼 생성에서 별도 크래시.
- **G2 유저 0 (ADMIN env 누락)** → `seed_admin` fail-closed skip + 공개 등록 라우터 의도적 미마운트
  → **락아웃**. 복구 경로(`tests/_provision_super.py`)가 tests/에 숨어 있어 신규 운영자가 모른다.
  경고 로그 한 줄만 남는다.
- **G3 셋업 문서 없음** → 루트 README/런북 부재. `.env.example`만 존재.
- **G4 기본 모델 외부의존** → 기본 chat=MLX(is_default)라 MLX 서버 없으면 첫 채팅이 곧장 실패.
  무외부 mock 모델이 시드돼 있으나 운영자가 전환법을 모른다.

## 설계

### G1 — DB 프리플라이트 + 명확한 에러 + 폴백 확장 패리티 (db.py)
- `init_db` 진입 시 **연결 프리플라이트**: 가벼운 `engine.connect()`(또는 `SELECT 1`)를
  먼저 시도. `OperationalError`/연결거부면 **명확한 다국어 친화 메시지**로 로깅하고
  `RuntimeError`(짧은 한 줄)로 재발생 → uvicorn 로그가 트레이스 벽 대신 조치를 보여준다.
  메시지: `DATABASE_URL` 값, "postgres 미기동? `docker compose up -d postgres` 후 재시도" 안내.
- 프리플라이트 통과(=DB 도달 가능) 후에만 `alembic upgrade` → 실패 시 `create_all` 폴백. 이러면
  폴백의 `engine.begin()` 이중 throw가 구조적으로 사라진다(DB 도달성은 이미 보장).
- **폴백에 확장 생성 추가**: `create_all` 직전 `CREATE EXTENSION IF NOT EXISTS vector`를 멱등 실행
  (마이그레이션 `b2c3d4e5f6a7`와 패리티). pgvector는 이 플랫폼의 **하드 요구**다(코어 모델이 Vector
  컬럼을 선언, docker가 pgvector 이미지를 번들). 이미 설치된 환경(관리형 PG 포함)에선 `IF NOT EXISTS`가
  비-수퍼유저에서도 no-op이라 통과한다. **만들 수 없으면 부분 부팅으로 가리지 않고 fail-closed**:
  명확한 조치 메시지("pgvector 번들 이미지 사용 또는 수퍼유저로 CREATE EXTENSION vector 후 재기동")로
  `RuntimeError`. (적대리뷰 058 P1: `create_all`은 all-or-nothing이라 "RAG만 비활성"이 불가능하고,
  Vector 테이블만 빼고 만들면 head 스탬프와 엮여 "나중에 pgvector를 고쳐도 rag_chunks가 영영 안
  생기는" 더 큰 함정이 된다. 또렷한 실패가 침묵하는 부분 스키마보다 낫다.)
- 검증: 단위 — 프리플라이트가 연결예외 모킹 시 명확 메시지 RuntimeError; 폴백 경로가 확장 SQL을
  발행(가짜 conn 캡처 또는 inspect 소스 단언).

### G2 — 첫 관리자 부트스트랩 경로 (콘솔 커맨드 + 시작 경고 강화)
- **회복 커맨드 승격**: `tests/_provision_super.py` 로직을 1급 모듈 `api.bootstrap_admin`로 승격(또는
  `python -m api.bootstrap_admin`). env(ADMIN_EMAIL/PASSWORD) 또는 인자로 superuser 멱등 생성. 락아웃
  복구·초기 시드 둘 다 이 한 경로로. (fail-closed 유지 — 자동 빈 관리자/공개 등록은 *도입 안 함*.)
- **시작 경고 강화(노이즈 억제)**: `seed_admin`이 env 누락으로 skip할 때, **유저 수가 0인 경우에만**
  눈에 띄는 멀티라인 경고로 정확한 복구 커맨드를 출력(관리자가 이미 있으면 조용히). 0 유저 판정은
  seed_admin 안에서 count로.
- 검증: 단위 — bootstrap_admin이 모킹 매니저로 UserCreate 호출(멱등: 이미 있으면 no-op);
  seed_admin이 env無+유저0에서 강화 경고를 내는지(로그 캡처), 유저>0에선 조용한지.

### G3 — 운영 시작 문서 (루트 README)
- 루트 `README.md` 초안: 처음 받아 실행하는 최소 절차 —
  1) `cp .env.example .env` + 필수값(`DATABASE_URL`·`ADMIN_EMAIL/PASSWORD`·`API_AUTH_TOKEN`) 교체
  2) `docker compose up -d postgres` (pgvector 번들)
  3) api 기동(uvicorn) → `init_db`가 자동 마이그레이션·시드
  4) 관리자 로그인. 락아웃 시 `python -m api.bootstrap_admin` 회복.
  5) 모델: 기본 chat=MLX. MLX 없으면 admin에서 기본을 **Mock LLM**으로 바꾸면 무외부 동작(G4 참조).
- **docs/는 인간 영역**이라 README도 *초안만* 작성하고 인간 검토 요청(루트 README는 운영 문서지만
  같은 검토 규율 적용). 사용자가 이미 본 작업에 명시 포함했으므로 초안 작성은 승인됨.

### G4 — 기본 모델 외부의존 완화 (보수적: 문서 + 에러 안내, 기본값 불변)
- **기본값은 MLX 유지**(실제 의도 — 데모 기대·verify 스크립트 가정 보호). 대신:
  - chat의 모델 연결 실패(MLX 도달 불가) 시 **에러에 전환 힌트**: "기본 모델 'MLX'에 연결 불가 —
    MLX_BASE_URL 확인 또는 admin에서 기본을 'Mock LLM'으로 전환". (이미 friendly 400 경로 옆에 보강.)
  - README G3에 동일 안내.
- **대안(미채택, 리스크 절에 기록)**: seed에서 mock-llm을 `is_default=True`로 → 무외부 즉시 채팅.
  단 응답이 canned라 "왜 가짜 답?" 혼란 + verify/seed 가정 변경 리스크. 보수적으로 보류, 사용자가
  원하면 전환.

## 완료 조건(검증) — 전부 라이브 인프라 없이 정적/단위
1. **G1 단위**: 프리플라이트가 연결예외에서 명확 RuntimeError(메시지에 DATABASE_URL·docker 힌트);
   폴백 경로가 `CREATE EXTENSION IF NOT EXISTS vector` 발행; 폴백 진입이 *DB 도달 후*로 한정됨.
2. **G2 단위**: `api.bootstrap_admin` 멱등 생성(모킹); `seed_admin` env無+유저0=강화 경고, 유저>0=조용.
3. **G3**: 루트 README 존재·절차 5단계·복구 커맨드·모델 전환 안내 포함(문서 린트/존재 단언).
4. **G4 단위**: chat 모델 연결 실패 메시지에 'Mock LLM' 전환 힌트 문자열 포함.
5. **타자 적대 검증(필수)**: codex — (a) 프리플라이트가 *진짜* DB-down만 잡고 정상 부팅 회귀 없게,
   (b) bootstrap_admin이 escalation(050: 기존 실계정 super 승격) 안 여는지, (c) 강화 경고가 유저>0에서
   안 새는지, (d) 폴백 확장 추가가 권한부족에서 부팅 막지 않는지.
6. 무회귀: 기존 verify_* (seed/auth 관련) 그대로 통과.

## 리스크 / 주의
- **프리플라이트 회귀**: 정상 부팅을 느리게/막지 않게 — 가벼운 `SELECT 1` 1회·타임아웃 짧게. 통합
  rung(실 DB 부팅)은 사용자 복귀 후 1회 권장(현재는 정적/단위 우선).
- **bootstrap_admin escalation(050)**: 기존 계정 이메일로 호출 시 super 승격 열지 말 것 — 신규 생성만,
  이미 있으면 no-op(승격 금지). 적대 검증 필수.
- **폴백 확장 권한**: 제약 postgres에서 CREATE EXTENSION 불가 시 — pgvector는 하드 요구라 부분 부팅으로
  가리지 않고 **명확한 메시지로 fail-closed**(적대리뷰 058 P1 반영). 부분 스키마+head 스탬프 함정 회피.
- **G4 기본값 불변 선택**: 무외부 즉시 채팅을 원하면 mock-default 대안으로 전환(별도 합의).
- **docs 인간 영역**: README는 초안 — 인간 검토 후 확정.
