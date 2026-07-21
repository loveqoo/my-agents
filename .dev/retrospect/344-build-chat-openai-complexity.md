# 344 — build_chat_openai 복잡도 분해(스펙 416)

## 발단
개발자 "코드 복잡도 체크" → `make complexity`(xenon 절대 상한 C) 유일 실패: `model.py build_chat_openai`
CC **31(E)**. 스펙 411에서 wire 기반 파라미터 배선이 한 함수에 누적된 선재 부채. "리팩터하되 과거
이력·방법을 파악해 복리를 최대한 적용"하라는 지시.

## 한 일
동작 보존 추출 — `_resolve_wire_params`(PARAMS 배선 루프)·`_pool_key`/`_pool_remember`(클라 풀)를
private 헬퍼로 빼고 공개 함수는 얇은 오케스트레이터로. CC 31(E) → **15(C)**, 게이트 통과.

## 배운 것 — 복리는 "설계 논의 0"으로 나타난다(retrospect 228 계보)
이 리팩터는 새 판단이 거의 없었다. Context에서 인덱스로 관련 학습 4개를 싸게 꺼내 **그대로 조립**했다:

1. **extract-body-keep-wrapper(learning 126)** — 본체를 헬퍼로 빼고 공개 함수는 얇게. 어떤 구조를
   만들지 고민할 필요 없이 이미 검증된 형태가 있었다.
2. **no-wholesale-drop(learning 155)** — 추출이 분기를 조용히 누락하면 안 된다. 스펙에 보존 목록
   (temperature default·max_tokens 스킵·chat_template_kwargs·풀키 구성·LRU)을 **먼저 적고** 대조하며
   옮겼다. 155가 "리팩터의 통째 교체가 새 필드를 파괴"를 경고했기에 목록화가 반사적이었다.
3. **logic-surgery-needs-live-roundtrip(retrospect 167)** — import·mypy 아닌 verify_411 24/24·410 14/14
   +실채팅으로 동작 보존 확인.
4. **measure-before-after(retrospect 222)** — 자가선언 대신 radon으로 31→15 실측 마감.

**핵심**: 인덱스 층([[index-layer-for-context-recall]])이 없었으면 이 4개를 통독으로 찾아야 했다.
한 줄 후크로 골라 바로 적용 → Context 비용이 낮아 복리가 실제로 실린다. 인덱스가 "회고를 상기
싸게 만든다"는 설계가 이 작은 작업에서 그대로 증명됐다.

## 부수 관찰 — 게이트가 INDEX 누락을 선제 포착
spec 416 파일을 만들고 INDEX 줄을 Compounding으로 미뤘더니, 그물 검증에서 verify_043(인덱스 정합)이
"파일 있는데 인덱스에 없음: 416"으로 잡았다. 리팩터 회귀가 아니라 **규율을 게이트가 강제**한 것 —
"새 자산=같은 턴 인덱스 한 줄"을 사람 기억이 아니라 테스트가 지킨다([[net-runs-are-exclusive]] 형제:
자산 생성+INDEX는 한 단위).

## 자산화 후보(관련)
[[index-layer-for-context-recall]] — learning 126·155, retrospect 167·222·228 재사용(신규 학습 없음, 복리 실증).
