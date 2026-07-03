/* my-agents admin — 평가(Eval) 화면 (스펙 137, admin 전용).
   문제집(데이터셋) CRUD·케이스 편집(선언적 asserts: 필수/금지 도구 채점 포함)·시험 실행·성적표.
   수치 검증→자율 반복(Ralph) 로드맵의 제품 표면. 러너는 오염 제로(백엔드 eval_runner) —
   실행해도 세션/메모리에 흔적이 남지 않는다. */
import { useState, useEffect, useCallback } from 'react'
import { Tabs, Button, Input, Select, Tag, Modal, Popconfirm, Alert, Collapse, message } from 'antd'
import { Page, DataTable, Drawer, Desc, type Column } from '../shared'
import { Icon } from '../icons'
import {
  listEvalDatasets, createEvalDataset, deleteEvalDataset,
  listEvalCases, createEvalCase, updateEvalCase, deleteEvalCase,
  startEvalRun, listEvalRuns, getEvalRun, listAgents,
  type EvalDataset, type EvalCaseT, type EvalAssert, type EvalRunT, type EvalRunDetail, type Agent,
} from '../../api'

const { TextArea } = Input

/* assert 유형 — 백엔드 build_asserts의 닫힌 집합과 동일(드리프트 시 400으로 드러남). */
const ASSERT_TYPES: { value: EvalAssert['type']; label: string; needsArg: boolean; hint: string }[] = [
  { value: 'trace_has', label: '필수 도구/노드', needsArg: true, hint: '예: rag: (RAG 필수) · mcp:local-tools/ · memory:used' },
  { value: 'trace_lacks', label: '금지 도구/노드', needsArg: true, hint: '예: mcp:danger/ — 이 흔적이 있으면 실패' },
  { value: 'output_contains', label: '답변에 포함', needsArg: true, hint: '답변에 이 문구가 있어야 통과' },
  { value: 'no_error', label: '오류 없음', needsArg: false, hint: '실행 오류가 없어야 통과' },
  { value: 'output_nonempty', label: '답변 비어있지 않음', needsArg: false, hint: '' },
]

function AssertEditor({ value, onChange }: { value: EvalAssert[]; onChange: (v: EvalAssert[]) => void }) {
  const set = (i: number, patch: Partial<EvalAssert>) =>
    onChange(value.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {value.map((a, i) => {
        const meta = ASSERT_TYPES.find((t) => t.value === a.type)
        return (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <Select
              size="small"
              style={{ width: 170 }}
              value={a.type}
              onChange={(v) => set(i, { type: v, ...(ASSERT_TYPES.find((t) => t.value === v)?.needsArg ? {} : { arg: undefined }) })}
              options={ASSERT_TYPES.map((t) => ({ value: t.value, label: t.label }))}
            />
            {meta?.needsArg ? (
              <Input
                size="small"
                style={{ flex: 1, minWidth: 160 }}
                placeholder={meta.hint}
                value={a.arg ?? ''}
                onChange={(e) => set(i, { arg: e.target.value })}
              />
            ) : (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{meta?.hint}</span>
            )}
            <Button size="small" type="text" danger icon={<Icon name="delete" />} onClick={() => onChange(value.filter((_, j) => j !== i))} />
          </div>
        )
      })}
      <Button size="small" icon={<Icon name="plus" />} onClick={() => onChange([...value, { type: 'trace_has', arg: '' }])} style={{ alignSelf: 'flex-start' }}>
        채점 기준 추가
      </Button>
    </div>
  )
}

/* 케이스 편집 폼 — 신규/수정 겸용. */
function CaseForm({
  initial, onSave, onCancel, busy,
}: {
  initial?: EvalCaseT
  onSave: (body: { name: string; input: string; asserts: EvalAssert[] }) => void
  onCancel?: () => void
  busy: boolean
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [input, setInput] = useState(initial?.input ?? '')
  const [asserts, setAsserts] = useState<EvalAssert[]>(initial?.asserts ?? [{ type: 'no_error' }, { type: 'output_nonempty' }])
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
      <Input placeholder="문제 이름 (예: RAG 필수 회귀)" value={name} onChange={(e) => setName(e.target.value)} />
      <TextArea rows={2} placeholder="에이전트에게 보낼 질문" value={input} onChange={(e) => setInput(e.target.value)} />
      <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>채점 기준 (전부 통과해야 그 문제 통과 · 기준 0개는 자동 실패)</div>
      <AssertEditor value={asserts} onChange={setAsserts} />
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        {onCancel ? <Button size="small" onClick={onCancel}>취소</Button> : null}
        <Button size="small" type="primary" loading={busy} disabled={!name.trim() || !input.trim()} onClick={() => onSave({ name: name.trim(), input: input.trim(), asserts })}>
          저장
        </Button>
      </div>
    </div>
  )
}

/* 문제집 상세 드로어 — 케이스 목록/편집 + 시험 실행. */
function DatasetDrawer({
  dataset, agents, onClose, onChanged, onRunStarted,
}: {
  dataset: EvalDataset | null
  agents: Agent[]
  onClose: () => void
  onChanged: () => void
  onRunStarted: () => void
}) {
  const [cases, setCases] = useState<EvalCaseT[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [runAgent, setRunAgent] = useState<string | undefined>()
  const [starting, setStarting] = useState(false)

  const load = useCallback(async () => {
    if (!dataset) return
    try {
      setCases(await listEvalCases(dataset.id))
    } catch (e) {
      message.error((e as Error).message)
    }
  }, [dataset?.id])

  useEffect(() => {
    setEditing(null)
    setAdding(false)
    void load()
  }, [load])

  const save = async (body: { name: string; input: string; asserts: EvalAssert[] }, caseId?: string) => {
    if (!dataset) return
    setBusy(true)
    try {
      if (caseId) await updateEvalCase(caseId, body)
      else await createEvalCase(dataset.id, body)
      setEditing(null)
      setAdding(false)
      await load()
      onChanged()
    } catch (e) {
      message.error('저장 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const localAgents = agents.filter((a) => a.source === 'ui')
  const start = async () => {
    if (!dataset || !runAgent) return
    setStarting(true)
    try {
      await startEvalRun(dataset.id, runAgent)
      message.success('시험 실행 시작 — "실행 이력" 탭에서 확인하세요')
      onRunStarted()
    } catch (e) {
      message.error('실행 실패: ' + (e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  return (
    <Drawer open={!!dataset} width={640} title={dataset ? `문제집 · ${dataset.name}` : ''} onClose={onClose}>
      {dataset ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 시험 실행 — 로컬(ui) 에이전트만(러너 제약). */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Select
              style={{ minWidth: 220, flex: 1 }}
              placeholder="시험 칠 에이전트 선택 (로컬 ui 에이전트만)"
              value={runAgent}
              onChange={setRunAgent}
              options={localAgents.map((a) => ({ value: a.id, label: a.name }))}
            />
            <Button type="primary" icon={<Icon name="thunderbolt" />} loading={starting} disabled={!runAgent || cases.length === 0} onClick={() => void start()}>
              시험 실행
            </Button>
          </div>
          {cases.length === 0 ? (
            <Alert type="info" showIcon message="문제가 없습니다 — 아래에서 첫 문제를 추가하세요." />
          ) : null}

          {cases.map((c) =>
            editing === c.id ? (
              <CaseForm key={c.id} initial={c} busy={busy} onSave={(b) => void save(b, c.id)} onCancel={() => setEditing(null)} />
            ) : (
              <div key={c.id} style={{ padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600 }}>{c.name}</span>
                  <Tag>{c.asserts.length}개 기준</Tag>
                  <div style={{ flex: 1 }} />
                  <Button size="small" type="text" icon={<Icon name="edit" />} onClick={() => setEditing(c.id)} />
                  <Popconfirm title="이 문제를 삭제할까요?" okText="삭제" cancelText="취소" onConfirm={() => void deleteEvalCase(c.id).then(load).then(onChanged)}>
                    <Button size="small" type="text" danger icon={<Icon name="delete" />} />
                  </Popconfirm>
                </div>
                <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginTop: 6 }}>{c.input}</div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
                  {c.asserts.map((a, i) => (
                    <Tag key={i} color={a.type === 'trace_lacks' ? 'red' : a.type === 'trace_has' ? 'geekblue' : 'default'}>
                      {a.type}{a.arg ? `: ${a.arg}` : ''}
                    </Tag>
                  ))}
                </div>
              </div>
            )
          )}

          {adding ? (
            <CaseForm busy={busy} onSave={(b) => void save(b)} onCancel={() => setAdding(false)} />
          ) : (
            <Button icon={<Icon name="plus" />} onClick={() => setAdding(true)} style={{ alignSelf: 'flex-start' }}>
              문제 추가
            </Button>
          )}
        </div>
      ) : null}
    </Drawer>
  )
}

/* 성적표 드로어. */
function RunDrawer({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const [detail, setDetail] = useState<EvalRunDetail | null>(null)
  useEffect(() => {
    setDetail(null)
    if (!runId) return
    let alive = true
    getEvalRun(runId).then((d) => alive && setDetail(d)).catch((e) => message.error((e as Error).message))
    return () => {
      alive = false
    }
  }, [runId])
  return (
    <Drawer open={!!runId} width={640} title={detail ? `성적표 · ${detail.dataset_name ?? ''}` : '성적표'} onClose={onClose}>
      {detail ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 28, fontWeight: 700 }}>{detail.score != null ? Math.round(detail.score * 100) + '%' : '—'}</span>
            <span style={{ color: 'var(--color-text-secondary)' }}>{detail.passed}/{detail.total} 통과</span>
            <Tag color={detail.status === 'ok' ? 'green' : detail.status === 'error' ? 'red' : 'blue'}>{detail.status}</Tag>
          </div>
          <Desc label="에이전트">{detail.agent_name ?? '—'}</Desc>
          {detail.error ? <Alert type="error" showIcon message="실행 오류" description={detail.error} /> : null}
          {detail.results.map((r, i) => (
            <div key={i} style={{ padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Tag color={r.case_passed ? 'green' : 'red'}>{r.case_passed ? '통과' : '실패'}</Tag>
                <span style={{ fontWeight: 600 }}>{r.case_name}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 8, fontSize: 12 }}>
                {r.details.map(([name, ok], j) => (
                  <div key={j} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <Icon name={ok ? 'check-circle' : 'close-circle'} size={12} style={{ color: ok ? 'var(--color-success)' : 'var(--color-error)' }} />
                    <span style={{ fontFamily: 'var(--font-family-code)' }}>{name}</span>
                  </div>
                ))}
              </div>
              {r.obs ? (
                <Collapse
                  size="small"
                  style={{ marginTop: 8 }}
                  items={[{
                    key: 'o',
                    label: <span style={{ fontSize: 12 }}>관측 (답변·흔적)</span>,
                    children: (
                      <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {r.obs.detail ? <Alert type="warning" showIcon message={r.obs.detail} /> : null}
                        <div style={{ whiteSpace: 'pre-wrap', color: 'var(--color-text-secondary)' }}>{r.obs.output || '(빈 답변)'}</div>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {(r.obs.trace_nodes ?? []).map((t, k) => (
                            <Tag key={k} style={{ fontFamily: 'var(--font-family-code)', margin: 0 }}>{t}</Tag>
                          ))}
                        </div>
                      </div>
                    ),
                  }]}
                />
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </Drawer>
  )
}

export default function EvalView() {
  const [tab, setTab] = useState('datasets')
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [runs, setRuns] = useState<EvalRunT[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [detail, setDetail] = useState<EvalDataset | null>(null)
  const [runDetail, setRunDetail] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')

  const loadDatasets = useCallback(() => {
    listEvalDatasets().then(setDatasets).catch((e) => message.error((e as Error).message))
  }, [])
  const loadRuns = useCallback(() => {
    listEvalRuns().then(setRuns).catch((e) => message.error((e as Error).message))
  }, [])

  useEffect(() => {
    loadDatasets()
    loadRuns()
    listAgents().then(setAgents).catch(() => {})
  }, [loadDatasets, loadRuns])

  // 실행 중인 런이 있으면 5초 폴링(성적 반영) — 없으면 중지.
  useEffect(() => {
    if (!runs.some((r) => r.status === 'running')) return
    const t = setInterval(loadRuns, 5000)
    return () => clearInterval(t)
  }, [runs, loadRuns])

  const dsCols: Column<EvalDataset>[] = [
    { key: 'name', title: '문제집', render: (d) => <span style={{ fontWeight: 600 }}>{d.name}</span> },
    { key: 'kind', title: '종류', width: 90, render: (d) => <Tag>{d.kind}</Tag> },
    { key: 'case_count', title: '문제 수', width: 90, align: 'right', render: (d) => d.case_count },
    {
      key: 'actions', title: '', width: 60,
      render: (d) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Popconfirm title="문제집과 모든 문제·성적을 삭제할까요?" okText="삭제" cancelText="취소" onConfirm={() => void deleteEvalDataset(d.id).then(loadDatasets)}>
            <Button size="small" type="text" danger icon={<Icon name="delete" />} />
          </Popconfirm>
        </span>
      ),
    },
  ]

  const runCols: Column<EvalRunT>[] = [
    { key: 'dataset_name', title: '문제집', render: (r) => r.dataset_name ?? '—' },
    { key: 'agent_name', title: '에이전트', render: (r) => r.agent_name ?? '—' },
    {
      key: 'status', title: '상태', width: 100,
      render: (r) =>
        r.status === 'running' ? (
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <Icon name="loading" spin size={12} /> 실행 중
          </span>
        ) : (
          <Tag color={r.status === 'ok' ? 'green' : 'red'}>{r.status}</Tag>
        ),
    },
    {
      key: 'score', title: '점수', width: 110, align: 'right',
      render: (r) => (r.score != null ? `${Math.round(r.score * 100)}% (${r.passed}/${r.total})` : '—'),
    },
    { key: 'started_at', title: '시작', width: 150, hideBelow: 'lg', render: (r) => r.started_at?.slice(0, 19).replace('T', ' ') },
  ]

  return (
    <Page title="평가" subtitle="문제집으로 에이전트를 시험하고 통과율을 수치로 봅니다 — 실행은 세션·메모리에 흔적을 남기지 않습니다.">
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'datasets', label: '문제집',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Button type="primary" icon={<Icon name="plus" />} onClick={() => setCreating(true)} style={{ alignSelf: 'flex-start' }}>
                  새 문제집
                </Button>
                <DataTable<EvalDataset> columns={dsCols} rows={datasets} onRowClick={setDetail} empty="문제집이 없습니다 — 첫 문제집을 만들어 보세요." />
              </div>
            ),
          },
          {
            key: 'runs', label: '실행 이력',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Button icon={<Icon name="reload" />} onClick={loadRuns} style={{ alignSelf: 'flex-start' }}>
                  새로고침
                </Button>
                <DataTable<EvalRunT> columns={runCols} rows={runs} onRowClick={(r) => setRunDetail(r.id)} empty="실행 이력이 없습니다." />
              </div>
            ),
          },
        ]}
      />

      <Modal
        open={creating}
        title="새 문제집"
        okText="만들기"
        cancelText="취소"
        okButtonProps={{ disabled: !newName.trim() }}
        onCancel={() => setCreating(false)}
        onOk={() =>
          void createEvalDataset({ name: newName.trim(), description: newDesc.trim() || null })
            .then(() => {
              setCreating(false)
              setNewName('')
              setNewDesc('')
              loadDatasets()
            })
            .catch((e) => message.error((e as Error).message))
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Input placeholder="이름 (예: 옵시디언 매니저 회귀 시험)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Input placeholder="설명 (선택)" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
        </div>
      </Modal>

      <DatasetDrawer dataset={detail} agents={agents} onClose={() => setDetail(null)} onChanged={loadDatasets} onRunStarted={() => { loadRuns(); setTab('runs') }} />
      <RunDrawer runId={runDetail} onClose={() => setRunDetail(null)} />
    </Page>
  )
}
