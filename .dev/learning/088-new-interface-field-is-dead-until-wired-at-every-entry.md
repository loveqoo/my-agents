# 088 — 인터페이스에 새 필드를 더하면 *모든 입구*에서 다뤄질 때까지 죽은 것이다

## 언제

config/dataclass/Protocol 같은 공유 인터페이스에 **새 필드를 추가**할 때 — 특히 그 필드를 *읽는*
곳(소비)과 *쓰는/빌드하는* 곳(생성·갱신·직렬화·컨텍스트 적재)이 여러 입구로 흩어져 있을 때.
(스펙 085에서 `AgentConfig.impl`(런타임 구현 키)·`AgentBuildContext.overrides`(원본 오버라이드) 두
필드를 더했고, codex 적대 리뷰가 둘 다 *일부 입구에서만 살아있음*을 F1·F4로 짚은 사례.)

## 핵심

새 필드는 **모든 입구가 그걸 다룰 때까지 "살아있지" 않다.** 그 필드가 *새것*이라 아직 아무도
단언하지 않으므로, 빠뜨린 입구는 **happy-path 초록인 채로** 그 필드를 떨어뜨린다. 두 전형 실패:

1. **full-replace 쓰기 = silent drop.** 갱신 입구가 `body.model_dump()`/통째 직렬화로 레코드를 교체하면,
   요청에 그 필드가 *없을 때* 기본값(보통 None)이 기존 값을 덮어쓴다. 폼/클라이언트가 아직 그 필드를
   안 보내면(SPA 미배선) 편집 한 번에 silent 되돌림. (085 F1: 편집→활성화가 커스텀 에이전트를 기본
   구현으로 격하 — 사용자가 모른 채 1급→2급.)
2. **빌드 입구 미배선 = dead contract.** dataclass/ctx에 필드를 *선언*했는데 그걸 채우는 적재 지점이
   안 실으면 항상 기본값(None)이다 — 설계는 했으나 죽은 계약. 소비자가 아직 그 필드를 안 읽으면 통합도
   초록. (085 F4: `AgentBuildContext.overrides`가 `_load_context`에서 미적재 + 3개 build 사이트 미배선.)

## 처방

- **입구를 닫힌 집합으로 센다**: 읽기(소비)뿐 아니라 **create / update / 직렬화(model_dump 등) /
  컨텍스트 적재 / 모든 build 사이트**까지. 주 경로 하나만 보면 샌다(learning 060·070과 같은 결).
- **full-replace 갱신은 미전송 필드를 보존**: `model_fields_set`(Pydantic) 등으로 *명시 전송됐는지*
  구분 — 안 보냈으면 편집 베이스(초안→활성)에서 이어받고, 명시 전송이면 클리어 포함 존중.
- **선언과 배선을 같은 변경에서 짝지운다**: dataclass 필드 추가 = 그걸 채우는 *모든* 적재/빌드 지점
  배선까지가 한 단위. 선언만 하고 배선 안 하면 dead.
- **회귀는 "필드가 모든 입구를 통과해 살아남는지"로 박는다**: 단위 라운드트립(생성 응답에 필드 보존)
  으로 부족 — *편집→활성화→소비*까지의 통합 라운드트립이라야 full-replace drop을 잡는다(085 H5).
- **적대자에게 여집합을 시킨다**: "내가 단언한 입구 *말고* 이 필드를 떨어뜨릴 수 있는 입구는?" —
  happy-path는 상상한 실패만 본다(learning 023). 085의 F1·F4 둘 다 자가검증이 아니라 codex가 잡았다.

## 공명

- **086**(소비층 fail-closed만으론 dead-state 샌다·술어를 모든 쓰기/렌더 입구에 정렬)과 같은 축:
  086은 *capability 술어*를 모든 입구에 정렬, 088은 *새 필드*를 모든 입구에 정렬. 둘 다 "한 층만 닫으면
  나머지 입구가 happy-path 초록인 채 샌다"의 변주.
- **023**(비가역·파괴 경로는 출하 전 적대 리뷰): silent 되돌림(F1)이 그 비가역에 해당.
- **probe-deeper**: F1을 처음 "편집 폼 영향 없음"으로 넘긴 게 오판 — 단정 전 한 겹 더 봤어야.

[new-interface-field,wire-at-every-entry,full-replace-silent-drop,model-fields-set,dead-contract,enumerate-entries,roundtrip-through-all-entries,adversarial-codex,probe-deeper,086-sibling-axis]
