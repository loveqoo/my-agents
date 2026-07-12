/* my-agents admin — 승인 큐(스펙 251 개편). 복잡도 1위(전건 카드 그리드·화면 22배)를
   서버 페이지네이션(PagedListShell, 스펙 128) + 3층 위계로 처방:
   - 주 과업 = 대기 건 판정 → 행은 판정 요약만(권한·요약·에이전트·시각·액션)
   - 인자 JSON 등 상세 = 행 클릭 드로어(3층)
   - 대기/처리됨 Tabs(판정 큐 vs 감사 기록 — 성격 다른 도구, 212 규칙)
   Approve → 체크포인트에서 재개, Reject → 실행 중단(기존 resolve API 그대로). */
import { useState } from 'react'
import { Tag, Button, message, Tabs, Drawer, Descriptions, Grid } from 'antd'
import { Page } from '../shared'
import { fmtDateTime } from '../format'
import { type Approval } from '../mockData'
import { listApprovalsPage, resolveApproval } from '../../api'
import { PagedListShell, type ListController } from './PagedListShell'
import { runWithToast } from '../../hooks'

function ResultTag({ item }: { item: Approval }) {
  const approved = item.status === 'approved'
  return (
    <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      <Tag color={approved ? 'green' : 'red'} style={{ margin: 0 }}>{approved ? '승인' : '거부'}</Tag>
      {item.resolvedBySelf != null && (
        <Tag style={{ margin: 0 }}>{item.resolvedBySelf ? '본인' : '관리자'}</Tag>
      )}
    </span>
  )
}

/* 요약 셀 — 1차: 요약문, 2차: 에이전트 · 체크포인트(대기) / 에이전트(처리). */
function SummaryCell({ item, showCheckpoint }: { item: Approval; showCheckpoint?: boolean }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color: 'var(--color-text-heading)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.summary}</div>
      <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', overflowWrap: 'anywhere' }}>
        {item.agent}
        {showCheckpoint && item.checkpoint ? (
          // 긴 식별자가 모바일 카드 폭을 관통(오버플로 실측 20건) — 줄바꿈 허용. full은 드로어.
          <> · <code style={{ fontFamily: 'var(--font-family-code)', overflowWrap: 'anywhere' }}>{item.checkpoint}</code></>
        ) : null}
      </div>
    </div>
  )
}

export default function ApprovalsView({ onPendingChange }: { onPendingChange?: (n: number) => void }) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const [tab, setTab] = useState<'pending' | 'resolved'>('pending')
  const [pendingTotal, setPendingTotal] = useState<number | null>(null)
  const [detail, setDetail] = useState<Approval | null>(null)
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  // resolve 후 재조회(처리 건이 대기→처리로 이동) — refreshKey로 셸에 신호.
  const [refreshKey, setRefreshKey] = useState(0)

  const resolve = async (item: Approval, decision: 'approve' | 'reject', ctl?: ListController) => {
    setBusy(decision)
    const ok = await runWithToast(() => resolveApproval(item.id, decision))
    setBusy(null)
    if (ok) {
      if (decision === 'approve') message.success(`승인됨 — ${item.checkpoint}에서 ${item.agent} 재개 중`)
      else message.warning(`거부됨 — ${item.agent} 실행 중단`)
      setDetail(null)
      setRefreshKey((k) => k + 1)
      // 마지막 항목을 처리해 페이지가 비면 이전 페이지로(셸 관례 — ctl 있을 때만).
      if (ctl && ctl.rowCount === 1 && ctl.page > 1) ctl.setPage(ctl.page - 1)
    }
  }

  const pendingColumns = (ctl: ListController) => [
    {
      key: 'permission',
      title: '권한',
      width: 150,
      render: (r: Approval) => <Tag color="geekblue" style={{ margin: 0 }}>{r.permission}</Tag>,
    },
    { key: 'summary', title: '요청', render: (r: Approval) => <SummaryCell item={r} showCheckpoint /> },
    {
      key: 'requestedAt',
      title: '요청 시각',
      width: 150,
      hideBelow: 'lg' as const,
      render: (r: Approval) => <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{fmtDateTime(r.requestedAt)}</span>,
    },
    {
      key: 'actions',
      title: '',
      width: 190,
      align: 'right' as const,
      render: (r: Approval) => (
        <span style={{ display: 'inline-flex', gap: 6 }} onClick={(e) => e.stopPropagation()}>
          <Button size="small" danger onClick={() => void resolve(r, 'reject', ctl)}>거부</Button>
          <Button size="small" type="primary" onClick={() => void resolve(r, 'approve', ctl)}>승인 및 재개</Button>
        </span>
      ),
    },
  ]

  const resolvedColumns = [
    { key: 'result', title: '결과', width: 130, render: (r: Approval) => <ResultTag item={r} /> },
    { key: 'summary', title: '요청', render: (r: Approval) => <SummaryCell item={r} /> },
    {
      key: 'resolvedAt',
      title: '처리 시각',
      width: 150,
      hideBelow: 'lg' as const,
      render: (r: Approval) => <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{r.resolvedAt ? fmtDateTime(r.resolvedAt) : '—'}</span>,
    },
  ]

  return (
    <Page title="승인" subtitle="체크포인트에서 일시정지된 승인 작업 — 대기 중 결정 + 처리 내역">
      <Tabs
        activeKey={tab}
        onChange={(v) => setTab(v as 'pending' | 'resolved')}
        items={[
          { key: 'pending', label: `대기 중${pendingTotal != null && pendingTotal > 0 ? ` (${pendingTotal})` : ''}` },
          { key: 'resolved', label: '처리됨' },
        ]}
      />
      {/* 탭별 셸 — scopeKey=탭(전환 시 검색·페이지 리셋). 서버가 {items,total}을 소유(스펙 251). */}
      {tab === 'pending' ? (
        <PagedListShell<Approval>
          scopeKey="approvals-pending"
          refreshKey={refreshKey}
          fetchPage={async (q, limit, offset) => {
            const page = await listApprovalsPage('pending', q, limit, offset)
            setPendingTotal(page.total)
            onPendingChange?.(page.total)
            return page
          }}
          columns={pendingColumns}
          onRowClick={(r) => setDetail(r)}
          searchPlaceholder="요약·권한·액션 검색"
          countLabel={(n) => `대기 ${n}건`}
          emptyText="대기 중인 승인이 없습니다. 모두 처리됐어요."
          errorTitle="승인 목록 조회 실패"
        />
      ) : (
        <PagedListShell<Approval>
          scopeKey="approvals-resolved"
          refreshKey={refreshKey}
          fetchPage={(q, limit, offset) => listApprovalsPage('resolved', q, limit, offset)}
          columns={resolvedColumns}
          onRowClick={(r) => setDetail(r)}
          searchPlaceholder="요약·권한·액션 검색"
          countLabel={(n) => `처리 ${n}건`}
          emptyText="처리된 승인 내역이 아직 없습니다."
          errorTitle="승인 내역 조회 실패"
        />
      )}

      {/* 상세 드로어(3층) — 인자 JSON·식별자는 여기로. 대기 건이면 판정도 가능. */}
      <Drawer
        open={!!detail}
        onClose={() => setDetail(null)}
        size={isMobile ? undefined : 480}
        title={detail?.permission}
        footer={
          detail?.status === 'pending' ? (
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Button danger loading={busy === 'reject'} onClick={() => detail && void resolve(detail, 'reject')}>거부</Button>
              <Button type="primary" loading={busy === 'approve'} onClick={() => detail && void resolve(detail, 'approve')}>승인 및 재개</Button>
            </div>
          ) : detail ? (
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}><ResultTag item={detail} /></div>
          ) : null
        }
      >
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ fontSize: 14, color: 'var(--color-text-heading)' }}>{detail.summary}</div>
            <Descriptions
              column={1}
              size="small"
              bordered
              layout={isMobile ? 'vertical' : 'horizontal'}
              labelStyle={{ width: 110 }}
              items={[
                { key: 'agent', label: '에이전트', children: detail.agent },
                {
                  key: 'action',
                  label: '액션',
                  children: <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12 }}>{detail.action}</code>,
                },
                ...(detail.checkpoint
                  ? [{
                      key: 'checkpoint',
                      label: '체크포인트',
                      children: <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12 }}>{detail.checkpoint}</code>,
                    }]
                  : []),
                {
                  key: 'session',
                  label: '세션',
                  children: <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, overflowWrap: 'anywhere' }}>{detail.sessionId}</code>,
                },
                { key: 'requested', label: '요청 시각', children: fmtDateTime(detail.requestedAt) },
                ...(detail.resolvedAt
                  ? [{ key: 'resolved', label: '처리 시각', children: fmtDateTime(detail.resolvedAt) }]
                  : []),
              ]}
            />
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-tertiary)', marginBottom: 6 }}>인자</div>
              <pre
                style={{
                  fontFamily: 'var(--font-family-code)', fontSize: 12, lineHeight: 1.6,
                  background: 'var(--gray-2)', border: '1px solid var(--color-border-secondary)',
                  borderRadius: 8, padding: '10px 12px', margin: 0, whiteSpace: 'pre-wrap',
                  maxHeight: 280, overflow: 'auto',
                }}
              >
                {JSON.stringify(detail.args ?? {}, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </Drawer>
    </Page>
  )
}
