# 343 — 전 테이블 감사 컬럼(created_at/updated_at/created_by/updated_by)

## 요구 (사용자, 2026-07-14)

- **모든 테이블은 audit이 가능해야 한다.** `created_at`·`updated_at`·`created_by`·`updated_by`.
- `created_by`/`updated_by`는 **유저 아이디**. 이메일이면 `@` **앞 문자열만** 등록(`admin@example.com` → `admin`).
- `user` 테이블로 풀 수도 있지만 **별도로 기록**한다(의도적 비정규화 — 조인 없이 감사, 유저 삭제 후에도 이력 잔존).
- **FK를 안 쓰는 진짜 이유**(사용자, 2026-07-14 보충): "이 서비스에 등록된 유저는 전체 유저의 **부분집합**
  이다. 회사로 치면 전체 회사원이 고객이고 여기 등록된 유저는 그중 **관리인**이다. 추후 **채팅 중에
  유저 아이디가 들어올** 것이라 FK로 묶지 않았다." → actor 값 공간은 `{관리자 로컬파트} ∪ {system,
  unknown} ∪ {미등록 최종 사용자 ID(추후)}`. 코드·UI는 이 집합이 열려 있다고 가정해야 한다.
- **최초 삽입 시 4개가 모두 채워진다**(created == updated).

### 합의된 4갈래 (AskUserQuestion, 2026-07-14)

| 질문 | 결정 |
|---|---|
| 범위 | **우리 소유 27개 전부**. 외부 라이브러리 소유 9개는 제외(스키마 주인이 다름 — 아래 §1) |
| `owner_id`와의 관계 | **공존, 역할 분리** — `owner_id`=현재 소유자(이전 가능·인가 판정), `created_by`=최초 생성자(불변·감사) |
| 사람 아닌 주체 | **`system`** 예약어(시드·마이그레이션·배치·백그라운드 잡) |
| 기존 행 | **`unknown` 백필 + NOT NULL** — 이후 신규 행은 DB가 채움을 보장 |

## 1. 대상 (닫힌 집합 — 실 스키마 덤프 기준, 36테이블)

**적용 27**: agents · agent_versions · allowed_hosts · app_settings · approvals · batch_config ·
batch_runs · collection_reindex_events · collections · document_blobs · documents · eval_case_results ·
eval_cases · eval_datasets · eval_runs · mcp_servers · memory_snapshots · memory_types ·
message_feedback · messages · models · node_templates · personas · providers · rag_chunks · roles · sessions

**제외 9(외부 소유)**: checkpoints · checkpoint_writes · checkpoint_blobs · checkpoint_migrations
(LangGraph) · mem0_memories (mem0) · user · accesstoken (fastapi-users) · casbin_rule (casbin) ·
alembic_version (alembic). — 라이브러리가 스스로 만들고 마이그레이션하므로 우리가 컬럼을 더하면
업그레이드 시 충돌한다. `docs/db-model.md` §0의 소유 구분과 같은 선.

기존 `created_at` 18개는 **재사용**(중복 생성 금지), 없는 9개만 추가. `updated_at`은 5개만 있어
22개 추가. `sessions.started_at`·`batch_runs.started_at`·`eval_runs.started_at`·`approvals.requested_at`은
**도메인 의미**(시작/요청 시각)라 그대로 두고, 감사용 `created_at`을 별도로 갖는다(삽입 시 동일 값).

## 2. 설계 — **앱 계층(SQLAlchemy)**. DB 트리거는 **기각**(사용자, 2026-07-14)

> 초안은 DB 트리거였다. **사용자가 기각** — 로직이 DB에 숨는 방식은 쓰지 않는다. 앱 계층으로 간다.

핵심: **SQLAlchemy 컬럼 `default`/`onupdate`는 ORM뿐 아니라 Core `insert()`/`update()`에도 적용된다.**
우려했던 누수 경로(rag_ingest의 청크 대량 삽입, 좀비 스윕의 Core `update(Document)`)는 매핑된 테이블을
대상으로 하는 한 자동으로 채워진다 — ORM 이벤트 훅이었다면 샜을 자리다.

```python
class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), default=_actor, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(80), default=_actor, onupdate=_actor, nullable=False)
```

`_actor()`는 **contextvar**를 읽는다(요청 미들웨어가 principal에서 세팅, 없으면 `system`). 콜러블
default라 **실행 시점**에 평가되므로 배경 태스크·배치도 각자의 actor로 찍힌다. 최초 삽입 시
`created_* == updated_*`(같은 `_now()` 호출은 아니지만 같은 트랜잭션 내 μs 차 — 동일성이 필요하면
`__init__`에서 한 값으로 맞춘다).

**액터 해석(단일 헬퍼)**: `actor_of(principal)` — 이메일이면 `@` 앞 로컬파트(`admin@example.com` →
`admin`), 머신 토큰/시드/마이그레이션/배치/백그라운드는 `system`. 한 곳에서만 계산(드리프트 0).

**생성 정보 불변**: ORM 경로는 `before_flush` 훅이 dirty 객체의 `created_at`/`created_by` 변경을
**옛 값으로 되돌린다**. 

**정직 경계(트리거를 뺀 대가)** — DB가 강제하지 않으므로 두 구멍이 남는다:
1. `text()` raw SQL 쓰기는 감사 컬럼을 안 채운다 → 우리 코드에 그런 쓰기가 **없음을 grep으로 측정**하고
   상주 테스트로 못박는다(새 코드가 raw 쓰기를 도입하면 실패).
2. Core `update().values(created_by=…)`처럼 **대놓고 덮어쓰는 코드**는 앱이 못 막는다 → 테스트가
   잡는 선까지가 한계. (트리거였다면 DB가 봉했을 자리 — 기각의 대가로 명시 기록.)

**배경 잡(스펙 334 인제스트)**: 업로드 요청 자체(`documents` 행 생성)는 **사용자 actor**로 찍히고,
이후 배경 잡의 상태 전이(parsing→ready)는 `updated_by='system'`이 된다 — 사용자 결정("백그라운드=system")과
정합. 즉 "누가 올렸나"는 `created_by`에, "누가 마지막에 만졌나"는 `updated_by`에 남는다.

## 3. 마이그레이션 (단일 리비전, 손수 번호 금지)

`alembic revision -m …`로 **ID를 생성**받는다(learning: 손수 순번 = 조용한 충돌·silent overwrite).
순서: ① 없는 컬럼 추가(nullable) → ② 백필(`created_at`=기존 유사 컬럼 또는 `now()`,
`created_by`/`updated_by`=`'unknown'`, `updated_at`=`created_at`) → ③ NOT NULL 승격.
downgrade는 역순(추가한 컬럼만 제거 — 기존 `created_at` 18개는 보존). **DB 객체(함수·트리거) 생성 없음.**

**주의(learning `reload-reruns-migrations-mid-edit`)**: 마이그레이션 작성 중 dev 서버가 `--reload`로
살아 있으면 저장 시점에 반쪽 적용된다. **작성 전 서버를 내리고**, 완성 후 기동한다.

## 4. 검증 (사다리 3런 — 비겹침)

1. **단위/시맨틱**(throwaway DB, virgin): ORM insert · **Core `insert()` 대량 삽입** · **Core `update()`**
   전부 4컬럼이 채워짐/갱신됨(= 컬럼 default·onupdate가 Core에도 적용됨을 실증 — 트리거 없이 이 설계가
   서는 근거) · ORM UPDATE 시 `created_*` 불변(before_flush가 되돌림) · actor 미설정 시 `system` ·
   이메일 로컬파트 변환(`a@b.com` → `a`).
2. **커버리지 측정**(자가선언 금지): ① DB 질의로 우리-소유 27테이블에 4컬럼이 존재(27/27),
   ② ORM 레지스트리 스캔으로 모든 매핑 클래스가 `AuditMixin` 상속(새 테이블이 규약을 빠뜨리면 실패),
   ③ **raw `text()` 쓰기 grep 0**(감사 우회 경로 부재를 상주 핀으로).
3. **실 인프라 통합**: 로그인 후 HTTP로 에이전트 생성 → `created_by='admin'`(이메일 로컬파트 실증).
   RAG 업로드 → `documents.created_by=<사용자>`, 배경 잡 완료 후 `updated_by='system'`.
   **누출 핀**: 사용자 요청 직후 actor 없는 경로(배치·시드)가 실행되면 `system`으로 찍히는지
   (contextvar가 요청 경계를 넘어 새지 않음 — 앱 계층 설계의 대응 위험).
4. **적대 검증(codex)**: 우회 경로 여집합 — `text()` raw 쓰기 · `INSERT … ON CONFLICT DO UPDATE`(onupdate
   미적용 가능성) · `bulk_update_mappings` · `created_by` 직접 덮어쓰기 · 백그라운드 태스크의 contextvar
   승계(요청 actor가 배경 잡으로 묻어나는지) · 시드/마이그레이션 경로의 actor 부재.

## 결과 (2026-07-14 실행)

- 설계대로 — `api/audit.py`(AuditMixin + contextvar actor + before_flush 불변 가드), 27모델 믹스인,
  actor 주입 2곳(`auth._principal`·`authz.require`), 마이그레이션 `a7f3c9e21b4d`. **DB 트리거 0개**.
- **예상 못 한 충돌 1건**: `message_feedback`에 **이미 `created_by`가 있었다** — 감사용이 아니라
  "피드백 작성자"(auth User UUID)이고 `(message_pk, created_by)` 유니크 인덱스의 일부. 이름만 같은
  남남이라 다른 테이블이 같은 개념을 부르는 이름(`owner_id`)으로 **개명**했다(코드 5곳·인덱스·테스트).
- **codex 적대 검토 → P1 2건·P2 2건·P3 2건 수정**:
  - P1 피드백 upsert의 `set_`에 `updated_by` 누락 → 재클릭해도 최초 작성자가 남음(감사 거짓말). 수정.
  - P1 downgrade 순서 오류(개명을 먼저 되돌리면 감사 `created_by`와 충돌) → 감사 컬럼 drop을 먼저.
  - P2 배경 잡 actor 정책이 **RAG에만** 있었음(평가 런·AI 출제·수확은 요청자 이름으로 찍힘) →
    `background.spawn()` **단일 관문**으로 올림(잡별로 두면 하나 빠뜨린다는 게 정확히 실현된 것).
  - P2 V9의 보장이 실제보다 컸음 → Core `.values(created_*=)` 스캔(V10)·upsert 누락 스캔(V11) 추가.
- 검증: **VERIFY343_OK 16/16**(ORM/Core insert·Core update·위변조 되돌림·actor 기본 system·이메일
  로컬파트·27테이블 커버리지 DB 측정·NOT NULL·레지스트리 스캔·우회 경로 3종 스캔·**배경 잡 관문**) +
  **VERIFY343B_OK 4/4**(upgrade→downgrade→upgrade 왕복 — 아무도 안 돌려보는 downgrade를 상주 핀으로).
  라이브: 로그인 생성 → `created_by=admin`(이메일 로컬파트 실증), 수정 → `updated_by` 갱신,
  RAG 업로드 → `created_by=admin`·배경 완료 후 `updated_by=system`(경계 실증), 과거 행 `unknown` 백필.
  무회귀: 209 피드백·수확 통과, lint/mypy 클린.
- **정직 경계**: (1) `text()` raw INSERT/UPDATE와 Core `.values(created_*=)`는 DB가 막지 않는다 —
  **스캔 테스트가 잡는 선까지**가 보장 크기(트리거 기각의 대가, 스펙 §2). (2) 백필은 27테이블 full-table
  UPDATE — 이 규모(수천 행)에선 무해하나 **운영 규모에선 배치 백필·lock_timeout이 필요**하다(codex P2).
- 기존 게이트 드리프트 2건(verify_098 세션검색·verify_034 페이지네이션)은 **이 변경 이전에도 실패**함을
  stash 대조로 확인 — 이번 회귀 아님(백로그).

## 5. OUT

- 변경 **이력 테이블**(누가 무엇을 어떻게 바꿨는지 diff 보관) — 이번엔 "마지막 수정자"까지만.
  이력이 필요해지면 별 스펙(audit_log 테이블 + 트리거에서 OLD/NEW diff 적재).
- 외부 소유 9테이블 · admin UI 노출(생성자/수정자 표시) · 소프트 삭제(deleted_at/deleted_by).
