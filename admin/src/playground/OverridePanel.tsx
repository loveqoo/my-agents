/* Playground "Proxy" 오버라이드 패널 (스펙 025).
   web 에이전트: 저장 설정을 세션 한정으로 덮어쓴다(모델·temperature·시스템 프롬프트·MCP·
   메모리 스코프·historyDepth). 저장된 에이전트는 불변. "적용(새 대화)"으로 커밋하면 세션이
   리셋되고 이후 턴이 그 설정대로 실행된다.
   code 에이전트: 원격 실행이라 오버라이드 미적용 — read-only 안내만. */
import { useEffect, useState } from 'react'
import { Drawer, Select, Input, Slider, Switch, Button, Alert, Tag, Tooltip, Collapse } from 'antd'
import { isOrchestratorImpl, type Agent, type BlockCategory } from '../admin/mockData'
import type { Collection, Model } from '../api'
import { PickerGroups, type PickerGroup } from '../PickerGroups'

export interface Overrides {
  model: string
  temperature: number | null // null = 자동(모델 등록 params 적용)
  systemPrompt: string
  mcps: string[]
  memories: string[]
  capabilities: string[] // 조율형 위임 대상(cap id 목록, 스펙 122). 직접형은 항상 빈 배열.
  historyDepth: number
}

/* 에이전트 저장 설정에서 패널 기본값을 만든다. Agent엔 temperature 필드가 없어 자동(null). */
export function overrideDefaults(a: Agent): Overrides {
  return {
    model: a.model ?? '',
    temperature: null,
    systemPrompt: a.systemPrompt ?? '',
    mcps: [...(a.mcps ?? [])],
    memories: [...(a.memories ?? [])],
    capabilities: [...(a.capabilities ?? [])],
    historyDepth: a.historyDepth ?? 20,
  }
}

const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().join('\n') === [...b].sort().join('\n')

/* 적용된 오버라이드를 에이전트 기본값과 비교해 **변경된 키만** 담은 전송 페이로드.
   비어 있으면(=변경 없음) 호출부가 overrides를 안 보내 저장 설정 그대로 실행(무회귀). */
export function overridePayload(applied: Overrides, base: Overrides): Record<string, unknown> {
  const p: Record<string, unknown> = {}
  if (applied.model && applied.model !== base.model) p.model = applied.model
  if (applied.temperature != null && applied.temperature !== base.temperature) p.temperature = applied.temperature
  // 빈 systemPrompt로 persona를 지우지 않도록 — 비어있지 않고 달라진 경우만.
  if (applied.systemPrompt.trim() && applied.systemPrompt !== base.systemPrompt) p.systemPrompt = applied.systemPrompt
  if (!sameSet(applied.mcps, base.mcps)) p.mcps = applied.mcps
  if (!sameSet(applied.memories, base.memories)) p.memories = applied.memories
  // 조율형 위임 대상(스펙 122) — 변경 시만 전송. 안 건드리면 저장분 그대로(무회귀).
  if (!sameSet(applied.capabilities, base.capabilities)) p.capabilities = applied.capabilities
  if (applied.historyDepth !== base.historyDepth) p.historyDepth = applied.historyDepth
  return p
}

const DEPTH_OPTS = [
  { label: '기억 안 함 (0개)', value: 0 },
  { label: '최근 6개 메시지', value: 6 },
  { label: '최근 10개 메시지', value: 10 },
  { label: '최근 20개 메시지', value: 20 },
  { label: '최근 40개 메시지', value: 40 },
  { label: '최근 100개 메시지', value: 100 },
]

/* group=false(기본): 단일 컨트롤용 <label> — 라벨 클릭이 그 컨트롤로 포커스 이동(UX). group=true:
   컨트롤 여러 개(PickerGroups 등)를 담을 땐 <div>로 감싼다 — <label>은 컨트롤 하나에만 붙어야 하고,
   여러 컨트롤을 label로 감싸면 라벨 어디를 클릭하든 브라우저가 **첫 하위 컨트롤로 클릭을 전달**해
   엉뚱한 항목이 토글된다(스펙 123: 그룹 헤더 클릭→첫 체크박스 오토글 버그). */
function Field({ label, hint, children, group = false }: { label: string; hint?: string; children: React.ReactNode; group?: boolean }) {
  const inner = (
    <>
      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)' }}>{label}</span>
      {children}
      {hint ? <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{hint}</span> : null}
    </>
  )
  const style = { display: 'flex', flexDirection: 'column' as const, gap: 6 }
  return group ? (
    <div role="group" aria-label={label} style={style}>{inner}</div>
  ) : (
    <label style={style}>{inner}</label>
  )
}

/* 외부(A2A) 에이전트 — 코드처럼 read-only. 오버라이드 대신 등록된 카드 메타를 노출(026, 1차).
   실제 A2A 런타임 호출은 2차 스펙이라, 여기선 카드 정보만 보여준다. */
function ExternalCardInfo({ agent }: { agent: Agent }) {
  const card = agent.card
  const caps = Object.entries(card?.capabilities ?? {})
    .filter(([, v]) => v === true)
    .map(([k]) => k)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Alert
        type="info"
        showIcon
        title="외부(A2A) 에이전트 — 오버라이드 미적용"
        description="이 에이전트는 외부 A2A 서비스가 소유합니다. 모델·도구·메모리는 원격이 관장하므로 로컬 설정을 덮어쓸 수 없습니다. 실제 호출 기능은 준비 중입니다."
      />
      {!card ? (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>등록된 카드 정보가 없습니다.</span>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="카드">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontWeight: 600 }}>
                {card.name}
                {card.version ? <Tag style={{ marginLeft: 8 }}>v{card.version}</Tag> : null}
              </span>
              {card.description ? (
                <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>{card.description}</span>
              ) : null}
              {card.provider?.organization ? (
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                  제공: {card.provider.organization}
                </span>
              ) : null}
            </div>
          </Field>

          <Field label="엔드포인트">
            <span style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, wordBreak: 'break-all' }}>
              {card.url ?? agent.endpoint ?? '—'}
            </span>
          </Field>

          {caps.length ? (
            <Field label="기능 (capabilities)">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {caps.map((c) => (
                  <Tag key={c} color="blue">{c}</Tag>
                ))}
              </div>
            </Field>
          ) : null}

          {card.skills?.length ? (
            <Field label="스킬 (skills)">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {card.skills.map((s, i) => (
                  <div key={s.id ?? i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{s.name ?? s.id}</span>
                    {s.description ? (
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{s.description}</span>
                    ) : null}
                  </div>
                ))}
              </div>
            </Field>
          ) : null}
        </div>
      )}
    </div>
  )
}

interface Props {
  open: boolean
  agent: Agent | null
  models: Model[]
  blocks: Record<string, BlockCategory>
  /** 조율형 위임 대상 카탈로그(스펙 122): 원격 에이전트·문서 컬렉션. capGroups 조립용. */
  agents: Agent[]
  collections: Collection[]
  /** 현재 적용 중인 오버라이드(없으면 미적용). */
  applied: Overrides | null
  onApply: (ov: Overrides) => void
  onClear: () => void
  onClose: () => void
}

export function OverridePanel({ open, agent, models, blocks, agents, collections, applied, onApply, onClear, onClose }: Props) {
  const isCode = agent?.source === 'code'
  const isExternal = agent?.source === 'external' // 외부 A2A — 코드처럼 read-only(026)
  const isOrchestrator = isOrchestratorImpl(agent?.impl) // 조율형 — capabilities로 위임(스펙 108/122)
  // 비영속(스펙 238 #4) — 편집 폼과 오버라이드 폼의 규칙 정합. 저장 방식 자체는 세션 오버라이드
  // **불가**(서버 allowed 키에 없음 — 근본 모드)이므로 read-only로 표시하고, 비영속이 무시/금지하는
  // 표면(기억 회상=235, memwrite/memedit=237)은 여기서도 disabled.
  const isEphemeral = !!agent?.ephemeral
  const [draft, setDraft] = useState<Overrides | null>(null)

  // 열릴 때(또는 에이전트가 바뀔 때) 드래프트를 적용값 ?? 기본값으로 시드.
  useEffect(() => {
    if (!open || !agent) return
    setDraft(applied ? { ...applied } : overrideDefaults(agent))
    // applied는 의도적으로 deps에서 제외 — 열려 있는 동안 외부 적용으로 드래프트가 튀지 않게.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, agent?.id])

  if (!agent) return null

  const set = <K extends keyof Overrides>(k: K, v: Overrides[K]) =>
    setDraft((d) => (d ? { ...d, [k]: v } : d))
  const toggleList = (k: 'mcps' | 'memories', name: string) =>
    setDraft((d) => {
      if (!d) return d
      const cur = d[k]
      return { ...d, [k]: cur.includes(name) ? cur.filter((x) => x !== name) : [...cur, name] }
    })

  // 등록 chat 모델 옵션 — 현재 모델이 목록에 없으면(예: 미등록 이름) 그대로 추가해 선택 유지.
  const modelOptions = models.filter((m) => m.kind === 'chat').map((m) => ({ label: m.name, value: m.name }))
  if (draft?.model && !modelOptions.some((o) => o.value === draft.model)) {
    modelOptions.push({ label: draft.model, value: draft.model })
  }

  // "이 대화에서 쓸 것"(스펙 109) — mcps·memories 두 배열을 PickerGroups 하나로. 등록 폼과 같은
  // 효율 렌더(접이식+검색+카운트) 공용. id prefix로 라우팅, 저장은 기존 배열 그대로.
  const OV_FIELD: Record<string, 'mcps' | 'memories'> = { tool: 'mcps', mem: 'memories' }
  const ovGroups: PickerGroup[] = [
    {
      key: '도구',
      title: '도구',
      items: (blocks.mcp?.items ?? []).map((m) => ({ id: `tool:${m.name}`, label: m.name })),
      emptyText: '등록된 MCP 서버 없음',
    },
    {
      key: '기억',
      title: '기억',
      items: (blocks.memory?.items ?? []).map((m) => ({
        id: `mem:${m.name}`,
        label: m.name,
        // 비영속은 회상·기록을 하지 않는다(스펙 235) — 새 선택만 잠근다(미선택-잠금, codex 238 #2:
        // 이미 적용된 오버라이드에 남은 기선택은 해제할 수 있어야 함).
        disabled: isEphemeral && !draft?.memories.includes(m.name),
        disabledHint: isEphemeral ? '비영속(1회성) 에이전트는 기억을 쓰지 않습니다.' : undefined,
      })),
      emptyText: '등록된 메모리 블록 없음',
    },
  ]
  const ovSelected = draft ? [...draft.mcps.map((x) => `tool:${x}`), ...draft.memories.map((x) => `mem:${x}`)] : []
  const ovToggle = (id: string) => {
    const i = id.indexOf(':')
    const field = OV_FIELD[id.slice(0, i)]
    if (field) toggleList(field, id.slice(i + 1))
  }

  // 조율형 "무엇에 맡길까요?"(스펙 122) — 편집 폼(AgentsView capGroups)과 같은 4그룹. cap id는 값으로만,
  // 표시는 사람이 읽는 이름. draft.capabilities에 바인딩해 세션 오버라이드(백엔드 브로커가 호출자 RBAC 게이트).
  const capGroups: PickerGroup[] = [
    {
      key: '다른 에이전트',
      title: '다른 에이전트',
      items: agents
        .filter((a) => a.source === 'code' || a.source === 'external')
        .map((a) => ({ id: a.agentId, label: a.name })),
      emptyText: '위임할 원격 에이전트 없음',
    },
    {
      key: '도구',
      title: '도구',
      items: (blocks.mcp?.items ?? []).map((m) => ({ id: `mcp:${m.name}`, label: m.name })),
      emptyText: '등록된 MCP 서버 없음',
    },
    {
      key: '문서',
      title: '문서',
      items: collections.map((c) => ({ id: `rag:${c.name}`, label: c.name })),
      emptyText: '등록된 문서 컬렉션 없음',
    },
    {
      key: '사용자 기억',
      title: '사용자 기억',
      items: [
        { id: 'memory:user', label: '사용자 기억 읽기' },
        {
          id: 'memwrite:user',
          label: '사용자 기억에 저장 · 승인 필요',
          // 편집 폼과 동일 규칙(스펙 237/238) — 비영속은 DB 쓰기 능력 금지(서버도 런타임 필터).
          // 미선택-잠금: 이미 적용된 오버라이드에 남은 기선택은 해제 가능해야(codex 238 #2).
          disabled: isEphemeral && !draft?.capabilities.includes('memwrite:user'),
          disabledHint: isEphemeral ? '비영속(1회성)에서는 쓸 수 없습니다 — 기록을 남기는 능력입니다.' : undefined,
        },
      ],
    },
  ]
  const capToggle = (id: string) =>
    setDraft((d) => {
      if (!d) return d
      const cur = d.capabilities
      return { ...d, capabilities: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] }
    })

  return (
    <Drawer
      open={open}
      onClose={onClose}
      // 위→아래(스펙 248 후속15, 사용자 디자인): 헤더에 매달린 U 손잡이를 당기면 서랍이 내려온다.
      placement="top"
      height="min(70vh, 560px)"
      title="런타임 오버라이드"
      styles={{ body: { paddingTop: 12 } }}
    >
      {isExternal ? (
        <ExternalCardInfo agent={agent} />
      ) : isCode ? (
        <Alert
          type="info"
          showIcon
          title="코드 에이전트 — 오버라이드 미적용"
          description="이 에이전트는 등록된 원격 엔드포인트에서 실행됩니다(bypass). 모델·도구·메모리는 원격 배포가 소유하므로 여기 설정은 로컬 실행에 적용되지 않습니다."
        />
      ) : !draft ? null : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Alert
            type="info"
            showIcon
            style={{ padding: '6px 12px' }}
            title="세션 한정 — 저장된 에이전트 설정은 바뀌지 않습니다. 적용하면 새 대화로 시작합니다."
          />
          {/* 바꿀 수 없는 것 명시(스펙 238 #4) — 저장 방식(영속/비영속)은 근본 모드라 세션 오버라이드 불가. */}
          {isEphemeral && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Tag color="default">비영속 (1회성)</Tag>
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                저장 방식은 여기서 바꿀 수 없습니다 — 에이전트 편집에서 변경하세요.
              </span>
            </div>
          )}

          <Field label="모델" hint="mock-llm을 고르면 라이브 모델 없이 결정적으로 응답합니다.">
            <Select
              value={draft.model}
              onChange={(v) => set('model', v)}
              style={{ width: '100%' }}
              options={modelOptions}
            />
          </Field>

          {/* 페르소나 블록에서 채우기(스펙 077) — 생성 폼의 페르소나 Select와 대칭.
              블록을 고르면 그 본문이 아래 시스템 프롬프트에 채워지고, 이후 자유편집 가능. */}
          <Field label="페르소나 블록에서 채우기" hint="등록된 페르소나를 고르면 아래 시스템 프롬프트가 채워집니다.">
            <Select
              value={undefined}
              placeholder="페르소나 블록 선택…"
              style={{ width: '100%' }}
              allowClear
              options={(blocks.persona?.items ?? []).map((p) => ({ label: p.name, value: p.id }))}
              onChange={(id) => {
                const p = (blocks.persona?.items ?? []).find((x) => x.id === id)
                if (p?.body != null) set('systemPrompt', p.body)
              }}
              notFoundContent="등록된 페르소나 블록 없음"
            />
          </Field>

          <Field label="시스템 프롬프트" hint="비워두면 저장된 페르소나가 그대로 쓰입니다.">
            <Input.TextArea
              value={draft.systemPrompt}
              onChange={(e) => set('systemPrompt', e.target.value)}
              autoSize={{ minRows: 3, maxRows: 10 }}
              placeholder={agent.systemPrompt ? undefined : '(저장된 시스템 프롬프트 없음)'}
            />
          </Field>

          {/* 이 대화에서 쓸 것(스펙 109/122) — 조율형은 위임 대상(capabilities), 직접형은 도구·기억.
              편집 폼과 같은 kind별 표면(스펙 108): 조율형에 mcps/memories를 보여주면 런타임 미사용이라
              오해만 준다(learning 108). */}
          <Field group label={isOrchestrator ? '이 대화에서 맡길 것' : '이 대화에서 쓸 것'}>
            {isOrchestrator ? (
              <PickerGroups groups={capGroups} selected={draft.capabilities} onToggle={capToggle} />
            ) : (
              <PickerGroups groups={ovGroups} selected={ovSelected} onToggle={ovToggle} />
            )}
          </Field>

          {/* 세부 설정(선택·기본 접힘) — Temperature·채팅 히스토리. 기본값 있어 평소 접어둠. */}
          <Collapse
            size="small"
            items={[
              {
                key: 'advanced',
                label: '세부 설정 (선택)',
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <Field
                      group
                      label="Temperature"
                      hint={draft.temperature == null ? '자동 — 모델 등록 기본값을 사용합니다.' : undefined}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <Tooltip title="끄면 모델 등록 기본값(자동)">
                          <Switch
                            size="small"
                            checked={draft.temperature != null}
                            onChange={(on) => set('temperature', on ? 0.7 : null)}
                          />
                        </Tooltip>
                        <Slider
                          min={0}
                          max={2}
                          step={0.1}
                          disabled={draft.temperature == null}
                          value={draft.temperature ?? 0.7}
                          onChange={(v) => set('temperature', v)}
                          style={{ flex: 1 }}
                        />
                        <span style={{ width: 32, textAlign: 'right', fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
                          {draft.temperature == null ? '—' : draft.temperature.toFixed(1)}
                        </span>
                      </div>
                    </Field>
                    <Field label="채팅 히스토리">
                      <Select
                        value={draft.historyDepth}
                        onChange={(v) => set('historyDepth', v)}
                        style={{ width: '100%' }}
                        options={DEPTH_OPTS}
                      />
                    </Field>
                  </div>
                ),
              },
            ]}
          />

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
            <Button type="primary" onClick={() => draft && onApply(draft)}>
              적용 (새 대화)
            </Button>
            <Button onClick={() => agent && setDraft(overrideDefaults(agent))}>기본값으로</Button>
            {applied ? (
              <Button type="text" danger onClick={onClear}>
                오버라이드 해제
              </Button>
            ) : null}
            {applied ? <Tag color="purple">적용 중</Tag> : null}
          </div>
        </div>
      )}
    </Drawer>
  )
}
