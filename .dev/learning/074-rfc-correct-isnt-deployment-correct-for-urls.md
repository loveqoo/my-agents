# 074 — RFC-정확 ≠ 배포-정확: 프록시 path-prefix 뒤 루트상대 URL은 origin으로 풀려 prefix를 잃는다

## 한 줄
제3자가 광고한 **루트상대 URL**(`/a2a`)을 `urljoin(base, "/a2a")`로 풀면 RFC 3986상 *완벽히 옳게*
origin루트로 가지만(`https://host/a2a`), 그 발행자가 **프록시 path-prefix 뒤**(외부 경로 `…/prefix/…`)에
있으면 발행자 의도는 *mount prefix 상대*다 → prefix가 탈락해 호출 시 404. "표준대로 동작"과 "실배포에서
옳음"이 갈린다. 구제: 카드가 *제공된 위치*(prefix)에 상대로 resolve하되 **`urljoin`으로**(string concat 금지
— dot-segment가 literal로 남아 프록시 정규화로 prefix를 탈출하는 표면이 생긴다), 보안 게이트(host 판정)는
호출 시점 그대로.

## 맥락 (spec 071 / retro 059)
- A2A 카드가 service `url: "/a2a"`(루트상대)를 발행. 카드는 `…/ai-core/ccab-weekly-report/.well-known/
  agent.json`에서 제공(reverse-proxy가 `/ai-core/ccab-weekly-report/*`를 내부 root로 매핑). 원격 앱은
  자기를 root로 알아 `/a2a` 발행.
- `urljoin(candidate, "/a2a")` = `https://host/a2a` — RFC상 leading-slash는 authority만 두고 base path를
  버린다. prefix `/ai-core/ccab-weekly-report` 탈락 → 등록은 통과(probe가 404도 live로 봄)·채팅서 404.
- 구제: prefix = candidate에서 well-known 접미 제거한 path. `urljoin(origin+prefix+"/", raw.lstrip("/"))`로
  prefix 디렉터리 상대 resolve → `https://host/ai-core/ccab-weekly-report/a2a`. 결과는 기존 SSRF 정규화를
  그대로 통과(host 판정은 call-time guard_url 불변).

## 왜 중요한가
- **"코드가 표준을 정확히 따른다"가 버그 부재를 뜻하지 않는다.** RFC-정확한 resolution이 *발행자 의도*와
  어긋나는 배포(path-prefix 프록시)가 흔하다. 제3자 URL/카드/웹훅/리다이렉트를 소비하는 모든 경계에서,
  표준 resolution이 실배포 토폴로지에서 옳은지 한 번 더 본다(probe-deeper의 URL판).
- **URL은 문자열 concat이 아니라 `urljoin`(RFC path-merge)으로 짓는다.** concat(`origin+prefix+s`)은 `..`를
  literal로 남겨(`…/prefix/../../admin`) 다운스트림 프록시가 collapse하면 prefix를 탈출한다(적대 codex F4).
  `urljoin`은 dot-segment를 canonical화하고 origin서 clamp한다 — 같은 결과·더 적은 코드·탈출 표면 없음.
- **liveness probe는 "host 도달"과 "route 존재"를 구분해야 한다.** "아무 status나 응답=live"(status<600)는
  *잘못된 경로*도 healthy로 등록해 오resolve를 등록 단계에서 못 잡는다. 404(route 부재) vs 405/200(route
  존재)을 가르면 신호가 등록 시점에 드러난다(단 false-dead는 status 라벨만 좌우, 사용성 무관 — 수용 가능).
- **적대 rung이 또 단위·라이브의 사각을 짚었다.** 단위·라이브는 *clean input*만 써 dot-segment(F4)를 못 봤다.
  073(저장계층 인덱스)·072(가드 열거 여집합)과 동형: 적대 타자는 자가 테스트가 안 넣는 *입력공간/계층*을
  공략한다. 비겹침 사다리에서 적대 rung의 고유 가치는 "내가 상상 안 한 입력".

## 다음에 이렇게
1. **제3자가 광고한 상대 URL을 절대화할 땐 "어디에 상대인가"를 배포 토폴로지로 정한다** — origin루트(RFC
   기본)가 아니라 *그 문서가 제공된 위치/mount*에 상대일 때가 많다(프록시 prefix). 표준값과 의도값이
   갈리면 의도값으로 구제하되 *근거*(발행자 의도·커뮤니티 합의)를 남긴다.
2. **부분에서 URL을 조립하면 무조건 `urljoin`.** concat은 `..`/중복슬래시/dot-segment를 canonical화 못 해
   path 정규화 차이를 무기로 내준다. 조립 후 `normalize`/host-guard를 *결과*에 다시 돌린다(절대화·검증 한 곳).
3. **liveness/health는 reachable과 correct-route를 따로 본다.** "응답 옴=live"는 잘못된 경로를 healthy로
   숨긴다. 가능하면 route-존재 신호(405 vs 404)나 프로토콜 핸드셰이크(JSON-RPC ping)로 구분.
4. **URL resolution은 단위 테스트에 *적대 입력*을 직접 넣는다** — `..`·`%2e%2e`·`/\`·`//evil`·cross-host
   절대·userinfo. clean input만 있으면 적대 rung 전엔 사각으로 남는다.

## 연결
- 사례: spec 071, retro 059. 같은 계열: spec 060/063(소비경계 url 정규화), 045(probe), 066(normalize-
  before-guard — 절대화·host판정 분리).
- learning: 073(계층별 봉합·적대 rung이 사각 짚음), 072(방어 열거 여집합), 044/055(installed-guard ≠ 전계층
  덮음 — "한 곳 옳음 ≠ 전 경로 옳음"의 동류).
- memory: probe-deeper-before-concluding("표준대로 동작"이 "옳음"을 숨김), verification-ladder-three-rungs
  (적대 rung이 단위·라이브의 입력공간 사각을 잡음).
