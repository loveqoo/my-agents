# 066 — 가드 앞에 관대 정규화를 새로 끼우면, 스킴으로 거부되던 입력이 가드를 통과할 수 있다

> 후크: 보안 가드(SSRF/검증) **바로 앞**에 입력을 관대하게 절대화/정규화하는 단계를 새로 넣을 때.
> normalize는 *절대화만*, 사설/둔갑 판정은 guard — 단, 정규화가 host를 **둔갑**시키면 guard는 *틀린
> host*를 본다. 그래서 정규화는 userinfo(`@`)·비숫자 포트 같은 둔갑 벡터를 *스스로* 거부해야 한다.

## 명제

guard는 자기가 받은 URL의 host로 사설/공인을 판정한다. guard 앞에 "관대 정규화"를 끼우면 *guard가
보는 host를 정규화가 정한다*. 정규화가 입력을 **다른 host로 둔갑**시킬 수 있으면, 예전에 guard가
스킴(또는 형식)으로 거부하던 값이 이제 *공인 host로 둔갑한 채* guard를 통과한다 — 가드는 그대로인데
가드의 **입력 분포**가 바뀌어 우회가 열린다. 정규화는 "절대화만 한다"는 불변을 *내가* 믿어도, 절대화
방식(스킴 없으면 `http://` 전치)이 colon-form URI를 host 위치가 어긋난 절대 URL로 만들면 불변이 깨진다.

## 표본 (스펙 063, codex 적대 [P1])

D1로 호출 경계 `guard_url(endpoint)` **앞에** `endpoint = normalize_http_url(endpoint)`를 끼웠다.
정규화는 스킴 없는 `host:port`에 `http://`를 전치한다. 그런데 `mailto:user@example.com/a2a`는 `://`가
없어 "스킴 없음"으로 분류돼 `http://mailto:user@example.com/a2a`가 된다 → urlparse/httpx 모두 이를
host=`example.com`(**공인**), userinfo=`mailto:user`로 읽는다. 결과: 예전엔 guard가 비-http 스킴으로
*거부*하던 `mailto:` 입력이, 정규화를 거치자 **공인 host로 둔갑**해 guard를 통과 → Bearer 토큰 포함
A2A 요청이 공격자 통제 공인 host로 샌다(SSRF + 자격증명 누출). `evil.com@127.0.0.1`도 userinfo로
실제 host를 127.0.0.1로 숨겨 표시상 공인처럼 보이게 한다. happy-path(정상 `host:port`)는 전부 초록 —
**적대자만** 이 둔갑 입력을 던진다.

## 처방

1. **정규화가 host를 바꿀 수 있는 모든 형식을 정규화 단계에서 fail-closed.** A2A 엔드포인트는 임베디드
   자격증명을 안 쓰므로(인증=별도 token 필드) `parsed.username/password`가 있으면 거부. 비숫자 포트는
   `parsed.port` 접근 시 ValueError로 거부(`http://example.com:http` 류).
2. **"절대화만"을 *결과*로 단언하지 말고 *둔갑 벡터*로 단언하라.** 정규화 끝에 `scheme∈{http,https} &
   hostname 존재`만 검사하면 둔갑된 host도 통과한다(host=example.com은 "존재"하니까). userinfo/포트
   같은 *어떻게 그 host가 나왔나*를 검사해야 한다.
3. **방어 다중화는 유지하되 그것에 기대지 마라.** percent-encoded `@`(`evil.com%40127.0.0.1`)는
   정규화는 통과하나 hostname에 literal `%40`이 남아 guard의 resolve 실패로 막힌다(2차 방어). 하지만
   1차(정규화)에서 막을 수 있는 raw 둔갑은 1차에서 막아 guard에 *깨끗한 host*만 보낸다.
4. **회귀 고정**: raw userinfo 벡터(U1b)와 encoded-@ 벡터(U1c)를 단위 테스트에 박아, 미래의 정규화
   "개선"이 둔갑 구멍을 다시 열면 즉시 빨갛게.

## 판별 질문

- "이 가드 앞에 입력을 *변형*하는 단계를 새로 넣나?" → 그렇다면 변형이 가드의 *판정 대상(host 등)*을
  바꿀 수 있는지 본다.
- "변형 후 결과만 단언하나, 변형 *경로*도 단언하나?" → 결과만이면 둔갑이 샌다.
- "이 변형이 예전에 가드가 거부하던 입력을 *통과 형태*로 만들 수 있나?" → 그게 새 우회면이다.

## 가족

- `[[installed-guard-isnt-covering-guard]]`·044/057 redirect-SSRF: **가드 설치≠덮음**의 형제 —
  거기선 가드 *검사 지점*과 부수효과 지점이 어긋났고, 여기선 가드 *입력*이 둔갑돼 host가 어긋났다.
  공통 뿌리=신뢰 못할 입력이 보안 결정값(host)으로 흐르는 경로를 끝까지 추적.
- learning 064(self-advertised-address): host가 요청 파생이라 오염 — 064는 *어디서 host가 오나*,
  066은 *정규화가 host를 어떻게 둔갑시키나*. 둘 다 "보안 판정값으로 흐르는 host의 출처/변형 추적".
- `[[adversarial-review-before-destructive-ship]]`·verification-ladder: happy-path 초록이라 자가검증
  구조적으로 못 봄(정상 입력엔 `@`·비숫자 포트 없음) → codex 적대가 둔갑 벡터를 구체화해 적발.
- learning 065(curated-message): 063의 *짝* 결함축 — 065=계약값을 경계가 버림, 066=정규화가 가드
  입력을 둔갑. 둘 다 "경계 한 홉이 끼면 양끝 불변이 깨진다".

[normalize-before-guard, ssrf, userinfo-disguise, host-confusion, fail-closed, defense-in-depth, adversarial, regression-pin]
