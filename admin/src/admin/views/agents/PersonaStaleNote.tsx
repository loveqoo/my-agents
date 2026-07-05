import { useState } from 'react'
import { Tag, Button } from 'antd'
import type { Agent } from '../../mockData'

/* ---- 페르소나 스냅샷 오래됨 안내 + 갱신(스펙 161) — 원본 블록이 수정된 뒤 이 에이전트가 저장 시점
   본문을 계속 쓰고 있음을 가시화하고, can_manage인 경우에만 명시적 갱신을 허용. ---- */
export function PersonaStaleNote({ agent, onRefresh }: { agent: Agent; onRefresh: (a: Agent) => Promise<void> }) {
  const [loading, setLoading] = useState(false)
  if (!agent.personaStale) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', margin: '4px 0 10px' }}>
      <Tag color="warning">원본 페르소나가 수정됨 — 이전 내용 사용 중</Tag>
      {agent.can_manage !== false ? (
        <Button
          size="small"
          loading={loading}
          onClick={async () => {
            setLoading(true)
            try {
              await onRefresh(agent)
            } finally {
              setLoading(false)
            }
          }}
        >
          최신 페르소나로 갱신
        </Button>
      ) : null}
    </div>
  )
}
