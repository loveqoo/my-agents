# 082 — A2A endpoint resolution 꼬리 중복(`/a2a/a2a`) collapse (071 누락 케이스)

## 배경 (실측 재현)

사용자: a2a로 등록한 외부 에이전트가 Playground에서 동작 안 함 — 저장 endpoint 뒤에 `a2a/a2a`가 붙음.
요구: **"url 마지막에 a2a가 있으면 추가로 a2a를 안 붙인다."**

071(`_resolve_card_endpoint`)은 카드가 광고한 루트상대 `/a2a`를 *카드가 마운트된 prefix 하위*로
resolve해 프록시 path-prefix 배포(kakaopay `/proxy/ccab/a2a`)의 404를 구제했다. 그러나 **prefix 자체가
이미 `/a2a`로 끝나면** — 카드를 `http://h/a2a/.well-known/agent-card.json`에서 가져왔거나 base가
`/a2a`인 경우 — `/a2a`(prefix) + `/a2a`(카드 상대) = `http://h/a2a/a2a` 중복이 된다.

재현(`_resolve_card_endpoint(raw, candidate)`):

| 케이스 | raw(card.url) | candidate | 현재 결과 | 판정 |
|---|---|---|---|---|
| kakaopay prefix | `/a2a` | `…/proxy/ccab/.well-known/agent-card.json` | `…/proxy/ccab/a2a` | 정상 |
| **prefix=/a2a + 루트상대** | `/a2a` | `…/a2a/.well-known/agent-card.json` | `…/a2a/a2a` | **버그** |
| **bare a2a + prefix /a2a** | `a2a` | `…/a2a/.well-known/agent-card.json` | `…/a2a/a2a` | **버그** |
| **base=/a2a 직접 서빙** | `/a2a` | `…/a2a` | `…/a2a/a2a` | **버그** |
| 절대 url | `http://h/a2a` | `…/.well-known/…` | `http://h/a2a` | 정상 |
| 표준 root + 루트상대 | `/a2a` | `…/.well-known/…` | `http://h/a2a` | 정상 |

→ 중복은 **mount prefix의 꼬리 == 카드 상대경로**일 때만. 그 외 071 동작은 불변이어야 한다(무회귀).

## 목표 (완료 조건 — 측정 가능)

상대 카드 url을 prefix 하위로 resolve할 때, **prefix가 이미 그 상대경로(꼬리)로 끝나면 중복을 부착하지
않고 `origin + prefix`를 그대로 endpoint로** 쓴다(꼬리 collapse). 위 표의 버그 3행이 `…/a2a`로 교정되고,
정상 3행(kakaopay·절대·표준 root)은 그대로 유지된다.

## 설계

### `agent_card.py::_resolve_card_endpoint`
절대/스킴보유 분기는 불변(prefix 무관). 상대 분기만:

```python
rel = s.strip("/")                       # "/a2a"·"a2a" → "a2a", "/v1/a2a" → "v1/a2a"
if rel and (prefix == "/" + rel or prefix.endswith("/" + rel)):
    resolved = origin + prefix           # prefix 꼬리가 이미 카드 경로 → 중복 부착 금지
else:
    resolved = urljoin(origin + prefix + "/", rel)   # 071 기존 동작
return normalize_http_url(resolved)
```

- **정확 꼬리 매치만** collapse(`prefix == "/"+rel` 또는 `prefix.endswith("/"+rel)`). 부분 겹침
  (prefix `/a2a`, rel `a2a/rpc`)은 collapse 안 함 — 모호하므로 071 기존 urljoin 유지(보수적).
- kakaopay(`/proxy/ccab` ∌ `/a2a`)는 분기 안 타 무회귀. 표준 root(prefix="")도 `"".endswith("/a2a")`=False라 무회귀.

### 경계 (적대 리뷰 071 F4 불변 유지)
collapse 결과 `origin + prefix`는 **이미 카드를 fetch한 candidate의 path 부분집합**(host 고정·prefix는
candidate를 urlparse한 canonical path) — 새 host·`..` 탈출 없음. `normalize_http_url`이 그대로 후행(SSRF/
userinfo/port 검증 동일). string-concat 아닌 부분문자열이라 prefix 탈출 표면 없음.

## 적용 범위
`_resolve_card_endpoint`는 `fetch_card`의 단일 resolution 지점 → connect·register·**resync(081)** 모두
일괄 교정. 이미 `/a2a/a2a`로 저장된 행은 **재동기화(081 자가치유)** 1회로 교정되거나 삭제+재연결로 해소.

## 검증 사다리 3런 (비겹침)
1. **단위**: 위 표 6행 매트릭스 — 버그 3행 collapse·정상 3행 무회귀 + 추가(`/v1/a2a` 꼬리 collapse, 부분겹침 미collapse).
2. **라이브 통합**: prefix=`/a2a` 마운트 스레드 서버(well-known 카드 url=`/a2a`) → connect → 저장 endpoint가
   `…/a2a`(중복 아님)·probe live·그 endpoint로 POST 도달. 071 라이브(`/proxy/ccab`)도 재실행해 무회귀.
3. **적대 codex**: collapse가 prefix 탈출·host 혼동·`..`·SSRF 새 입구를 여나? 정상 prefix(kakaopay)를 과도
   collapse하나? "보장 목록의 여집합".

## RBAC 체크리스트 적용 여부
**미적용** — 네트워크 endpoint 경로 resolution(소유권·user_id·테넌트·`_own_scope` 무관). 071과 동일 표면.

## 검증 결과 (3런 그린)
- 단위(verify_082_collapse) 매트릭스 8: 버그 3행 collapse·정상 3행(kakaopay·절대·표준root) 무회귀·다중꼬리
  `/v1/a2a` collapse·부분겹침 `a2a/rpc` 미collapse.
- 라이브(verify_082_collapse) 4: prefix=/a2a 마운트 스레드 서버 connect → 저장 endpoint `…/a2a`(중복 아님)·
  probe live·그 endpoint로 POST 도달.
- 회귀: 071(card 10+probe 7 / live 4)·081(unit 7 / live 8)·045·060 PASS.
- 적대 codex: 핵심 보장 모두 성립(host 불변·`..` 미보존·정확 꼬리매치라 정상 prefix 오collapse 없음·절대 url은
  collapse 도달 불가·SSRF/normalize 우회 없음). 신규 결함 0(인코딩 dot-segment 노트는 candidate-path 파생, 비도입).

## 완료 체크
- [x] `_resolve_card_endpoint` 꼬리 collapse(정확 매치만)
- [x] 단위 매트릭스(버그 3 collapse·정상 3 무회귀·꼬리/부분겹침 추가) 그린
- [x] 라이브(/a2a 마운트 도달 + /proxy/ccab 무회귀) 그린, 071/081 무회귀
- [x] 적대 codex(prefix 탈출·SSRF 여집합) 그린
