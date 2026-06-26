/* my-agents admin — 메모리 관리 화면 (스펙 030).
   에이전트 전용 메모리(agent_id)와 유저 메모리(user_id)를 한 화면 두 탭에서
   조회·필터·교정한다. 에이전트 탭은 029 AgentMemoryPanel을 재사용한다. */
import { useEffect, useState } from 'react'
import { Tabs, Select, message } from 'antd'
import { Page } from '../shared'
import { listAgents, listUserIds, type Agent } from '../../api'
import { AgentMemoryPanel } from './AgentMemoryPanel'
import { UserMemoryPanel } from './UserMemoryPanel'

const LONG_TERM = '장기 기억 (mem0)'

function AgentMemoryTab() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [sel, setSel] = useState<string | undefined>()

  useEffect(() => {
    listAgents()
      .then((all) =>
        setAgents(all.filter((a) => a.source === 'ui' && (a.memories || []).includes(LONG_TERM)))
      )
      .catch(() => message.error('에이전트를 불러오지 못했습니다'))
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
      <Select
        placeholder="장기 기억(mem0)을 쓰는 에이전트 선택"
        style={{ width: '100%' }}
        value={sel}
        onChange={setSel}
        showSearch
        optionFilterProp="label"
        options={agents.map((a) => ({ value: a.id, label: a.name }))}
        notFoundContent="장기 기억을 쓰는 UI 에이전트가 없습니다"
      />
      {sel ? <AgentMemoryPanel agentId={sel} /> : null}
    </div>
  )
}

function UserMemoryTab() {
  const [users, setUsers] = useState<string[]>([])
  const [sel, setSel] = useState<string | undefined>()

  useEffect(() => {
    listUserIds()
      .then(setUsers)
      .catch(() => message.error('유저 목록을 불러오지 못했습니다'))
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
      <Select
        placeholder="유저 선택 (대화에 쓰인 userId)"
        style={{ width: '100%' }}
        value={sel}
        onChange={setSel}
        showSearch
        optionFilterProp="label"
        options={users.map((u) => ({ value: u, label: u }))}
        notFoundContent="대화에 쓰인 userId가 없습니다"
      />
      {sel ? <UserMemoryPanel userId={sel} /> : null}
    </div>
  )
}

export default function MemoryView() {
  return (
    <Page title="메모리" subtitle="에이전트 전용 기억과 유저 기억을 조회·교정합니다.">
      <Tabs
        items={[
          { key: 'agent', label: '에이전트 메모리', children: <AgentMemoryTab /> },
          { key: 'user', label: '유저 메모리', children: <UserMemoryTab /> },
        ]}
      />
    </Page>
  )
}
