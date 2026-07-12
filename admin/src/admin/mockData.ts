/* Admin 콘솔 공용 타입·상태맵.
   에이전트/세션/블록의 TypeScript 타입과 상태맵(라벨·태그·색) 단일 출처. 실 데이터는 백엔드
   API에서 받는다(seed.py가 첫 설치 예제의 단일 출처, 스펙 303). 예전 mock 데이터 배열
   (BLOCKS·ADMIN_AGENTS·ADMIN_SESSIONS)은 死코드라 제거(스펙 305) — 타입·상수만 유지. */

/* 단기 기억 카탈로그 라벨(스펙 269) — 백엔드 memory_enabled()가 무시하는 죽은 문자열(단기 기억은
   historyDepth가 소유). 기억 *선택지·표시*에서 제외하는 단일 출처(카탈로그 DB 행은 유지). */
export const SHORT_TERM_MEMORY = '단기(세션)'

/* ---------- 타입 ---------- */
export interface AgentConfig {
  model?: string
  persona?: string
  temperature?: number | null // 에이전트 영속 온도(스펙 077). null=자동(모델 등록값)
  memories?: string[]
  historyDepth?: number
  persistHistory?: boolean
  ephemeral?: boolean
  suggestedPrompts?: string[]
  vectorTables?: string[]
  mcps?: string[]
  tools?: string[] // 직접형 도구 단위 배선(스펙 276) — 런타임명 목록. 비면 배선 서버 전체.
  impl?: string // 실행 방식(런타임 키, 스펙 085/106). 빈값/미지정=기본 UI 에이전트.
  capabilities?: string[] // 능력 브로커 allowlist(스펙 106). 오케스트레이터 impl에서 위임 대상.
  toolPolicy?: ToolPolicy // 도구 승인 오버라이드(스펙 177 P2).
  artifactSpec?: ArtifactSpec // 노코드 산출물형 필드 명세(스펙 190). impl=artifact_form일 때만 의미.
  nodes?: (PipelineNode | PipelineNodeRef)[] // 노드형 파이프라인 노드(스펙 259) — 인라인 또는 라이브러리 참조(스펙 316). impl=pipeline일 때만 의미.
  ragMinScores?: Record<string, number> // 컬렉션별 문서 검색 최소 유사도(스펙 191 v2). {컬렉션명:0~1}, 미만 제외.
}

/** 노드형 파이프라인 노드(스펙 259) — 일렬로 이어 실행. 각 노드가 자기 프롬프트·모델·도구를 가짐.
    tools는 ctx.tools의 도구 이름 부분집합(에이전트 밖 이름은 백엔드가 무시 = 권한 상승 0). */
export interface PipelineNode {
  name?: string // 표시 이름(비면 백엔드가 노드N 자동)
  prompt: string // 이 노드의 시스템 프롬프트(비어있지 않아야 저장)
  model: string // 이 노드가 쓸 등록 모델 이름(ModelConfig.name)
  tools: string[] // 이 노드가 참고할 도구 이름(MCP 도구명 + 문서 검색 search_documents)
  context?: 'carry' | 'clean' // 맥락 모드(스펙 260). carry=대화 이어받기(기본), clean=앞 결과만 격리
  format?: 'text' | 'json' // 출력 형식(스펙 261). text=자유(기본), json=유효 JSON 강제
  fields?: string[] // JSON 필수 키(스펙 261, 선택) — format=json일 때만 의미
  memories?: string[] // 회상 받을 기억 블록(스펙 268 P2, 선택) — 비면 이 노드는 회상 없음
  memoryQuery?: 'user' | 'input' // 회상 키워드(268). user=사용자 입력(캐시 공유, 기본), input=이 노드의 입력
  historyDepth?: number | null // 단기 기억 창(스펙 270) — 이전 대화 N개. undefined/null=에이전트 상속. carry일 때만 의미
  /* 코드 노드(스펙 317) — impl이 있으면 실행을 코드(신뢰 레지스트리)가 소유한다. 이때 prompt/model은
     **런타임에 없을 수 있다**(해석 config·resolvedNodes 항목이 {impl, overridable, name}만 실음) —
     소비처는 접근 전 가드(?? ''). overridable=세션 오버라이드가 병합할 수 있는 필드 목록(빈 배열=전부 코드 소유). */
  impl?: string // 코드 노드 레지스트리 키(스펙 317). 없으면 일반(설정) 노드
  overridable?: string[] // 코드 노드의 오버라이드 허용 필드(스펙 317) — impl 있을 때만 의미
}

/** 등록 노드 참조(스펙 316) — 노드 라이브러리의 (name, version)에 핀 고정. 새 버전이 발행돼도
    참조는 자기 버전에 머문다(명시적으로 올릴 때만 이동). ref 항목에 인라인 키 혼합 금지(서버 422). */
export type PipelineNodeRef = { ref: { name: string; version: number } }

/** 노드 항목 판별(스펙 316, 단일 소스) — nodes[] 항목은 인라인 노드 또는 라이브러리 참조 둘 중 하나.
    폼·상세·오버라이드가 전부 이 헬퍼로 분기한다(사본 판별식 금지 — 드리프트 0). */
export const isNodeRef = (n: PipelineNode | PipelineNodeRef): n is PipelineNodeRef =>
  typeof n === 'object' && n != null && 'ref' in n

/** 노드 tools 항목 중 에이전트-호출 도구 판별(스펙 318) — `agent__{agent_id}` 규약.
    MCP 도구·문서 도구와 한 배열에 섞여 저장되므로, 편집 시 서로의 항목을 병합 보존하는 데 쓴다. */
export const isAgentTool = (t: string): boolean => t.startsWith('agent__')

/** 노코드 산출물형 필드(스펙 190) — 후보 있으면 SelectBox(enum), 없으면 자유 입력. */
export interface ArtifactField {
  key: string // 결과 dict 키(비어있지 않은 문자열)
  label: string // 화면 표시 이름
  candidates?: string[] // 선택지(있으면 SelectBox)
  required?: boolean // 기본 true
}
export interface ArtifactSpec {
  kind?: string // 산출물 종류 라벨(기본 form-result)
  fields: ArtifactField[]
}

/* 조율형(다른 곳에 위임하는 런타임) 판정 — orchestrate/orchestrate_ranked 둘 다(구 저장분 호환).
   편집 폼·오버라이드 폼이 공유하는 단일 소스(스펙 122, 드리프트 0). */
export const isOrchestratorImpl = (impl?: string): boolean =>
  impl === 'orchestrate' || impl === 'orchestrate_ranked'
export interface VersionMeta {
  version: string
  status: 'draft' | 'active' | 'archived'
  createdAt: string
  note: string
  config?: AgentConfig
}
export interface BlockItem {
  id: string
  name: string // 식별 이름(규칙, 스펙 148)
  description?: string | null // 설명(선택, 스펙 210) — 표시 = name 단독, 설명은 툴팁
  usedBy: number
  updated: string
  body?: string
  /* persona */ tone?: string
  /* memory */ key?: string
  /* memory */ scope?: string
  /* embedding */ model?: string
  source?: string
  dims?: number
  rows?: number
  status?: string
  /* mcp */ transport?: string
  tools?: string[]
  enabledTools?: string[]
  /* mcp 도구 메타(스펙 151) — name→{description, params}. 탐색 시점 스냅샷 */
  toolsMeta?: Record<string, { description?: string; params?: { name: string; type?: string; required?: boolean }[] }> | null
  published?: boolean
  endpoint?: string
  served_url?: string | null // 서빙 URL(스펙 156) — source=custom일 때만, 외부가 이 URL로 등록·접속
  url?: string
  auth?: string
  activeVersion?: string
  versions?: VersionMeta[]
  owner_id?: string | null // 소유자(스펙 112, mcp만)
  can_manage?: boolean // 관리 가능(스펙 114) — false면 편집/삭제 숨김
}
export interface BlockCategory {
  label: string
  icon: string
  color: string
  desc: string
  items: BlockItem[]
}
/** 도구 승인 오버라이드(스펙 177 P2) — cap_id(`mcp:{server}/{tool}`)→승인 정책 덮어쓰기.
 *  required 미지정=도구 기본 따름 / true·false=강화·완화. approver=admin(관리자)·self(본인). */
export type ToolApprovalOverride = { required?: boolean; approver?: 'admin' | 'self' }
export type ToolPolicy = Record<string, { approval?: ToolApprovalOverride }>

export interface Agent {
  id: string
  name: string // 식별 이름(규칙, 스펙 148)
  description?: string | null // 설명(선택, 스펙 210) — 표시 = name 단독, 설명은 툴팁
  agentId: string
  environments: string[]
  model: string
  status: 'online' | 'idle' | 'offline'
  persona: string
  temperature?: number | null // 에이전트 영속 온도(스펙 077). null/미지정=자동(모델 등록값)
  memories: string[]
  historyDepth: number
  persistHistory?: boolean
  ephemeral?: boolean
  suggestedPrompts?: string[]
  vectorTables: string[]
  mcps: string[]
  tools?: string[] // 직접형 도구 단위 배선(스펙 276) — 런타임명(server__tool) 목록. 비면 배선 서버 전체.
  impl?: string // 실행 방식 런타임 키(스펙 085/106) — 폼 재로드/라운드트립 보존
  capabilities?: string[] // 능력 브로커 allowlist(스펙 106)
  toolPolicy?: ToolPolicy // 도구 승인 오버라이드(스펙 177 P2) — cap_id→{approval:{required?,approver?}}
  artifactSpec?: ArtifactSpec // 노코드 산출물형 필드 명세(스펙 190) — 폼 재로드/라운드트립 보존
  nodes?: (PipelineNode | PipelineNodeRef)[] // 노드형 파이프라인 노드(스펙 259) — 인라인 또는 라이브러리 참조(스펙 316), 폼 재로드/라운드트립 보존
  resolvedNodes?: PipelineNode[] | null // 참조를 등록 config로 치환한 유효 노드 목록(스펙 316, 읽기 전용 파생) — 미해결 참조면 null
  ragMinScores?: Record<string, number> // 컬렉션별 문서 검색 최소 유사도(스펙 191 v2) — 폼 재로드/라운드트립 보존
  owner_id?: string | null // 소유자(스펙 112). null=공유/레거시
  can_manage?: boolean // 관리 가능(스펙 114) — false면 편집/삭제 숨김
  exposed: { a2a: boolean }
  sessions: number
  created: string
  systemPrompt?: string // 해석된 페르소나 본문(저장 시점 스냅샷)
  personaStale?: boolean // 스냅샷이 현재 원본 페르소나와 다름(스펙 161)
  activeVersion: string
  versions: VersionMeta[]
  /* 공통 인터페이스 준수 분류(스펙 089) — 백엔드가 resolve와 같은 게이트로 파생.
     conforming=로컬 적합 / non_conforming=원격 A2A(다른 종류) / config_error=impl 선언했으나 미해결(서빙 거부). */
  conformance?: 'conforming' | 'non_conforming' | 'config_error'
  /* ---- code-defined agent (source === 'code') ---- */
  source?: 'ui' | 'code' | 'external'
  endpoint?: string
  token?: string
  runtime?: string
  repo?: string
  commit?: string
  registeredAt?: string
  lastSync?: string
  /* ---- external A2A agent (source === 'external') — 등록 시점 카드 스냅샷(읽기 전용) ---- */
  card?: AgentCard
}

/* A2A Agent Card(외부 에이전트가 광고하는 메타). 표시용 — 필드는 카드 스펙의 부분집합. */
export interface AgentCard {
  name?: string
  description?: string
  url?: string
  version?: string
  provider?: { organization?: string; url?: string }
  capabilities?: Record<string, unknown>
  defaultInputModes?: string[]
  defaultOutputModes?: string[]
  skills?: Array<{ id?: string; name?: string; description?: string; tags?: string[] }>
}
export interface Session {
  id: string
  agentId: string
  agent: string
  channel: string
  status: 'active' | 'running' | 'awaiting' | 'draining' | 'idle' | 'error' | 'completed'
  turns: number
  started: string
  lastActivity: string
  tokens: number
  preview?: string // 첫 사용자 메시지 일부 — 사람이 알아볼 세션 라벨(스펙 055)
  awaiting?: { permission: string; summary: string; checkpoint: string }
  error?: string
}
export interface Approval {
  id: string
  sessionId: string
  agentId: string
  agent: string
  permission: string
  action: string
  args: Record<string, unknown>
  summary: string
  requestedAt: string
  checkpoint: string
  status?: string
  approver?: 'admin' | 'self' | null // 승인자(스펙 177 P2) — 태그 표기(본인/관리자 승인)
  resolvedAt?: string | null // 처리 시각(스펙 181, 감사) — 미처리면 없음
  resolvedBySelf?: boolean | null // 처리자=요청자면 true(본인), 다르면 false(관리자), 미처리 null
}
export interface StatusMeta {
  label: string
  color?: string
  tag: string
  icon?: string
  desc?: string
}

/* ---------- 상태맵 ---------- */
export const VERSION_STATUS: Record<string, StatusMeta> = {
  draft: { label: '초안', tag: 'gold', color: 'var(--gold-6)', desc: '임시 — 게시 전 테스트' },
  active: { label: '활성', tag: 'green', color: 'var(--color-success)', desc: '현재 서빙 중' },
  archived: { label: '보관', tag: 'default', color: 'var(--gray-6)', desc: '이전 버전 · 롤백용 보관' },
}
export const SESSION_STATUS: Record<string, StatusMeta> = {
  active: { label: '활성', color: 'var(--color-success)', tag: 'green' },
  running: { label: '실행 중', color: 'var(--color-primary)', tag: 'blue' },
  awaiting: { label: '승인 대기', color: 'var(--purple-6)', tag: 'purple' },
  draining: { label: '드레이닝', color: 'var(--volcano-6)', tag: 'volcano' },
  idle: { label: '유휴', color: 'var(--gold-6)', tag: 'gold' },
  error: { label: '오류', color: 'var(--color-error)', tag: 'red' },
  completed: { label: '완료', color: 'var(--gray-6)', tag: 'default' },
}
export const VECTOR_STATUS: Record<string, StatusMeta> = {
  synced: { label: '동기화됨', tag: 'green' },
  indexing: { label: '재색인 중', tag: 'blue' },
  stale: { label: '갱신 필요', tag: 'gold' },
}
/* 신호등 단일 출처(스펙 284 ⑥→286) — 색=사용자 지정: 파랑(온라인)/노랑(유휴)/빨강(오프라인).
   목록 점·상세 헤더·대시보드 StatusPill이 모두 여기서 읽는다. */
export const AGENT_STATUS: Record<string, StatusMeta> = {
  online: { label: '온라인', color: 'var(--blue-6)', tag: 'blue', desc: '온라인 — 활성 버전이 서빙 중' },
  idle: { label: '유휴', color: 'var(--gold-6)', tag: 'gold', desc: '유휴 — 초안만 있음(활성화 전)' },
  offline: { label: '오프라인', color: 'var(--red-6)', tag: 'red', desc: '오프라인 — 원격에 연결되지 않음' },
}
/* 에이전트가 만들어진 출처. UI 구성(이 콘솔에서 블록으로 조립) vs Code 정의(SDK로 선언해
   코드베이스에서 배포, 엔드포인트로 등록). Code 에이전트는 여기서 읽기 전용 — 구성은 코드가 소유. */
export const AGENT_SOURCE: Record<string, StatusMeta> = {
  ui: { label: 'UI 구성', tag: 'default', icon: 'appstore', desc: '콘솔에서 빌딩 블록을 조합해 생성 · 편집 가능' },
  code: { label: 'code', tag: 'geekblue', icon: 'code', desc: 'SDK로 코드 정의 · 원격 엔드포인트 실행 · 읽기 전용' },
  external: { label: 'external', tag: 'purple', icon: 'robot', desc: 'A2A 카드로 등록한 외부 에이전트 · 읽기 전용' },
}
/* 공통 인터페이스 준수 분류(스펙 089). resolve_agent_runtime과 같은 게이트로 파생(파생값·저장 안 함).
   준수=로컬 적합(서빙 가능) · 비준수=원격 A2A로 in-process 인터페이스 미대상(정당한 다른 종류, 실패 아님)
   · 설정 실패=impl을 선언했으나 미해결(미등록/Protocol 부적합) — 런타임이 서빙을 거부하므로 강조. */
export const AGENT_CONFORMANCE: Record<string, StatusMeta> = {
  conforming: { label: '준수', tag: 'green', icon: 'check-circle', desc: '공통 인터페이스에 구조적 적합(Protocol 게이트 통과) · 플랫폼이 in-process로 서빙. 행위(astream/interrupt) 보장은 런타임 몫.' },
  non_conforming: { label: '비준수', tag: 'default', icon: 'api', desc: '원격 A2A 에이전트 · in-process 인터페이스 미대상(다른 종류)' },
  config_error: { label: '설정 실패', tag: 'red', icon: 'exclamation-circle', desc: 'impl을 선언했으나 미해결(미등록/부적합) · 런타임이 서빙 거부' },
}
