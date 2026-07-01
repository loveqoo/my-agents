# 084 — 능력 브로커 kind 확장: RAG provider (Phase 2, 셋째 provider)

스펙 103. 능력 브로커에 세 번째 provider(kind=rag, 문서 컬렉션 검색)를 붙였다. spec 100이
"1개 시임에 여러 kind"라 주장했고, 101(MCP)이 둘째로 실증, 102가 오케스트레이션 전략으로 시임을
한 번 더 눌렀다. 103은 **셋째 provider로 시임 무누수를 다시 측정**한 것 — 게다가 처음으로
**읽기전용(부수효과 0)** provider라, 그동안 A2A/MCP가 강제하던 HIL·승인 기계가 여기선 전부 꺼진다.

## 무엇을 했나

- `RagProvider`(kind=rag)를 `broker.py`에 추가. cap_id = `rag:<collection_name>`(1레벨, 이름에
  콜론/슬래시 허용). McpProvider를 거울삼아 6메서드 시임 계약(candidates/load/describe/invoke/
  node_label/approval_for) 그대로 구현.
- **정책은 손 안 댐**: `_permitted`(allowlist∩RBAC·deny-by-default·존재비노출)는 브로커 단일 지점에
  그대로. rag는 1레벨이라 mcp의 "서버 전체 허용" 특례가 필요 없어 기본 `cap_id in allow` 경로가 정답.
  `build_broker`의 `enforce(id, "capability:rag", "invoke")`도 kind만 바뀌어 자동 처리.
- **invoke는 기존 검색 코어 재사용**: `runtime.search_collections`(스펙 037 본체, 072로 추출) +
  결과 포맷은 `build_rag_tool` 클로저에서 `format_rag_hits`를 **추출해 공유**(A안). 이로써
  엔드포인트·인-챗 도구·브로커 **세 입구가 한 코어**를 쓴다(drift 0).
- 결과 trust=untrusted(문서 내용=데이터 채널, learning 100). `approval_for`는 **항상 None**
  (읽기전용 = 비가역 부수효과 없음 = HIL 불필요).
- 검증 사다리 3런: verify_103(단위 순수 + 실 mock임베딩·실 DB 통합, 46 ok) + 무회귀
  (072/100/101/102) + codex 적대 리뷰.

## codex 적대 리뷰 — 3판정

- **[P1] 인-챗 RAG 도구(`vectorTables`)가 브로커 정책 밖** — 사실이나 **정직한 경계**(코드결함 아님).
  `vectorTables`는 에이전트 저작자가 정의 시점에 묶는 것(페르소나·모델 선택과 동급 신뢰), `rag:`
  능력은 런타임 위임을 유저 RBAC로 게이트하는 것 — **다른 신뢰 모델**. 103은 위임 능력을 *추가*할
  뿐 기존 도구를 브로커 뒤로 옮기지 않는다. complement 공격이 비-브로커 경로를 찾았지만 안전 위반이
  아니므로 **스펙 비목표에 OUT 기록 + 안전 불변식(H4/H5=브로커 rag는 정책 게이트됨) 테스트**로 정직화
  (learning [[complement-attack-can-be-honest-boundary]] 재적용).
- **[P2] 질의 길이 무제한** — 엔드포인트는 스키마서 4000자로 막지만 도구·브로커 경로는 상한 없음.
  → **공유 코어 `search_collections`에 4000자 상한 1회**. 엔드포인트는 이미 ≤4000이라 무영향,
  도구·브로커가 함께 경계를 얻는다(교차입구 불변식은 코어에 = learning 103).
- **[P2] 빈 이름 `rag:`** — 컬렉션 이름 검증 부재로 `rag:`가 능력으로 승격 가능(운영 footgun).
  → 브로커 파싱 층(candidates/load)에서 빈 리소스 이름 방어. 근본(컬렉션 이름 min_length)은
  스펙 037 CRUD 영역이라 경계로 기록.

## 잘된 것

- **셋째 provider가 시임을 다시 측정**했고 통과 — 정책은 정말 provider와 분리돼 있었다(rag 추가에
  `_permitted` 분기 0줄). 039/085/101/102가 쌓은 "둘째/셋째 구현이 추상을 측정한다"의 재확인.
- **읽기전용이 통합을 싸게 만듦**: approval_for=None 한 줄로 HIL 기계 전부 우회, 그러나 정책은
  완전 적용. **두 게이트(정책/승인) 분리**가 여기서 값을 했다 → learning 103.
- 공유 코어 재사용으로 drift 0을 *구조적으로* 보장(H7이 provider invoke == 코어+포맷 실측).

## 아쉬웠던 것 / 다음

- P2 두 건은 codex가 짚기 전엔 안 보였다 — happy-path 초록(46 ok)은 상상한 실패만 본다. 적대
  타자검증이 여집합(무제한 입력·빈 id)을 잡았다. 검증 사다리 ③런의 값을 또 확인.
- 다음 축: memory provider(kind=memory)는 per-user 데이터라 **인가 입도**(per-cap·per-user 소유권)를
  선행 강제한다 — 103이 미룬 그 빚. 백로그 Phase 2-b/인가 입도로.

관련: [[complement-attack-can-be-honest-boundary]] · learning 100·101·102 · 스펙 103.
