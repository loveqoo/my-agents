# 262 — 인스펙터 노드 요약: clean 노드의 remove를 사람 말로 (스펙 260 표시 다듬기)

## 배경
260의 "깨끗이 받기"(clean) 노드는 이전 대화를 걷어낼 때 메시지마다 `RemoveMessage`(LangGraph 상태
삭제 지시)를 낸다. 인스펙터 "실행 흐름"이 노드 델타를 요약하며 이걸 `_msg_role`로 렌더 →
`RemoveMessage.type=="remove"`라 **"remove / remove / user: «...»"** 로 날것 노출(사용자 지적, 2026-07-09).

**검증됨**: `remove`는 모델 프롬프트에 없음 — `ainvoke` 인자는 `[sys, human]`뿐이고 `removals`는
반환 델타에만(pipeline.py). 순수 **표시** 아티팩트. 개수 = 그 시점 정리된 이전 메시지 수(사용자 입력 +
앞 노드 결과 → 2개 → "remove / remove"). 대화가 길수록 늘어남.

## 설계 (표시만 — 동작 무변)
디버깅 신호("격리가 일어났다 + 몇 개 걷어냈다")는 **보존**하되 내부어 `remove`는 **감춘다**(플레이그라운드
= 정밀 디버그 통로: 신호는 남기고 잡음만). `_summarize_node_update`의 messages 요약에서:
- 델타 메시지 중 `RemoveMessage`(role=="remove")를 **세어** 한 줄로 접음: **"이전 맥락 N개 정리 (격리)"**.
- 나머지 실제 발화(user/assistant/tool)만 기존대로 role+본문 프리뷰(앞 3건 + "+N건").

## 구현
- `packages/api/src/api/runtime.py` `_summarize_node_update`의 `key=="messages"` 블록: remove 카운트
  분리 → 격리 노트 prepend, rest만 프리뷰. `extra`는 rest 기준 재계산. 불변식(비밀 fail-closed·budgeted
  캡·예외 None) 그대로.

## 검증
- **단위** `verify_262_summary.py`: (1) RemoveMessage 2개+human+ai 델타 → "이전 맥락 2개 정리 (격리)"
  포함·"remove" 문자열 미포함·실제 발화(user/assistant) 프리뷰 유지, (2) remove 없는 델타는 기존 동작
  무변(무회귀), (3) remove만 있는 델타도 정상.
- **통합**(브라우저): 인스펙터에 "이전 맥락 N개 정리"·"remove" 미노출 확인(shot-pipeline-inspector 확장).
- **무회귀**: 086 관련 요약 불변식(비밀 미표시) 유지.

## 경계
- 표시만 — `RemoveMessage`의 격리 동작·모델 프롬프트는 불변(이미 검증). "추후 더 다듬기"는 별도(노드별
  모델·형식 배지 등).

## 결과 (구현·검증, 2026-07-09)

**구현**: `api/runtime.py` `_summarize_node_update`의 messages 블록 — 델타 메시지 중 role=="remove"
(RemoveMessage)를 세어 `"이전 맥락 N개 정리 (격리)"` 한 줄로 접고, 나머지 실제 발화만 프리뷰. extra는
rest 기준 재계산. 086 불변식(비밀 fail-closed·budgeted 캡·예외 None) 그대로.

**사전 확인(고치기 전)**: 증상이 동작인지 표시인지 계층부터 갈랐다 — `remove`는 모델 프롬프트에
없음(pipeline.py `ainvoke` 인자는 `[sys, human]`뿐, removals는 반환 델타에만). 순수 표시라 표시 계층만
수정(동작 무변). "왜 2개?"=그 시점 정리된 이전 메시지 수(사용자 입력+앞 노드 결과).

**검증**:
- **단위** `verify_262_summary.py` 6/6: S1 격리 접기(remove 미노출·발화 프리뷰 유지), S2 무회귀(remove
  없는 델타 불변), S3 remove만, S4 비밀 불변식(임의 키 값 길이만).
- **통합**(브라우저, shot-pipeline-inspector 확장): 인스펙터에 "이전 맥락 N개 정리" 표시·"remove /
  remove" 미노출 실측(ALL GREEN).

**경계**: 표시만 — 격리 동작·모델 프롬프트 불변(검증됨). "추후 더 다듬기"(노드별 모델·형식 배지 등)는 별도.
