/* my-agents admin — 유저 메모리(user_id) 큐레이션 패널 (스펙 030).
   유저가 대화 중 남긴 장기 기억을 조회·필터·수정·삭제한다. 관리자는 유저 사실을
   *저작*하지 않고 *교정*만 한다 → add 없음(조회/수정/삭제만). */
import { useState, useEffect, useCallback } from 'react'
import { Button, Input, message, Popconfirm } from 'antd'
import { Icon } from '../icons'
import {
  listUserMemory,
  updateUserMemory,
  deleteUserMemory,
  type AgentMemory,
} from '../../api'

export function UserMemoryPanel({ userId, label }: { userId: string; label?: string }) {
  const [items, setItems] = useState<AgentMemory[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await listUserMemory(userId))
    } catch (e) {
      message.error('메모리 조회 실패: ' + (e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  const saveEdit = async (memId: string) => {
    const text = editText.trim()
    if (!text) return
    setBusy(true)
    try {
      await updateUserMemory(userId, memId, text)
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
      await deleteUserMemory(userId, memId)
      await load()
      message.success('삭제됨')
    } catch (e) {
      message.error('삭제 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const visible = filter.trim()
    ? items.filter((m) => m.text.toLowerCase().includes(filter.trim().toLowerCase()))
    : items

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        이 유저가 대화 중 남긴 장기 기억. <b>{label ?? userId}</b>
        {label ? (
          <span style={{ opacity: 0.6, fontFamily: 'monospace' }}> ({userId})</span>
        ) : null}{' '}
        에게만 회상됩니다 — 잘못되거나 민감한 정보는 여기서 교정·삭제하세요.
      </span>
      {items.length > 0 ? (
        <Input
          placeholder="필터 (텍스트 부분일치)"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          allowClear
          size="small"
        />
      ) : null}
      {loading ? (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>불러오는 중…</span>
      ) : items.length === 0 ? (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
          이 유저의 장기 기억이 없습니다.
        </span>
      ) : visible.length === 0 ? (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
          필터에 맞는 기억이 없습니다.
        </span>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {visible.map((m) =>
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
                <Popconfirm title="이 기억을 삭제할까요?" onConfirm={() => remove(m.id)} okText="삭제" cancelText="취소">
                  <Button size="small" type="text" danger icon={<Icon name="delete" />} />
                </Popconfirm>
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}
