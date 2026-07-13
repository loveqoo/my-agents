/* my-agents — debug console shared types.
   The real backend streams chat tokens, a session id, and a final execution trace.
   These types describe the trace shape the Inspector renders, plus the simplified
   chat-message shape the playground keeps in state. (Mock data + the HIL/A2UI flows
   were removed when the console was wired to the real backend.) */

import type { MessageFeedback } from '../api'

export interface Memory {
  // (스펙 324) type 필드 제거 — 백엔드가 항상 "semantic"만 실던 폐기 분류의 화석.
  text: string
  score: number
  // 이 기억이 회상된 스코프 축: 'user_id'(유저 장기) | 'run_id'(세션). 없으면 미상.
  scope?: 'user_id' | 'run_id' | string
}

// RAG 히트 1건의 표시 구조(스펙 191) — 인스펙터가 컬렉션·파일명·유사도·본문 프리뷰를 카드로 그린다.
export interface RagHit {
  score: number
  filename: string
  collection?: string
  textPreview: string
  meta?: Record<string, unknown> | null // 엔티티 원본 행 데이터(스펙 255 — 인스펙터 JsonTree용, 2000자 캡)
  belowCutoff?: boolean // 스펙 192: 커트라인 미달로 에이전트가 못 쓴 문서
  cutoff?: number // 그 컬렉션 커트라인 값(belowCutoff 판정 기준)
}

export interface McpCallT {
  server: string
  tool: string
  status: 'ok' | 'error' | string
  ms: number
  args: Record<string, unknown>
  result: string
  // 실패 사유(스펙 320) — status='error'일 때 사람이 읽을 에러 메시지(마스킹+캡). 성공 기록엔 없음.
  error?: string
  // RAG 검색 도구가 반환한 히트 수(server='rag'일 때). 스펙 079.
  hits?: number
  // 히트별 구조 + 컬렉션별 최소 유사도 맵(스펙 191 v2). 있으면 카드 렌더, 없으면 result 텍스트 폴백.
  hitsDetail?: RagHit[]
  minScores?: Record<string, number>
}

export interface GraphNode {
  node: string
  ms: number
  // 그 노드가 바꾼 상태 델타의 안전 요약(키기반 redaction + 캡). 스펙 086.
  // 폴백 경로(원격 재개 등 노드 미관측)는 undefined — 요약 행 미표시.
  summary?: string
  // 병렬 superstep(한 update 청크에 노드 2+)이면 true — ms가 노드별 실측이 아니라 청크 공유값이라
  // 순차 누적처럼 표시하지 않기 위함(스펙 086, codex F4). 직렬 그래프는 undefined.
  parallel?: boolean
}

export interface Trace {
  latencyMs: number
  tokens: { in: number; out: number; estimated?: boolean } // estimated=usage 부재 시 글자수 추정(스펙 205)
  promptRef: string
  memories: Memory[]
  mcp: McpCallT[]
  graph: GraphNode[]
  resumedFrom?: string
  // 적용된 메모리 스코프(다층). None이 아닌 축만 담긴다: {user_id?, run_id?}.
  // user_id 있으면 유저 장기(세션 가로지름)+세션, 없으면 세션 한정.
  memoryScope?: { user_id?: string; run_id?: string }
  // 회상에 쓴 쿼리(=user_text 에코) — 0건 회상이어도 "조회 이력"을 인스펙터에 남긴다. 스펙 079.
  memoryQuery?: string
  // 노드별 회상 기록(스펙 268 P2, 노드형) — 프록시가 조회마다 남김. cached=캐시 반환(조회 공유).
  memoryRecalls?: { node: string; query: string; hits: number; cached: boolean }[]
  // 이 턴에 구성된 RAG 컬렉션명(도구 호출 여부와 무관하게 노출). 스펙 037/079.
  ragCollections?: string[]
  // 요청됐으나 해석 실패한 컬렉션명(조용히 비는 footgun을 드러냄). 스펙 079.
  ragUnresolved?: string[]
  // 도구 무발동 진단(스펙 236) — 도구가 바인딩된 턴의 호출 수. called=0이면 "왜 안 되는지" 표면화.
  toolDiag?: { bound: string[]; called: number }
  // 실행 버전(스펙 242) — 이 턴이 어느 버전 config였나. versionPinned=미리보기(활성 아님) 턴.
  agentVersion?: string
  versionPinned?: boolean
  // 브로커 호출 상세(스펙 130) — 조율형 위임 호출의 표시용 메타. rag:* 는 RAG 섹션이 렌더.
  // resultPreview(스펙 131): 결과 본문 프리뷰(2000자 캡·비밀 마스킹, args는 계속 미포함).
  brokerCalls?: {
    node?: string // 그래프 노드명(broker_invoke:<kind>:<이름>) — agent kind는 cap_id(agt_)와 달라 매칭에 필수(스펙 256)
    cap_id: string
    ms: number
    hits?: number
    topScore?: number
    // 스펙 320: 실패 사유 문자열(구 boolean과 호환 — 사유 없으면 true 폴백). truthy면 실패 태그, 문자열이면 사유 표시.
    error?: boolean | string
    resultPreview?: string
    // 스펙 191(RAG 위임): 히트별 카드 + 최소 유사도 기준선 + 검색 질의(직접 도구와 동일 표시-안전 값).
    hitsDetail?: RagHit[]
    minScore?: number
    query?: string
    local?: boolean // 로컬 인프로세스 위임(스펙 256) — A2A와 호출 방식 구분 표식
    subTraceNodes?: string[] // 하위 실행 흐름(canonical 노드, 상한 50 — 트레이싱 관통)
  }[]
  // 전송 프롬프트 전문(스펙 131) — 실제 그래프에 넣은 배열(조립 system=persona+회상 포함), 메시지당
  // 2000자 캡. 재개 턴은 N/A(체크포인트 내부 재개 — 스펙 131 경계).
  sentMessages?: { role: string; content: string }[]
  sentMessagesSource?: 'measured' | 'reconstructed' // 스펙 205 — 실측(모델 콜백) vs 재구성(131 폴백)
  modelCalls?: number // 이 턴의 모델 호출 수(실측 시)
  // 이 턴에 적용된 오버라이드(스펙 134) — 세션에 설정 다른 턴이 섞여도 턴별 구분(마스킹·캡된 값).
  overrides?: Record<string, unknown>
  // 스펙 314 — 자동 기억 저장 상태. memoryPending=백그라운드 저장 진행 중(로딩 표시). memorySaved=
  // 완료 결과(트레일링 event: memory / 영속 병합). 둘 다 없으면 이 턴은 자동 저장이 없다(장기 메모리 미사용).
  memoryPending?: boolean
  memorySaved?: MemorySaved
}

// 스펙 314 — 백그라운드 자동 기억 저장 결과 요약(비밀 마스킹·캡됨). status: ok(1건+)/none(0건)/error.
export interface MemorySaved {
  status: 'ok' | 'none' | 'error'
  count: number
  items: { event: string; text: string }[]
}

// artifact: 산출물형(스펙 188) 완성 페이로드 — 임베드 시 JS 콜백(ui-callback)이 받는 JSON 그대로.
export type ChatMsg = {
  role: 'me' | 'ai'
  text: string
  trace?: Trace
  artifact?: { kind: string; data: Record<string, unknown>; raw?: string | null }
  // 스펙 209 P1.5: 저장된 assistant 메시지 id + 현재 사용자 피드백(👍/👎). id 있는 ai 메시지에만
  // 피드백 버튼 노출(스트림 message_id 프레임 또는 세션 리로드로 채워짐).
  id?: string
  feedback?: MessageFeedback | null
}
