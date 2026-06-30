# 075 — 내부 도구를 직접 엔드포인트로 승격하면 입력 신뢰경계가 리셋된다

## 상황
스펙 072에서 retrieval 본체를 공유 코어 `search_collections`로 빼고, 그걸 (a) 인-챗 LangGraph 도구
`build_rag_tool`과 (b) 새 `POST /collections/{cid}/search` 엔드포인트가 **둘 다** 호출하게 했다.
같은 코어인데 적대 codex가 엔드포인트 쪽에만 P2 두 개를 짚었다.

## 배운 것 (일반화)
**같은 코드라도 입구가 바뀌면 입력 신뢰경계가 바뀐다.** 내부 도구로 호출될 때 코어의 입력은 상류가
암묵적으로 제한해준다 — LLM이 query 길이를 알아서 줄이고, 도구를 연결하는 코드가 모델 kind/완전성을
이미 보장한다. 그 코어를 **사용자 직접 POST 엔드포인트**로 승격하면 그 암묵 보호가 사라지고 입력이
**raw로** 도착한다:

- **길이/크기**: LLM은 query를 짧게 주지만, 직접 POST는 임의 크기 → 임베딩 provider 60초 점유·메모리.
  → 새 입구에서 `max_length`/raw-byte cap을 *직접* 건다(cap-the-raw-source-not-the-buffer와 같은 결).
- **참조 무결성**: 도구 연결 경로는 embedding 모델이 `kind=embedding`임을 전제하지만, 모델은 나중에
  PUT로 chat kind로 바뀔 수 있다. 엔드포인트가 그걸 막지 않으면 "설정 오류 400"이 아니라 provider
  실패 502로 뭉개진다. → 새 입구에서 종류 가드(`em.kind != "embedding"` → 400)를 *직접* 건다.
- **의미 검증의 층 분리**: Pydantic `min_length=1`은 strip *전* 길이라 "   "(공백)가 통과 → 코어에서
  502. 길이 검증(min/max_length)과 의미 검증(비공백)은 다른 층 — `@field_validator`로 strip 후 blank를 422로.

## 어떻게 적용하나
내부 함수/도구를 외부 엔드포인트(또는 공개 API)로 승격할 때, "코어가 같으니 검증도 같다"고 가정하지 말 것.
체크: **상류가 대신 막아주던 입력 제약을 새 입구가 스스로 재검증하는가** —
(1) 크기/길이 상한(raw에서), (2) 참조 대상의 종류/상태 가드, (3) 의미 검증을 올바른 층에서.
빠뜨리면 "설정 오류로 막아야 할 것"이 하류 502로 뭉개지거나 자원 고갈 입구가 된다.

## 근거
- 적대 codex(rung 3)가 happy-path·단위가 못 본 두 입구를 짚음 — 같은 코어, 다른 신뢰경계.
- 봉인: schemas.py `CollectionSearchIn.query max_length=4000` + `@field_validator` 비공백,
  rag.py search_collection `em.kind != "embedding"` 가드. 테스트 B6/B7(verify_072).
- 관련: [[cap-the-raw-source-not-the-buffer]] (raw에서 캡), [[installed-guard-isnt-covering-guard]]
  (가드 검사지점≠발생지점), verification-ladder-three-rungs(적대 rung만이 이 입구를 잡음), probe-deeper.
