# 010 — create_react_agent + 회상 주입은 단일 system 프롬프트로

날짜: 2026-06-23
맥락: [docs/spec/007](../../docs/spec/007-real-agent-service.md), `packages/api/src/api/chat.py`. E2E가 잡음.

## 버그
mem0에서 회상한 기억을 **별도 `{"role":"system"}` 메시지로 messages 앞에 prepend**했더니,
`create_react_agent(prompt=persona)`가 이미 persona를 system으로 넣어 **system 메시지가 2개**가 됐다.
로컬 MLX(Qwen) 채팅 템플릿이 거부: `400 - Chat template error: System message must be at the beginning.`
→ 스트림 errored → (오류 턴 미영속 설계 때문에) 세션/메시지 저장도 스킵.

영향: **의미론적 메모리를 켠 에이전트만** 깨졌다(메모리 끈 에이전트는 system 주입이 없어 정상). 그래서 단발 스모크로는 놓치기 쉬웠고, **E2E의 "저장→회상→영속" 시나리오가 잡아냈다.**

## 교훈
- `create_react_agent`는 `prompt`로 시스템 프롬프트를 관리한다. 추가 컨텍스트(회상 기억·동적 지시)는
  **별도 system 메시지로 넣지 말고 `prompt`(persona)에 합쳐** 단일 system을 유지한다.
- 많은 챗 템플릿(특히 로컬 모델)은 **system 메시지가 맨 앞 1개**여야 한다. 멀티 system 가정 금지.

## 검증 패턴
- "오류 턴은 영속 안 함" 같은 방어 로직은 **실패를 조용히 삼킬 수 있다** — 단언이 빈 결과로 약해질 수 있으니,
  E2E에서 **응답이 알려준 실제 식별자(session 프레임)** 로 영속을 결정적으로 확인할 것.
- Playwright 상태 속성 셀렉터(`[aria-checked="false"]`)는 토글되면 매칭에서 빠져 다른 요소로 재해석된다 →
  토글 검증은 **위치 기반(nth) 고정 로케이터**로.
