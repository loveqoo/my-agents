# my-agents

에이전트를 **하드코딩하지 않고** 구조 안에서 만들고·재사용하고·A2A로 협업시키는 멀티 에이전트 플랫폼.
페르소나·파운데이션 모델·MCP(tools)·메모리(Mem0)를 조합해 에이전트를 정의하고, 자체 MCP와
원격 MCP를 등록해 제공·관리한다.

- **Backend(API)** — FastAPI + LangGraph. 에이전트/MCP 런타임, A2A 프로토콜.
- **Admin SPA** — React + TypeScript + Ant Design. 에이전트·MCP·모델 관리 콘솔.
- **DB** — PostgreSQL + pgvector (Mem0 벡터 스토어).

> 작업 방식(6단계 루프)·폴더 규약은 [`CLAUDE.md`](./CLAUDE.md), 스펙은 [`docs/spec/`](./docs/spec/) 참고.

---

## 처음 받아 실행하기 (first run)

처음 클론한 상태에서 아래 순서대로 하면 로컬에서 뜬다. 부팅 시 DB 스키마 마이그레이션과 기본
시드(Provider/모델/에이전트)는 **자동**으로 처리된다.

### 1. 환경 변수 — `.env` 작성

```bash
cp .env.example .env
```

`.env`에서 최소 아래 값을 환경에 맞게 채운다([`.env.example`](./.env.example)에 각 값 설명):

| 키 | 용도 | 비고 |
|---|---|---|
| `DATABASE_URL` | postgres 접속 | 아래 docker compose 기본값과 일치하면 그대로 둬도 됨 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 첫 관리자 시드 | **영속 keep-list 계정**(예: `admin@example.com`)으로 둔다. 비우면 관리자가 안 만들어져 로그인 불가(아래 4·복구 참고) |
| `API_AUTH_TOKEN` | 머신(서버↔서버) 인증 토큰 | 강한 값으로 교체. admin의 `VITE_API_TOKEN`과 동일해야 함 |

> 모델 연결 env는 없다(스펙 059). 기본 채팅/임베딩 모델은 **Mock LLM**(무외부 동작)이고, 실 모델은 env가 아니라 admin **Provider UI**에서 추가한다(5번 참고).

### 2. PostgreSQL 기동 (pgvector 번들)

```bash
docker compose up -d postgres
```

`pgvector/pgvector:pg16` 이미지라 pgvector 확장이 포함된다. (마이그레이션이 `CREATE EXTENSION
vector`를 멱등 실행하므로 별도 설치 불필요.)

### 3. API 기동

```bash
uv sync                 # 의존성 설치
uv run api              # = uvicorn (api.main:app), 기본 127.0.0.1:8000
```

기동 시 `init_db`가 (1) DB 연결 **프리플라이트** → (2) `alembic upgrade head`(실패 시 `create_all`
폴백) → (3) 비어 있으면 시드를 자동 수행한다. DB가 안 떠 있으면 raw 트레이스 대신 **명확한 조치
메시지**(어떤 `DATABASE_URL`인지 + `docker compose up -d postgres` 안내)로 부팅을 중단한다.

> 외부(Tailscale 등) 노출은 `API_HOST=<tailnet IP>`로만 켠다. 기본은 loopback이라 외부 비노출.

### 4. Admin 콘솔 기동 + 로그인

```bash
cd admin
npm install
npm run dev             # vite, 기본 5173
```

브라우저로 admin에 접속해 1번에서 정한 `ADMIN_EMAIL`/`ADMIN_PASSWORD`로 로그인한다.
공개 회원가입은 의도적으로 막혀 있다 — 관리자 계정은 시드 또는 아래 부트스트랩으로만 만든다.

**락아웃 복구**(유저가 0명인데 로그인할 수 없을 때):

```bash
uv run python -m api.bootstrap_admin <email> <password>
# 또는 ADMIN_EMAIL/ADMIN_PASSWORD env를 채우고 인자 없이 실행
```

신규 superuser를 **생성만** 한다. 이미 존재하는 계정은 보안상 승격하지 않으니(권한 상승 방지),
새 관리자는 *새 이메일*로 만든다.

### 5. 모델 — 기본은 무외부 Mock, 실 모델은 Provider UI에서 추가

기본 채팅·임베딩 모델은 **Mock LLM**(스펙 059)이다 — 외부 모델 서버 없이 바로 동작한다(응답은
canned). 별도 env 설정이 필요 없고, 시드에 Mock Provider/모델(`mock-llm` 채팅 + `mock-embed`
임베딩)이 기본으로 들어 있어 클론 직후 채팅·RAG가 곧장 뜬다.

실제 모델(MLX·OpenAI 호환·기타)을 쓰려면 **admin Provider UI**에서 Provider와 Model을 추가하고
기본 채팅 모델을 그쪽으로 전환한다. 전환한 실 모델 서버가 안 떠 있으면 첫 채팅이 연결 실패하고,
에러 메시지에 **Mock LLM으로 되돌리는 안내**가 함께 표시된다.

---

## 자주 만나는 첫 실행 상황

| 상황 | 동작 |
|---|---|
| **갓 클론 (기본 경로)** | `mock-llm`(채팅)·`mock-embed`(임베딩)이 기본 시드 → **외부 모델 없이 채팅·RAG가 즉시 동작**(스펙 059). 정상 `alembic upgrade head` 경로·`create_all` 폴백 경로 모두 같은 Mock 기본으로 수렴 |
| DB 미기동/연결 불가 | 프리플라이트가 명확한 조치 메시지로 부팅 중단 (`docker compose up -d postgres`) |
| 테이블 없음 | `alembic upgrade head` 자동, 실패 시 `create_all`(+pgvector 확장) 폴백 |
| pgvector 확장 부재 + 설치 권한 없음 | 명확한 메시지로 부팅 중단(pgvector 번들 이미지 사용 또는 수퍼유저로 `CREATE EXTENSION vector`) |
| 빈 DB | `seed_if_empty`가 Provider(Mock LLM)/모델/에이전트 등 카탈로그 자동 시드 |
| 유저 0 + ADMIN env 누락 | 부팅 시 복구 안내 경고 → `python -m api.bootstrap_admin`로 생성 |
| 기본 채팅 모델을 실 모델로 바꿨는데 그 서버가 안 뜸 | 첫 채팅이 연결 실패 → 에러에 **Mock LLM으로 되돌리기** 안내 동반 |
| 시드 모델을 전부 삭제한 경우 | 채팅이 friendly 400("모델을 먼저 등록하세요"), 임베딩 부재 시 메모리(Mem0) graceful 비활성 — 채팅 자체는 정상 |

---

> 이 README는 운영 시작 문서(런북) 초안이다 — `docs/`는 인간 영역이므로 검토 후 확정한다(스펙 058 G3).
