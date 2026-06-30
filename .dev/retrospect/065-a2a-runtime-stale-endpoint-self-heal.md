# 065 — A2A 런타임 stale endpoint 자가치유(resync) + 호출 폴백·오프라인 정직화 회고

## 무엇을 했나
사용자: "071 테스트 잘 안 됨 — 외부 에이전트 응답 오류 404". 다른 에이전트 리포트(문제 A/B/C)를
전달받아 스펙 081로 닫았다. resync가 카드 출처(cardUrl)에서 재fetch·재resolve해 stale endpoint를
자가치유(P1), 호출 실패에 행동가능 안내(P2), stream 404/405→message/send 1회 폴백(P3).

## 핵심 판단 1 — 전달받은 리포트를 액면 수용하지 않고 *원인을 재분별*
리포트는 3문제를 동급으로 나열했지만, A2A 표준에서 `message/stream`·`message/send`는 **같은 endpoint
URL**로 가는 JSON-RPC 메서드다. 따라서 그 URL이 404면 send 폴백(C)도 같은 URL이라 똑같이 404 —
C는 "stream만 별도 라우트로 둔 비표준 서버"에만 듣는 저수율 방어책이다. 사용자의 404의 **1순위 원인은
B**(저장된 endpoint가 틀림 — 071의 원래 카카오페이 prefix 버그와 동류). 리포트가 C를 1순위처럼 적었어도
구조를 따져 B로 무게를 옮겼고, 스펙에 그 분별을 정직 기록했다([[probe-deeper-before-concluding]]).

## 핵심 판단 2 — 파생값 stale의 진짜 봉합은 "출처 저장 + 재파생 경로"
endpoint는 카드에서 *resolve된 파생값*이다. 071이 resolution을 고쳤지만 그 보정은 **fetch_card 시점에만**
걸려, 071 이전 등록분·원격 변경분의 stale endpoint는 안 고쳐졌다. resync는 있었지만 `last_sync="방금"`만
찍는 **표시용 no-op**이었다 — 재파생을 안 했다. 봉합은 두 가지가 필요했다: (1) 파생의 **출처**(cardUrl)를
저장, (2) refresh 경로가 타임스탬프만 찍지 말고 **실제로 재파생**(re-fetch→re-resolve→endpoint·status
갱신). 출처를 안 저장했으면 재연결 없이는 못 고친다(learning 084).

## 핵심 판단 3 — 적대 codex가 내가 *상속한* 결함을 짚음
codex가 stream 404/405 분기의 `await resp.aread()`(무경계 에러 바디 버퍼링)를 F1로 짚었다. 기존
`>=400` 경로와 동일 패턴이라 "원래 그래"로 넘길 수 있었지만, 내 새 분기는 폴백 직전이라 본문이 아예
불필요 → 읽지 않고 `async with`가 닫게 해 **기존보다 엄격하게** 고쳤다(memory: cap-the-raw-source,
[[adversarial-review-before-destructive-ship]]). F2(config 재할당 last-writer-wins)는 앱 전역 JSONB
모델이 낙관락 없는 동일 구조라 수용·기록, F3(probe raise→500)는 probe_endpoint가 total이라 성립으로 분별.

## 검증 — 3런 비겹침, 객관 측정
- 단위(verify_081_unit) 7: C 폴백 3(stream404→send 텍스트/단일endpoint 404 이중방출 없음/500 폴백 안 함)
  + A 술어 2(무방출 부가/부분스트림 뒤 미부가).
- 라이브(verify_081_live) 8: connect cardUrl 저장→endpoint 손상→resync 교정→status→호출 도달→레거시 no-op.
  실 DB+스레드 A2A 서버(071 라이브 패턴 재사용 — prefix-마운트 카드).
- 회귀 045/057/060/063/071/042 PASS. 통합 rung만이 "손상→resync→교정→도달" 글루를 잡음(단위는 못 잡음).

## 잘된 것 / 다음에
- 잘됨: 전달 리포트를 구조(A2A 단일-endpoint)로 재검해 1순위(B)를 바로잡고 C는 저수율 방어로 정직 강등.
- 잘됨: 파생 stale을 "표시 갱신"이 아니라 "출처 저장+재파생"으로 근본 봉합.
- 잘됨: 적대 지적 중 내 분기를 기존보다 엄격히(F1), 나머지는 수용/성립으로 분별(과잉수정 회피).
- 다음: **파생값을 컬럼에 저장할 땐 같은 턴에 "출처도 저장했나 + refresh가 재파생하나"를 묻는다**
  (learning 084). 071→081은 "resolution을 고쳐도 stale 잔존분은 별도 자가치유 경로가 필요"의 사례.

## 자산
- 스펙: docs/spec/081-a2a-runtime-call-path-hardening.md
- learning: 084(파생값 저장 시 출처도 저장하고 refresh는 재파생하게)
- 코드: agents.py(cardUrl 저장+resync 자가치유), chat.py(_a2a_stream 안내), a2a_client.py(stream 404/405 폴백)
- 테스트: tests/verify_081_unit.py, tests/verify_081_live.py
