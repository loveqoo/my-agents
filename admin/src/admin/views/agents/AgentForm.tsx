import { useState, useEffect } from 'react'
import { Select, Input, Switch, Slider, Tooltip, Collapse, Alert, Modal } from 'antd'
import { isOrchestratorImpl, type BlockCategory, type ToolPolicy, type Agent } from '../../mockData'
import { type Model, type Collection } from '../../../api'
import { PickerGroups, type PickerGroup } from '../../../PickerGroups'
import { validateName, NAME_HINT } from '../../naming'
import { Field, SectionHeader } from './primitives'
import type { AgentFormData } from './types'

/* 빈 폼 기본값 — persona는 로드된 blocks에서, model은 등록된 첫 chat 모델에서
   계산한다(둘 다 없으면 빈 값). 가상 모델명 하드코딩 금지(스펙 023). */
export function blankForm(blocks: Record<string, BlockCategory>, models: Model[]): AgentFormData {
  return {
    name: '',
    alias: '',
    model: models.find((m) => m.kind === 'chat')?.name ?? '',
    persona: blocks.persona?.items?.[0]?.name ?? '',
    temperature: null,
    memories: [],
    historyDepth: 20,
    persistHistory: true,
    vectorTables: [],
    mcps: [],
    impl: '',
    capabilities: [],
    toolPolicy: {},
  }
}

/* 에이전트 종류(사용자 언어, 스펙 108) — 내부 impl 키를 유저가 이해하는 두 선택지로 감싼다.
   ''=직접 응답(DefaultUiAgent, 자기 도구로 답함), 'orchestrate'=조율형(다른 곳에 넘김).
   impl·브로커·위임·오케스트레이터 같은 내부어는 UI에 절대 노출하지 않는다. */
export const AGENT_TYPES: { value: string; label: string; desc: string }[] = [
  { value: '', label: '직접 응답', desc: '스스로 도구·문서·기억을 써서 답합니다.' },
  { value: 'orchestrate', label: '조율형', desc: '일을 다른 에이전트·도구에 넘겨 처리합니다.' },
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
      // 원격(code/external) 에이전트만 위임 대상(로컬 UI 에이전트는 대상 아님).
      items: agents
        .filter((a) => a.source === 'code' || a.source === 'external')
        .map((a) => ({ id: a.agentId, label: a.name })),
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
      items: [
        { id: 'memory:user', label: '사용자 기억 읽기' },
        { id: 'memwrite:user', label: '사용자 기억에 저장 · 승인 필요' },
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
      items: (blocks.memory?.items ?? []).map((m) => ({ id: `mem:${m.name}`, label: m.name, hint: m.body })),
    },
  ]
  const orchestratorSelected = isOrchestratorImpl(form.impl)
  // 식별 이름 규칙(스펙 148) — 서버 400의 프론트 힌트. 빈 값은 입력 전이라 조용히(제출만 막음).
  const nameErr = form.name.trim() ? validateName(form.name.trim()) : null

  return (
    <Modal
      open={open}
      width={560}
      title={isEdit ? `초안 편집 · ${draftVersion}` : '에이전트 생성'}
      okText={isEdit ? '초안 저장' : '에이전트 생성'}
      cancelText="취소"
      onCancel={onCancel}
      okButtonProps={{ disabled: !form.name.trim() || !!nameErr }}
      onOk={() => onSave({ ...form, name: form.name.trim(), alias: form.alias.trim() })}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message={
            isEdit
              ? `변경사항은 초안 ${draftVersion}에 저장됩니다 — 활성화하기 전까지 현재 버전이 계속 서빙합니다.`
              : '에이전트의 v1 초안을 만듭니다. 테스트 후 활성화해 게시하세요.'
          }
        />
        {/* ── 1단계: 기본(필수) — 이름·모델·페르소나·종류(스펙 109) ── */}
        <SectionHeader first>기본</SectionHeader>
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
          <Field label="별명 (선택)">
            <Input placeholder="예: 리서치 어시스턴트" value={form.alias} onChange={(e) => set('alias', e.target.value)} />
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>화면 표시용 자유 표기</span>
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: 16 }}>
          <Field label="모델">
            <Select
              value={form.model}
              onChange={(v) => set('model', v)}
              style={{ width: '100%' }}
              options={modelOptions}
            />
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
        <Field label="에이전트 종류">
          <Select
            value={form.impl}
            onChange={(v) => set('impl', v)}
            options={typeOptions}
            style={{ width: '100%' }}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {typeDesc(form.impl)}
          </span>
        </Field>

        {/* ── 2단계: 이 에이전트가 하는 일(스펙 109) — 종류가 그룹 세트를 가른다(108). 늘어나는 항목은
            PickerGroups(접이식+검색+카운트)로 효율 렌더 → 항목 100개여도 폼 높이 안정. ── */}
        <SectionHeader>이 에이전트가 하는 일</SectionHeader>
        {orchestratorSelected ? (
          <PickerGroups groups={capGroups} selected={form.capabilities} onToggle={toggleCap} />
        ) : (
          <PickerGroups groups={doGroups} selected={directSelected} onToggle={toggleDirect} />
        )}

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

        {/* ── 3단계: 세부 설정(선택·기본 접힘) — 기본값 있어 평소 접어둠. Temperature·히스토리·대화저장. ── */}
        <Collapse
          size="small"
          items={[
            {
              key: 'advanced',
              label: '세부 설정 (선택)',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
                  </Field>
                  <Field label="대화 저장">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <Switch checked={form.persistHistory} onChange={(v) => set('persistHistory', v)} />
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                        {form.persistHistory
                          ? '대화를 DB에 저장 (세션·인스펙터·재개)'
                          : '대화를 저장하지 않음 (가볍고 기록이 남지 않음)'}
                      </span>
                    </div>
                  </Field>
                </div>
              ),
            },
          ]}
        />
      </div>
    </Modal>
  )
}
