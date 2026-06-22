/* my-agents admin — Approvals queue: admin-approver permission requests where a
   LangGraph run is paused at a checkpoint (interrupt) awaiting an admin decision.
   Approve → resume from checkpoint; Reject → abort the run. */
import { useState, useEffect } from 'react'
import { Tag, Button, Avatar, Alert } from 'antd'
import { Page, Panel } from '../shared'
import { Icon } from '../icons'
import { ADMIN_APPROVALS, type Approval } from '../mockData'

function ApprovalCard({
  item,
  onResolve,
}: {
  item: Approval
  onResolve: (item: Approval, decision: 'approve' | 'reject') => void
}) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const act = (decision: 'approve' | 'reject') => {
    setBusy(decision)
    setTimeout(() => onResolve(item, decision), 360)
  }
  return (
    <Panel style={{ padding: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--color-border-secondary)' }}>
        <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
          <Icon name="robot" size={13} />
        </Avatar>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{item.agent}</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            <code style={{ fontFamily: 'var(--font-family-code)' }}>{item.sessionId}</code> · {item.requestedAt}
          </div>
        </div>
        <Tag color="purple">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Icon name="team" size={11} />관리자 승인
          </span>
        </Tag>
      </div>

      <div style={{ padding: '16px 18px' }}>
        <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--color-text-heading)', marginBottom: 10 }}>{item.summary}</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          <Tag color="geekblue">{item.permission}</Tag>
          <Tag color="cyan">
            <code style={{ fontFamily: 'var(--font-family-code)' }}>{item.action}</code>
          </Tag>
        </div>
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          <Icon name="clock-circle" size={12} />
          체크포인트 <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)' }}>{item.checkpoint}</code>에서 일시정지됨 — 승인하면 여기서 재개됩니다.
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

export default function ApprovalsView() {
  const [queue, setQueue] = useState<Approval[]>([...ADMIN_APPROVALS])
  const [toast, setToast] = useState<{ type: 'success' | 'warning'; msg: string } | null>(null)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 2600)
    return () => clearTimeout(t)
  }, [toast])

  const resolve = (item: Approval, decision: 'approve' | 'reject') => {
    setQueue((q) => q.filter((x) => x.id !== item.id))
    setToast(
      decision === 'approve'
        ? { type: 'success', msg: `승인됨 — ${item.checkpoint}에서 ${item.agent} 재개 중` }
        : { type: 'warning', msg: `거부됨 — ${item.agent} 실행 중단` },
    )
  }

  return (
    <Page title="승인" subtitle="체크포인트에서 일시정지된 관리자 승인 작업 — 결정을 기다립니다">
      {queue.length === 0 ? (
        <Panel style={{ padding: '56px 24px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
          <Icon name="check-circle" size={30} style={{ color: 'var(--color-success)' }} />
          <div style={{ marginTop: 10, fontSize: 14 }}>대기 중인 승인이 없습니다. 모두 처리됐어요.</div>
        </Panel>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
          {queue.map((item) => (
            <ApprovalCard key={item.id} item={item} onResolve={resolve} />
          ))}
        </div>
      )}

      {toast ? (
        <div style={{ position: 'absolute', top: 16, left: 0, right: 0, display: 'flex', justifyContent: 'center', zIndex: 1100, pointerEvents: 'none' }}>
          <div style={{ pointerEvents: 'auto' }}>
            <Alert type={toast.type} showIcon message={toast.msg} />
          </div>
        </div>
      ) : null}
    </Page>
  )
}
