# 135 — A2A skills 확장: 카드가 실제 능력 광고 (스펙 157, 실사용 #7)

자율 루프 8건차(B 시리즈 마지막). A2A 카드가 `chat` 하나만 광고하던 걸, 에이전트의 실제 능력
(MCP 도구·서브에이전트 위임·RAG)을 스킬로 정직하게 광고하게 확장 + 플레이그라운드 A2A 모드에
광고 스킬 칩(테스트 수단).

## 무엇을 했나
- `_agent_a2a_skills(agent)`: config.mcps + config.capabilities(broker 파서 재사용)를 실제 능력 스킬로.
  살아있는 참조만(dangling 스킵), 이름·설명만(민감정보 미포함), 50개 캡.
- 플레이그라운드 A2A 모드에 광고 스킬 칩(getA2ASkills로 카드 fetch).

## 배운 것 (상기용)
1. **"능력을 광고"할 땐 그 능력이 *실제로 호출 가능한지*까지 맞춰야 정직이다.** 카드에 `agent:sub`를
   delegate로 실었는데, AgentProvider는 remote(code/external+endpoint)만 위임한다(broker:236). ui
   서브에이전트를 광고하면 **거짓 능력**(호출 불가)이자 **그 에이전트 노출 게이트를 우회한 이름 누출**
   (codex High). 광고 목록은 "설정에 적힌 것"이 아니라 "런타임이 실제 실행하는 것"과 일치시켜야 한다 —
   transport(stdio 미광고, Med1)·enabled 의미(빈=전체, Med2)·위임 가능성(remote만, High) 모두. [[installed-guard-isnt-covering-guard]]의
   광고판: "설정됨"≠"실행 가능". 존재 비노출(learning 068)은 카드 같은 **공개 표면**에서 특히.
2. **공개 표면에 무엇이 나가는지 = 그 표면의 게이트가 아니라 원천 데이터의 게이트로 판단하라.** 카드는
   무인증 공개(self-fetch 호환) — 그래서 카드에 실리는 *모든 파생 데이터*는 "이게 공개돼도 되나"를
   원천에서 물어야 한다. 서브에이전트 이름은 그 에이전트의 노출 축에 속하는데 부모 카드가 대신 흘렸다.
3. **런타임 의미론을 광고가 복제할 땐 그 의미론을 정확히 읽어라.** `enabled_tools=[]`가 "필터 없음=전체"
   라는 런타임 규칙(runtime:213)을 카드가 몰라 정반대(아무것도 광고 안 함)로 갈렸다(Med2). 파생 표면은
   원천 로직의 **엣지 의미**(빈 리스트·None·전체)를 그대로 옮겨야 한다.

## codex 적대 리뷰 (High1/Med2/Low1 전부 반영)
- High: ui 미노출 서브에이전트 이름 누출+거짓 위임 → remote+endpoint만 광고(V7 봉인).
- Med1: transport 무관 광고 → http만(runtime 일치, V8). Med2: 빈 enabled → tools 스냅샷(V9).
- Low: 칩 stale → deps에 exposed·능력 시그니처.
- 경계: tools_meta.description은 공개 발견 메타(비밀 아님, 상류 위생 책임).

## 검증
- verify_157 9/9(V7 누출 봉인·V8 stdio·V9 빈enabled 포함), e2e 6/6(칩 렌더·복귀 부재), codex 전부 반영.
