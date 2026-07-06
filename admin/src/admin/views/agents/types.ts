import type { ToolPolicy, ArtifactSpec } from '../../mockData'

/* 폼 데이터 shape — 생성/편집에서 공유. */
export interface AgentFormData {
  name: string // 식별 이름(규칙, 스펙 148)
  alias: string // 별명(자유 표기, 스펙 148) — ''=없음
  model: string
  persona: string
  temperature: number | null // null=자동(모델 등록값), 수동이면 0–2(스펙 077)
  memories: string[]
  historyDepth: number
  persistHistory: boolean
  vectorTables: string[]
  mcps: string[]
  impl: string // 실행 방식(런타임 키). ''=기본 UI 에이전트(스펙 106).
  capabilities: string[] // 능력 브로커 allowlist(cap id 목록, 스펙 106).
  toolPolicy: ToolPolicy // 도구 승인 오버라이드(스펙 177 P2) — cap_id→{approval:{required?,approver?}}.
  artifactSpec?: ArtifactSpec // 노코드 산출물형 필드 명세(스펙 190) — impl=artifact_form일 때.
}
