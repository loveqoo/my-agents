/* my-agents admin — 에이전트 전용 메모리(agent_id) 큐레이션 패널 (스펙 029·051·127).
   관리자가 저작한 에이전트 전용 지식을 **한 검색 표면**에서 다룬다(127): [일치 | 유사도] 모드 —
   일치=서버 페이지네이션 부분일치 목록(행에서 수정·삭제)+추가 입력, 유사도=회상 시험(RecallPanel).
   채팅 자가기록 경로는 제거됨(스펙 051) — 유저가 채팅에서 agent_id 메모리를 못 넣게 막아 페르소나 보호. */
import { useState } from 'react'
import { Button, Input, Segmented, message } from 'antd'
import {
  pageAgentMemory,
  addAgentMemory,
  updateAgentMemory,
  deleteAgentMemory,
  searchAgentMemory,
} from '../../api'
import { PagedMemoryList } from './PagedMemoryList'
import { RecallPanel } from './RecallPanel'

export function AgentMemoryPanel({ agentId }: { agentId: string }) {
  const [mode, setMode] = useState<'exact' | 'similar'>('exact')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0) // 추가 후 목록 재조회 트리거

  const add = async () => {
    const text = draft.trim()
    if (!text) return
    setBusy(true)
    try {
      await addAgentMemory(agentId, text)
      setDraft('')
      setRefreshKey((k) => k + 1)
      message.success('에이전트 지식 추가됨')
    } catch (e) {
      message.error('추가 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Segmented
          value={mode}
          onChange={(v) => setMode(v as 'exact' | 'similar')}
          options={[
            { label: '일치 검색', value: 'exact' },
            { label: '유사도 검색', value: 'similar' },
          ]}
        />
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          관리자가 저작한 에이전트 전용 지식. 모든 세션·사용자를 가로질러 회상됩니다 — 특정 사용자 정보는
          여기 두지 마세요(채팅 자가기록은 차단됨).
        </span>
      </div>

      {mode === 'exact' ? (
        <>
          <PagedMemoryList
            scopeKey={agentId}
            scopeLabel={agentId}
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
