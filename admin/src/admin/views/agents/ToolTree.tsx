/* 공용 도구 선택 트리(스펙 277·278) — 서버(부모)→도구(자식) 체크박스, **점진 공개**:
   아코디언(Collapse) 안에 트리, 처음 열면 1 depth(서버만), 블릿(스위처)으로 서버별 확장,
   리프에 도구 설명(toolsMeta — "설명 없이 고를 수 없다", 사용자 피드백). 직접형 폼·노드 카드·
   오버라이드 드로어 공용(값=런타임명 server__tool, 스펙 276). 부모 체크=그 서버 도구 전체,
   부분 선택=indeterminate(antd 비-strict 자동 파생). */
import { useMemo, useState } from 'react'
import type { Key } from 'react'
import { Tree, Input, Tag, Collapse } from 'antd'
import { safeToolName } from './AgentForm'

type ServerInfo = {
  name: string
  tools?: string[]
  toolsMeta?: Record<string, { description?: string }> | null
}

const MUTED = { fontSize: 12, color: 'var(--color-text-tertiary)' } as const

export function ToolTree({
  servers,
  value,
  onChange,
  emptyText = '등록된 MCP 도구 없음 — 빌딩 블록에서 서버를 등록하세요.',
  bare = false,
}: {
  servers: ServerInfo[]
  value: string[] // 런타임명(server__tool) 목록
  onChange: (next: string[]) => void
  emptyText?: string
  // bare=true(스펙 279 ③): Collapse 래퍼·헤더 없이 검색+트리만 — 부모가 자기 구획(도구·문서 단일
  // Collapse)에 임베드할 때. 기본(false)=자체 아코디언(노드 카드·오버라이드).
  bare?: boolean
}) {
  const [q, setQ] = useState('')
  // 1 depth 초기화(스펙 278) — 처음엔 서버만 보이고, 스위처(블릿)로 서버별 확장. 277은 expandedKeys를
  // 상수로 고정+onExpand 빈 함수라 블릿이 죽고 전부 펼쳐졌다(인지 부담) — 상태로 수리.
  const [expanded, setExpanded] = useState<Key[]>([])

  const withTools = servers.filter((s) => (s.tools?.length ?? 0) > 0)
  const query = q.trim().toLowerCase()
  const treeData = useMemo(
    () =>
      withTools
        .map((s) => {
          const serverMatch = s.name.toLowerCase().includes(query)
          const tools = (s.tools ?? []).filter((t) => {
            if (!query || serverMatch) return true
            const desc = s.toolsMeta?.[t]?.description ?? ''
            return (t + ' ' + desc).toLowerCase().includes(query)
          })
          if (query && !serverMatch && !tools.length) return null
          return {
            key: `srv:${s.name}`,
            title: (
              <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 13 }}>{s.name}</span>
                <span style={MUTED}>도구 {s.tools?.length ?? 0}개</span>
              </span>
            ),
            children: tools.map((t) => {
              const desc = s.toolsMeta?.[t]?.description
              return {
                key: safeToolName(s.name, t),
                title: (
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: 0 }}>
                    <span style={{ fontSize: 13 }}>{t}</span>
                    {desc ? (
                      <span style={{ ...MUTED, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', maxWidth: 480 }}>
                        {desc}
                      </span>
                    ) : null}
                  </span>
                ),
              }
            }),
          }
        })
        .filter(Boolean) as { key: string; title: React.ReactNode; children: { key: string; title: React.ReactNode }[] }[],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [servers, query]
  )

  const chosen = value.length
  const total = withTools.reduce((n, s) => n + (s.tools?.length ?? 0), 0)

  const body =
    total === 0 ? (
      <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>{emptyText}</span>
    ) : (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {total > 6 && (
          <Input
            allowClear
            size="small"
            placeholder="도구 검색... (이름·설명)"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        )}
        {treeData.length === 0 ? (
          <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>검색 결과 없음</span>
        ) : (
          <Tree
            checkable
            selectable={false}
            blockNode
            // 검색 중=매칭 서버 자동 확장, 평시=사용자 확장 상태(초기 []=1 depth). 스위처가 onExpand로
            // 상태를 갱신하므로 접기/펼치기 동작(스펙 278 수리).
            expandedKeys={query ? treeData.map((n) => n.key) : expanded}
            onExpand={(keys) => { if (!query) setExpanded(keys) }}
            checkedKeys={value}
            onCheck={(checked) => {
              const keys = Array.isArray(checked) ? checked : checked.checked
              // 부모(srv:) 키를 걸러 리프(런타임명)만 — value 축과 일치(스펙 277).
              onChange((keys as string[]).filter((k) => !k.startsWith('srv:')))
            }}
            treeData={treeData}
          />
        )}
      </div>
    )

  if (bare) return body

  // 아코디언(스펙 278) — PickerGroups와 같은 룩: 헤더=도구+선택/전체 배지, 선택 있으면 기본 펼침.
  return (
    <Collapse
      size="small"
      defaultActiveKey={chosen > 0 ? ['tools'] : []}
      items={[
        {
          key: 'tools',
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              도구
              <Tag color={chosen > 0 ? 'blue' : 'default'} style={{ marginInlineEnd: 0 }}>
                {chosen}/{total}
              </Tag>
            </span>
          ),
          children: body,
        },
      ]}
    />
  )
}
