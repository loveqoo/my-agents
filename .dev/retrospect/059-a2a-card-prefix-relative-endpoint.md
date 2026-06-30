# 059 — A2A 카드 prefix-상대 endpoint 구제 + probe 404 정직화 회고

스펙: `docs/spec/071-a2a-card-prefix-relative-endpoint.md`
관련: 060/063(소비경계 url 정규화 — 같은 계열의 후속)·045(probe liveness)·066(normalize-before-guard)·
learning 074(신설)·073/072(적대 rung이 사각을 잡은 동형)

## 무엇을 했나
다른 디바이스에서 카카오페이 sandbox A2A를 connect 등록 → 등록은 성공인데 채팅서 404. 스크린샷의 타
에이전트 진단을 **코드·A2A 스펙으로 확정**: 카드가 service url을 루트상대 `/a2a`로 발행하는데, 카드는
`…/ai-core/ccab-weekly-report/.well-known/agent.json`에서 제공된다(프록시 path-prefix). 우리
`agent_card.py`가 `urljoin(candidate, "/a2a")`로 resolve하면 RFC 3986상 leading-slash는 base path를
버리고 origin루트로 가 prefix가 탈락(`…/a2a`, 404). 게다가 probe가 `status<600`이라 그 404를 live로 봐
**잘못된 endpoint가 online으로 등록**됐다(등록 시점에 못 걸러짐).

수정 2건: (1) `_resolve_card_endpoint` 신설 — 상대 url을 카드가 마운트된 prefix 디렉터리 기준으로
resolve(`urljoin(origin+prefix+"/", raw.lstrip("/"))`), 절대 url은 기존대로 위임. (2) probe가 404/410을
dead로 봄(405/200/3xx/401/403은 live) — route 부재와 method-mismatch를 구분.

## 검증 사다리 3런 (069 항목 5, 비겹침)
1. **단위**(verify_071, 12 resolution + 7 probe): resolve 매트릭스(prefix 보존·절대 passthrough·origin루트
   회귀·dot-segment clamp·host 혼동 차단) + probe 술어. 순수 로직.
2. **라이브**(verify_071_live, 4): 스레드 HTTP 서버로 prefix 하위 루트상대 `/a2a` 카드를 띄워 **실제 장애
   재현** → 실 `connect_agent`+DB로 저장 endpoint가 prefix 보존·옛 버그값 대조·probe live·저장 endpoint
   실도달까지. 카드 fetch→resolve→저장→호출 글루를 실 인프라로 봉합.
3. **적대 codex**(gpt-5.5): P1 없음. F4(dot-segment `..` literal 잔존→프록시 prefix 탈출, P2) 봉합(string
   concat→urljoin), F1(절대 url cross-host, by-design 무회귀)·F3(404 false-dead, status 라벨만) 정직 기록.

## 배운 것 / 함정
- **RFC-정확 ≠ 배포-정확.** `urljoin(base, "/a2a")`는 RFC상 *완벽히 옳다* — 루트상대는 origin루트로 간다.
  그런데 프록시 path-prefix 뒤 원격 앱은 자기를 root로 착각해 `/a2a`를 발행하므로, *발행자 의도*는 mount
  prefix 상대다. "코드가 표준대로 동작"과 "실배포에서 옳음"이 갈리는 지점. → learning 074.
- **URL은 concat 말고 urljoin으로 짓는다.** 내 1차 구현은 `origin+prefix+s` 문자열 concat이라 `..`가
  literal로 남았다(적대 codex F4). `urljoin`은 RFC path-merge로 dot-segment를 canonical화하고 origin서
  clamp한다 — 같은 결과를 더 적은 코드로, 그리고 prefix-탈출 표면 없이. 테스트는 clean input만 써 이 사각을
  못 봤고 **적대 rung만** 짚었다(073/072와 동형: 적대 타자가 단위·라이브 못 보는 *입력공간*을 짚음).
- **liveness probe는 "host 도달"과 "route 존재"를 구분해야 한다.** `status<600`(아무 응답이나 live)은 너무
  관대해 *잘못된 경로*를 healthy로 등록했다 — 등록 시점에 잡았어야 할 신호를 삼킴. 404(route 부재) vs
  405/200(route 존재)을 가르니 오resolve가 등록 단계에서 드러난다. probe-deeper의 변종: "도달=충분"이라는
  단정이 한 겹 아래(route 정확성)를 숨겼다.
- **타 에이전트(다른 디바이스)의 진단을 그대로 믿지 않고 코드·스펙으로 재확정한 게 옳았다.** 진단은
  정확했지만 "우리 코드의 버그"라는 프레임은 부정확 — 실제는 *비표준 카드 + 우리 resolution이 구제 못함 +
  probe가 못 걸러냄*의 합. 책임 소재를 웹(A2A 스펙: url은 절대 강제)으로 확인해 정직하게 분해.

## 처분
- 카드 작성자(카카오페이)에 절대 url 발행 요청은 옵션(스펙상 정답)이나, 우리 소비측이 비표준을 구제하므로
  사용자는 즉시 동작. F1(cross-host 절대 url)·query/`#`는 by-design 수용(guard_url이 host 게이트 유지).
- 자산: learning 074 신설, 073/072와 상호링크(적대 rung 사각 짚기 동형).
