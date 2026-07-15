/* my-agents admin — 에이전트 전용 메모리(agent_id) 큐레이션 패널 (스펙 029·051·127).
   관리자가 저작한 에이전트 전용 지식을 **한 검색 표면**에서 다룬다(127): [일치 | 유사도] 모드 —
   일치=서버 페이지네이션 부분일치 목록(행에서 수정·삭제)+추가 입력, 유사도=회상 시험(RecallPanel).
   채팅 자가기록 경로는 제거됨(스펙 051) — 유저가 채팅에서 agent_id 메모리를 못 넣게 막아 프롬프트 보호. */
import { useState } from 'react'
import { Button, Input, Tabs } from 'antd'
import {
  pageAgentMemory,
  addAgentMemory,
  updateAgentMemory,
  deleteAgentMemory,
  searchAgentMemory,
} from '../../api'
import { PagedMemoryList } from './PagedMemoryList'
import { RecallPanel } from './RecallPanel'
import { runWithToast } from '../../hooks'

export function AgentMemoryPanel({ agentId, agentLabel }: { agentId: string; agentLabel?: string }) {
  const [mode, setMode] = useState<'exact' | 'similar'>('exact')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0) // 추가 후 목록 재조회 트리거

  const add = async () => {
    const text = draft.trim()
    if (!text) return
    setBusy(true)
    const ok = await runWithToast(() => addAgentMemory(agentId, text), {
      success: '에이전트 지식 추가됨',
      errorPrefix: '추가 실패',
    })
    setBusy(false)
    if (ok) {
      setDraft('')
      setRefreshKey((k) => k + 1)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 스펙 219: [일치|유사도]는 서로 다른 도구/화면(편집 목록 vs 회상 시험)이라 Segmented→Tabs로 통일 —
          상위 에이전트/유저 기억 Tabs와 시각 일관(사용자 지적). 스위처만, 내용은 아래 조건부 렌더. */}
      <Tabs
        activeKey={mode}
        onChange={(k) => setMode(k as 'exact' | 'similar')}
        items={[
          { key: 'exact', label: '일치 검색' },
          { key: 'similar', label: '유사도 검색' },
        ]}
        style={{ marginBottom: -8 }}
      />
      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        관리자가 저작한 에이전트 전용 지식. 모든 세션·사용자를 가로질러 회상됩니다 — 특정 사용자 정보는
        여기 두지 마세요(채팅 자가기록은 차단됨).
      </span>

      {mode === 'exact' ? (
        <>
          <PagedMemoryList
            scopeKey={agentId}
            scopeLabel={agentLabel ?? agentId}
            fetchPage={(q, l, o) => pageAgentMemory(agentId, q, l, o)}
            onEdit={async (memId, text) => {
              await updateAgentMemory(agentId, memId, text)
            }}
            onDelete={async (memId) => {
              await deleteAgentMemory(agentId, memId)
            }}
            refreshKey={refreshKey}
          />
          <div style={{ display: 'flex', gap: 6 }}>
            <Input
              placeholder="에이전트 전용 지식 추가 (예: 보고서는 항상 한 줄 요약으로 시작한다)"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onPressEnter={add}
            />
            <Button type="primary" loading={busy} disabled={!draft.trim()} onClick={add}>
              추가
            </Button>
          </div>
        </>
      ) : (
        <RecallPanel scopeKey={agentId} onSearch={(q, l) => searchAgentMemory(agentId, q, l)} />
      )}
    </div>
  )
}
