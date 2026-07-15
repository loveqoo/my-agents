/* 시드·계약 상수(스펙 366) — e2e 스펙 공용. 시드/계약이 바뀌면 여기 한 곳만 고친다.
   이름은 식별 규칙(영소문자·숫자·대시)을 지켜야 400을 안 맞는다. */
export const SEED = {
  chatModel: 'mock-llm', // 시드 채팅 모델(구 qwen3.6-35b)
  embedModel: 'mock-embed', // 시드 임베딩 모델(구 multilingual-e5-large)
  uiAgent: 'research-assistant', // mem0 시드 UI 에이전트(구 'Research Assistant')
  codeAgent: 'doc-translator', // 원격 프록시 시드 코드 에이전트(구 'Doc Translator')
  mcpServer: 'local-tools', // 빌딩블록 MCP 탭 시드 서버(구 'tavily')
  memoryType: '단기(세션)', // 시드 메모리 타입 라벨
}
export const A2A_SIGNATURE = '[mock-a2a]' // mock 원격 스트림 텍스트 시그니처(구 '원격 에이전트')
export const BLOCK_CATEGORIES = ['prompt', 'memory', 'embedding', 'mcp'] // permission 제거(권한 재설계)
