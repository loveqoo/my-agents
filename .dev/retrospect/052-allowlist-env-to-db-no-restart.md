# 052 — SSRF allowlist를 env에서 DB로(무재시작 관리) 회고

스펙 064. 스펙 042의 SSRF allowlist를 env(`A2A_ALLOWED_HOSTS`)에서 DB 테이블(`allowed_hosts`)로
옮겨 **재기동 없이** Admin UI/API로 관리하게 했다. `A2A_` 접두어를 떼고(`ALLOWED_HOSTS`, MCP/카드/
probe/blocks 공용), env는 alembic 마이그레이션이 1회 읽는 **부트스트랩 시드**로 강등(DB가 진실원).

## 무엇을 했나 (D1~D6)
- D1 `allowed_hosts` 테이블(`AllowedHost` 모델 + 마이그 `d0e1f2a3b4c5` + create_all 폴백).
- D2 env→DB 부트스트랩을 **alembic 단독 1회**(revision-stamped → 재실행 없음 → 049 재시드 footgun 차단,
  seed.py 무관여). path B(create_all)는 **빈 fail-closed**로 시작(env 미임포트).
- D3 `net_guard` 모듈 캐시 스냅샷(monotonic TTL 기본 10s) — `guard_url`은 sync 시그니처 유지하며 스냅샷만
  읽고, async 호출처 5곳이 직전에 `await refresh_allowed_hosts()`. 콜드/빈 스냅샷 = fail-closed.
- D4 이름 일반화 + 차단 메시지를 무재시작 콘솔 안내로(learning 063 — 위반 host echo).
- D5 Admin CRUD(`require("allowed_hosts","manage")` 게이트·422/409/204·캐시 무효화).
- D6 `AllowedHostsView` + AdminShell 배선(관리 그룹 메뉴).

## 검증 사다리 (비겹침 4 rung)
단위(`verify_064_unit`: normalize 거부/수용·캐시 시맨틱·TTL 클램프)·라이브 통합(`verify_064_live`:
실 DB L1~L5 무재시작 반영·≤TTL staleness 창)·브라우저(`shot-allowed-hosts-064` 4 스샷)·**적대 codex**.

## 핵심 통찰
1. **저장 위상 이전(env→DB)이 입력 표면을 넓힌다.** env는 부팅 1회·운영자만 넣었다. DB로 옮기니 *런타임
   CRUD*가 새 입력 경로가 됐고, env 파싱이 우연히 걸러주던 것·운영자만 넣던 신뢰가 사라졌다. → 새 진입점
   (`normalize_allowed_host`)이 **유일 게이트**가 되고, DB 컬럼 제약(`String(255)`)이 500-vs-422 경계가 됐다.
   codex가 정확히 이 틈을 짚음(과길이 host → 500, learning 067).
2. **정확매칭 allowlist가 IP-class 가드보다 *먼저* 단락하면, allowlist의 정규화가 마지막 방어선이다.**
   `guard_url`은 `host in allowlist`면 `_ip_is_blocked` 전에 통과시킨다. 그래서 `ipaddress.ip_address()`가
   *수용*하는 것과 그 리터럴이 *안전한 단일 타깃*인 것은 다르다 — `0.0.0.0`·`::`(미지정=와일드카드 바인드)는
   canonical로 깔끔히 통과해 allowlist에 들면 로컬 리스너를 연다(codex [P1]). normalize에서 `is_unspecified`
   거부로 막음(learning 067).
3. **적대 검증이 자가검증의 구조적 사각을 또 메웠다.** happy-path(정상 host·정상 TTL)는 전부 초록 —
   `0.0.0.0`·과길이·`inf` TTL은 *적대자만* 던진다. 8건 중 P1 1·P2 3을 코드로 고치고, 4건(DNS rebinding·
   DB-outage stale·멀티워커 ≤TTL·빈 시드)은 **by-design**으로 §5.1에 처분 명시(고침과 안-고침을 둘 다 근거와
   함께 기록 = adversarial-review-before-destructive-ship 메모리의 "보장 목록 여집합" 실천).
4. **by-design을 "안전하니 무시"가 아니라 *명시 처분*으로 적었다.** DNS rebinding은 호스트 allowlist의
   본질이자 042부터 기존 동작(064 회귀 아님), DB-outage stale은 빈 스냅샷=전 아웃바운드 self-DoS보다 나은
   fail-safe. 근거를 spec에 남겨야 다음 적대 리뷰가 같은 걸 재제기해도 싸게 닫힌다.

## 아쉬움 / 다음
- `0.0.0.0`/과길이/TTL은 스펙 §3 위협모델을 처음 적을 때 *수용 벡터*까지 열거했으면 1차에 잡혔다 —
  "거부 목록"은 적었지만 "수용하는 IP 리터럴 중 비-타깃"은 안 적음. 위협모델에 *통과시키면 안 되는
  canonical 값*을 별도 축으로.
- 마이그레이션 미정규화 폴백(`part.lower()`)은 실 DB선 죽은 경로였지만 신규 배포의 fail-closed 일관성을
  위해 skip으로 바꿈 — "거의 안 타는 폴백"도 보안 경로면 안전 방향으로.

retrospect 052 · learning 067 · spec 064.
