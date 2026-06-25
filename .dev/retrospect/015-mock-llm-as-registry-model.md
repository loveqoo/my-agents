# 015 — Mock LLM을 런타임 분기 대신 레지스트리 1급 모델로

날짜: 2026-06-25
스펙: [024](../../docs/spec/024-mock-llm-registry-model.md)
연동: [[012-runtime-config-single-source]], [[026-mock-belongs-in-registry-not-runtime-branch]], [009](../../docs/spec/009-code-agent-remote-exec.md)

## 무엇을 했나
라이브 MLX(`localhost:8045`) 없이 에이전트를 **결정적으로** 돌릴 수단이 없었다. 기존 mock은
`/_remote/agent`(코드 에이전트 SSE 더블)·`/_remote/models`·`/_remote/embeddings`로 산발했고,
**일반 chat 런타임(`build_agent`→`ChatOpenAI`→`{base_url}/chat/completions`)이 칠 OpenAI 호환
chat completions 엔드포인트가 없었다**. → mock-llm을 레지스트리 1급 chat 모델로 등록하고,
그 모델이 가리킬 `/_remote/v1/chat/completions`(스트림/비스트림 OpenAI 포맷)를 구현했다.

## 무엇이 잘 됐나
1. **런타임을 안 건드렸다.** "mock일 때 특수 처리"를 `build_agent`/`chat.py`에 넣고 싶은 유혹이
   컸지만, 대신 **데이터(레지스트리 행) + 그 데이터가 기대하는 계약(엔드포인트)**만 추가했다.
   `build_agent`는 mock의 존재를 모른다 — 그냥 base_url로 OpenAI를 칠 뿐. [012]의 "런타임은
   레지스트리만, 특수분기 없음"을 깨지 않고 기능을 더한 게 핵심. (→ learning 026)
2. **결정적 검증의 정직함.** mock 응답을 단언만 하지 않고, Ops 에이전트를 psql로 임시 mock-llm
   전환 → 실제 langgraph `call_model` 노드 통과 확인(latency 22ms, MLX 무관) → qwen3.6-35b 복원.
   "가짜 경로로 통과" 아닌 **진짜 런타임 경로**로 검증.
3. **`is_default=False`로 폭발 반경 차단.** 기본으로 두면 모든 폴백이 mock으로 새 위험. 명시
   선택해야만 발동.

## 무엇이 아쉬웠나 / 교정
- **env 의미를 처음엔 뭉뚱그렸다.** 초안은 mock base를 "009의 self-call 패턴 재사용"이라며
  `REMOTE_AGENT_BASE`와 엮을 뉘앙스로 적었다. codex P2-1이 짚었고, 다시 보니 둘은 **의미가
  다르다** — `REMOTE_AGENT_BASE`=코드 에이전트의(운영 시 외부) 배포 URL, `MOCK_LLM_BASE_URL`=
  이 API 자신의 self-주소. 운영에서 결합하면 mock base가 외부로 잘못 파생된다. → 별도 env
  유지로 정정, seed/마이그레이션/스펙 주석에 의미 차이를 박았다. **"비슷해 보이는 두 env가
  사실 다른 축"** — 기본값이 우연히 같다고(127.0.0.1:8000) 묶지 말 것.
- **downgrade 비대칭**(codex P2-2): upgrade는 멱등 skip, downgrade는 무조건 삭제. `mock-llm`
  이름을 seed/마이그레이션이 **소유**하는 정책으로 수용 + 주석 명시(스펙 023 수용 스타일과 동일).

## 다음에 적용
런타임이 "단일 소스만 읽는다"([012])는 제약이 있을 때, 새 동작은 **런타임 분기가 아니라
그 단일 소스에 들어갈 데이터 + 데이터가 기대하는 계약 구현**으로 푼다 → learning 026.
