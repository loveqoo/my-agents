/* my-agents admin — Sessions view: live & past conversation sessions, each with
   status; click a session to see its state detail.
   목록 엔진은 공용 PagedListShell(스펙 128) — 디바운스 서버검색·페이지네이션·지속 오류를 셸이 담당
   (기존 사라지는 토스트 오류도 지속 Alert로 교정됨). counts 배지는 응답 extra로 받아 Segmented에 반영,
   status 필터는 pageResetKey로 page만 리셋(검색어 보존 — 기존 UX 유지). */
import { useEffect, useState } from 'react'
import { Tag, Button, Avatar, Alert, Segmented, Popconfirm, message, Descriptions } from 'antd'
import { Page, StatusPill, Drawer, type Column } from '../shared'
import { PagedListShell } from './PagedListShell'
import { Icon } from '../icons'
import { SESSION_STATUS, type Session } from '../mockData'
import { fmtTime } from '../format'
import { listSessions, getSessionMessages, endSession, type SessionMessage, type MessageFeedback } from '../../api'
import { FeedbackButtons } from '../../FeedbackButtons'

export default function SessionsView() {
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [filter, setFilter] = useState<string>('all')
  const [detail, setDetail] = useState<Session | null>(null)
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [ending, setEnding] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0) // 종료 후 목록·counts 재조회(셸 트리거)

  // 세션 종료(스펙 129) — 서버가 status→completed로 전이(소유권은 서버 _own_scope가 강제).
  // 성공 시 드로어를 응답으로 갱신(완료 상태 즉시 반영 — footer 조건에 의해 종료 버튼이 사라짐)
  // + 목록·counts 재조회.
  const doEnd = async () => {
    if (!detail) return
    setEnding(true)
    try {
      const updated = await endSession(detail.id)
      setDetail(updated)
      setRefreshKey((k) => k + 1)
      message.success('세션을 종료했습니다')
    } catch (e) {
      message.error('세션 종료 실패: ' + (e as Error).message)
    } finally {
      setEnding(false)
    }
  }

  useEffect(() => {
    if (!detail) {
      setMessages([])
      return
    }
    let cancelled = false
    const sessionId = detail.id
    ;(async () => {
      try {
        const msgs = await getSessionMessages(sessionId)
        if (!cancelled) setMessages(msgs)
      } catch {
        if (!cancelled) setMessages([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [detail])

  // 스펙 209 — 피드백 변경을 로컬 메시지 상태에 반영(서버 응답으로 확정된 값).
  const applyFeedback = (mid: string, fb: MessageFeedback | null) =>
    setMessages((ms) => ms.map((m) => (m.id === mid ? { ...m, feedback: fb } : m)))

  const columns: Column<Session>[] = [
    {
      key: 'id',
      title: '세션',
      render: (s) => (
        <div>
          <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>{s.id}</code>
          <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{s.channel}</div>
        </div>
      ),
    },
    {
      key: 'agent',
      title: '에이전트',
      render: (s) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
            <Icon name="robot" size={13} />
          </Avatar>
          <span>{s.agent}</span>
        </div>
      ),
    },
    {
      key: 'status',
      title: '상태',
      width: 130,
      render: (s) => {
        const st = SESSION_STATUS[s.status]
        return s.status === 'running' ? (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 14 }}>
            <Icon name="loading" spin size={13} style={{ color: st.color }} />
            {st.label}
          </span>
        ) : (
          <StatusPill color={st.color ?? ''} label={st.label} />
        )
      },
    },
    {
      key: 'turns',
      title: '턴',
      width: 80,
      align: 'right',
      hideBelow: 'xl',
      render: (s) => <span style={{ fontFamily: 'var(--font-family-code)' }}>{s.turns}</span>,
    },
    {
      key: 'tokens',
      title: '토큰',
      width: 100,
      align: 'right',
      hideBelow: 'xl',
      render: (s) => (
        <span style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)' }}>{(s.tokens / 1000).toFixed(1)}k</span>
      ),
    },
    {
      key: 'lastActivity',
      title: '마지막 활동',
      width: 140,
      align: 'right',
      render: (s) => <span style={{ color: 'var(--color-text-tertiary)' }}>{fmtTime(s.lastActivity)}</span>,
    },
  ]

  return (
    <Page title="세션" subtitle="모든 채널에서 에이전트와 진행 중인 대화">
      <PagedListShell<Session, Record<string, number>>
        scopeKey="sessions"
        pageResetKey={filter} // status 전환 → page만 1로(검색어 보존, 기존 UX)
        refreshKey={refreshKey} // 세션 종료 후 목록·counts 재조회(스펙 129)
        fetchPage={async (q, limit, offset) => {
          const data = await listSessions({ status: filter, q, limit, offset })
          return { items: data.items, total: data.total, extra: data.counts }
        }}
        onExtra={(c) => setCounts(c ?? {})}
        columns={columns}
        onRowClick={setDetail}
        searchPlaceholder="세션 ID·유저·에이전트 검색"
        emptyText="조건에 맞는 세션이 없습니다"
        errorTitle="세션을 불러오지 못했습니다"
        leftSlot={
          <Segmented
            value={filter}
            onChange={(v) => setFilter(v as string)}
            options={[
              { label: `전체 (${counts.all ?? 0})`, value: 'all' },
              { label: `라이브 (${counts.live ?? 0})`, value: 'live' },
              { label: `승인 대기 (${counts.awaiting ?? 0})`, value: 'awaiting' },
              { label: `오류 (${counts.error ?? 0})`, value: 'error' },
            ]}
          />
        }
      />

      <Drawer
        open={!!detail}
        title={detail ? detail.id : ''}
        width={440}
        onClose={() => setDetail(null)}
        footer={
          detail && (detail.status === 'active' || detail.status === 'running' || detail.status === 'idle') ? (
            <>
              <Button onClick={() => setDetail(null)}>닫기</Button>
              <Popconfirm
                title="이 세션을 종료할까요?"
                description="세션이 완료 상태로 전환됩니다 (되돌릴 수 없음)."
                okText="종료"
                cancelText="취소"
                onConfirm={() => void doEnd()}
              >
                <Button danger loading={ending} icon={<Icon name="pause-circle" />}>
                  세션 종료
                </Button>
              </Popconfirm>
            </>
          ) : (
            <Button onClick={() => setDetail(null)}>닫기</Button>
          )
        }
      >
        {detail ? (
          <div>
            {(() => {
              const st = SESSION_STATUS[detail.status]
              return (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: st.color }} />
                  <span style={{ fontSize: 16, fontWeight: 600 }}>{st.label}</span>
                  <Tag color={st.tag} style={{ marginInlineStart: 'auto' }}>
                    {detail.channel}
                  </Tag>
                </div>
              )
            })()}
            {detail.error ? (
              <div style={{ marginBottom: 16 }}>
                <Alert type="error" showIcon title="세션 오류" description={detail.error} />
              </div>
            ) : null}
            {detail.awaiting ? (
              <div style={{ marginBottom: 16 }}>
                <Alert
                  type="warning"
                  showIcon
                  title="일시정지 — 관리자 승인 대기 중"
                  description={`${detail.awaiting.summary} · ${detail.awaiting.permission} · 체크포인트 ${detail.awaiting.checkpoint}`}
                />
              </div>
            ) : null}
            <Descriptions
              column={1}
              size="small"
              items={[
                { key: 'agent', label: '에이전트', children: detail.agent },
                { key: 'channel', label: '채널', children: detail.channel },
                { key: 'turns', label: '턴', children: detail.turns },
                { key: 'tokens', label: '토큰', children: detail.tokens.toLocaleString() },
                { key: 'started', label: '시작', children: fmtTime(detail.started) },
                { key: 'last', label: '마지막 활동', children: fmtTime(detail.lastActivity) },
              ]}
            />
            <div style={{ marginTop: 16 }}>
              <Alert type="info" showIcon title="디버그 콘솔에서 이 세션을 열면 턴별 프롬프트·메모리·MCP 호출을 확인할 수 있습니다." />
            </div>
            {messages.length > 0 ? (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 8 }}>최근 메시지</div>
                {messages.slice(-5).map((m, i) => (
                  <div key={m.id ?? i} style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: 0.5, flex: 1 }}>{m.role}</div>
                      {/* 스펙 209 — assistant 응답에만 피드백(서버도 assistant-only 게이트). */}
                      {m.role === 'assistant' && m.id && detail ? (
                        <FeedbackButtons
                          sessionId={detail.id}
                          messageId={m.id}
                          value={m.feedback}
                          onChange={(fb) => applyFeedback(m.id as string, fb)}
                        />
                      ) : null}
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', whiteSpace: 'pre-wrap' }}>{m.content}</div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </Drawer>
    </Page>
  )
}
