/* my-agents admin — 평가(Eval) 화면 (스펙 137, admin 전용).
   문제집(데이터셋) CRUD·케이스 편집(선언적 asserts: 필수/금지 도구 채점 포함)·시험 실행·성적표.
   수치 검증→자율 반복(Ralph) 로드맵의 제품 표면. 러너는 오염 제로(백엔드 eval_runner) —
   실행해도 세션/메모리에 흔적이 남지 않는다. */
import { useState, useEffect, useCallback, type CSSProperties } from 'react'
import { Tabs, Button, Input, InputNumber, AutoComplete, Select, Tag, Modal, Popconfirm, Alert, Collapse, Checkbox, Tooltip, message, Descriptions, Skeleton, List } from 'antd'
import { Page, DataTable, Drawer, type Column } from '../shared'
import { Icon } from '../icons'
import { TrendChart, CompareDrawer } from './EvalTrend'
import { MatrixView } from './EvalMatrix'
import { PagedListShell } from './PagedListShell'
import {
  listEvalDatasets, getEvalDataset, createEvalDataset, deleteEvalDataset,
  listEvalCases, createEvalCase, updateEvalCase, deleteEvalCase,
  startEvalRun, listEvalRuns, getEvalRun, listAgents, listCollections, listModels, suggestEvalCases, getEvalHelperStatus, listDocuments,
  type EvalDataset, type EvalCaseT, type EvalAssert, type EvalRunT, type EvalRunDetail, type Agent, type Collection, type Model,
} from '../../api'

const { TextArea } = Input

/* assert 유형 — 백엔드 build_asserts의 닫힌 집합과 동일(드리프트 시 400으로 드러남).
   cat=카테고리(스캔·그룹·색). 숫자 비교형은 gte/lte 쌍(연산자 select로 왕복, 스펙 194). */
type AssertCat = '답변' | '도구' | 'RAG' | 'AI'
const CAT_META: Record<AssertCat, { color: string; icon: string }> = {
  답변: { color: 'blue', icon: 'message' },
  도구: { color: 'geekblue', icon: 'thunderbolt' },
  RAG: { color: 'purple', icon: 'search' },
  AI: { color: 'gold', icon: 'experiment' },
}
const ASSERT_TYPES: { value: EvalAssert['type']; label: string; needsArg: boolean; hint: string; cat: AssertCat }[] = [
  { value: 'output_contains', label: '답변에 포함', needsArg: true, hint: '답변에 이 문구가 있어야 통과', cat: '답변' },
  { value: 'output_nonempty', label: '답변 비어있지 않음', needsArg: false, hint: '', cat: '답변' },
  { value: 'no_error', label: '오류 없음', needsArg: false, hint: '실행 오류가 없어야 통과', cat: '답변' },
  { value: 'trace_has', label: '필수 도구/노드', needsArg: true, hint: '예: rag: (RAG 필수) · mcp:local-tools/ · memory:used', cat: '도구' },
  { value: 'trace_lacks', label: '금지 도구/노드', needsArg: true, hint: '예: mcp:danger/ — 이 흔적이 있으면 실패', cat: '도구' },
  { value: 'rag_hits_gte', label: 'RAG: 검색 결과 건수', needsArg: true, hint: '2', cat: 'RAG' },
  { value: 'rag_hits_lte', label: 'RAG: 검색 결과 건수', needsArg: true, hint: '2', cat: 'RAG' },
  { value: 'rag_score_gte', label: 'RAG: 최고 유사도', needsArg: true, hint: '0.4', cat: 'RAG' },
  { value: 'rag_score_lte', label: 'RAG: 최고 유사도', needsArg: true, hint: '0.4', cat: 'RAG' },
  { value: 'rag_source_contains', label: 'RAG: 근거 파일명', needsArg: true, hint: '예: AB테스트.md — 이 파일이 근거로 나와야 함', cat: 'RAG' },
  { value: 'llm_judge', label: 'AI 판정 (비결정)', needsArg: true, hint: '예: 답변이 정중한 존댓말로 작성되었는가', cat: 'AI' },
]
const catOf = (t: EvalAssert['type']): AssertCat => ASSERT_TYPES.find((x) => x.value === t)?.cat ?? '답변'

/* assert → 사람이 읽는 한 줄 문장(순수). 편집 폼·저장된 케이스 카드가 **공유**(드리프트 0, 스펙 194 E). */
export function assertLabel(a: EvalAssert): string {
  const arg = (a.arg ?? '').trim()
  switch (a.type) {
    case 'no_error': return '오류 없음'
    case 'output_nonempty': return '답변 비어있지 않음'
    case 'output_contains': return `답변에 "${arg}" 포함`
    case 'trace_has': return `${arg} 호출됨`
    case 'trace_lacks': return `${arg} 호출 안 됨`
    case 'rag_hits_gte': return `검색 결과 ${arg}건 이상`
    case 'rag_hits_lte': return `검색 결과 ${arg}건 이하`
    case 'rag_score_gte': return `유사도 ${arg} 이상`
    case 'rag_score_lte': return `유사도 ${arg} 이하`
    case 'rag_source_contains': return `근거 파일 "${arg}"`
    case 'llm_judge': return `AI 판정: ${arg}`
    default: return a.type
  }
}

/* 도구 정직성(스펙 170) — trace_nodes 중 실제 호출된 도구 흔적(rag/mcp/memory)이 하나라도 있나.
   그래프 노드(원형)는 도구가 아니므로 접두로만 판정(trace_has와 동일 어휘). */
const TOOL_TRACE_PREFIXES = ['rag:', 'mcp:', 'memory:']
const firedTool = (nodes?: string[] | null) =>
  (nodes ?? []).some((n) => TOOL_TRACE_PREFIXES.some((p) => String(n).startsWith(p)))

function AssertEditor({ value, onChange, kind, filenames }: { value: EvalAssert[]; onChange: (v: EvalAssert[]) => void; kind: 'agent' | 'rag'; filenames?: string[] }) {
  // kind별 유형 필터(codex 140 #3): rag 문제집엔 trace_*, agent엔 rag_* 숨김(fail-closed 혼란 방지).
  // lte는 유형 select에서 숨기고 연산자 select(이상/이하)로 gte↔lte 전환(스펙 194 — 사람이 읽는 문장형).
  const pool = ASSERT_TYPES.filter((t) =>
    (kind === 'rag' ? !t.value.startsWith('trace_') : !t.value.startsWith('rag_')) && !t.value.endsWith('_lte')
  )
  const grouped = (['답변', '도구', 'RAG', 'AI'] as AssertCat[])
    .map((c) => ({ label: c, options: pool.filter((t) => t.cat === c).map((t) => ({ value: t.value, label: t.label.replace(/^RAG: /, '') })) }))
    .filter((g) => g.options.length)
  // 유형 select 표시값: lte는 gte로 정규화(연산자 select가 실제 gte/lte 담당).
  const repType = (t: EvalAssert['type']) => (t === 'rag_hits_lte' ? 'rag_hits_gte' : t === 'rag_score_lte' ? 'rag_score_gte' : t)
  // 도구 정직성 안내(스펙 170) — agent 케이스에 도구 검사가 하나도 없으면 조용히 찔러준다(막진 않음).
  const lacksToolCheck = kind === 'agent' && !value.some((a) => a.type === 'trace_has' || a.type === 'trace_lacks')
  const set = (i: number, patch: Partial<EvalAssert>) => onChange(value.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  const txt: CSSProperties = { fontSize: 13, color: 'var(--color-text-secondary)' }

  // 유형별 "문장 안의 입력 요소"(mad-libs) — 읽으면 그대로 자연어가 된다.
  const inline = (a: EvalAssert, i: number) => {
    const fam = a.type.startsWith('rag_hits') ? 'hits' : a.type.startsWith('rag_score') ? 'score' : null
    if (fam) {
      const op = a.type.endsWith('_lte') ? 'lte' : 'gte'
      return (
        <>
          <span style={txt}>{fam === 'hits' ? '검색 결과가' : '최고 유사도가'}</span>
          <InputNumber size="small" style={{ width: 82 }} min={0} max={fam === 'score' ? 1 : undefined} step={fam === 'score' ? 0.05 : 1}
            value={a.arg ? Number(a.arg) : null} onChange={(v) => set(i, { arg: v == null ? '' : String(v) })} />
          {fam === 'hits' ? <span style={txt}>건</span> : null}
          <Select size="small" style={{ width: 76 }} value={op}
            onChange={(o) => set(i, { type: `rag_${fam}_${o}` as EvalAssert['type'] })}
            options={[{ value: 'gte', label: '이상' }, { value: 'lte', label: '이하' }]} />
          <span style={txt}>여야 통과</span>
        </>
      )
    }
    switch (a.type) {
      case 'no_error': return <span style={txt}>실행 오류가 없어야 통과</span>
      case 'output_nonempty': return <span style={txt}>답변이 비어있지 않아야 통과</span>
      case 'output_contains':
        return <><span style={txt}>답변에</span><Input size="small" style={{ flex: 1, minWidth: 130 }} placeholder="예: 환불 정책" value={a.arg ?? ''} onChange={(e) => set(i, { arg: e.target.value })} /><span style={txt}>가 포함되어야 통과</span></>
      case 'trace_has':
      case 'trace_lacks':
        return (
          <>
            <Input size="small" style={{ flex: 1, minWidth: 130 }} placeholder="예: rag: / mcp:local-tools/ / memory:used" value={a.arg ?? ''} onChange={(e) => set(i, { arg: e.target.value })} />
            <span style={txt}>가 {a.type === 'trace_has' ? '호출되어야' : '호출되지 않아야'} 통과</span>
            <span style={{ display: 'inline-flex', gap: 4 }}>
              {['rag:', 'mcp:', 'memory:used'].map((p) => (
                <Button key={p} size="small" style={{ fontSize: 11, padding: '0 6px', height: 22 }} onClick={() => set(i, { arg: p })}>{p}</Button>
              ))}
            </span>
          </>
        )
      case 'rag_source_contains':
        return (
          <>
            <span style={txt}>근거 파일명에</span>
            {filenames && filenames.length ? (
              /* 스펙 195: 등록된 파일에서 고르기(오타 방지). contains 매칭이라 자유입력도 허용(AutoComplete). */
              <AutoComplete size="small" style={{ flex: 1, minWidth: 130 }} placeholder="파일 선택 또는 입력"
                options={filenames.map((f) => ({ value: f }))} value={a.arg ?? ''}
                onChange={(v) => set(i, { arg: v })}
                filterOption={(inp, opt) => String(opt?.value ?? '').toLowerCase().includes(inp.toLowerCase())} />
            ) : (
              <Input size="small" style={{ flex: 1, minWidth: 130 }} placeholder="예: AB테스트.md" value={a.arg ?? ''} onChange={(e) => set(i, { arg: e.target.value })} />
            )}
            <span style={txt}>이 있어야 통과</span>
          </>
        )
      case 'llm_judge':
        return <><span style={txt}>AI 판정:</span><TextArea autoSize={{ minRows: 1 }} style={{ flex: 1, minWidth: 170 }} placeholder="예: 답변이 정중한 존댓말로 작성되었는가 — 심판 모델이 PASS/FAIL" value={a.arg ?? ''} onChange={(e) => set(i, { arg: e.target.value })} /></>
      default: return null
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {value.map((a, i) => {
        const cm = CAT_META[catOf(a.type)]
        return (
          <div key={i}>
            {i > 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '3px 0 3px 4px' }}>
                <div style={{ height: 1, width: 14, background: 'var(--color-border)' }} />
                <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontWeight: 600 }}>그리고</span>
              </div>
            ) : null}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '8px 10px', border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
              <Icon name={cm.icon} size={14} style={{ color: `var(--${cm.color}-6)`, flex: 'none' }} />
              <Select size="small" style={{ width: 148, flex: 'none' }} value={repType(a.type)}
                onChange={(v) => set(i, { type: v, arg: ASSERT_TYPES.find((t) => t.value === v)?.needsArg ? '' : undefined })}
                options={grouped} />
              {inline(a, i)}
              <div style={{ flex: 1 }} />
              <Button size="small" type="text" danger icon={<Icon name="delete" />} onClick={() => onChange(value.filter((_, j) => j !== i))} />
            </div>
          </div>
        )
      })}
      <Button size="small" icon={<Icon name="plus" />} onClick={() => onChange([...value, { type: pool[0].value, arg: pool[0].needsArg ? '' : undefined }])} style={{ alignSelf: 'flex-start' }}>
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

/* 케이스 편집 폼 — 신규/수정 겸용. 스펙 195: '문제 이름' 입력 제거(내부 해시로 관리) → 질문 하나만. */
function CaseForm({
  initial, onSave, onCancel, busy, kind, filenames,
}: {
  initial?: EvalCaseT
  onSave: (body: { input: string; asserts: EvalAssert[] }) => void
  onCancel?: () => void
  busy: boolean
  kind: 'agent' | 'rag'
  filenames?: string[]  // 스펙 195: rag 근거 파일명 AutoComplete 옵션(컬렉션 문서)
}) {
  const [input, setInput] = useState(initial?.input ?? '')
  const [asserts, setAsserts] = useState<EvalAssert[]>(initial?.asserts ?? [{ type: 'no_error' }, { type: 'output_nonempty' }])
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
      <TextArea rows={2} placeholder="에이전트에게 보낼 질문 (이 질문이 문제 제목이 됩니다)" value={input} onChange={(e) => setInput(e.target.value)} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '5px 9px', background: 'var(--geekblue-1)', border: '1px solid var(--geekblue-3)', borderRadius: 6, color: 'var(--color-text-secondary)' }}>
        <Icon name="check-circle" size={13} style={{ color: 'var(--geekblue-6)', flex: 'none' }} />
        <span>아래 <b>모든</b> 기준을 만족해야 이 문제가 통과합니다 (AND) · 기준 0개는 자동 실패</span>
      </div>
      <AssertEditor value={asserts} onChange={setAsserts} kind={kind} filenames={filenames} />
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        {onCancel ? <Button size="small" onClick={onCancel}>취소</Button> : null}
        <Button size="small" type="primary" loading={busy} disabled={!input.trim()} onClick={() => onSave({ input: input.trim(), asserts })}>
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
  const [filenames, setFilenames] = useState<string[]>([])  // 스펙 195: rag 근거 파일명 AutoComplete용

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

  // 스펙 193: 생성 중이면 케이스가 채워지므로 폴링(load=cases 갱신, onChanged=부모 목록·generating 갱신).
  useEffect(() => {
    if (!dataset?.generating) return
    const t = setInterval(() => { void load(); onChanged() }, 2500)
    return () => clearInterval(t)
  }, [dataset?.generating, dataset?.id, load, onChanged])

  // 스펙 195: rag 문제집의 고정 컬렉션 문서 파일명 → 근거 파일명 AutoComplete 옵션(오타 방지).
  useEffect(() => {
    const cid = dataset?.collection_id
    if (!cid) { setFilenames([]); return }
    listDocuments(cid, '', 100)
      .then((p) => setFilenames(Array.from(new Set((p.items ?? []).map((d) => d.filename)))))
      .catch(() => setFilenames([]))
  }, [dataset?.collection_id])

  const save = async (body: { input: string; asserts: EvalAssert[] }, caseId?: string) => {
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
  // 스펙 193: RAG는 고정 컬렉션 우선(있으면 runAgent 불필요), 구버전은 고른 컬렉션(첫 실행 시 백엔드가 고정).
  const ragTarget = isRag ? (dataset?.collection_id ?? runAgent) : null
  const start = async () => {
    if (!dataset || (isRag ? !ragTarget : !runAgent)) return
    setStarting(true)
    try {
      await startEvalRun(
        dataset.id,
        isRag ? { collectionId: ragTarget! } : { agentId: runAgent, models: runModels }
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
            {isRag && dataset.collection_id ? (
              /* 스펙 193: 문제집에 고정된 대상 컬렉션 — 실행 시 재선택 불필요(칩 표시, 버튼만 누르면 됨). */
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 220 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>대상 컬렉션</span>
                <Tag color="geekblue" style={{ margin: 0 }}>
                  {collections.find((c) => c.id === dataset.collection_id)?.name ?? '(삭제된 컬렉션)'}
                </Tag>
              </span>
            ) : (
              <Select
                style={{ minWidth: 220, flex: 1 }}
                placeholder={isRag ? '시험 칠 RAG 컬렉션 선택 (첫 실행 후 이 문제집에 고정됩니다)' : '시험 칠 에이전트 선택 (로컬 ui 에이전트만)'}
                value={runAgent}
                onChange={setRunAgent}
                options={
                  isRag
                    ? collections.map((c) => ({ value: c.id, label: c.name }))
                    : localAgents.map((a) => ({ value: a.id, label: a.name }))
                }
              />
            )}
            <Button type="primary" icon={<Icon name="thunderbolt" />} loading={starting}
              disabled={(isRag ? !ragTarget : !runAgent) || cases.length === 0} onClick={() => void start()}>
              {runModels.length > 1 ? `${runModels.length}개 모델 비교 실행` : '시험 실행'}
            </Button>
            {/* 스펙 195: AI 출제를 상단으로 — 빈 문제집을 만든 뒤 원할 때만 눌러 AI가 문제를 채운다(agent·rag 공통).
               도우미는 기본 chat이 실모델일 때만(mock이면 비활성+사유). rag는 고정 컬렉션 필요. */}
            <Tooltip title={
              !helper.available ? helper.reason
                : isRag ? (dataset.collection_id ? 'AI가 이 컬렉션 문서로 문제 10개를 추가합니다(기존 문제 보존)' : '먼저 시험 실행으로 컬렉션을 고정하세요')
                  : !runAgent ? '시험 칠 에이전트를 먼저 선택하세요'
                    : 'AI가 이 에이전트에 맞는 문제 10개를 추가합니다(기존 문제 보존)'
            }>
              <Button icon={<Icon name="experiment" />} loading={suggesting}
                disabled={!helper.available || (isRag ? !dataset.collection_id : !runAgent)}
                onClick={() => {
                  if (!dataset) return
                  setSuggesting(true)
                  suggestEvalCases(dataset.id, isRag ? { count: 10 } : { agent_id: runAgent, count: 10 })
                    .then(() => { message.success('AI 출제 시작 — 잠시 후 문제가 채워집니다(문제집을 다시 열면 갱신)'); onChanged() })
                    .catch((e) => message.error((e as Error).message))
                    .finally(() => setSuggesting(false))
                }}>
                AI 출제
              </Button>
            </Tooltip>
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
            <div style={{ padding: 12, border: '1px solid var(--geekblue-3)', borderLeft: '3px solid var(--geekblue-5)', borderRadius: 8, background: 'var(--geekblue-1)' }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon name="dashboard" size={14} style={{ color: 'var(--geekblue-6)' }} />
                성적 추이{' '}
                <span style={{ fontWeight: 400, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                  (최근 {dsRuns.length}회{dsRuns.length >= 50 ? ' — 50회까지만 표시' : ''})
                </span>
              </div>
              <TrendChart runs={dsRuns} />
              {/* antd List로 통일(스펙 204) — 클릭 행·정렬은 renderItem에 보존. */}
              <List
                size="small"
                split={false}
                style={{ marginTop: 6 }}
                dataSource={dsRuns.slice(0, 5)}
                rowKey={(r) => r.id}
                renderItem={(r) => (
                  <List.Item
                    onClick={() => r.status !== 'running' && onOpenRun(r.id)}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, padding: '2px 0', border: 'none', cursor: r.status !== 'running' ? 'pointer' : 'default' }}
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
                  </List.Item>
                )}
              />
            </div>
          ) : null}
          {cases.length === 0 && !dataset.generating ? (
            <Alert type="info" showIcon message="문제가 없습니다 — 아래에서 첫 문제를 추가하세요." />
          ) : null}
          {/* 스펙 193: 자동 생성 중이면 아직 안 온 문제 자리를 Skeleton 카드로(무언가 써지는 중임을 시각화).
              gen_target 미노출이라 3개 고정 자리표시 — 폴링으로 실제 케이스가 위에 하나씩 채워진다. */}
          {dataset.generating ? (
            <>
              <div style={{ fontSize: 12, color: 'var(--geekblue-6)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon name="loading" spin size={12} /> AI가 문제를 만드는 중입니다 — 자동으로 채워집니다
              </div>
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={`sk-${i}`} style={{ padding: 12, border: '1px dashed var(--geekblue-3)', borderRadius: 8, background: 'var(--geekblue-1)' }}>
                  <Skeleton active title={{ width: '45%' }} paragraph={{ rows: 1, width: ['85%'] }} />
                </div>
              ))}
            </>
          ) : null}

          {cases.map((c) =>
            editing === c.id ? (
              <CaseForm key={c.id} initial={c} busy={busy} kind={dataset.kind} filenames={filenames} onSave={(b) => void save(b, c.id)} onCancel={() => setEditing(null)} />
            ) : (
              <div key={c.id} style={{ padding: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8 }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                  {/* 스펙 195: '문제 이름' 제거 → 질문을 제목으로(내부 name은 해시, 유저 비노출). */}
                  <span style={{ fontWeight: 600, flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{c.input}</span>
                  {canManage ? (
                    <span style={{ display: 'inline-flex', flex: 'none' }}>
                      <Button size="small" type="text" icon={<Icon name="edit" />} onClick={() => setEditing(c.id)} />
                      <Popconfirm title="이 문제를 삭제할까요?" okText="삭제" cancelText="취소" onConfirm={() => void deleteEvalCase(c.id).then(load).then(onChanged)}>
                        <Button size="small" type="text" danger icon={<Icon name="delete" />} />
                      </Popconfirm>
                    </span>
                  ) : null}
                </div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
                  {/* 스펙 194: raw type 대신 사람이 읽는 문장(assertLabel) — 편집 폼과 같은 어휘(드리프트 0). */}
                  {c.asserts.map((a, i) => (
                    <Tag key={i} color={CAT_META[catOf(a.type)].color}>{assertLabel(a)}</Tag>
                  ))}
                </div>
              </div>
            )
          )}

          {canManage ? (
            adding ? (
              <CaseForm busy={busy} kind={dataset.kind} filenames={filenames} onSave={(b) => void save(b)} onCancel={() => setAdding(false)} />
            ) : (
              <Button icon={<Icon name="plus" />} onClick={() => setAdding(true)} style={{ alignSelf: 'flex-start' }}>
                문제 추가
              </Button>
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
          <Descriptions column={1} size="small" items={[{ key: 'agent', label: '에이전트', children: detail.agent_name ?? '—' }]} />
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

export default function EvalView({ initialCollectionId, onConsumedInitial }: {
  initialCollectionId?: string | null  // 스펙 197: 컬렉션 '평가하기'로 진입 시 프리필할 컬렉션
  onConsumedInitial?: () => void
} = {}) {
  const [tab, setTab] = useState('datasets')
  // 스펙 196: 목록은 PagedListShell이 소유(서버 페이징·검색) — 부모는 재조회 트리거·폴링 신호만 든다.
  const [refreshKey, setRefreshKey] = useState(0)
  const [anyGenerating, setAnyGenerating] = useState(false)
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
  const [newColl, setNewColl] = useState<string | undefined>() // 스펙 193 — rag 문제집 대상 컬렉션(생성 시 고정)
  const [collections, setCollections] = useState<Collection[]>([])
  const [chatModels, setChatModels] = useState<Model[]>([])
  const [helper, setHelper] = useState<{ available: boolean; reason: string | null }>({ available: false, reason: '확인 중…' })

  const bumpDatasets = useCallback(() => setRefreshKey((k) => k + 1), [])
  // 케이스 변경·AI 출제 후: 목록 재조회 + 열린 드로어(detail) 단건 재조회(generating·case_count 반영, 스펙 196).
  const onDatasetChanged = useCallback(() => {
    setRefreshKey((k) => k + 1)
    if (detail) getEvalDataset(detail.id).then((d) => setDetail((c) => (c && c.id === d.id ? d : c))).catch(() => {})
  }, [detail])
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
    loadRuns()  // 목록(datasets)은 PagedListShell이 자체 로드(스펙 196)
    listAgents().then(setAgents).catch(() => {})
    listCollections().then(setCollections).catch(() => {})
    listModels('chat').then(setChatModels).catch(() => {})
    getEvalHelperStatus().then(setHelper).catch(() => setHelper({ available: false, reason: '도우미 상태 확인 실패' }))
  }, [loadRuns])

  // 스펙 197: 컬렉션 '평가하기'로 진입 → 이 컬렉션이 프리필된 '새 문제집' 모달을 연다(1회 소비, 재열림 방지).
  useEffect(() => {
    if (!initialCollectionId) return
    setTab('datasets')
    setNewKind('rag')
    setNewColl(initialCollectionId)
    setCreating(true)
    onConsumedInitial?.()

  }, [initialCollectionId]) // eslint-disable-line react-hooks/exhaustive-deps

  // 실행 중인 런이 있으면 5초 폴링(성적 반영) — 없으면 중지.
  useEffect(() => {
    if (!runs.some((r) => r.status === 'running')) return
    const t = setInterval(loadRuns, 5000)
    return () => clearInterval(t)
  }, [runs, loadRuns])

  // 스펙 193/196: 현재 페이지에 생성 중 문제집이 있으면(any_generating) 2.5초마다 목록 재조회 — 끝나면 중지.
  useEffect(() => {
    if (!anyGenerating) return
    const t = setInterval(() => setRefreshKey((k) => k + 1), 2500)
    return () => clearInterval(t)
  }, [anyGenerating])

  // 스펙 196: 열린 드로어(detail)가 생성 중이면 단건 폴링으로 최신화 — generating 종료·collection_id 반영.
  // (목록이 셸 소유라 datasets에서 find 못 함 → getEvalDataset으로 자기 재조회.)
  useEffect(() => {
    if (!detail?.generating) return
    const t = setInterval(() => {
      getEvalDataset(detail.id)
        .then((d) => setDetail((cur) => (cur && cur.id === d.id ? d : cur)))
        .catch(() => {})
    }, 2500)
    return () => clearInterval(t)
  }, [detail?.generating, detail?.id])

  const dsCols: Column<EvalDataset>[] = [
    {
      key: 'name', title: '문제집',
      render: (d) => (
        <div>
          <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            {d.name}
            {/* 스펙 193: 자동 생성 중 배지(스피너) — 폴링으로 완료 시 사라짐. */}
            {d.generating ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--geekblue-6)', fontWeight: 500 }}>
                <Icon name="loading" spin size={11} /> 문제 생성 중…
              </span>
            ) : null}
          </div>
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
            <Popconfirm title="문제집과 모든 문제·성적을 삭제할까요?" okText="삭제" cancelText="취소" onConfirm={() => void deleteEvalDataset(d.id).then(bumpDatasets)}>
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
                {/* 스펙 196: 목록을 PagedListShell로 — 최근순 정렬·서버 검색·페이징(세션 098/128 패턴).
                   '새 문제집'은 leftSlot으로(스펙 195: '컬렉션에서 생성' 자동 채움은 제거됨 — 빈 문제집+상단 AI 출제). */}
                <PagedListShell<EvalDataset, boolean>
                  scopeKey="eval-datasets"
                  refreshKey={refreshKey}
                  fetchPage={async (q, limit, offset) => {
                    const data = await listEvalDatasets({ q, limit, offset })
                    return { items: data.items, total: data.total, extra: data.any_generating }
                  }}
                  onExtra={(g) => setAnyGenerating(!!g)}
                  columns={dsCols}
                  onRowClick={setDetail}
                  searchPlaceholder="문제집 이름·설명 검색"
                  emptyText="문제집이 없습니다 — 첫 문제집을 만들어 보세요."
                  errorTitle="문제집을 불러오지 못했습니다"
                  leftSlot={
                    <Button type="primary" icon={<Icon name="plus" />} onClick={() => setCreating(true)}>
                      새 문제집
                    </Button>
                  }
                />
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
                    /* 스펙 196: 전체 datasets(이제 페이징됨) 대신 runs에서 고유 문제집 유도 — 실행 이력 탭이라 자연. */
                    options={Array.from(new Map(runs.map((r) => [r.dataset_id, r.dataset_name])).entries()).map(([id, name]) => ({ value: id, label: name ?? id }))}
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
        okButtonProps={{ disabled: !newName.trim() || (newKind === 'rag' && !newColl) }}
        onCancel={() => setCreating(false)}
        onOk={() =>
          void createEvalDataset({
            name: newName.trim(), description: newDesc.trim() || null, kind: newKind,
            collection_id: newKind === 'rag' ? newColl : null, // 스펙 193: rag만 컬렉션 고정
          })
            .then(() => {
              setCreating(false)
              setNewName('')
              setNewDesc('')
              setNewKind('agent')
              setNewColl(undefined)
              bumpDatasets()
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
          {/* 스펙 193: rag 문제집은 만들 때 대상 컬렉션을 고정 → 실행 시 재선택 불필요. */}
          {newKind === 'rag' ? (
            <Select
              placeholder="채점 대상 RAG 컬렉션 선택 (문제집에 고정됩니다)"
              value={newColl}
              onChange={setNewColl}
              options={collections.map((c) => ({ value: c.id, label: c.name }))}
            />
          ) : null}
          <Input placeholder="이름 (예: 옵시디언 매니저 회귀 시험)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Input placeholder="설명 (선택)" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
        </div>
      </Modal>

      <DatasetDrawer
        dataset={detail}
        agents={agents}
        collections={collections}
        chatModels={chatModels}
        helper={helper}
        onClose={() => setDetail(null)}
        onChanged={onDatasetChanged}
        onRunStarted={() => { loadRuns(); setTab('runs') }}
        onOpenRun={(rid) => { setDetail(null); setRunDetail(rid) }}
      />
      <CompareDrawer aId={compare[0] ?? null} bId={compare[1] ?? null} onClose={() => setCompare([])} />
      <RunDrawer runId={runDetail} onClose={() => setRunDetail(null)} />
    </Page>
  )
}
