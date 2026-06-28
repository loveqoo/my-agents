/* my-agents admin — 메모리 관리 화면 (스펙 030).
   에이전트 전용 메모리(agent_id)와 유저 메모리(user_id)를 한 화면 두 탭에서
   조회·필터·교정한다. 에이전트 탭은 029 AgentMemoryPanel을 재사용한다. */
import { useEffect, useState } from 'react'
import { Tabs, Select, message } from 'antd'
import { Page } from '../shared'
import { listAgents, listMemoryUsers, type Agent, type MemoryUser } from '../../api'
import { AgentMemoryPanel } from './AgentMemoryPanel'
import { UserMemoryPanel } from './UserMemoryPanel'

// 드롭다운/패널 식별 라벨 — 이메일(있으면 display_name 병기), 미등록이면 raw UUID.
function userLabel(u: MemoryUser): string {
  if (!u.email) return `(미등록) ${u.user_id}`
  const name = u.display_name?.trim()
  return name ? `${name} · ${u.email}` : u.email
}

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
  const [users, setUsers] = useState<MemoryUser[]>([])
  const [sel, setSel] = useState<string | undefined>()

  useEffect(() => {
    listMemoryUsers()
      .then(setUsers)
      .catch(() => message.error('유저 목록을 불러오지 못했습니다'))
  }, [])

  const selUser = users.find((u) => u.user_id === sel)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 720 }}>
      <Select
        placeholder="유저 선택 (이메일·이름으로 검색)"
        style={{ width: '100%' }}
        value={sel}
        onChange={setSel}
        showSearch
        // 라벨(이메일·이름)과 user_id 둘 다로 검색되게 — UUID 일부로도 찾을 수 있다.
        // filterOption 함수를 주면 antd가 optionFilterProp을 무시하므로 후자는 두지 않는다.
        filterOption={(input, opt) =>
          `${opt?.label ?? ''} ${opt?.value ?? ''}`.toLowerCase().includes(input.toLowerCase())
        }
        options={users.map((u) => ({ value: u.user_id, label: userLabel(u) }))}
        notFoundContent="대화에 쓰인 유저가 없습니다"
      />
      {sel ? (
        <UserMemoryPanel userId={sel} label={selUser ? userLabel(selUser) : undefined} />
      ) : null}
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
