/* my-agents admin — 평가(Eval) 화면 (스펙 137, admin 전용).
   문제집(데이터셋) CRUD·케이스 편집(선언적 asserts: 필수/금지 도구 채점 포함)·시험 실행·성적표.
   수치 검증→자율 반복(Ralph) 로드맵의 제품 표면. 러너는 오염 제로(백엔드 eval_runner) —
   실행해도 세션/메모리에 흔적이 남지 않는다. */
import { useState, useEffect, useCallback } from 'react'
import { Tabs, Button, Input, Select, Tag, Modal, Popconfirm, Alert, Collapse, Checkbox, Tooltip, message } from 'antd'
import { Page, DataTable, Drawer, Desc, type Column } from '../shared'
import { Icon } from '../icons'
import { TrendChart, CompareDrawer } from './EvalTrend'
import { MatrixView } from './EvalMatrix'
import {
  listEvalDatasets, createEvalDataset, deleteEvalDataset,
  listEvalCases, createEvalCase, updateEvalCase, deleteEvalCase,
  startEvalRun, listEvalRuns, getEvalRun, listAgents, listCollections, listModels, generateEvalDataset, suggestEvalCases, getEvalHelperStatus,
  type EvalDataset, type EvalCaseT, type EvalAssert, type EvalRunT, type EvalRunDetail, type Agent, type Collection, type Model,
} from '../../api'

const { TextArea } = Input

/* assert 유형 — 백엔드 build_asserts의 닫힌 집합과 동일(드리프트 시 400으로 드러남). */
const ASSERT_TYPES: { value: EvalAssert['type']; label: string; needsArg: boolean; hint: string }[] = [
  { value: 'trace_has', label: '필수 도구/노드', needsArg: true, hint: '예: rag: (RAG 필수) · mcp:local-tools/ · memory:used' },
  { value: 'trace_lacks', label: '금지 도구/노드', needsArg: true, hint: '예: mcp:danger/ — 이 흔적이 있으면 실패' },
  { value: 'output_contains', label: '답변에 포함', needsArg: true, hint: '답변에 이 문구가 있어야 통과' },
  { value: 'llm_judge', label: 'AI 판정 (비결정)', needsArg: true, hint: '예: 답변이 정중한 존댓말로 작성되었는가 — 심판 모델이 PASS/FAIL 판정' },
  { value: 'rag_hits_gte', label: 'RAG: 결과 N건 이상', needsArg: true, hint: '예: 2 — 검색 결과가 이 건수 이상(RAG 문제집 전용)' },
  { value: 'rag_score_gte', label: 'RAG: 유사도 임계', needsArg: true, hint: '예: 0.4 — 최고 유사도가 이 값 이상(RAG 문제집 전용)' },
  { value: 'rag_source_contains', label: 'RAG: 근거 파일명', needsArg: true, hint: '예: AB테스트.md — 이 파일이 근거로 나와야 함(RAG 문제집 전용)' },
  { value: 'no_error', label: '오류 없음', needsArg: false, hint: '실행 오류가 없어야 통과' },
  { value: 'output_nonempty', label: '답변 비어있지 않음', needsArg: false, hint: '' },
]

/* 도구 정직성(스펙 170) — trace_nodes 중 실제 호출된 도구 흔적(rag/mcp/memory)이 하나라도 있나.
   그래프 노드(원형)는 도구가 아니므로 접두로만 판정(trace_has와 동일 어휘). */
const TOOL_TRACE_PREFIXES = ['rag:', 'mcp:', 'memory:']
const firedTool = (nodes?: string[] | null) =>
  (nodes ?? []).some((n) => TOOL_TRACE_PREFIXES.some((p) => String(n).startsWith(p)))

function AssertEditor({ value, onChange, kind }: { value: EvalAssert[]; onChange: (v: EvalAssert[]) => void; kind: 'agent' | 'rag' }) {
  // kind별 유형 필터(codex 140 #3) — rag 전용 기준을 agent 문제집에 넣으면 fail-closed로 항상
  // 실패해 혼란만 준다. rag 문제집에선 도구 흔적 기준(trace_*)이 무의미해 숨긴다.
  const types = ASSERT_TYPES.filter((t) =>
    kind === 'rag' ? !t.value.startsWith('trace_') : !t.value.startsWith('rag_')
  )
  // 도구 정직성 안내(스펙 170) — agent 케이스에 도구 검사(trace_*)가 하나도 없으면 조용히 찔러준다.
  // 막지 않음: 모든 케이스가 도구를 써야 하는 건 아니므로(과잉 강제는 독). 거짓 초록은 출제 시 태어남.
  const lacksToolCheck = kind === 'agent' && !value.some((a) => a.type === 'trace_has' || a.type === 'trace_lacks')
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
              options={types.map((t) => ({ value: t.value, label: t.label }))}
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
      <Button size="small" icon={<Icon name="plus" />} onClick={() => onChange([...value, { type: types[0].value, arg: '' }])} style={{ alignSelf: 'flex-start' }}>
        채점 기준 추가
      </Button>
      {lacksToolCheck ? (
        <div style={{ fontSize: 12, color: 'var(--color-warning-text, #d46b08)', display: 'flex', gap: 6, alignItems: 'flex-start' }}>
          <Icon name="info" size={12} style={{ marginTop: 2 }} />
          <span>도구 호출을 검사하는 기준이 없습니다. RAG·MCP가 <b>꼭 불려야 하는</b> 질문이면 <b>'필수 도구/노드'</b>를 추가하세요 — 안 그러면 도구를 안 불러도 통과할 수 있어요.</span>
        </div>
      ) : null}
    </div>
  )
}

/* 케이스 편집 폼 — 신규/수정 겸용. */
function CaseForm({
  initial, onSave, onCancel, busy, kind,
}: {
  initial?: EvalCaseT
  onSave: (body: { name: string; input: string; asserts: EvalAssert[] }) => void
  onCancel?: () => void
  busy: boolean
  kind: 'agent' | 'rag'
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [input, setInput] = useState(initial?.input ?? '')
  const [asserts, setAsserts] = useState<EvalAssert[]>(initial?.asserts ?? [{ type: 'no_error' }, { type: 'output_nonempty' }])
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
      <Input placeholder="문제 이름 (예: RAG 필수 회귀)" value={name} onChange={(e) => setName(e.target.value)} />
      <TextArea rows={2} placeholder="에이전트에게 보낼 질문" value={input} onChange={(e) => setInput(e.target.value)} />
      <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>채점 기준 (전부 통과해야 그 문제 통과 · 기준 0개는 자동 실패)</div>
      <AssertEditor value={asserts} onChange={setAsserts} kind={kind} />
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
  dataset, agents, collections, chatModels, helper, onClose, onChanged, onRunStarted, onOpenRun,
}: {
  dataset: EvalDataset | null
  agents: Agent[]
  collections: Collection[]
  chatModels: Model[]
  helper: { available: boolean; reason: string | null }
  onClose: () => void
  onChanged: () => void
  onRunStarted: () => void
  onOpenRun: (runId: string) => void
}) {
  const [cases, setCases] = useState<EvalCaseT[]>([])
  const [dsRuns, setDsRuns] = useState<EvalRunT[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [runAgent, setRunAgent] = useState<string | undefined>()
  const [runModels, setRunModels] = useState<string[]>([]) // 모델 비교(스펙 141, 빈 배열=기본 모델 1회)
  const [starting, setStarting] = useState(false)
  const [suggesting, setSuggesting] = useState(false)

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
    setRunAgent(undefined) // 문제집 전환 시 대상 리셋(codex 140 #4 — kind 다른 stale id로 실행 방지)
    setRunModels([])
    void load()
    if (dataset) listEvalRuns(dataset.id).then(setDsRuns).catch(() => setDsRuns([]))
    else setDsRuns([])
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
  const isRag = dataset?.kind === 'rag'
  // 관리 액션(실행·케이스 편집) 게이트(스펙 178 P3) — can_manage 미실림(구버전 응답)은 보이게.
  const canManage = dataset?.can_manage !== false
  const start = async () => {
    if (!dataset || !runAgent) return
    setStarting(true)
    try {
      await startEvalRun(
        dataset.id,
        isRag ? { collectionId: runAgent } : { agentId: runAgent, models: runModels }
      )
      message.success(
        runModels.length > 1
          ? `모델 ${runModels.length}개 비교 실행 시작 — "모델 격자" 탭에서 확인하세요`
          : '시험 실행 시작 — "실행 이력" 탭에서 확인하세요'
      )
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
          {/* 시험 실행 — 소유자·관리자만(스펙 178 P3, 읽기는 공개). 로컬(ui) 에이전트만(러너 제약). */}
          {canManage ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Select
              style={{ minWidth: 220, flex: 1 }}
              placeholder={isRag ? '시험 칠 RAG 컬렉션 선택' : '시험 칠 에이전트 선택 (로컬 ui 에이전트만)'}
              value={runAgent}
              onChange={setRunAgent}
              options={
                isRag
                  ? collections.map((c) => ({ value: c.id, label: c.name }))
                  : localAgents.map((a) => ({ value: a.id, label: a.name }))
              }
            />
            <Button type="primary" icon={<Icon name="thunderbolt" />} loading={starting} disabled={!runAgent || cases.length === 0} onClick={() => void start()}>
              {runModels.length > 1 ? `${runModels.length}개 모델 비교 실행` : '시험 실행'}
            </Button>
          </div>
          ) : null}
          {canManage && !isRag ? (
            <Select
              mode="multiple"
              allowClear
              maxCount={6}
              placeholder="모델 비교 (선택) — 고르지 않으면 에이전트 기본 모델로 1회 실행. 조율형은 메인(분석·종합) 모델만 교체되고 위임받는 에이전트의 모델은 그대로입니다."
              value={runModels}
              onChange={setRunModels}
              options={chatModels.map((m) => ({ value: m.name, label: m.name }))}
            />
          ) : null}
          {/* 성적 추이(스펙 138) — 이 문제집의 완료 런들. 최근 런 목록이 표 뷰 역할(클릭→성적표). */}
          {dsRuns.length > 0 ? (
            <div style={{ padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
                성적 추이{' '}
                <span style={{ fontWeight: 400, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                  (최근 {dsRuns.length}회{dsRuns.length >= 50 ? ' — 50회까지만 표시' : ''})
                </span>
              </div>
              <TrendChart runs={dsRuns} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
                {dsRuns.slice(0, 5).map((r) => (
                  <div
                    key={r.id}
                    onClick={() => r.status !== 'running' && onOpenRun(r.id)}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, cursor: r.status !== 'running' ? 'pointer' : 'default' }}
                  >
                    <span style={{ color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>{(r.started_at ?? '').slice(5, 16).replace('T', ' ')}</span>
                    <span>{r.agent_name}</span>
                    <div style={{ flex: 1 }} />
                    {r.status === 'ok' ? (
                      <span style={{ fontWeight: 600 }}>{r.score != null ? Math.round(r.score * 100) + '%' : '—'} ({r.passed}/{r.total})</span>
                    ) : r.status === 'running' ? (
                      <Tag color="blue">실행 중</Tag>
                    ) : (
                      <Tag color="red">error</Tag>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {cases.length === 0 ? (
            <Alert type="info" showIcon message="문제가 없습니다 — 아래에서 첫 문제를 추가하세요." />
          ) : null}

          {cases.map((c) =>
            editing === c.id ? (
              <CaseForm key={c.id} initial={c} busy={busy} kind={dataset.kind} onSave={(b) => void save(b, c.id)} onCancel={() => setEditing(null)} />
            ) : (
              <div key={c.id} style={{ padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600 }}>{c.name}</span>
                  <Tag>{c.asserts.length}개 기준</Tag>
                  <div style={{ flex: 1 }} />
                  {canManage ? (
                    <>
                      <Button size="small" type="text" icon={<Icon name="edit" />} onClick={() => setEditing(c.id)} />
                      <Popconfirm title="이 문제를 삭제할까요?" okText="삭제" cancelText="취소" onConfirm={() => void deleteEvalCase(c.id).then(load).then(onChanged)}>
                        <Button size="small" type="text" danger icon={<Icon name="delete" />} />
                      </Popconfirm>
                    </>
                  ) : null}
                </div>
                <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginTop: 6 }}>{c.input}</div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
                  {c.asserts.map((a, i) => (
                    <Tag key={i} color={a.type === 'trace_lacks' ? 'red' : a.type === 'trace_has' ? 'geekblue' : a.type === 'llm_judge' ? 'purple' : 'default'}>
                      {a.type}{a.arg ? `: ${a.arg}` : ''}
                    </Tag>
                  ))}
                </div>
              </div>
            )
          )}

          {canManage ? (
            adding ? (
              <CaseForm busy={busy} kind={dataset.kind} onSave={(b) => void save(b)} onCancel={() => setAdding(false)} />
            ) : (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Button icon={<Icon name="plus" />} onClick={() => setAdding(true)}>
                  문제 추가
                </Button>
                {!isRag ? (
                  /* AI 출제(스펙 143) — 대상 에이전트의 구성(RAG 능력·역할)에 맞춰 문제를 채워준다.
                     도우미는 기본 chat이 실모델일 때만(사용자 원칙 — mock이면 사유 툴팁+비활성). */
                  <Tooltip title={!helper.available ? helper.reason : !runAgent ? '위에서 시험 칠 에이전트를 먼저 선택하세요' : 'AI가 이 에이전트에 맞는 문제 10개를 추가합니다(기존 문제 보존) — 생성 후 수정하세요'}>
                    <Button
                      icon={<Icon name="experiment" />}
                      loading={suggesting}
                      disabled={!helper.available || !runAgent}
                      onClick={() => {
                        if (!dataset || !runAgent) return
                        setSuggesting(true)
                        suggestEvalCases(dataset.id, { agent_id: runAgent, count: 10 })
                          .then(() => {
                            message.success('AI 출제 시작 — 잠시 후 문제가 채워집니다(문제집을 다시 열면 갱신)')
                            onChanged()
                          })
                          .catch((e) => message.error((e as Error).message))
                          .finally(() => setSuggesting(false))
                      }}
                    >
                      AI로 문제 채우기
                    </Button>
                  </Tooltip>
                ) : null}
              </div>
            )
          ) : null}
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
            {/* 도구 정직성 집계(스펙 170) — 통과 중 도구 미호출 건수를 한눈에(거짓 초록 규모). */}
            {(() => {
              const toolless = detail.results.filter((r) => r.case_passed && r.obs && !firedTool(r.obs.trace_nodes)).length
              return toolless > 0 ? (
                <Tooltip title="통과했지만 RAG·MCP·메모리를 하나도 호출하지 않은 케이스 수. 도구가 필요한 질문이라면 '필수 도구/노드' 기준을 추가해 실제 호출을 보증하세요.">
                  <Tag color="orange">도구 미사용 {toolless}건</Tag>
                </Tooltip>
              ) : null
            })()}
          </div>
          <Desc label="에이전트">{detail.agent_name ?? '—'}</Desc>
          {detail.error ? <Alert type="error" showIcon message="실행 오류" description={detail.error} /> : null}
          {detail.results.map((r, i) => (
            <div key={i} style={{ padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Tag color={r.case_passed ? 'green' : 'red'}>{r.case_passed ? '통과' : '실패'}</Tag>
                <span style={{ fontWeight: 600 }}>{r.case_name}</span>
                {/* 도구 정직성(스펙 170) — 통과했지만 도구를 하나도 안 부른 케이스 = 거짓 초록 후보. */}
                {r.case_passed && r.obs && !firedTool(r.obs.trace_nodes) ? (
                  <Tooltip title="이 케이스는 통과했지만 RAG·MCP·메모리를 하나도 호출하지 않았습니다. 도구가 꼭 필요한 질문이면 '필수 도구/노드' 기준을 추가하세요.">
                    <Tag color="orange" style={{ margin: 0 }}>도구 미사용</Tag>
                  </Tooltip>
                ) : null}
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
                        {/* RAG 근거(스펙 140) — 파일·유사도 실값(요약보다 실값+상한 원칙). */}
                        {r.obs.rag && r.obs.rag.hits.length > 0 ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                            {r.obs.rag.hits.map((h, k) => (
                              <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                                <Tag color="geekblue" style={{ margin: 0 }}>{h.score.toFixed(3)}</Tag>
                                <span style={{ fontFamily: 'var(--font-family-code)', overflowWrap: 'anywhere' }}>{h.filename}</span>
                              </div>
                            ))}
                          </div>
                        ) : null}
                        {/* AI 판정 이유(스펙 139) — 비결정 축임을 라벨로 명시. */}
                        {r.obs.judge
                          ? Object.entries(r.obs.judge).map(([crit, v]) => (
                              <div key={crit} style={{ padding: '6px 8px', background: 'var(--purple-1)', borderRadius: 6 }}>
                                <Tag color="purple">AI 판정</Tag>
                                <Tag color={v.pass ? 'green' : 'red'}>{v.pass ? 'PASS' : 'FAIL'}</Tag>
                                <span style={{ fontWeight: 600 }}>{crit}</span>
                                {v.reason ? (
                                  <div style={{ marginTop: 4, color: 'var(--color-text-secondary)' }}>{v.reason}</div>
                                ) : null}
                              </div>
                            ))
                          : null}
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
  const [runFilter, setRunFilter] = useState<string | undefined>() // 실행 이력 문제집 필터(스펙 138)
  const [compareSel, setCompareSel] = useState<string[]>([]) // 비교 선택(최대 2, 같은 문제집·ok만)
  const [compare, setCompare] = useState<string[]>([]) // 비교 드로어에 넘길 확정 쌍
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newKind, setNewKind] = useState<'agent' | 'rag'>('agent')
  const [genOpen, setGenOpen] = useState(false)
  const [genCol, setGenCol] = useState<string | undefined>()
  const [genCount, setGenCount] = useState(10)
  const [genName, setGenName] = useState('')
  const [genBusy, setGenBusy] = useState(false)
  const [collections, setCollections] = useState<Collection[]>([])
  const [chatModels, setChatModels] = useState<Model[]>([])
  const [helper, setHelper] = useState<{ available: boolean; reason: string | null }>({ available: false, reason: '확인 중…' })

  const loadDatasets = useCallback(() => {
    listEvalDatasets().then(setDatasets).catch((e) => message.error((e as Error).message))
  }, [])
  const loadRuns = useCallback(() => {
    listEvalRuns()
      .then((rs) => {
        setRuns(rs)
        // 비교 선택 정리(codex 138 #3) — 갱신 후 목록에 없는/미완료 id가 남아 유령 비교가 되지 않게.
        setCompareSel((sel) => sel.filter((id) => rs.some((r) => r.id === id && r.status === 'ok')))
      })
      .catch((e) => message.error((e as Error).message))
  }, [])

  useEffect(() => {
    loadDatasets()
    loadRuns()
    listAgents().then(setAgents).catch(() => {})
    listCollections().then(setCollections).catch(() => {})
    listModels('chat').then(setChatModels).catch(() => {})
    getEvalHelperStatus().then(setHelper).catch(() => setHelper({ available: false, reason: '도우미 상태 확인 실패' }))
  }, [loadDatasets, loadRuns])

  // 실행 중인 런이 있으면 5초 폴링(성적 반영) — 없으면 중지.
  useEffect(() => {
    if (!runs.some((r) => r.status === 'running')) return
    const t = setInterval(loadRuns, 5000)
    return () => clearInterval(t)
  }, [runs, loadRuns])

  const dsCols: Column<EvalDataset>[] = [
    {
      key: 'name', title: '문제집',
      render: (d) => (
        <div>
          <div style={{ fontWeight: 600 }}>{d.name}</div>
          {d.description ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{d.description}</div>
          ) : null}
        </div>
      ),
    },
    { key: 'kind', title: '종류', width: 90, render: (d) => <Tag>{d.kind}</Tag> },
    { key: 'case_count', title: '문제 수', width: 90, align: 'right', render: (d) => d.case_count },
    {
      key: 'actions', title: '', width: 60,
      render: (d) =>
        // 삭제는 소유자·관리자만(읽기는 공개, 스펙 178 P3) — can_manage 미실림(구버전 응답)은 보이게.
        d.can_manage !== false ? (
          <span onClick={(e) => e.stopPropagation()}>
            <Popconfirm title="문제집과 모든 문제·성적을 삭제할까요?" okText="삭제" cancelText="취소" onConfirm={() => void deleteEvalDataset(d.id).then(loadDatasets)}>
              <Button size="small" type="text" danger icon={<Icon name="delete" />} />
            </Popconfirm>
          </span>
        ) : null,
    },
  ]

  const toggleCompare = (r: EvalRunT) => {
    setCompareSel((sel) => {
      if (sel.includes(r.id)) return sel.filter((x) => x !== r.id)
      const first = runs.find((x) => x.id === sel[0])
      // 같은 문제집의 ok 런만 비교 대상 — 다른 문제집을 고르면 새로 시작.
      if (first && first.dataset_id !== r.dataset_id) return [r.id]
      return sel.length >= 2 ? [sel[1], r.id] : [...sel, r.id]
    })
  }
  const runCols: Column<EvalRunT>[] = [
    {
      key: 'cmp', title: '비교', width: 56, align: 'center',
      render: (r) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Checkbox
            disabled={r.status !== 'ok'}
            checked={compareSel.includes(r.id)}
            onChange={() => toggleCompare(r)}
          />
        </span>
      ),
    },
    { key: 'dataset_name', title: '문제집', render: (r) => r.dataset_name ?? '—' },
    { key: 'agent_name', title: '대상', render: (r) => r.agent_name ?? '—' },
    { key: 'model_name', title: '모델', width: 140, hideBelow: 'md', render: (r) => (r.model_name ? <Tag style={{ margin: 0 }}>{r.model_name}</Tag> : '—') },
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
                {/* 소유 기반 공개(스펙 178 P3) — 읽기는 모든 사용자, 편집·실행은 소유자·관리자만. */}
                <Alert type="info" showIcon message="평가 결과는 모든 사용자에게 공개됩니다" />
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Button type="primary" icon={<Icon name="plus" />} onClick={() => setCreating(true)}>
                    새 문제집
                  </Button>
                  <Button icon={<Icon name="experiment" />} onClick={() => setGenOpen(true)}>
                    컬렉션에서 생성
                  </Button>
                </div>
                <DataTable<EvalDataset> columns={dsCols} rows={datasets} onRowClick={setDetail} empty="문제집이 없습니다 — 첫 문제집을 만들어 보세요." />
              </div>
            ),
          },
          {
            key: 'matrix', label: '모델 격자',
            children: <MatrixView runs={runs} onOpenRun={(id) => setRunDetail(id)} />,
          },
          {
            key: 'runs', label: '실행 이력',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Button icon={<Icon name="reload" />} onClick={loadRuns}>새로고침</Button>
                  <Select
                    allowClear
                    style={{ minWidth: 200 }}
                    placeholder="문제집으로 필터"
                    value={runFilter}
                    onChange={(v) => { setRunFilter(v); setCompareSel([]) }}
                    options={datasets.map((d) => ({ value: d.id, label: d.name }))}
                  />
                  <div style={{ flex: 1 }} />
                  <Button
                    type="primary"
                    disabled={compareSel.length !== 2}
                    onClick={() => setCompare(compareSel)}
                    title="같은 문제집의 완료된 런 2개를 체크하면 비교할 수 있습니다"
                  >
                    선택 {compareSel.length}/2 비교
                  </Button>
                </div>
                <DataTable<EvalRunT>
                  columns={runCols}
                  rows={runFilter ? runs.filter((r) => r.dataset_id === runFilter) : runs}
                  onRowClick={(r) => setRunDetail(r.id)}
                  empty="실행 이력이 없습니다."
                />
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
          void createEvalDataset({ name: newName.trim(), description: newDesc.trim() || null, kind: newKind })
            .then(() => {
              setCreating(false)
              setNewName('')
              setNewDesc('')
              setNewKind('agent')
              loadDatasets()
            })
            .catch((e) => message.error((e as Error).message))
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Select
            value={newKind}
            onChange={setNewKind}
            options={[
              { value: 'agent', label: '에이전트 시험 — 에이전트에게 질문하고 답변·도구 사용을 채점' },
              { value: 'rag', label: 'RAG 컬렉션 시험 — 컬렉션 검색 품질(결과 수·유사도·근거 문서)을 채점' },
            ]}
          />
          <Input placeholder="이름 (예: 옵시디언 매니저 회귀 시험)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Input placeholder="설명 (선택)" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
        </div>
      </Modal>

      <Modal
        open={genOpen}
        title="컬렉션에서 문제집 생성"
        okText="생성"
        cancelText="취소"
        okButtonProps={{ disabled: !genCol || !genName.trim(), loading: genBusy }}
        onCancel={() => setGenOpen(false)}
        onOk={() => {
          if (!genCol) return
          setGenBusy(true)
          generateEvalDataset({ collection_id: genCol, name: genName.trim(), count: genCount })
            .then(() => {
              setGenOpen(false)
              setGenName('')
              message.success('생성 시작 — 문제집 목록의 설명에 진행 상태가 표시됩니다')
              loadDatasets()
            })
            .catch((e) => message.error((e as Error).message))
            .finally(() => setGenBusy(false))
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            컬렉션 문서에서 질문을 자동 출제합니다 — 각 문제의 채점 기준은 "그 질문으로 검색하면
            출처 문서가 나와야 한다"(자기일관 골든)로 자동 부여되고, 생성 후 검토·수정할 수 있습니다.
          </div>
          <Select
            placeholder="컬렉션 선택"
            value={genCol}
            onChange={(v) => {
              setGenCol(v)
              const c = collections.find((x) => x.id === v)
              if (c && !genName.trim()) setGenName(`${c.name} 골든셋`)
            }}
            options={collections.map((c) => ({ value: c.id, label: c.name }))}
          />
          <Input placeholder="문제집 이름" value={genName} onChange={(e) => setGenName(e.target.value)} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
            문제 수
            <Select
              value={genCount}
              onChange={setGenCount}
              style={{ width: 90 }}
              options={[5, 10, 15, 20].map((n) => ({ value: n, label: String(n) }))}
            />
          </div>
        </div>
      </Modal>

      <DatasetDrawer
        dataset={detail}
        agents={agents}
        collections={collections}
        chatModels={chatModels}
        helper={helper}
        onClose={() => setDetail(null)}
        onChanged={loadDatasets}
        onRunStarted={() => { loadRuns(); setTab('runs') }}
        onOpenRun={(rid) => { setDetail(null); setRunDetail(rid) }}
      />
      <CompareDrawer aId={compare[0] ?? null} bId={compare[1] ?? null} onClose={() => setCompare([])} />
      <RunDrawer runId={runDetail} onClose={() => setRunDetail(null)} />
    </Page>
  )
}
