# 051 — A2A endpoint 호출 경계 정규화 회고 (스펙 063)

> 짝/선행: 060(등록 시점 정규화)·061(A2A 노출). 선행 자산: learning 065(계약은 경로 전체에서
> 유지)·042(SSRF 가드)·retrospect 049/050. 실버그 레포트: A2A 에이전트 채팅 버블에 "[오류] URL은
> http(s) 절대 URL이어야 합니다"만 반복.

## 무엇을 했나

사용자 스샷 버그를 probe-deeper(추측 금지)로 코드 재현해 확정: spec 060이 정규화를 **등록 시점에만**
걸었기에, 060 *이전*에 만들어졌거나 정규화를 건너뛴 경로의 에이전트는 `endpoint`에 `http(s)://`
스킴이 없는 채 저장돼 있고, 채팅 시 호출 경계 `guard_url(endpoint)`가 "절대 URL이어야" 로 거부. 이건
**learning 065 패턴 그 자체** — 계약(절대 URL)이 등록 홉에선 지켜졌어도 *저장→호출* 홉이 stale 값을
재정규화 없이 신뢰하면 깨진다. 견고한 픽스 위치는 **소비(호출) 경계**다.

처방 3겹: **D1**(핵심·자가치유) `a2a_client.a2a_stream`에서 `guard_url` 앞에 `normalize_http_url`을
끼워 모든 outbound A2A 호출의 단일 chokepoint에서 절대화. **D2**(빌더 하드닝) `_build_external_agent`
·`_build_code_agent_from_card`가 `_norm_endpoint`로 저장값 자체를 청결화(실패 시 raw 보존→등록 500
방지, D1이 2차 방어). **D3**(stale 데이터) `migrate_063` — 기본 dry-run, `--apply`만 쓰기, 안전 행만,
멱등, compare-and-set으로 lost-update 방어.

## 핵심 통찰 (가장 비싸게 배운 것)

**가드 앞에 관대 정규화를 새로 끼우면 가드의 *입력 분포*가 바뀐다.** codex 적대 [P1]: `mailto:user@
example.com/a2a`는 `://`가 없어 "스킴 없음"으로 분류돼 `http://mailto:user@example.com/a2a`로 전치
→ host=`example.com`(공인), userinfo=`mailto:user`로 둔갑 → 예전엔 guard가 비-http 스킴으로 *거부*하던
값이 이제 *공인 host로 둔갑한 채* guard를 통과해 Bearer 토큰이 공격자 호스트로 샌다. "정규화는 절대화만
하고 사설 판정은 guard"라는 보안 불변을 *내가 믿어도*, 절대화 방식이 host를 둔갑시키면 guard는 *틀린
host*를 본다. 고침: 정규화 단계에서 userinfo(`@`)·비숫자 포트를 **fail-closed**로 거부해 guard에
*깨끗한 host*만 전달(learning 066). 이게 핵심 학습이라 별도 자산화했다.

## 무엇이 잘 됐나

- **probe-deeper로 단정 회피**: 스샷 한 줄을 "URL 형식 문제"로 단정하지 않고 호출 연쇄를 코드로
  재현해 *stale 저장값 + 호출 경계 신뢰*라는 진짜 원인을 잡았다(메모리 probe-deeper 적용).
- **비겹침 검증 사다리 4 rung**이 각자 다른 결함을 잡았다: 단위(시맨틱·둔갑 회귀)·라이브 통합(실 API
  자가치유 + 마이그레이션 왕복)·적대(codex P1 SSRF·P2 lost-update)·무회귀(060·IPv6). 특히 통합 rung만이
  "주입한 stale 행이 채팅서 실제로 자가치유되는가"를 실측했다(verification-ladder 메모리 재확인).
- **codex 적대가 자가검증이 구조적으로 못 보는 둔갑 벡터를 적발.** happy-path는 전부 초록이었다 —
  정상 `host:port`엔 `@`·비숫자 포트가 없으니까. 적대자만 둔갑 입력을 던진다.

## 무엇이 아쉬웠나 / 다음에

- **first-fix 휴리스틱 버그**: P1 1차 수정에서 `parsed.port is None and ":" in netloc`로 비숫자 포트를
  잡으려다 bare IPv6(`http://[::1]`)를 false-reject. 깔끔한 `try: parsed.port`(비숫자면 ValueError,
  IPv6는 None 안전)로 교체. 교훈: 형식 휴리스틱은 *정상 입력의 변종*(IPv6 등)을 먼저 회귀에 박아라.
- **앞 단계(060)가 "등록 시점만" 고친 게 이 버그의 씨앗.** 계약을 *한 홉*에서만 강제하면 다른 홉의
  stale 데이터가 남는다 — 계약은 경로 전체(저장·호출·표시·probe)에서 같은 불변으로 강제해야 한다.
  D1+D2+D3가 그 전체 정합을 노린 이유.

## 검증 (완료조건 대비)

단위 `verify_063_unit.py` PASS(U1~U5 + U1b raw-userinfo + U1c encoded-@ 회귀)·라이브 `verify_063_live.py`
PASS(실 API 자가치유 + 마이그레이션 dry→apply→멱등 왕복)·060 무회귀 PASS·codex 적대 1차 [P1]+[P2]
적발→수정→재점검 "P1 closed"(전 벡터 ValueError, encoded-@ guard 차단, 잔여 우회 없음).

learning 066 [normalize-before-guard,ssrf,userinfo-disguise,host-confusion,defense-in-depth,verification-ladder,adversarial]
