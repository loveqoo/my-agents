import { useState, useEffect } from 'react'
import { Select, Input, Switch, Slider, Tooltip, Collapse, Alert, Modal, Segmented, Button, Tag, Steps } from 'antd'
import { isOrchestratorImpl, type BlockCategory, type ToolPolicy, type Agent } from '../../mockData'
import { DelegationGraph } from '../../DelegationGraph'
import { listAgentImpls, type Model, type Collection, type ImplMeta } from '../../../api'
import { PickerGroups, type PickerGroup } from '../../../PickerGroups'
import { validateName, NAME_HINT } from '../../naming'
import { Field, SectionHeader } from './primitives'
import { ArtifactSpecEditor, artifactSpecValid } from './ArtifactSpecEditor'
import { NodeListEditor, pipelineValid } from './NodeListEditor'
import type { AgentFormData } from './types'

/* 빈 폼 기본값 — persona는 로드된 blocks에서, model은 등록된 첫 chat 모델에서
   계산한다(둘 다 없으면 빈 값). 가상 모델명 하드코딩 금지(스펙 023). */
export function blankForm(blocks: Record<string, BlockCategory>, models: Model[]): AgentFormData {
  return {
    name: '',
    description: '',
    model: models.find((m) => m.kind === 'chat')?.name ?? '',
    persona: blocks.persona?.items?.[0]?.name ?? '',
    temperature: null,
    memories: [],
    historyDepth: 20,
    persistHistory: true,
    ephemeral: false,
    suggestedPrompts: [],
    vectorTables: [],
    mcps: [],
    impl: '',
    capabilities: [],
    toolPolicy: {},
    ragMinScores: {}, // 컬렉션별 문서 검색 최소 유사도(스펙 191 v2) — 기본 무필터
  }
}

/* 에이전트 종류(사용자 언어, 스펙 108) — 내부 impl 키를 유저가 이해하는 두 선택지로 감싼다.
   ''=직접 응답(DefaultUiAgent, 자기 도구로 답함), 'orchestrate'=조율형(다른 곳에 넘김).
   impl·브로커·위임·오케스트레이터 같은 내부어는 UI에 절대 노출하지 않는다. */
export const AGENT_TYPES: { value: string; label: string; desc: string }[] = [
  { value: '', label: '직접 응답', desc: '스스로 도구·문서·기억을 써서 답합니다.' },
  { value: 'orchestrate', label: '조율형', desc: '일을 다른 에이전트·도구에 넘겨 처리합니다.' },
  // 노코드 산출물형(스펙 190) — 코드 없이 "모을 항목"만 정의(impl=artifact_form).
  { value: 'artifact_form', label: '산출물형', desc: '대화·폼으로 정보를 모아 결과물(JSON)을 만듭니다.' },
  // 노드형 일렬 파이프라인(스펙 259) — 노드마다 프롬프트·모델·도구를 직접 정해 순서대로 이음(impl=pipeline).
  { value: 'pipeline', label: '노드형', desc: '노드를 순서대로 이어, 노드마다 프롬프트·모델·도구를 직접 정합니다.' },
]
export const typeDesc = (key: string) => AGENT_TYPES.find((t) => t.value === key)?.desc ?? ''

/* ---- Create / edit form (composes blocks into a version config) ---- */
export function AgentForm({
  open,
  initial,
  mode,
  draftVersion,
  blocks,
  models,
  collections,
  agents,
  onCancel,
  onSave,
}: {
  open: boolean
  initial: AgentFormData | null
  mode: 'create' | 'edit'
  draftVersion: string | null
  blocks: Record<string, BlockCategory>
  models: Model[]
  collections: Collection[]
  agents: Agent[]
  onCancel: () => void
  onSave: (data: AgentFormData) => void
}) {
  const [form, setForm] = useState<AgentFormData>(() => initial ? { ...initial } : blankForm(blocks, models))

  useEffect(() => {
    setForm(initial ? { ...initial } : blankForm(blocks, models))
    setSpDraft('') // 추천 명령어 입력 드래프트도 초기화(모달 재오픈 시 잔존 방지)
    /* eslint-disable-next-line */
  }, [open])

  // /blocks가 폼을 연 뒤 늦게 도착하면 생성 모드의 빈 persona를 첫 항목으로 채운다
  // (페르소나 없는 에이전트 생성 방지).
  useEffect(() => {
    const first = blocks.persona?.items?.[0]?.name
    if (open && mode === 'create' && first) {
      setForm((f) => (f.persona ? f : { ...f, persona: first }))
    }
  }, [open, mode, blocks])

  // 등록 모델(/models)이 폼을 연 뒤 늦게 도착하면 생성 모드의 빈 model을 첫 등록
  // chat 모델로 채운다(가상 모델명 폴백 방지 — persona와 동일 패턴).
  useEffect(() => {
    const first = models.find((m) => m.kind === 'chat')?.name
    if (open && mode === 'create' && first) {
      setForm((f) => (f.model ? f : { ...f, model: first }))
    }
  }, [open, mode, models])

  const set = <K extends keyof AgentFormData>(k: K, v: AgentFormData[K]) =>
    setForm((f) => ({ ...f, [k]: v }))
  // 추천 명령어 입력 드래프트(스펙 238 후속2) — 입력창+추가 버튼 편집기(태그형 Select는 모바일 불가).
  const [spDraft, setSpDraft] = useState('')
  const addSuggestedPrompt = () => {
    const v = spDraft.trim().slice(0, 200)
    if (!v || form.suggestedPrompts.length >= 8) return
    set('suggestedPrompts', [...form.suggestedPrompts, v])
    setSpDraft('')
  }

  // 저장 방식 전환(스펙 238) — 비영속으로 바꾸면 DB 쓰기 능력(memwrite/memedit)을 자동 해제한다.
  // disabled 상태로 남겨두면 "해제하라"는 요구와 "해제할 수 없다"는 상태가 모순되기 때문(경고 지양).
  const setEphemeral = (v: boolean) =>
    setForm((f) => ({
      ...f,
      ephemeral: v,
      capabilities: v
        ? f.capabilities.filter((c) => !c.startsWith('memwrite:') && !c.startsWith('memedit:'))
        : f.capabilities,
    }))
  const toggleCap = (id: string) =>
    setForm((f) => ({
      ...f,
      capabilities: f.capabilities.includes(id)
        ? f.capabilities.filter((x) => x !== id)
        : [...f.capabilities, id],
    }))
  const toggle = (k: 'memories' | 'vectorTables' | 'mcps', v: string) =>
    setForm((f) => ({
      ...f,
      [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v],
    }))
  const isEdit = mode === 'edit'

  // 실행 방식 소비 표면(스펙 206) — impl이 "나는 이 설정을 읽는다"를 선언(consumes). 미선언(null)
  // =전부 노출(무회귀). 로드 실패도 전부 노출(best-effort — 게이트는 정직화 부가층).
  const [implMetas, setImplMetas] = useState<Record<string, string[] | null>>({})
  useEffect(() => {
    listAgentImpls()
      .then((ms: ImplMeta[]) => setImplMetas(Object.fromEntries(ms.map((m) => [m.key, m.consumes]))))
      .catch(() => {})
  }, [])
  // ''(직접 응답)=기본 ReAct(전부 소비). 커스텀 impl은 선언 있으면 그대로, 없으면 null(전부).
  const consumes = form.impl ? (implMetas[form.impl] ?? null) : null
  const surfaceOf: Record<string, string> = { 도구: 'mcps', 문서: 'vectorTables', 기억: 'memories' }
  const surfaceVisible = (groupKey: string) =>
    consumes == null || consumes.includes(surfaceOf[groupKey] ?? '')
  // 숨긴 표면에 저장된 연결이 있으면 경고(데이터는 보존 — impl 되돌리면 부활).
  const ignoredCounts: [string, number][] = consumes == null ? [] : ([
    ['도구', consumes.includes('mcps') ? 0 : form.mcps.length],
    ['문서', consumes.includes('vectorTables') ? 0 : form.vectorTables.length],
    ['기억', consumes.includes('memories') ? 0 : form.memories.length],
  ] as [string, number][]).filter(([, n]) => n > 0)

  // 등록된 chat 모델로 옵션 구성. 목록이 비었거나 현재 model이 목록에 없으면
  // 현재 값을 옵션에 보존해 편집 시 선택이 사라지지 않게 한다.
  const modelOptions = models.map((m) => ({ label: m.name, value: m.name }))
  if (form.model && !modelOptions.some((o) => o.value === form.model)) {
    modelOptions.push({ label: form.model, value: form.model })
  }

  // 종류 선택지 2개(직접 응답/조율형). 구 저장분이 exotic impl이면 값 보존해 편집 시 안 사라지게.
  const typeOptions = AGENT_TYPES.map((t) => ({ label: t.label, value: t.value }))
  if (form.impl && !typeOptions.some((o) => o.value === form.impl)) {
    typeOptions.push({ label: isOrchestratorImpl(form.impl) ? '조율형' : form.impl, value: form.impl })
  }

  // 조율형 "무엇에 맡길까요?" 그룹 — 폼 데이터에서 조립(스펙 106). 표시엔 사람이 읽는 이름만,
  // 내부 id(cap = `<kind>:<...>`)는 값으로만(스펙 108). 강제는 백엔드 브로커(104/105).
  const capGroups: PickerGroup[] = [
    {
      key: '다른 에이전트',
      title: '다른 에이전트',
      // 위임 대상(스펙 256): 원격(code/external=A2A) + 로컬 ui(활성 버전 보유, 자기 자신 제외 —
      // 인프로세스 직접 호출).
      items: agents
        .filter((a) => (a.source === 'code' || a.source === 'external')
          || (((a.source ?? 'ui') === 'ui') && !!a.activeVersion && a.name !== initial?.name))
        .map((a) => ({ id: a.agentId, label: (a.source === 'code' || a.source === 'external') ? `${a.name} · A2A` : `${a.name} · 로컬` })),
    },
    {
      key: '도구',
      title: '도구',
      items: (blocks.mcp?.items ?? []).map((m) => ({ id: `mcp:${m.name}`, label: m.name })),
    },
    {
      key: '문서',
      title: '문서',
      items: collections.map((c) => ({ id: `rag:${c.name}`, label: c.name })),
    },
    {
      key: '사용자 기억',
      title: '사용자 기억',
      // 비영속(스펙 237→238)은 DB 쓰기 능력 금지 — 숨김·경고 대신 **disabled**(사용자 지적: 놀래키지
      // 말 것). 비영속 전환 시 setEphemeral이 기선택을 자동 해제하므로 disabled+checked 모순 없음.
      items: [
        { id: 'memory:user', label: '사용자 기억 읽기' },
        {
          id: 'memwrite:user',
          label: '사용자 기억에 저장 · 승인 필요',
          // 미선택-잠금(codex 238 #2 동형 방지): 전환 시 자동 해제되지만, 혹시 남은 기선택은 해제 가능.
          disabled: form.ephemeral && !form.capabilities.includes('memwrite:user'),
          disabledHint: '비영속(1회성)에서는 쓸 수 없습니다 — 기록을 남기는 능력입니다.',
        },
      ],
    },
  ]

  // 직접 응답 "하는 일" 그룹 — 3개 form 배열(memories/vectorTables/mcps)을 PickerGroups
  // 하나로 묶으려 id를 카테고리 prefix로 네임스페이스(스펙 109). 저장은 기존 배열 그대로, prefix는
  // UI 라우팅용. 리치 렌더 보존: 메모리/컬렉션→hint(설명).
  const DIRECT_FIELD: Record<string, 'memories' | 'vectorTables' | 'mcps'> = {
    mem: 'memories',
    col: 'vectorTables',
    tool: 'mcps',
  }
  const directSelected = [
    ...form.memories.map((x) => `mem:${x}`),
    ...form.vectorTables.map((x) => `col:${x}`),
    ...form.mcps.map((x) => `tool:${x}`),
  ]
  const toggleDirect = (id: string) => {
    const i = id.indexOf(':')
    const field = DIRECT_FIELD[id.slice(0, i)]
    if (field) toggle(field, id.slice(i + 1))
  }
  const doGroups: PickerGroup[] = [
    {
      key: '도구',
      title: '도구',
      items: (blocks.mcp?.items ?? []).map((m) => ({ id: `tool:${m.name}`, label: m.name })),
      emptyText: 'MCP 서버 없음 — 빌딩 블록에서 등록하세요.',
    },
    {
      key: '문서',
      title: '문서',
      items: collections.map((c) => ({
        id: `col:${c.name}`,
        label: c.name,
        hint: `${c.embedding_model_name} · 청크 ${c.chunk_count}개`,
      })),
      emptyText: '컬렉션 없음 — RAG 컬렉션 메뉴에서 문서를 적재하세요.',
    },
    {
      key: '기억',
      title: '기억',
      // 비영속은 회상하지 않는다(스펙 235) — 새 선택은 disabled(codex 238 #1), 기선택은 해제만 가능
      // ("선택했는데 무동작" 함정과 "해제 불가" 모순을 동시에 피하는 미선택-잠금 패턴).
      items: (blocks.memory?.items ?? []).map((m) => ({
        id: `mem:${m.name}`,
        label: m.name,
        hint: form.ephemeral && form.memories.includes(m.name) ? '비영속에서는 회상되지 않습니다 — 해제 가능' : m.body,
        disabled: form.ephemeral && !form.memories.includes(m.name),
        disabledHint: '비영속(1회성) 에이전트는 기억을 쓰지 않습니다.',
      })),
    },
  ]
  const orchestratorSelected = isOrchestratorImpl(form.impl)
  const isArtifactForm = form.impl === 'artifact_form'
  const isPipeline = form.impl === 'pipeline'
  // 산출물형이면 유효 필드 ≥1을 저장 조건으로 강제(스펙 190) — 빈 명세 저장 방지.
  const artifactInvalid = isArtifactForm && !artifactSpecValid(form.artifactSpec)
  // 노드형이면 노드 ≥1·각 노드 프롬프트+모델 채움을 저장 조건으로 강제(스펙 259) — 빈 파이프라인 방지.
  const pipelineInvalid = isPipeline && !pipelineValid(form.nodes)

  // 노드형 편집기 데이터(스펙 259). 모델=등록 chat 모델, 페르소나=blocks 본문(불러오기용),
  // 도구=개별 MCP 도구 + 문서 검색(search_documents 단일 도구, 컬렉션 전체 대상).
  const chatModelOptions = models.filter((m) => m.kind === 'chat').map((m) => ({ label: m.name, value: m.name }))
  const nodePersonas = (blocks.persona?.items ?? []).map((p) => ({ name: p.name, body: p.body ?? '' }))
  // MCP 도구의 **런타임 이름**(스펙 265) — 백엔드 _safe_name(`서버__도구`, 비허용문자 _ 치환, 60자 캡)
  // 미러(변경 시 함께). 민이름("wiki_search")으로 저장하면 런타임 by_name 매칭이 0이 돼 도구가 조용히
  // 미바인딩(모델이 호출한 척 환각, 스펙 264 실측) + 서버 간 동명 도구의 Select value 충돌도 해소.
  const safeToolName = (server: string, tool: string) =>
    `${server}__${tool}`.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 60) || 'tool'
  const nodeToolOptions = [
    ...(blocks.mcp?.items ?? []).flatMap((s) =>
      (s.tools ?? []).map((t) => ({ label: `${s.name} · ${t}`, value: safeToolName(s.name, t) }))
    ),
    ...(collections.length ? [{ label: '문서 검색 (컬렉션 전체)', value: 'search_documents' }] : []),
  ]
  // 저장 직전 파생(스펙 259) — 노드형은 에이전트-레벨 도구 풀(mcps/vectorTables)을 노드 도구 합집합에서
  // 파생한다(에이전트-레벨 도구 UI를 숨기므로). 백엔드 ctx.tools는 이 풀로 빌드되고, 노드는 자기 tools로
  // 다시 필터한다(권한 상승 0). 문서 검색은 단일 도구라 컬렉션 스코핑 불가 → 쓰면 전체 컬렉션이 풀에.
  // 매칭은 런타임 이름 기준(스펙 265) — 민이름 구저장분은 엔진 접미 폴백이 자가치유.
  const finalizeForm = (): AgentFormData => {
    const base = { ...form, name: form.name.trim(), description: form.description.trim() }
    if (!isPipeline) return base
    const used = new Set((form.nodes ?? []).flatMap((n) => n.tools))
    const mcps = (blocks.mcp?.items ?? [])
      .filter((s) => (s.tools ?? []).some((t) => used.has(safeToolName(s.name, t)) || used.has(t)))
      .map((s) => s.name)
    const vectorTables = used.has('search_documents') ? collections.map((c) => c.name) : []
    return { ...base, mcps, vectorTables }
  }
  // 식별 이름 규칙(스펙 148) — 서버 400의 프론트 힌트. 빈 값은 입력 전이라 조용히(제출만 막음).
  const nameErr = form.name.trim() ? validateName(form.name.trim()) : null

  /* ── 위저드(스펙 239) — 4단계: 정체성 → 하는 일 → 세부 → 요약·확인.
     생성: 순차 진행(방문한 단계는 클릭 재이동), 요약까지 가야 생성 버튼.
     수정: 전 단계 자유 이동, 저장은 요약에서만(생성과 동일 규칙 — 사용자 합의). ── */
  const [step, setStep] = useState(0)
  const [maxVisited, setMaxVisited] = useState(0)
  useEffect(() => {
    if (open) {
      setStep(0)
      setMaxVisited(isEdit ? 3 : 0)
    }
  }, [open, isEdit])
  const stepOk = (s: number): boolean => {
    if (s === 0) return !!form.name.trim() && !nameErr
    if (s === 1) return !artifactInvalid && !pipelineInvalid
    return true
  }
  const goNext = () => {
    if (!stepOk(step)) return
    const n = Math.min(step + 1, 3)
    setStep(n)
    setMaxVisited((m) => Math.max(m, n))
  }
  const goTo = (n: number) => {
    if (n <= maxVisited) setStep(n)
  }
  const saveDisabled = !form.name.trim() || !!nameErr || artifactInvalid || pipelineInvalid
  const typeLabel = AGENT_TYPES.find((t) => t.value === form.impl)?.label ?? (form.impl || '직접 응답')

  return (
    <Modal
      open={open}
      width={760}
      title={isEdit ? `초안 편집 · ${draftVersion}` : '에이전트 생성'}
      onCancel={onCancel}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <Button onClick={onCancel}>취소</Button>
          <div style={{ display: 'flex', gap: 8 }}>
            {step > 0 && <Button onClick={() => setStep(step - 1)}>이전</Button>}
            {step < 3 && (
              <Button type="primary" disabled={!stepOk(step)} onClick={goNext}>
                다음
              </Button>
            )}
            {step === 3 && (
              <Button
                type="primary"
                disabled={saveDisabled}
                onClick={() => onSave(finalizeForm())}
              >
                {isEdit ? '초안 저장' : '에이전트 생성'}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '62vh', overflow: 'auto' }}>
        <Steps
          size="small"
          current={step}
          onChange={goTo}
          style={{ marginBottom: 4 }}
          items={[
            { title: '정체성', disabled: 0 > maxVisited },
            { title: '하는 일', disabled: 1 > maxVisited },
            { title: '세부', disabled: 2 > maxVisited },
            { title: '요약·확인', disabled: 3 > maxVisited },
          ]}
        />
        {step === 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 0 }}
            title={
              isEdit
                ? `변경사항은 초안 ${draftVersion}에 저장됩니다 — 활성화하기 전까지 현재 버전이 계속 서빙합니다.`
                : '에이전트의 v1 초안을 만듭니다. 테스트 후 활성화해 게시하세요.'
            }
          />
        )}
        {/* ── 단계 ① 정체성(스펙 239) — 이름·설명·종류·모델·페르소나·저장 방식 ── */}
        {step === 0 && (
          <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: 16 }}>
          <Field label="식별 이름">
            <Input
              placeholder="예: research-assistant"
              value={form.name}
              status={nameErr ? 'error' : undefined}
              onChange={(e) => set('name', e.target.value)}
            />
            <span style={{ fontSize: 12, color: nameErr ? 'var(--red-6)' : 'var(--color-text-tertiary)' }}>
              {nameErr ?? NAME_HINT}
            </span>
          </Field>
          <Field label="설명 (선택 — 부가 정보)">
            <Input placeholder="예: 리서치 어시스턴트" value={form.description} onChange={(e) => set('description', e.target.value)} />
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>화면에는 이름만 표시되며, 이 설명은 마우스 오버 시에만 노출됩니다</span>
          </Field>
        </div>
        {/* 노드형(스펙 259)은 모델·페르소나를 노드마다 직접 정하므로 에이전트-레벨 모델/페르소나를 숨긴다
            (결정 #1·#2). 안내는 종류 필드 아래 설명에 합류(스펙 263 — 떠 있는 중복 문구 제거). */}
        {isPipeline ? null : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: 16 }}>
          <Field label="모델">
            <Select
              value={form.model}
              onChange={(v) => set('model', v)}
              style={{ width: '100%' }}
              options={modelOptions}
            />
            {/* mock+도구 안내(스펙 236→238): 큰 경고 Alert에서 보조 문구로 강등 — 놀래키지 않되 정보는 유지. */}
            {models.find((m) => m.name === form.model)?.provider_kind === 'mock' && form.mcps.length > 0 && (
              <span style={{ fontSize: 12, color: 'var(--color-warning)' }}>
                mock 모델은 정해진 키워드·도구 이름에만 도구를 호출합니다 — 도구를 제대로 쓰려면 실제 모델을 선택하세요.
              </span>
            )}
          </Field>
          <Field label="페르소나">
            <Select
              value={form.persona}
              onChange={(v) => set('persona', v)}
              style={{ width: '100%' }}
              options={(blocks.persona?.items ?? []).map((p) => ({ label: p.name, value: p.name }))}
            />
          </Field>
        </div>
        )}
        {/* 종류 선택 rich화(스펙 238 #3) — 드롭다운 옵션마다 설명을 내장(단순 라벨 선택박스 지양). */}
        <Field label="에이전트 종류">
          <Select
            value={form.impl}
            onChange={(v) => set('impl', v)}
            options={typeOptions}
            style={{ width: '100%' }}
            optionRender={(o) => (
              <span style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '2px 0' }}>
                <span style={{ fontWeight: 600 }}>{o.label}</span>
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', whiteSpace: 'normal' }}>
                  {typeDesc(String(o.value ?? ''))}
                </span>
              </span>
            )}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {typeDesc(form.impl)}
            {/* 노드형(스펙 263): 원인 필드(종류) 아래에 다음 행동 안내 — 위에 떠 있던 중복 문구 대체. */}
            {isPipeline ? ' 노드는 다음 "하는 일" 단계에서 추가합니다.' : ''}
          </span>
        </Field>
        {/* 저장 방식(스펙 238 #1) — 영속/비영속은 부가정보가 아니라 1급 정보(사용자 지적). 기본=영속.
            비영속 전환은 금지 능력(memwrite/memedit)을 자동 해제한다(setEphemeral — disabled+checked 모순 방지). */}
        <Field label="저장 방식">
          <Segmented
            value={form.ephemeral ? 'ephemeral' : 'persistent'}
            onChange={(v) => setEphemeral(v === 'ephemeral')}
            options={[
              { label: '영속 (기본)', value: 'persistent' },
              { label: '비영속 — 1회성', value: 'ephemeral' },
            ]}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {form.ephemeral
              ? '아무것도 저장하지 않는 1회성 추론입니다 — 세션·대화 이력·기억 없이 응답만 합니다.'
              : '대화와 기록을 저장합니다 — 세션·이력·기억을 사용할 수 있습니다.'}
          </span>
        </Field>

          </>
        )}

        {/* ── 단계 ② 하는 일(스펙 109/239) — 종류가 그룹 세트를 가른다(108). 늘어나는 항목은
            PickerGroups(접이식+검색+카운트)로 효율 렌더 → 항목 100개여도 폼 높이 안정.
            산출물형(스펙 190)은 도구/문서 대신 "모을 항목" 편집기를 띄운다. ── */}
        {step === 1 && (
          <>
        <SectionHeader first>{isArtifactForm ? '모을 항목' : isPipeline ? '처리 단계 (노드)' : '이 에이전트가 할 수 있는 일'}</SectionHeader>
        {isArtifactForm ? (
          <ArtifactSpecEditor value={form.artifactSpec} onChange={(s) => set('artifactSpec', s)} />
        ) : isPipeline ? (
          <NodeListEditor
            value={form.nodes}
            onChange={(nodes) => set('nodes', nodes)}
            modelOptions={chatModelOptions}
            personas={nodePersonas}
            toolOptions={nodeToolOptions}
          />
        ) : orchestratorSelected ? (
          <>
            <PickerGroups groups={capGroups} selected={form.capabilities} onToggle={toggleCap} />
            {/* 위임 구조 미리보기(스펙 257 후속) — 저장을 막지 않고 보이게: 순환은 빨간 마커
                ("실행 시 자동 차단"). 하드 차단은 존재 비노출 원칙과 충돌(타인 private 에이전트
                때문에 저장 거부 = 존재 누출)·런타임 체인이 이미 안전을 보장하므로 채택 안 함. */}
            {form.capabilities.some((c) => !c.includes(':')) ? (
              <div style={{ marginTop: 12, border: '1px solid var(--color-border-secondary)', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 6 }}>위임 구조 미리보기</div>
                <DelegationGraph
                  rootAgentId={agents.find((a) => a.name === initial?.name)?.agentId ?? '__new__'}
                  agents={agents}
                  rootCapsOverride={form.capabilities}
                  rootLabel={form.name || '(이 에이전트)'}
                />
              </div>
            ) : null}
          </>
        ) : (
          <>
            {/* 소비 표면 게이트(스펙 206) — 이 impl이 안 읽는 그룹은 숨기고, 저장된 연결이 있으면 경고. */}
            {ignoredCounts.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 10 }}
                title={`이 실행 방식은 ${ignoredCounts.map(([k]) => k).join('·')} 설정을 읽지 않습니다 — 저장된 연결 ${ignoredCounts.reduce((s, [, n]) => s + n, 0)}개는 무시됩니다(연결은 보존되며, 실행 방식을 되돌리면 다시 적용됩니다).`}
              />
            ) : null}
            <PickerGroups groups={doGroups.filter((g) => surfaceVisible(g.key))} selected={directSelected} onToggle={toggleDirect} />
            {/* 하이브리드 도구 접근 안내(스펙 203, 사용자 요청) — 임계값 10은 백엔드
                agent/toolbox.py DISCOVER_THRESHOLD 미러(변경 시 함께). */}
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', display: 'block', marginTop: 6 }}>
              도구를 많이 연결하면(총 10개 초과) 컨텍스트(프롬프트) 보호를 위해 도구를 검색해 쓰는
              방식으로 자동 전환됩니다 — 기능은 동일합니다.
            </span>
          </>
        )}

        {/* 컬렉션별 문서 검색 최소 유사도(스펙 191 v2) — 배선된 RAG 컬렉션마다 슬라이더 하나.
            직접=vectorTables, 조율형=capabilities의 rag:*. 산출물형은 문서 검색 없음. */}
        {(() => {
          if (isArtifactForm) return null
          const cols = orchestratorSelected
            ? form.capabilities.filter((c) => c.startsWith('rag:')).map((c) => c.slice(4))
            : form.vectorTables
          if (!cols.length) return null
          const scores = form.ragMinScores || {}
          const setScore = (col: string, val: number) =>
            set('ragMinScores', { ...scores, [col]: val })
          return (
            <div style={{ marginTop: 4 }}>
              <SectionHeader>문서 검색 — 최소 유사도 (컬렉션별)</SectionHeader>
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', display: 'block', marginBottom: 10 }}>
                각 컬렉션에서 이 값 미만으로 유사한 문서는 검색에서 무시합니다(0 = 무필터). 유사도는 0~1이며 1이 완전 일치입니다.
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {cols.map((col) => {
                  const v = scores[col] ?? 0
                  return (
                    <div key={col} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                      <span style={{ minWidth: 130, fontSize: 13, fontFamily: 'var(--font-family-code)', overflowWrap: 'anywhere' }}>{col}</span>
                      <Slider
                        style={{ flex: 1 }}
                        min={0}
                        max={1}
                        step={0.05}
                        value={v}
                        onChange={(val) => setScore(col, typeof val === 'number' ? val : 0)}
                        marks={{ 0: '0', 0.5: '0.5', 1: '1' }}
                      />
                      <span style={{ fontFamily: 'var(--font-family-code)', minWidth: 44, textAlign: 'right', fontSize: 13 }}>
                        {v === 0 ? '무필터' : v.toFixed(2)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* 도구 승인 오버라이드(스펙 177 P2) — 배선된 MCP 도구별로 승인 정책을 이 에이전트에 한해 덮어씀.
            완화(본인 승인·승인 없음)는 백엔드 완화 게이트가 admin만 저장 허용(비-admin 저장 시 403). */}
        {(() => {
          const wired = new Set<string>(form.mcps)
          form.capabilities.forEach((c) => {
            if (c.startsWith('mcp:') && !c.includes('/')) wired.add(c.slice(4))
          })
          const rows: { server: string; tool: string }[] = []
          ;[...wired].forEach((srv) => {
            const item = blocks.mcp?.items?.find((m) => m.name === srv)
            ;(item?.tools ?? []).forEach((t) => rows.push({ server: srv, tool: t }))
          })
          if (!rows.length) return null
          const valOf = (capId: string): string => {
            const a = form.toolPolicy[capId]?.approval
            if (!a) return ''
            if (a.required === false) return 'off'
            if (a.approver === 'self') return 'self'
            if (a.required === true) return 'admin'
            return ''
          }
          const setVal = (capId: string, v: string) =>
            setForm((f) => {
              const tp: ToolPolicy = { ...f.toolPolicy }
              if (v === 'admin') tp[capId] = { approval: { required: true, approver: 'admin' } }
              else if (v === 'self') tp[capId] = { approval: { required: true, approver: 'self' } }
              else if (v === 'off') tp[capId] = { approval: { required: false } }
              else delete tp[capId]
              return { ...f, toolPolicy: tp }
            })
          return (
            <Collapse
              size="small"
              items={[
                {
                  key: 'toolpolicy',
                  label: `도구 승인 오버라이드 (${rows.length}개 · 선택)`,
                  children: (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                        도구 호출 전 승인을 이 에이전트에 한해 덮어씁니다. 완화(본인 승인·승인 없음)는 관리자만 저장됩니다.
                      </span>
                      {rows.map(({ server, tool }) => {
                        const capId = `mcp:${server}/${tool}`
                        return (
                          <div
                            key={capId}
                            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}
                          >
                            <span style={{ fontSize: 13 }}>
                              <code>{server}</code> · {tool}
                            </span>
                            <Select
                              size="small"
                              style={{ width: 190 }}
                              value={valOf(capId)}
                              onChange={(v) => setVal(capId, v)}
                              options={[
                                { value: '', label: '기본값 사용' },
                                { value: 'admin', label: '승인 필요 · 관리자' },
                                { value: 'self', label: '승인 필요 · 본인' },
                                { value: 'off', label: '승인 없음' },
                              ]}
                            />
                          </div>
                        )
                      })}
                    </div>
                  ),
                },
              ]}
            />
          )
        })()}

          </>
        )}

        {/* ── 단계 ③ 세부(전부 선택 — 기본값 그대로면 그냥 다음, 스펙 239) ── */}
        {step === 2 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    모두 선택 사항입니다 — 그대로 두면 기본값으로 동작합니다.
                  </span>
                  {/* 스펙 235: 경계 구분 — 모델 동작 / 저장·영속(폼 표준 SectionHeader로 일관). */}
                  <SectionHeader>모델 동작</SectionHeader>
                  {/* 온도(스펙 077) — 자동(끔)=모델 등록 기본값, 수동=0–2 저장. 플그 오버라이드와 대칭. */}
                  <Field label="Temperature">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <Tooltip title="끄면 모델 등록 기본값(자동)">
                        <Switch
                          size="small"
                          checked={form.temperature != null}
                          onChange={(on) => set('temperature', on ? 0.7 : null)}
                        />
                      </Tooltip>
                      <Slider
                        min={0}
                        max={2}
                        step={0.1}
                        disabled={form.temperature == null}
                        value={form.temperature ?? 0.7}
                        onChange={(v) => set('temperature', v)}
                        style={{ flex: 1 }}
                      />
                      <span style={{ width: 32, textAlign: 'right', fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
                        {form.temperature == null ? '—' : form.temperature.toFixed(1)}
                      </span>
                    </div>
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      {form.temperature == null ? '자동 — 모델 등록 기본값을 사용합니다.' : '에이전트에 저장됩니다(세션마다 동일).'}
                    </span>
                  </Field>
                  {/* 채팅 히스토리(스펙 238 재검토) — 저장 설정이 아니라 **모델 컨텍스트** 설정
                      (모델에 넣을 최근 N개). 런타임 _window는 비영속에도 적용되므로(클라이언트가 보낸
                      대화 기준) 비영속에서도 활성 — "적용 안 됨"으로 잠갔던 건 거짓이었다. */}
                  <Field label="채팅 히스토리">
                    <Select
                      value={form.historyDepth}
                      onChange={(v) => set('historyDepth', v)}
                      style={{ width: '100%' }}
                      options={[
                        { label: '기억 안 함 (0개)', value: 0 },
                        { label: '최근 6개 메시지', value: 6 },
                        { label: '최근 10개 메시지', value: 10 },
                        { label: '최근 20개 메시지', value: 20 },
                        { label: '최근 40개 메시지', value: 40 },
                        { label: '최근 100개 메시지', value: 100 },
                      ]}
                    />
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      모델에 넣을 최근 대화 개수입니다{form.ephemeral ? ' — 비영속에서도 요청에 담긴 대화에 적용됩니다' : ''}.
                    </span>
                  </Field>
                  <SectionHeader>저장·영속</SectionHeader>
                  {/* 영속/비영속 자체는 상단 "저장 방식"이 소유(스펙 238 — 1급 정보 승격). 여기는
                      영속일 때의 세부만. */}
                  <Field label="대화 저장">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      {/* 표시값=실효값(사용자 지적: 비영속인데 ON 고정은 모순). 저장된 persistHistory는
                          보존 — 영속으로 되돌리면 원래 값이 복원된다. */}
                      <Switch
                        checked={!form.ephemeral && form.persistHistory}
                        disabled={form.ephemeral}
                        onChange={(v) => set('persistHistory', v)}
                      />
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                        {form.ephemeral
                          ? '비영속(1회성)은 대화를 저장하지 않습니다'
                          : form.persistHistory
                            ? '대화를 DB에 저장 (세션·인스펙터·재개)'
                            : '대화를 저장하지 않음 (가볍고 기록이 남지 않음)'}
                      </span>
                    </div>
                  </Field>
                  <SectionHeader>플레이그라운드</SectionHeader>
                  {/* 추천 명령어(스펙 238 #5, 후속2) — 태그형 Select(Enter 의존)는 모바일서 입력 불가·
                      발견성 나빠 명시적 입력창+추가 버튼+목록으로 교체(사용자 지적). 서버 캡: 8개·200자. */}
                  <Field label="추천 명령어 (선택)">
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Input
                        value={spDraft}
                        onChange={(e) => setSpDraft(e.target.value)}
                        onPressEnter={addSuggestedPrompt}
                        maxLength={200}
                        placeholder="예: 최신 스트리밍 UI 동향을 검색해줘"
                      />
                      <Button
                        onClick={addSuggestedPrompt}
                        disabled={!spDraft.trim() || form.suggestedPrompts.length >= 8}
                      >
                        추가
                      </Button>
                    </div>
                    {form.suggestedPrompts.length > 0 && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                        {form.suggestedPrompts.map((p, i) => (
                          <Tag
                            key={`${i}-${p}`}
                            closable
                            onClose={(e) => {
                              e.preventDefault()
                              set('suggestedPrompts', form.suggestedPrompts.filter((_, j) => j !== i))
                            }}
                            style={{ whiteSpace: 'normal', height: 'auto', padding: '4px 8px', marginInlineEnd: 0, overflowWrap: 'anywhere' }}
                          >
                            {p}
                          </Tag>
                        ))}
                      </div>
                    )}
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      플레이그라운드 새 대화 화면에 카드로 노출됩니다 ({form.suggestedPrompts.length}/8 · 각 200자).
                    </span>
                  </Field>
                </div>
        )}

        {/* ── 단계 ④ 요약·확인(스펙 239) — 섹션별 요약 + "수정"으로 해당 단계 점프. 생성/저장은 여기만. ── */}
        {step === 3 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <SummaryCard title="정체성" onEdit={() => setStep(0)}>
              <SummaryRow k="이름" v={form.name.trim() || '(미입력)'} bad={!form.name.trim() || !!nameErr} />
              {form.description.trim() && <SummaryRow k="설명" v={form.description.trim()} />}
              <SummaryRow k="종류" v={`${typeLabel} — ${typeDesc(form.impl)}`} />
              {/* 노드형(스펙 263): 에이전트-레벨 모델/페르소나는 안 쓰이는데(페르소나=미사용, 모델=노드
                  폴백뿐) 요약에 1급처럼 뜨면 거짓 확인(사용자가 정하지 않은 숨은 기본값). 정직하게 대체. */}
              {isPipeline ? (
                <SummaryRow k="모델·프롬프트" v="노드마다 설정 — 아래 처리 단계 참고" />
              ) : (
                <>
                  <SummaryRow k="모델" v={form.model || '(없음)'} />
                  <SummaryRow k="페르소나" v={form.persona || '(없음)'} />
                </>
              )}
              <SummaryRow k="저장 방식" v={form.ephemeral ? '비영속 (1회성) — 대화·기록을 남기지 않음' : '영속 — 대화와 기록 저장'} />
            </SummaryCard>
            <SummaryCard title="하는 일" onEdit={() => setStep(1)}>
              {isArtifactForm ? (
                <SummaryRow
                  k="모을 항목"
                  v={
                    (form.artifactSpec?.fields ?? []).length
                      ? (form.artifactSpec!.fields as { key?: string; label?: string }[])
                          .map((f) => f.label || f.key || '?')
                          .join(', ')
                      : '(없음 — 최소 1개 필요)'
                  }
                  bad={artifactInvalid}
                />
              ) : isPipeline ? (
                <SummaryRow
                  k="처리 단계"
                  v={
                    (form.nodes ?? []).length
                      ? `${form.nodes!.length}단계 — ${form.nodes!
                          .map((n, i) => `${n.name?.trim() || `노드${i + 1}`}${n.model ? `(${n.model})` : ''}`)
                          .join(' → ')}`
                      : '(없음 — 최소 1개 필요)'
                  }
                  bad={pipelineInvalid}
                />
              ) : orchestratorSelected ? (
                <SummaryRow
                  k="위임 대상"
                  v={form.capabilities.length ? `${form.capabilities.length}개 — ${form.capabilities.slice(0, 6).join(', ')}${form.capabilities.length > 6 ? ' 외' : ''}` : '없음 — 위임 없이는 답만 합니다'}
                />
              ) : (
                <>
                  <SummaryRow k="도구" v={form.mcps.length ? form.mcps.join(', ') : '없음'} />
                  <SummaryRow k="문서" v={form.vectorTables.length ? form.vectorTables.join(', ') : '없음'} />
                  <SummaryRow k="기억" v={form.ephemeral ? '사용 안 함 (비영속)' : form.memories.length ? form.memories.join(', ') : '없음'} />
                </>
              )}
              {/* 현재 종류가 안 쓰는 표면에 남은 연결도 저장은 되므로 정직하게 표기(codex 239 #1 —
                  요약이 payload를 축소하면 거짓 확인. 데이터 보존 정책(206)은 유지, 표시만 추가). */}
              {(() => {
                const hidden: string[] = []
                if (isArtifactForm || orchestratorSelected) {
                  if (form.mcps.length) hidden.push(`도구 ${form.mcps.length}`)
                  if (form.vectorTables.length) hidden.push(`문서 ${form.vectorTables.length}`)
                  if (form.memories.length) hidden.push(`기억 ${form.memories.length}`)
                }
                if (!orchestratorSelected && form.capabilities.length) hidden.push(`위임 대상 ${form.capabilities.length}`)
                return hidden.length ? (
                  <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>
                    보존된 연결(현재 종류에선 사용 안 함): {hidden.join(' · ')} — 종류를 되돌리면 다시 적용됩니다.
                  </span>
                ) : null
              })()}
            </SummaryCard>
            <SummaryCard title="세부" onEdit={() => setStep(2)}>
              {(() => {
                const diffs: [string, string][] = []
                if (form.temperature != null) diffs.push(['Temperature', form.temperature.toFixed(1)])
                if (form.historyDepth !== 20) diffs.push(['채팅 히스토리', form.historyDepth === 0 ? '기억 안 함' : `최근 ${form.historyDepth}개`])
                if (!form.ephemeral && !form.persistHistory) diffs.push(['대화 저장', '저장 안 함(윈도우 모드)'])
                if (form.suggestedPrompts.length) diffs.push(['추천 명령어', `${form.suggestedPrompts.length}개`])
                const minScores = Object.entries(form.ragMinScores || {}).filter(([, v]) => v > 0)
                if (minScores.length) diffs.push(['문서 검색 최소 유사도', minScores.map(([k, v]) => `${k}=${v.toFixed(2)}`).join(', ')])
                const tpCount = Object.keys(form.toolPolicy || {}).length
                if (tpCount) diffs.push(['도구 승인 오버라이드', `${tpCount}개`])
                return diffs.length ? (
                  <>{diffs.map(([k, v]) => <SummaryRow key={k} k={k} v={v} />)}</>
                ) : (
                  <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>기본값 사용</span>
                )
              })()}
            </SummaryCard>
          </div>
        )}
      </div>
    </Modal>
  )
}

/* 요약 카드(스펙 239) — 섹션 제목 + "수정" 점프 버튼 + 행들. */
function SummaryCard({ title, onEdit, children }: { title: string; onEdit: () => void; children: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 8, padding: '10px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-tertiary)' }}>{title}</span>
        <Button size="small" type="link" onClick={onEdit} style={{ padding: 0, height: 'auto' }}>
          수정
        </Button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{children}</div>
    </div>
  )
}

function SummaryRow({ k, v, bad }: { k: string; v: string; bad?: boolean }) {
  return (
    <div style={{ display: 'flex', gap: 10, fontSize: 13 }}>
      <span style={{ minWidth: 110, color: 'var(--color-text-tertiary)', flexShrink: 0 }}>{k}</span>
      <span style={{ color: bad ? 'var(--red-6)' : 'var(--color-text)', overflowWrap: 'anywhere' }}>{v}</span>
    </div>
  )
}
