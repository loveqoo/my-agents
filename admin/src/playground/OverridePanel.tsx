/* Playground "Proxy" 오버라이드 패널 (스펙 025).
   web 에이전트: 저장 설정을 세션 한정으로 덮어쓴다(모델·temperature·시스템 프롬프트·MCP·
   메모리 스코프·historyDepth). 저장된 에이전트는 불변. "적용(새 대화)"으로 커밋하면 세션이
   리셋되고 이후 턴이 그 설정대로 실행된다.
   code 에이전트: 원격 실행이라 오버라이드 미적용 — read-only 안내만. */
import { useEffect, useState } from 'react'
import { Drawer, Slider, Switch, Button, Alert, Tag, Tooltip, Steps, Grid } from 'antd'
import { isOrchestratorImpl, SHORT_TERM_MEMORY, type Agent, type BlockCategory } from '../admin/mockData'
import type { Collection, Model } from '../api'
import { PickerGroups, type PickerGroup } from '../PickerGroups'
import { DelegationGraph } from '../admin/DelegationGraph'
import { ShortTermMemoryField, LongTermMemoryField } from '../admin/views/agents/MemoryFields'
import { ModelField } from '../admin/views/agents/ModelFields'
import { PromptField } from '../admin/views/agents/PromptFields'
import { safeToolName } from '../admin/views/agents/AgentForm'

export interface Overrides {
  model: string
  temperature: number | null // null = 자동(모델 등록 params 적용)
  systemPrompt: string
  mcps: string[]
  tools: string[] // 도구 단위 배선(스펙 276) — 런타임명 목록. mcps는 서버 합집합 파생.
  memories: string[]
  capabilities: string[] // 조율형 위임 대상(cap id 목록, 스펙 122). 직접형은 항상 빈 배열.
  historyDepth: number
}

/* 에이전트 저장 설정에서 패널 기본값을 만든다. Agent엔 temperature 필드가 없어 자동(null).
   tools 구저장 하이드레이션(스펙 276)은 컴포넌트가 blocks 카탈로그로 수행(여기선 저장값 그대로). */
export function overrideDefaults(a: Agent): Overrides {
  return {
    model: a.model ?? '',
    temperature: null,
    systemPrompt: a.systemPrompt ?? '',
    mcps: [...(a.mcps ?? [])],
    tools: [...(a.tools ?? [])],
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
  // 도구 단위 배선(스펙 276) — tools가 달라지면 mcps(서버 로드 원천)도 함께 보낸다(토글이 파생 유지).
  if (!sameSet(applied.tools, base.tools)) p.tools = applied.tools
  if (!sameSet(applied.memories, base.memories)) p.memories = applied.memories
  // 조율형 위임 대상(스펙 122) — 변경 시만 전송. 안 건드리면 저장분 그대로(무회귀).
  if (!sameSet(applied.capabilities, base.capabilities)) p.capabilities = applied.capabilities
  if (applied.historyDepth !== base.historyDepth) p.historyDepth = applied.historyDepth
  return p
}

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
  afterOpenChange?: (open: boolean) => void // 서랍 애니메이션 완료 신호(하단 손잡이 타이밍용)
  footer?: React.ReactNode // 모바일: 닫기를 드로어 안 하단에(바깥 손잡이는 화면 밖으로 밀림)
  bottomHandle?: React.ReactNode // 데탑: 패널 하단에 부착돼 서랍과 함께 움직이는 닫기 손잡이(후속22)
}

export function OverridePanel({ open, agent, models, blocks, agents, collections, applied, onApply, onClear, onClose, afterOpenChange, footer, bottomHandle }: Props) {
  const screens = Grid.useBreakpoint()
  // 단계형(스펙 249, 생성폼 기조) — 열 때마다 1단계부터. 요약 단계는 생략(사용자 결정).
  const [step, setStep] = useState(0)
  useEffect(() => { if (open) setStep(0) }, [open])
  const isCode = agent?.source === 'code'
  const isExternal = agent?.source === 'external' // 외부 A2A — 코드처럼 read-only(026)
  const isOrchestrator = isOrchestratorImpl(agent?.impl) // 조율형 — capabilities로 위임(스펙 108/122)
  // 비영속(스펙 238 #4) — 편집 폼과 오버라이드 폼의 규칙 정합. 저장 방식 자체는 세션 오버라이드
  // **불가**(서버 allowed 키에 없음 — 근본 모드)이므로 read-only로 표시하고, 비영속이 무시/금지하는
  // 표면(기억 회상=235, memwrite/memedit=237)은 여기서도 disabled.
  const isEphemeral = !!agent?.ephemeral
  const [draft, setDraft] = useState<Overrides | null>(null)

  // 열릴 때(또는 에이전트가 바뀔 때) 드래프트를 적용값 ?? 기본값으로 시드.
  // tools 구저장 하이드레이션(스펙 276): tools 빈값+mcps 있음 = 도구 단위 도입 전 — 카탈로그에서
  // 그 서버들의 전체 도구로 확장(폼과 동일 규칙, 안 하면 편집 적용 시 배선 유실).
  useEffect(() => {
    if (!open || !agent) return
    const base = applied ? { ...applied } : overrideDefaults(agent)
    if (!base.tools.length && base.mcps.length) {
      const items = blocks.mcp?.items ?? []
      base.tools = base.mcps.flatMap((srv) => {
        const it = items.find((m) => m.name === srv)
        return (it?.tools ?? []).map((t) => safeToolName(srv, t))
      })
    }
    setDraft(base)
    // applied는 의도적으로 deps에서 제외 — 열려 있는 동안 외부 적용으로 드래프트가 튀지 않게.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, agent?.id])

  if (!agent) return null

  const set = <K extends keyof Overrides>(k: K, v: Overrides[K]) =>
    setDraft((d) => (d ? { ...d, [k]: v } : d))
  // 도구 단위 토글(스펙 276) — mcps(서버 로드 원천)를 서버 합집합으로 파생 유지. 카탈로그에 도구
  // 목록 없는 서버는 mcps에 보존(런타임 폴백=전체 노출 — 폼과 동일 규칙).
  const toggleTool = (rt: string) =>
    setDraft((d) => {
      if (!d) return d
      const tools = d.tools.includes(rt) ? d.tools.filter((x) => x !== rt) : [...d.tools, rt]
      const items = blocks.mcp?.items ?? []
      const preserved = d.mcps.filter((srv) => !(items.find((m) => m.name === srv)?.tools?.length))
      const mcps = [...new Set([...tools.map((x) => x.split('__')[0]), ...preserved])]
      return { ...d, tools, mcps }
    })

  // 모델 옵션화(chat 필터·미등록 값 보존)는 공용 ModelField가 담당(스펙 274 — 사본 소멸).

  // "이 대화에서 쓸 것"(스펙 109) — 도구만 PickerGroups(기억은 273에서 우측 세부 공용 컨트롤로).
  // 항목=개별 도구(스펙 276, 폼·노드와 같은 어휘) — 서버가 아니라 기능 단위로 세션 오버라이드.
  const ovGroups: PickerGroup[] = [
    {
      key: '도구',
      title: '도구',
      items: (blocks.mcp?.items ?? []).flatMap((s) =>
        (s.tools ?? []).map((t) => ({ id: `tool:${safeToolName(s.name, t)}`, label: `${s.name} · ${t}` }))
      ),
      emptyText: '등록된 MCP 도구 없음',
    },
  ]
  const ovSelected = draft ? draft.tools.map((x) => `tool:${x}`) : []
  const ovToggle = (id: string) => {
    if (id.startsWith('tool:')) toggleTool(id.slice(5))
  }
  // 장기 기억 옵션(273 공용 컨트롤용) — 단기(세션)은 선택지에서 제외(스펙 269, historyDepth가 소유).
  // 비영속 미선택-잠금(235·codex 238 #2)은 LongTermMemoryField의 ephemeral prop이 담당(중복 구현 소멸).
  const memoryOptions = (blocks.memory?.items ?? [])
    .filter((m) => m.name !== SHORT_TERM_MEMORY)
    .map((m) => ({ label: m.name, value: m.name }))

  // 조율형 "무엇에 맡길까요?"(스펙 122) — 편집 폼(AgentsView capGroups)과 같은 4그룹. cap id는 값으로만,
  // 표시는 사람이 읽는 이름. draft.capabilities에 바인딩해 세션 오버라이드(백엔드 브로커가 호출자 RBAC 게이트).
  const capGroups: PickerGroup[] = [
    {
      key: '다른 에이전트',
      title: '다른 에이전트',
      items: agents
        // 로컬 ui(활성 버전 보유·자기 제외)도 위임 대상(스펙 256 — 인프로세스 직접 호출)
        .filter((a) => (a.source === 'code' || a.source === 'external')
          || (((a.source ?? 'ui') === 'ui') && !!a.activeVersion && a.id !== agent?.id))
        .map((a) => ({ id: a.agentId, label: (a.source === 'code' || a.source === 'external') ? `${a.name} · A2A` : `${a.name} · 로컬` })),
      emptyText: '위임할 에이전트 없음',
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
      // 모바일: 열릴 때 첫 입력으로 자동 포커스하면 본문이 스크롤돼 Steps가 가려짐 — 포커스 이동 끔.
      autoFocus={false}
      // 닫힐 때 내용 언마운트 — 이전 열림의 본문 스크롤(예: 2단계서 적용)이 남아 재열기 때 Steps가
      // 스크롤 위로 숨던 문제(scrollTop 115 실측). 매번 1단계·스크롤 0에서 시작.
      destroyOnHidden
      afterOpenChange={afterOpenChange}
      // 하단 고정 푸터(스펙 249) — 요약 단계가 없는 대신 적용을 어디서나 한 클릭으로.
      // 좌=보조(기본값·해제), 우=이동(이전/다음)+적용. 모바일 닫기(footer prop)는 맨 오른쪽에 병합.
      footer={
        !isExternal && !isCode && draft ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button size="small" onClick={() => agent && setDraft(overrideDefaults(agent))}>기본값으로</Button>
            {applied ? (
              <Button size="small" type="text" danger onClick={onClear}>해제</Button>
            ) : null}
            {applied ? <Tag color="purple" style={{ margin: 0 }}>적용 중</Tag> : null}
            <span style={{ flex: 1 }} />
            {step > 0 && <Button size="small" onClick={() => setStep(step - 1)}>이전</Button>}
            {step < 1 && <Button size="small" onClick={() => setStep(step + 1)}>다음</Button>}
            <Button size="small" type="primary" onClick={() => draft && onApply(draft)}>적용 — 새 대화</Button>
            {footer}
          </div>
        ) : footer
      }
      // 손잡이를 패널에 직접 부착(후속22) — 지연 게이팅 대신 서랍과 **함께** 내려온다(0초 지연).
      drawerRender={(node) => (
        <div style={{ height: '100%', position: 'relative' }}>
          {node}
          {bottomHandle}
        </div>
      )}
      // 위→아래(스펙 248 후속15, 사용자 디자인): 헤더에 매달린 U 손잡이를 당기면 서랍이 내려온다.
      placement="top"
      // 컨테이너 기준 %(후속25): 70vh는 모바일 주소창 탓에 실제 가시 영역보다 커서 하단 닫기가
      // 화면 밖으로 밀렸다(사용자 실기기). 래퍼(헤더 아래 영역)는 실제 레이아웃 높이라 항상 화면 안.
      height="min(85%, 560px)"
      // 헤더 삭제(후속26, 사용자): 손잡이에 '오버라이드'가 이미 써 있고 본문 첫 줄이 안내 —
      // 제목·X 없는 무헤더 서랍(title 없음+closable=false → antd가 헤더 자체를 안 그림).
      closable={false}
      // 후속16: body가 아니라 플레이그라운드 영역 안에 렌더 — 데탑은 사이드바를 제외한 우측만 덮고,
      // 모바일은 그 영역이 곧 전폭. 부모(Playground 루트)가 position: relative를 소유.
      getContainer={false}
      rootStyle={{ position: 'absolute' }}
      // wrapper를 마스크(z 1000) 위로 — 같은 z면 DOM 뒤의 마스크가 패널 밖으로 나온 손잡이의
      // 클릭을 가로챈다(elementFromPoint 실측).
      styles={{ body: { paddingTop: 12 }, wrapper: { zIndex: 1001 } }}
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
          <Steps
            size="small"
            current={step}
            onChange={setStep}
            // 2단계 제목은 kind별 실내용(스펙 273): 직접형=도구 피커+기억 공용 컨트롤, 조율형=위임 피커.
            items={[{ title: '모델 · 프롬프트' }, { title: isOrchestrator ? '맡길 것 · 세부' : '도구 · 기억 · 세부' }]}
            style={{ maxWidth: 520 }}
          />
          {step === 0 && (<>
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

          {/* 모델·시스템 프롬프트 = 공용 컨트롤(스펙 274) — chat 필터·미등록 보존·페르소나 로더가
              단일 출처. 프롬프트의 "가져오기"는 라벨 줄 콤팩트 로더로 축약(별도 Field 2개→1구획, 077 대칭 유지). */}
          <ModelField
            value={draft.model}
            onChange={(v) => set('model', v)}
            models={models}
            hint="mock-llm을 고르면 라이브 모델 없이 결정적으로 응답합니다."
          />
          <PromptField
            label="시스템 프롬프트"
            value={draft.systemPrompt}
            onChange={(v) => set('systemPrompt', v)}
            personas={(blocks.persona?.items ?? []).map((p) => ({ name: p.name, body: p.body ?? '' }))}
            placeholder={agent.systemPrompt ? undefined : '(저장된 시스템 프롬프트 없음)'}
            hint="비워두면 저장된 페르소나가 그대로 쓰입니다."
          />
          </>)}

          {step === 1 && (
          // 데탑 2열(스펙 249 후속1, 사용자: 2단계가 서랍 세로를 넘음) — top 드로어는 가로가 넓다:
          // 좌=쓸 것, 우=세부. 모바일은 1열+스크롤.
          <div style={{ display: 'grid', gridTemplateColumns: screens.md ? '1fr 1fr' : '1fr', gap: screens.md ? 28 : 18, alignItems: 'start' }}>
          {/* 이 대화에서 쓸 것(스펙 109/122) — 조율형은 위임 대상(capabilities), 직접형은 도구·기억.
              편집 폼과 같은 kind별 표면(스펙 108): 조율형에 mcps/memories를 보여주면 런타임 미사용이라
              오해만 준다(learning 108). */}
          <Field group label={isOrchestrator ? '이 대화에서 맡길 것' : '이 대화에서 쓸 것'}>
            {/* 내부 스크롤 상한(스펙 249 후속2) — 도구·컬렉션이 많아도(14개 실측 697px) 서랍 골격은
                고정, 목록만 스크롤. 데탑 한정(모바일은 본문 스크롤이 자연). */}
            <div style={{ maxHeight: screens.md ? 400 : undefined, overflowY: 'auto' }}>
              {isOrchestrator ? (
                <PickerGroups groups={capGroups} selected={draft.capabilities} onToggle={capToggle} />
              ) : (
                <PickerGroups groups={ovGroups} selected={ovSelected} onToggle={ovToggle} />
              )}
            </div>
          </Field>
          {isOrchestrator && agent ? (
            // 위임 구조 미리보기(스펙 257) — 편집 중 값(draft.capabilities) 기준: 체크를 바꾸면
            // 적용 전에 구조가 어떻게 되는지 즉시 보인다. 순환은 빨간 마커(실행 시 자동 차단).
            <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 6 }}>위임 구조 미리보기</div>
              <DelegationGraph rootAgentId={agent.agentId} agents={agents} rootCapsOverride={draft.capabilities} />
            </div>
          ) : null}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* 세부(스펙 249: 단계가 이미 구획이라 Collapse 해제·평면 나열) — Temperature·채팅 히스토리. */}
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
          {/* 기억(스펙 273) — AgentForm 271과 같은 공용 컨트롤(MemoryFields). 단기=historyDepth,
              장기=memories(비영속 미선택-잠금은 ephemeral prop이 담당). 라벨·옵션 단일 출처=drift 0. */}
          <ShortTermMemoryField
            value={draft.historyDepth}
            onChange={(v) => set('historyDepth', v ?? 0)}
            hint="최근 N개 대화(채팅 히스토리)를 모델에 넣습니다."
          />
          {!isOrchestrator && (
            <LongTermMemoryField
              value={draft.memories}
              onChange={(arr) => set('memories', arr)}
              options={memoryOptions}
              ephemeral={isEphemeral}
            />
          )}
          </div>
          </div>
          )}
        </div>
      )}
    </Drawer>
  )
}
