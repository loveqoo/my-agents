/* 공용 도구 선택 트리(스펙 277) — 서버(부모)→도구(자식) 체크박스. 직접형 폼·노드 카드·오버라이드
   드로어가 같은 위젯을 조립한다(값=런타임명 server__tool, 스펙 276). 부모 체크=그 서버 도구 전체,
   부분 선택=indeterminate(antd 비-strict 자동 파생). 카탈로그 스케일 대비 검색+선택 배지. */
import { useMemo, useState } from 'react'
import { Tree, Input, Tag } from 'antd'
import { safeToolName } from './AgentForm'

type Server = { name: string; tools?: string[] }

export function ToolTree({
  servers,
  value,
  onChange,
  emptyText = '등록된 MCP 도구 없음 — 빌딩 블록에서 서버를 등록하세요.',
}: {
  servers: Server[]
  value: string[] // 런타임명(server__tool) 목록
  onChange: (next: string[]) => void
  emptyText?: string
}) {
  const [q, setQ] = useState('')

  // 카탈로그에 도구가 있는 서버만 트리에. 자식 key=런타임명(safeToolName) — value와 동일 축.
  const withTools = servers.filter((s) => (s.tools?.length ?? 0) > 0)
  const query = q.trim().toLowerCase()
  const treeData = useMemo(
    () =>
      withTools
        .map((s) => {
          const serverMatch = s.name.toLowerCase().includes(query)
          const tools = (s.tools ?? []).filter((t) => !query || serverMatch || t.toLowerCase().includes(query))
          if (!tools.length) return null
          return {
            title: s.name,
            key: `srv:${s.name}`,
            selectable: false,
            children: tools.map((t) => ({ title: t, key: safeToolName(s.name, t), selectable: false })),
          }
        })
        .filter(Boolean) as { title: string; key: string; children: { title: string; key: string }[] }[],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [servers, query]
  )

  // 검색 중이면 매칭 서버 자동 확장(리치 UX). 평시엔 전부 펼침(선택 상태를 한눈에).
  const expandedKeys = treeData.map((n) => n.key)
  const chosen = value.length
  const total = withTools.reduce((n, s) => n + (s.tools?.length ?? 0), 0)

  if (!total) {
    return <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>{emptyText}</span>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>도구</span>
        <Tag color={chosen > 0 ? 'blue' : 'default'} style={{ marginInlineEnd: 0 }}>
          {chosen}/{total}
        </Tag>
      </div>
      {total > 6 && (
        <Input
          allowClear
          size="small"
          placeholder="도구 검색..."
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
          expandedKeys={expandedKeys}
          // 확장은 자동(검색·전체 펼침) — 사용자 토글도 허용하되 매칭은 항상 보이게.
          onExpand={() => {}}
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
}
