# 105 — 부수효과 능력은 승인 게이트가 "구조" / 게이트는 최소 하네스로 검증 / privacy finding은 권한-델타로 판정

능력 브로커에 첫 부수효과(쓰기) 능력을 붙이며 세 가지가 굳었다.

## 1. 부수효과 능력의 안전은 프롬프트가 아니라 승인 게이트라는 "구조"

learning 031이 이미 처방했다: **LLM은 사용자의 "이거 기억해"를 도구 프롬프트의 금지보다 우선한다 —
도구 프롬프트의 규율은 격리 경계가 아니다. 진짜 보장은 프롬프트가 아니라 구조(승인 게이트)로.**
메모리 쓰기 능력이 정확히 그 사례였고, 브로커의 `approval_for`→interrupt→resume 파이프라인이 그 구조다.

부수효과 provider의 설계 규칙: **`approval_for`가 항상 non-None**(읽기 provider의 항상-None과 정반대).
브로커가 부수효과(`memory.add`) *이전*에 interrupt로 멈추고 사람이 승인해야 실행한다. 승인 payload는
실행될 내용을 **마스킹 없이** 노출한다(승인하려면 무엇을 승인하는지 봐야 한다 — MCP의 비밀 마스킹과
반대 방향의 결정).

이건 두 게이트 분리(learning 103)의 완성: 읽기=정책만, 쓰기=정책+승인. read-only provider는
`approval_for=None` 한 줄로 승인 우회, write provider는 항상 payload. 게이트가 처음부터 분리돼 있어
확장이 조합으로 떨어진다 — 새 kind는 자기 부수효과 유무만 선언하면 된다.

**적용:** 브로커/도구에 부수효과(쓰기·삭제·전송) 능력을 더할 때, 안전을 프롬프트 지시("PII 쓰지 마")로
걸지 마라 — 모델이 사용자 지시 한 마디에 뚫는다. **부수효과 이전 사람 승인**을 구조로 넣어라. 그리고
승인 뷰엔 실행될 내용을 그대로 보여줘라(승인의 의미).

## 2. 부수효과 게이트는 "게이트를 부르는 최소 하네스"로 결정적 검증

reject→무부수효과 / approve→정확히 1회를 검증하는 데 **전체 플로우(orchestrate+실 LLM)가 필요 없다.**
`broker.invoke`를 부르는 **최소 1노드 StateGraph + MemorySaver**면 interrupt/resume이 실제로 발화하고,
FakeMem-add로 부수효과를 카운트해 reject=0/approve=1/pause-전=0을 결정적으로(LLM·dev서버 없이) 실측한다.

```
async def _write(state): return {"r": (await broker.invoke("memwrite:user", {"text": state["fact"]})).text}
g = StateGraph(St); g.add_node("write", _write); g.add_edge(START,"write"); g.add_edge("write",END)
graph = g.compile(checkpointer=MemorySaver())
itr = await stream(graph, {"fact":...}, cfg)          # interrupt, FakeMem.adds==0
await stream(graph, Command(resume={"decision":"approve"}), cfg)  # FakeMem.adds==1
```

101은 풀 orchestrate+mock LLM으로 HIL을 봤지만, 게이트 *메커니즘*만 볼 땐 그게 과하다. **테스트는
검증하려는 불변식을 부르는 가장 작은 실행 맥락에서** — interrupt는 그래프 런타임이 필요하니 그래프는
쓰되, 플로우 로직(analyze/select/synthesize)은 불필요하니 뺀다. 싸고 결정적이고 dev서버 비의존.

## 3. privacy finding은 "그 주체가 다른 경로로 이미 가진 권한을 넓히나?"로 판정

codex가 "admin이 남의 memory-write 승인을 열람·결정 가능 = privacy 노출"이라 짚었다. 하지만 **admin은
이미 스펙 053(`memory:manage`)로 임의 유저 기억을 읽고 큐레이션할 권한이 있다.** 그래서 승인 뷰에서
그 사실을 보는 것이 admin 권한을 **넓히지 않는다** — 새 노출이 아니라 기존 권한의 다른 표면일 뿐.

**privacy/authz finding 판정의 핵심 질문: "이 경로가 그 주체가 *이미 다른 경로로 가진* 권한/가시성을
넓히나?"** 안 넓히면 새 결함이 아니라 기존 경계(문서화 대상). 넓히면 실결함. 이 질문 없이 "admin이
민감 데이터를 본다"만 보면 이미 admin인 권한을 결함으로 오인한다. 안전 불변식(여기선 저장 스코프=승인자
무관 요청자 user_id, 교차유저 쓰기 0)이 유지되면, 나머지는 권한-델타로 가른다. ([[complement-attack-can-be-honest-boundary]]의
authz판 — 여집합 공격 성공이 항상 결함은 아니다, 특히 그 권한이 이미 존재하면.)

## 적용 요약
- 부수효과 능력: `approval_for` 항상 non-None(부수효과 이전 사람 승인), 승인 뷰엔 실행 내용 노출.
- 게이트 검증: 게이트를 부르는 최소 하네스(1노드 graph+MemorySaver+Fake), 전체 플로우 불요.
- 자원 상한(text 길이)은 승인·실행 **공유 헬퍼**로(승인한 것==실행되는 것, 드리프트 0 — learning 103).
- privacy finding: "다른 경로로 이미 가진 권한을 넓히나?"로 실결함/기존경계 판정.
- 정책 민감도 등급(self-승인 vs admin)은 도메인 판단 → 자가결정 말고 사용자 확인(outcome으로 제시).

관련: 스펙 105 · retrospect [[086-capability-broker-memory-write-provider]] · learning 031(구조로 막아라)·
100·103·104 · [[complement-attack-can-be-honest-boundary]].
