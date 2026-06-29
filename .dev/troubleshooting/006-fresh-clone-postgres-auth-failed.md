# 006 — fresh clone 부팅 시 `password authentication failed for user "agent"`

## 증상
다른 머신에 fresh clone → `docker compose up`으로 postgres를 띄우고 `uv run api` →
G1 프리플라이트가 부팅을 또렷이 중단:

```
ERROR: DB 연결 실패 — 부팅을 중단합니다.
DATABASE_URL = postgresql+asyncpg://agent:***@localhost:5432/agents
원본 오류: password authentication failed for user "agent"
```

**이건 코드 결함이 아니라 G1(스펙 058)이 진짜 인증 실패를 raw 트레이스 대신 마스킹 DSN +
조치 메시지로 잡아 알려주는 *설계대로의 동작*이다.** 뜻: 앱이 닿은 postgres가 `agent`/`agent`
자격증명을 가진 *이 프로젝트의 컨테이너가 아니다*.

## 근본 원인(랭킹)
1. **5432를 다른 postgres가 점유** — 호스트 postgres(Postgres.app·Homebrew) 또는 이전 시도에서
   남은/다른 프로젝트의 컨테이너. 앱이 그쪽에 붙으면 `agent` 유저가 없어 인증 실패.
2. **stale 볼륨** — 예전에 다른 비밀번호로 init된 `pgdata` 볼륨이 남아 있으면 compose의
   `agent/agent`로 *안 바뀐다*(postgres는 최초 init 때만 비번을 정함).
3. `.env`의 `DATABASE_URL` 유저/비번/포트가 compose와 불일치.

> 주의: 이 repo의 `docker-compose.yml`은 **서비스가 `postgres` 하나뿐**이다 → `docker compose
> up -d` 와 `docker compose up -d postgres`는 *논리적으로 동일*하다. "서비스명을 붙이니 됐다"는
> 사례(2026-06-29 실제 보고)의 진짜 원인은 **재실행이 stale/충돌 postgres를 이 프로젝트
> 컨테이너로 교체**한 것이지, 서비스명 자체가 아니다.

## 진단 사다리(사용자 머신에서)
```bash
# ① 5432에 무엇이 떠 있나 — 이 컨테이너인가 호스트/다른 postgres인가
lsof -nP -i :5432
docker compose ps

# ② 컨테이너 *안*에서 agent/agent가 먹는가
docker compose exec postgres psql -U agent -d agents -c "select current_user, current_database()"
```
- ②는 성공인데 앱은 실패 → ①의 **다른 postgres가 5432를 가로챔**. 그걸 끄거나
  (`brew services stop postgresql` / Postgres.app 종료) compose 포트를 바꾼다.
- ②도 실패(같은 auth 에러) → **stale 볼륨**. fresh clone이면 데이터 날려도 안전:
  ```bash
  docker compose down -v        # -v = 볼륨 삭제(DB 데이터 삭제 주의)
  docker compose up -d postgres
  ```

## 해결(보고된 사례)
`docker compose up -d postgres`로 재기동하니 이 프로젝트의 postgres(agent/agent)가 5432를
잡아 정상 부팅. README 5번까지 채팅·RAG 동작 확인.

## 재발 방지 메모
- README는 이미 `docker compose up -d postgres`(서비스명 형)를 처방하므로 문서 변경 불필요.
- 막히면 **G1 메시지의 "자격증명(.env)·포트 확인"**을 먼저 믿고 위 진단 사다리 ①②를 돌릴 것 —
  대개 호스트 postgres 충돌 또는 stale 볼륨이다.
