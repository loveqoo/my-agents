# 085 — 맥락상대 경로 resolution은 꼬리에 멱등이어야 한다: base가 이미 그 세그먼트로 끝나면 또 붙이지 마라

## 상황
스펙 071이 프록시 path-prefix 배포의 404를 고치려, 카드가 광고한 루트상대 `/a2a`를 *카드가 마운트된
prefix 하위*로 resolve하게 했다(kakaopay `/proxy/ccab` + `/a2a` → `/proxy/ccab/a2a`, 정상). 그런데
**prefix 자체가 이미 `/a2a`로 끝나는** 토폴로지(카드를 `…/a2a/.well-known/…`에서 가져오거나 base가
`/a2a`)에선 `/a2a`(prefix) + `/a2a`(카드) = `…/a2a/a2a` **중복**이 됐다 — 사용자 외부 에이전트가 Playground에서 404.

## 배운 것 (일반화)
- **"상대 경로를 base에 붙인다"는 base가 그 경로의 꼬리를 *이미 포함*할 때 중복을 만든다.** prefix-상대
  resolution(또는 어떤 join/concat heuristic)은 **꼬리에 멱등이어야 한다**: 붙이려는 세그먼트로 base가
  이미 끝나면 또 붙이지 않는다. 071은 "prefix 하위로 해석"만 보고 prefix==advertised-tail 경우를 놓쳤다.
- **같은 입력이 토폴로지에 따라 다른 정답을 갖는 heuristic은 본질적으로 모호하다.** 루트상대 `/a2a`는
  "origin 기준"(표준 RFC)일 수도 "prefix 기준"(071 프록시 의도)일 수도 있다 — 071은 후자로 고정해 전자
  케이스(prefix가 곧 endpoint)를 깨뜨렸다. 모호하면 ① 멱등 collapse(꼬리 중복 제거, 이번 선택, 저비용)
  또는 ② **liveness로 disambiguate**(두 해석을 probe해 도달하는 쪽 채택, 045/084의 진실=도달)로 닫는다.
  이번엔 사용자가 동작을 정확히 지정("url 끝이 a2a면 추가 a2a 금지")해 ①로 충분했다.
- **collapse/heuristic은 *정확 꼬리 매치*로만 — 부분 겹침은 건드리지 마라.** prefix `/a2a` + rel `a2a/rpc`
  같은 부분겹침까지 collapse하면 정상 경로를 깬다. 보수적으로 `prefix == "/"+rel or prefix.endswith("/"+rel)`
  만. codex가 정상 prefix(`/proxy/ccab`·`/proxy/ccab-a2a`·`/proxy/a2a2`) 오매치 없음을 확인.
- **경계는 base에서만 파생되게 두면 새 입구가 안 열린다.** collapse 결과 `origin + prefix`는 이미 카드를
  fetch한 candidate의 부분집합(host 고정·urlparse canonical path) — rel이 host·`..`를 주입 못 함,
  normalize_http_url 후행 유지. heuristic을 고쳐도 신뢰경계(learning 064·084)를 안 넓히는 게 핵심.

## 어떻게 적용하나
경로/URL/식별자를 base에 *상대로 합성*할 때(prefix-mount·urljoin·문자열 concat·네임스페이스 접두):
① base가 붙이려는 꼬리 세그먼트로 **이미 끝나는가?** → 그렇다면 붙이지 말고 base를 그대로(멱등).
② 같은 입력이 배포 토폴로지에 따라 다른 정답이면 heuristic은 모호 → 멱등 collapse 또는 **probe로
   disambiguate**(도달하는 해석 채택). 한쪽으로 고정하면 반대 토폴로지가 깨진다.
③ collapse는 **정확 꼬리 매치만**(부분겹침 제외 — 정상 경로 보존).
④ 합성 결과는 base 파생값만 쓰고(host·canonical path), 상대 입력이 host/`..`를 주입 못 하게 + 정규화 후행.
⑤ 검증은 **버그 토폴로지 + 정상 토폴로지를 같은 매트릭스로** — 고친 케이스만 보면 무회귀를 못 잡는다.

## 근거
- 스펙 082: `_resolve_card_endpoint` 상대 분기에 `rel = s.strip("/")`; `prefix == "/"+rel or
  prefix.endswith("/"+rel)`이면 `origin + prefix`(collapse), 아니면 071 urljoin 유지.
- 검증 verify_082_collapse: 단위 8(버그 3 collapse·정상 3 무회귀·다중꼬리·부분겹침 미collapse) + 라이브 4
  (prefix=/a2a connect → `…/a2a` 중복 없음·probe live·POST 도달). 071/081/045/060 무회귀. 적대 codex 신규결함 0.
- 관련: 071(prefix-상대 resolution 자체)·084(파생값=출처 저장+재파생; 이미 `/a2a/a2a` 저장분은 resync로
  교정)·045(probe=liveness 진실, ②의 disambiguate 근거), [[move-breaks-references-both-directions]](경로
  합성의 신뢰경계), memory: probe-deeper(전달 보고를 재현으로 확정).
