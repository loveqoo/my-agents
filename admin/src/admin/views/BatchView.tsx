/* my-agents admin — Batch view (스펙 038 + 039): 격리 배치 토대 + 두 작업.
   세션 보존정리(session-cleanup, 038) + 유저 메모리 통합(memory-consolidation, 039).
   각 패널: 설정(임계치/일수 + cron) 편집 + dry-run/실행 트리거. 하단에 공용 실행 이력.
   백엔드: GET/PATCH /admin/batch/config, POST /admin/batch/{job}/run, GET /admin/batch/runs. */
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

const STATUS_PILL: Record<string, { color: string; label: string }> = {
  ok: { color: 'var(--green-6)', label: 'ok' },
  running: { color: 'var(--gold-6, #d48806)', label: 'running' },
  error: { color: 'var(--red-6, #cf1322)', label: 'error' },
}

/** summary(JSON) 요약을 사람이 읽을 칩으로 — 작업(job_name)별 분기. */
function summarize(r: BatchRun): React.ReactNode {
  const s = r.summary as Record<string, unknown> | null
  if (!s) return <span style={{ color: 'var(--color-text-tertiary)' }}>—</span>
  const st = s.status as string | undefined
  if (r.job_name === 'memory-consolidation') {
    if (st === 'disabled')
      return <Tag>{s.reason === 'no_mem_cfg' ? '비활성(모델 미설정)' : '비활성(임계치 미설정)'}</Tag>
    if (st === 'dry_run')
      return (
        <span>
          <Tag color="geekblue">dry-run</Tag>
          후보 {String((s.candidates as unknown[] | undefined)?.length ?? 0)}명 · 유저{' '}
          {String(s.users_scanned ?? '?')}명 스캔
        </span>
      )
    if (st === 'ok')
      return (
        <span>
          {String((s.consolidated as unknown[] | undefined)?.length ?? 0)}명 통합 · 기억{' '}
          {String(s.total_before ?? '?')}→{String(s.total_after ?? '?')}
        </span>
      )
    return <code style={{ fontSize: 12 }}>{JSON.stringify(s)}</code>
  }
  if (r.job_name === 'a2a-cleanup') {
    // A2A 정크 정리(스펙 050) — 함께 죽는 세션 수도 정직히 표기.
    const casc = s.cascade_sessions != null ? ` (+세션 ${String(s.cascade_sessions)})` : ''
    if (st === 'dry_run')
      return (
        <span>
          <Tag color="geekblue">dry-run</Tag>
          삭제 예정 {String(s.would_delete ?? '?')} 에이전트{casc}
        </span>
      )
    if (st === 'ok')
      return (
        <span>
          삭제 {String(s.deleted ?? '?')} 에이전트{casc}
        </span>
      )
    return <code style={{ fontSize: 12 }}>{JSON.stringify(s)}</code>
  }
  if (r.job_name === 'user-cleanup') {
    // 테스트 유저 정리(스펙 050) — 마지막 super 보존 건수도 표기.
    if (st === 'disabled') return <Tag>비활성(패턴 미설정)</Tag>
    if (st === 'rejected') return <Tag color="red">거부(전체 삭제 패턴)</Tag>
    const prot = (s.protected_superusers as unknown[] | undefined)?.length ?? 0
    const protTxt = prot > 0 ? ` · super ${String(prot)}명 보존` : ''
    if (st === 'dry_run')
      return (
        <span>
          <Tag color="geekblue">dry-run</Tag>
          삭제 예정 {String(s.would_delete ?? '?')}명{protTxt}
        </span>
      )
    if (st === 'ok')
      return (
        <span>
          삭제 {String(s.deleted ?? '?')}명{protTxt}
        </span>
      )
    return <code style={{ fontSize: 12 }}>{JSON.stringify(s)}</code>
  }
  // session-cleanup — 나이·턴 기준의 합집합(스펙 049)이라 활성 기준만 골라 표기.
  const crit = [
    s.retention_days != null ? `보존 ${String(s.retention_days)}일` : null,
    s.min_session_turns != null ? `${String(s.min_session_turns)}턴 미만` : null,
  ]
    .filter(Boolean)
    .join(' · ')
  if (st === 'disabled') return <Tag>비활성(기준 미설정)</Tag>
  if (st === 'dry_run')
    return (
      <span>
        <Tag color="geekblue">dry-run</Tag>
        삭제 예정 {String(s.would_delete ?? '?')}건{crit ? ` · ${crit}` : ''}
      </span>
    )
  if (st === 'ok')
    return (
      <span>
        삭제 {String(s.deleted ?? '?')}건{crit ? ` · ${crit}` : ''}
      </span>
    )
  return <code style={{ fontSize: 12 }}>{JSON.stringify(s)}</code>
}

export default function BatchView() {
  const [cfg, setCfg] = useState<BatchConfig | null>(null)
  // session-cleanup
  const [days, setDays] = useState<number | null>(null)
  const [cron, setCron] = useState<string>('')
  const [minTurns, setMinTurns] = useState<number | null>(null)
  // memory-consolidation
  const [threshold, setThreshold] = useState<number | null>(null)
  const [memCron, setMemCron] = useState<string>('')
  // user-cleanup (스펙 050, #13)
  const [userPattern, setUserPattern] = useState<string>('')

  const [runs, setRuns] = useState<BatchRun[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<'session' | 'memory' | 'user' | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // `${job}:${dry|run}`

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await listBatchRuns(20))
    } catch {
      message.error('실행 이력을 불러오지 못했습니다')
    }
  }, [])

  const applyCfg = useCallback((c: BatchConfig) => {
    setCfg(c)
    setDays(c.session_retention_days)
    setCron(c.session_cleanup_cron ?? '')
    setMinTurns(c.min_session_turns)
    setThreshold(c.memory_consolidation_threshold)
    setMemCron(c.memory_consolidation_cron ?? '')
    setUserPattern(c.test_user_email_pattern ?? '')
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [c] = await Promise.all([getBatchConfig(), loadRuns()])
      applyCfg(c)
    } catch {
      message.error('배치 설정을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [loadRuns, applyCfg])

  useEffect(() => {
    void load()
  }, [load])

  const sessionDirty =
    cfg !== null &&
    (days !== cfg.session_retention_days ||
      (cron || null) !== (cfg.session_cleanup_cron || null) ||
      minTurns !== cfg.min_session_turns)
  const memoryDirty =
    cfg !== null &&
    (threshold !== cfg.memory_consolidation_threshold ||
      (memCron || null) !== (cfg.memory_consolidation_cron || null))
  const userDirty =
    cfg !== null && (userPattern.trim() || null) !== (cfg.test_user_email_pattern || null)

  const save = async (which: 'session' | 'memory' | 'user') => {
    setSaving(which)
    try {
      const body =
        which === 'session'
          ? {
              session_retention_days: days,
              session_cleanup_cron: cron.trim() || null,
              min_session_turns: minTurns,
            }
          : which === 'memory'
            ? {
                memory_consolidation_threshold: threshold,
                memory_consolidation_cron: memCron.trim() || null,
              }
            : { test_user_email_pattern: userPattern.trim() || null }
      applyCfg(await updateBatchConfig(body))
      message.success('배치 설정을 저장했습니다')
    } catch {
      // 백엔드 422(전체 삭제 패턴 거부 등) 포함.
      message.error('저장 실패 — 패턴이 너무 광범위하거나(전체 삭제) 형식이 잘못되었을 수 있습니다')
    } finally {
      setSaving(null)
    }
  }

  const trigger = async (job: string, dryRun: boolean) => {
    setBusy(`${job}:${dryRun ? 'dry' : 'run'}`)
    try {
      const res = await triggerBatchJob(job, dryRun)
      const s = res.summary as Record<string, unknown> | undefined
      if (res.status === 'error') {
        message.error(`실행 오류: ${res.error ?? '알 수 없음'}`)
      } else if (s?.status === 'rejected') {
        message.error('거부됨 — 전체 삭제 위험 패턴입니다. 구체적 이메일 패턴을 설정하세요.')
      } else if (s?.status === 'disabled') {
        message.warning(
          job === 'memory-consolidation'
            ? s.reason === 'no_mem_cfg'
              ? '기본 모델이 설정되지 않아 작업이 비활성 상태입니다'
              : '통합 임계치가 설정되지 않아 작업이 비활성 상태입니다'
            : job === 'user-cleanup'
              ? '테스트 유저 이메일 패턴이 설정되지 않아 작업이 비활성 상태입니다'
              : '보존일수가 설정되지 않아 작업이 비활성 상태입니다',
        )
      } else if (job === 'memory-consolidation') {
        if (dryRun)
          message.success(
            `dry-run 완료 — 후보 ${String((s?.candidates as unknown[] | undefined)?.length ?? 0)}명(실변경 없음)`,
          )
        else
          message.success(
            `통합 완료 — ${String((s?.consolidated as unknown[] | undefined)?.length ?? 0)}명 (기억 ${String(s?.total_before ?? 0)}→${String(s?.total_after ?? 0)})`,
          )
      } else if (job === 'a2a-cleanup') {
        const casc = s?.cascade_sessions != null ? ` (+세션 ${String(s.cascade_sessions)})` : ''
        if (dryRun)
          message.success(
            `dry-run 완료 — 삭제 예정 ${String(s?.would_delete ?? 0)} 에이전트${casc}(실삭제 없음)`,
          )
        else message.success(`실행 완료 — ${String(s?.deleted ?? 0)} 에이전트 삭제${casc}`)
      } else if (job === 'user-cleanup') {
        const prot = (s?.protected_superusers as unknown[] | undefined)?.length ?? 0
        const protTxt = prot > 0 ? ` · super ${String(prot)}명 보존` : ''
        if (dryRun)
          message.success(
            `dry-run 완료 — 삭제 예정 ${String(s?.would_delete ?? 0)}명${protTxt}(실삭제 없음)`,
          )
        else message.success(`실행 완료 — ${String(s?.deleted ?? 0)}명 삭제${protTxt}`)
      } else if (dryRun) {
        message.success(`dry-run 완료 — 삭제 예정 ${String(s?.would_delete ?? 0)}건(실삭제 없음)`)
      } else {
        message.success(`실행 완료 — 삭제 ${String(s?.deleted ?? 0)}건`)
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
      hideBelow: 'xl',
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
      {/* 세션 보존정리 설정 (스펙 038) */}
      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 4px', fontSize: 16 }}>세션 보존정리 (session-cleanup)</h4>
        <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13, marginBottom: 16 }}>
          마지막 활동이 보존일수보다 오래된 세션, 또는 최소 턴 수에 못 미친 이탈 세션과 그 메시지를 삭제합니다.
          장기기억(mem0)은 건드리지 않습니다. 두 기준 모두 비우면 비활성(삭제 안 함)입니다.
          (진행 중인 대화는 보호됩니다 — 최근 1시간 내 활동 세션은 턴 수와 무관하게 정리하지 않습니다.)
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
        <Desc label="최소 턴 수">
          <InputNumber
            min={1}
            max={10000}
            value={minTurns ?? undefined}
            onChange={(v) => setMinTurns(v ?? null)}
            placeholder="비활성"
            addonAfter="턴"
            style={{ width: 160 }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            {minTurns == null
              ? '비활성 — 턴 수로 삭제하지 않음'
              : `${minTurns}턴 미만 이탈 세션 정리(활성 보호)`}
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
            <Button
              type="primary"
              onClick={() => void save('session')}
              loading={saving === 'session'}
              disabled={!sessionDirty}
            >
              설정 저장
            </Button>
            <Button
              onClick={() => void trigger('session-cleanup', true)}
              loading={busy === 'session-cleanup:dry'}
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
              onConfirm={() => void trigger('session-cleanup', false)}
            >
              <Button danger loading={busy === 'session-cleanup:run'} disabled={busy !== null}>
                지금 실행
              </Button>
            </Popconfirm>
          </Space>
          {sessionDirty && (
            <span style={{ marginInlineStart: 12, color: 'var(--gold-6, #d48806)', fontSize: 13 }}>
              저장하지 않은 변경이 있습니다.
            </span>
          )}
        </div>
      </Panel>

      {/* 유저 메모리 통합 설정 (스펙 039) */}
      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 4px', fontSize: 16 }}>유저 메모리 통합 (memory-consolidation)</h4>
        <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13, marginBottom: 16 }}>
          장기기억(mem0 user_id 축)이 임계치를 넘은 유저의 기억을 LLM으로 더 적고 일관된 사실로 통합합니다.
          원본은 삭제 전 스냅샷에 백업합니다(롤백 가능). 임계치를 비우면 비활성입니다.
        </div>
        <Desc label="통합 임계치">
          <InputNumber
            min={2}
            max={10000}
            value={threshold ?? undefined}
            onChange={(v) => setThreshold(v ?? null)}
            placeholder="비활성"
            addonAfter="개"
            style={{ width: 160 }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            {threshold == null
              ? '비활성 — 통합하지 않음'
              : `기억이 ${threshold}개를 넘은 유저만 통합 (최소 2)`}
          </span>
        </Desc>
        <Desc label="스케줄(cron)">
          <Input
            value={memCron}
            onChange={(e) => setMemCron(e.target.value)}
            placeholder="예: 0 5 * * 0  (비우면 자동 실행 안 함)"
            style={{ maxWidth: 280, fontFamily: 'var(--font-mono, monospace)' }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            격리 배치 서비스(batch serve)가 이 cron으로 자동 실행합니다.
          </span>
        </Desc>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button
              type="primary"
              onClick={() => void save('memory')}
              loading={saving === 'memory'}
              disabled={!memoryDirty}
            >
              설정 저장
            </Button>
            <Button
              onClick={() => void trigger('memory-consolidation', true)}
              loading={busy === 'memory-consolidation:dry'}
              disabled={busy !== null}
            >
              Dry-run (미리보기)
            </Button>
            <Popconfirm
              title="지금 실행하시겠습니까?"
              description="유저 기억을 통합하고 원본을 교체합니다. 원본은 스냅샷에 백업되지만 신중히 진행하세요."
              okText="실행"
              cancelText="취소"
              okButtonProps={{ danger: true }}
              onConfirm={() => void trigger('memory-consolidation', false)}
            >
              <Button danger loading={busy === 'memory-consolidation:run'} disabled={busy !== null}>
                지금 실행
              </Button>
            </Popconfirm>
          </Space>
          {memoryDirty && (
            <span style={{ marginInlineStart: 12, color: 'var(--gold-6, #d48806)', fontSize: 13 }}>
              저장하지 않은 변경이 있습니다.
            </span>
          )}
        </div>
      </Panel>

      {/* A2A 정크 정리 (스펙 050, #1) — 설정 없음, dry-run/실행만 */}
      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 4px', fontSize: 16 }}>A2A 정크 정리 (a2a-cleanup)</h4>
        <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13, marginBottom: 16 }}>
          외부(A2A 카드) 소스이면서 endpoint 호스트가 루프백/사설망(127.*·localhost·10.*·192.168.*·
          172.16~31.*)인 에이전트를 삭제합니다 — 테스트가 등록한 프로브 카드만 해당됩니다. 공개 endpoint의
          실 A2A 파트너와 UI/코드 데모 에이전트는 절대 대상이 아닙니다. 삭제 시 그 에이전트의 세션도 함께
          정리됩니다(dry-run에 함께 표시). 설정은 없으며, 먼저 dry-run으로 대상을 확인하세요.
        </div>
        <Space>
          <Button
            onClick={() => void trigger('a2a-cleanup', true)}
            loading={busy === 'a2a-cleanup:dry'}
            disabled={busy !== null}
          >
            Dry-run (미리보기)
          </Button>
          <Popconfirm
            title="지금 실행하시겠습니까?"
            description="프로브 A2A 에이전트와 그 세션을 실제로 삭제합니다. 되돌릴 수 없습니다."
            okText="실행"
            cancelText="취소"
            okButtonProps={{ danger: true }}
            onConfirm={() => void trigger('a2a-cleanup', false)}
          >
            <Button danger loading={busy === 'a2a-cleanup:run'} disabled={busy !== null}>
              지금 실행
            </Button>
          </Popconfirm>
        </Space>
      </Panel>

      {/* 테스트 유저 정리 (스펙 050, #13) — 가장 비가역, 바닥 3겹 */}
      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 4px', fontSize: 16 }}>테스트 유저 정리 (user-cleanup)</h4>
        <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13, marginBottom: 16 }}>
          이메일이 아래 SQL LIKE 패턴에 일치하는 유저를 삭제합니다(액세스 토큰·권한 grant 함께 정리).
          가장 비가역한 작업이라 안전장치 3겹: 패턴을 비우면 비활성, <code>%</code>·빈 패턴 등 전체 삭제
          위험 패턴은 거부, 부트스트랩/데모 계정(admin@·alice@)과 마지막 슈퍼유저는 패턴과 무관하게 보존합니다.
          반드시 먼저 dry-run으로 대상을 확인하세요.
        </div>
        <Desc label="이메일 패턴">
          <Input
            value={userPattern}
            onChange={(e) => setUserPattern(e.target.value)}
            placeholder="예: verify%@example.com  (비우면 비활성)"
            style={{ maxWidth: 320, fontFamily: 'var(--font-mono, monospace)' }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            {userPattern.trim() === ''
              ? '비활성 — 삭제하지 않음'
              : `${userPattern.trim()} 에 일치하는 유저 정리(keep-list·마지막 super 제외)`}
          </span>
        </Desc>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button
              type="primary"
              onClick={() => void save('user')}
              loading={saving === 'user'}
              disabled={!userDirty}
            >
              설정 저장
            </Button>
            <Button
              onClick={() => void trigger('user-cleanup', true)}
              loading={busy === 'user-cleanup:dry'}
              disabled={busy !== null}
            >
              Dry-run (미리보기)
            </Button>
            <Popconfirm
              title="지금 실행하시겠습니까?"
              description="패턴에 일치하는 테스트 유저를 실제로 삭제합니다(토큰·권한 포함). 되돌릴 수 없습니다."
              okText="실행"
              cancelText="취소"
              okButtonProps={{ danger: true }}
              onConfirm={() => void trigger('user-cleanup', false)}
            >
              <Button danger loading={busy === 'user-cleanup:run'} disabled={busy !== null}>
                지금 실행
              </Button>
            </Popconfirm>
          </Space>
          {userDirty && (
            <span style={{ marginInlineStart: 12, color: 'var(--gold-6, #d48806)', fontSize: 13 }}>
              저장하지 않은 변경이 있습니다.
            </span>
          )}
        </div>
      </Panel>

      {/* 실행 이력 (네 작업 공용) */}
      <h4 style={{ margin: '0 0 12px', fontSize: 16 }}>실행 이력</h4>
      <DataTable columns={columns} rows={runs} empty={loading ? '불러오는 중…' : '실행 이력 없음'} />
    </Page>
  )
}
