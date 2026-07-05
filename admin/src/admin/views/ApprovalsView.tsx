/* my-agents admin — Approvals queue: admin-approver permission requests where a
   LangGraph run is paused at a checkpoint (interrupt) awaiting an admin decision.
   Approve → resume from checkpoint; Reject → abort the run. */
import { useState, useEffect, type ReactNode } from 'react'
import { Tag, Button, Avatar, message, Segmented } from 'antd'
import { Page, Panel } from '../shared'
import { Icon } from '../icons'
import { type Approval } from '../mockData'
import { listApprovals, resolveApproval } from '../../api'

// 두 카드(ApprovalCard·HistoryCard) 공통 조각(스펙 182 중복 추출).
// 헤더: 아바타+에이전트명+세션id + 우측 태그 슬롯. 카드별 상단 패딩(14/12)·부제(요청시각 유무)·태그가
// 달라 파라미터로 픽셀 보존.
function CardHeaderRow({ agent, sessionId, extra, pad, rightTag }: {
  agent: string; sessionId: string; extra?: ReactNode; pad: string; rightTag: ReactNode
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: pad, borderBottom: '1px solid var(--color-border-secondary)' }}>
      <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
        <Icon name="robot" size={13} />
      </Avatar>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{agent}</div>
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          <code style={{ fontFamily: 'var(--font-family-code)' }}>{sessionId}</code>{extra}
        </div>
      </div>
      {rightTag}
    </div>
  )
}

// 권한·액션 태그 쌍(두 카드 완전 동일).
function PermActionTags({ permission, action }: { permission: string; action: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      <Tag color="geekblue">{permission}</Tag>
      <Tag color="cyan">
        <code style={{ fontFamily: 'var(--font-family-code)' }}>{action}</code>
      </Tag>
    </div>
  )
}

function ApprovalCard({
  item,
  onResolve,
}: {
  item: Approval
  onResolve: (item: Approval, decision: 'approve' | 'reject') => Promise<void>
}) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const act = async (decision: 'approve' | 'reject') => {
    setBusy(decision)
    const delay = new Promise<void>((r) => setTimeout(r, 360))
    try {
      await Promise.all([onResolve(item, decision), delay])
    } finally {
      setBusy(null)
    }
  }
  return (
    <Panel style={{ padding: 0 }}>
      <CardHeaderRow
        agent={item.agent}
        sessionId={item.sessionId}
        extra={<> · {item.requestedAt}</>}
        pad="14px 18px"
        rightTag={
          <Tag color={item.approver === 'self' ? 'blue' : 'purple'}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name={item.approver === 'self' ? 'user' : 'lock'} size={11} />
              {item.approver === 'self' ? '본인 승인' : '관리자 승인'}
            </span>
          </Tag>
        }
      />

      <div style={{ padding: '16px 18px' }}>
        <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--color-text-heading)', marginBottom: 10 }}>{item.summary}</div>
        <PermActionTags permission={item.permission} action={item.action} />
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>인자</div>
        <pre
          style={{
            fontFamily: 'var(--font-family-code)',
            fontSize: 12,
            lineHeight: 1.6,
            color: 'var(--color-text)',
            background: 'var(--gray-2)',
            border: '1px solid var(--color-border-secondary)',
            borderRadius: 6,
            padding: '10px 12px',
            margin: 0,
            whiteSpace: 'pre-wrap',
          }}
        >
          {JSON.stringify(item.args, null, 2)}
        </pre>
        {/* flex row → 인라인 흐름(스펙 133 모바일 점검): flex 항목화된 텍스트 조각들이 좁은 폭에서
            긴 <code>에 밀려 한 글자씩 세로로 짜부라졌다(390px 판독 불가). 일반 텍스트 흐름 + code만
            줄바꿈 허용으로 어떤 폭에서도 자연스럽게 감긴다. */}
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--color-text-tertiary)', lineHeight: 1.7 }}>
          <Icon name="clock-circle" size={12} style={{ marginRight: 6, verticalAlign: '-2px' }} />
          체크포인트{' '}
          <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>
            {item.checkpoint}
          </code>
          에서 일시정지됨 — 승인하면 여기서 재개됩니다.
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
        <Button danger icon={<Icon name="close" />} loading={busy === 'reject'} disabled={!!busy} onClick={() => act('reject')}>
          거부
        </Button>
        <Button type="primary" icon={<Icon name="check" />} loading={busy === 'approve'} disabled={!!busy} onClick={() => act('approve')}>
          승인 및 재개
        </Button>
      </div>
    </Panel>
  )
}

// 처리됨(감사) 카드 — 읽기 전용. 결과·처리 시각·처리자(본인/관리자)를 보여준다(스펙 181).
function HistoryCard({ item }: { item: Approval }) {
  const approved = item.status === 'approved'
  return (
    <Panel style={{ padding: 0 }}>
      <CardHeaderRow
        agent={item.agent}
        sessionId={item.sessionId}
        pad="12px 18px"
        rightTag={
          <Tag color={approved ? 'green' : 'red'}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name={approved ? 'check' : 'close'} size={11} />
              {approved ? '승인됨' : '거부됨'}
            </span>
          </Tag>
        }
      />
      <div style={{ padding: '14px 18px' }}>
        <div style={{ fontSize: 14, color: 'var(--color-text-heading)', marginBottom: 10 }}>{item.summary}</div>
        <PermActionTags permission={item.permission} action={item.action} />
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', lineHeight: 1.8 }}>
          <div>
            <Icon name={item.resolvedBySelf ? 'user' : 'lock'} size={12} style={{ marginRight: 6, verticalAlign: '-2px' }} />
            {item.resolvedBySelf ? '본인 처리' : '관리자 처리'}
          </div>
          <div>
            <Icon name="clock-circle" size={12} style={{ marginRight: 6, verticalAlign: '-2px' }} />
            처리 시각 {item.resolvedAt ?? '—'}
          </div>
          <div style={{ color: 'var(--color-text-quaternary)' }}>요청 {item.requestedAt}</div>
        </div>
      </div>
    </Panel>
  )
}

export default function ApprovalsView({ onPendingChange }: { onPendingChange?: (n: number) => void } = {}) {
  const [queue, setQueue] = useState<Approval[]>([])
  const [tab, setTab] = useState<'pending' | 'resolved'>('pending') // 대기 중 / 처리됨(스펙 181)
  const [history, setHistory] = useState<Approval[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  useEffect(() => {
    let alive = true
    // 승인 큐는 pending만 — resolved 항목이 재로드 시 재등장하지 않도록 서버에서 필터(045).
    listApprovals('pending')
      .then((items) => {
        if (alive) {
          setQueue(items)
          onPendingChange?.(items.length)
        }
      })
      .catch((e: unknown) => {
        if (alive) message.error(e instanceof Error ? e.message : '승인 목록을 불러오지 못했습니다.')
      })
    return () => {
      alive = false
    }
  }, [])

  // 처리됨 탭 진입 시(또는 처리 후 무효화되면) 이력 로드 — 전체 조회에서 pending 제외, 처리 시각 최근순.
  // listApprovals는 소유 스코프(일반 유저=자기 것)라 이력도 자동으로 자기 것만.
  useEffect(() => {
    if (tab !== 'resolved' || historyLoaded) return
    let alive = true
    listApprovals()
      .then((items) => {
        if (!alive) return
        const done = items
          .filter((a) => a.status && a.status !== 'pending')
          .sort((a, b) => (b.resolvedAt ?? '').localeCompare(a.resolvedAt ?? ''))
        setHistory(done)
        setHistoryLoaded(true)
      })
      .catch((e: unknown) => alive && message.error(e instanceof Error ? e.message : '승인 내역을 불러오지 못했습니다.'))
    return () => {
      alive = false
    }
  }, [tab, historyLoaded])

  const resolve = async (item: Approval, decision: 'approve' | 'reject') => {
    try {
      await resolveApproval(item.id, decision)
      setHistoryLoaded(false) // 처리됨 목록 무효화 — 다음 진입 시 이 건 포함해 재조회
      // 함수형 updater로 최신 큐에서 제거(연속 resolve 시 stale 클로저가 항목을 되살리지
      // 않게) + 외부 콜백 onPendingChange는 리듀서 밖에서 1회 호출(StrictMode 이중 호출
      // 노출 방지). 길이는 멱등한 로컬 캡처로 전달(적대 리뷰 045).
      let nextLen = 0
      setQueue((q) => {
        const next = q.filter((x) => x.id !== item.id)
        nextLen = next.length
        return next
      })
      onPendingChange?.(nextLen)
      if (decision === 'approve') message.success(`승인됨 — ${item.checkpoint}에서 ${item.agent} 재개 중`)
      else message.warning(`거부됨 — ${item.agent} 실행 중단`)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '결정을 처리하지 못했습니다.')
    }
  }

  return (
    <Page title="승인" subtitle="체크포인트에서 일시정지된 승인 작업 — 대기 중 결정 + 처리 내역">
      <div style={{ marginBottom: 16 }}>
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as 'pending' | 'resolved')}
          options={[
            { label: `대기 중${queue.length ? ` (${queue.length})` : ''}`, value: 'pending' },
            { label: '처리됨', value: 'resolved' },
          ]}
        />
      </div>

      {tab === 'pending' ? (
        queue.length === 0 ? (
          <Panel style={{ padding: '56px 24px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
            <Icon name="check-circle" size={30} style={{ color: 'var(--color-success)' }} />
            <div style={{ marginTop: 10, fontSize: 14 }}>대기 중인 승인이 없습니다. 모두 처리됐어요.</div>
          </Panel>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 16, alignItems: 'start' }}>
            {queue.map((item) => (
              <ApprovalCard key={item.id} item={item} onResolve={resolve} />
            ))}
          </div>
        )
      ) : history.length === 0 ? (
        <Panel style={{ padding: '56px 24px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
          <Icon name="clock-circle" size={30} />
          <div style={{ marginTop: 10, fontSize: 14 }}>처리된 승인 내역이 아직 없습니다.</div>
        </Panel>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 16, alignItems: 'start' }}>
          {history.map((item) => (
            <HistoryCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </Page>
  )
}
