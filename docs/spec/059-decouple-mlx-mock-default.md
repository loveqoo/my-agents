# 059 — MLX를 env에서 분리하고 Mock LLM을 기본으로 (Provider는 UI에서 추가)

> 상태: **초안 v1(AI 작성 · 인간 검토 대기)**. 동기: 사용자가 "MLX 설정이 왜 env에 있나 —
> MLX는 필수가 아니고 Provider(admin UI)에서 추가하도록 해야 한다"고 지적. 점검 중 더 큰
> 잠재 결함이 드러남: **정상 alembic 경로의 fresh 설치가 이미 깨져 있다**(아래 배경).

## 배경 — 점검 결과 (정적 분석 + 마이그레이션 고고학)

### 사용자가 지적한 표면 문제
- `.env.example`에 `MLX_BASE_URL/API_KEY/MODEL`이 1급 설정으로 박혀 있고, `seed.py`가 이를 읽어
  **MLX provider + `qwen3.6-35b`(chat, is_default=True) + `multilingual-e5-large`(embed, is_default=True)**를
  시드한다. Provider는 admin UI에서 추가하는 1급 엔티티(스펙 035)인데 MLX만 env로 특별 취급 = 모순.

### 점검 중 드러난 더 큰 결함 (seed drift, 회고 046/057 계열)
`init_db` = preflight → `alembic upgrade head`(정상 성공) → `seed_if_empty`. 그런데:
- 마이그레이션 `f4a5`가 mock-llm을 INSERT → `a1b2c3`(provider 정규화)가 그걸 **provider 행으로 승격**.
- 그 결과 fresh DB에서 head까지 올리면 **Provider 테이블이 비어있지 않다** → `seed.py`의
  `if _empty(Provider)` 게이트가 False → **Provider/Model 시드 블록 전체가 스킵된다**.
- 따라서 **정상 alembic 경로의 fresh 설치 결과**: 모델은 mock-llm 하나(`is_default=False`),
  **기본 chat 모델 없음**, **임베딩 모델 없음**, 시드 에이전트는 없는 `qwen3.6-35b` 참조(dangling),
  컬렉션 시드는 빈 임베딩 목록에 `embs[0]` 접근 → IndexError 위험.
- MLX provider는 **create_all 폴백 경로에서만** 시드됐다. 두 부팅 경로가 서로 다른 결과를 낸다.
- 어떤 마이그레이션도 MLX/qwen을 INSERT하지 않는다(모델 데이터 insert는 `f4a5` mock-llm·
  `c1d2e3` memory_types뿐) → MLX 제거는 seed.py만 고치면 되지만, **기본값을 alembic 경로에서도
  세우려면 마이그레이션이 필요**하다(seed Provider 블록이 그 경로에선 죽어 있으므로).

## 설계 — 두 부팅 경로 모두에서 "Mock 기본 + MLX는 UI 추가"가 참이 되게

사용자 결정(확인 완료): **(1) 기본 채팅 모델 = Mock LLM**(외부 의존 0, 응답 canned), **(2) packages/agent
패키지도 함께 정리**.

### D1 — 새 마이그레이션: alembic 경로의 기본값 정직화 (next head)
- `<rev>_mock_default_and_embed`: head 이후 상태를 **작동하는 기본**으로 만든다.
  - mock-llm chat 모델 `is_default=True`로 — **단, 이미 다른 chat 모델이 default면 건드리지 않는다**
    (기존 설치가 의도적으로 고른 실 모델 default를 클로버하지 않음 = 회고 046 seed-drift 교훈의 역).
    즉 "default chat 모델이 하나도 없을 때만" mock-llm을 default로 승격.
  - mock-embed 임베딩 모델을 멱등 삽입(이름 존재 시 skip) + 임베딩 default가 없으면 default로.
    → 임베딩 모델 부재(컬렉션 바인딩 크래시)·RAG 게이트(스펙 048) 안전.
  - downgrade는 가역(default 플래그 원복·mock-embed 제거, 이름 소유 정책 — f4a5와 동일 철학).
- 이로써 fresh alembic 설치가 **기본 Mock chat + Mock embed**로 곧장 작동.

### D2 — seed.py: create_all 폴백 경로를 D1과 일치 + MLX 제거
- Provider 시드 블록에서 **MLX provider·qwen·e5 제거**. **Mock provider만** 시드:
  - mock-llm (chat, **is_default=True**), mock-embed (embedding, **is_default=True**).
- `CHAT_MODEL_NAME = "qwen3.6-35b"` → **`"mock-llm"`**: 시드 에이전트(Research/Secretary/코드/번역)가
  존재하는 모델을 가리키게.
- env 읽기(`MLX_BASE_URL` 등) 제거. 컬렉션 시드는 mock-embed(default)에 바인딩.

### D3 — .env.example: MLX_* 블록 제거
- `MLX_BASE_URL/API_KEY/MODEL` 3줄 삭제. (MLX는 이제 admin Provider UI에서 추가.)
- 나머지(DATABASE_URL·ADMIN_*·API_AUTH_TOKEN·AUTH_COOKIE_SECURE)는 유지.

### D4 — packages/agent: MLX-특화 env를 provider-무관 이름으로
- CLI 단독 테스터(`main()`)가 읽는 `MLX_BASE_URL/API_KEY/MODEL` → 일반 `MODEL_BASE_URL/API_KEY/MODEL_ID`로
  rename(특정 벤더 색 제거). docstring("로컬 MLX")도 중립화. 기본 base_url은 mock 엔드포인트로 둬
  무외부에서도 동작하게 검토(또는 localhost 일반 유지).
- `models.py:209`/`schemas.py:227`의 `default="local-mlx"`(코드 에이전트 자기보고 모델 라벨)는
  표시용 cosmetic — 테스트 참조 확인 후 중립 라벨로(또는 범위 외로 유지, 검토 시 결정).

### D5 — chat.py G4 힌트 재서술
- 기본이 Mock(무외부 동작)이 됐으므로 힌트 의미가 뒤집힌다: 이제 **사용자가 추가한 실 모델(MLX/OpenAI 호환)**
  연결 실패 시 도움. "추가한 모델 서버에 연결 실패(base_url=…) — 서버/주소 확인. 기본 Mock LLM으로
  되돌리면 무외부 동작." 제어흐름·연결지문 감지 로직 불변, 문구만.

### D6 — README 갱신 (스텝 5 + 표)
- 스텝 5 "MLX 없이 바로 시험" → "**기본 채팅 모델은 Mock LLM**(무외부, 응답 canned). 실 모델은
  admin Provider UI에서 추가(예: MLX/OpenAI 호환)하고 기본 전환." 표의 MLX_* 행 제거.
- docs는 인간 영역이라 초안 — 인간 검토.

## 완료 조건(검증) — 라이브 인프라 없이 정적/단위 우선
1. **D2 단위**: seed가 MLX 미참조; mock-llm chat·mock-embed embed가 `is_default=True`; `CHAT_MODEL_NAME=="mock-llm"`;
   시드 에이전트 model 참조가 시드 모델 집합 안에 있음(dangling 0).
2. **D1 단위/소스**: 새 마이그레이션이 "default chat 없을 때만 mock 승격"·mock-embed 멱등; downgrade 가역.
3. **D3/D6**: `.env.example`에 `MLX_` 부재; README에 MLX_* 행 부재·Mock 기본 안내 존재(존재 단언).
4. **D4 단위**: agent CLI가 `MLX_` env 미참조; 일반 `MODEL_*` 사용.
5. **타자 적대 검증(필수)**: codex — (a) D1 마이그레이션이 **기존 실-모델 default를 클로버하지 않는지**,
   (b) 두 부팅 경로(alembic-head / create_all)가 **동일한 기본 상태**로 수렴하는지, (c) 컬렉션·RAG 게이트가
   임베딩 default 변경에 무회귀, (d) `CHAT_MODEL_NAME` 변경이 시드 에이전트/verify에 dangling 안 만드는지.
6. **무회귀**: 기존 verify_*(seed/provider/catalog/rag) 그대로 통과.
7. **통합 rung(사용자 fresh-clone 테스트)**: 실 DB에서 `alembic upgrade head` → 기본 Mock 채팅이 바로 동작,
   admin에서 MLX provider 추가 → 기본 전환 동작. (라이브 필요 — 사용자 복귀/외부 환경서 1회.)

## 리스크 / 주의
- **두 부팅 경로 수렴**: D1(마이그레이션, alembic 경로)과 D2(seed, create_all 경로)가 *같은* 기본 상태를
  내야 한다. 둘 중 하나만 고치면 경로별 결과가 또 갈린다(이번 결함의 재발). 검증 (b)가 이를 본다.
- **기존 설치 클로버 금지**: D1은 "default chat 모델이 없을 때만" mock 승격. 이미 MLX/실모델을 default로
  쓰는 설치는 불변(회고 046 seed-drift: 신호를 바꾸지 말고 빠진 것만 채움).
- **canned 응답 혼란**: Mock 기본은 가짜 답을 준다 → README가 "실 모델은 Provider UI에서 추가"를 명확히.
- **agent 패키지 동작 변경**: D4는 별도 배포물의 런타임 모델 설정을 바꾼다 — env 이름 변경이라 기존
  배포 스크립트가 `MLX_*`를 넘기면 무효가 됨. README/주석에 명시.
- **docs 인간 영역**: README는 초안 — 인간 검토 후 확정.
