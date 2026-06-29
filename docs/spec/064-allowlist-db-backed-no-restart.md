# 064 — SSRF allowlist를 env→DB로 (무재시작) + `A2A_ALLOWED_HOSTS`→`ALLOWED_HOSTS` 일반화

> 상태: 초안(AI) → 인간 검토. 선행/분리원: spec 063(§2에서 본 작업을 064로 분리 합의). 선행 자산:
> learning 012(런타임 설정=단일 레지스트리·env는 부트스트랩만)·063(fail-closed 가드 메시지=위반값+조치)·
> 062(기본값=모든 부팅경로 수렴상태)·049(청소는 발생원 살아있으면 무의미)·044/055(가드 커버리지)·
> 037(파괴적 노브 바닥). 메모리 core-is-model-config-and-memory(config 관리=토대, 엄격 검증).

## 1. 문제 / 동기

SSRF 가드(`net_guard.guard_url`, 스펙 042)의 allowlist는 현재 **`A2A_ALLOWED_HOSTS` 환경변수**에서만
읽힌다(`_allowed_hosts()` = `os.environ`). 두 가지 한계:

1. **무재시작 불가**: 허용 host를 추가/제거하려면 `.env`를 고치고 **API 재기동**해야 한다(차단 메시지도
   "변경 후 API 재기동 필요"라고 안내). 운영 중 A2A/MCP 대상 host 하나 열려고 전체 재기동은 과하다.
2. **이름이 거짓**: 이 allowlist는 `guard_url` 한 곳을 거쳐 **A2A 클라이언트·Agent Card fetch/probe·
   MCP 런타임 연결·MCP blocks 연결 전부**에 적용된다(코드 확인: `a2a_client`·`agent_card`·`runtime`·
   `blocks` 모두 `guard_url` 경유). `A2A_` 접두어는 적용 범위를 오도한다.

목표: allowlist를 **DB가 진실원**인 무재시작 설정으로 옮기고, Admin UI+API로 관리하며, env 변수는
부트스트랩 시드로만 남기고 이름을 `ALLOWED_HOSTS`로 일반화한다.

## 2. 목표 / 비목표

- 목표: (a) `allowed_hosts` DB 테이블이 진실원, (b) Admin API로 list/add/remove, (c) Admin UI 뷰,
  (d) `guard_url`이 무재시작으로 DB 값을 반영(짧은 TTL 캐시), (e) env는 **부트스트랩 1회 시드**만
  (`ALLOWED_HOSTS`, 구 `A2A_ALLOWED_HOSTS` 폴백), 이후 DB가 단일 소스(learning 012).
- 비목표: **SSRF 정책 자체 변경 없음**(사설/공인 판정·`_ip_is_blocked`·resolve 로직 그대로). allowlist는
  여전히 "이 host는 사설대역이라도 통과"의 *예외 목록*일 뿐. CIDR·와일드카드·서브넷 매칭 도입 안 함
  (정확 host 매칭 유지 — 와일드카드는 allow-all SSRF footgun, §3). 멀티워커 즉시 일관성(TTL 내 수렴 허용).

## 3. 보안 불변 / 위협 모델 (적대 검증 대상)

allowlist 편집은 **SSRF 구멍을 여는 행위**다(host 하나 추가 = 그 host로 향하는 사설대역 요청 허용).
그러므로:

- **권한**: add/remove 엔드포인트는 batch/user_admin과 **동일한 admin 게이트**(슈퍼유저). 약한 권한
  주체는 403(learning 050/054 — 보호대상의 *모든 동사*를 같은 술어로).
- **입력 검증(037 파괴적 노브 바닥)**: host 항목은 **정확 host(이름 또는 IP)만**. 거부: 빈 값·공백·
  `*`·와일드카드·CIDR(`/`)·스킴 포함(`http://`)·`,`(다중 우회)·포트 포함. 와일드카드/빈값을 넣으면
  `host.lower() in set` 매칭이 깨지거나(무력) allow-all로 둔갑할 수 있으니 **정규화 후 정확 host**만 저장.
  저장은 `host.strip().lower()`(guard_url 매칭과 동형), 중복은 unique 제약.
- **불변 유지**: guard_url의 판정 로직은 불변. allowlist는 "공인 판정을 건너뛸 host 집합"이라는 기존
  의미 그대로 — DB로 옮겨도 *무엇을 통과시키는지*는 동일, *어디서 읽는지*만 바뀐다.
- **캐시 staleness**: host **제거**가 TTL(≤10s) 동안 아직 허용될 수 있다(removed-but-cached). 보안상
  "닫는 변경이 늦게 반영"되는 창이므로 TTL을 짧게(기본 10s) 두고, 제거 시 **그 워커 캐시는 즉시 무효화**
  (다른 워커는 TTL 내 수렴). 이 창을 스펙에 명시하고 codex 적대 점검 대상으로.

## 4. 처방

### D1 — `allowed_hosts` 테이블 (models.py + alembic + create_all 양 경로)
`class AllowedHost(Base)`: `id`(pk), `host`(String(255), unique, NOT NULL — 정규화 lower 저장),
`note`(String(200) nullable — "왜 열었나"), `created_at`(server_default now). 마이그레이션 1건
(alembic head `c9d0e1f2a3b4` 뒤). create_all 폴백 경로(path B)도 `Base.metadata`로 자동 생성됨.

### D2 — env→DB 부트스트랩 시드 (alembic 마이그레이션 단독 + 049 재시드 footgun)
첫 부팅 시 env(`ALLOWED_HOSTS`, 없으면 구 `A2A_ALLOWED_HOSTS` 폴백)를 파싱해 `allowed_hosts`에 1회
삽입. **재시드 footgun 차단(049)**: 관리자가 UI로 목록을 비운 뒤 재부팅해도 env가 *되살리면* 안 된다.
보안 allowlist라 "테이블이 비었나" 게이트(seed_if_empty)는 위험 — 비운 직후 재부팅이 SSRF 예외를
*되살린다*. 그래서 env→DB 임포트를 **alembic 데이터 마이그레이션 단독**(`d0e1f2a3b4c5`, revision-stamped
→ 정확히 1회, 관리자가 비워도 재실행 안 됨)으로만 둔다. **seed.py는 손대지 않는다**(049 재시드 표면
원천 차단). create_all 폴백(path B)은 `Base.metadata`로 테이블을 만들되 **빈 allowlist로 시작**
(fail-closed — env를 임포트하지 않음). 즉 부트스트랩 env 시드는 alembic 경로(path A)에서만 일어나고,
path B는 비어 시작해 관리자가 콘솔로 채운다. 두 경로 모두 *DB가 진실원·env 미반영*이라는 동일 불변으로
수렴함을 통합 검증에서 단언(062). 구 변수명 폴백 시 deprecation 로그 1줄.

### D3 — `net_guard` DB 캐시 스냅샷 (sync guard_url 유지, 무재시작)
- 모듈 전역 `_ALLOWED_CACHE: set[str]` + `_CACHE_EXPIRES: float`(monotonic). `_allowed_hosts()`는
  **이 스냅샷을 sync로 읽기만** 한다(현 시그니처·guard_url sync 유지 — 블라스트 반경 최소).
- `async def refresh_allowed_hosts(force=False)`: 만료(now ≥ expires)거나 force면 DB 조회→스냅샷 교체→
  `expires = now + TTL`(기본 10s). 디바운스(만료 전이면 no-op·DB 안 침). 동시 다중 호출은 멱등 교체라 무해.
- **배선(055 — 새/기존 아웃바운드 경로마다 가드 재확인)**: `guard_url(...)` 호출 *직전*에 `await
  net_guard.refresh_allowed_hosts()`를 두는 지점 = `a2a_client.a2a_stream`·`agent_card.fetch_card`·
  `agent_card.probe_endpoint`·`runtime`(MCP connect)·`blocks`(MCP connect). 다섯 곳 모두 async라 await 가능.
- 부팅 lifespan에서 1회 warm(선택) — 콜드 첫 요청도 lazy refresh로 안전.
- 순환 import 주의: net_guard가 db.py 세션 팩토리를 지연 import(`from . import db` inside func).

### D4 — 이름 일반화 + 차단 메시지 갱신 (learning 063)
- `A2A_ALLOWED_HOSTS`→`ALLOWED_HOSTS`: `.env`·`.env.example`·`runtime.py`/`net_guard.py` 독스트링.
  부트스트랩 시드만 env를 읽고(구 이름 폴백), 런타임은 DB만. 
- 차단 메시지(net_guard.py:166-170): "환경변수 …에 추가, 재기동 필요"를 **"관리 콘솔 '허용 호스트'에서
  이 host를 추가하세요(무재시작, 최대 ~10초 반영)"**로. 위반 host echo는 유지(063 불변).

### D5 — Admin API (admin 게이트 CRUD)
새 라우터 `allowed_hosts.py`(`prefix="/admin/allowed-hosts"`, batch_routes 패턴=자체 admin 보호):
- `GET /` 목록(host, note, created_at).
- `POST /` {host, note?} — §3 검증(정확 host만·정규화 lower)·중복 409·성공 시 그 워커 캐시 무효화.
- `DELETE /{id}` — 제거·그 워커 캐시 무효화.
입력 검증 실패는 detail에 안전 사유(learning 065/063 — 위반값+조치). main.py에 라우터 등록.

### D6 — Admin UI (`AllowedHostsView`)
AdminShell 관리 그룹(users/batch 옆)에 메뉴 `허용 호스트` 추가. 목록 테이블 + 추가 폼(host·note) +
삭제(확인 모달). BatchView/UsersView 패턴·`httpError` 중앙 추출(065) 재사용. 추가/삭제 후 목록 refetch.

## 5. 검증 (사다리 — 자가검증 지양, 비겹침)

- **단위(시맨틱)**: host 검증(빈값·`*`·CIDR·스킴·콤마·포트 거부, 정상 host/IP 통과·lower 정규화)·
  캐시 TTL 로직(만료 전 no-op·만료 후 교체·force 무효화)·env 폴백(`ALLOWED_HOSTS` 우선, 구 이름 폴백).
- **라이브 통합(실 인프라·062 양 경로)**: fresh DB(path A=alembic)에 env 시드 → `guard_url`이 그 host
  통과. API로 host 추가 → **재기동 없이** TTL 내 `guard_url` 통과로 전환. host 제거 → 다시 차단. path B
  (create_all 폴백)는 **빈 allowlist로 시작**(env 미임포트=fail-closed)함을 단언. 양 경로가 *DB 진실원·
  런타임 env 미반영*이라는 동일 불변으로 수렴·관리자 비움 후 재부팅이 **재시드 안 함**(049, 마이그레이션
  revision-stamped라 재실행 없음) 단언.
- **적대(codex)**: ①allowlist 편집이 권한 상승·SSRF-open 표면인지(비-admin 403·와일드카드/빈값/CIDR/
  대소문자·콤마 우회로 allow-all 둔갑 차단) ②캐시 staleness 창(제거가 TTL 내 늦게 닫힘)이 문서대로 ≤TTL인지
  ③049 재시드 footgun(빈 목록 재부팅) ④구 env 변수 폴백이 부트스트랩에서만(런타임 우회 아님) ⑤멀티워커
  수렴(한 워커 추가가 다른 워커에 TTL 내 반영, 영구 분기 아님).
- **브라우저**: `AllowedHostsView` 추가/삭제 + 스크린샷(verify-ui-in-browser, tests/browser/shot-*).

### 5.1 codex 적대 처분 (2026-06-29, 8건 → 수정 4·by-design 4)

- **[P1] `0.0.0.0`/`::` 수용 → allow-local 둔갑**: `normalize_allowed_host`가 미지정 주소를 canonical로
  수용해, allowlist에 들면 `guard_url`이 `_ip_is_blocked` 전에 정확매칭으로 통과시켰다. → **수정**:
  `ip.is_unspecified` 거부. 회귀 벡터 추가(`verify_064_unit` N: `0.0.0.0`·`::`·`[::]`).
- **[P2] 과길이 host → 500**: DB `String(255)` 초과 입력이 `add_host`에서 DataError→500. → **수정**:
  normalize에 253자 캡(422). 회귀 벡터 추가.
- **[P2] `ALLOWED_HOSTS_TTL` 무한/오타**: `float(env)` 직파싱이 `inf`엔 제거 영구 미반영·오타엔 부팅 크래시.
  → **수정**: `_parse_ttl` [0,300] 클램프·비유한/음수/오타→기본 10s. 회귀 벡터 추가(T1~T6).
- **[P2] 마이그레이션 미정규화 폴백**: `normalize` 임포트 실패 시 `part.lower()` 저장 → CRUD 검증 우회
  드리프트. → **수정**: 임포트 실패 시 **건너뜀(fail-closed)**.
- **[P1] DNS rebinding(allowlist된 이름은 resolve 스킵)**: 호스트 allowlist의 *본질*(이름을 신뢰해 사설
  도달이 목적)이자 스펙 042부터 **기존 동작** — 064 회귀 아님. **알려진 한계**(§3 빚과 동류). 관리자가
  공격자 통제 호스트명을 *직접* 등록해야 성립.
- **[P1] DB 장애 시 stale 스냅샷 유지**: **의도된 fail-safe** — 일시 블립에 빈 스냅샷으로 떨구면 전 아웃바운드
  self-DoS. 1s 재시도로 회복. ≤TTL 경계는 *건강한 DB 가정*이고 총체적 DB 다운 시엔 stale-until-recovery
  (닫는 변경만 지연, 새 host는 안 열림 = 안전 방향). by-design.
- **[P2] 멀티워커 제거는 프로세스-로컬 무효화**: 다른 워커는 ≤TTL 수렴 — §5⑤ 문서화된 기대 동작. dev는
  단일 워커.
- **[P2] 1회 빈 시드 + `ALLOWED_HOSTS=""` 섀도**: 문서화된 fail-closed(D2). 빈=안전 방향(UI 재추가).
  `""` 명시 설정이 구 변수를 가리는 건 좁은 운영 엣지지만 결과가 더 제한적이라 안전.

## 6. 완료 조건

- [x] `allowed_hosts` 테이블 생성(alembic + create_all 양 경로), `AllowedHost` 모델. → models.py:431 `AllowedHost`, 마이그 `d0e1f2a3b4c5`(라이브 적용 확인).
- [x] env(`ALLOWED_HOSTS`·구 `A2A_ALLOWED_HOSTS` 폴백)→DB 부트스트랩 시드 alembic 단독(path B는 빈 fail-closed), 비움 후 무재시드. → 마이그 upgrade() 1회 임포트, seed.py 무관여. live L1 시드 로드.
- [x] `guard_url`이 DB allowlist를 **무재시작**(TTL ≤10s)으로 반영, 다섯 아웃바운드 경로 모두 refresh 배선. → `verify_064_live` L3(무재시작 통과)·L4/L5(≤TTL 수렴) PASS.
- [x] `A2A_ALLOWED_HOSTS`→`ALLOWED_HOSTS` 일반화, 차단 메시지가 무재시작 콘솔 안내로(위반 host echo 유지). → net_guard guard_url 메시지·.env.example 갱신.
- [x] Admin API add/remove(admin 게이트·정확 host 검증·중복 409·캐시 무효화), main.py 등록. → allowed_hosts.py(`require("allowed_hosts","manage")`·422·409·204), main.py include_router. 브라우저서 게이트·검증 확인.
- [x] Admin UI `AllowedHostsView`(목록·추가·삭제), 관리 그룹 메뉴. → AllowedHostsView.tsx·AdminShell 배선, shot-allowed-hosts-064(4 스샷) OK.
- [x] codex 적대 통과(편집 권한·와일드카드 둔갑·staleness 창·049 재시드·env 폴백·멀티워커 수렴). → §5.1: 8건 중 P1 1·P2 3 수정, 4 by-design 문서화. 재검증 unit/live PASS.
- [x] 무회귀: 기존 env-only 동작(시드 경유로 동등)·MCP/A2A/card/probe 가드 경로 전부 동작. → verify 042/045/057/060/063 전부 PASS.
