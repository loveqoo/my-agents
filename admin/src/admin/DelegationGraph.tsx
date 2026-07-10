/* 조율형 위임 구조(스펙 257) — 에이전트 capabilities로 조립한 위임 그래프를 들여쓰기 트리로.
   런타임은 호출 체인(256 v2)이 재방문을 차단해 모든 실행이 비순환 — 여기서는 **설정 층**의 구조를
   보이게 하고, 설정상 순환(back-edge)은 "실행 시 자동 차단" 마커로 정직하게 표시한다.
   상세 구성 탭(저장 config 기준)과 오버라이드 서랍(draft 기준 미리보기)이 공유. */
import { Tag } from 'antd'
import type { Agent } from './mockData'
import { isOrchestratorImpl } from './mockData'

const MAX_DEPTH = 8 // 표시 캡(런타임 여유 캡과 동일) — 그 아래는 "…"

function isAgentCap(c: string): boolean {
  return typeof c === 'string' && c.length > 0 && !c.includes(':') // broker._kind_of와 동일 규칙
}

function capSummary(caps: string[]): string {
  const mcp = caps.filter((c) => c.startsWith('mcp:')).length
  const rag = caps.filter((c) => c.startsWith('rag:')).length
  const mem = caps.some((c) => c.startsWith('memory'))
  const parts: string[] = []
  if (mcp) parts.push(`도구 ${mcp}개`)
  if (rag) parts.push(`문서 ${rag}개`)
  if (mem) parts.push('기억')
  return parts.join(' · ')
}

function NodeRow({ agent, name, depth, cycle, capsOverride }: {
  agent?: Agent
  name: string
  depth: number
  cycle?: boolean
  capsOverride?: string[]
}) {
  const orch = agent ? isOrchestratorImpl(agent.impl) : false
  const remote = agent ? agent.source === 'code' || agent.source === 'external' : false
  const caps = capsOverride ?? agent?.capabilities ?? []
  const summary = agent && !remote ? capSummary(caps) : ''
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', paddingLeft: depth * 20, fontSize: 13, minHeight: 26 }}>
      {depth > 0 && <span style={{ color: 'var(--color-text-quaternary)', fontFamily: 'var(--font-family-code)' }}>└─</span>}
      <span style={{ fontWeight: depth === 0 ? 600 : 500, color: 'var(--color-text-heading)' }}>{name}</span>
      {agent ? (
        <>
          {orch && <Tag color="geekblue" style={{ margin: 0, fontSize: 11 }}>조율형</Tag>}
          <Tag style={{ margin: 0, fontSize: 11 }}>{remote ? 'A2A' : '로컬'}</Tag>
          {!remote && !agent.activeVersion ? <Tag color="orange" style={{ margin: 0, fontSize: 11 }}>미서빙 — 위임 불가</Tag> : null}
          {summary ? <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{summary}</span> : null}
        </>
      ) : (
        <Tag color="default" style={{ margin: 0, fontSize: 11 }}>미확인(삭제됨?)</Tag>
      )}
      {cycle && (
        <Tag color="red" style={{ margin: 0, fontSize: 11 }}>↩ 순환 — 실행 시 자동 차단</Tag>
      )}
    </div>
  )
}

export function DelegationGraph({ rootAgentId, agents, rootCapsOverride, rootLabel }: {
  rootAgentId: string
  agents: Agent[]
  /** 오버라이드 미리보기(스펙 257) — 루트의 위임 대상을 편집 중 값으로(저장 config 대신). */
  rootCapsOverride?: string[]
  /** 루트가 아직 저장 전(새 에이전트)일 때 표시할 이름 — 미확인 태그 대신 합성 루트로. */
  rootLabel?: string
}) {
  const byId = new Map(agents.map((a) => [a.agentId, a]))
  const root = byId.get(rootAgentId)
  const rows: React.ReactNode[] = []

  const walk = (agentId: string, depth: number, path: Set<string>) => {
    const a = byId.get(agentId)
    const cycle = path.has(agentId)
    const syntheticRoot = depth === 0 && !a && !!rootCapsOverride // 저장 전 새 에이전트(스펙 257 후속)
    rows.push(
      syntheticRoot ? (
        <NodeRow key="root" name={rootLabel || '(이 에이전트)'} depth={0} capsOverride={rootCapsOverride} />
      ) : (
        <NodeRow
          key={`${agentId}-${depth}-${rows.length}`}
          agent={a}
          name={a?.name ?? agentId}
          depth={depth}
          cycle={cycle}
          capsOverride={depth === 0 ? rootCapsOverride : undefined}
        />
      ),
    )
    if (syntheticRoot) {
      const next = new Set(path)
      for (const c of (rootCapsOverride ?? []).filter(isAgentCap)) walk(c, 1, next)
      return
    }
    if (cycle || !a) return // 순환·미확인은 전개 중단(런타임과 동일 지점에서 멈춤)
    if (a.source === 'code' || a.source === 'external') return // 원격은 내부 구조 미상(잎)
    if (depth >= MAX_DEPTH) {
      rows.push(
        <div key={`cap-${rows.length}`} style={{ paddingLeft: (depth + 1) * 20, fontSize: 12, color: 'var(--color-text-quaternary)' }}>
          … (표시 깊이 상한 {MAX_DEPTH})
        </div>,
      )
      return
    }
    const caps = depth === 0 && rootCapsOverride ? rootCapsOverride : (a.capabilities ?? [])
    const next = new Set(path)
    next.add(agentId)
    for (const c of caps.filter(isAgentCap)) walk(c, depth + 1, next)
  }

  walk(rootAgentId, 0, new Set())

  const targets = (rootCapsOverride ?? root?.capabilities ?? []).filter(isAgentCap)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {rows}
      {targets.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>
          위임 대상이 없습니다 — "맡길 것"에서 다른 에이전트를 선택하면 구조가 그려집니다.
        </div>
      )}
    </div>
  )
}
