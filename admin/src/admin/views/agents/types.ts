import type { ToolPolicy, ArtifactSpec, PipelineNode, PipelineNodeRef } from '../../mockData'

/* 폼 데이터 shape — 생성/편집에서 공유. */
export interface AgentFormData {
  name: string // 식별 이름(규칙, 스펙 148)
  description: string // 설명(선택, 스펙 210) — ''=없음
  model: string
  persona: string
  temperature: number | null // null=자동(모델 등록값), 수동이면 0–2(스펙 077)
  memories: string[]
  historyDepth: number
  persistHistory: boolean
  ephemeral: boolean
  suggestedPrompts: string[] // 플그 추천 명령어(스펙 238, 옵셔널·최대 8)
  vectorTables: string[]
  mcps: string[]
  // 직접형 도구 단위 배선(스펙 276) — 런타임명(server__tool) 목록. mcps는 이것의 서버 합집합 파생
  // (+카탈로그 미열거 서버 보존). 빈 목록=배선 서버 전체(구저장 무회귀).
  tools: string[]
  impl: string // 실행 방식(런타임 키). ''=기본 UI 에이전트(스펙 106).
  capabilities: string[] // 능력 브로커 allowlist(cap id 목록, 스펙 106).
  toolPolicy: ToolPolicy // 도구 승인 오버라이드(스펙 177 P2) — cap_id→{approval:{required?,approver?}}.
  artifactSpec?: ArtifactSpec // 노코드 산출물형 필드 명세(스펙 190) — impl=artifact_form일 때.
  nodes?: (PipelineNode | PipelineNodeRef)[] // 노드형 파이프라인 노드(스펙 259) — 인라인 또는 라이브러리 참조(스펙 316). impl=pipeline일 때.
  ragMinScores: Record<string, number> // 컬렉션별 문서 검색 최소 유사도(스펙 191 v2). {컬렉션명:0~1}.
}
