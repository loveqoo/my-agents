/* my-agents admin — Sessions view: live & past conversation sessions, each with
   status; click a session to see its state detail. */
import { useEffect, useState } from 'react'
import { Tag, Button, Avatar, Alert, Radio, Pagination, message } from 'antd'
import { Page, StatusPill, DataTable, Drawer, Desc, type Column } from '../shared'
import { Icon } from '../icons'
import { SESSION_STATUS, type Session } from '../mockData'
import { fmtTime } from '../format'
import { listSessions, getSessionMessages, type SessionMessage } from '../../api'

const PAGE_SIZE = 20

export default function SessionsView() {
  const [rows, setRows] = useState<Session[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [filter, setFilter] = useState<string>('all')
  const [page, setPage] = useState(1) // 1-base
  const [detail, setDetail] = useState<Session | null>(null)
  const [messages, setMessages] = useState<SessionMessage[]>([])

  // 필터·페이지 변경 → 서버 재조회. 필터 전환 시 page=1로 리셋(아래 onChange에서).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await listSessions({ status: filter, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
        if (!cancelled) {
          setRows(data.items)
          setTotal(data.total)
          setCounts(data.counts)
        }
      } catch {
        message.error('세션을 불러오지 못했습니다')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [filter, page])

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
      render: (s) => <span style={{ fontFamily: 'var(--font-family-code)' }}>{s.turns}</span>,
    },
    {
      key: 'tokens',
      title: '토큰',
      width: 100,
      align: 'right',
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
      <div style={{ marginBottom: 16 }}>
        <Radio.Group
          optionType="button"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value)
            setPage(1) // 필터 전환 시 첫 페이지로
          }}
          options={[
            { label: `전체 (${counts.all ?? 0})`, value: 'all' },
            { label: `라이브 (${counts.live ?? 0})`, value: 'live' },
            { label: `승인 대기 (${counts.awaiting ?? 0})`, value: 'awaiting' },
            { label: `오류 (${counts.error ?? 0})`, value: 'error' },
          ]}
        />
      </div>
      <DataTable<Session> columns={columns} rows={rows} onRowClick={setDetail} empty="조건에 맞는 세션이 없습니다" />
      {total > PAGE_SIZE ? (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={total}
            showSizeChanger={false}
            onChange={setPage}
            showTotal={(t) => `총 ${t}건`}
          />
        </div>
      ) : null}

      <Drawer
        open={!!detail}
        title={detail ? detail.id : ''}
        width={440}
        onClose={() => setDetail(null)}
        footer={
          detail && (detail.status === 'active' || detail.status === 'running' || detail.status === 'idle') ? (
            <>
              <Button onClick={() => setDetail(null)}>닫기</Button>
              <Button danger icon={<Icon name="pause-circle" />}>
                세션 종료
              </Button>
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
                <Alert type="error" showIcon message="세션 오류" description={detail.error} />
              </div>
            ) : null}
            {detail.awaiting ? (
              <div style={{ marginBottom: 16 }}>
                <Alert
                  type="warning"
                  showIcon
                  message="일시정지 — 관리자 승인 대기 중"
                  description={`${detail.awaiting.summary} · ${detail.awaiting.permission} · 체크포인트 ${detail.awaiting.checkpoint}`}
                />
              </div>
            ) : null}
            <Desc label="에이전트">{detail.agent}</Desc>
            <Desc label="채널">{detail.channel}</Desc>
            <Desc label="턴">{detail.turns}</Desc>
            <Desc label="토큰">{detail.tokens.toLocaleString()}</Desc>
            <Desc label="시작">{fmtTime(detail.started)}</Desc>
            <Desc label="마지막 활동">{fmtTime(detail.lastActivity)}</Desc>
            <div style={{ marginTop: 16 }}>
              <Alert type="info" showIcon message="디버그 콘솔에서 이 세션을 열면 턴별 프롬프트·메모리·MCP 호출을 확인할 수 있습니다." />
            </div>
            {messages.length > 0 ? (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 8 }}>최근 메시지</div>
                {messages.slice(-5).map((m, i) => (
                  <div key={i} style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: 0.5 }}>{m.role}</div>
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
