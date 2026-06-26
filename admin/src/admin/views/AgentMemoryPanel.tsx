/* my-agents admin — 에이전트 전용 메모리(agent_id) 큐레이션 패널 (스펙 029).
   에이전트가 자가기록한 사실 + 관리자 저작 사실을 조회·수정·삭제·추가한다.
   쓰기(에이전트)와 교정(관리자)을 분리: 에이전트 쓰기는 즉시 활성, 여기서 사후 교정. */
import { useState, useEffect, useCallback } from 'react'
import { Button, Input, message, Popconfirm } from 'antd'
import { Icon } from '../icons'
import {
  listAgentMemory,
  addAgentMemory,
  updateAgentMemory,
  deleteAgentMemory,
  type AgentMemory,
} from '../../api'

export function AgentMemoryPanel({ agentId }: { agentId: string }) {
  const [items, setItems] = useState<AgentMemory[]>([])
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await listAgentMemory(agentId))
    } catch (e) {
      message.error('메모리 조회 실패: ' + (e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    void load()
  }, [load])

  const add = async () => {
    const text = draft.trim()
    if (!text) return
    setBusy(true)
    try {
      await addAgentMemory(agentId, text)
      setDraft('')
      await load()
      message.success('에이전트 지식 추가됨')
    } catch (e) {
      message.error('추가 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const saveEdit = async (memId: string) => {
    const text = editText.trim()
    if (!text) return
    setBusy(true)
    try {
      await updateAgentMemory(agentId, memId, text)
      setEditing(null)
      await load()
      message.success('수정됨')
    } catch (e) {
      message.error('수정 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (memId: string) => {
    setBusy(true)
    try {
      await deleteAgentMemory(agentId, memId)
      await load()
      message.success('삭제됨')
    } catch (e) {
      message.error('삭제 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        에이전트가 스스로 기록한(또는 관리자가 저작한) 전용 지식. 모든 세션·사용자를 가로질러
        회상됩니다 — 특정 사용자 정보는 여기 두지 마세요.
      </span>
      {loading ? (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>불러오는 중…</span>
      ) : items.length === 0 ? (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
          아직 전용 지식이 없습니다.
        </span>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((m) =>
            editing === m.id ? (
              <div key={m.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <Input
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onPressEnter={() => saveEdit(m.id)}
                  autoFocus
                />
                <Button size="small" type="primary" loading={busy} onClick={() => saveEdit(m.id)}>
                  저장
                </Button>
                <Button size="small" onClick={() => setEditing(null)}>
                  취소
                </Button>
              </div>
            ) : (
              <div
                key={m.id}
                style={{
                  display: 'flex',
                  gap: 8,
                  alignItems: 'center',
                  padding: '6px 8px',
                  background: 'var(--color-fill-quaternary)',
                  borderRadius: 6,
                }}
              >
                <span style={{ flex: 1, fontSize: 13 }}>{m.text}</span>
                <Button
                  size="small"
                  type="text"
                  icon={<Icon name="edit" />}
                  onClick={() => {
                    setEditing(m.id)
                    setEditText(m.text)
                  }}
                />
                <Popconfirm title="이 지식을 삭제할까요?" onConfirm={() => remove(m.id)} okText="삭제" cancelText="취소">
                  <Button size="small" type="text" danger icon={<Icon name="delete" />} />
                </Popconfirm>
              </div>
            )
          )}
        </div>
      )}
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
    </div>
  )
}
