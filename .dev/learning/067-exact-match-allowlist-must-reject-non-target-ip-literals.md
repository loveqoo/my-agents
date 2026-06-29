# 067 — 가드보다 먼저 단락하는 정확매칭 allowlist는 *비-타깃 IP 리터럴*을 스스로 거부해야 한다 (canonical 수용 ≠ 안전 타깃)

**언제** — SSRF/접근 가드가 `host in allowlist`면 IP-class 검사(`is_global`/사설 판정) *전에* 통과시키는
구조에서, 그 allowlist 항목을 `ipaddress.ip_address()` 류로 "유효한 IP면 수용" 정규화할 때. 또는 보안
control의 *저장 위상*을 부팅-static(env/config)에서 런타임-DB(CRUD 관리)로 옮길 때.

**명제** — 정확매칭 allowlist가 IP-class 가드보다 먼저 `return`하면, **allowlist의 정규화가 마지막
방어선**이다. 그런데 `ipaddress.ip_address(s)`가 *파싱 성공*하는 것과 그 리터럴이 *안전한 단일 아웃바운드
타깃*인 것은 다르다. 미지정(`0.0.0.0`·`::`)·멀티캐스트·예약 대역은 canonical form으로 깔끔히 통과하지만
"전부/없음/그룹"을 뜻하는 비-타깃이다. 가드는 allowlist 단락 *뒤*에 이들을 `_ip_is_blocked`로 막지만,
allowlist에 *들어가 버리면* 그 막이 안 돈다 → allow-local/allow-all 둔갑.

**부수 명제(저장 위상 이전)** — control을 env→DB로 옮기면 *런타임 CRUD가 새 입력 경로*가 된다. env 파싱이
우연히 거르던 것·운영자만 넣던 신뢰가 사라지고, 정규화 함수가 *유일 게이트*가 되며 **DB 컬럼 제약이
500-vs-422 경계**가 된다(과길이 host가 `String(255)` DataError→500). 옛 static 경로가 *암묵적으로* 좁히던
값 전부를 새 런타임 진입점에서 *명시적으로* 재검증해야 한다.

**표본** — 스펙 064(SSRF allowlist env→DB). `guard_url`은 `host.lower() in _allowed_hosts()`면 `_ip_is_blocked`
전에 통과. `normalize_allowed_host`가 `0.0.0.0`·`::`를 canonical로 수용 → allowlist에 들면 `http://0.0.0.0/`
가 로컬 리스너로 통과(codex [P1]). 과길이 host는 normalize에 길이 캡 없어 `add_host`서 500(codex [P2]).
`ALLOWED_HOSTS_TTL`은 `float(env)` 직파싱이라 `inf`엔 제거가 *영원히* 미반영·오타엔 부팅 크래시(codex [P2]).
→ normalize에 `ip.is_unspecified` 거부 + 253자 캡, `_parse_ttl` [0,300] 클램프로 수정·회귀 고정.

**처방**
1. **allowlist가 가드보다 먼저 단락하면, 그 정규화에서 비-타깃 IP를 거부**하라 — `is_unspecified`(필요시
   `is_multicast`·`is_reserved`)는 "유효 IP"여도 단일 타깃이 아니다. 파싱 성공을 수용 근거로 쓰지 마라.
2. **저장 컬럼 제약과 검증을 일치**시켜라 — 검증이 컬럼 길이/형식보다 느슨하면 그 차이가 500(서버 에러)으로
   샌다. 검증에서 422로 먼저 막아 사용자에게 조치 가능한 메시지를(learning 063).
3. **보안 control을 static→runtime으로 옮길 땐 새 진입점에서 *전부* 재검증**하라 — 옛 경로가 무엇을 암묵적으로
   좁혔는지(부팅 1회·운영자만·env 파싱 부수효과) 열거하고, 그 보장을 런타임 CRUD 게이트에 명시 이식.
4. **방어적 파싱** — env/사용자發 수치(TTL 등)는 `float()` 직파싱 금지: 비유한/음수/오타/과도값을 안전 기본·
   상한으로 클램프(보안 control의 수렴 보장이 한 typo에 깨지지 않게).

**판별 질문** — "이 가드가 allowlist 매칭에서 *조기 return*하나? 그럼 allowlist 정규화가 마지막 막이다 —
거기서 *유효하지만 비-타깃*인 값(미지정/멀티캐스트/와일드카드)을 거르나?" + "이 control의 저장을 옮겼나?
옛 경로가 암묵적으로 걸러주던 값을 새 진입점이 명시적으로 거르나?" + "검증이 저장 컬럼 제약만큼 엄격한가?"

**가족** — 037(파괴적 노브 바닥: `*`/CIDR 거부)·066(가드 앞 정규화가 입력 둔갑 — 여긴 allowlist *항목*
정규화가 가드의 *예외 집합*을 둔갑)·064 self-advertised(신뢰못할 입력이 보안결정값으로)·063(검증≥저장
제약, 위반값+조치 메시지)·installed-guard-isnt-covering-guard(가드 *설치*≠*적용범위 덮음*: 여긴 가드가
allowlist 단락으로 IP-class 검사를 *건너뛰는* 틈). 공통뿌리=happy-path 초록(정상 host/TTL)→적대자만 비-타깃
리터럴·과길이·`inf` 던짐→codex 적대 필수.

[allowlist,exact-match,short-circuit,ip-literal,is-unspecified,canonical-not-safe,storage-migration,static-to-runtime,column-constraint,defensive-parse,ssrf,adversarial]
