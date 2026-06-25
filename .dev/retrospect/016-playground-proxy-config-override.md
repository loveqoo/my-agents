# 016 — Playground Proxy: 세션 한정 설정 오버라이드 (회고)

스펙: [025](../../docs/spec/025-playground-proxy-config-override.md)
날짜: 2026-06-26
연결: [[027-frontend-filter-is-not-a-backend-guard]], [012] 단일 소스, [025-config-storage-split], [009] 코드 bypass

## 무엇을 했나

Playground를 "Proxy(런타임 레이어)" 모델로 개편. web 에이전트는 세션 한정으로 저장 설정을
덮어써(model·temperature·systemPrompt·mcps·memories·historyDepth) 테스트할 수 있고, 코드 에이전트는
오버라이드를 무시하고 원격 bypass를 그대로 유지. 새 DB 엔티티 없이 `_load_context`에 화이트리스트
병합 한 겹만 추가. "변경 → 새 대화"(021 패턴 확장)로 트레이스 혼선 방지.

## 잘된 것 — 분기 대신 데이터로 안전하게

- **무회귀가 구조적으로 보장됐다.** `if overrides and agent.source != "code"` 한 줄이 게이트라,
  오버라이드가 없으면(`None`/`{}`) 분기에 진입조차 안 해 spec-025 이전과 바이트 동일한 경로를 탄다.
  "기능을 끄면 정확히 예전 동작"이 코드 형태로 증명된다. 새 기능은 이렇게 **기존 경로를 건드리지 않는
  추가**로 넣는 게 가장 안전하다.
- **[012] 단일 소스 유지.** 모델 오버라이드도 "어떤 등록 모델 이름을 고르나"만 바꿀 뿐, 런타임은
  여전히 `cfg["model"]` 이름으로 레지스트리에서만 해석. 특수분기 0개([026] 결과를 그대로 계승).
- **프런트 diff-payload.** `overridePayload`가 "변경된 키만" 보내, 손 안 댄 필드는 저장값 그대로.
  적용 중 오버라이드를 화면(시스템 프롬프트 뷰어)에 우선 반영해 "화면=실제"([025]) 정합.

## 아팠던 것 — 가드를 한쪽에만 뒀다 (codex P1)

빈 systemPrompt가 persona를 지우는 걸 **프런트 `overridePayload`에서만** 막았다(비어있지 않고 달라진
경우만 전송). 그래서 "프런트로는 절대 빈 값이 안 간다"고 안심했는데, codex가 정확히 찔렀다: **백엔드가
클라이언트를 신뢰**한다. `_load_context`는 `"systemPrompt" in overrides`만 보고 빈 문자열도 그대로
persona에 덮어썼다 — 직접 API 호출(또는 다른 클라이언트)이면 저장 페르소나가 날아간다.

가드를 백엔드로 내렸다(`isinstance(sp,str) and sp.strip()`). 프런트 필터는 UX 편의일 뿐 **계약의
경계가 아니다.** 입력 검증·불변식 보호는 그 데이터를 실제로 쓰는 쪽(백엔드)에 둬야 한다.

## 검증에서 배운 것

- **타자 검증이 자가검증의 사각을 메웠다.** 나는 프런트 가드를 보고 "안전"이라 결론냈는데, 같은 코드를
  본 codex는 백엔드 신뢰 경계를 봤다. 단정 전에 한 겹 더([[probe-deeper-before-concluding]]) — 이번엔
  내가 아니라 타자가 그 한 겹을 봐줬다.
- **untracked 신규 파일은 `git diff`에 안 잡혀 리뷰 사각이 된다.** `OverridePanel.tsx`(신규)가 diff에
  없어 codex가 핵심 프런트 로직을 못 봤다(P2). 타자 검증 줄 때 신규 파일은 명시적으로 포함해야 한다 →
  [[027-frontend-filter-is-not-a-backend-guard]]에 운영 팁으로 적음.
- **실제 모델로 행동을 관찰**했다(mock 응답은 프롬프트를 echo 안 함). qwen에 "한 단어 BANANA" persona를
  걸어 실제 복종을 확인 → systemPrompt 오버라이드가 모델까지 도달함을 눈으로 증명. mock만으로는
  "에러 없이 받음"까지밖에 못 본다 — 행동 검증엔 실모델이 필요할 때가 있다.
