# my-agents

에이전트를 **하드코딩하지 않고** 구조 안에서 만들고·재사용하고·A2A로 협업시키는 멀티 에이전트 플랫폼.
프롬프트·모델·MCP 도구·메모리(mem0)·RAG 컬렉션을 조합해 에이전트를 정의하고, 버전으로 게시하며,
위험 작업은 승인(HIL) 관문을 거친다. 자체 MCP·A2A 서빙으로 외부에도 노출한다.

- **Backend(API)** — FastAPI + LangGraph. 에이전트/MCP 런타임, A2A 프로토콜, 버전 그래프 캐시.
- **Admin SPA** — React + TypeScript + Ant Design. 에이전트·블록·모델·승인·평가 관리 콘솔.
- **DB** — PostgreSQL + pgvector (mem0 벡터 스토어 겸용).

## 문서

| 문서 | 대상 | 내용 |
|---|---|---|
| [유저 가이드](./docs/user-guide.md) | 플랫폼 사용자·관리자 | 전체 기능 개요와 메뉴별 사용법(스크린샷 포함) |
| [개발 가이드](./docs/dev-guide.md) | 개발자 | SDK(코드) 에이전트 작성·등록·실행, 클래스 다이어그램, 확장 포인트 |
| [시스템 아키텍처](./docs/architecture.md) | 개발자·아키텍트 | 시스템 컨텍스트, 요청 흐름, 핵심 메커니즘(캐시·브로커·HIL) |
| [DB 모델](./docs/db-model.md) | 개발자 | ER 다이어그램·테이블 소유·라이프사이클(라이브 스키마 대조) |

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

기동 시 `init_db`가 (1) DB 연결 **프리플라이트** → (2) `alembic upgrade head` → (3) 비어 있으면
시드를 자동 수행한다. 마이그레이션이 실패하면 **조용히 대체하지 않고**(스펙 330 — 구 `create_all`
폴백 제거) 원인 후보·진단 명령을 담은 메시지로 부팅을 중단한다. DB가 안 떠 있으면 raw 트레이스
대신 **명확한 조치 메시지**(어떤 `DATABASE_URL`인지 + `docker compose up -d postgres` 안내)로
부팅을 중단한다.

> 외부(Tailscale 등) 노출은 `API_HOST=<tailnet IP>`로만 켠다. 기본은 loopback이라 외부 비노출.

> **회사망(SASE) 디바이스**: web-fetch(위키)가 503이면 **게이트웨이의 UA 필터**를 의심한다(스펙
> 341) — 특정 UA만 통과시키는 회사망이 있다. 그 디바이스 `.env`에만:
> - `WEB_FETCH_UA=curl/8.7.1` — 아웃바운드 web-fetch UA 교체(기본값은 무변경). 통과 UA는 환경마다
>   다르니 소스에 박지 않는다.
>
> (사내 CA 신뢰 확장(339·340)은 **제거**됐다 — 실제 원인이 UA였고 아무도 켜지 않아서. 스펙 342.)

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
| **갓 클론 (기본 경로)** | `mock-llm`(채팅)·`mock-embed`(임베딩)이 기본 시드 → **외부 모델 없이 채팅·RAG가 즉시 동작**(스펙 059). 스키마는 `alembic upgrade head` 단일 경로가 빌드(스펙 330) |
| DB 미기동/연결 불가 | 프리플라이트가 명확한 조치 메시지로 부팅 중단 (`docker compose up -d postgres`) |
| 테이블 없음 | `alembic upgrade head`가 전 체인 자동 빌드(pgvector 확장 포함). 실패 시 폴백 없이 조치 메시지로 부팅 중단(스펙 330) |
| pgvector 확장 부재 + 설치 권한 없음 | 명확한 메시지로 부팅 중단(pgvector 번들 이미지 사용 또는 수퍼유저로 `CREATE EXTENSION vector`) |
| 빈 DB | `seed_if_empty`가 Provider(Mock LLM)/모델/에이전트 등 카탈로그 자동 시드 |
| 유저 0 + ADMIN env 누락 | 부팅 시 복구 안내 경고 → `python -m api.bootstrap_admin`로 생성 |
| 기본 채팅 모델을 실 모델로 바꿨는데 그 서버가 안 뜸 | 첫 채팅이 연결 실패 → 에러에 **Mock LLM으로 되돌리기** 안내 동반 |
| 시드 모델을 전부 삭제한 경우 | 채팅이 friendly 400("모델을 먼저 등록하세요"), 임베딩 부재 시 메모리(Mem0) graceful 비활성 — 채팅 자체는 정상 |

---

## 개발·테스트

품질 게이트는 `Makefile`이 정본이다. 자주 쓰는 명령:

```bash
make test           # 회귀망 씨앗 그물(unit + db — run당 격리 DB)
make test-all       # 전층(http 포함 — dev 서버 8000 전제)
make suite          # 실모델 조합 스위트
make metrics        # lint·복잡도·타입 + suite (완료 판정자)
make e2e            # Playwright (API 8000 + Postgres 전제)
```

SDK(코드) 에이전트 개발은 [개발 가이드](./docs/dev-guide.md)를 따른다.

---

> 런북 검증 기준일: 2026-07-21(절차·명령을 저장소 실물과 대조).
