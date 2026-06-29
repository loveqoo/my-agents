# 048 — MLX를 env에서 떼고 Mock LLM을 기본으로 (스펙 059 회고)

## 한 줄
"mlx 설정이 왜 env에 있어? 프로바이더에서 추가하게 해줘"라는 한 줄 요청이, env 한 블록 삭제가
아니라 **정상 fresh-install이 이미 깨져 있다는 발견**으로 번졌다. 진짜 작업은 "기본값을 세우는
*두 부팅 경로*를 같은 작동 상태로 수렴시키기"였다.

## 무엇을 했나
- **D1 마이그레이션 `c9d0e1f2a3b4`**: alembic 경로(정상 부팅)에서 `mock-llm`을 기본 chat으로 승격
  (단 chat 기본이 없을 때만 — no-clobber), `mock-embed` 멱등 삽입, provider를 'Mock LLM'/kind=mock으로 정규화.
- **D2 seed.py**: `CHAT_MODEL_NAME` `qwen3.6-35b`→`mock-llm`, Provider 시드 블록을 Mock 하나로 축소
  (create_all 폴백 경로 전용). 두 모델(mock-chat 채팅·mock-embed 임베딩) is_default 시드.
- **D3 .env.example / D6 README**: MLX_* env·표 행 제거, "기본=Mock·실모델은 Provider UI" 안내(문서는 초안·인간검토).
- **D4 agent 패키지**: `MLX_*` env → 벤더무관 `MODEL_*`, `local-mlx` 기본 → `mock-llm`(models.py·schemas.py).
- **D5 chat.py**: 연결실패 힌트를 "기본은 MLX"에서 "Mock LLM으로 되돌리기"로 재프레이밍(기본이 이제 Mock이므로).
- **검증**: verify_059(31단언 정적/단위 ALL PASS), verify_058 재실행(chat 힌트 무회귀 확인), codex 적대 리뷰(a/b/c/d 전부 HANDLED).

## 핵심 통찰 — 가장 값진 것

### 1. 기본값은 상수가 아니라 *모든 부팅 경로의 수렴 상태*다 (learning 062)
요청은 "기본을 Mock으로"였지만, **기본값이 세워지는 경로가 둘**이었다:
- **경로 A(정상)**: `alembic upgrade head` → f4a5가 mock-llm INSERT, a1b2c3가 provider 정규화 →
  providers 행 존재 → seed.py의 `if _empty(Provider)`가 **False라 스킵**. 즉 seed로는 기본이 안 선다.
- **경로 B(폴백)**: create_all + `stamp head`(데이터 insert 없이 적용표시) → providers 행 없음 →
  seed Provider 블록 **실행**.

`CHAT_MODEL_NAME` 상수만 고쳤다면 경로 B만 고쳐지고 **경로 A(정상 fresh-install)는 여전히
기본 chat·임베딩 모델이 없는 깨진 상태**였다. seed의 per-table `_empty` 게이트가 마이그레이션
경로에서 *죽어 있어서*, 그 경로의 기본값은 오직 마이그레이션만 세울 수 있었다. → D1과 D2가
**같은 관측 상태**(provider 이름/kind, is_default, model_id)로 수렴하도록 둘 다 작성.

### 2. Context 단계의 고고학이 작업의 진짜 범위를 바꿨다
표면 요청("env 제거")을 그대로 실행했다면 깨진 fresh-install을 못 봤다. 마이그레이션 체인을
거슬러 읽고(`f4a5`→`a1b2c3`) init_db 흐름을 따라가 **두 경로가 분기한다**는 걸 발견한 것이
이 작업의 분기점이었다. learning 046(seed drift: 코드 옳아도 옛 영속/마이그레이션 경로는 깨짐)이
바로 이 클래스 — 정확히 그 패턴을 다시 만났고, 이번엔 *기본값 establishment* 축에서.

### 3. no-clobber — 신호를 바꾸지 말고 빈 곳만 채워라 (learning 046 재적용)
업그레이드하는 기존 설치가 이미 실모델을 기본으로 *의도적으로* 골랐을 수 있다. 마이그레이션은
"chat 기본이 하나도 없을 때만" mock 승격 — 기존 default를 절대 덮지 않는다. mock-embed도
"임베딩 기본이 없을 때만" default. **빈 곳을 채우되 의도적 신호는 보존.**

## 검증 — 타자 우선, 자가검증 지양
- verify_059는 정적/소스 단언(라이브 인프라 불필요 — 사용자가 외부라 라이브 검증 어려움).
- **codex 적대 리뷰**가 a/b/c/d(no-clobber·두경로수렴·RAG무회귀·댕글링)를 전부 명시적 HANDLED로
  확인하고, 잔여 엣지 1건 적발: mock-embed 멱등이 이름-only라 *손상된* 업그레이드 DB(이름은 같은데
  임베딩 모델이 아닌 행)는 복구 못함. **두 fresh-install 경로 밖**이고 우리 시드/마이그레이션이
  그 상태를 안 만들므로 **수용 가능한 한계로 문서화**(learning 046 — 신호 너머 과설계 금지).
- ~~통합 rung은 사용자가 다른 곳에서 수행~~ → **2026-06-29 직접 실측으로 채움**(사용자 "다시 한 번
  first-run 준비 확인" 요청). 던짐용 pgvector 컨테이너(5433)에 빈 DB 둘을 만들어 **실제 `init_db()`로
  경로 A**(정상 alembic)·**폴백 분기로 경로 B**(create_all)를 부팅, 관측 상태를 덤프·비교:
  - 두 경로가 **완전히 동일**한 상태로 수렴 — providers([Mock LLM/mock]), models(mock-llm/mock-chat
    chat default·mock-embed/mock-embed embedding default), 에이전트 3개 mock-llm 참조·**댕글링 0**,
    컬렉션 4개 전부 mock-embed 바인딩(부팅이 컬렉션 시드에서 안 죽음). 15단언 ALL PASS.
  - **end-to-end 스모크**: fr_patha로 API 기동 후 `/_remote/v1/chat/completions`(mock-chat)가
    결정적 답변, `/_remote/v1/embeddings`(mock-embed)가 1024차원(=RAG_EMBED_DIMS) 반환 → 시드된
    기본 모델이 *실제로* 동작.
  - 자산화: `tests/verify_059_integration.py`(단일 DB pass/fail + 두 경로 하니스 문서화). 기존 dev
    컨테이너는 OS glibc 변경 전 볼륨이라 template1 collation 불일치로 CREATE DATABASE가 막혀
    던짐용 컨테이너를 썼다(이 환경 함정도 파일에 기록). dev 컨테이너는 무손상.
  - **결론: first-run 준비됨** — 정적+적대(지난 턴)에 더해 통합 rung까지 셋 다 green. 검증사다리
    완성(메모리 'verification-ladder: three rungs' — rung2가 seed drift·요청간 글루를 잡는 그 rung).

## 다음에 적용할 것
- "기본값을 X로" 류 요청은 **그 기본값이 세워지는 모든 경로를 먼저 열거**하고 각 경로가
  X를 세우는지 확인한다(상수 하나로 끝나는 일이 드물다). → learning 062.
- 두 코드경로가 "같은 상태"를 *다른 메커니즘*으로 만들면(마이그레이션 data-insert vs seed),
  관측 가능한 상태(이름·플래그·id)를 명시 단언해 수렴을 못박는다.
