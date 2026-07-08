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
import { Avatar, Button, Tag, Grid, Tooltip, Segmented, Select, Input, Dropdown, Card, Popover } from 'antd'
import { Icon } from '../admin/icons'
import { fmtTime } from '../admin/format'
import { MessageContent } from './MessageContent'
import { getA2ASkills, type A2ASkill, type ChatFormFrame, type MessageFeedback } from '../api'
import { FeedbackButtons } from '../FeedbackButtons'
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
  // antd Tag로 통일(스펙 204) — header=Tag(색 프리셋), row=경량 텍스트(테두리 없는 bordered=false Tag).
  const chip = header ? (
    <Tag
      color={b.remote ? 'default' : 'blue'}
      style={{ fontFamily: 'var(--font-family-code)', fontWeight: 600, marginInlineEnd: 6 }}
    >
      {b.text}
    </Tag>
  ) : (
    <Tag bordered={false} style={{ fontFamily: 'var(--font-family-code)', fontSize: 11, color: 'var(--color-text-tertiary)', background: 'transparent', paddingInline: 0, marginInlineEnd: 0 }}>
      {b.text}
    </Tag>
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
  // 스펙 209 P1.5 — assistant 응답 피드백(👍/👎) 변경을 상위(convos)로 전파(낙관 갱신).
  onFeedbackChange?: (msgIndex: number, fb: MessageFeedback | null) => void
  streaming: boolean
  awaitingApproval: boolean // 승인 대기 중(스펙 179 P3) — 입력 차단(그래프가 그 턴에서 멈춤)
  approvalCanResolve?: boolean // 인라인 승인(스펙 180) — 현재 사용자가 이 승인을 그 자리서 처리 가능
  approvalKind?: 'self' | 'admin' // 승인 종류(라벨용)
  onResolveApproval?: (decision: 'approve' | 'reject') => Promise<void> | void
  // 산출물형 폼(스펙 188) — 폼 프레임이 오면 입력 위에 렌더. 제출은 onSubmitForm, 텍스트 입력도
  // 계속 열려 있다(이중 입력 일급 — 승인 대기와 달리 입력을 잠그지 않는다).
  pendingForm?: { formId: string; form: ChatFormFrame } | null
  onSubmitForm?: (values: Record<string, string>) => Promise<void> | void
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
  a2aMode: boolean
  onToggleA2A: (v: boolean) => void
  pinnedVersion?: string // 버전 미리보기(스펙 243) — undefined=활성
  onPinVersion?: (v?: string) => void
}

// A2A 노출 판정(스펙 154·155): source∈{ui,code} + exposed.a2a. 154가 code 중계 공개를 허용해
// 게이트를 넓혔다(이전엔 ui만 — code 노출 에이전트를 놓치던 낡은 게이트). external은 봉인(152).
export function isA2AExposed(agent: Agent): boolean {
  return (agent.source === 'ui' || agent.source === 'code') && !!agent.exposed?.a2a
}


/* Rich agent picker — replaces the left rail. Shows avatar, persona, model and
   MCP chips per agent in a dropdown. */
function AgentCombo({
  agent,
  agents,
  onSwitch,
  fullWidth = false, // 모바일(스펙 132 v2): 한 줄을 통째로 — 이름·모델을 온전히 표시(잘림 최소화)
}: {
  agent: Agent
  agents: Agent[]
  onSwitch: (id: string) => void
  fullWidth?: boolean
}) {
  const [open, setOpen] = useState(false)
  // 에이전트 조회(스펙 248) — 검색(이름·모델·페르소나 부분일치) + 최근 사용 순(localStorage).
  const [q, setQ] = useState('')
  const recent: string[] = (() => {
    try { return JSON.parse(localStorage.getItem('pg_recent_agents') || '[]') } catch { return [] }
  })()
  const rank = (id: string) => { const i = recent.indexOf(id); return i === -1 ? Infinity : i }
  const shown = agents
    .filter((a) => {
      const needle = q.trim().toLowerCase()
      if (!needle) return true
      return [a.name, a.model, a.persona].some((f) => (f || '').toLowerCase().includes(needle))
    })
    .slice()
    .sort((x, y) => rank(x.id) - rank(y.id) || (x.name || '').localeCompare(y.name || ''))
  // antd Dropdown으로 통일(스펙 204) — 바깥클릭·포지셔닝·z-index·접근성을 antd에 이양(수제
  // mousedown 리스너 제거). 패널 내용(리치 행)은 popupRender로 그대로.
  return (
    <Dropdown
      open={open}
      onOpenChange={(o) => { setOpen(o); if (o) setQ('') }}
      trigger={['click']}
      popupRender={() => (
        <div
          style={{
            width: 'min(360px, calc(100vw - 24px))',
            background: 'var(--color-bg-elevated)',
            borderRadius: 12,
            boxShadow: 'var(--box-shadow)',
            padding: 6,
            maxHeight: 420,
            overflow: 'auto',
          }}
        >
          <Input
            autoFocus
            allowClear
            size="small"
            placeholder="이름·모델·페르소나 검색"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ margin: '4px 4px 6px', width: 'calc(100% - 8px)' }}
          />
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '2px 10px 4px' }}>
            에이전트 {shown.length}{q ? ` / ${agents.length}` : ''}
          </div>
          {shown.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--color-text-quaternary)', padding: '8px 10px' }}>검색 결과 없음</div>
          )}
          {shown.map((a) => {
            const on = a.id === agent.id
            return (
              <button
                key={a.id}
                onClick={() => {
                  // 최근 사용 기록(스펙 248) — 다음 조회 시 최근 순 정렬.
                  try {
                    const next = [a.id, ...recent.filter((id) => id !== a.id)].slice(0, 8)
                    localStorage.setItem('pg_recent_agents', JSON.stringify(next))
                  } catch { /* localStorage 불가 환경 무시 */ }
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
                    {recent.includes(a.id) && !q ? <Tag bordered={false} style={{ background: 'var(--color-fill-tertiary)', fontSize: 11 }}>최근</Tag> : null}
                    {hasDraft(a) ? <Tag color="gold">초안</Tag> : null}
                    {isA2AExposed(a) ? <Tag color="green">A2A</Tag> : null}
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
      )}
    >
      <div style={{ minWidth: 0, width: fullWidth ? '100%' : undefined }}>
      <button
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
          maxWidth: fullWidth ? '100%' : 360,
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
        <span style={{ minWidth: 0, textAlign: 'left', flex: fullWidth ? 1 : undefined }}>
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
      </div>
    </Dropdown>
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
  fullWidth = false, // 모바일(스펙 132 v2): 한 줄 통째 — 세션 미리보기를 온전히 표시
}: {
  sessions: Session[]
  currentId?: string
  loading: boolean
  onPick: (sid: string) => void
  onNew: () => void
  onReload: () => void
  fullWidth?: boolean
}) {
  const [open, setOpen] = useState(false)
  // 칩 라벨: 사람이 알아볼 수 있게 현재 세션의 preview(첫 메시지) 우선, 없으면 해시 단축형.
  const current = currentId ? sessions.find((s) => s.id === currentId) : undefined
  const label = current?.preview || (currentId ? shortSid(currentId) : '새 세션')
  const labelIsPreview = !!current?.preview
  // antd Dropdown으로 통일(스펙 204) — 열 때 onReload(최신 세션 반영)는 onOpenChange에서.
  return (
    <Dropdown
      open={open}
      onOpenChange={(o) => {
        if (o) onReload() // 열 때마다 최신 목록(승인 후 복귀 세션 즉시 반영)
        setOpen(o)
      }}
      trigger={['click']}
      popupRender={() => (
        <div
          style={{
            width: 'min(300px, calc(100vw - 24px))',
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
      )}
    >
      <div style={{ minWidth: 0, flex: 'none', width: fullWidth ? '100%' : undefined }}>
      <button
        title="세션 — 과거 대화를 골라 이어서 대화합니다."
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
          borderRadius: 8, border: '1px solid ' + (open ? 'var(--color-primary-border)' : 'var(--color-border)'),
          background: open ? 'var(--color-primary-bg)' : 'var(--color-bg-container)',
          cursor: 'pointer', font: 'inherit', maxWidth: fullWidth ? '100%' : 240, width: fullWidth ? '100%' : undefined,
          minWidth: 0, transition: 'all .2s',
        }}
      >
        <Icon name="comment" size={13} style={{ color: 'var(--color-text-tertiary)', flex: 'none' }} />
        <span
          style={{
            fontSize: 13, fontFamily: labelIsPreview ? undefined : (currentId ? 'var(--font-family-code)' : undefined),
            color: currentId ? 'var(--color-text)' : 'var(--color-text-tertiary)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: fullWidth ? 1 : undefined,
            textAlign: 'left',
          }}
        >
          {label}
        </span>
        <Icon
          name="down" size={11}
          style={{ color: 'var(--color-text-tertiary)', flex: 'none', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}
        />
      </button>
      </div>
    </Dropdown>
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
  a2aMode,
  onToggleA2A,
  pinnedVersion,
  onPinVersion,
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
  pinnedVersion?: string // 버전 미리보기(스펙 243) — undefined=활성(서빙) 버전
  onPinVersion?: (v?: string) => void
  overrideActive: boolean
  onToggleOverrides: () => void
  a2aMode: boolean
  onToggleA2A: (v: boolean) => void
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  // A2A 광고 스킬(스펙 157) — A2A 모드일 때 노출 에이전트의 카드가 외부에 광고하는 능력(chat+mcp+
  // delegate+rag)을 fetch해 칩으로 표시. 외부 소비자가 보는 것과 동일한 걸 확인하는 테스트 수단.
  const [a2aSkills, setA2aSkills] = useState<A2ASkill[]>([])
  useEffect(() => {
    if (!a2aMode || !isA2AExposed(agent)) {
      setA2aSkills([])
      return
    }
    let live = true
    getA2ASkills(agent.id)
      .then((sk) => { if (live) setA2aSkills(sk) })
      .catch(() => { if (live) setA2aSkills([]) })
    return () => { live = false }
    // 노출 상태·능력 시그니처가 바뀌면 재fetch(codex Low): 같은 agent.id라도 un-expose/능력 변경 시
    // stale 칩을 남기지 않는다. exposed 꺼지면 위 가드가 [] 처리, 능력 바뀌면 카드 재조회.
  }, [a2aMode, agent.id, agent.exposed?.a2a, JSON.stringify(agent.mcps), JSON.stringify(agent.capabilities)])
  // 좁은 데스크톱(lg 미만): 사이드바(232px) 탓에 헤더 가로가 빠듯해 AgentCombo가 아바타만 남게
  // 쭈그러든다. md만으로는 너무 늦으니 lg부터 컨트롤을 축소(A2A 숨김 + 버튼 아이콘만)해 공간 확보.
  // 또한 인스펙터가 나란히(side-by-side) 열려 있으면 채팅 컬럼이 384px만큼 더 줄어 라벨이 인스펙터로
  // 흘러넘친다(#9). 그래서 인스펙터가 열린 동안엔 폭과 무관하게 항상 compact로 둔다.
  // 모바일(스펙 132 v2)은 여러 줄 스택이라 라벨 공간이 충분 — compact(라벨 제거)는 **비모바일**
  // 좁은 데스크톱/인스펙터 병행에만 적용. 사용자 피드백: 아이콘만으로는 버튼 뜻을 알 수 없음.
  const compact = !isMobile && (!screens.lg || inspectorOpen)
  return (
    <div style={{ flex: 'none', borderBottom: '1px solid var(--color-border-secondary)', background: 'var(--color-bg-container)' }}>
      {/* compact: 버튼 아이콘만(라벨 제거) + A2A 배지 숨김 — 한 줄에 안 들어가 겹치던 문제. */}
      {/* 모바일(스펙 132 v2 — 사용자 피드백): 아이콘만으로는 무슨 에이전트/세션인지 알 수 없다 →
          **여러 줄 스택 + 온전한 텍스트**(1줄 에이전트, 2줄 세션, 3줄 도구 라벨·줄바꿈 허용). */}
      <div
        style={
          isMobile
            ? { display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: 8, padding: '10px 12px' }
            : { height: 64, display: 'flex', alignItems: 'center', gap: 12, padding: '0 20px' }
        }
      >
        <AgentCombo agent={agent} agents={agents} onSwitch={onSwitchAgent} fullWidth={isMobile} />
        {/* 신호 배지(스펙 247) — 기본과 다른 상태만 헤더에 표시(미리보기·오버라이드). 설정 자체는
            "대화 설정" 팝오버로 가림(집중 모델: 헤더=에이전트+신호만). */}
        {pinnedVersion && (
          <Tag color="orange" style={{ margin: 0, flexShrink: 0 }}>미리보기 {pinnedVersion}</Tag>
        )}
        {overrideActive && (
          <Tag color="blue" style={{ margin: 0, flexShrink: 0, cursor: 'pointer' }} onClick={onToggleOverrides}>오버라이드 ✓</Tag>
        )}
        {a2aMode && <Tag color="green" style={{ margin: 0, flexShrink: 0 }}>A2A 경유</Tag>}
        {!isMobile && <div style={{ flex: 1 }} />}
        {/* 도구 줄 — 모바일은 라벨 포함·줄바꿈 허용(flexWrap). */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
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
        {/* 미반영 초안 안내(스펙 078): 신호 배지 — 헤더 유지. */}
        {hasDraft(agent) && <DraftBadge compact={compact} />}
        {/* 대화 설정(스펙 247) — 집중 모델: 설정류 6종(버전·세션·A2A 경유·시스템 프롬프트·오버라이드·
            인스펙터)을 한 입구 뒤로. 헤더 상시 요소=에이전트·신호 배지·새 대화·이 버튼. */}
        <Popover
          trigger="click"
          placement="bottomRight"
          content={
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: 260 }}>
              {agent.source === 'ui' && (agent.versions?.length ?? 0) > 0 && agent.can_manage !== false && onPinVersion && (
                <div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>버전 (미리보기)</div>
                  <Select
                    size="small"
                    style={{ width: '100%' }}
                    value={pinnedVersion ?? '__active__'}
                    onChange={(v) => onPinVersion(v === '__active__' ? undefined : v)}
                    options={[
                      { value: '__active__', label: `활성${agent.activeVersion ? ` (${agent.activeVersion})` : ''}` },
                      ...(agent.versions ?? [])
                        .filter((v) => v.status !== 'active')
                        .map((v) => ({
                          value: v.version,
                          label: `${v.version} · ${v.status === 'draft' ? '초안' : '보관'}`,
                        })),
                    ]}
                  />
                </div>
              )}
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>대화 이어가기</div>
                <SessionCombo
                  sessions={sessions}
                  currentId={currentSessionId}
                  loading={sessionsLoading}
                  onPick={onPickSession}
                  onNew={onResetConversation}
                  onReload={onReloadSessions}
                  fullWidth
                />
              </div>
              {isA2AExposed(agent) && (
                <div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>실행 경로</div>
                  <Tooltip title={a2aMode ? 'A2A 경유 테스트 — 단발 메시지(세션·trace·오버라이드 미전달)' : '직접 실행(/chat)'}>
                    <Segmented
                      size="small"
                      block
                      value={a2aMode ? 'a2a' : 'direct'}
                      onChange={(v) => onToggleA2A(v === 'a2a')}
                      options={[
                        { label: '직접', value: 'direct' },
                        { label: 'A2A 경유', value: 'a2a' },
                      ]}
                    />
                  </Tooltip>
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <Button size="small" type={overrideActive ? 'primary' : 'default'} icon={<Icon name="experiment" />} onClick={onToggleOverrides} style={{ justifyContent: 'flex-start' }}>
                  {overrideActive ? '오버라이드 (적용 중)' : '오버라이드'}
                </Button>
                <Button size="small" type={showPrompt ? 'primary' : 'default'} icon={<Icon name="file" />} onClick={onTogglePrompt} style={{ justifyContent: 'flex-start' }}>
                  시스템 프롬프트
                </Button>
                <Button size="small" type={inspectorOpen ? 'primary' : 'default'} icon={<Icon name="dashboard" />} onClick={onToggleInspector} style={{ justifyContent: 'flex-start' }}>
                  인스펙터
                </Button>
              </div>
            </div>
          }
        >
          <Button size="small" icon={<Icon name="setting" />}>
            {compact ? null : '대화 설정'}
          </Button>
        </Popover>
        </div>
      </div>
      {/* A2A 모드 가시 힌트(스펙 155, codex 경계 #1): A2A 경유는 단발 호출이라 세션/히스토리/trace를
          안 넘긴다. 기존 세션을 이어보는 것처럼 보여도 이 턴은 우리 DB에 안 남는다(재로드 시 사라짐).
          툴팁은 hover-only라 부족 — 인라인 배너로 경계를 늘 보이게. */}
      {a2aMode && isA2AExposed(agent) ? (
        <div style={{ padding: '0 20px 10px' }}>
          <Tag color="green" style={{ whiteSpace: 'normal', height: 'auto', margin: 0 }}>
            A2A 경유 테스트 — 단발 호출입니다(세션·히스토리·trace 미저장 · 이 턴은 저장되지 않음).
          </Tag>
          {/* 광고 스킬(스펙 157) — 카드가 외부에 노출하는 능력. chat 외(mcp/delegate/rag)만 칩으로. */}
          {a2aSkills.filter((s) => s.id !== 'chat').length ? (
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>광고 스킬:</span>
              {a2aSkills
                .filter((s) => s.id !== 'chat')
                .map((s) => (
                  <Tooltip key={s.id} title={`${s.id} — ${s.description}`}>
                    <Tag
                      color={s.tags.includes('mcp') ? 'cyan' : s.tags.includes('delegate') ? 'geekblue' : s.tags.includes('rag') ? 'purple' : 'default'}
                      style={{ margin: 0 }}
                    >
                      {s.name}
                    </Tag>
                  </Tooltip>
                ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {showPrompt ? (
        <div style={{ padding: '0 20px 16px' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {(agent.memories || []).map((m) => (
              <Tag key={m} color="purple">
                {m}
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

/* 산출물형 폼 패널(스펙 188) — form 프레임을 antd 컨트롤로 렌더. 채팅 입력은 계속 열려 있어
   말로 답해도 된다(이중 입력 — 서버가 병합 후 재제시). formId가 바뀌면 key로 state 리셋. */
function InlineFormPanel({
  form,
  onSubmit,
  disabled,
}: {
  form: ChatFormFrame
  onSubmit: (values: Record<string, string>) => void
  disabled?: boolean
}) {
  const [vals, setVals] = useState<Record<string, string>>(() => ({ ...form.prefill }))
  const set = (k: string, v: string) => setVals((s) => ({ ...s, [k]: v }))
  const missing = form.fields.filter((f) => (f.required ?? true) && !vals[f.key])
  return (
    <Card
      size="small"
      style={{ maxWidth: 680, margin: '0 auto 8px', background: 'var(--gray-2)' }}
      styles={{ body: { display: 'flex', flexDirection: 'column', gap: 8 } }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-text-secondary)' }}>
        <Icon name="edit" size={14} />
        입력이 필요합니다 — 폼으로 고르거나 채팅으로 말씀하셔도 됩니다.
      </div>
      {form.note ? (
        <div style={{ fontSize: 12, color: 'var(--gold-7, #ad6800)' }}>{form.note}</div>
      ) : null}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {form.fields.map((f) => (
          <label
            key={f.key}
            style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--color-text-tertiary)', minWidth: 150 }}
          >
            {f.label || f.key}
            {f.candidates && f.candidates.length ? (
              <Select
                size="small"
                value={vals[f.key] || undefined}
                onChange={(v) => set(f.key, v)}
                options={f.candidates.map((c) => ({ value: c, label: c }))}
                placeholder="선택"
                style={{ minWidth: 150 }}
              />
            ) : (
              <Input size="small" value={vals[f.key] || ''} onChange={(e) => set(f.key, e.target.value)} />
            )}
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button size="small" type="primary" disabled={disabled || missing.length > 0} onClick={() => onSubmit(vals)}>
          제출
        </Button>
      </div>
    </Card>
  )
}

/* 산출물 카드(스펙 188) — 완성 payload를 그대로 표시. 임베드 시 JS 콜백이 받는 JSON과 동일. */
function ArtifactCard({ artifact }: { artifact: NonNullable<ChatMsg['artifact']> }) {
  return (
    <Card
      size="small"
      style={{ maxWidth: 560, fontSize: 13, background: 'var(--green-1, #f6ffed)', borderColor: 'var(--green-3, #b7eb8f)' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Tag color="green" style={{ margin: 0 }}>산출물</Tag>
        <code style={{ fontFamily: 'var(--font-family-code)' }}>{artifact.kind}</code>
      </div>
      <pre style={{ margin: 0, fontSize: 12, fontFamily: 'var(--font-family-code)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        {JSON.stringify(artifact.data, null, 2)}
      </pre>
      <div style={{ marginTop: 6, fontSize: 11, color: 'var(--color-text-tertiary)' }}>
        임베드 시 이 JSON이 호스트 페이지의 JS 콜백(ui-callback)으로 전달됩니다.
      </div>
    </Card>
  )
}

function TraceChips({ trace, active, onClick }: { trace?: Trace; active: boolean; onClick: () => void }) {
  if (!trace) return null
  return (
    <Tag
      onClick={onClick}
      color={active ? 'blue' : undefined}
      // antd Tag로 통일(스펙 204) — 컨테이너 pill만 교체, 칩 내용(도메인 요약)은 유지.
      style={{
        display: 'inline-flex',
        gap: 10,
        alignItems: 'center',
        marginTop: 2,
        padding: '4px 10px',
        cursor: 'pointer',
        borderRadius: 100,
        marginInlineEnd: 0,
      }}
    >
      <Chip icon="bulb" color="var(--purple-6)" n={trace.memories.length} label="mem" />
      {/* rag 칩(스펙 130) — 직접형(mcp server='rag') + 조율형(브로커 rag:*) 합산. mcp 칩은 rag를
          제외해 중복 계산 방지(인스펙터 섹션 카운트와 동일 기준). */}
      <Chip
        icon="search"
        color="var(--geekblue-6)"
        n={
          trace.mcp.filter((c) => c.server === 'rag').length +
          (trace.brokerCalls?.filter((b) => b.cap_id.startsWith('rag:')).length ?? 0)
        }
        label="rag"
      />
      <Chip icon="thunderbolt" color="var(--cyan-7)" n={trace.mcp.filter((c) => c.server !== 'rag').length} label="mcp" />
      <Chip icon="clock-circle" color="var(--color-text-tertiary)" label={(trace.latencyMs / 1000).toFixed(2) + 's'} />
      <span style={{ fontSize: 12, color: 'var(--color-primary)', fontWeight: 500 }}>인스펙터{active ? ' ✓' : ''}</span>
    </Tag>
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
  onFeedbackChange,
  messages,
  streaming,
  awaitingApproval,
  pendingForm = null,
  onSubmitForm,
  approvalCanResolve = false,
  approvalKind = 'admin',
  onResolveApproval,
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
  a2aMode,
  onToggleA2A,
  pinnedVersion,
  onPinVersion,
}: DebugChatProps) {
  const scroller = useRef<HTMLDivElement>(null)
  // Sender는 submit 시 스스로 입력을 비우지 않는다(@ant-design/x 2.8 — triggerSend가
  // onSubmit만 호출, clear는 클리어 버튼에서만). 그래서 controlled로 두고 직접 비운다.
  const [draft, setDraft] = useState('')
  const [resolving, setResolving] = useState<'approve' | 'reject' | null>(null) // 인라인 승인 처리 중(스펙 180)
  const doResolve = async (decision: 'approve' | 'reject') => {
    if (!onResolveApproval) return
    setResolving(decision)
    try {
      await onResolveApproval(decision)
    } finally {
      setResolving(null)
    }
  }
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

  // 에이전트 전환 시 입력 자동 포커스(스펙 248) — "찾고 → 바로 친다"의 마지막 반 박자.
  useEffect(() => {
    inputTextarea()?.focus()
  }, [agent?.id])

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

  // 추천 명령어(스펙 238) — 에이전트에 등록돼 있으면 그걸 카드로, 없으면 기본 3종 폴백(무회귀).
  // onItemClick이 description을 입력으로 보내므로 커스텀도 description에 실문장을 싣는다.
  const promptItems = agent?.suggestedPrompts?.length
    ? agent.suggestedPrompts.map((p, i) => ({
        key: `s${i}`,
        icon: <Icon name="bulb" style={{ color: 'var(--purple-6)' }} />,
        // label 생략(스펙 247) — 절단 제목+전문 설명이 같은 내용 중복으로 보이던 것(사용자 화면 진단).
        // onItemClick은 description을 전송하므로 전문만 싣는다.
        description: p,
      }))
    : [
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
        a2aMode={a2aMode}
        onToggleA2A={onToggleA2A}
        pinnedVersion={pinnedVersion}
        onPinVersion={onPinVersion}
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
            {/* 시작 조건 요약(스펙 248) — 어떤 조건으로 첫 메시지가 나가는지 시작 화면에서만 한 줄.
                기본과 다르면 헤더 신호 배지가 있으므로, 여기는 기본 상태까지 포함한 확인용. */}
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', textAlign: 'center' }}>
              {agent ? (
                <>
                  <strong style={{ color: 'var(--color-text-secondary)' }}>{agent.name}</strong>
                  {' · '}
                  {pinnedVersion ? `미리보기 ${pinnedVersion}` : `활성${agent.activeVersion ? ` ${agent.activeVersion}` : ''}`}
                  {' · '}
                  {overrideActive ? '오버라이드 적용 중' : '오버라이드 없음'}
                  {a2aMode ? ' · A2A 경유' : ''}
                  <span style={{ color: 'var(--color-text-quaternary)' }}> — 조건 변경은 우측 상단 “대화 설정”</span>
                </>
              ) : null}
            </div>
            <Prompts
              title={agent?.suggestedPrompts?.length ? '추천 명령어' : '디버그 프롬프트 체험'}
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
                    <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <Bubble
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
                      {/* 산출물 카드(스펙 188) — 완성 payload를 그 턴 아래 표시. */}
                      {m.artifact ? <ArtifactCard artifact={m.artifact} /> : null}
                      {/* 응답 피드백(스펙 209 P1.5) — 저장된 id가 있는 완료 응답에만(스트리밍 중 제외). */}
                      {m.id && currentSessionId && !isStreaming ? (
                        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                          <FeedbackButtons
                            sessionId={currentSessionId}
                            messageId={m.id}
                            value={m.feedback}
                            onChange={(fb) => onFeedbackChange?.(i, fb)}
                          />
                        </div>
                      ) : null}
                    </div>
                  )
                }
                return <Bubble key={i} placement="end" variant="filled" avatar={userAvatar} content={m.text} />
              })}
            </div>
          </div>
        )}
      </div>

      <div style={{ flex: 'none', padding: '8px 24px 18px' }}>
        {/* 인라인 승인 바(스펙 180) — 현재 사용자가 처리 가능한 승인 대기면 그 자리서 승인/거부.
            불가(일반 유저의 admin 승인 대기)면 바 없이 아래 입력이 "관리자 승인 대기"로 잠긴다. */}
        {awaitingApproval && approvalCanResolve && (
          <div
            style={{
              maxWidth: 680, margin: '0 auto 8px', display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 14px', border: '1px solid var(--color-border)', borderRadius: 10,
              background: 'var(--gray-2)',
            }}
          >
            <Icon name={approvalKind === 'self' ? 'user' : 'lock'} size={14} style={{ color: 'var(--color-text-secondary)' }} />
            <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: 'var(--color-text-secondary)' }}>
              {approvalKind === 'self' ? '본인 승인' : '관리자 승인'} 대기 — 이 도구 실행을 승인할까요?
            </span>
            <Button size="small" danger icon={<Icon name="close" />} loading={resolving === 'reject'} disabled={!!resolving} onClick={() => doResolve('reject')}>
              거부
            </Button>
            <Button size="small" type="primary" icon={<Icon name="check" />} loading={resolving === 'approve'} disabled={!!resolving} onClick={() => doResolve('approve')}>
              승인 및 재개
            </Button>
          </div>
        )}
        {/* 산출물형 폼(스펙 188) — 폼으로 고르거나 아래 입력으로 말해도 된다(이중 입력, 입력 안 잠금). */}
        {pendingForm && !streaming && (
          <InlineFormPanel
            key={pendingForm.formId}
            form={pendingForm.form}
            onSubmit={(v) => void onSubmitForm?.(v)}
          />
        )}
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
            placeholder={
              awaitingApproval
                ? approvalCanResolve
                  ? '위 승인/거부를 선택하세요'
                  : '승인 대기 중 — 관리자 승인 후 이어서 입력하세요'
                : `${agent.name}에게 메시지…`
            }
            loading={streaming}
            disabled={awaitingApproval}
            onSubmit={(text) => {
              if (awaitingApproval) return // 승인 대기 중 입력 차단(스펙 179 P3)
              histRef.current = resetHist()
              setDraft('')
              onSend(text)
            }}
            onCancel={onStop}
            prefix={<Button type="text" icon={<Icon name="paper-clip" />} />}
            footer={() => (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>턴마다 실행 기록이 남습니다 · ↑ 이전 입력</span>
            )}
          />
        </div>
      </div>
    </div>
  )
}
