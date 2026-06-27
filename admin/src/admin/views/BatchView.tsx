/* my-agents admin — Batch view (스펙 038): 격리 배치 토대 + 세션 보존정리.
   보존정리 설정(보존일수 + cron) 편집 + dry-run/실행 트리거 + 실행 이력.
   백엔드: GET/PATCH /admin/batch/config, POST /admin/batch/{job}/run, GET /admin/batch/runs.
   자동화 주 경로는 격리 배치 서비스(api.batch)지만, 여기서 같은 작업 함수를 즉시 호출·검증한다. */
import { useState, useEffect, useCallback } from 'react'
import { Button, InputNumber, Input, Tag, Tooltip, Popconfirm, Space, message } from 'antd'
import { Page, Panel, DataTable, StatusPill, Desc, type Column } from '../shared'
import {
  getBatchConfig,
  updateBatchConfig,
  listBatchRuns,
  triggerBatchJob,
  type BatchConfig,
  type BatchRun,
} from '../../api'

const JOB = 'session-cleanup'

const STATUS_PILL: Record<string, { color: string; label: string }> = {
  ok: { color: 'var(--green-6)', label: 'ok' },
  running: { color: 'var(--gold-6, #d48806)', label: 'running' },
  error: { color: 'var(--red-6, #cf1322)', label: 'error' },
}

/** summary(JSON) 요약을 사람이 읽을 칩으로. dry_run/disabled/ok 분기. */
function summarize(r: BatchRun): React.ReactNode {
  const s = r.summary as Record<string, unknown> | null
  if (!s) return <span style={{ color: 'var(--color-text-tertiary)' }}>—</span>
  const st = s.status as string | undefined
  if (st === 'disabled') return <Tag>비활성(보존일수 미설정)</Tag>
  if (st === 'dry_run')
    return (
      <span>
        <Tag color="geekblue">dry-run</Tag>
        삭제 예정 {String(s.would_delete ?? '?')}건 · 보존 {String(s.retention_days ?? '?')}일
      </span>
    )
  if (st === 'ok')
    return (
      <span>
        삭제 {String(s.deleted ?? '?')}건 · 보존 {String(s.retention_days ?? '?')}일
      </span>
    )
  return <code style={{ fontSize: 12 }}>{JSON.stringify(s)}</code>
}

export default function BatchView() {
  const [cfg, setCfg] = useState<BatchConfig | null>(null)
  const [days, setDays] = useState<number | null>(null)
  const [cron, setCron] = useState<string>('')
  const [runs, setRuns] = useState<BatchRun[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState<'dry' | 'run' | null>(null)

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await listBatchRuns(20))
    } catch {
      message.error('실행 이력을 불러오지 못했습니다')
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [c] = await Promise.all([getBatchConfig(), loadRuns()])
      setCfg(c)
      setDays(c.session_retention_days)
      setCron(c.session_cleanup_cron ?? '')
    } catch {
      message.error('배치 설정을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [loadRuns])

  useEffect(() => {
    void load()
  }, [load])

  const dirty =
    cfg !== null &&
    (days !== cfg.session_retention_days || (cron || null) !== (cfg.session_cleanup_cron || null))

  const save = async () => {
    setSaving(true)
    try {
      const updated = await updateBatchConfig({
        session_retention_days: days,
        session_cleanup_cron: cron.trim() || null,
      })
      setCfg(updated)
      setDays(updated.session_retention_days)
      setCron(updated.session_cleanup_cron ?? '')
      message.success('배치 설정을 저장했습니다')
    } catch {
      message.error('저장 실패')
    } finally {
      setSaving(false)
    }
  }

  const trigger = async (dryRun: boolean) => {
    setBusy(dryRun ? 'dry' : 'run')
    try {
      const res = await triggerBatchJob(JOB, dryRun)
      const summary = res.summary as Record<string, unknown> | undefined
      if (res.status === 'error') {
        message.error(`실행 오류: ${res.error ?? '알 수 없음'}`)
      } else if (summary?.status === 'disabled') {
        message.warning('보존일수가 설정되지 않아 작업이 비활성 상태입니다')
      } else if (dryRun) {
        message.success(`dry-run 완료 — 삭제 예정 ${String(summary?.would_delete ?? 0)}건(실삭제 없음)`)
      } else {
        message.success(`실행 완료 — 삭제 ${String(summary?.deleted ?? 0)}건`)
      }
      await loadRuns()
    } catch {
      message.error('트리거 실패')
    } finally {
      setBusy(null)
    }
  }

  const columns: Column<BatchRun>[] = [
    {
      key: 'job_name',
      title: '작업',
      render: (r) => (
        <div>
          <span style={{ fontWeight: 500 }}>{r.job_name}</span>
          {r.dry_run && (
            <Tag color="geekblue" style={{ marginInlineStart: 8 }}>
              dry-run
            </Tag>
          )}
        </div>
      ),
    },
    {
      key: 'status',
      title: '상태',
      render: (r) => {
        const p = STATUS_PILL[r.status] ?? { color: 'var(--gray-6)', label: r.status }
        return <StatusPill color={p.color} label={p.label} />
      },
    },
    { key: 'summary', title: '결과', render: summarize },
    {
      key: 'error',
      title: '오류',
      render: (r) =>
        r.error ? (
          <Tooltip title={r.error}>
            <span style={{ color: 'var(--red-6, #cf1322)', fontSize: 13 }}>
              {r.error.length > 40 ? r.error.slice(0, 40) + '…' : r.error}
            </span>
          </Tooltip>
        ) : (
          <span style={{ color: 'var(--color-text-tertiary)' }}>—</span>
        ),
    },
    {
      key: 'started_at',
      title: '시작',
      render: (r) => (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>
          {r.started_at ? new Date(r.started_at).toLocaleString() : '—'}
        </span>
      ),
    },
  ]

  return (
    <Page
      title="배치"
      subtitle="격리 배치 서비스가 자동화 주 경로입니다 — 여기서는 같은 작업을 즉시 트리거·검증하고 설정을 편집합니다."
      actions={
        <Button onClick={() => void load()} loading={loading}>
          새로고침
        </Button>
      }
    >
      {/* 세션 보존정리 설정 */}
      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 4px', fontSize: 16 }}>세션 보존정리 (session-cleanup)</h4>
        <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13, marginBottom: 16 }}>
          마지막 활동이 보존일수보다 오래된 세션과 그 메시지를 삭제합니다. 장기기억(mem0)은 건드리지 않습니다.
          보존일수를 비우면 비활성(삭제 안 함)입니다.
        </div>
        <Desc label="보존일수">
          <InputNumber
            min={1}
            max={3650}
            value={days ?? undefined}
            onChange={(v) => setDays(v ?? null)}
            placeholder="비활성"
            addonAfter="일"
            style={{ width: 160 }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            {days == null ? '비활성 — 삭제하지 않음' : `${days}일 이전 세션 정리`}
          </span>
        </Desc>
        <Desc label="스케줄(cron)">
          <Input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            placeholder="예: 0 4 * * *  (비우면 자동 실행 안 함)"
            style={{ maxWidth: 280, fontFamily: 'var(--font-mono, monospace)' }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            격리 배치 서비스(batch serve)가 이 cron으로 자동 실행합니다.
          </span>
        </Desc>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button type="primary" onClick={() => void save()} loading={saving} disabled={!dirty}>
              설정 저장
            </Button>
            <Button
              onClick={() => void trigger(true)}
              loading={busy === 'dry'}
              disabled={busy !== null}
            >
              Dry-run (미리보기)
            </Button>
            <Popconfirm
              title="지금 실행하시겠습니까?"
              description="오래된 세션과 메시지를 실제로 삭제합니다. 되돌릴 수 없습니다."
              okText="실행"
              cancelText="취소"
              okButtonProps={{ danger: true }}
              onConfirm={() => void trigger(false)}
            >
              <Button danger loading={busy === 'run'} disabled={busy !== null}>
                지금 실행
              </Button>
            </Popconfirm>
          </Space>
          {dirty && (
            <span style={{ marginInlineStart: 12, color: 'var(--gold-6, #d48806)', fontSize: 13 }}>
              저장하지 않은 변경이 있습니다.
            </span>
          )}
        </div>
      </Panel>

      {/* 실행 이력 */}
      <h4 style={{ margin: '0 0 12px', fontSize: 16 }}>실행 이력</h4>
      <DataTable
        columns={columns}
        rows={runs}
        empty={loading ? '불러오는 중…' : '실행 이력 없음'}
      />
    </Page>
  )
}
