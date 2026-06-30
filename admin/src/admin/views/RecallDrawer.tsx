/* my-agents admin — 메모리 회상 시험 드로어 (스펙 084).
   에이전트/유저 메모리 패널이 공유한다 — 챗과 *같은 코어*(memory.search)로 스코프에 질의해
   "이 쿼리로 무엇이 회상되는가"를 즉석 확인. 072 CollectionsView SearchDrawer의 메모리판.
   onSearch만 주입(searchAgentMemory/searchUserMemory 바인딩) → UI drift 0. */
import { useState, useEffect } from 'react'
import { Drawer, Input, InputNumber, Button, Tag, Alert, message } from 'antd'
import { Icon } from '../icons'
import { type MemorySearchOut } from '../../api'

const { TextArea } = Input

export function RecallDrawer({
  open,
  title,
  scopeKey,
  onClose,
  onSearch,
}: {
  open: boolean
  title: string
  scopeKey: string // 스코프(에이전트/유저) 식별자 — 바뀌면 질의·결과 초기화
  onClose: () => void
  onSearch: (query: string, limit: number) => Promise<MemorySearchOut>
}) {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(4)
  const [out, setOut] = useState<MemorySearchOut | null>(null)
  const [searching, setSearching] = useState(false)

  // 스코프 전환 시 이전 질의/결과 초기화(072 SearchDrawer 패턴).
  useEffect(() => {
    setQuery('')
    setOut(null)
  }, [scopeKey])

  const run = async () => {
    if (!query.trim()) {
      message.warning('질의를 입력하세요')
      return
    }
    setSearching(true)
    try {
      const res = await onSearch(query.trim(), limit)
      setOut(res)
      if (res.enabled && !res.results.length) message.info('회상된 기억이 없습니다')
    } catch (e) {
      // 403=타 유저 메모리 접근 거부, 422=입력 오류 — 서버 메시지를 그대로 노출.
      message.error(e instanceof Error ? e.message : '조회에 실패했습니다')
    } finally {
      setSearching(false)
    }
  }

  return (
    <Drawer open={open} width={640} title={title} onClose={onClose} destroyOnHidden>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          에이전트가 채팅에서 회상하는 것과 <b>같은 메모리 코어</b>로 이 스코프에 질의합니다. 관련도(1.0=가장
          관련) 내림차순 상위 기억을 보여줍니다 — 저장된 기억이 의도대로 회상되는지 즉석 확인하세요.
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <TextArea
            rows={2}
            placeholder="예: 내가 선호하는 보고서 형식은?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={(e) => {
              e.preventDefault()
              void run()
            }}
            style={{ flex: 1 }}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: 120 }}>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>limit (1–10)</span>
            <InputNumber
              min={1}
              max={10}
              style={{ width: '100%' }}
              value={limit}
              onChange={(v) => setLimit(v ?? 4)}
            />
            <Button type="primary" icon={<Icon name="search" />} loading={searching} onClick={() => void run()}>
              조회
            </Button>
          </div>
        </div>

        {out !== null ? (
          !out.enabled ? (
            <Alert
              type="info"
              showIcon
              title="장기 기억이 비활성/미구성입니다"
              description="이 스코프는 장기 기억(mem0)이 설정되지 않아 회상할 수 없습니다. 임베딩 모델·에이전트 메모리 설정을 확인하세요."
            />
          ) : out.results.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)' }}>
                회상 {out.results.length}건
              </div>
              {out.results.map((h, i) => (
                <div
                  key={i}
                  style={{
                    padding: 12,
                    border: '1px solid var(--color-border-secondary)',
                    borderRadius: 'var(--radius-lg)',
                    background: 'var(--gray-2)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Tag color="blue">#{i + 1}</Tag>
                    <Tag color={h.score >= 0.5 ? 'green' : 'default'}>관련도 {h.score.toFixed(3)}</Tag>
                    <Tag>{h.scope}</Tag>
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{h.type}</span>
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', whiteSpace: 'pre-wrap' }}>
                    {h.text}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>회상된 기억이 없습니다.</div>
          )
        ) : null}
      </div>
    </Drawer>
  )
}
