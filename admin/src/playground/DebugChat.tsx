/* my-agents debug console — center: chat with the selected agent.
   Header exposes the agent's config + a "System prompt" toggle. Each assistant
   turn is selectable (drives the Inspector) and shows trace chips. Data is real:
   agents come from the backend, turns/traces come from the streaming chat API. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Bubble, Sender, Prompts } from '@ant-design/x'
import type { GetRef } from 'antd'
import {
  INITIAL_HIST,
  recallOlder,
  recallNewer,
  resetHist,
  dedupeConsecutive,
  type HistState,
} from './inputHistory'
import { Avatar, Button, Tag, Grid, Tooltip } from 'antd'
import { Icon } from '../admin/icons'
import { fmtTime } from '../admin/format'
import { MessageContent } from './MessageContent'
import type { ChatMsg, Trace } from './agentData'
import type { Agent, Session } from '../admin/mockData'

const agentAvatar = (
  <Avatar style={{ background: 'var(--gray-12)', flex: 'none' }}>
    <Icon name="robot" />
  </Avatar>
)
const userAvatar = <Avatar style={{ background: 'var(--volcano-6)', flex: 'none' }}>U</Avatar>

const STATUS_DOT: Record<string, string> = {
  online: 'var(--color-success)',
  idle: 'var(--gold-6)',
  offline: 'var(--gray-6)',
}
const statusDot = (status: string) => STATUS_DOT[status] ?? 'var(--gray-6)'

/* 모델 배지를 source별로 정직하게 (스펙 028). code 에이전트는 model 필드가 박혀 있어도
   로컬 모델로 돌지 않고 자기 원격 엔드포인트(dev=mock)로 bypass하므로 모델명을 띄우면
   거짓이다 → "원격 (SDK)"(AGENT_SOURCE.code.label '원격'·"원격 MCP" 어휘와 일관).
   external은 A2A 원격 → "외부 A2A"(AGENT_SOURCE.external.label과 동일). ui만 실행 모델 맞아 모델명. */
function modelBadge(a: Agent): { text: string; remote: boolean; tip?: ReactNode } {
  if (a.source === 'code')
    return {
      text: '원격 (SDK)',
      remote: true,
      tip: (
        <span style={{ whiteSpace: 'pre-line' }}>
          {['원격 엔드포인트에서 실행 — 로컬 모델 미사용', a.runtime, a.endpoint].filter(Boolean).join('\n')}
        </span>
      ),
    }
  if (a.source === 'external')
    return { text: '외부 A2A', remote: true, tip: a.card?.url ?? a.endpoint }
  return { text: a.model, remote: false }
}

/* size='header': 헤더 칩(pill). size='row': 피커 행의 작은 텍스트. remote면 primary 대신 중립색. */
function ModelBadge({ a, size }: { a: Agent; size: 'header' | 'row' }) {
  const b = modelBadge(a)
  const header = size === 'header'
  const chip = (
    <span
      style={{
        fontFamily: 'var(--font-family-code)',
        fontWeight: header ? 600 : 400,
        fontSize: header ? undefined : 11,
        color: b.remote ? 'var(--color-text-tertiary)' : header ? 'var(--color-primary)' : 'var(--color-text-tertiary)',
        ...(header
          ? {
              background: b.remote ? 'var(--color-fill-tertiary)' : 'var(--color-primary-bg)',
              border: '1px solid ' + (b.remote ? 'var(--color-border)' : 'var(--color-primary-border)'),
              borderRadius: 5,
              padding: '0 5px',
              marginInlineEnd: 6,
            }
          : {}),
      }}
    >
      {b.text}
    </span>
  )
  return b.tip ? <Tooltip title={b.tip}>{chip}</Tooltip> : chip
}

/* 미활성 초안 감지(스펙 078): 편집은 항상 draft 버전에 저장되고 Playground는 활성 서빙
   config를 실행하므로, 초안이 있으면 "편집이 아직 반영 안 됨"이다. 진실원은 agent.versions
   (list_agents가 draft 포함 전 버전 직렬화) — mock 상수 아님(learning 035). code/external은
   draft 상태 버전이 없어 자연히 false. */
function hasDraft(a: Agent): boolean {
  return (a.versions ?? []).some((v) => v.status === 'draft')
}

/* 헤더/피커에 다는 미반영 초안 배지. compact면 아이콘만(좁은 폭에서도 안내 보존). */
function DraftBadge({ compact }: { compact?: boolean }) {
  return (
    <Tooltip title="이 에이전트에 활성화되지 않은 초안 편집이 있습니다. Playground는 활성 버전을 실행합니다 — 변경을 반영하려면 Agents에서 초안을 활성화하세요.">
      <Tag color="gold" style={{ margin: 0, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <Icon name="edit" size={11} />
        {compact ? null : '미반영 초안'}
      </Tag>
    </Tooltip>
  )
}

interface DebugChatProps {
  agent: Agent | null
  agents: Agent[]
  onSwitchAgent: (id: string) => void
  sessions: Session[]
  currentSessionId?: string
  sessionsLoading: boolean
  onPickSession: (sid: string) => void
  onReloadSessions: () => void
  messages: ChatMsg[]
  streaming: boolean
  selectedTurn: number | null
  onSelectTurn: (i: number) => void
  onSend: (text: string) => void
  onStop: () => void
  canResetConversation: boolean
  onResetConversation: () => void
  showPrompt: boolean
  onTogglePrompt: () => void
  effectiveSystemPrompt?: string
  inspectorOpen: boolean
  onToggleInspector: () => void
  overrideActive: boolean
  onToggleOverrides: () => void
}

function ExposeBadges({ agent }: { agent: Agent }) {
  // A2A 배지는 로컬(ui) 노출 에이전트만 — 원격/외부는 재노출 불가(스펙 083 불변식: exposed.a2a ⟹ source=ui).
  const exposed = agent.source === 'ui' && agent.exposed?.a2a
  return <div style={{ display: 'flex', gap: 6 }}>{exposed ? <Tag color="green">A2A</Tag> : null}</div>
}

/* Rich agent picker — replaces the left rail. Shows avatar, persona, model and
   MCP chips per agent in a dropdown. */
function AgentCombo({
  agent,
  agents,
  onSwitch,
}: {
  agent: Agent
  agents: Agent[]
  onSwitch: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  return (
    <div ref={ref} style={{ position: 'relative', minWidth: 0 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '6px 12px 6px 8px',
          borderRadius: 10,
          border: '1px solid ' + (open ? 'var(--color-primary-border)' : 'var(--color-border)'),
          background: open ? 'var(--color-primary-bg)' : 'var(--color-bg-container)',
          cursor: 'pointer',
          font: 'inherit',
          transition: 'all .2s',
          maxWidth: 360,
          // 슬롯이 좁아지면 버튼도 따라 줄고 안쪽 텍스트가 ellipsis 되도록 — 안 그러면
          // 콘텐츠 폭(~347px)을 고수해 슬롯 밖으로 넘쳐 옆 요소(userId)를 덮는다.
          width: '100%',
          minWidth: 0,
        }}
      >
        <span style={{ position: 'relative', flex: 'none' }}>
          {agentAvatar}
          <span
            style={{
              position: 'absolute',
              right: -1,
              bottom: -1,
              width: 9,
              height: 9,
              borderRadius: '50%',
              background: statusDot(agent.status),
              border: '2px solid #fff',
            }}
          />
        </span>
        <span style={{ minWidth: 0, textAlign: 'left' }}>
          <span
            style={{
              display: 'block',
              fontSize: 15,
              fontWeight: 600,
              color: 'var(--color-text-heading)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {agent.name}
          </span>
          <span
            style={{
              display: 'block',
              fontSize: 12,
              color: 'var(--color-text-tertiary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {/* 실행 주체를 한눈에 — ui=모델명, code=코드 정의, external=외부 A2A (스펙 028). */}
            <ModelBadge a={agent} size="header" />
            {agent.persona}
          </span>
        </span>
        {/* 미반영 초안 표식(스펙 078) — 현재 선택된 에이전트가 초안을 안고 있으면 트리거에도 점등. */}
        {hasDraft(agent) ? (
          <Tag color="gold" style={{ margin: 0, flex: 'none' }}>
            <Icon name="edit" size={10} /> 초안
          </Tag>
        ) : null}
        <Icon
          name="down"
          size={12}
          style={{
            color: 'var(--color-text-tertiary)',
            flex: 'none',
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform .2s',
          }}
        />
      </button>
      {open ? (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            zIndex: 1050,
            width: 360,
            background: 'var(--color-bg-elevated)',
            borderRadius: 12,
            boxShadow: 'var(--box-shadow)',
            padding: 6,
            maxHeight: 420,
            overflow: 'auto',
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '6px 10px 4px' }}>에이전트 {agents.length}</div>
          {agents.map((a) => {
            const on = a.id === agent.id
            return (
              <button
                key={a.id}
                onClick={() => {
                  onSwitch(a.id)
                  setOpen(false)
                }}
                style={{
                  width: '100%',
                  display: 'flex',
                  gap: 10,
                  alignItems: 'flex-start',
                  padding: '9px 10px',
                  borderRadius: 8,
                  border: 'none',
                  cursor: 'pointer',
                  font: 'inherit',
                  textAlign: 'left',
                  background: on ? 'var(--color-primary-bg)' : 'transparent',
                  transition: 'background .15s',
                }}
                onMouseEnter={(e) => {
                  if (!on) e.currentTarget.style.background = 'var(--color-fill-tertiary)'
                }}
                onMouseLeave={(e) => {
                  if (!on) e.currentTarget.style.background = 'transparent'
                }}
              >
                <span style={{ position: 'relative', flex: 'none', marginTop: 1 }}>
                  <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
                    <Icon name="robot" size={13} />
                  </Avatar>
                  <span
                    style={{
                      position: 'absolute',
                      right: -1,
                      bottom: -1,
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: statusDot(a.status),
                      border: '2px solid var(--color-bg-elevated)',
                    }}
                  />
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>{a.name}</span>
                    {on ? <Icon name="check" size={12} style={{ color: 'var(--color-primary)' }} /> : null}
                    <span style={{ flex: 1 }} />
                    <ModelBadge a={a} size="row" />
                  </span>
                  <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 1 }}>{a.persona}</span>
                  <span style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                    {/* 미반영 초안(스펙 078): 어느 에이전트가 미활성 편집을 안고 있는지 피커에서 구분. */}
                    {hasDraft(a) ? <Tag color="gold">초안</Tag> : null}
                    {a.source === 'ui' && a.exposed && a.exposed.a2a ? <Tag color="green">A2A</Tag> : null}
                    {a.mcps.map((m) => (
                      <Tag key={m} color="cyan">
                        {m}
                      </Tag>
                    ))}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

/* 세션 이어가기 피커(스펙 055) — 활성 에이전트의 과거 세션을 골라 대화를 복원한다.
   왜 필요한가: 위험 도구(delete_record) 승인하러 다른 뷰로 갔다 오면 Playground 메모리
   상태가 소실된다. 백엔드는 세션·메시지를 영속하므로(승인 시 resume_approval이 원 세션에
   최종 답변까지 영속) 여기서 골라 다시 불러오면 이어서 대화할 수 있다.
   드롭다운 열 때마다 onReload로 최신 목록을 받아 '방금 승인하고 돌아온' 세션도 즉시 보인다. */
const SESSION_STATUS_LABEL: Record<string, string> = {
  active: '활성', running: '실행중', awaiting: '승인대기', draining: '정리중',
  idle: '유휴', error: '오류', completed: '완료',
}
function shortSid(id: string) {
  // sess-ab12cd → sess-ab12cd 그대로 짧음. 더 길면 끝 6자만.
  return id.length <= 14 ? id : '…' + id.slice(-12)
}
function SessionCombo({
  sessions,
  currentId,
  loading,
  onPick,
  onNew,
  onReload,
}: {
  sessions: Session[]
  currentId?: string
  loading: boolean
  onPick: (sid: string) => void
  onNew: () => void
  onReload: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  const toggle = () => {
    setOpen((o) => {
      if (!o) onReload() // 열 때마다 최신 목록(승인 후 복귀 세션 즉시 반영)
      return !o
    })
  }
  // 칩 라벨: 사람이 알아볼 수 있게 현재 세션의 preview(첫 메시지) 우선, 없으면 해시 단축형.
  const current = currentId ? sessions.find((s) => s.id === currentId) : undefined
  const label = current?.preview || (currentId ? shortSid(currentId) : '새 세션')
  const labelIsPreview = !!current?.preview
  return (
    <div ref={ref} style={{ position: 'relative', minWidth: 0, flex: 'none' }}>
      <button
        onClick={toggle}
        title="세션 — 과거 대화를 골라 이어서 대화합니다."
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
          borderRadius: 8, border: '1px solid ' + (open ? 'var(--color-primary-border)' : 'var(--color-border)'),
          background: open ? 'var(--color-primary-bg)' : 'var(--color-bg-container)',
          cursor: 'pointer', font: 'inherit', maxWidth: 240, minWidth: 0, transition: 'all .2s',
        }}
      >
        <Icon name="comment" size={13} style={{ color: 'var(--color-text-tertiary)', flex: 'none' }} />
        <span
          style={{
            fontSize: 13, fontFamily: labelIsPreview ? undefined : (currentId ? 'var(--font-family-code)' : undefined),
            color: currentId ? 'var(--color-text)' : 'var(--color-text-tertiary)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {label}
        </span>
        <Icon
          name="down" size={11}
          style={{ color: 'var(--color-text-tertiary)', flex: 'none', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}
        />
      </button>
      {open ? (
        <div
          style={{
            position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 1050, width: 300,
            background: 'var(--color-bg-elevated)', borderRadius: 12, boxShadow: 'var(--box-shadow)',
            padding: 6, maxHeight: 420, overflow: 'auto',
          }}
        >
          <button
            onClick={() => { onNew(); setOpen(false) }}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px',
              borderRadius: 8, border: 'none', cursor: 'pointer', font: 'inherit', textAlign: 'left',
              background: currentId ? 'transparent' : 'var(--color-primary-bg)',
            }}
          >
            <Icon name="plus" size={13} style={{ color: 'var(--color-primary)' }} />
            <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-heading)' }}>새 세션</span>
          </button>
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '6px 10px 4px' }}>
            최근 세션 {loading ? '불러오는 중…' : sessions.length}
          </div>
          {!loading && sessions.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', padding: '4px 10px 8px' }}>
              아직 세션이 없습니다.
            </div>
          ) : null}
          {sessions.map((s) => {
            const on = s.id === currentId
            // 주 라벨: 첫 메시지 preview(사람이 알아봄). preview가 없으면(메시지 없는/오래된
            // 시드 세션) '(빈 세션)' 같은 오해 대신 해시를 정직하게 보여준다 — 14턴짜리가
            // "빈 세션"으로 보이던 문제. preview 없을 때만 해시가 주 라벨이라 메타에서 중복 제거.
            const hasPreview = !!s.preview
            const time = fmtTime(s.lastActivity)
            return (
              <button
                key={s.id}
                onClick={() => { onPick(s.id); setOpen(false) }}
                style={{
                  width: '100%', display: 'flex', flexDirection: 'column', gap: 3, padding: '9px 10px',
                  borderRadius: 8, border: 'none', cursor: 'pointer', font: 'inherit', textAlign: 'left',
                  background: on ? 'var(--color-primary-bg)' : 'transparent', transition: 'background .15s',
                }}
                onMouseEnter={(e) => { if (!on) e.currentTarget.style.background = 'var(--color-fill-tertiary)' }}
                onMouseLeave={(e) => { if (!on) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      fontSize: 13, fontWeight: 500,
                      fontFamily: hasPreview ? undefined : 'var(--font-family-code)',
                      color: 'var(--color-text-heading)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0,
                    }}
                  >
                    {hasPreview ? s.preview : shortSid(s.id)}
                  </span>
                  {on ? <Icon name="check" size={12} style={{ color: 'var(--color-primary)', flex: 'none' }} /> : null}
                  <span style={{ flex: 1 }} />
                  {s.status === 'awaiting' ? <Tag color="gold">{SESSION_STATUS_LABEL.awaiting}</Tag> : null}
                </span>
                {/* 부 메타: (preview 있으면) 해시 단축형 + 턴/상태/시각. preview 없으면 해시는
                    이미 주 라벨이라 생략. */}
                <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
                  {hasPreview ? (
                    <>
                      <span style={{ fontFamily: 'var(--font-family-code)' }}>{shortSid(s.id)}</span>
                      {' · '}
                    </>
                  ) : null}
                  {s.turns}턴 · {SESSION_STATUS_LABEL[s.status] ?? s.status}
                  {time ? ' · ' + time : ''}
                </span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

function ChatHeader({
  agent,
  agents,
  onSwitchAgent,
  sessions,
  currentSessionId,
  sessionsLoading,
  onPickSession,
  onReloadSessions,
  canResetConversation,
  onResetConversation,
  showPrompt,
  onTogglePrompt,
  effectiveSystemPrompt,
  inspectorOpen,
  onToggleInspector,
  overrideActive,
  onToggleOverrides,
}: {
  agent: Agent
  agents: Agent[]
  onSwitchAgent: (id: string) => void
  sessions: Session[]
  currentSessionId?: string
  sessionsLoading: boolean
  onPickSession: (sid: string) => void
  onReloadSessions: () => void
  canResetConversation: boolean
  onResetConversation: () => void
  showPrompt: boolean
  onTogglePrompt: () => void
  effectiveSystemPrompt?: string
  inspectorOpen: boolean
  onToggleInspector: () => void
  overrideActive: boolean
  onToggleOverrides: () => void
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  // 좁은 데스크톱(lg 미만): 사이드바(232px) 탓에 헤더 가로가 빠듯해 AgentCombo가 아바타만 남게
  // 쭈그러든다. md만으로는 너무 늦으니 lg부터 컨트롤을 축소(A2A 숨김 + 버튼 아이콘만)해 공간 확보.
  // 또한 인스펙터가 나란히(side-by-side) 열려 있으면 채팅 컬럼이 384px만큼 더 줄어 라벨이 인스펙터로
  // 흘러넘친다(#9). 그래서 인스펙터가 열린 동안엔 폭과 무관하게 항상 compact로 둔다.
  const compact = !screens.lg || inspectorOpen
  return (
    <div style={{ flex: 'none', borderBottom: '1px solid var(--color-border-secondary)', background: 'var(--color-bg-container)' }}>
      {/* compact: 버튼 아이콘만(라벨 제거) + A2A 배지 숨김 — 한 줄에 안 들어가 겹치던 문제. */}
      <div style={{ height: 64, display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 12, padding: isMobile ? '0 12px' : '0 20px' }}>
        <AgentCombo agent={agent} agents={agents} onSwitch={onSwitchAgent} />
        {/* 세션 이어가기(스펙 055): 에이전트 피커 옆에서 과거 세션을 골라 복원. */}
        <SessionCombo
          sessions={sessions}
          currentId={currentSessionId}
          loading={sessionsLoading}
          onPick={onPickSession}
          onNew={onResetConversation}
          onReload={onReloadSessions}
        />
        <div style={{ flex: 1 }} />
        {/* mem0 user_id 축은 서버가 로그인 유저에서 도출한다(스펙 032) — 수동 userId 입력은 제거.
            "새 대화"는 userId 잠금에서 분리된 일반 리셋: 진행 중인 대화가 있을 때만 노출. */}
        {canResetConversation && (
          <Button
            size="small"
            icon={<Icon name="plus" />}
            onClick={onResetConversation}
            title="새 대화 — 현재 대화를 비우고 처음부터 시작합니다."
          >
            {compact ? null : '새 대화'}
          </Button>
        )}
        {/* 미반영 초안 안내(스펙 078): 편집은 초안에 저장되고 Playground는 활성 버전을 실행 —
            초안이 있으면 "수정이 안 보임"의 원인을 배지로 알린다. compact에서도 아이콘만 유지. */}
        {hasDraft(agent) && <DraftBadge compact={compact} />}
        {!compact && <ExposeBadges agent={agent} />}
        <Button
          size="small"
          type={overrideActive ? 'primary' : 'default'}
          icon={<Icon name="experiment" />}
          onClick={onToggleOverrides}
          title={overrideActive ? '런타임 오버라이드 (적용 중)' : '런타임 오버라이드'}
        >
          {compact ? null : overrideActive ? '오버라이드 ✓' : '오버라이드'}
        </Button>
        <Button
          size="small"
          type={showPrompt ? 'primary' : 'default'}
          icon={<Icon name="file" />}
          onClick={onTogglePrompt}
          title="시스템 프롬프트"
        >
          {compact ? null : '시스템 프롬프트'}
        </Button>
        <Button
          size="small"
          type={inspectorOpen ? 'primary' : 'default'}
          icon={<Icon name="dashboard" />}
          onClick={onToggleInspector}
          title="인스펙터"
        >
          {compact ? null : '인스펙터'}
        </Button>
      </div>
      {showPrompt ? (
        <div style={{ padding: '0 20px 16px' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {(agent.memories || []).map((m) => (
              <Tag key={m} color="purple">
                {m}
              </Tag>
            ))}
            {agent.permissions.map((p) => (
              <Tag key={p} color="geekblue">
                {p}
              </Tag>
            ))}
            {agent.mcps.map((m) => (
              <Tag key={m} color="cyan">
                {m}
              </Tag>
            ))}
          </div>
          <pre
            style={{
              fontFamily: 'var(--font-family-code)',
              fontSize: 12,
              lineHeight: 1.6,
              color: 'var(--color-text)',
              background: 'var(--gray-2)',
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 8,
              padding: '12px 14px',
              margin: 0,
              whiteSpace: 'pre-wrap',
              maxHeight: 220,
              overflow: 'auto',
            }}
          >
            {effectiveSystemPrompt ?? agent.systemPrompt ?? ''}
          </pre>
        </div>
      ) : null}
    </div>
  )
}

function Chip({ icon, color, n, label }: { icon: string; color: string; n?: number; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--color-text-secondary)' }}>
      <Icon name={icon} size={12} style={{ color }} />
      {n != null ? n + ' ' : ''}
      {label}
    </span>
  )
}

function TraceChips({ trace, active, onClick }: { trace?: Trace; active: boolean; onClick: () => void }) {
  if (!trace) return null
  return (
    <div
      onClick={onClick}
      style={{
        display: 'inline-flex',
        gap: 10,
        alignItems: 'center',
        marginTop: 2,
        padding: '4px 10px',
        cursor: 'pointer',
        border: '1px solid ' + (active ? 'var(--color-primary-border)' : 'var(--color-border-secondary)'),
        background: active ? 'var(--color-primary-bg)' : 'var(--color-bg-container)',
        borderRadius: 100,
        transition: 'all .2s',
      }}
    >
      <Chip icon="bulb" color="var(--purple-6)" n={trace.memories.length} label="mem" />
      <Chip icon="thunderbolt" color="var(--cyan-7)" n={trace.mcp.length} label="mcp" />
      <Chip icon="clock-circle" color="var(--color-text-tertiary)" label={(trace.latencyMs / 1000).toFixed(2) + 's'} />
      <span style={{ fontSize: 12, color: 'var(--color-primary)', fontWeight: 500 }}>인스펙터{active ? ' ✓' : ''}</span>
    </div>
  )
}

export function DebugChat({
  agent,
  agents,
  onSwitchAgent,
  sessions,
  currentSessionId,
  sessionsLoading,
  onPickSession,
  onReloadSessions,
  messages,
  streaming,
  selectedTurn,
  onSelectTurn,
  onSend,
  onStop,
  canResetConversation,
  onResetConversation,
  showPrompt,
  onTogglePrompt,
  effectiveSystemPrompt,
  inspectorOpen,
  onToggleInspector,
  overrideActive,
  onToggleOverrides,
}: DebugChatProps) {
  const scroller = useRef<HTMLDivElement>(null)
  // Sender는 submit 시 스스로 입력을 비우지 않는다(@ant-design/x 2.8 — triggerSend가
  // onSubmit만 호출, clear는 클리어 버튼에서만). 그래서 controlled로 두고 직접 비운다.
  const [draft, setDraft] = useState('')
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [messages, streaming, showPrompt])

  // 터미널 콘솔식 입력 히스토리 재호출(스펙 091). 정책은 inputHistory.ts 순수 함수가 쥐고,
  // 여기선 caret 판정·DOM 부수효과만. history = 현재 대화에서 *내가 보낸* 입력(연속중복 접음).
  const senderRef = useRef<GetRef<typeof Sender>>(null)
  const histRef = useRef<HistState>(INITIAL_HIST)
  // 재호출마다 ++ 하는 단조 카운터. caret 이동 effect의 의존을 draft가 아니라 이걸로 둬야,
  // 재호출 값이 현재 입력과 *우연히 같을 때*(예: 최신 입력이 이미 입력창에 있음)도 발화한다
  // (setDraft가 no-op이면 draft만 보는 effect는 안 돔 — codex 적대 리뷰 P2).
  const [recallSeq, setRecallSeq] = useState(0)
  const history = useMemo(
    () => dedupeConsecutive(messages.filter((m) => m.role === 'me').map((m) => m.text)),
    [messages],
  )

  // inputElement는 textarea지만 타입이 union(HTMLElement 포함)이라 caret API 접근 시 좁힌다.
  const inputTextarea = (): HTMLTextAreaElement | null =>
    (senderRef.current?.inputElement as HTMLTextAreaElement | undefined) ?? null

  // 재호출 시 caret을 끝으로(편집이 자연스럽게 이어지도록). recallSeq에만 의존하므로 사용자
  // 타이핑(draft만 변함)엔 발화하지 않고, 마운트(seq 0)도 건너뛴다.
  useLayoutEffect(() => {
    if (recallSeq === 0) return
    const ta = inputTextarea()
    if (ta) ta.setSelectionRange(ta.value.length, ta.value.length)
  }, [recallSeq])

  // Sender 키 핸들러: 비탐색 진입은 caret 절대 맨앞(ArrowUp)에서만, 탐색 중엔 caret 무관.
  const onHistKey = (e: React.KeyboardEvent): void | false => {
    if (e.nativeEvent.isComposing) return // IME 조합 중엔 양보(조합 깨짐 방지)
    const ta = inputTextarea()
    const navigating = histRef.current.idx !== -1
    if (e.key === 'ArrowUp') {
      if (!navigating && !(ta && ta.selectionStart === 0 && ta.selectionEnd === 0)) return
      const r = recallOlder(histRef.current, history, draft)
      if (!r.handled) return
      histRef.current = r.state
      setDraft(r.value)
      setRecallSeq((n) => n + 1)
      e.preventDefault()
      return false
    }
    if (e.key === 'ArrowDown') {
      if (!navigating) return
      const r = recallNewer(histRef.current, history)
      if (!r.handled) return
      histRef.current = r.state
      setDraft(r.value)
      setRecallSeq((n) => n + 1)
      e.preventDefault()
      return false
    }
  }

  if (!agent) {
    return (
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--color-text-tertiary)',
          background: 'var(--color-bg-container)',
        }}
      >
        에이전트를 불러오는 중…
      </div>
    )
  }

  const empty = messages.length === 0
  // 세션을 골랐는데(currentSessionId 있음) 메시지가 0개면 = 불러올 히스토리가 없는 세션
  // (메시지 영속 전이거나 시드/레거시 세션). 새 대화의 프롬프트 카드와 똑같이 보이면 "선택해도
  // 아무것도 안 나온다"고 오해되므로(사용자 보고) 명시적 빈 상태를 띄운다.
  const pickedButEmpty = empty && !!currentSessionId && !streaming

  const promptItems = [
    { key: '1', icon: <Icon name="bulb" style={{ color: 'var(--purple-6)' }} />, label: '메모리 회상 테스트', description: '지난번에 무슨 얘기를 나눴지?' },
    { key: '2', icon: <Icon name="thunderbolt" style={{ color: 'var(--cyan-7)' }} />, label: '도구 호출 유도', description: '스트리밍 UI 최신 동향을 검색해줘' },
    { key: '3', icon: <Icon name="file" style={{ color: 'var(--color-primary)' }} />, label: '시스템 프롬프트 확인', description: '너의 역할과 규칙을 한 줄로 요약해줘' },
  ]

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--color-bg-container)' }}>
      <ChatHeader
        agent={agent}
        agents={agents}
        onSwitchAgent={onSwitchAgent}
        sessions={sessions}
        currentSessionId={currentSessionId}
        sessionsLoading={sessionsLoading}
        onPickSession={onPickSession}
        onReloadSessions={onReloadSessions}
        canResetConversation={canResetConversation}
        onResetConversation={onResetConversation}
        showPrompt={showPrompt}
        onTogglePrompt={onTogglePrompt}
        effectiveSystemPrompt={effectiveSystemPrompt}
        inspectorOpen={inspectorOpen}
        onToggleInspector={onToggleInspector}
        overrideActive={overrideActive}
        onToggleOverrides={onToggleOverrides}
      />

      <div ref={scroller} style={{ flex: 1, overflowY: 'auto' }}>
        {pickedButEmpty ? (
          <div
            style={{
              maxWidth: 520, margin: '0 auto', width: '100%', padding: '12vh 24px 0',
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, textAlign: 'center',
            }}
          >
            <Icon name="comment" size={28} style={{ color: 'var(--color-text-quaternary)' }} />
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-secondary)' }}>
              이 세션에는 불러올 메시지가 없습니다.
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', lineHeight: 1.7 }}>
              메시지가 영속되기 전이거나 이전 버전에서 생성된 세션입니다.
              <br />
              아래에 입력하면 이 세션({shortSid(currentSessionId!)})에 이어서 대화가 쌓입니다.
            </div>
          </div>
        ) : empty ? (
          <div style={{ maxWidth: 680, margin: '0 auto', width: '100%', padding: '7vh 24px 0', display: 'flex', flexDirection: 'column', gap: 24 }}>
            <Prompts
              title="디버그 프롬프트 체험"
              wrap
              items={promptItems}
              onItemClick={(info) => onSend((info.data as { description?: string }).description ?? '')}
            />
          </div>
        ) : (
          <div style={{ maxWidth: 680, margin: '0 auto', padding: 24, width: '100%', boxSizing: 'border-box' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {messages.map((m, i) => {
                if (m.role === 'ai') {
                  const isLast = i === messages.length - 1
                  const isStreaming = streaming && isLast
                  const footer: ReactNode =
                    m.trace && !isStreaming ? (
                      <TraceChips trace={m.trace} active={selectedTurn === i} onClick={() => onSelectTurn(i)} />
                    ) : null
                  return (
                    <Bubble
                      key={i}
                      placement="start"
                      avatar={agentAvatar}
                      header={agent.name}
                      content={m.text}
                      // 평문 대신 markdown/JSON 렌더(스펙 088). contentRender는 full content를
                      // 받고(부분 아님) 노드 반환 시 typing 애니메이션은 비적용 — 토큰마다 m.text가
                      // 커지며 재렌더돼 점진 markdown이 일어난다. 형식 추론은 스트림 완료에서만 도므로
                      // 스트리밍 여부를 넘긴다(부분 버퍼로 JSON 트리 깜빡임 방지).
                      contentRender={(t) => <MessageContent text={t} streaming={isStreaming} />}
                      // 첫 토큰 도착 전(빈 content)에는 typing이 보일 게 없어 말풍선이 멈춘 듯
                      // 보인다 — 그 구간엔 loading 점 애니메이션을 띄운다(사용자 피드백).
                      loading={isStreaming && !m.text}
                      typing={isStreaming}
                      footer={footer}
                    />
                  )
                }
                return <Bubble key={i} placement="end" variant="filled" avatar={userAvatar} content={m.text} />
              })}
            </div>
          </div>
        )}
      </div>

      <div style={{ flex: 'none', padding: '8px 24px 18px' }}>
        <div style={{ maxWidth: 680, margin: '0 auto' }}>
          <Sender
            ref={senderRef}
            value={draft}
            onChange={(v) => {
              // 사용자 편집은 탐색 종료. (우리 재호출은 setDraft 직접 호출이라 onChange 미발화 →
              // 여기 들어오는 건 실제 타이핑·붙여넣기뿐.)
              histRef.current = resetHist()
              setDraft(v)
            }}
            onKeyDown={onHistKey}
            placeholder={`${agent.name}에게 메시지…`}
            loading={streaming}
            onSubmit={(text) => {
              histRef.current = resetHist()
              setDraft('')
              onSend(text)
            }}
            onCancel={onStop}
            prefix={<Button type="text" icon={<Icon name="paper-clip" />} />}
            footer={() => (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>LangGraph 에이전트 실행 · 턴마다 트레이스 기록 · ↑ 이전 입력</span>
            )}
          />
        </div>
      </div>
    </div>
  )
}
